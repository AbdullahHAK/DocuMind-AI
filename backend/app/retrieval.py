"""Two-stage retrieval: cheap-and-wide, then expensive-and-precise.

Stage 1  hybrid search (dense + BM25, fused with RRF) pulls ~24 candidates.
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

from dataclasses import dataclass, field

from app.config import Settings
from app.indexer import FEDERAL_DOC_ID
from app.models import Chunk
from app.query_expansion import expand_query
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

    search_query: str = ""

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

    def retrieve(self, question: str, doc_id: str, *, gate_threshold: float | None = None) -> RetrievalResult:
        s = self.settings
        gate = s.gate_threshold if gate_threshold is None else gate_threshold
        query = expand_query(question)

        policy_ranked = self._rerank(
            query, self.store.hybrid_search(query, doc_id=doc_id, kind="policy", limit=s.retrieval_candidates)
        )
        federal_ranked = self._rerank(
            query, self.store.hybrid_search(query, doc_id=FEDERAL_DOC_ID, limit=s.retrieval_candidates // 2)
        )
        result = RetrievalResult(
            best_policy_score=policy_ranked[0].score if policy_ranked else None,
            best_federal_score=federal_ranked[0].score if federal_ranked else None,
            search_query=query,
        )
        best = max([sc.score for sc in policy_ranked[:1] + federal_ranked[:1]], default=float("-inf"))
        if best < gate:
            return result  # off-topic: nothing passes the gate

        result.policy = policy_ranked[: s.policy_top_k]
        # federal text is optional context, so it must clear a stricter bar of its own
        result.federal = [sc for sc in federal_ranked if sc.score >= s.federal_min_score][: s.federal_top_k]
        return result
