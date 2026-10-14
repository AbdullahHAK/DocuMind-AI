from app.models import Chunk


def _chunk(doc_id, position, text, kind="policy", version="v1"):
    return Chunk(
        chunk_id=f"00000000-0000-0000-0000-{abs(hash((doc_id, position))) % 10**12:012d}",
        doc_id=doc_id,
        kind=kind,
        text=text,
        position=position,
        source_title=doc_id,
        page=position + 1,
        extra={"version": version},
    )


def test_upsert_count_and_delete(store):
    store.upsert([_chunk("a", 0, "dental care excluded"), _chunk("a", 1, "MRI needs prior authorization")])
    store.upsert([_chunk("b", 0, "acupuncture covered for back pain")])
    assert store.count() == 3
    assert store.count(doc_id="a") == 2
    assert store.count(doc_id="a", version="v1") == 2
    assert store.count(doc_id="a", version="v2") == 0
    store.delete_document("a")
    assert store.count() == 1


def test_hybrid_search_is_scoped_to_one_document(store):
    store.upsert([_chunk("mine", 0, "adult dental care is not covered")])
    store.upsert([_chunk("someone-else", 0, "adult dental care is fully covered")])
    hits = store.hybrid_search("is dental care covered", doc_id="mine")
    assert [h.doc_id for h in hits] == ["mine"]


def test_hybrid_search_ranks_keyword_match_first(store):
    store.upsert(
        [
            _chunk("a", 0, "Emergency room visits have a $400 copay."),
            _chunk("a", 1, "7.3(b) routine dental care for adults is not covered."),
            _chunk("a", 2, "Physical therapy is limited to 30 visits."),
        ]
    )
    hits = store.hybrid_search("what does 7.3(b) say about dental", doc_id="a", limit=3)
    assert hits[0].position == 1
    assert hits[0].page == 2  # metadata survives the round trip


def test_search_by_kind(store):
    store.upsert([_chunk("a", 0, "appeal within 180 days", kind="federal")])
    store.upsert([_chunk("b", 0, "appeal within 180 days", kind="policy")])
    assert {h.kind for h in store.hybrid_search("appeal", kind="federal")} == {"federal"}
