"""A clause graph built from the policy's own cross-references.

Insurance policies constantly point at each other: "GLP-1 drugs are covered
for diabetes. Drugs prescribed primarily for weight loss are excluded
(see 7.5)." Answering "is Wegovy covered?" correctly needs BOTH clauses, but
similarity search only finds the one that sounds like the question.

So we build a small graph at indexing time:

    nodes  = clauses, identified by their number ("6.4", "7.5", "4")
    edges  = "this chunk references that clause" (see 7.5, Section 3.10, ...)

Edges are stored on each chunk's payload in Qdrant (`refs` = chunk ids), so
there is no extra database. At question time the retriever follows the
edges of the top-ranked chunks one hop out and adds the referenced clauses
to the context: one lookup by id, no LLM calls.

This is deliberately narrower than LLM-built knowledge graphs ("GraphRAG"):
cross-references are explicit in the text, so extracting them with a regex
is exact, free and testable, while LLM entity extraction costs a call per
chunk and can invent relationships.
"""

import re
from collections import defaultdict

from app.models import Chunk

# "see 7.5", "(see Section 4)", "described in Section 3.10", "listed in 3.11", "under Section 6"
REFERENCE = re.compile(
    r"\b(?:see|in|under|per|described in|listed in|defined in)\s+(?:section\s+)?(\d{1,2}(?:\.\d{1,2})?)\b(?!\s*%)",
    re.IGNORECASE,
)
# leading clause number of a section label part: "7.3 Dental and Vision" -> "7.3"
CLAUSE_NUMBER = re.compile(r"^(\d{1,2}(?:\.\d{1,2})?)\b")
MAJOR_NUMBER = re.compile(r"^(?:SECTION|Section|ARTICLE|Article|PART|Part)\s+(\d{1,2})\b")

MAX_REFS_PER_CHUNK = 4
CHUNKS_PER_TARGET = 2  # a referenced clause may span several chunks; take its first two


def clause_key(section: str | None) -> str | None:
    """'SECTION 7 - EXCLUSIONS › 7.3 Dental and Vision' -> '7.3';  'SECTION 4 - PRIOR AUTH' -> '4'."""
    if not section:
        return None
    parts = [p.strip() for p in section.split("›")]
    minor = CLAUSE_NUMBER.match(parts[-1])
    if minor:
        return minor.group(1)
    major = MAJOR_NUMBER.match(parts[0])
    return major.group(1) if major else None


def references(text: str) -> list[str]:
    seen: list[str] = []
    for m in REFERENCE.finditer(text):
        if m.group(1) not in seen:
            seen.append(m.group(1))
    return seen


def link_chunks(chunks: list[Chunk]) -> int:
    """Fill chunk.extra['refs'] with the chunk ids each chunk points to. Returns the edge count."""
    by_clause: dict[str, list[Chunk]] = defaultdict(list)
    by_major: dict[str, list[Chunk]] = defaultdict(list)
    for chunk in chunks:
        key = clause_key(chunk.section)
        if key:
            by_clause[key].append(chunk)
            by_major[key.split(".")[0]].append(chunk)

    edges = 0
    for chunk in chunks:
        own = clause_key(chunk.section)
        targets: list[str] = []
        for ref in references(chunk.text):
            if ref == own:
                continue
            # "7.5" -> that clause; "4" -> the start of section 4 (its first subsections)
            candidates = by_clause.get(ref) if "." in ref else (by_clause.get(ref) or by_major.get(ref))
            for target in (candidates or [])[:CHUNKS_PER_TARGET]:
                if target.chunk_id != chunk.chunk_id and target.chunk_id not in targets:
                    targets.append(target.chunk_id)
        chunk.extra["refs"] = targets[:MAX_REFS_PER_CHUNK]
        edges += len(chunk.extra["refs"])
    return edges
