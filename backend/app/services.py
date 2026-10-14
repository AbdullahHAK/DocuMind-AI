"""Builds and holds every long-lived object the API needs.

One place to wire things together (a tiny "composition root"). Tests build
the same container with fakes - in-memory Qdrant, a fake embedder, a fake
LLM client - and the routes can't tell the difference.
"""

import json
import logging
from dataclasses import dataclass, field

import anthropic
from qdrant_client import QdrantClient

from app.answering import AnswerService
from app.config import Settings
from app.documents import DocumentRecord, DocumentRegistry
from app.embeddings import Embedder
from app.indexer import index_federal_corpus, index_policy_pdf
from app.ratelimit import DailyBudget, SlidingWindowLimiter
from app.retrieval import Retriever
from app.vectorstore import VectorStore, create_client

log = logging.getLogger(__name__)

SAMPLE_DOC_ID = "sample-evergreen"
SAMPLE_PDF_NAME = "evergreen-silver-3000-ppo.pdf"
SAMPLE_TITLE = "Evergreen Silver 3000 PPO (sample)"


@dataclass
class Services:
    settings: Settings
    store: VectorStore
    registry: DocumentRegistry
    retriever: Retriever
    llm_client: anthropic.Anthropic | None
    answers: AnswerService | None
    question_limiter: SlidingWindowLimiter = field(init=False)
    upload_limiter: SlidingWindowLimiter = field(init=False)
    daily_budget: DailyBudget = field(init=False)

    def __post_init__(self) -> None:
        s = self.settings
        self.question_limiter = SlidingWindowLimiter(s.questions_per_ip_per_hour, 3600)
        self.upload_limiter = SlidingWindowLimiter(s.uploads_per_ip_per_hour, 3600)
        self.daily_budget = DailyBudget(s.questions_per_day_global)

    @property
    def llm_configured(self) -> bool:
        return self.answers is not None

    def startup(self) -> None:
        """Make sure the knowledge base and the sample policy are indexed."""
        self.store.ensure_collection()
        index_federal_corpus(self.store, self.settings)
        self._register_sample()
        self.delete_expired_uploads()

    def _register_sample(self) -> None:
        pdf = self.settings.data_dir / "samples" / SAMPLE_PDF_NAME
        facts_path = pdf.with_suffix(".facts.json")
        chunks, pages = index_policy_pdf(
            self.store, pdf, doc_id=SAMPLE_DOC_ID, title=SAMPLE_TITLE, settings=self.settings, skip_if_current=True
        )
        self.registry.save(
            DocumentRecord(
                doc_id=SAMPLE_DOC_ID,
                title=SAMPLE_TITLE,
                filename=SAMPLE_PDF_NAME,
                pdf_path=str(pdf),
                pages=pages,
                chunks=chunks,
                is_sample=True,
                facts=json.loads(facts_path.read_text(encoding="utf-8")) if facts_path.exists() else None,
            )
        )

    def delete_expired_uploads(self) -> None:
        for doc_id in self.registry.expired(self.settings.upload_ttl_hours):
            log.info("Deleting expired upload %s", doc_id)
            self.store.delete_document(doc_id)
            self.registry.delete(doc_id)


def build_llm_client(settings: Settings) -> anthropic.Anthropic | None:
    if not settings.anthropic_api_key:
        log.warning("ANTHROPIC_API_KEY is not set: retrieval works, but questions can't be answered.")
        return None
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def build_services(
    settings: Settings,
    *,
    qdrant: QdrantClient | None = None,
    embedder=None,
    llm_client: anthropic.Anthropic | None = None,
) -> Services:
    embedder = embedder or Embedder(settings)
    store = VectorStore(qdrant or create_client(settings), settings.qdrant_collection, embedder)
    llm_client = llm_client or build_llm_client(settings)
    return Services(
        settings=settings,
        store=store,
        registry=DocumentRegistry(settings.uploads_dir),
        retriever=Retriever(store, embedder, settings),
        llm_client=llm_client,
        answers=AnswerService(llm_client, settings) if llm_client else None,
    )
