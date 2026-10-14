from app.models import Chunk
from app.retrieval import ScoredChunk
from app.schemas import LLMAnswer, LLMFederalNote, LLMPolicyCitation
from app.verification import quote_matches, verify_citations

POLICY_TEXT = (
    "7.3 Dental and Vision Services\n(b) Routine dental care for members age 19 and older is not covered. "
    "This includes cleanings, X-rays, fillings, crowns, root canals, extractions,\northodontics, implants and dentures."
)


def _sources():
    policy = {"P1": ScoredChunk(Chunk("a", "d", "policy", POLICY_TEXT, 0, "Policy", page=10, section="7.3 Dental"), 5.0)}
    federal = {"F1": ScoredChunk(Chunk("b", "federal", "federal", "Adult dental is not an EHB.", 0, "EHB", source_url="https://x"), 2.0)}
    return policy, federal


def _answer(verdict="not_covered", citations=(), federal=()):
    return LLMAnswer(
        verdict=verdict, headline="h", explanation="e",
        policy_citations=[LLMPolicyCitation(source_id=s, quote=q) for s, q in citations],
        conditions=[], exclusions=[], questions_to_ask=[], cost_rule=None,
        federal_notes=[LLMFederalNote(source_id=s, note="n") for s in federal],
    )


def test_exact_quote_matches():
    assert quote_matches("Routine dental care for members age 19 and older is not covered.", POLICY_TEXT)


def test_quote_across_pdf_line_break_and_curly_quotes_matches():
    assert quote_matches("extractions, orthodontics, implants and dentures", POLICY_TEXT)
    assert quote_matches("Routine dental care for members age 19 and older is not covered’", POLICY_TEXT)


def test_small_typo_still_matches_but_invented_text_does_not():
    assert quote_matches("Routine dental care for member age 19 and older is not covered", POLICY_TEXT)
    assert not quote_matches("Routine dental care for adults is fully covered at 100%", POLICY_TEXT)


def test_too_short_quotes_are_rejected():
    assert not quote_matches("is", POLICY_TEXT)


def test_verified_citation_gets_page_and_section():
    policy, federal = _sources()
    verdict, cits, fed, warnings = verify_citations(
        _answer(citations=[("P1", "Routine dental care for members age 19 and older is not covered.")], federal=["F1"]),
        policy, federal,
    )
    assert verdict == "not_covered"
    assert (cits[0].page, cits[0].section) == (10, "7.3 Dental")
    assert fed[0].title == "EHB" and fed[0].url == "https://x"
    assert warnings == []


def test_fabricated_citation_is_dropped_and_verdict_downgraded():
    policy, federal = _sources()
    verdict, cits, _, warnings = verify_citations(
        _answer(verdict="covered", citations=[("P1", "Adult dental cleanings are covered twice a year.")]), policy, federal
    )
    assert cits == []
    assert verdict == "unclear"
    assert len(warnings) == 2


def test_unknown_source_ids_are_ignored():
    policy, federal = _sources()
    verdict, cits, fed, _ = verify_citations(
        _answer(verdict="informational", citations=[("P9", "anything at all here")], federal=["F7"]), policy, federal
    )
    assert cits == [] and fed == []
    assert verdict == "informational"  # informational answers don't require policy evidence


def test_duplicate_citations_are_collapsed():
    policy, federal = _sources()
    q = "Routine dental care for members age 19 and older is not covered."
    _, cits, _, _ = verify_citations(_answer(citations=[("P1", q), ("P1", q)]), policy, federal)
    assert len(cits) == 1
