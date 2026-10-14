"""Core data types shared across ingestion, retrieval and answering."""

from dataclasses import dataclass, field
from typing import Literal

ChunkKind = Literal["policy", "federal"]


@dataclass
class Chunk:
    """One retrievable piece of a document, plus where it came from.

    The metadata (page, section, source) is what lets us show a citation like
    "Section 7.3 Dental, page 14" instead of an anonymous blob of text.
    """

    chunk_id: str
    doc_id: str
    kind: ChunkKind
    text: str
    position: int  # order within the document
    source_title: str
    page: int | None = None
    section: str | None = None
    source_url: str | None = None
    extra: dict = field(default_factory=dict)

    def embedding_text(self) -> str:
        """Text that gets embedded: the section header is prepended so a chunk that
        only says "Not covered." still carries "7.3 Dental and Vision" in its vector."""
        header = self.section or self.source_title
        return f"{header}\n{self.text}" if header else self.text

    def to_payload(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "kind": self.kind,
            "text": self.text,
            "position": self.position,
            "source_title": self.source_title,
            "page": self.page,
            "section": self.section,
            "source_url": self.source_url,
            **self.extra,
        }

    @classmethod
    def from_payload(cls, payload: dict) -> "Chunk":
        known = {"chunk_id", "doc_id", "kind", "text", "position", "source_title", "page", "section", "source_url"}
        return cls(
            **{k: payload.get(k) for k in known},
            extra={k: v for k, v in payload.items() if k not in known},
        )
