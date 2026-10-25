# 11 · Architecture decisions and trade-offs

Each entry says what the implementation **does** (verified in code), the alternatives, and the trade-offs. Motivations are not recorded in code. Where commit messages or comments state a reason, that's cited; otherwise none is invented.

| # | Decision | What the code does | Alternatives | Trade-offs | Stated reason in repo |
|---|---|---|---|---|---|
| 1 | Local ONNX models | `Embedder` loads bge-small (dense), Qdrant/bm25 (sparse), ms-marco-MiniLM (cross-encoder) via fastembed | hosted embeddings API; sentence-transformers/PyTorch | no key/cost, offline tests ↔ ~200 MB models, CPU latency, bigger image | module docstring in `embeddings.py`; commit "Add local dense, BM25 and cross-encoder models via fastembed" |
| 2 | Qdrant, embedded by default | one collection with named dense + sparse vectors; RRF fusion inside `query_points`; `QDRANT_URL` switches to a server | pgvector + tsvector; Chroma; FAISS + rank_bm25; Meilisearch for keywords | hybrid in one query, same client for tests/dev/prod ↔ embedded mode is single-process | `vectorstore.py` docstring |
| 3 | Section-aware chunking | headings start chunks; never cross pages; overlap on size splits | fixed-size windows; semantic chunking | citations always have one page and section ↔ heuristics tied to numbered-section layouts | `chunker.py` docstring; regression tests for three parsing bugs |
| 4 | Lay-term query expansion | regex dictionary appends insurance terms | LLM query rewriting; HyDE | free, deterministic, testable ↔ manual maintenance | `query_expansion.py` docstring; retrieval eval 97% → 100% hit@6 (commit message) |
| 5 | Single relevance gate | skip the LLM if the best rerank score < -6 | per-chunk cutoff; no gate | cheap refusal of clearly off-topic questions ↔ borderline questions rely on the LLM's `not_in_policy` | `retrieval.py` docstring; threshold sweep in `run_retrieval_eval.py` |
| 6 | Regex clause graph | `link_chunks` stores `refs` on payloads; one hop after rerank | LLM-built knowledge graph (GraphRAG); no graph | free and exact ↔ explicit references only; measured gain only with tight context (6/8 → 7/8 at top_k 2-4; 8/8 both ways at 6) | `graph.py` docstring; `run_graph_eval.py` |
| 7 | Schema-constrained output + verification | `LLMAnswer` JSON; quotes checked; verdict downgrades | free text; provider citation features | checkable, renderable fields ↔ must stay compatible with both providers' schema support | `schemas.py`, `verification.py` docstrings |
| 8 | Cost math in Python | LLM returns a `CostRule`; `estimate_cost` computes | LLM computes | exact and tested ↔ needs plan facts and a dollar amount | `costs.py` docstring |
| 9 | Provider layer, Gemini default with fallback chain | `StructuredLLM`; `GeminiLLM` over `[primary, *fallbacks]` | single SDK | free demo, swappable ↔ two adapters; free-tier overload | `llm.py` docstring; commit "Add LLM provider layer…" (503/504 observed) |
| 10 | Code-level security guards | scanner at ingestion; output guards after the LLM | prompt-only defenses | holds regardless of model behaviour ↔ regex coverage limits | `security.py` docstring; red-team results |
| 11 | SSE over POST | sync generator yields events; manual parser in the browser | single JSON response; WebSocket | progressive UX ↔ errors after the first byte can't use HTTP status codes | `api.py` comments; `api.ts` docstring |
| 12 | Everything synchronous | sync handlers, sync SDK calls, thread pool | async end to end; task queue | simple code ↔ threads blocked on LLM I/O; long uploads block a thread | none stated |
| 13 | One container for API + UI | `StaticFiles` mount when `frontend/dist` exists | separate static hosting | one URL, no prod CORS ↔ coupled scaling | `main.py` docstring |
| 14 | No authentication, 24 h expiry | anonymous; uuid4 ids; TTL cleanup | accounts; signed URLs | zero-friction demo ↔ no ownership; link = access | UI note in `DocumentPanel.tsx`; `documents.py` docstring (privacy) |
| 15 | Fakes in tests, real models only in evals | `FakeEmbedder`, fake LLMs, `:memory:` Qdrant | real models in CI | fast, free, deterministic CI ↔ quality measured separately | `conftest.py` docstring |

## What would change the decisions

- More than one backend process → decision 2 (embedded Qdrant) and the process-memory limiters must change first.
- Real users with personal documents → decision 14 must change (authentication, encryption at rest, retention guarantees).
- Sustained concurrent load → decisions 1 and 12 (CPU reranker, synchronous LLM waits) become the bottleneck.
- Larger, cross-referencing documents → decision 6 is expected to matter more. That's untested: the only multi-hop eval uses the 14-page sample.
