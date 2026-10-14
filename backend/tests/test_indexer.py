from pathlib import Path

from app.config import Settings
from app.indexer import FEDERAL_DOC_ID, index_federal_corpus, index_policy_pdf

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "samples" / "evergreen-silver-3000-ppo.pdf"


def test_federal_corpus_indexes_once(store):
    settings = Settings()
    first = index_federal_corpus(store, settings)
    assert first > 20
    assert store.count(doc_id=FEDERAL_DOC_ID) == first

    # second run sees the same version and doesn't re-embed
    calls = []
    original = store.upsert
    store.upsert = lambda chunks: calls.append(chunks) or original(chunks)
    index_federal_corpus(store, settings)
    assert calls == []


def test_sample_policy_indexes_with_pages_and_sections(store):
    chunks, pages = index_policy_pdf(store, SAMPLE, doc_id="sample", title="Evergreen", settings=Settings())
    assert pages == 14
    assert store.count(doc_id="sample") == chunks
    hits = store.hybrid_search("7.3 Dental and Vision adult dental", doc_id="sample", limit=5)
    assert any(h.section and "7.3 Dental" in h.section and h.page == 10 for h in hits)
