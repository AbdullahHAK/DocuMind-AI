"""Qdrant wrapper: store chunks with two vectors each and run hybrid search.

Hybrid search = run a dense (meaning) search and a sparse BM25 (keyword) search,
then merge both ranked lists with Reciprocal Rank Fusion (RRF). RRF only looks
at *rank positions*, so we don't have to make cosine scores and BM25 scores
comparable - a chunk ranked high by either method rises to the top.
"""

import warnings

from qdrant_client import QdrantClient, models

from app.config import Settings
from app.models import Chunk, ChunkKind

DENSE = "dense"
SPARSE = "bm25"


def create_client(settings: Settings) -> QdrantClient:
    if settings.qdrant_url:
        return QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)
    settings.qdrant_path.mkdir(parents=True, exist_ok=True)
    return QdrantClient(path=str(settings.qdrant_path))  # embedded, on-disk


def _filter(doc_id: str | None = None, kind: ChunkKind | None = None, version: str | None = None):
    conditions = [
        models.FieldCondition(key=key, match=models.MatchValue(value=value))
        for key, value in (("doc_id", doc_id), ("kind", kind), ("version", version))
        if value is not None
    ]
    return models.Filter(must=conditions) if conditions else None


class VectorStore:
    def __init__(self, client: QdrantClient, collection: str, embedder) -> None:
        self.client = client
        self.collection = collection
        self.embedder = embedder

    def ensure_collection(self) -> None:
        if self.client.collection_exists(self.collection):
            return
        self.client.create_collection(
            self.collection,
            vectors_config={DENSE: models.VectorParams(size=self.embedder.dense_size, distance=models.Distance.COSINE)},
            # IDF modifier: Qdrant computes inverse document frequency for us, completing BM25
            sparse_vectors_config={SPARSE: models.SparseVectorParams(modifier=models.Modifier.IDF)},
        )
        # Indexes make filtered search fast on a Qdrant server; embedded mode
        # ignores them (and warns), which is fine at demo scale.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            for field in ("doc_id", "kind", "version"):
                self.client.create_payload_index(self.collection, field, models.PayloadSchemaType.KEYWORD)

    def upsert(self, chunks: list[Chunk], batch_size: int = 64) -> None:
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            dense, sparse = self.embedder.embed_documents([c.embedding_text() for c in batch])
            self.client.upsert(
                self.collection,
                points=[
                    models.PointStruct(
                        id=chunk.chunk_id,
                        vector={
                            DENSE: d,
                            SPARSE: models.SparseVector(indices=s.indices, values=s.values),
                        },
                        payload=chunk.to_payload(),
                    )
                    for chunk, d, s in zip(batch, dense, sparse)
                ],
            )

    def delete_document(self, doc_id: str) -> None:
        self.client.delete(self.collection, points_selector=models.FilterSelector(filter=_filter(doc_id=doc_id)))

    def count(self, *, doc_id: str | None = None, kind: ChunkKind | None = None, version: str | None = None) -> int:
        return self.client.count(self.collection, count_filter=_filter(doc_id, kind, version), exact=True).count

    def get_chunks(self, chunk_ids: list[str]) -> list[Chunk]:
        """Fetch chunks by id - used to follow graph edges (no vector search needed)."""
        if not chunk_ids:
            return []
        points = self.client.retrieve(self.collection, ids=chunk_ids, with_payload=True)
        by_id = {str(p.id): Chunk.from_payload(p.payload) for p in points}
        return [by_id[cid] for cid in chunk_ids if cid in by_id]

    def hybrid_search(
        self, query: str, *, doc_id: str | None = None, kind: ChunkKind | None = None, limit: int = 24
    ) -> list[Chunk]:
        dense, sparse = self.embedder.embed_query(query)
        query_filter = _filter(doc_id, kind)
        result = self.client.query_points(
            self.collection,
            prefetch=[
                models.Prefetch(query=dense, using=DENSE, limit=limit, filter=query_filter),
                models.Prefetch(
                    query=models.SparseVector(indices=sparse.indices, values=sparse.values),
                    using=SPARSE,
                    limit=limit,
                    filter=query_filter,
                ),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=limit,
            with_payload=True,
        )
        return [Chunk.from_payload(point.payload) for point in result.points]
