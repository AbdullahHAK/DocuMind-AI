# 12 · Interview guide

This guide is built from the code, not from the README. Use it to **understand**: for every answer, open the cited file in the atlas and check it yourself before an interview.

## Personal contribution honesty

- **What the repository shows:** the implementation, its tests, eval and red-team results, and a git history of 104 commits authored under your GitHub identity, 103 of which (all except the repository's "Initial commit") carry an AI co-author trailer (`Co-Authored-By: Claude …`).
- **What it does not prove:** who made each design decision or wrote each line. Don't claim sole authorship of design work. A truthful framing is: *"I built this with an AI pair-programmer; I directed the scope, ran and interpreted the evaluations and security tests, and I can explain and modify every part."* Make sure the last part is true by working through the exercises below.
- **What still needs your own investigation:** the open questions in report 13, especially the 65-minute hang and the two prompt-only security regressions.

## 30-second explanation

"It's a RAG app that answers questions about a US health insurance policy. You upload your plan or use a sample, ask 'is an MRI covered?', and get a verdict with the exact clause and page, verified against the PDF text, plus the federal rules that apply and a cost estimate computed in code. It's built to refuse rather than guess, and I measured that: 100% retrieval hit rate on a 34-question eval, and quote verification that catches made-up citations."

## Two-minute technical explanation

"The backend is one FastAPI process. On upload, pypdf extracts text per page; a scanner strips any lines that look like instructions to an AI; a section-aware chunker keeps each clause with its heading and page; and a regex pass links cross-references like 'see 7.5' into a small clause graph. Each chunk gets a dense bge-small vector and a BM25 sparse vector in Qdrant.

On a question, I expand lay terms ('nose job' becomes 'cosmetic surgery'), run hybrid search with reciprocal-rank fusion, rerank with a cross-encoder, and apply a relevance gate: if nothing scores above a threshold calibrated on the eval, I answer 'not found' without calling the LLM. Otherwise I follow one hop of cross-references and send tagged excerpts to Gemini with a strict JSON schema. The server verifies every quote, strips markup and unknown contact details, downgrades contradictions to 'unclear', computes costs in Python, and streams it all to React over Server-Sent Events, including a trace of each stage."

## Five-to-ten-minute walkthrough (follow along in the atlas)

1. **System overview view:** the context diagram. Everything is in one process except the LLM.
2. **Components view:** show the HTTP layer, composition root (`build_services` is the only wiring point), ingestion, retrieval, answering, security.
3. **Execution flows → "Ask a question"**: walk the 19 steps. Stress *where* validation happens (before the stream starts, because after that the HTTP status is fixed at 200).
4. **Data model view:** one Qdrant collection (two vectors per point, `doc_id` filter = tenant isolation, `refs` = graph edges, deterministic ids = idempotent re-indexing) and JSON records on disk. There's no SQL database, and say why that's fine for this scale.
5. **Security view:** the red-team table. Lead with the honest lesson: code-level guards held; prompt-only guards regressed after later prompt edits.
6. **Performance view:** measured stage timings; the reranker is the CPU bottleneck; what I'd change first (the LLM deadline, then caching).

## A request, verbally, from click to response

"The Chat component calls `askQuestion`, which POSTs to `/api/ask`. FastAPI validates the body with `AskRequest`. The handler validates the doc id against a strict regex, loads the JSON record, and checks the per-IP sliding-window limiter. Then it returns a StreamingResponse over a generator. The generator emits a status event, calls `Retriever.retrieve`: query embedding, two Qdrant hybrid queries filtered by doc_id, cross-encoder rerank, the gate, then the graph hop. It emits the sources. It spends one unit of the daily budget, then calls `AnswerService.answer`, which builds the tagged prompt and calls `GeminiLLM.generate`; that tries each model in the chain until one returns schema-valid JSON. Back in the service: verify quotes, apply guards, compute cost, build the trace. The generator emits the answer, then done. In the browser, `dispatch` parses each SSE block and React renders the AnswerCard."

## Questions and answers

### Beginner

**Q: What is RAG and why use it here?** Retrieve relevant passages, then generate from them. The model doesn't know *your* policy, and insurance answers must be traceable to a clause. (`retrieval.py`, `answering.py`)

**Q: What's an embedding? Why two per chunk?** A vector where similar meaning means nearby vectors. Dense (bge-small) catches meaning ("dentist" ≈ "dental"); BM25 sparse catches exact tokens ("7.3(b)", "semaglutide"). RRF merges both rankings by position. (`vectorstore.hybrid_search`)

**Q: Where are user documents stored?** PDF and JSON record in `backend/storage/uploads/<uuid>.*`; chunks in Qdrant filtered by `doc_id`. Deleted after 24 h, lazily. (`documents.py`, report 05)

**Q: How does the frontend get partial results?** Server-Sent Events: `status`, `sources`, `answer`/`error`, `done`. It's parsed manually because `EventSource` can't POST. (`api.ts` `dispatch`)

### Intermediate

**Q: Why rerank if you already have hybrid search?** Bi-encoder retrieval compares independently computed vectors; a cross-encoder reads question and chunk together, which is more precise but slower, so it runs only on 12+6 candidates. Measured: it's ~1.5 s of the latency. (`Retriever._rerank`)

**Q: How did you pick the gate threshold of -6?** A sweep in `run_retrieval_eval.py`: the lowest in-scope best score was about -3.5, off-topic questions scored around -8 to -11, and -6 keeps 30/30 in-scope and blocks 3/4 off-topic. The 4th mentions the insurer's name; the LLM then answers `not_in_policy`.

**Q: How do you stop hallucinated citations?** Quotes must match the cited excerpt (normalized substring, or ≥ 90% fuzzy over a same-length word window); unmatched quotes are dropped; a coverage verdict with no surviving quote becomes `unclear`. 0 unverified quotes across the recorded eval runs. (`verification.py`)

**Q: Why compute costs in Python?** LLMs are unreliable at multi-step arithmetic; US cost-sharing has a fixed order (deductible → copay/coinsurance → out-of-pocket cap) that's easy to unit-test. Tests reproduce the policy's own examples ($12,700 birth → $5,910). (`costs.py`)

**Q: Is this GraphRAG?** A narrow version: edges come from explicit cross-references via regex, not LLM extraction. Measured honestly: no gain at the default top_k=6 on the 14-page sample; +1/8 multi-hop when context is tight. Kept because its cost is one lookup by id. (`graph.py`, `run_graph_eval.py`)

### Advanced

**Q: Walk me through your prompt-injection defenses and what broke.** Ingestion scanner (removes instruction-like lines before indexing), escaped and fenced excerpts with a closing reminder, schema-only output, then code-level output guards. The red-team suite (11 attacks, 3 trials, live model) found a contradictory-rider attack succeeding 3/3, which I fixed with conflict detection. Re-running showed an HTML payload regression (2/3), fixed with code-level markup stripping. The final run shows two prompt-only defenses regressed after unrelated prompt edits: off-task abuse 3/3, rider 1/3. The lesson: anything that matters must be enforced in code and regression-tested. (report 07)

**Q: What happens if Gemini is down?** The adapter tries each model in the chain; when all fail you get `LLMError`, an SSE `error` event, and a Retry button. But one recorded request took 65 minutes despite a 30 s timeout. I'd add an overall wall-clock deadline across the chain and investigate the SDK's timeout semantics. (`llm.py`, report 13)

**Q: How would you scale to 100× traffic?** Measure first: the bottlenecks are CPU reranking and LLM latency/quota. Cheap steps: cache answers for repeated questions, make the LLM wait non-blocking, reduce reranker cost. Before more than one process: `QDRANT_URL` (already supported), shared upload storage, Redis-backed limits. No microservices needed. (report 09)

**Q: What's the tenancy model?** None: anonymous, with per-document filters in every query. A doc id is a 122-bit capability. For real users I'd add accounts or signed URLs and an owner check in `_get_document`. (report 07)

**Q: How do you know a prompt change didn't make things worse?** The answer eval scores verdict accuracy, citation pages, off-topic handling and unverified quotes. Single runs vary 82-97%, so I'd run each question several times and compare distributions; I haven't done that yet.

## Defend the design (short form)

For each decision in report 11 you should be able to say: what it does (cite the function), one alternative, the trade-off, and the measurement that supports it, where one exists. If asked *why* it was chosen originally, answer from the recorded evidence (commit messages, docstrings, eval results) and don't invent motives.

## Debugging exercises

| Scenario | Investigation path | Files | Likely causes | Verify by |
|---|---|---|---|---|
| A correct clause is missing from the answer | open "Under the hood": did the gate pass? which sources were sent? | `retrieval.py`, `query_expansion.py` | vocabulary gap; candidates too few; chunk split badly | add the question to `eval/questions.json`, run `run_retrieval_eval.py` |
| Answer says "covered" but the quote is wrong | check `trace.verification` (quotes proposed vs verified) | `verification.py`, `answering.py` | fuzzy match too lenient; the quote exists but is out of context | unit test in `test_verification.py` with the exact text |
| Questions suddenly slow | compare `search_ms`, `rerank_ms`, `llm.ms` in traces | `embeddings.py`, `llm.py` | CPU contention (rerank); provider overload; model fallbacks (`fallbacks_used`) | profile like report 09; check logs for "trying next model" |
| LLM call hangs | logs for `llm=` lines and warnings | `llm.py` `build_llm` / `GeminiLLM.generate` | SDK timeout not applied as expected; retry backoff | reproduce with a fake server that sleeps; add a deadline |
| Upload returns 500 | server log stack trace | `api.upload_document`, `indexer.py` | pypdf exception type not wrapped in `PdfLoadError`; embedding OOM | upload the file in a test with the fake embedder |
| Rate limit not triggering behind a proxy | log `client_ip(request)` | `api.client_ip`, Dockerfile CMD | `X-Forwarded-For` trust settings | request with a forged header |
| Dependency update breaks answers | CI tests pass but eval drops | `llm.py` (SDK shapes), `requirements.txt` pins | provider SDK changes (e.g. response fields) | `run_answer_eval.py --limit 5` |
| Uploaded document still readable after 24 h | check `created_at` vs now | `services.delete_expired_uploads`, `documents.expired` | cleanup only runs on upload/startup | test with a back-dated record |
| Service restarted and uploads vanished | storage location | `config.storage_dir`, Dockerfile | container filesystem not persisted | mount a volume or use `QDRANT_URL` |

## Exercises to prove you understand (do these before interviews)

1. Change `GATE_THRESHOLD` to -3 and re-run `run_retrieval_eval.py`. Explain the new sweep row.
2. Add a lay term (e.g. "eye doctor" → "vision") with a test in `test_query_expansion.py`.
3. Write the fix for `sec:rider-headline` and a unit test in `test_answering.py`.
4. Add an overall deadline to `GeminiLLM.generate` and a test with a fake client that sleeps.
5. Trace `test_upload_then_ask_about_it` line by line through `api.py` with the atlas open.
