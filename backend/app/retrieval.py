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
    linked_from: str | None = None  # chunk_id that cross-references this one (graph expansion)


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
        if s.graph_expansion:
            result.policy += self._follow_references(result.policy)
        # federal text is optional context, so it must clear a stricter bar of its own
        result.federal = [sc for sc in federal_ranked if sc.score >= s.federal_min_score][: s.federal_top_k]
        return result
