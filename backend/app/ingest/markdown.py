"""Load the curated federal-rules knowledge base (Markdown files) into chunks.

Each file starts with a tiny front-matter block:

    ---
    title: No Surprises Act
    source_url: https://www.cms.gov/nosurprises
    ---

and is split on "## " headings, so every chunk is one self-contained rule.
"""

import re
from pathlib import Path

from app.ingest.chunker import _split_long_line, make_chunk_id
from app.models import Chunk

FRONT_MATTER = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


def parse_front_matter(raw: str) -> tuple[dict, str]:
    match = FRONT_MATTER.match(raw)
    if not match:
        return {}, raw
    meta = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    return meta, raw[match.end():]


def _pack(paragraphs: list[str], max_chars: int) -> list[str]:
    out, current = [], ""
    for para in paragraphs:
        for piece in _split_long_line(para, max_chars):
            if current and len(current) + 2 + len(piece) > max_chars:
                out.append(current)
                current = piece
            else:
                current = f"{current}\n\n{piece}".strip()
    if current:
        out.append(current)
    return out


def chunk_markdown(path: Path, *, doc_id: str, start_position: int = 0, max_chars: int = 1100) -> list[Chunk]:
    raw = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    meta, body = parse_front_matter(raw)
    title = meta.get("title", path.stem)
    chunks: list[Chunk] = []

    for block in re.split(r"^## ", body, flags=re.MULTILINE):
        block = block.strip()
        if not block or block.startswith("# "):  # skip the H1 / intro-less preamble
            continue
        heading, _, text = block.partition("\n")
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        for piece in _pack(paragraphs, max_chars):
            position = start_position + len(chunks)
            chunks.append(
                Chunk(
                    chunk_id=make_chunk_id(doc_id, position),
                    doc_id=doc_id,
                    kind="federal",
                    text=piece,
                    position=position,
                    source_title=title,
                    section=f"{title} › {heading.strip()}",
                    source_url=meta.get("source_url"),
                )
            )
    return chunks


def load_federal_corpus(directory: Path, *, doc_id: str = "federal", max_chars: int = 1100) -> list[Chunk]:
    chunks: list[Chunk] = []
    for path in sorted(directory.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        chunks.extend(chunk_markdown(path, doc_id=doc_id, start_position=len(chunks), max_chars=max_chars))
    return chunks
