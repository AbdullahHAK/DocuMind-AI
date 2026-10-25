# 09 · Performance and scalability

## Where the time goes in one question (measured)

From a live trace of "Are GLP-1 drugs like semaglutide covered?" on a developer machine (8 cores, about 66% busy with other programs):

| Stage | Time | Bound by |
|---|---|---|
| Hybrid search (2 queries, 18 candidates) | 159 ms | CPU (query embedding) + in-process Qdrant |
| Cross-encoder rerank (18 pairs) | 1,481 ms | **CPU** |
| LLM (gemini-3.5-flash-lite, 1,507 in / 396 out tokens) | 4,295 ms | network + provider |
| **Total** | **5.9 s** | |

Before tuning, reranking 24 candidates took about 5 s on the same machine; `RETRIEVAL_CANDIDATES` was lowered to 12 with **identical** retrieval eval results (hit@6 100%, MRR 0.95, gate 30/30 + 3/4) at 24, 16 and 12.

## A. Current architecture: what it actually does

- **Synchronous everywhere:** sync handlers on the AnyIO thread pool (default 40 threads). Each `/ask` holds a thread for retrieval *and* the LLM wait; each upload holds one for parsing, embedding every chunk and a plan-facts LLM call.
- **CPU-heavy steps run inside requests:** query embedding, reranking, document embedding. They share the container's cores.
- **No caching:** identical questions recompute everything, including the LLM call.
- **In-process state:** embedded Qdrant, limiters and budget live in one process, so there can be exactly one worker.
- **External quotas:** the free-tier LLM has per-model rate limits and frequent 503/504s. The model chain absorbs some of this; `QUESTIONS_PER_DAY_GLOBAL` caps cost.
- **Memory:** about 800 MB with models loaded (measured in the container). `SlidingWindowLimiter._hits` keeps one key per client IP forever (tiny, but unbounded).
- **Data volume:** the sample is 52 chunks; uploads are capped at 150 pages and 1.5 M characters. Qdrant in embedded mode does brute-force-sized work at this scale, and payload indexes are ignored.

For a portfolio demo with a handful of concurrent users, **this is sufficient**. The limiting factors are reranker CPU and LLM latency/quota, not the database.

## B. First scaling stage: lowest-complexity changes

| Change | Bottleneck addressed | Trade-off | Trigger to do it |
|---|---|---|---|
| **Fix the LLM deadline** (an overall wall-clock budget across the model chain) | one stuck call blocked 65 min (`rel:llm-hang`) | small code change | now: this is a reliability bug, not a scaling optimization |
| Answer cache keyed by (doc_id, normalized question, pipeline version) | repeated demo questions (suggested chips) pay for retrieval + LLM every time | invalidation when prompts or pipeline change (include versions in the key) | the same few questions dominate traffic |
| Run the LLM call with `async` / a bounded executor | threads blocked on network I/O | more complex code path | thread-pool saturation (requests queue while CPU idles) |
| Smaller / quantized reranker, or skip the federal rerank when the policy gate is decisive | ~1.5 s CPU per question | possible ranking quality loss: re-run `run_retrieval_eval.py` | p95 latency dominated by rerank under concurrent load |
| Background indexing for uploads (202 + polling) | long uploads hold a thread | job state and polling UI | uploads become common or > ~50 pages |
| Check expiry on read | stale documents readable | none | now (privacy) |

## C. Large-scale evolution (only if usage justifies it)

| Change | Needed when | Notes |
|---|---|---|
| `QDRANT_URL` (Qdrant server or cloud) | more than one process or replica, or large document volume | already supported by `create_client`; payload indexes start working |
| Shared upload storage (object store) + DB-backed registry | replicas | `DocumentRegistry` is the only file-based component to replace |
| Redis (or the edge provider's limiter) for rate limits and budget | replicas, or limits must survive restarts | `ratelimit.py` has a small interface to swap |
| Separate embedding/rerank service (GPU) | sustained concurrent load where CPU rerank dominates | adds a network hop and an ops burden |
| Paid LLM tier / provider with an SLA | quota or overload errors become user-visible regularly | cost |

**Not recommended without evidence:** Kubernetes, microservices, Kafka. Nothing in this workload (one request → one retrieval → one LLM call) needs them, and the measured bottlenecks are CPU rerank and the external LLM, which they don't address.

## Reliability notes

- **Idempotency:** re-indexing the same document is idempotent (deterministic point ids + delete-then-upsert). Retries of `/ask` are safe (read-only except counters). A retried upload creates a second document (new uuid).
- **Partial failures:** delete-then-upsert has no transaction; a failed upload leaves the PDF orphaned (`rel:partial-upload`).
- **Retries:** the Gemini SDK retries (attempts=2) and the adapter falls through the model chain. No retry for the Anthropic adapter beyond the SDK default.
- **Measurement noise:** four full answer-eval runs on the same 34 questions scored 82%, 97%, 91% and 88% exact verdicts (first prompt, then later prompt versions), so single runs can't separate small regressions from model randomness.
