# 04 · Execution and data flows

Each flow below is also an interactive sequence diagram in the **Execution flows** view, where every step links to its source. Status labels: **verified** = every step read in code; **partial** = some behaviour observed at runtime contradicts or isn't explained by the code.

## 1. Application startup (verified)

1. `uvicorn app.main:app` imports `backend/app/main.py`; `logging.basicConfig(INFO)`; module-level `app = create_app()`.
2. `create_app` (26-47) registers `CORSMiddleware`, `router` (`/api`), and `StaticFiles("/")` **only if** `frontend/dist` exists (in Docker it does; in dev it usually doesn't, and Vite serves the UI).
3. **Lifespan** (runs before the first request): `build_services(get_settings())`:
   - `Embedder(settings)` (models are lazy `cached_property`s),
   - `VectorStore(create_client(settings))`: embedded `QdrantClient(path=storage/qdrant)` unless `QDRANT_URL`,
   - `build_llm(settings)`: Gemini if `GEMINI_API_KEY`, else Anthropic if `ANTHROPIC_API_KEY`, else `None`,
   - `DocumentRegistry(storage/uploads)`, `Retriever`, `AnswerService` (only if an LLM exists), limiters.
4. `Services.startup` (53-58): `ensure_collection` → `index_federal_corpus` (skipped if stored `version` and count match) → `_register_sample` (same, then rewrites the sample's JSON record) → `delete_expired_uploads`.
5. `Embedder.warm_up` loads all three models (first run downloads them).

**Failure behaviour:** an exception anywhere aborts startup. All of this runs synchronously inside the async lifespan, so the server only starts accepting connections once it's done.

## 2. Ask a question: typical successful journey (verified, the most important path)

| # | What happens | Where |
|---|---|---|
| 1 | User submits; `ask()` adds a loading turn, `run()` calls `askQuestion` with an `AbortController` | `Chat.tsx` (`Chat` 34-193) |
| 2 | `POST /api/ask {question, doc_id}`; `AskRequest` enforces 3-500 chars | `api.ts` `askQuestion` 51-74; `schemas.AskRequest` |
| 3 | `validate_doc_id` (404), `_get_document` (404), `question_limiter.check(client_ip)` (429 + `Retry-After`), all before streaming | `api.ask` 162-236 |
| 4 | Stream opens; `event: status` "Searching your policy…" | `answer_events` |
| 5 | `Retriever.retrieve`: `expand_query` → `embed_query` → 2× `hybrid_search` (Qdrant `query_points`, dense + sparse prefetch, RRF) → 2× `_rerank` | `retrieval.py` 81-110, `vectorstore.py` 91-111 |
| 6 | Gate: `best < -6` → empty result (see flow 3) | `retrieval.py` |
| 7 | Top 6 policy chunks + ≤3 cross-referenced chunks fetched by id (`get_chunks`) | `_follow_references` 67-79 |
| 8 | `event: sources` with every chunk the model will see (`linked_from` marks graph hops) | `_source_previews` |
| 9 | No LLM → `event: error`; daily budget exhausted → `event: error` | `answer_events` |
| 10 | `event: status` "Reading the relevant sections…"; `AnswerService.answer` | `answering.py` 85-142 |
| 11 | `build_user_message`: escaped `<excerpt id="P1" page=… section=… [referenced_by=…]>`, federal `F1…`, `<plan_facts>`, `<question>`, closing `<reminder>` | `prompts.py` 88-102 |
| 12 | `GeminiLLM.generate`: JSON mode + `response_json_schema=LLMAnswer`, thinking level from `LLM_EFFORT`; model chain on 429/5xx/exceptions | `llm.py` 62-106 |
| 13 | `_parse`: finish reason checks, `LLMAnswer.model_validate_json` | `llm.py` 108-124 |
| 14 | `verify_citations` → conflict downgrade → `clean()` every text field → `compute_cost` → `trace` | `answering.py`, `verification.py` 50-88 |
| 15 | API appends a warning if the document had flagged lines, merges the retrieval trace + `total_ms`; `event: answer`, `event: done` | `answer_events` |
| 16 | `dispatch()` routes events to handlers; `AnswerCard` + `TracePanel` render | `api.ts` 75-97 |

**Data read:** Qdrant points for `doc_id` and `federal`; the `DocumentRecord` JSON (for `facts`, `security_flags`). **Data written:** none (only limiter counters in memory).
**External call:** one LLM request (possibly several, one per model in the chain).
**Observability:** the `trace` dict and log lines `llm=gemini:<model> finish=… in=… out=…`.

## 3. Off-topic question: relevance gate (verified)

Same as steps 1-5. In `retrieve`, if the best reranked score of policy + federal candidates is below `GATE_THRESHOLD` the result is empty, `found_anything` is False, and `answer_events` sends `fallback_answer()` with `trace.llm = null`. **No LLM call and no budget spent.** The threshold of -6 comes from the sweep in `eval/run_retrieval_eval.py` (all 30 in-scope questions kept, 3 of 4 off-topic blocked; the fourth reaches the LLM, which answered `not_in_policy`).

## 4. Upload a policy: main write path (verified)

1. `DocumentPanel.handleFile` → `uploadDocument` (multipart `POST /api/documents`).
2. `upload_document` (94-137): upload limit (429) → read ≤ `MAX_UPLOAD_MB`+1 bytes (413) → `%PDF-` magic bytes (415) → `delete_expired_uploads()` → `doc_id = uuid4().hex` → write `storage/uploads/<id>.pdf`.
3. `index_policy_pdf`: `load_policy_pages` (page cap, char cap, `strip_injection`) → `chunk_pages` → `link_chunks` → `_stamp` → `_replace` (delete + upsert in batches of 64; **embeddings computed here, CPU-bound**). `PdfLoadError` → 422 and the PDF is deleted.
4. If an LLM exists **and** `daily_budget.try_spend()`: `extract_plan_facts(llm, sanitized_pages)` (one LLM call, effort `low`) → `ground_plan_facts` (drop numbers not literally in the text, drop deductible > OOP max).
5. Title = extracted `plan_name` if any, else a sanitized filename; save `DocumentRecord` (with `security_flags`) → `201` with `record.public()` (no `pdf_path`).
6. Frontend stores the id in `localStorage['amicovered:doc']`.

**Everything is synchronous**: the response arrives only after embedding and the LLM call. **Partial-failure gap:** only `PdfLoadError` is cleaned up; other exceptions leave the PDF (and maybe some points) behind (finding `rel:partial-upload`).

## 5. Open a cited page: representative read (verified)

`documentFileUrl(docId, page)` builds `/api/documents/{id}/file#page=N`; the browser navigates there. `get_document_file` (76-83) → `_get_document` → `FileResponse(record.pdf_path, inline)`. The path comes from server-written JSON, never from the request. No ownership check (finding `sec:no-auth`).

## 6. LLM overloaded: significant failure path (partially verified)

`GeminiLLM.generate` tries each model; on 429/500/503/504 or any exception it logs and moves on. When all models fail it raises `LLMError` ("busy" if the last error was 429, else "overloaded"). `events()` turns that into `event: error`; the UI shows the message with a **Try again** button (`retry()` in `Chat.tsx`).

**What the code does not explain:** in the final answer eval, one request took **3,933.7 seconds** before ending with "overloaded" (`backend/eval/results/answers-20261025-062139.json`, row `oop-max`). With `timeout=30 s`, 2 attempts and 3 models, the intended worst case is a few minutes. The cause is unknown (see report 13).

## 7. Authentication and authorization

**Does not exist.** There is no login, session, token, role or ownership check in the code. The atlas documents this instead of inventing a flow.

## 8. Background and asynchronous work

There are **no background workers, queues or schedulers**. "Asynchronous" behaviour in this codebase is:

- **SSE streaming:** status and sources reach the browser before the LLM finishes.
- **Expiry cleanup** piggybacks on startup and on each upload.
- **Thread-pool execution:** sync handlers and the sync SSE generator run in AnyIO worker threads.

## 9. Most technically distinctive feature: the answer-guard pipeline

Between the LLM and the user, the answer passes through four independent checks, all in code:

1. **Quote verification** (`verification.quote_matches`, 31-47): normalize (HTML entities, curly quotes, punctuation), require a substring match or ≥ 90% fuzzy match over a sliding window of the same word count; drop unmatched quotes; downgrade `covered` / `covered_with_conditions` / `not_covered` to `unclear` if no quote survives.
2. **Conflict downgrade:** a non-null `conflicting_provisions` adds a warning and downgrades to `unclear`.
3. **Markup stripping** (`security.strip_markup`).
4. **Contact allow-list** (`security.redact_unsupported_contacts`): phone numbers (compared by their last 10 digits) and URLs must appear in the excerpt text.

Everything changed is recorded in `trace.verification`, which the UI shows under "Under the hood".

## 10. Offline harnesses (verified)

- **Retrieval eval** (`eval/run_retrieval_eval.py`): builds an in-memory index of the sample + federal corpus and computes hit@6, MRR and the gate sweep. No LLM.
- **Graph eval** (`eval/run_graph_eval.py`): multi-hop recall with the graph on and off.
- **Answer eval** (`eval/run_answer_eval.py`): full pipeline with the live LLM; writes `eval/results/*.json`.
- **Red-team** (`redteam/run_redteam.py`): real upload + ask through `TestClient`, in-memory Qdrant and a temporary storage dir; writes `redteam/results/*.json`.
