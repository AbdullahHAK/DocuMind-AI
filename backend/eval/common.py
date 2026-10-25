"""Shared helpers for the evaluation scripts."""

import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from qdrant_client import QdrantClient  # noqa: E402

from app.config import Settings  # noqa: E402
from app.embeddings import build_embedder  # noqa: E402
from app.indexer import index_federal_corpus, index_policy_pdf  # noqa: E402
from app.retrieval import Retriever  # noqa: E402
from app.vectorstore import VectorStore  # noqa: E402

SAMPLE_PDF = BACKEND_DIR / "data" / "samples" / "evergreen-silver-3000-ppo.pdf"
EVAL_DOC_ID = "sample-evergreen"


def load_questions() -> list[dict]:
    return json.loads((Path(__file__).parent / "questions.json").read_text(encoding="utf-8"))["questions"]


def build_retriever(settings: Settings | None = None) -> Retriever:
    """Index the sample + federal corpus into a throwaway in-memory Qdrant."""
    settings = settings or Settings()
    embedder = build_embedder(settings)
    store = VectorStore(QdrantClient(":memory:"), "eval", embedder)
    store.ensure_collection()
    index_federal_corpus(store, settings)
    index_policy_pdf(store, SAMPLE_PDF, doc_id=EVAL_DOC_ID, title="Evergreen Silver 3000 PPO", settings=settings)
    return Retriever(store, embedder, settings)
