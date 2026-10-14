from app.ingest.chunker import SectionTracker, chunk_pages, make_chunk_id
from app.ingest.pdf import Page, clean_text


def _chunks(pages, **kw):
    return chunk_pages(pages, doc_id="doc", source_title="Test Policy", **kw)


def test_heading_classification():
    assert SectionTracker.classify("SECTION 7 - EXCLUSIONS AND LIMITATIONS") == "major"
    assert SectionTracker.classify("7.3 Dental and Vision") == "minor"
    assert SectionTracker.classify("4. Prior Authorization") == "minor"
    assert SectionTracker.classify("Article IV") == "major"
    # A wrapped sentence fragment that happens to start with "Section" is not a heading.
    assert SectionTracker.classify("Section 3.11.") is None
    assert SectionTracker.classify("Section 4 lists the services that need it.") is None
    # Ordinary sentences that start with a number are not headings.
    assert SectionTracker.classify("30 visits per calendar year are covered.") is None
    assert SectionTracker.classify("The plan pays 70% after the deductible") is None


def test_new_heading_starts_new_chunk_with_section_label():
    page = Page(
        1,
        "SECTION 7 - EXCLUSIONS\n"
        "7.2 Cosmetic Services\nCosmetic surgery is not covered unless it repairs an injury.\n"
        "7.3 Dental and Vision\n(b) Routine dental care for adults age 19 and older is not covered.",
    )
    chunks = _chunks([page])
    assert len(chunks) == 2
    assert chunks[0].section == "SECTION 7 - EXCLUSIONS › 7.2 Cosmetic Services"
    assert "Cosmetic surgery" in chunks[0].text
    assert chunks[1].section == "SECTION 7 - EXCLUSIONS › 7.3 Dental and Vision"
    assert "Routine dental care" in chunks[1].text


def test_wrapped_major_heading_is_rejoined():
    page = Page(
        8,
        "SECTION 5 - CARE OUT OF NETWORK AND OUTSIDE THE\nUNITED STATES\n"
        "5.3 Care Outside the United States\nEmergency services abroad are covered at the In-Network level.",
    )
    chunks = _chunks([page])
    assert chunks[-1].section == (
        "SECTION 5 - CARE OUT OF NETWORK AND OUTSIDE THE UNITED STATES › 5.3 Care Outside the United States"
    )


def test_section_carries_across_pages_but_chunks_do_not():
    pages = [
        Page(3, "7.3 Dental and Vision\nAdult dental care is not covered under this plan at all."),
        Page(4, "Pediatric vision exams are covered once per calendar year for members under 19."),
    ]
    chunks = _chunks(pages)
    assert [c.page for c in chunks] == [3, 4]
    assert chunks[1].section == "7.3 Dental and Vision"


def test_long_section_is_split_with_overlap():
    lines = [f"Line {i}: the plan covers medically necessary service number {i}." for i in range(40)]
    chunks = _chunks([Page(1, "\n".join(lines))], max_chars=400, overlap_chars=120)
    assert len(chunks) > 3
    assert all(len(c.text) <= 400 for c in chunks)
    # the last line of chunk N is repeated at the start of chunk N+1
    for a, b in zip(chunks, chunks[1:]):
        assert a.text.splitlines()[-1] in b.text


def test_tiny_fragments_are_dropped():
    assert _chunks([Page(1, "Some short footer text")]) == []


def test_heading_without_body_is_not_a_chunk():
    page = Page(1, "SECTION 5 - CARE OUTSIDE THE UNITED STATES\n5.1 Out-of-Network Care\nCovered at the out-of-network level.")
    chunks = _chunks([page])
    assert len(chunks) == 1
    assert chunks[0].text.startswith("5.1 Out-of-Network Care")


def test_chunk_ids_are_deterministic():
    assert make_chunk_id("doc", 3) == make_chunk_id("doc", 3)
    assert make_chunk_id("doc", 3) != make_chunk_id("other", 3)


def test_embedding_text_includes_section_header():
    page = Page(1, "7.3 Dental and Vision\nNot covered for adults, including cleanings and fillings.")
    (chunk,) = _chunks([page])
    assert chunk.embedding_text().startswith("7.3 Dental and Vision\n")


def test_clean_text_rejoins_hyphenated_words():
    assert clean_text("cover-\nage  is   limited") == "coverage is limited"


def test_clean_text_drops_page_number_lines():
    assert clean_text("Page 11\n7.5 Weight Management\nText.\n3 of 40") == "7.5 Weight Management\nText."
    # bare numbers may be real table values (e.g. a visit limit), so they are kept
    assert clean_text("Visit limit\n12") == "Visit limit\n12"
