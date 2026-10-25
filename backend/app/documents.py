"""A tiny on-disk registry of documents the app knows about.

Each document gets a JSON metadata file next to its PDF:

    storage/uploads/<doc_id>.pdf
    storage/uploads/<doc_id>.json

Uploads are deleted after ``upload_ttl_hours`` (privacy: insurance documents
can contain names and member IDs, so we don't keep them around). The sample
policy is registered at startup and never expires.
"""

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

DOC_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


class InvalidDocumentId(ValueError):
    pass


def validate_doc_id(doc_id: str) -> str:
    # doc_id ends up in file paths, so it must never contain "/", "..", etc.
    if not DOC_ID_PATTERN.match(doc_id):
        raise InvalidDocumentId("Invalid document id.")
    return doc_id


@dataclass
class DocumentRecord:
    doc_id: str
    title: str
    filename: str
    pdf_path: str
    pages: int
    chunks: int
    is_sample: bool = False
    facts: dict | None = None
    # lines removed at ingestion because they looked like instructions to an AI
    security_flags: list[dict] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def public(self) -> dict:
        """What the API returns (never the server-side file path)."""
        data = asdict(self)
        data.pop("pdf_path")
        return data


class DocumentRegistry:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def pdf_path(self, doc_id: str) -> Path:
        return self.root / f"{validate_doc_id(doc_id)}.pdf"

    def _meta_path(self, doc_id: str) -> Path:
        return self.root / f"{validate_doc_id(doc_id)}.json"

    def save(self, record: DocumentRecord) -> None:
        self._meta_path(record.doc_id).write_text(json.dumps(asdict(record), indent=2), encoding="utf-8")

    def get(self, doc_id: str) -> DocumentRecord | None:
        try:
            path = self._meta_path(doc_id)
        except InvalidDocumentId:
            return None
        if not path.exists():
            return None
        return DocumentRecord(**json.loads(path.read_text(encoding="utf-8")))

    def delete(self, doc_id: str) -> None:
        for path in (self._meta_path(doc_id), self.pdf_path(doc_id)):
            path.unlink(missing_ok=True)

    def expired(self, ttl_hours: int, now: datetime | None = None) -> list[str]:
        cutoff = (now or datetime.now(timezone.utc)) - timedelta(hours=ttl_hours)
        stale = []
        for meta in self.root.glob("*.json"):
            record = self.get(meta.stem)
            if record and not record.is_sample and datetime.fromisoformat(record.created_at) < cutoff:
                stale.append(record.doc_id)
        return stale
