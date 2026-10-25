# ---------- stage 1: build the React frontend ----------
FROM node:22-alpine AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---------- stage 2: Python backend that also serves the frontend ----------
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=7860

# run as a non-root user (also required by Hugging Face Spaces)
RUN useradd --create-home --uid 1000 app
WORKDIR /app/backend

COPY backend/requirements.txt ./
RUN pip install -r requirements.txt

COPY --chown=app:app backend/ ./
COPY --from=frontend --chown=app:app /frontend/dist /app/frontend/dist
# WORKDIR creates /app/backend as root; the app user must be able to write
# its model cache and runtime storage there.
RUN mkdir -p .cache storage && chown -R app:app /app
USER app

# Bake the embedding/reranking models into the image so containers start
# without downloading ~200 MB from Hugging Face on every cold start.
RUN python -c "from app.config import Settings; from app.embeddings import Embedder; Embedder(Settings()).warm_up()"

# Pre-build the vector index for the bundled documents (federal rules + sample
# policy). At runtime startup() sees the same content hash and skips
# re-embedding, so cold starts on scale-to-zero hosts (Cloud Run) are faster.
RUN python -c "from app.config import Settings; from app.services import build_services; build_services(Settings()).startup()"

EXPOSE 7860
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
