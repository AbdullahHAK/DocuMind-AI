# 02 · Architecture

All paths are relative to the repository root. Line ranges come from the generated atlas data (commit shown in the viewer's header).

## Level B: components

| Component | Responsibility | Runtime | Key files |
|---|---|---|---|
| React SPA | Chat UI, upload, answer/trace rendering, SSE client | Browser | `frontend/src/api.ts`, `components/Chat.tsx`, `components/AnswerCard.tsx` |
| HTTP API layer | Routes, validation, limits, SSE, static mount, CORS | uvicorn process | `backend/app/api.py`, `backend/app/main.py` |
| Composition root & settings | Builds the `Services` container; startup indexing; env config | in-process | `backend/app/services.py`, `backend/app/config.py` |
| Ingestion & clause graph | PDF/Markdown → sanitized chunks → edges → vectors | in-process, sync | `indexer.py`, `ingest/*.py`, `graph.py` |
| Retrieval pipeline | Expansion → hybrid search → rerank → gate → graph hop | in-process, CPU | `retrieval.py`, `vectorstore.py`, `embeddings.py`, `query_expansion.py` |
| Answering & verification | Prompt, LLM call, verification, guards, cost math, plan facts | in-process, blocks on LLM | `answering.py`, `prompts.py`, `verification.py`, `costs.py`, `plan_facts.py`, `schemas.py` |
| LLM adapter | `StructuredLLM` protocol; Gemini (model chain) & Anthropic | in-process client | `llm.py` |
| Security guards & limits | Injection scanner, output guards, fact grounding, rate limits, safe ids | in-process | `security.py`, `ratelimit.py`, `documents.py` |
| Document registry | JSON + PDF per document on disk | `backend/storage/uploads` | `documents.py` |
| Qdrant | Vectors + payload; filtered hybrid queries | embedded on disk (or `QDRANT_URL`) | `vectorstore.py` |
| ONNX models | Dense, BM25, cross-encoder | process memory, `.cache/models` | `embeddings.py` |
| Bundled knowledge | Federal rules Markdown, sample policy | `backend/data` | `data/federal/*.md`, `data/samples/*` |

## Connections (directed)

| From → To | Type | Evidence |
|---|---|---|
| SPA → API | HTTP (`fetch`; SSE for `/ask`) | `frontend/src/api.ts` `askQuestion` (51-74), `uploadDocument` |
| API → Services | function call via `request.app.state.services` | `api.py` `services` (36-37) |
| API → Retrieval | function call | `api.py` line with `svc.retriever.retrieve` in `ask` |
| API → Answering | function call | `svc.answers.answer`, `extract_plan_facts(svc.llm, …)` in `api.py` |
| API → Ingestion | function call on upload | `index_policy_pdf(svc.store, …)` in `upload_document` (94-137) |
| Ingestion → Security | function call | `indexer.load_policy_pages` (69-88) → `strip_injection` |
| Ingestion → Qdrant | write (delete + upsert) | `indexer._replace`, `VectorStore.upsert` |
| Retrieval → Qdrant | read (`query_points` with RRF; `retrieve` by id) | `VectorStore.hybrid_search` (91-111), `get_chunks` |
| Retrieval / Ingestion → ONNX models | function call | `Embedder.embed_query`, `embed_documents`, `rerank` (66-70) |
| Answering → LLM adapter | function call | `AnswerService._call_llm`, `plan_facts.extract_plan_facts` (54-66) |
| LLM adapter → Gemini / Anthropic | external HTTPS | `GeminiLLM.generate` (62-106), `AnthropicLLM.generate` |
| API → SPA | static files | `main.create_app` mounts `frontend/dist` when present |

Statuses are shown per edge in the **Components** view (dashed = partial / inferred).

## Level C: subsystems

### HTTP layer (`backend/app/api.py`, `main.py`)

- `create_app(services=None, warm_up=True)` (main.py 26-47): lifespan builds services, runs `startup()`, warms models; adds CORS (`CORS_ORIGINS`, default `http://localhost:5173`, GET/POST, `Content-Type` only); includes the router; mounts the SPA. The module-level `app = create_app()` is what uvicorn imports.
- Handlers are **sync `def`**, so FastAPI runs them in the AnyIO thread pool. `ask` returns a `StreamingResponse` over a *sync generator*, which Starlette iterates in the thread pool too.
- Validation lives in three places: Pydantic (`AskRequest`, `UploadFile`), explicit checks in the handler (size, magic bytes, `validate_doc_id`), and `DocumentRegistry.get` (returns `None` for invalid ids).
- Error handling: `HTTPException` before streaming starts; inside the stream, `AnswerError` → `event: error` with its message; anything else → generic message + `log.exception`.

### Composition root (`services.py`, `config.py`)

- `Settings` (config.py 15-86) has 36 fields; pydantic-settings reads each from an upper-case env var or `backend/.env`. See the Deployment view for the full table (secret defaults are hidden).
- `build_services(settings, qdrant=None, embedder=None, llm=None)` (86-103) is the **only place dependencies are wired**. Tests and the red-team/eval harnesses inject fakes or in-memory Qdrant here, so routes run unchanged.
- `Services` holds two `SlidingWindowLimiter`s (questions, uploads; window 3600 s) and one `DailyBudget`.

### Ingestion (`indexer.py`, `ingest/`, `graph.py`)

1. `load_pdf` (pypdf) → pages with `clean_text` (NFKC, soft hyphens, rejoin hyphenated words, strip "Page N" footers). Too little text → `PdfLoadError` (scanned PDF).
2. `load_policy_pages` enforces `MAX_DOCUMENT_CHARS` and runs `strip_injection` on every page (the sanitized text is all later steps ever see).
3. `chunk_pages` (chunker.py 97-163): section-aware (major `SECTION n`, minor `7.3 Title`), never crosses a page, packs to `CHUNK_MAX_CHARS` with `CHUNK_OVERLAP_CHARS` overlap, drops heading-only chunks.
4. `link_chunks` (graph.py 62-86): regex cross-references → `chunk.extra["refs"]` (≤4 per chunk, ≤2 target chunks per referenced clause).
5. `_stamp` with a content hash that includes `PIPELINE_VERSION`, then `_replace` = delete by `doc_id` + upsert.

### Retrieval (`retrieval.py`)

`Retriever.retrieve` (81-110): `expand_query` → two `hybrid_search` calls (policy for this `doc_id`, limit 12; federal, limit 6) → `_rerank` each with the cross-encoder → **gate** (`best < GATE_THRESHOLD` → empty result) → top `POLICY_TOP_K` (6) policy chunks → `_follow_references` adds ≤ `GRAPH_MAX_LINKED` (3) referenced chunks with `score=nan` and `linked_from` → federal chunks must clear `FEDERAL_MIN_SCORE` (-2.0), top 3.

### Answering (`answering.py`, `prompts.py`, `verification.py`, `costs.py`)

`AnswerService.answer` (85-142): fallback if nothing retrieved → `_call_llm` with `LLMAnswer` schema → `verify_citations` (quote must match the cited excerpt; evidence-requiring verdict with no surviving quote → `unclear`) → conflict downgrade → `clean()` on every free-text field (`strip_markup`, then `redact_unsupported_contacts`) → `compute_cost` → `trace`.

### LLM adapter (`llm.py`)

- `StructuredLLM.generate(system, user, schema, max_tokens, effort, meta=None)`.
- `GeminiLLM` iterates `[GEMINI_MODEL, *GEMINI_FALLBACK_MODELS]`; codes 429/500/503/504 and *any* other exception move on to the next model; 401/403 → "not configured"; other API errors → "rephrase". `_parse` maps finish reasons and validates JSON with Pydantic.
- `AnthropicLLM` uses `client.beta.messages.parse(... output_format=schema, fallbacks="default")`.
- `build_llm` sets Gemini `HttpOptions(timeout=LLM_TIMEOUT_SECONDS*1000, retry attempts=2)`.

## Dependency direction and coupling

- Direction is mostly clean: `api` → (`services`, `retrieval`, `answering`, `indexer`, `security`, `documents`) → (`vectorstore`, `embeddings`, `llm`, `models`, `config`). Nothing in `app/` imports `api`.
- **Cross-layer import:** `prompts.py` imports `RetrievalResult`/`ScoredChunk` from `retrieval.py`, and `answering.py` imports `prompts`, so answering depends on retrieval's data classes. Acceptable, but it means changing `ScoredChunk` touches three modules.
- `retrieval.py` imports `FEDERAL_DOC_ID` from `indexer.py` (a constant shared across layers).
- No circular imports: a cycle search over the generated import graph found none among `backend/app` modules.
- Most-imported modules (number of importing files across app, tests, eval and red-team): `config.py` 16, `models.py` 12, `retrieval.py` 10, `ingest/pdf.py` 8, `llm.py` 7, `security.py` 6. A change to these has the widest blast radius; see "Imported by" in each file's detail panel.

## Level D: code-level navigation

Use **Modules & files**: pick a scope, click a file, then **Expand symbols of selected file** to see its functions and the inferred call edges. Calls through injected objects (`svc.retriever.retrieve`, `self.llm.generate`, `self.store.hybrid_search`) are *not* resolvable statically; they're traced in the **Execution flows** view with evidence instead.
