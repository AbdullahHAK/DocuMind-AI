"""Two-stage retrieval: cheap-and-wide, then expensive-and-precise.

Stage 1  hybrid search (dense + BM25, fused with RRF) pulls ~12 candidates.
Stage 2  a cross-encoder reranks them and we keep the best few.

Relevance gate: if even the best candidate scores below ``gate_threshold``,
the question is off-topic for this policy and we answer with a fallback
*without* calling the LLM (saves money, and the model can't make things up
from irrelevant text). The eval showed this cross-encoder is poorly
calibrated on insurance text, so the gate is deliberately lenient: it only
catches clearly unrelated questions, and the LLM's own "not_in_policy"
verdict is the second line of defence.

We search two sources separately - the user's policy and the federal rules -
so federal text can never crowd out the user's own policy (or vice versa),
and the answer can keep "what your policy says" apart from "what the law says".
"""

import time
from dataclasses import dataclass, field

from app.config import Settings
from app.embeddings import cosine
from app.indexer import FEDERAL_DOC_ID
from app.models import Chunk
from app.query_expansion import expand_query
from app.vectorstore import VectorStore


@dataclass
class ScoredChunk:
    chunk: Chunk
    score: float  # cross-encoder logit: higher = more relevant
    linked_from: str | None = None  # chunk_id that cross-references this one (graph expansion)


@dataclass
class RetrievalResult:
    policy: list[ScoredChunk] = field(default_factory=list)
    federal: list[ScoredChunk] = field(default_factory=list)
    # best rejected candidates, kept for debugging / the eval report
    best_policy_score: float | None = None
    best_federal_score: float | None = None

    search_query: str = ""
    # observability: what this request cost, for the "under the hood" trace
    search_ms: float = 0.0
    rerank_ms: float = 0.0
    candidates: int = 0
    gate_passed: bool = False

    @property
    def found_anything(self) -> bool:
        return bool(self.policy or self.federal)


class Retriever:
    def __init__(self, store: VectorStore, embedder, settings: Settings) -> None:
        self.store = store
        self.embedder = embedder
        self.settings = settings

    def _rerank(self, question: str, candidates: list[Chunk]) -> list[ScoredChunk]:
        scores = self.embedder.rerank(question, [c.embedding_text() for c in candidates])
        ranked = [ScoredChunk(c, s) for c, s in zip(candidates, scores)]
        return sorted(ranked, key=lambda sc: sc.score, reverse=True)

    def _follow_references(self, top: list[ScoredChunk]) -> list[ScoredChunk]:
        """One hop through the clause graph: add clauses the top chunks point at ("see 7.5")."""
        have = {sc.chunk.chunk_id for sc in top}
        wanted: dict[str, str] = {}  # target chunk_id -> referring chunk_id, in rank order
        for sc in top:
            for ref in sc.chunk.extra.get("refs", []):
                if ref not in have and ref not in wanted:
                    wanted[ref] = sc.chunk.chunk_id
        targets = list(wanted)[: self.settings.graph_max_linked]
        return [
            ScoredChunk(chunk, score=float("nan"), linked_from=wanted[chunk.chunk_id])
            for chunk in self.store.get_chunks(targets)
        ]

    def _similarity_ranked(self, query: str, doc_id: str, kind, limit: int) -> list[ScoredChunk]:
        """No-reranker mode: keep the hybrid (RRF) order, score each hit by dense cosine
        similarity so the relevance gate still has a calibrated number to test."""
        hits, query_vector = self.store.hybrid_search_with_vectors(query, doc_id=doc_id, kind=kind, limit=limit, with_vectors=True)
        return [ScoredChunk(chunk, cosine(query_vector, vector) if vector else 0.0) for chunk, vector in hits]

    def retrieve(self, question: str, doc_id: str, *, gate_threshold: float | None = None) -> RetrievalResult:
        s = self.settings
        query = expand_query(question)
        rerank = getattr(self.embedder, "can_rerank", True)
        if rerank:
            gate = s.gate_threshold if gate_threshold is None else gate_threshold
            federal_min = s.federal_min_score
        else:
            gate = s.gate_similarity if gate_threshold is None else gate_threshold
            federal_min = s.federal_min_similarity

        started = time.perf_counter()
        if rerank:
            policy_candidates = self.store.hybrid_search(query, doc_id=doc_id, kind="policy", limit=s.retrieval_candidates)
            federal_candidates = self.store.hybrid_search(query, doc_id=FEDERAL_DOC_ID, limit=s.retrieval_candidates // 2)
            searched = time.perf_counter()
            policy_ranked = self._rerank(query, policy_candidates)
            federal_ranked = self._rerank(query, federal_candidates)
        else:
            policy_ranked = self._similarity_ranked(query, doc_id, "policy", s.retrieval_candidates)
            federal_ranked = self._similarity_ranked(query, FEDERAL_DOC_ID, None, s.retrieval_candidates // 2)
            policy_candidates, federal_candidates = policy_ranked, federal_ranked
            searched = time.perf_counter()
        result = RetrievalResult(
            best_policy_score=max((sc.score for sc in policy_ranked), default=None),
            best_federal_score=max((sc.score for sc in federal_ranked), default=None),
            search_query=query,
            search_ms=(searched - started) * 1000,
            rerank_ms=(time.perf_counter() - searched) * 1000,
            candidates=len(policy_candidates) + len(federal_candidates),
        )
        best = max([sc.score for sc in policy_ranked + federal_ranked], default=float("-inf"))
        if best < gate:
            return result  # off-topic: nothing passes the gate
        result.gate_passed = True

        result.policy = policy_ranked[: s.policy_top_k]
        if s.graph_expansion:
            result.policy += self._follow_references(result.policy)
        # federal text is optional context, so it must clear a stricter bar of its own
        result.federal = [sc for sc in federal_ranked if sc.score >= federal_min][: s.federal_top_k]
        return result
