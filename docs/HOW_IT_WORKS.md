# How Am I Covered? works

This guide explains the whole system in plain language: what each part does, why it was built that way, what went wrong along the way, and how to talk about it in an interview. Read it top to bottom once, then use the codebase map to jump into the code.

---

## 1. The problem

A US health insurance policy is a 50-150 page legal document. People don't read it, then get surprised by a denied claim. Generic chatbots are dangerous here because they **sound** confident while inventing coverage rules. So the goal is narrow and strict:

> Answer coverage questions **only** from the person's own policy (plus well-known federal rules), show the exact clause and page, and say "I couldn't find it" instead of guessing.

That's **RAG: retrieval-augmented generation**. Instead of trusting what the language model memorized, we *retrieve* the relevant pages first and make the model *generate* an answer from them.

---

## 2. The big picture: two phases

**Phase 1: indexing (once per document).** Turn a PDF into small searchable pieces and store them.

```
PDF -> text per page -> chunks (with page + section) -> two vectors per chunk -> Qdrant
```

**Phase 2: answering (every question).** Find the right pieces, then let the LLM write an answer from them, then check that answer.

```
question -> expand words -> hybrid search -> rerank -> relevance gate
         -> Claude (structured output) -> verify quotes -> compute cost -> stream to browser
```

---

## 3. Phase 1 in detail: what happens when a PDF is uploaded

`POST /api/documents` in [backend/app/api.py](../backend/app/api.py)

1. **Safety checks.** Rate limit per IP, size limit (10 MB), and the first bytes must be `%PDF-`. We check the *bytes*, not the filename, because filenames are user-controlled.
2. **Save the file** under a random ID (`uuid4`). IDs are validated with a strict regex in [documents.py](../backend/app/documents.py), so a request can never use `../../` to read other files (path traversal).
3. **Extract text per page** with pypdf ([ingest/pdf.py](../backend/app/ingest/pdf.py)). We keep pages separate because page numbers are what make citations checkable. Cleanup: rejoin hyphenated words, collapse spaces, remove "Page 11" footers. If there's almost no text, the PDF is a scanned image, and we say so (no OCR).
4. **Chunk** ([ingest/chunker.py](../backend/app/ingest/chunker.py)). Policies are organized as numbered sections ("7.3 Dental and Vision"), so the chunker:
   - starts a new chunk at every heading, so a clause stays with its heading;
   - never crosses a page boundary, so every chunk has exactly one page number;
   - splits long sections at ~1,100 characters with ~150 characters of **overlap**, so a sentence cut at the edge still appears whole in one chunk;
   - records the section label, e.g. `SECTION 7 - EXCLUSIONS › 7.3 Dental and Vision`.
5. **Embed** ([embeddings.py](../backend/app/embeddings.py)). Each chunk gets **two** vectors (see §5):
   - a *dense* vector (384 numbers from `bge-small`) that captures meaning;
   - a *sparse* BM25 vector that captures exact words.

   The section label is prepended to the text before embedding, so a chunk that only says "Not covered." still "knows" it's about dental.
6. **Store** in Qdrant ([vectorstore.py](../backend/app/vectorstore.py)) with metadata: `doc_id`, page, section, kind (`policy` / `federal`).
7. **Extract plan facts** ([plan_facts.py](../backend/app/plan_facts.py)). One small LLM call reads the first pages and returns deductible, out-of-pocket maximum, copays, and so on as structured JSON. These fill the sidebar and feed the cost calculator.

The **federal rules** ([backend/data/federal/](../backend/data/federal/)) are hand-written Markdown summaries of healthcare.gov / CMS / DOL pages, chunked by `##` heading. At startup, [indexer.py](../backend/app/indexer.py) stamps chunks with a content hash and only re-embeds if the files changed. That makes indexing **idempotent**.

---

## 4. Phase 2 in detail: what happens when you ask a question

