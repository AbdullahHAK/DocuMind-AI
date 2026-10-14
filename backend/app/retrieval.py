"""Two-stage retrieval: cheap-and-wide, then expensive-and-precise.

Stage 1  hybrid search (dense + BM25, fused with RRF) pulls ~24 candidates.
Stage 2  a cross-encoder reranks them and we keep the best few that clear
         ``relevance_threshold``.

We search two sources separately - the user's policy and the federal rules -
so federal text can never crowd out the user's own policy (or vice versa),
and the answer can keep "what your policy says" apart from "what the law says".
"""

from dataclasses import dataclass, field

from app.config import Settings
from app.indexer import FEDERAL_DOC_ID
from app.models import Chunk
from app.vectorstore import VectorStore


@dataclass
class ScoredChunk:
    chunk: Chunk
    score: float  # cross-encoder logit: higher = more relevant


@dataclass
class RetrievalResult:
    policy: list[ScoredChunk] = field(default_factory=list)
    federal: list[ScoredChunk] = field(default_factory=list)
    # best rejected candidates, kept for debugging / the eval report
    best_policy_score: float | None = None
    best_federal_score: float | None = None

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

    def _select(self, ranked: list[ScoredChunk], top_k: int, threshold: float) -> list[ScoredChunk]:
        return [sc for sc in ranked if sc.score >= threshold][:top_k]

    def retrieve(self, question: str, doc_id: str, *, threshold: float | None = None) -> RetrievalResult:
        threshold = self.settings.relevance_threshold if threshold is None else threshold
        s = self.settings

        policy_ranked = self._rerank(
            question, self.store.hybrid_search(question, doc_id=doc_id, kind="policy", limit=s.retrieval_candidates)
        )
        federal_ranked = self._rerank(
            question, self.store.hybrid_search(question, doc_id=FEDERAL_DOC_ID, limit=s.retrieval_candidates // 2)
        )
        return RetrievalResult(
            policy=self._select(policy_ranked, s.policy_top_k, threshold),
            federal=self._select(federal_ranked, s.federal_top_k, threshold),
            best_policy_score=policy_ranked[0].score if policy_ranked else None,
            best_federal_score=federal_ranked[0].score if federal_ranked else None,
        )
