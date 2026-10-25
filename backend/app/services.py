"""Builds and holds every long-lived object the API needs.

One place to wire things together (a tiny "composition root"). Tests build
the same container with fakes - in-memory Qdrant, a fake embedder, a fake
LLM client - and the routes can't tell the difference.
"""

import json
import logging
from dataclasses import dataclass, field

from qdrant_client import QdrantClient

from app.answering import AnswerService
from app.config import Settings
from app.documents import DocumentRecord, DocumentRegistry
from app.embeddings import build_embedder
from app.indexer import index_federal_corpus, index_policy_pdf
from app.llm import StructuredLLM, build_llm
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
    llm: StructuredLLM | None
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
        indexed = index_policy_pdf(
            self.store, pdf, doc_id=SAMPLE_DOC_ID, title=SAMPLE_TITLE, settings=self.settings, skip_if_current=True
        )
        self.registry.save(
            DocumentRecord(
                doc_id=SAMPLE_DOC_ID,
                title=SAMPLE_TITLE,
                filename=SAMPLE_PDF_NAME,
                pdf_path=str(pdf),
                pages=len(indexed.pages),
                chunks=indexed.chunks,
                is_sample=True,
                facts=json.loads(facts_path.read_text(encoding="utf-8")) if facts_path.exists() else None,
            )
        )

    def delete_expired_uploads(self) -> None:
        for doc_id in self.registry.expired(self.settings.upload_ttl_hours):
            log.info("Deleting expired upload %s", doc_id)
            self.store.delete_document(doc_id)
            self.registry.delete(doc_id)


def build_services(
    settings: Settings,
    *,
    qdrant: QdrantClient | None = None,
    embedder=None,
    llm: StructuredLLM | None = None,
) -> Services:
    embedder = embedder or build_embedder(settings)
    store = VectorStore(qdrant or create_client(settings), settings.collection_name, embedder)
    llm = llm or build_llm(settings)
    return Services(
        settings=settings,
        store=store,
        registry=DocumentRegistry(settings.uploads_dir),
        retriever=Retriever(store, embedder, settings),
        llm=llm,
        answers=AnswerService(llm, settings) if llm else None,
    )
