"""Ingestion pipeline: file -> pages -> chunks -> vectors in Qdrant.

Indexing is idempotent: every chunk is stamped with a content hash ("version").
On startup we only re-embed the federal corpus or the sample policy if their
content actually changed, so restarts are fast.
"""

import hashlib
import logging
from pathlib import Path

from app.config import Settings
from app.ingest.chunker import chunk_pages
from app.ingest.markdown import load_federal_corpus
from app.ingest.pdf import load_pdf
from app.models import Chunk
from app.vectorstore import VectorStore

log = logging.getLogger(__name__)

FEDERAL_DOC_ID = "federal"


def content_hash(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def _stamp(chunks: list[Chunk], version: str) -> list[Chunk]:
    for chunk in chunks:
        chunk.extra["version"] = version
    return chunks


def _replace(store: VectorStore, doc_id: str, chunks: list[Chunk]) -> None:
    store.delete_document(doc_id)
    store.upsert(chunks)


def index_federal_corpus(store: VectorStore, settings: Settings) -> int:
    directory = settings.data_dir / "federal"
    version = content_hash([p for p in directory.glob("*.md")])
    chunks = load_federal_corpus(directory, doc_id=FEDERAL_DOC_ID, max_chars=settings.chunk_max_chars)
    if store.count(doc_id=FEDERAL_DOC_ID, version=version) == len(chunks):
        log.info("Federal corpus up to date (%d chunks)", len(chunks))
        return len(chunks)
    log.info("Indexing federal corpus: %d chunks", len(chunks))
    _replace(store, FEDERAL_DOC_ID, _stamp(chunks, version))
    return len(chunks)


def chunk_policy_pdf(path: Path, *, doc_id: str, title: str, settings: Settings) -> tuple[list[Chunk], int]:
    """Load and chunk a policy PDF. Returns (chunks, page_count). Raises PdfLoadError."""
    pages = load_pdf(path, max_pages=settings.max_upload_pages)
    chunks = chunk_pages(
        pages,
        doc_id=doc_id,
        source_title=title,
        kind="policy",
        max_chars=settings.chunk_max_chars,
        overlap_chars=settings.chunk_overlap_chars,
    )
    return chunks, len(pages)


def index_policy_pdf(
    store: VectorStore, path: Path, *, doc_id: str, title: str, settings: Settings, skip_if_current: bool = False
) -> tuple[int, int]:
    """Index a policy PDF. Returns (chunk_count, page_count)."""
    version = content_hash([path])
    chunks, page_count = chunk_policy_pdf(path, doc_id=doc_id, title=title, settings=settings)
    if skip_if_current and store.count(doc_id=doc_id, version=version) == len(chunks):
        log.info("%s up to date (%d chunks)", doc_id, len(chunks))
        return len(chunks), page_count
    log.info("Indexing %s: %d pages, %d chunks", doc_id, page_count, len(chunks))
    _replace(store, doc_id, _stamp(chunks, version))
    return len(chunks), page_count
