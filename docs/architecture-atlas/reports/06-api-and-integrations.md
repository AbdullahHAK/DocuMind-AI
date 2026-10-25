# 06 · API and integrations

All endpoints are defined in `backend/app/api.py` on `APIRouter(prefix="/api")`. **None require authentication.** FastAPI also serves its auto-generated OpenAPI document at `/openapi.json` and Swagger UI at `/docs` (framework default; not disabled in `create_app`).

## Endpoints

### `GET /api/health` → 200
Handler `health` (64-67). Returns `{"status": "ok", "llm_configured": bool, "llm_provider": "gemini" | "anthropic" | null}`. The provider is derived from `llm.name`. Used by `App.tsx` to show a banner when no LLM is configured and to name the provider in the privacy note.

### `GET /api/documents/{doc_id}` → 200 | 404
Handler `get_document` (71-72). Returns `DocumentRecord.public()`: `doc_id, title, filename, pages, chunks, is_sample, facts, security_flags, created_at`. 404 "Document not found. It may have expired…" for unknown or invalid ids (invalid ids are rejected by `DocumentRegistry.get` without touching the filesystem). Caller: `fetchDocument` in `api.ts`.

### `GET /api/documents/{doc_id}/file` → 200 (application/pdf, inline) | 404
Handler `get_document_file` (76-83). `FileResponse(record.pdf_path, media_type="application/pdf", filename=record.filename, content_disposition_type="inline")`. Caller: links built by `documentFileUrl(docId, page)` (adds `#page=N`).

### `POST /api/documents` → 201 | 413 | 415 | 422 | 429
Handler `upload_document` (94-137). Multipart field `file`.

| Status | When |
|---|---|
| 429 | more than `UPLOADS_PER_IP_PER_HOUR` (6) from this client IP; `Retry-After` header |
| 413 | body larger than `MAX_UPLOAD_MB` (10) |
| 415 | bytes don't start with `%PDF-` (filename and content type are ignored) |
| 422 | `PdfLoadError`: encrypted, invalid, more than `MAX_UPLOAD_PAGES` (150), too much text (`MAX_DOCUMENT_CHARS`), or almost no text (scanned) |
| 201 | public record (as above) |

Side effects: PDF + JSON written; chunks upserted; one LLM call for plan facts if an LLM exists and the daily budget allows.

### `POST /api/ask` → 200 `text/event-stream` | 404 | 422 | 429
Handler `ask` (162-236). Body `AskRequest {question: str(3..500), doc_id: str(1..64)}`.

Before streaming: 422 (Pydantic validation), 404 (invalid or unknown doc_id), 429 (`QUESTIONS_PER_IP_PER_HOUR`, 30).

Stream (each event is `event: <name>\ndata: <json>\n\n`):

| Event | Payload | Sent when |
|---|---|---|
| `status` | `{stage: "searching" \| "answering", message}` | start; before the LLM call |
| `sources` | `SourcePreview[]`: `source_id, kind, page, section, title, url, text, score (null for graph-linked), linked_from` | after retrieval (may be `[]`) |
| `answer` | `Answer`: `verdict, headline, explanation, citations[], conditions[], exclusions[], federal[], questions_to_ask[], cost_estimate, warnings[], used_llm, trace{}` | success, or gate fallback |
| `error` | `{message}` | no LLM configured, daily budget exhausted, `LLMError`, unexpected exception |
| `done` | `{}` | always last (also after `error`) |

Response headers: `Cache-Control: no-cache`, `X-Accel-Buffering: no` (stop reverse proxies from buffering the stream).

**Contract caveat:** once streaming starts the HTTP status is always 200; clients must read `event: error`.

## Internal API client (`frontend/src/api.ts`)

| Function | Endpoint | Error handling |
|---|---|---|
| `fetchHealth` | GET /api/health | throws `ApiError` |
| `fetchDocument` | GET /api/documents/{id} | throws `ApiError` (message from `detail`) |
| `documentFileUrl` | builds /file URL | n/a (navigation) |
| `uploadDocument` | POST /api/documents | throws `ApiError` with server `detail` |
| `askQuestion` + `dispatch` | POST /api/ask | parses SSE manually (`fetch` + `TextDecoderStream`), because `EventSource` only supports GET |

## LLM interface (`backend/app/llm.py`)

`StructuredLLM.generate(*, system, user, schema, max_tokens, effort, meta=None) -> schema instance` or `LLMError`.

| Adapter | SDK call | Structured output | Failure mapping |
|---|---|---|---|
| `GeminiLLM` | `client.models.generate_content(model, contents=user, config)` per model in the chain | `response_mime_type="application/json"`, `response_json_schema=schema.model_json_schema()`; then `schema.model_validate_json` | 429/500/503/504/exception → next model; 401/403 → "not configured"; other → "rephrase"; finish SAFETY etc. → "can't help"; MAX_TOKENS → "incomplete"; invalid JSON → "unexpected format" |
| `AnthropicLLM` | `client.beta.messages.parse(... betas=["server-side-fallback-2026-07-01"], fallbacks="default", output_format=schema)` | SDK parse | typed SDK exceptions → user-safe messages; `stop_reason` refusal / max_tokens |

Schemas sent to the model: `LLMAnswer` (answers) and `PlanFacts` (uploads), both in `schemas.py` / `plan_facts.py`.

## Third-party integrations

| Integration | Purpose | Configuration | Verified at runtime? |
|---|---|---|---|
| Google Gemini (`google-genai` 2.33.0) | default LLM | `GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_FALLBACK_MODELS`, `LLM_TIMEOUT_SECONDS` | yes (all recorded eval/red-team runs) |
| Anthropic (`anthropic` 1.14.0) | optional LLM | `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `LLM_PROVIDER` | **no**, unit tests with fakes only |
| Qdrant (`qdrant-client` 1.19.1) | vector store | `QDRANT_URL`, `QDRANT_API_KEY`, `QDRANT_COLLECTION` | embedded mode yes; server mode not exercised |
| fastembed (bge-small, Qdrant/bm25, ms-marco-MiniLM) | embeddings + rerank | `DENSE_MODEL`, `SPARSE_MODEL`, `RERANK_MODEL`, `MODELS_CACHE_DIR` | yes |
| Hugging Face Hub | model file source | implicit (fastembed) | downloads yes; offline startup not tested |
| pypdf 6.20.1 | PDF text extraction | none | yes |

No webhooks, event schemas, payment systems or object storage exist.