`POST /api/ask` in [api.py](../backend/app/api.py) returns a **stream** of events.

| Step | Code | What happens |
|---|---|---|
| 1 | `api.ask` | Validate the request (Pydantic), check the document exists, check the per-IP rate limit. |
| 2 | [query_expansion.py](../backend/app/query_expansion.py) | Add insurance terms for everyday words: "nose job" gets "cosmetic surgery", "Wegovy" gets "GLP-1 semaglutide". |
| 3 | `VectorStore.hybrid_search` | Two searches inside Qdrant (dense and BM25), restricted to *this* document, merged with **Reciprocal Rank Fusion**. Returns ~24 candidates. Run separately for the policy and for federal rules. |
| 4 | `Retriever._rerank` | A **cross-encoder** scores each (question, chunk) pair and the list is re-sorted. |
| 5 | `Retriever.retrieve` | **Relevance gate**: if the best score is below −6, the question is off-topic and we return a fallback answer **without calling the LLM**. |
| 6 | SSE `sources` event | The UI immediately shows what was found, before the answer is ready. |
| 7 | [prompts.py](../backend/app/prompts.py) | Build the prompt: excerpts wrapped in `<excerpt id="P1" page="10" section="...">`, federal ones as `F1...`, plan facts, the question. Text is HTML-escaped so a document can't fake a closing tag. |
| 8 | [answering.py](../backend/app/answering.py) | Call Claude with **structured output**: the response *must* match the `LLMAnswer` schema in [schemas.py](../backend/app/schemas.py) (verdict enum, headline, citations with `source_id` + `quote`, conditions, exclusions, federal notes, questions to ask, optional cost rule). |
| 9 | [verification.py](../backend/app/verification.py) | Check every quote really appears in the excerpt it cites (normalized, with a 90% fuzzy match for PDF line breaks). Drop fakes. If a covered / not-covered verdict has no verified quote left, downgrade it to **unclear**. |
| 10 | [costs.py](../backend/app/costs.py) | If the question has a dollar amount, compute deductible → copay/coinsurance → out-of-pocket cap **in Python**. |
| 11 | SSE `answer` / `error`, then `done` | The frontend renders the answer card. |

The frontend ([frontend/src/api.ts](../frontend/src/api.ts)) reads the stream with `fetch` + a small parser, because the browser's built-in `EventSource` only supports GET and we need POST.

---

## 5. The core ideas, explained simply

**Embedding (dense vector).** A model turns text into a list of numbers (here 384) so that texts with similar *meaning* end up close together. "Dentist cleaning" and "routine dental care" are close even though they share no words. Closeness is measured with cosine similarity.

**BM25 (sparse vector).** Classic keyword search, the kind search engines used for decades. It scores documents by matching words, giving more weight to rare words. It's excellent at exact terms like "7.3(b)", "semaglutide" or "$400" that dense embeddings blur.

**Hybrid search + RRF.** We run both searches and merge the two ranked lists with **Reciprocal Rank Fusion**: each chunk gets `1/(k + rank)` from each list, and the scores are summed. RRF only uses *ranks*, so we never have to make cosine scores and BM25 scores comparable. A chunk that is #1 in either list rises to the top.

**Cross-encoder reranking.** Embeddings compare two separately computed vectors (fast, approximate). A cross-encoder reads the question and the chunk *together* and outputs one relevance score: much more accurate, but too slow for thousands of chunks. So it's used as stage 2, on ~24 candidates. This "retrieve wide, rerank narrow" pattern is standard in production search.

**Chunking.** LLMs and embedding models work best on focused pieces of text. Too big and the vector is a blur of many topics; too small and the clause loses its context. Structure-aware chunking (headings, pages) beats fixed-size cutting for legal documents.

**Structured output.** Instead of free text, the API constrains Claude to return JSON that matches our schema. The SDK's `messages.parse()` validates it into a Pydantic object, so there's no regex parsing of prose.

