from app.config import Settings
from app.indexer import FEDERAL_DOC_ID
from app.models import Chunk
from app.retrieval import Retriever


def _chunk(doc_id, i, text, kind):
    return Chunk(
        chunk_id=f"00000000-0000-0000-0001-{abs(hash((doc_id, i))) % 10**12:012d}",
        doc_id=doc_id, kind=kind, text=text, position=i, source_title=doc_id, page=i + 1,
    )


def _setup(store):
    store.upsert([
        _chunk("mine", 0, "Routine dental care for adults is not covered.", "policy"),
        _chunk("mine", 1, "Emergency room copay is $400.", "policy"),
        _chunk("mine", 2, "Chiropractic care limited to 12 visits.", "policy"),
    ])
    store.upsert([_chunk(FEDERAL_DOC_ID, 0, "Adult dental care is not an essential health benefit.", "federal")])


def test_policy_and_federal_are_retrieved_separately(store, embedder):
    _setup(store)
    result = Retriever(store, embedder, Settings(gate_threshold=0.0, federal_min_score=0.0)).retrieve("adult dental care", "mine")
    assert result.policy[0].chunk.text.startswith("Routine dental care")
    assert all(sc.chunk.kind == "policy" for sc in result.policy)
    assert [sc.chunk.kind for sc in result.federal] == ["federal"]


def test_threshold_filters_irrelevant_chunks(store, embedder):
    _setup(store)
    result = Retriever(store, embedder, Settings(gate_threshold=0.0, federal_min_score=0.0)).retrieve("pizza delivery near me", "mine")
    assert not result.found_anything
    assert result.best_policy_score is not None and result.best_policy_score < 0


def test_results_are_sorted_by_rerank_score(store, embedder):
    _setup(store)
    result = Retriever(store, embedder, Settings(gate_threshold=-100)).retrieve("emergency room copay", "mine")
    scores = [sc.score for sc in result.policy]
    assert scores == sorted(scores, reverse=True)
    assert result.policy[0].chunk.text.startswith("Emergency room")


def test_graph_expansion_follows_cross_references(store, embedder):
    exclusion = _chunk("mine", 1, "Drugs prescribed primarily for weight loss are not covered.", "policy")
    glp1 = _chunk("mine", 0, "GLP-1 drugs are covered for type 2 diabetes. Weight loss drugs: see 7.5.", "policy")
    glp1.extra["refs"] = [exclusion.chunk_id]
    store.upsert([glp1, exclusion])

    settings = Settings(gate_threshold=-100, policy_top_k=1)
    with_graph = Retriever(store, embedder, settings).retrieve("Are GLP-1 drugs covered for diabetes?", "mine")
    assert [sc.chunk.chunk_id for sc in with_graph.policy] == [glp1.chunk_id, exclusion.chunk_id]
    assert with_graph.policy[1].linked_from == glp1.chunk_id

    without = Retriever(store, embedder, settings.model_copy(update={"graph_expansion": False}))
    assert len(without.retrieve("Are GLP-1 drugs covered for diabetes?", "mine").policy) == 1
