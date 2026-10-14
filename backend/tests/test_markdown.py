from app.ingest.markdown import chunk_markdown, load_federal_corpus, parse_front_matter

DOC = """---
title: No Surprises Act
source_url: https://www.cms.gov/nosurprises
---

## What it protects

Emergency services are protected.

## Help desk

Call 1-800-985-3059.
"""


def test_front_matter_is_parsed_and_removed():
    meta, body = parse_front_matter(DOC)
    assert meta == {"title": "No Surprises Act", "source_url": "https://www.cms.gov/nosurprises"}
    assert not body.startswith("---")


def test_each_heading_becomes_a_federal_chunk_with_source(tmp_path):
    path = tmp_path / "nsa.md"
    path.write_text(DOC, encoding="utf-8")
    chunks = chunk_markdown(path, doc_id="federal")
    assert [c.section for c in chunks] == ["No Surprises Act › What it protects", "No Surprises Act › Help desk"]
    assert all(c.kind == "federal" and c.source_url == "https://www.cms.gov/nosurprises" for c in chunks)
    assert chunks[1].text == "Call 1-800-985-3059."


def test_corpus_skips_readme_and_numbers_positions_globally(tmp_path):
    (tmp_path / "README.md").write_text("## Not a rule\n\nignored", encoding="utf-8")
    (tmp_path / "a.md").write_text(DOC, encoding="utf-8")
    (tmp_path / "b.md").write_text(DOC.replace("No Surprises Act", "Other"), encoding="utf-8")
    chunks = load_federal_corpus(tmp_path)
    assert len(chunks) == 4
    assert [c.position for c in chunks] == [0, 1, 2, 3]
    assert len({c.chunk_id for c in chunks}) == 4


def test_real_corpus_has_sources_for_every_chunk():
    from pathlib import Path

    chunks = load_federal_corpus(Path(__file__).resolve().parent.parent / "data" / "federal")
    assert len(chunks) > 40
    assert all(c.source_url and c.source_url.startswith("https://") for c in chunks)
