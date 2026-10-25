"""HTTP endpoints.

GET  /api/health                     liveness + whether the LLM is configured
GET  /api/documents/{doc_id}         document metadata + extracted plan facts
GET  /api/documents/{doc_id}/file    the PDF itself (citations link to #page=N)
POST /api/documents                  upload and index a policy PDF
POST /api/ask                        ask a question; streams Server-Sent Events
"""

import json
import logging
import re
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from app.answering import AnswerError, fallback_answer
from app.documents import DocumentRecord, InvalidDocumentId, validate_doc_id
from app.indexer import index_policy_pdf
from app.ingest.pdf import PdfLoadError
from app.plan_facts import extract_plan_facts
from app.security import ground_plan_facts
from app.prompts import source_ids
from app.retrieval import RetrievalResult
from app.schemas import AskRequest, SourcePreview
from app.services import Services

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


def services(request: Request) -> Services:
    return request.app.state.services


def client_ip(request: Request) -> str:
    if services(request).settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _rate_limited(retry_after: int, what: str) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": f"Too many {what}. Please try again in {max(1, retry_after // 60)} minute(s)."},
        headers={"Retry-After": str(retry_after)},
    )


def _get_document(svc: Services, doc_id: str) -> DocumentRecord:
    record = svc.registry.get(doc_id)
    if record is None:
        raise HTTPException(404, "Document not found. It may have expired - please upload it again.")
    return record


@router.get("/health")
def health(request: Request) -> dict:
    svc = services(request)
    provider = svc.llm.name.split(":", 1)[0] if svc.llm else None  # "gemini" | "anthropic" | None
    return {
        "status": "ok",
        "llm_configured": svc.llm_configured,
        "llm_provider": provider,
        # shown in the upload box so users know the limits before they try
        "limits": {"max_upload_mb": svc.settings.max_upload_mb, "max_upload_pages": svc.settings.max_upload_pages},
    }


@router.get("/documents/{doc_id}")
def get_document(doc_id: str, request: Request) -> dict:
    return _get_document(services(request), doc_id).public()


@router.get("/documents/{doc_id}/file")
def get_document_file(doc_id: str, request: Request) -> FileResponse:
    record = _get_document(services(request), doc_id)
    return FileResponse(
        record.pdf_path,
        media_type="application/pdf",
        filename=record.filename,
        content_disposition_type="inline",  # open in the browser's PDF viewer
    )


def _safe_title(filename: str | None) -> str:
    stem = Path(filename or "policy.pdf").stem
    stem = re.sub(r"[_\-]+", " ", stem)
    stem = re.sub(r"[^\w .,()&']", "", stem).strip()
    return (stem or "My policy")[:80]


@router.post("/documents", status_code=201)
def upload_document(request: Request, file: UploadFile = File(...)):
    svc = services(request)
    allowed, retry_after = svc.upload_limiter.check(client_ip(request))
    if not allowed:
        return _rate_limited(retry_after, "uploads")

    max_bytes = svc.settings.max_upload_mb * 1024 * 1024
    data = file.file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(413, f"File is too large. The limit is {svc.settings.max_upload_mb} MB.")
    if not data.startswith(b"%PDF-"):  # check the bytes, not the (user-controlled) filename or content type
        raise HTTPException(415, "Please upload a PDF file.")

    svc.delete_expired_uploads()
    doc_id = uuid.uuid4().hex
    pdf_path = svc.registry.pdf_path(doc_id)
    pdf_path.write_bytes(data)
    title = _safe_title(file.filename)

    try:
        indexed = index_policy_pdf(svc.store, pdf_path, doc_id=doc_id, title=title, settings=svc.settings)
    except PdfLoadError as exc:
        pdf_path.unlink(missing_ok=True)
        raise HTTPException(422, str(exc)) from exc

    facts = None
    # the extraction is an LLM call, so it spends from the same daily budget as questions
    if svc.llm is not None and svc.daily_budget.try_spend():
        facts = extract_plan_facts(svc.llm, indexed.pages)
        # every number must literally appear in the (sanitized) document text
        facts, dropped = ground_plan_facts(facts, "\n".join(p.text for p in indexed.pages))
        if dropped:
            log.warning("Dropped ungrounded plan facts for %s: %s", doc_id, dropped)
    if facts and facts.get("plan_name"):
        title = str(facts["plan_name"])[:80]

    record = DocumentRecord(
        doc_id=doc_id, title=title, filename=f"{title}.pdf", pdf_path=str(pdf_path),
        pages=len(indexed.pages), chunks=indexed.chunks, facts=facts,
        security_flags=[{"rule": f.rule, "text": f.line[:200]} for f in indexed.injection_findings],
    )
    svc.registry.save(record)
    log.info("Indexed upload %s: %d pages, %d chunks", doc_id, len(indexed.pages), indexed.chunks)
    return record.public()


def sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _source_previews(retrieval: RetrievalResult) -> list[dict]:
    policy, federal = source_ids(retrieval)
    sid_of = {sc.chunk.chunk_id: sid for sid, sc in policy.items()}
    previews = []
    for sid, sc in [*policy.items(), *federal.items()]:
        c = sc.chunk
        previews.append(
            SourcePreview(
                source_id=sid, kind=c.kind, page=c.page, section=c.section, title=c.source_title,
                url=c.source_url, text=c.text,
                score=None if sc.linked_from else round(sc.score, 2),
                linked_from=sid_of.get(sc.linked_from),
            ).model_dump()
        )
    return previews


@router.post("/ask")
def ask(body: AskRequest, request: Request):
    svc = services(request)
    try:
        validate_doc_id(body.doc_id)
    except InvalidDocumentId as exc:
        raise HTTPException(404, "Document not found.") from exc
    record = _get_document(svc, body.doc_id)

    allowed, retry_after = svc.question_limiter.check(client_ip(request))
    if not allowed:
        return _rate_limited(retry_after, "questions")

    question = body.question.strip()

    def retrieval_trace(retrieval: RetrievalResult) -> dict:
        best = max([s for s in (retrieval.best_policy_score, retrieval.best_federal_score) if s is not None], default=None)
        return {
            "query": {"expanded": retrieval.search_query != question, "search_query": retrieval.search_query},
            "retrieval": {
                "candidates": retrieval.candidates,
                "search_ms": round(retrieval.search_ms),
                "rerank_ms": round(retrieval.rerank_ms),
                "policy_chunks": sum(1 for sc in retrieval.policy if sc.linked_from is None),
                "federal_chunks": len(retrieval.federal),
            },
            "gate": {"passed": retrieval.gate_passed, "best_score": None if best is None else round(best, 2),
                     "threshold": svc.settings.gate_threshold},
            "graph": {"linked_clauses": [sc.chunk.section for sc in retrieval.policy if sc.linked_from]},
            "security": {"document_lines_removed": len(record.security_flags)},
        }

    def answer_events() -> Iterator[str]:
        started = time.perf_counter()
        yield sse("status", {"stage": "searching", "message": "Searching your policy..."})
        retrieval = svc.retriever.retrieve(question, body.doc_id)
        yield sse("sources", _source_previews(retrieval))
        trace = retrieval_trace(retrieval)

        if not retrieval.found_anything:
            answer = fallback_answer()  # relevance gate: no LLM call
            answer.trace = {**trace, "llm": None, "total_ms": round((time.perf_counter() - started) * 1000)}
            yield sse("answer", answer.model_dump())
            return
        if svc.answers is None:
            yield sse("error", {"message": "The AI service isn't configured on this server yet."})
            return
        if not svc.daily_budget.try_spend():
            yield sse("error", {"message": "This demo has reached its daily question limit. Please come back tomorrow."})
            return
        yield sse("status", {"stage": "answering", "message": "Reading the relevant sections..."})
        answer = svc.answers.answer(question, retrieval, record.facts)
        if record.security_flags:
            answer.warnings.append(
                f"This document contained {len(record.security_flags)} line(s) that looked like instructions "
                "to an AI system rather than policy text. They were removed and ignored."
            )
        answer.trace = {**trace, **answer.trace, "total_ms": round((time.perf_counter() - started) * 1000)}
        yield sse("answer", answer.model_dump())

    def events() -> Iterator[str]:
        try:
            yield from answer_events()
        except AnswerError as exc:
            yield sse("error", {"message": str(exc)})
        except Exception:
            log.exception("Unexpected error while answering")
            yield sse("error", {"message": "Something went wrong on our side. Please try again."})
        # not in a `finally`: yielding there would break when the client disconnects
        yield sse("done", {})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},  # don't let proxies buffer the stream
    )
