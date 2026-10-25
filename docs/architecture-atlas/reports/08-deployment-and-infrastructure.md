# 08 · Deployment and infrastructure

## What is verified vs. inferred

| Item | Status | Evidence |
|---|---|---|
| Local dev: uvicorn + Vite with `/api` proxy | verified | `frontend/vite.config.ts`, README "Run it locally" |
| Docker image builds and serves API + UI on one port | verified (built and smoke-tested earlier in this repo's history: ~10 s startup, ~800 MB RAM) | `Dockerfile` |
| CI on GitHub Actions (tests, lint, build) | verified (config; runs passed on GitHub earlier) | `.github/workflows/ci.yml` |
| Production deployment on Hugging Face Spaces | **unknown / not done**: documented plan only | `docs/DEPLOY.md` |
| Any other cloud resource | none in repo (no IaC, no deploy workflow) | n/a |

## Build and start commands

| Context | Command |
|---|---|
| Backend dev | `cd backend && .venv\Scripts\python -m uvicorn app.main:app --reload` (port 8000) |
| Frontend dev | `cd frontend && npm run dev` (port 5173, proxies `/api` to 8000) |
| Frontend build | `npm run build` (`tsc -b && vite build`, output `frontend/dist/`) |
| Container | `docker build -t am-i-covered .` then `docker run -p 7860:7860 -e GEMINI_API_KEY=… am-i-covered` |
| Tests | `cd backend && pytest -q` |

## Container structure (`Dockerfile`)

1. **Stage `frontend`** (`node:22-alpine`): `npm ci`, copy `frontend/`, `npm run build`.
2. **Runtime** (`python:3.12-slim`): env `PYTHONDONTWRITEBYTECODE`, `PYTHONUNBUFFERED`, `PIP_NO_CACHE_DIR`, `PORT=7860`; `useradd --uid 1000 app`; `pip install -r requirements.txt` (production deps only); copy `backend/` and the built `dist` to `/app/frontend/dist`; `mkdir .cache storage && chown -R app:app /app`; `USER app`; **bake models** by running `Embedder(Settings()).warm_up()` at build time.
3. `CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'`.

`main.FRONTEND_DIST = parents[2]/frontend/dist` resolves to `/app/frontend/dist` inside the image, matching the copy target. `.dockerignore` excludes `.venv`, `node_modules`, `storage`, `.cache`, `backend/.env`, eval results and `.git`.

## Runtime processes and network

- **One process:** uvicorn with a single worker (no `--workers` flag). Sync endpoints run in AnyIO's thread pool.
- **Inbound:** `$PORT` (7860 in the image, 8000 in dev).
- **Outbound:** LLM provider HTTPS (Gemini `generativelanguage` API, or Anthropic); Hugging Face Hub when models aren't cached. Startup logs on a dev machine with a warm cache still show metadata requests to `huggingface.co` (observed). Whether the image starts with no network access was **not tested**.
- **Storage:** `backend/storage/` (Qdrant files + uploads) inside the container filesystem, so it's lost on restart unless a volume is mounted or `QDRANT_URL` is set. The bundled documents are re-indexed at startup.

## Environment variables

All 36 are fields of `Settings` (`backend/app/config.py`); the full table with defaults is in the **Deployment** view. The ones that matter for deployment:

| Variable | Purpose |
|---|---|
| `GEMINI_API_KEY` / `ANTHROPIC_API_KEY` | LLM credentials (secret; one is required for answers) |
| `LLM_PROVIDER` | force `gemini` or `anthropic` |
| `GEMINI_MODEL`, `GEMINI_FALLBACK_MODELS`, `LLM_TIMEOUT_SECONDS` | model chain and timeout |
| `QDRANT_URL`, `QDRANT_API_KEY` | external Qdrant instead of embedded |
| `STORAGE_DIR`, `MODELS_CACHE_DIR` | runtime paths |
| `QUESTIONS_PER_IP_PER_HOUR`, `UPLOADS_PER_IP_PER_HOUR`, `QUESTIONS_PER_DAY_GLOBAL` | abuse and cost limits |
| `TRUST_PROXY_HEADERS` | make `client_ip()` read `X-Forwarded-For` itself (default false; the Docker CMD's uvicorn flags already rewrite the client address) |
| `CORS_ORIGINS` | only needed when the UI is served from another origin |
| `PORT` | container listen port (Dockerfile, not a `Settings` field) |

## CI/CD (`.github/workflows/ci.yml`)

Triggers: push to `main`, any pull request. Jobs: **backend** (Python 3.12, pip cache, `pip install -r requirements-dev.txt`, `pytest -q`) and **frontend** (Node 22, `npm ci`, `npm run lint`, `npm run build`). There is no image build, no push and no deploy stage. GitHub reported a Node 20 deprecation warning for `actions/checkout@v4` / `setup-node@v4` earlier (still runs).

## Health, readiness, monitoring

- `GET /api/health` is a liveness check; it returns OK as soon as the lifespan finished, so it also serves as readiness. It doesn't check Qdrant or the LLM provider.
- No metrics endpoint, tracing exporter or error reporting service. Observability is the INFO logs plus the per-request `trace` in each answer.

## Single points of failure

1. The single uvicorn process (no replica).
2. The embedded Qdrant on that container's disk.
3. The LLM provider. With Gemini's free tier, overload is frequent; the model chain mitigates this but didn't prevent the 65-minute hang.
4. Process-memory limiters (reset on restart).
