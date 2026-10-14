"""Split document pages into section-aware chunks.

Why not just cut every N characters? Insurance documents are organised as
numbered sections ("7.3 Dental and Vision"), and a clause only makes sense
together with its heading. So this chunker:

1. never lets a chunk span two sections (a new heading starts a new chunk),
2. never lets a chunk span two pages (so every citation has one page number),
3. packs lines up to ``max_chars`` and repeats a little text (``overlap_chars``)
   when a long section has to be split, so a sentence cut at the boundary
   still appears whole in one of the two chunks.
"""

import re
import uuid

from app.ingest.pdf import Page
from app.models import Chunk, ChunkKind

# "SECTION 7 - EXCLUSIONS", "Article IV", "PART 2: Benefits". The number must be
# followed by nothing or by a separator + title, so a wrapped sentence fragment
# like "Section 3.11." is NOT mistaken for a heading.
MAJOR_HEADING = re.compile(
    r"^(?:SECTION|Section|ARTICLE|Article|PART|Part)\s+[\dIVXL]+(?:\s*[-–—:.]?\s+[A-Z][^.]{1,80})?$"
)
# Continuation of a major heading wrapped onto a second line: "UNITED STATES"
HEADING_CONTINUATION = re.compile(r"^[A-Z][A-Z0-9 ,&/'()\-]{1,60}$")
# "7.3 Dental and Vision", "4. Prior Authorization" - short, title-like lines only
MINOR_HEADING = re.compile(r"^\d{1,2}(?:\.\d{1,2}){0,2}\.?\s+[A-Z][A-Za-z0-9 ,&/'()\-]{2,70}$")
SENTENCE_END = re.compile(r"(?<=[.;:!?])\s+")

MIN_CHUNK_CHARS = 40


class SectionTracker:
    """Remembers the current major + minor heading while we walk the document."""

    def __init__(self) -> None:
        self.major: str | None = None
        self.minor: str | None = None

    @staticmethod
    def classify(line: str) -> str | None:
        if MAJOR_HEADING.match(line):
            return "major"
        if MINOR_HEADING.match(line) and not line.rstrip().endswith("."):
            return "minor"
        return None

    def update(self, line: str, level: str) -> None:
        if level == "major":
            self.major, self.minor = line, None
        else:
            self.minor = line

    @property
    def label(self) -> str | None:
        parts = [p for p in (self.major, self.minor) if p]
        return " › ".join(parts) or None


def _split_long_line(line: str, max_chars: int) -> list[str]:
    """Break a line that alone exceeds max_chars at sentence ends (or hard-wrap)."""
    if len(line) <= max_chars:
        return [line]
    pieces, current = [], ""
    for sentence in SENTENCE_END.split(line):
        while len(sentence) > max_chars:  # a single monster sentence
            pieces.append(sentence[:max_chars])
            sentence = sentence[max_chars:]
        if current and len(current) + 1 + len(sentence) > max_chars:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)
    return pieces


def _overlap_tail(lines: list[str], overlap_chars: int) -> list[str]:
    """The last few lines of a chunk, up to overlap_chars, to repeat in the next one."""
    tail, size = [], 0
    for line in reversed(lines):
        if size + len(line) > overlap_chars:
            break
        tail.insert(0, line)
        size += len(line)
    return tail


def make_chunk_id(doc_id: str, position: int) -> str:
    # Deterministic: re-indexing the same document overwrites instead of duplicating.
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{doc_id}#{position}"))


def chunk_pages(
    pages: list[Page],
    *,
    doc_id: str,
    source_title: str,
    kind: ChunkKind = "policy",
    max_chars: int = 1100,
    overlap_chars: int = 150,
) -> list[Chunk]:
    tracker = SectionTracker()
    chunks: list[Chunk] = []
    buffer: list[str] = []
    buffer_section: str | None = None
    buffer_has_new_text = False  # False when the buffer holds only overlap

    def flush(page_number: int) -> None:
        nonlocal buffer, buffer_has_new_text
        text = "\n".join(buffer).strip()
        if buffer_has_new_text and len(text) >= MIN_CHUNK_CHARS:
            chunks.append(
                Chunk(
                    chunk_id=make_chunk_id(doc_id, len(chunks)),
                    doc_id=doc_id,
                    kind=kind,
                    text=text,
                    position=len(chunks),
                    source_title=source_title,
                    page=page_number,
                    section=buffer_section,
                )
            )
        buffer, buffer_has_new_text = [], False

    for page in pages:
        buffer_section = tracker.label
        previous_was_major = False
        for raw_line in page.text.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            level = SectionTracker.classify(line)
            if previous_was_major and not level and HEADING_CONTINUATION.match(line):
                # second line of a long all-caps heading: glue it back on
                tracker.update(f"{tracker.major} {line}", "major")
                buffer_section = tracker.label
                buffer[-1] = tracker.major
                continue
            previous_was_major = level == "major"
            if level:
                flush(page.number)
                tracker.update(line, level)
                buffer_section = tracker.label

            for piece in _split_long_line(line, max_chars):
                if buffer and len("\n".join(buffer)) + 1 + len(piece) > max_chars:
                    tail = _overlap_tail(buffer, overlap_chars)
                    flush(page.number)
                    buffer = tail
                buffer.append(piece)
                # a heading on its own isn't worth a chunk; it rides along with the
                # text that follows it
                buffer_has_new_text = buffer_has_new_text or not level

        flush(page.number)  # chunks never cross a page boundary

    return chunks
