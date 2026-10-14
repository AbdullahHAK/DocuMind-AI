from datetime import datetime, timedelta, timezone

import pytest

from app.documents import DocumentRecord, DocumentRegistry, InvalidDocumentId, validate_doc_id


def _record(doc_id, hours_old=0, is_sample=False):
    created = datetime.now(timezone.utc) - timedelta(hours=hours_old)
    return DocumentRecord(
        doc_id=doc_id, title="T", filename="f.pdf", pdf_path="x", pages=1, chunks=1,
        is_sample=is_sample, created_at=created.isoformat(),
    )


@pytest.mark.parametrize("bad", ["../etc/passwd", "a/b", "UPPER", "", "a" * 65, "..", "a.pdf"])
def test_rejects_unsafe_ids(bad):
    with pytest.raises(InvalidDocumentId):
        validate_doc_id(bad)


def test_save_get_delete(tmp_path):
    reg = DocumentRegistry(tmp_path)
    reg.save(_record("abc123"))
    assert reg.get("abc123").title == "T"
    assert "pdf_path" not in reg.get("abc123").public()
    reg.delete("abc123")
    assert reg.get("abc123") is None


def test_get_with_bad_id_returns_none(tmp_path):
    assert DocumentRegistry(tmp_path).get("../../secret") is None


def test_expired_skips_samples_and_fresh_uploads(tmp_path):
    reg = DocumentRegistry(tmp_path)
    reg.save(_record("old", hours_old=30))
    reg.save(_record("new", hours_old=1))
    reg.save(_record("sample", hours_old=999, is_sample=True))
    assert reg.expired(ttl_hours=24) == ["old"]
