"""Precompute Gemini embeddings for the bundled documents.

In EMBEDDING_PROVIDER=gemini mode the app indexes the federal rules and the
sample policy at every cold start. On the free tier each embedded text costs
one request out of 100 per minute, so ~100 texts at startup would eat the
whole minute's quota. This script embeds exactly the texts the indexer sends
(same chunking, same section headers) once, and writes them to
data/embeddings/<model>-<dims>.json. GeminiEmbedder uses that file first and
only calls the API for texts it doesn't contain (user uploads, questions).

Re-run it after changing the federal docs, the sample policy or the chunker:
  EMBEDDING_PROVIDER=gemini python scripts/precompute_embeddings.py
"""

import base64
import json
import sys
from array import array
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings  # noqa: E402
from app.embeddings import GeminiEmbedder, precomputed_key, precomputed_path  # noqa: E402
from app.ingest.chunker import chunk_pages  # noqa: E402
from app.ingest.markdown import load_federal_corpus  # noqa: E402
from app.indexer import load_policy_pages  # noqa: E402
from app.services import SAMPLE_DOC_ID, SAMPLE_PDF_NAME, SAMPLE_TITLE  # noqa: E402


def bundled_texts(settings: Settings) -> list[str]:
    federal = load_federal_corpus(settings.data_dir / "federal", max_chars=settings.chunk_max_chars)
    pages, _ = load_policy_pages(settings.data_dir / "samples" / SAMPLE_PDF_NAME, settings)
    sample = chunk_pages(pages, doc_id=SAMPLE_DOC_ID, source_title=SAMPLE_TITLE, kind="policy",
                         max_chars=settings.chunk_max_chars, overlap_chars=settings.chunk_overlap_chars)
    return [c.embedding_text() for c in federal + sample]


def main() -> None:
    settings = Settings(embedding_provider="gemini")
    if not settings.gemini_api_key:
        raise SystemExit("GEMINI_API_KEY is required")
    texts = sorted(set(bundled_texts(settings)))
    embedder = GeminiEmbedder(settings)
    embedder._precomputed = {}  # always recompute from the API
    print(f"embedding {len(texts)} bundled texts with {settings.gemini_embedding_model} ({settings.embedding_dimensions} dims)…")
    vectors = embedder._embed(texts, "RETRIEVAL_DOCUMENT")
    out = {
        "model": settings.gemini_embedding_model,
        "dimensions": settings.embedding_dimensions,
        "task_type": "RETRIEVAL_DOCUMENT",
        "vectors": {
            precomputed_key("RETRIEVAL_DOCUMENT", t): base64.b64encode(array("f", v).tobytes()).decode("ascii")
            for t, v in zip(texts, vectors)
        },
    }
    path = precomputed_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=0), encoding="utf-8")
    print(f"wrote {path} ({path.stat().st_size // 1024} KB, {len(vectors)} vectors)")


if __name__ == "__main__":
    main()
