# Deploying Am I Covered?

The app ships as **one Docker image**: FastAPI serves the API under `/api` and the built React app at `/`. The image bakes in the embedding models and a pre-built vector index for the bundled documents, so it needs no external database.

It runs in two modes, chosen with `EMBEDDING_PROVIDER`:

| Mode | What runs on the server | Needs | Measured (Docker) |
|---|---|---|---|
| `local` (default) | dense + BM25 + cross-encoder reranker (ONNX) | ≥ 1 full CPU, ~1 GB RAM | ~6 s answers; 100-page upload peaks at ~1.1 GB |
| `gemini` | BM25 only; dense vectors from the Gemini embedding API; no reranker | works on 0.1 CPU / 512 MB | ~6-7 s answers at 0.1 CPU, ~150 MB RAM, 15-page upload 19 s |

Retrieval eval: `local` hit@6 100%, MRR 0.95; `gemini` hit@6 100%, MRR 0.98. Answer eval in `gemini` mode: 91% exact verdicts (local-mode runs ranged 82-97%), 100% citations on the right page, 0 unverified quotes.

## Option A: Render free tier (no card), recommended

Render's free web services have 512 MB RAM and a fraction of a CPU, sleep after 15 minutes without traffic, and take a while to wake up. Measured at 0.1 CPU: about 100 s for the app to start after sleeping, then 6-7 s per answer.

1. Push this repository to GitHub (Render deploys from it).
2. Sign up at **render.com** with your GitHub account. No card needed for free services.
3. **New → Blueprint**, select the repository. Render reads [`render.yaml`](../render.yaml): Docker, free plan, `EMBEDDING_PROVIDER=gemini`, 20-page upload limit, demo rate limits.
4. When asked, paste your **GEMINI_API_KEY** (stored as a secret in Render, never in git).
5. **Apply**. The first build takes ~10 minutes. The app is live at `https://am-i-covered.onrender.com` (or the name Render shows), and every push to `main` redeploys it.

Free-tier limits to know: 750 instance-hours per month (one always-awake service uses ~720), an ephemeral filesystem (uploads vanish on restart; the bundled sample always works), and the Gemini free tier's 100 embedded texts per minute (the app throttles uploads to stay under it).

## Option B: Hugging Face Spaces (now requires PRO)

As of 2026, Docker Spaces need a paid PRO plan (creating one on a free account returns `402 Payment Required`). With PRO, run `scripts/deploy_hf.py`. It uses the Hub upload API because git pushes containing binary files (the sample PDF) are rejected. Local mode works there.

## Option C: any container host (Cloud Run, Railway, Fly.io, a VPS)

Point the host at the `Dockerfile` and set:

| Variable | Value |
|---|---|
| `GEMINI_API_KEY` or `ANTHROPIC_API_KEY` | your key (as a secret) |
| `EMBEDDING_PROVIDER` | `local` with ≥ 1 CPU and 1 GB RAM; `gemini` for small instances |
| `PORT` | usually set by the host; defaults to 7860 |

Run a single instance: the embedded vector store and the rate limiters live in the process. Uvicorn runs with `--proxy-headers`, so per-IP limits see the client address forwarded by the host's load balancer.

## Option D: run the image yourself

```bash
docker build -t am-i-covered .
docker run -p 7860:7860 -e GEMINI_API_KEY=... am-i-covered                              # local mode
docker run -p 7860:7860 -e GEMINI_API_KEY=... -e EMBEDDING_PROVIDER=gemini am-i-covered  # small-host mode
```

## Keeping uploads across restarts (optional)

The index lives inside the container, so uploads disappear on restart. That's acceptable because uploads expire after 24 hours anyway. To persist them, mount a volume at `/app/backend/storage`, or create a free Qdrant Cloud cluster and set `QDRANT_URL` and `QDRANT_API_KEY`.

## After changing bundled documents

In `gemini` mode the bundled documents' vectors are shipped in `backend/data/embeddings/`. After editing the federal rules, the sample policy or the chunker, run `EMBEDDING_PROVIDER=gemini python backend/scripts/precompute_embeddings.py` and commit the result; otherwise every cold start re-embeds them through the API.

## Cost control checklist

- **Gemini free tier:** no bill, but Google enforces per-model rate limits and daily quotas. When a model is overloaded or out of quota the app falls back to the next model in `GEMINI_FALLBACK_MODELS`; if all are exhausted, users see a friendly "busy, try again" message. Google may use free-tier prompts to improve its products, so the UI tells users their questions and policy excerpts are processed by Google.
- **Claude (paid):** roughly $0.03-0.06 per answered question with Claude Opus 5.5 at medium effort, so a `QUESTIONS_PER_DAY_GLOBAL` of 600 bounds a bad day at about $20-35. Also set a monthly spend limit in the Anthropic Console.
- `QUESTIONS_PER_IP_PER_HOUR` and `QUESTIONS_PER_DAY_GLOBAL` apply to both providers (`render.yaml` sets 20 and 300).
- Off-topic questions are answered by the relevance gate without any LLM call.
