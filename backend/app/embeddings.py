"""Local embedding and reranking models (via fastembed / ONNX, no API key needed).

Three models, three jobs:

- dense  (bge-small, 384-dim): captures *meaning*, so "dentist" matches "dental care".
- sparse (BM25): captures *exact words*, so "7.3(b)" or "semaglutide" match literally.
- reranker (cross-encoder): reads query + chunk *together* and scores relevance.
  Much more accurate than comparing two vectors, but too slow to run on every
  chunk, so it only re-scores the ~24 candidates that hybrid search returns.

Models download once (~200 MB total) into settings.models_cache_dir.
"""

from functools import cached_property
from typing import Protocol

from fastembed import SparseTextEmbedding, TextEmbedding
from fastembed.rerank.cross_encoder import TextCrossEncoder

from app.config import Settings


class SparseVector(Protocol):
    indices: list[int]
    values: list[float]


class Embedder:
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
        dense = [v.tolist() for v in self._dense.embed(texts, batch_size=32)]
        sparse = [_to_sparse(v) for v in self._sparse.embed(texts, batch_size=32)]
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


class _Sparse:
    def __init__(self, indices: list[int], values: list[float]) -> None:
        self.indices, self.values = indices, values


def _to_sparse(embedding) -> _Sparse:
    return _Sparse(embedding.indices.tolist(), embedding.values.tolist())