**Grounding and hallucination.** "Hallucination" is the model stating things that aren't in its sources. We reduce it in four layers: (1) only relevant excerpts are provided, (2) the prompt requires word-for-word quotes, (3) the server verifies every quote, (4) verdicts without evidence are downgraded.

**Server-Sent Events (SSE).** A simple one-way stream over plain HTTP: the server writes `event: name` / `data: json` blocks as things happen. That's how the UI can show "Searching your policy…" and then the sources before the answer arrives.

---

## 6. Design decisions and trade-offs

| Decision | Alternative | Why this way |
|---|---|---|
| Local embedding models (fastembed/ONNX) | OpenAI / Voyage embedding APIs | No second API key, no per-query cost, works offline, fast enough on CPU. Trade-off: bigger container (~200 MB of models). |
| Qdrant | pgvector, Chroma, FAISS | Native hybrid search (dense + sparse + RRF in one query), an embedded mode for dev/tests and a managed cloud for production with the *same client code*. |
| Hybrid search | Dense only | The eval showed exact terms (clause numbers, drug names) matter in insurance text. |
| Rerank top 24 | Rerank everything / no rerank | Accuracy of a cross-encoder at the cost of only 24 model calls. |
| Lay-term dictionary | LLM query rewriting | Deterministic, free, zero latency, unit-testable. An LLM rewrite would add a paid call to every question. Trade-off: the dictionary needs maintenance. |
| One relevance gate | Per-chunk score cutoff | The eval showed the reranker is poorly calibrated on insurance text (a correct chunk scored −8.8), so per-chunk cutoffs dropped good context. A single lenient gate only blocks clearly off-topic questions; the LLM's `not_in_policy` verdict is the second line of defense. |
| Structured output | Free-text answers | The UI needs a verdict, citations and lists in fixed fields, and verification needs `source_id` + `quote` pairs. |
| Python does the cost math | Let the LLM compute | LLMs make arithmetic mistakes; insurance math has an exact order (deductible → coinsurance → out-of-pocket cap) that's easy to unit-test. |
| SSE | WebSockets / polling | One-way server→client updates are all we need; SSE is plain HTTP and proxy-friendly. |
| One Docker image (API + UI) | Separate frontend host | One URL, no CORS in production, one deploy. |
| Fictional sample policy | A real insurer's PDF | No copyright or impersonation issues, and we know the ground truth for the eval. |
| Fake embedder + fake LLM in tests | Real models in tests | Tests run in seconds, offline, for free, deterministically; real quality is measured by the separate eval scripts. |

---

## 7. Problems found while building (good interview stories)

1. **Page footers leaked into chunks.** pypdf extracted "Page 11" first on each page. *Fix:* strip "Page N" / "N of M" lines, but keep bare numbers, since in tables they can be real values like a visit limit.
2. **A sentence was mistaken for a heading.** A wrapped line reading "Section 3.11." was parsed as a new major section, so clauses 7.9 and 7.10 got the wrong label. *Fix:* a major heading must be followed by nothing or by a separator + title. Regression test added.
3. **Wrapped headings.** "SECTION 5 - CARE OUT OF NETWORK AND OUTSIDE THE" / "UNITED STATES" was split across lines. *Fix:* glue an all-caps continuation line back onto the heading.
4. **Vocabulary gap.** Retrieval eval: "nose job" missed the cosmetic surgery clause entirely, and "I broke my arm in Spain" ranked the right page only #4. *Fix:* lay-term expansion. **hit@6 went from 97% to 100%, MRR from 0.82 to 0.95.**
5. **Reranker calibration.** A strict per-chunk threshold would have blocked real questions. *Fix:* measured the score distribution with a threshold sweep and replaced it with a single gate at −6, which keeps 30/30 in-scope questions and blocks 3/4 off-topic ones.

The pattern behind all five: **build, measure, find the failure, fix it, add a test or metric so it stays fixed.**

---

## 8. Codebase map

