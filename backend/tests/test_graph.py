from pathlib import Path

from app.graph import clause_key, link_chunks, references
from app.ingest.chunker import chunk_pages
from app.ingest.pdf import load_pdf
from app.models import Chunk

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "samples" / "evergreen-silver-3000-ppo.pdf"


def test_clause_key():
    assert clause_key("SECTION 7 - EXCLUSIONS AND LIMITATIONS › 7.3 Dental and Vision Services") == "7.3"
    assert clause_key("SECTION 4 - PRIOR AUTHORIZATION") == "4"
    assert clause_key("SECTION 10 - COVERAGE EXAMPLES › 10.2 A Simple Fracture") == "10.2"
    assert clause_key(None) is None


def test_reference_extraction():
    assert references("Drugs prescribed primarily for weight loss are excluded (see 7.5).") == ["7.5"]
    assert references("covered as described in Section 3.10. Hearing exams: see Section 3.11") == ["3.10", "3.11"]
    assert references("Prior Authorization is required (see Section 4).") == ["4"]
    # numbers that aren't clause references
    assert references("You pay 30% in 2026, up to 12 visits.") == []


def _chunk(cid, section, text):
    return Chunk(chunk_id=cid, doc_id="d", kind="policy", text=text, position=0, source_title="T", section=section)


def test_link_chunks_builds_edges_and_skips_self_references():
    chunks = [
        _chunk("a", "SECTION 6 › 6.4 Insulin", "Weight loss drugs are excluded (see 7.5). See 6.4 for insulin."),
        _chunk("b", "SECTION 7 › 7.5 Weight Management", "(b) Drugs for weight loss are not covered."),
        _chunk("c", "SECTION 4 - PRIOR AUTHORIZATION › 4.1 Services", "MRI needs approval."),
        _chunk("d", "SECTION 3 › 3.4 Imaging", "Prior Authorization is required (see Section 4)."),
    ]
    edges = link_chunks(chunks)
    refs = {c.chunk_id: c.extra["refs"] for c in chunks}
    assert refs["a"] == ["b"]  # 6.4 -> 7.5, the self-reference to 6.4 is ignored
    assert refs["d"] == ["c"]  # "Section 4" -> first subsection of section 4
    assert refs["b"] == [] and edges == 2


def test_sample_policy_graph_contains_the_known_cross_references():
    chunks = chunk_pages(load_pdf(SAMPLE), doc_id="s", source_title="Sample")
    link_chunks(chunks)
    by_id = {c.chunk_id: c for c in chunks}

    def linked(from_clause: str) -> set[str]:
        out = set()
        for c in chunks:
            if clause_key(c.section) == from_clause:
                out |= {clause_key(by_id[r].section) for r in c.extra["refs"]}
        return out

    assert "7.5" in linked("6.4")  # weight-loss drug exclusion
    assert "7.10" in linked("5.3")  # no medical evacuation from abroad
    assert "7.8" in linked("3.11")  # adult hearing aids excluded
    assert "3.10" in linked("7.3")  # pediatric dental/vision IS covered
