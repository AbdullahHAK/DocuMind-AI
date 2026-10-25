"""Local embedding and reranking models (via fastembed / ONNX, no API key needed).

Three models, three jobs:

- dense  (bge-small, 384-dim): captures *meaning*, so "dentist" matches "dental care".
- sparse (BM25): captures *exact words*, so "7.3(b)" or "semaglutide" match literally.
- reranker (cross-encoder): reads query + chunk *together* and scores relevance.
  Much more accurate than comparing two vectors, but too slow to run on every
  chunk, so it only re-scores the ~24 candidates that hybrid search returns.

Models download once (~200 MB total) into settings.models_cache_dir.
"""

import base64
import hashlib
import json
import threading
import time
from array import array
from collections import deque
from functools import cached_property
from pathlib import Path
from typing import Protocol

from fastembed import SparseTextEmbedding, TextEmbedding
from fastembed.rerank.cross_encoder import TextCrossEncoder

from app.config import Settings


class SparseVector(Protocol):
    indices: list[int]
    values: list[float]


class Embedder:
    can_rerank = True

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        # fastembed creates only the last folder of cache_dir, not its parents
        settings.models_cache_dir.mkdir(parents=True, exist_ok=True)

    @cached_property
    def _dense(self) -> TextEmbedding:
        return TextEmbedding(self.settings.dense_model, cache_dir=str(self.settings.models_cache_dir))

    @cached_property
    def _sparse(self) -> SparseTextEmbedding:
        return SparseTextEmbedding(self.settings.sparse_model, cache_dir=str(self.settings.models_cache_dir))

    @cached_property
    def _reranker(self) -> TextCrossEncoder:
        return TextCrossEncoder(self.settings.rerank_model, cache_dir=str(self.settings.models_cache_dir))

    @property
    def dense_size(self) -> int:
        return 384  # bge-small-en-v1.5

    def warm_up(self) -> None:
        """Load all models now (at startup) rather than on the first user request."""
        self.embed_query("warm up")
        self.rerank("warm up", ["warm up"])

    def embed_documents(self, texts: list[str]) -> tuple[list[list[float]], list[SparseVector]]:
        size = self.settings.embed_batch_size
        dense = [v.tolist() for v in self._dense.embed(texts, batch_size=size)]
        sparse = [_to_sparse(v) for v in self._sparse.embed(texts, batch_size=size)]
        return dense, sparse

    def embed_query(self, text: str) -> tuple[list[float], SparseVector]:
        # query_embed differs from embed: bge adds a retrieval instruction, BM25 skips term weighting
        dense = next(iter(self._dense.query_embed(text))).tolist()
        sparse = _to_sparse(next(iter(self._sparse.query_embed(text))))
        return dense, sparse

    def rerank(self, query: str, texts: list[str]) -> list[float]:
        if not texts:
            return []
        # small batches: every pair in a batch is padded to the longest one
        return [float(s) for s in self._reranker.rerank(query, texts, batch_size=8)]


