# 10 · Testing and engineering quality

## Checks actually executed for this atlas

| Command | Result |
|---|---|
| `cd backend && .venv\Scripts\python -m pytest -q` | **142 passed** (119 test functions; parametrized cases make up the difference) |
| `cd frontend && npm run lint` | no problems reported |
| `cd frontend && npm run build` | built successfully (`tsc -b && vite build`) |
| `python docs/architecture-atlas/tools/build_atlas.py` | all evidence references and graph edges resolve; a deliberate negative test (3 broken references) was reported as 4 errors |

Not executed for this atlas (they cost LLM quota or were run earlier): `eval/run_answer_eval.py`, `redteam/run_redteam.py`. Their most recent recorded outputs are in `backend/eval/results/` and `backend/redteam/results/`.

## Test inventory (backend, pytest)

| Test file | Functions | Modules exercised (direct imports) | Kind |
|---|---|---|---|
| `test_api.py` | 17 | config, main, plan_facts, schemas, services (and through them every route) | integration: real FastAPI app, real indexing + Qdrant (in-memory), fake embedder + fake LLM |
| `test_llm.py` | 15 | config, llm | unit: Gemini/Anthropic adapters with fake SDK clients (fallback chain, timeouts, error mapping) |
| `test_security.py` | 13 (25 cases) | security, ingest/pdf | unit: injection scanner (payloads + no false positives on the real sample), contacts, markup, fact grounding |
| `test_chunker.py` | 11 | ingest/chunker, ingest/pdf | unit, includes regression tests for 3 real parsing bugs |
| `test_costs.py` | 9 | costs | unit: checked against the sample policy's own worked examples |
| `test_answering.py` | 8 | answering, config, llm, models, retrieval, schemas | unit with a fake LLM |
| `test_verification.py` | 8 | verification, models, retrieval, schemas | unit: exact / fuzzy / fabricated quotes |
| `test_query_expansion.py` | 5 | query_expansion | unit |
| `test_graph.py`, `test_markdown.py`, `test_prompts.py`, `test_retrieval.py`, `test_ratelimit.py`, `test_documents.py`, `test_vectorstore.py`, `test_indexer.py`, `test_plan_facts.py` | 2-4 each | see the Tests view | unit / small integration |

**Fixtures and fakes** (`tests/conftest.py`): `FakeEmbedder` (hashed bag-of-words dense vectors, token-count sparse vectors, word-overlap "reranker" shifted so no overlap scores negative) and a `store` fixture on `QdrantClient(":memory:")`. The fake LLMs in `test_api.py` / `test_answering.py` implement the `StructuredLLM` protocol directly.

**Design consequence:** tests are fast, offline and deterministic, and exercise the *real* Qdrant query path. They do **not** measure retrieval or answer quality; that's what the eval and red-team harnesses are for.

## Coverage of critical journeys

| Journey | Automated test? |
|---|---|
| Ask → stream → verified answer | yes (`test_ask_streams_status_sources_answer_done`) |
| Off-topic gate skips the LLM | yes (`test_off_topic_question_skips_llm`) |
| Upload → ask about the upload (no leakage from the sample) | yes (`test_upload_then_ask_about_it`) |
| Injection lines removed at upload, warning in answers | yes |
| Rate limits, daily budget (questions and uploads) | yes |
| Path traversal ids | yes |
| LLM failure → SSE error | partially (adapter error mapping is unit-tested; the API-level error event is tested only for "no LLM configured" and "budget") |
| Real PDF parsing on the sample | yes (`test_indexer.py`, `test_graph.py`, `test_security.py`) |
| Frontend (SSE parser, components) | **no tests** |
| Docker image build | not in CI (manually verified once) |
| Anthropic provider end to end | **no** (fakes only) |

## Engineering-quality observations

- **Consistent structure:** one responsibility per module, dependency injection through `build_services`, settings centralized in `Settings`.
- **Comment density:** modules start with a docstring explaining *why*. The generated catalog (report 03) shows them.
- **Dead or stale code candidates:**
  - `backend/scratch/01_hello_llm.py`: a learning script that calls Anthropic directly and isn't used by the app.
  - `IndexedPolicy.graph_edges` is computed but only logged.
  - `Settings.trust_proxy_headers` overlaps with uvicorn's `--proxy-headers` in the Docker CMD; two mechanisms for one concern.
- **Duplication:** two fake-LLM classes (`test_api.FakeLLM`, `test_answering.FakeLLM`) and similar fake SDK clients in `test_llm.py`; acceptable in tests.
- **Coupling:** `prompts.py` and `answering.py` depend on `retrieval.ScoredChunk` / `RetrievalResult`.
- **Documentation drift:** README says "90 tests" (now 142 cases); the root `SECURITY.md` draft (untracked) contradicts the final red-team run; `docs/HOW_IT_WORKS.md` predates the security, graph and trace work in places.
- **Eval methodology:** single run per question, with large run-to-run variance (82-97% across four runs).
- **CI gaps:** no Docker build, no frontend tests, no eval smoke (reasonable: evals cost quota).
