"""Gemini-embedding mode: precomputed cache, free-tier throttle, no-reranker retrieval.
The Gemini client is faked; no network calls."""

from types import SimpleNamespace

import pytest
from google.genai import errors as genai_errors

from app.config import Settings
from app.embeddings import GeminiEmbedder, precomputed_key
from app.llm import LLMError
from app.models import Chunk
from app.retrieval import Retriever


class FakeClient:
    def __init__(self, dims=4, fail=False):
        self.calls = []
        self.dims, self.fail = dims, fail
        self.models = SimpleNamespace(embed_content=self.embed_content)

    def embed_content(self, *, model, contents, config):
        self.calls.append(list(contents))
        if self.fail:
            raise genai_errors.ClientError(429, {"error": {"message": "quota", "status": "RESOURCE_EXHAUSTED"}})
        return SimpleNamespace(embeddings=[SimpleNamespace(values=[float(len(t))] + [1.0] * (self.dims - 1)) for t in contents])


class Clock:
    def __init__(self):
        self.t = 0.0
        self.sleeps = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


def make(tmp_path, client, **overrides):
    clock = Clock()
    settings = Settings(embedding_provider="gemini", embedding_dimensions=4, data_dir=tmp_path,
                        models_cache_dir=tmp_path / "models", **overrides)
    emb = GeminiEmbedder(settings, client=client, clock=clock.now, sleep=clock.sleep)
    return emb, clock


def test_vectors_are_normalized_and_batched(tmp_path):
    client = FakeClient()
    emb, _ = make(tmp_path, client)
    emb.BATCH = 2
    vectors = emb._embed(["a", "bb", "ccc"], "RETRIEVAL_DOCUMENT")
    assert [len(c) for c in client.calls] == [2, 1]
    assert all(abs(sum(x * x for x in v) - 1) < 1e-9 for v in vectors)


def test_precomputed_vectors_skip_the_api(tmp_path):
    client = FakeClient()
    emb, _ = make(tmp_path, client)
    emb._precomputed = {precomputed_key("RETRIEVAL_DOCUMENT", "known"): [1.0, 0.0, 0.0, 0.0]}
    vectors = emb._embed(["known", "new"], "RETRIEVAL_DOCUMENT")
    assert client.calls == [["new"]]
    assert vectors[0] == [1.0, 0.0, 0.0, 0.0]


def test_free_tier_throttle_waits_instead_of_failing(tmp_path):
    client = FakeClient()
    emb, clock = make(tmp_path, client, embedding_texts_per_minute=3)
    emb._embed(["a", "b", "c", "d", "e"], "RETRIEVAL_DOCUMENT")
    # 3 texts in the first minute, then it waits ~60 s for the window before the rest
    assert [len(c) for c in client.calls] == [3, 2]
    assert sum(clock.sleeps) >= 59


def test_query_embeddings_are_cached(tmp_path):
    client = FakeClient()
    emb, _ = make(tmp_path, client)
    emb._sparse = SimpleNamespace(query_embed=lambda text: iter([SimpleNamespace(
        indices=SimpleNamespace(tolist=lambda: [1]), values=SimpleNamespace(tolist=lambda: [1.0]))]))
    emb.embed_query("is dental covered")
    emb.embed_query("is dental covered")
    assert len(client.calls) == 1


def test_api_errors_become_user_safe_errors(tmp_path):
    emb, _ = make(tmp_path, FakeClient(fail=True))
    with pytest.raises(LLMError, match="busy"):
        emb._embed(["x"], "RETRIEVAL_QUERY")


def test_collection_name_differs_per_provider():
    assert Settings(embedding_provider="local").collection_name == "chunks"
    assert Settings(embedding_provider="gemini").collection_name == "chunks_gemini"


# ------------------------------------------------------------------ retriever without reranker

def _chunk(doc_id, i, text):
    return Chunk(chunk_id=f"00000000-0000-0000-0002-{abs(hash((doc_id, i))) % 10**12:012d}",
                 doc_id=doc_id, kind="policy", text=text, position=i, source_title=doc_id, page=i + 1)


def test_no_rerank_mode_keeps_fused_order_and_gates_on_similarity(store, embedder):
    embedder.can_rerank = False
    embedder.rerank = None  # must never be called in this mode
    store.upsert([_chunk("mine", 0, "Routine dental care for adults is not covered."),
                  _chunk("mine", 1, "Emergency room copay is $400.")])
    retriever = Retriever(store, embedder, Settings(gate_similarity=0.2, federal_min_similarity=0.99))
    result = retriever.retrieve("adult dental care", "mine")
    assert result.gate_passed
    assert result.policy[0].chunk.text.startswith("Routine dental")
    assert 0 < result.policy[0].score <= 1.0  # cosine, not a reranker logit

    # cosine can't exceed 1.0, so this gate blocks everything (the fake embedder's
    # hashed buckets make "unrelated" text unpredictable, so test the mechanism)
    strict = Retriever(store, embedder, Settings(gate_similarity=1.01))
    blocked = strict.retrieve("adult dental care", "mine")
    assert not blocked.found_anything and not blocked.gate_passed
