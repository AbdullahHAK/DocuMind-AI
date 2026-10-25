# 13 · Open questions and uncertainties

Everything here is **unknown** or **inferred**. None of it should be stated as fact in an interview until it's investigated.

| # | Question | Status | Why it matters | How to investigate |
|---|---|---|---|---|
| 1 | Why did one `/ask` take **3,933.7 s** with `LLM_TIMEOUT_SECONDS=30`? | unknown | a single stuck request blocks a worker thread; a user waits indefinitely | read google-genai 2.33 `HttpOptions.timeout` / `HttpRetryOptions` semantics (per attempt? per read? does retry honour `Retry-After`?); reproduce against a local fake server that stalls or returns 503 with a long `Retry-After`; log timestamps per model attempt |
| 2 | Is embedded Qdrant safe under concurrent access from the AnyIO thread pool? | unknown | wrong results or errors under load | read qdrant-client local mode locking; run concurrent `/ask` requests in a test |
| 3 | Does uvicorn 0.54 with `--forwarded-allow-ips='*'` let clients spoof their IP? | inferred | per-IP limit bypass | send forged `X-Forwarded-For` to a container without a proxy and observe the limiter |
| 4 | Does the Docker image start without network access? | unknown | hosts with restricted egress; cold starts | `docker run --network none …` and watch startup logs (fastembed may call the Hugging Face Hub) |
| 5 | Does the Anthropic provider work end to end? | unknown | provider switch is advertised | `LLM_PROVIDER=anthropic` + key, run `eval/run_answer_eval.py --limit 5` |
| 6 | How much does the clause graph help on real (long) policies? | unknown | the only measurement uses a 14-page sample | build multi-hop questions for a real 100+ page Evidence of Coverage |
| 7 | How stable are answer-eval results? | partially known (82-97% across four single runs with different prompts) | can't tell regressions from noise | run each question 3-5× per configuration; report mean and spread |
| 8 | Why did the off-task and rider defenses regress after later prompt edits? | inferred: interaction with the added graph note / exception rule | prompt-only defenses are fragile | bisect prompt versions with the red-team suite (`--only off-task-abuse,conflicting-rider`) |
| 9 | Is the app deployed anywhere? | unknown (no evidence in the repo) | interview claims of "live" must be checked | check Hugging Face / host accounts |
| 10 | Are documents indexed by an older `PIPELINE_VERSION` present on any running instance? | unknown | old uploads lack `refs` and sanitization | inspect `storage/` on that instance (not done; the atlas never touches runtime data) |
| 11 | pypdf logs `incorrect startxref pointer` / `parsing for Object Streams` when reading PDFs during runs | observed, cause unknown | could indicate a malformed generated sample, or pypdf noise on reportlab output | open the sample with `pypdf.PdfReader(strict=True)` and check which file triggers it |
| 12 | Original design intent for decisions without stated reasons (e.g. fully synchronous handlers) | unknown | "why" questions in interviews | the repository can only show *what* was done; answer with trade-offs, not motives |

## Coverage limitations of this atlas

- **Static call graph:** call edges are resolved by name. Calls through injected objects (`svc.retriever.retrieve`, `self.llm.generate`, `self.store.hybrid_search`) are not edges in the code graph; the flows document them with evidence instead.
- **TypeScript analysis** is regex-based: top-level declarations, imports, JSX usage and `/api/` URLs. Functions defined *inside* components (`run`, `ask`, `retry` in `Chat.tsx`, `handleFile` in `DocumentPanel.tsx`) aren't separate symbols, so the flows cite them with line-matched evidence.
- **Generated and binary files** (lockfile, PDFs, result JSON) are inventoried but not analysed (report 14).
- **Runtime state** (`backend/storage`, `.cache`, `.env`) is deliberately not read.
- **Line numbers** are correct for the commit and working tree the atlas was generated from (shown in the viewer header). Re-run `tools/build_atlas.py` after code changes; it fails loudly if a curated reference no longer resolves.
