"""Shared test fixtures.

FakeEmbedder replaces the real ONNX models with tiny deterministic
bag-of-words vectors: tests stay fast, offline and repeatable, while still
exercising the real Qdrant hybrid-search code path.
"""

import hashlib
import math
import re

import pytest
from qdrant_client import QdrantClient

from app.vectorstore import VectorStore

DIM = 64


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _bucket(token: str, size: int) -> int:
    return int(hashlib.md5(token.encode()).hexdigest(), 16) % size


class _Sparse:
    def __init__(self, indices, values):
        self.indices, self.values = indices, values


class FakeEmbedder:
    dense_size = DIM

    def _dense(self, text: str) -> list[float]:
        vec = [0.0] * DIM
        for tok in _tokens(text):
            vec[_bucket(tok, DIM)] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def _sparse(self, text: str) -> _Sparse:
        counts: dict[int, float] = {}
        for tok in _tokens(text):
            idx = _bucket(tok, 100_000)
            counts[idx] = counts.get(idx, 0.0) + 1.0
        return _Sparse(list(counts), list(counts.values()))

    def embed_documents(self, texts):
        return [self._dense(t) for t in texts], [self._sparse(t) for t in texts]

    def embed_query(self, text):
        return self._dense(text), self._sparse(text)

    def rerank(self, query, texts):
        q = set(_tokens(query))
        # word overlap, shifted so "no overlap" is clearly negative like a real cross-encoder
        return [len(q & set(_tokens(t))) * 2.0 - 3.0 for t in texts]

    def warm_up(self):
        pass


@pytest.fixture
def embedder():
    return FakeEmbedder()


@pytest.fixture
def store(embedder):
    s = VectorStore(QdrantClient(":memory:"), "test", embedder)
    s.ensure_collection()
    return s