class GeminiEmbedder:
    """Dense vectors from the Gemini embedding API; BM25 stays local.

    For small hosts (Render free tier: 0.1 CPU, 512 MB) where running ONNX
    models per request is far too slow. There is no cross-encoder in this
    mode (can_rerank = False): the retriever keeps the hybrid-search order and
    gates on dense cosine similarity instead (see Retriever.retrieve).
    """

    can_rerank = False
    BATCH = 50  # texts per embed_content request

    def __init__(self, settings: Settings, client=None, clock=time.monotonic, sleep=time.sleep) -> None:
        self.settings = settings
        self._client = client
        settings.models_cache_dir.mkdir(parents=True, exist_ok=True)
        # Free tier counts every text as one request (100/min). Precomputed
        # vectors for the bundled documents mean cold starts use none of it.
        self._precomputed = load_precomputed(settings)
        self._clock, self._sleep = clock, sleep
        self._sent: deque[tuple[float, int]] = deque()  # (time, texts) in the last minute
        self._lock = threading.Lock()

    def _wait_for_quota(self, n: int) -> None:
        """Block until sending n more texts keeps us under EMBEDDING_TEXTS_PER_MINUTE."""
        limit = self.settings.embedding_texts_per_minute
        while True:
            with self._lock:
                now = self._clock()
                while self._sent and self._sent[0][0] <= now - 60:
                    self._sent.popleft()
                used = sum(count for _, count in self._sent)
                if used + n <= limit:
                    self._sent.append((now, n))
                    return
                wait = self._sent[0][0] + 60 - now
            self._sleep(max(wait, 0.5))

    @property
    def client(self):
        if self._client is None:
            from google import genai
            from google.genai import types

            self._client = genai.Client(
                api_key=self.settings.gemini_api_key,
                http_options=types.HttpOptions(
                    timeout=self.settings.llm_timeout_seconds * 1000,
                    retry_options=types.HttpRetryOptions(attempts=3, initial_delay=1.0, max_delay=8.0),
                ),
            )
        return self._client

    @cached_property
    def _sparse(self) -> SparseTextEmbedding:
        return SparseTextEmbedding(self.settings.sparse_model, cache_dir=str(self.settings.models_cache_dir))

    @property
    def dense_size(self) -> int:
        return self.settings.embedding_dimensions

    def _embed(self, texts: list[str], task_type: str) -> list[list[float]]:
        from google.genai import errors, types

        from app.llm import LLMError

        results: dict[int, list[float]] = {}
        missing: list[int] = []
        for i, text in enumerate(texts):
            cached = self._precomputed.get(precomputed_key(task_type, text)) if self._precomputed else None
            if cached is not None:
                results[i] = cached
            else:
                missing.append(i)

        config = types.EmbedContentConfig(task_type=task_type, output_dimensionality=self.dense_size)
        batch_size = min(self.BATCH, self.settings.embedding_texts_per_minute)
        for start in range(0, len(missing), batch_size):
            idx = missing[start : start + batch_size]
            self._wait_for_quota(len(idx))
            try:
                response = self.client.models.embed_content(
                    model=self.settings.gemini_embedding_model, contents=[texts[i] for i in idx], config=config
                )
            except errors.APIError as exc:
                raise LLMError("The search service is busy right now. Please try again in a minute.") from exc
            for i, e in zip(idx, response.embeddings):
                results[i] = _normalize(e.values)
        return [results[i] for i in range(len(texts))]

    def warm_up(self) -> None:
        self.embed_query("warm up")

    def embed_documents(self, texts: list[str]) -> tuple[list[list[float]], list[SparseVector]]:
        dense = self._embed(texts, "RETRIEVAL_DOCUMENT")
        sparse = [_to_sparse(v) for v in self._sparse.embed(texts, batch_size=self.settings.embed_batch_size)]
        return dense, sparse

    def embed_query(self, text: str) -> tuple[list[float], SparseVector]:
        # one question triggers two searches (policy + federal): embed it once
        cache = self.__dict__.setdefault("_query_cache", {})
        if text not in cache:
            dense = self._embed([text], "RETRIEVAL_QUERY")[0]
            sparse = _to_sparse(next(iter(self._sparse.query_embed(text))))
            if len(cache) > 256:
                cache.clear()
            cache[text] = (dense, sparse)
        return cache[text]

    def rerank(self, query: str, texts: list[str]) -> list[float]:
        raise NotImplementedError("GeminiEmbedder has no reranker; Retriever checks can_rerank")


def precomputed_path(settings: Settings) -> Path:
    name = f"{settings.gemini_embedding_model}-{settings.embedding_dimensions}.json"
    return settings.data_dir / "embeddings" / name


def precomputed_key(task_type: str, text: str) -> str:
    return hashlib.sha256(f"{task_type}\n{text}".encode("utf-8")).hexdigest()


def load_precomputed(settings: Settings) -> dict[str, list[float]]:
    """{sha256(task + text): unit vector}, written by scripts/precompute_embeddings.py.
    Vectors are stored as base64 float32 to keep the file small."""
    path = precomputed_path(settings)
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {k: list(array("f", base64.b64decode(v))) for k, v in raw["vectors"].items()}


def build_embedder(settings: Settings):
    if settings.embedding_provider == "gemini":
        return GeminiEmbedder(settings)
    return Embedder(settings)


def _normalize(values) -> list[float]:
    # Gemini only returns unit vectors at full size; truncated ones must be normalized
    norm = sum(v * v for v in values) ** 0.5 or 1.0
    return [v / norm for v in values]


def cosine(a: list[float], b: list[float]) -> float:
    """Both inputs are unit vectors here, so the dot product is the cosine."""
    return float(sum(x * y for x, y in zip(a, b)))


class _Sparse:
    def __init__(self, indices: list[int], values: list[float]) -> None:
        self.indices, self.values = indices, values


def _to_sparse(embedding) -> _Sparse:
    return _Sparse(embedding.indices.tolist(), embedding.values.tolist())
