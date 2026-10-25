# 05 · Database and data model

**There is no relational or document database.** Persistence is:

| Store | Technology | Location | Lifetime |
|---|---|---|---|
| Vector store | Qdrant (embedded local mode, or a server via `QDRANT_URL`) | `backend/storage/qdrant/` | until re-index / expiry |
| Document registry | one JSON file per document | `backend/storage/uploads/<doc_id>.json` | 24 h for uploads; samples forever |
| Uploaded files | raw PDF | `backend/storage/uploads/<doc_id>.pdf` | same as its record |
| Bundled knowledge | Markdown + PDF + JSON in git | `backend/data/` | versioned with the code |
| Abuse counters | Python dict/deque | process memory | until restart |
| Model cache | ONNX files | `backend/.cache/models/` | until deleted |
| Browser | `localStorage` key `amicovered:doc` | user's browser | until cleared |

There are **no migrations**. Schema evolution of the vector index is handled by **content-hash versioning**: `indexer.content_hash` hashes `PIPELINE_VERSION` plus the file bytes and stamps every chunk's `version`. On startup, bundled documents whose stored version or count differ are deleted and re-indexed. Uploaded documents are never re-indexed: they keep the payload shape from the pipeline version that indexed them until they expire. (Verified: `indexer.py` `content_hash`, `index_policy_pdf(skip_if_current=…)`.)

## Qdrant collection `chunks`

Created by `VectorStore.ensure_collection` (vectorstore.py 42-56):

- **Named vectors:** `dense`: 384 floats, cosine (bge-small-en-v1.5). `bm25`: sparse, with Qdrant's `Modifier.IDF`, so Qdrant computes the inverse document frequency.
- **Payload indexes:** keyword on `doc_id`, `kind`, `version`. In embedded mode Qdrant ignores payload indexes (the code suppresses the warning); they take effect only on a Qdrant server.
- **Point id:** `uuid5(NAMESPACE_URL, f"{doc_id}#{position}")` (`chunker.make_chunk_id`). Deterministic, so re-indexing overwrites.

| Payload field | Type | Written by | Notes |
|---|---|---|---|
| `chunk_id` | uuid str | `Chunk.to_payload` | equals point id |
| `doc_id` | str | | `federal`, `sample-evergreen`, or uuid4 hex |
| `kind` | `policy` \| `federal` | | every query filters on it or on `doc_id` |
| `text` | str | | sanitized for uploads |
| `position` | int | | order in document |
| `source_title` | str | | |
| `page` | int \| null | | null for federal |
| `section` | str \| null | | `MAJOR › minor` label |
| `source_url` | str \| null | | federal only |
| `version` | str | `indexer._stamp` | content hash |
| `refs` | list of chunk ids | `graph.link_chunks` | clause-graph edges (policy only) |

**Queries actually issued** (all in `vectorstore.py`):
- `query_points` with two `Prefetch` (dense and bm25, each `limit=N`, same filter) and `FusionQuery(RRF)`: `hybrid_search`.
- `retrieve(ids=…)`: `get_chunks`, used to follow graph edges.
- `count(filter, exact=True)`: idempotency check.
- `delete(FilterSelector(doc_id))`: re-index and expiry.

**Consistency assumptions:** a document's points are replaced with *delete-then-upsert* and no transaction. A crash between the two leaves the document with no points, until the next startup for bundled docs; uploads stay broken until they expire. Concurrent re-index of the same doc_id cannot happen for uploads (fresh uuid each time).

## DocumentRecord (JSON file)

Defined in `documents.py` (`DocumentRecord` dataclass). Fields: `doc_id`, `title`, `filename`, `pdf_path` (server only; removed by `public()`), `pages`, `chunks`, `is_sample`, `facts`, `security_flags`, `created_at` (UTC ISO).

- **Created:** `api.upload_document`; `Services._register_sample` (rewritten at every startup).
- **Read:** `api._get_document` (every document, file and ask request), `DocumentRegistry.expired`.
- **Deleted:** `Services.delete_expired_uploads` → `DocumentRegistry.delete` (JSON + PDF).
- **Id safety:** `validate_doc_id` regex `^[a-z0-9][a-z0-9-]{0,63}$` runs inside `pdf_path`/`_meta_path`, so no path can escape the folder (tests: `test_documents.py`).
- **Exposed by:** `GET /api/documents/{id}` (public fields), `POST /api/documents` (response).

## Relationships

| Relationship | Cardinality | Enforced? |
|---|---|---|
| DocumentRecord → chunk points (by `doc_id`) | 1 → many | convention only |
| DocumentRecord → uploaded PDF | 1 → 1 | convention (same folder, same id) |
| chunk → chunk (`refs`) | many ↔ many, same document | built at indexing; dangling refs are skipped by `get_chunks` |
| federal Markdown file → chunks (`doc_id='federal'`) | 1 → many | |
| sample files → DocumentRecord `sample-evergreen` | 1 → 1 | rewritten at startup |
| localStorage → DocumentRecord | 0..1 → 1 | the frontend falls back to the sample if the id 404s (`App.load`) |

## Ownership, tenancy, retention

- **No ownership or tenancy:** records have no owner field.
- **Retention:** uploads expire after 24 h, but deletion runs only at startup or on the next upload.
- **Personal data:** uploaded policies may contain names and member IDs. They're stored unencrypted on local disk, and the relevant excerpts are sent to the LLM provider.

## Declared vs. runtime state

The schema above is what the code *creates*. The atlas did not inspect any running instance's `storage/` directory. A deployed instance may hold documents indexed by an older `PIPELINE_VERSION` (for example, without `refs`).
