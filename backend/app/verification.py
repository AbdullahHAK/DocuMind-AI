"""Check the LLM's answer against the sources before anyone sees it.

LLMs can "cite" text that isn't there. For a coverage question that's the
worst possible failure, so every policy quote must actually appear in the
excerpt it claims to come from. Matching is whitespace/punctuation tolerant
(PDF text has odd line breaks and curly quotes) with a small fuzzy margin.

If a coverage verdict ends up with zero verified citations, it is
downgraded to "unclear" - we never show "Covered" without evidence.
"""

import html
import re
from difflib import SequenceMatcher

from app.retrieval import ScoredChunk
from app.schemas import Citation, FederalReference, LLMAnswer

EVIDENCE_REQUIRED = {"covered", "covered_with_conditions", "not_covered"}
FUZZY_MIN_RATIO = 0.9

_TRANSLATE = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-"})


def normalize(text: str) -> str:
    text = html.unescape(text).translate(_TRANSLATE).lower()
    text = re.sub(r"[^\w$%'\-]+", " ", text)  # keep words, $, %, apostrophes, hyphens
    return re.sub(r"\s+", " ", text).strip()


def quote_matches(quote: str, source_text: str) -> bool:
    q, s = normalize(quote), normalize(source_text)
    if not q or len(q) < 8:
        return False
    if q in s:
        return True
    # fuzzy: slide a window of the quote's length (in words) over the source
    q_words, s_words = q.split(), s.split()
    n = len(q_words)
    if n > len(s_words):
        return False
    best = 0.0
    for i in range(len(s_words) - n + 1):
        best = max(best, SequenceMatcher(None, q, " ".join(s_words[i : i + n])).ratio())
        if best >= FUZZY_MIN_RATIO:
            return True
    return False


def verify_citations(
    answer: LLMAnswer, policy_sources: dict[str, ScoredChunk], federal_sources: dict[str, ScoredChunk]
) -> tuple[str, list[Citation], list[FederalReference], list[str]]:
    """Returns (verdict, verified_citations, federal_refs, warnings)."""
    warnings: list[str] = []
    citations: list[Citation] = []
    seen: set[tuple[str, str]] = set()

    for cit in answer.policy_citations:
        source = policy_sources.get(cit.source_id)
        key = (cit.source_id, normalize(cit.quote))
        if source is None or key in seen or not quote_matches(cit.quote, source.chunk.text):
            continue
        seen.add(key)
        citations.append(
            Citation(source_id=cit.source_id, quote=cit.quote.strip(), page=source.chunk.page, section=source.chunk.section)
        )

    dropped = len(answer.policy_citations) - len(citations)
    if dropped:
        warnings.append(f"{dropped} citation(s) couldn't be verified against your policy text and were removed.")

    federal: list[FederalReference] = []
    for note in answer.federal_notes:
        source = federal_sources.get(note.source_id)
        if source is None:
            continue
        federal.append(
            FederalReference(
                source_id=note.source_id, note=note.note, title=source.chunk.source_title, url=source.chunk.source_url
            )
        )

    verdict = answer.verdict
    if verdict in EVIDENCE_REQUIRED and not citations:
        verdict = "unclear"
        warnings.append("We couldn't verify this answer against your policy text, so treat it as unconfirmed.")

    return verdict, citations, federal, warnings
