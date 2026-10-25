# 01 · System overview

## What the application does

*Am I Covered?* answers plain-English questions about a **US health insurance policy**. A user either uses the bundled fictional sample policy or uploads their own PDF. They ask "Is a nose job covered?" and get back:

- a **verdict** (`covered`, `covered_with_conditions`, `not_covered`, `unclear`, `not_in_policy`, `informational`),
- the **exact quoted clause with page and section**, verified by the server against the PDF text,
- notes from a bundled **federal-rules knowledge base** (ACA, No Surprises Act, appeals…),
- a **cost estimate** computed in Python when the question mentions a dollar amount,
- questions to ask the insurer, warnings, and a per-request **trace** of what each pipeline layer did.

Status: **verified**. Every point above maps to code: [`schemas.Answer`](../../../backend/app/schemas.py), [`AnswerService.answer`](../../../backend/app/answering.py) (lines 85-142), [`AnswerCard.tsx`](../../../frontend/src/components/AnswerCard.tsx).

## Who uses it

There is **no user model**. The code has no accounts, sessions, roles or tenants (verified: no auth dependency, middleware or check exists in [`api.py`](../../../backend/app/api.py) or [`main.py`](../../../backend/app/main.py)). Every visitor is anonymous. An uploaded document is reachable by anyone who knows its random id, and is deleted after `UPLOAD_TTL_HOURS` (24), though only when the next upload or a restart happens (see report 09).

## Primary user journeys

| Journey | Entry point | Flow in the atlas |
|---|---|---|
| Ask about the sample policy | suggested question chip in `Chat.tsx` | `flow:ask` |
| Off-topic question ("pizza near me") | same | `flow:ask-gated` |
| Upload own policy, then ask | drop zone in `DocumentPanel.tsx` | `flow:upload` → `flow:ask` |
| Open a cited page | quote link in `AnswerCard.tsx` | `flow:read-file` |
| AI provider overloaded | any question | `flow:llm-failure` |

## System context

```
 Person ──► Browser (React SPA) ──HTTPS JSON + SSE──► FastAPI process ──► Gemini API (default)
                                                        │   │   │   └──► Anthropic API (optional, untested live)
                                                        │   │   └──► local ONNX models ◄── Hugging Face Hub (model files)
                                                        │   └──► Qdrant (embedded, on local disk)
                                                        └──► storage/uploads (JSON records + PDFs), data/ (federal rules, sample)
```

**Runs locally (inside the backend process or its disk):** API, ingestion, retrieval, the three ONNX models, embedded Qdrant, document registry, rate limiters.
**Runs remotely:** only the LLM call (Gemini or Claude), plus model downloads from Hugging Face on first start.

## Trust boundaries

1. **Browser → API.** Everything from the client is untrusted: question text (validated length 3-500, [`AskRequest`](../../../backend/app/schemas.py) lines 118-120), `doc_id` (regex-validated, [`validate_doc_id`](../../../backend/app/documents.py) lines 26-30), uploaded bytes (magic bytes, size, page and text caps).
2. **Document text → LLM.** Uploaded PDF text is untrusted *data* that ends up in the prompt: injection lines are stripped at ingestion, excerpts are HTML-escaped and fenced.
3. **LLM output → user.** Model output is untrusted too: quotes are verified, markup is stripped, contact details not in the sources are removed, contradictions downgrade the verdict.
4. **Server → LLM provider.** The question and retrieved excerpts leave the machine. On the Gemini free tier, Google may use them; the UI discloses the provider.

## Major architectural choices (and their consequences)

| Choice | Consequence |
|---|---|
| Single FastAPI process with everything in-process (models, embedded Qdrant, limiters) | Zero infrastructure to run; horizontal scaling needs `QDRANT_URL` + shared storage first (report 09). |
| Local ONNX embeddings + cross-encoder | No embeddings API cost; CPU-bound latency (the reranker dominates). |
| Hybrid search + rerank + relevance gate + one-hop clause graph | 100% hit@6 / MRR 0.95 on the sample eval; off-topic questions skip the LLM. |
| Schema-constrained LLM output + server-side verification | Deterministic UI fields; hallucinated quotes are caught (0 in recorded runs). |
| Provider-neutral LLM adapter, Gemini free tier by default | Free public demo; free-tier overload drives a model fallback chain, and caused the 65-minute hang (finding `rel:llm-hang`). |
| SSE over POST | Progressive UI; errors after the first byte arrive as `event: error` with HTTP 200. |
| No authentication | Simple anonymous demo; documents are protected only by unguessable ids. |

## What the repository does *not* contain

No relational database, ORM or migrations; no queue, worker or scheduler; no cache; no authentication provider; no infrastructure-as-code; no deployment workflow; no frontend tests. Each is noted where relevant instead of being invented.
