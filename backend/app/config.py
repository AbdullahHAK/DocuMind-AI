"""Application settings, read from environment variables (or backend/.env).

Every tunable number lives here so it can be changed without touching code,
and so the README can point at one place for "how do I configure this?".
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    # --- LLM ---------------------------------------------------------------
    anthropic_api_key: str | None = None  # the SDK reads it from the env too
    llm_model: str = "claude-opus-5-5"
    llm_effort: str = "medium"  # low | medium | high | xhigh | max
    llm_max_tokens: int = 8000

    # --- Storage -----------------------------------------------------------
    data_dir: Path = BACKEND_DIR / "data"  # checked-in knowledge (federal docs, sample)
    storage_dir: Path = BACKEND_DIR / "storage"  # runtime state, git-ignored
    models_cache_dir: Path = BACKEND_DIR / ".cache" / "models"

    # Qdrant: leave qdrant_url empty to run an embedded on-disk database.
    qdrant_url: str | None = None
    qdrant_api_key: str | None = None
    qdrant_collection: str = "chunks"

    # --- Embedding / reranking models (run locally via fastembed) ----------
    dense_model: str = "BAAI/bge-small-en-v1.5"
    sparse_model: str = "Qdrant/bm25"
    rerank_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"

    # --- Chunking ----------------------------------------------------------
    chunk_max_chars: int = 1100
    chunk_overlap_chars: int = 150

    # --- Retrieval ---------------------------------------------------------
    retrieval_candidates: int = 24  # hybrid search pulls this many, reranker trims
    policy_top_k: int = 6
    federal_top_k: int = 3
    # Cross-encoder scores are logits (> 0 ~ "probably relevant"). Both values
    # were picked from the sweep in eval/run_retrieval_eval.py.
    gate_threshold: float = -6.0  # best chunk below this -> off-topic, skip the LLM
    federal_min_score: float = -2.0  # federal chunks must clear this to be attached

    # --- Uploads -----------------------------------------------------------
    max_upload_mb: int = 10
    max_upload_pages: int = 150
    upload_ttl_hours: int = 24

    # --- Abuse protection for the public demo ------------------------------
    questions_per_ip_per_hour: int = 30
    uploads_per_ip_per_hour: int = 6
    questions_per_day_global: int = 600
    trust_proxy_headers: bool = False  # set true behind a reverse proxy

    cors_origins: list[str] = ["http://localhost:5173"]

    @property
    def uploads_dir(self) -> Path:
        return self.storage_dir / "uploads"

    @property
    def qdrant_path(self) -> Path:
        return self.storage_dir / "qdrant"


@lru_cache
def get_settings() -> Settings:
    return Settings()