```
backend/
  app/
    config.py           every tunable setting (env vars)
    models.py           Chunk: text + page + section + source
    ingest/pdf.py       PDF -> clean text per page
    ingest/chunker.py   section-aware chunking
    ingest/markdown.py  federal rules -> chunks
    embeddings.py       dense, BM25 and cross-encoder models
    vectorstore.py      Qdrant collection + hybrid search
    indexer.py          file -> chunks -> vectors (idempotent)
    query_expansion.py  everyday words -> insurance terms
    retrieval.py        hybrid search -> rerank -> relevance gate
    prompts.py          system prompt + XML-tagged excerpts
    schemas.py          LLM output schema + API response models
    answering.py        Claude call, errors, fallback answer
    verification.py     quote checking, verdict downgrade
    costs.py            deductible/coinsurance/out-of-pocket math
    plan_facts.py       extract plan numbers from uploads
    documents.py        document registry, safe IDs, 24h expiry
    ratelimit.py        per-IP and daily limits
    services.py         wires everything together
    api.py              HTTP routes + SSE
    main.py             FastAPI app, startup, static frontend
  data/federal/         federal rules knowledge base (Markdown)
  data/samples/         fictional sample policy + its facts
  eval/                 questions.json + retrieval and answer evals
  tests/                90 tests (fake models, fake LLM)
frontend/src/
  api.ts                fetch helpers + SSE parser
  App.tsx               layout, current document
  components/Chat.tsx   conversation, loading, errors, retry
  components/AnswerCard.tsx, DocumentPanel.tsx, ...
```

---

## 9. Questions you should be able to answer

**What is RAG and why use it here?**
Retrieve relevant passages from your own documents, then have the LLM answer from them. The model's training data doesn't contain *your* policy, and for insurance we need answers that are traceable to a clause.

**Why two vectors per chunk?**
Dense vectors match meaning ("dentist" ≈ "dental care"); BM25 matches exact tokens ("7.3(b)", "semaglutide"). Each covers the other's blind spot, and RRF merges them.

**What does the reranker add if you already have hybrid search?**
Precision. Retrieval compares independently computed vectors; the cross-encoder reads question and chunk together. We only run it on 24 candidates because it's slower.

**How do you prevent hallucinations?**
Four layers: only relevant excerpts in the prompt; mandatory word-for-word quotes; server-side quote verification; verdicts without surviving evidence are downgraded to "unclear". Plus the relevance gate skips the LLM entirely for off-topic questions.

**How do you know the system is good?**
A 34-question ground-truth set. Retrieval eval (free): hit@6 100%, MRR 0.95. Answer eval (uses the API): verdict accuracy, citation on the correct page, off-topic handling, and the number of hallucinated quotes the verifier caught.

**Why not let the LLM calculate costs?**
LLMs are unreliable at multi-step arithmetic. The LLM extracts the rule ("30% after deductible"); tested Python applies it. The tests reproduce the policy's own worked examples ($12,700 birth → $5,910).

**What happens with a question the policy doesn't answer?**
If the best reranked chunk scores below the gate, the user gets a "not found in your policy" answer with questions to ask the insurer, and no LLM call is made. If it passes the gate but the excerpts still don't answer it, the model is instructed to return `not_in_policy`.

**How is the public demo protected?**
Per-IP sliding-window rate limits, a global daily question budget, upload size/page limits, byte-level PDF checks, safe document IDs, 24-hour deletion of uploads, and prompt-injection hardening (escaped, fenced excerpts; "documents are data").

**How would you scale it?**
Move rate limits to Redis and vectors to Qdrant Cloud (already supported via `QDRANT_URL`), run several stateless API instances behind a load balancer, push uploads/indexing to a background job queue, and cache answers to common questions per document.

**What would you build next?**
OCR for scanned PDFs, a state-law layer, follow-up questions with conversation-aware query rewriting, and layout-aware table parsing for real SBC grids.
