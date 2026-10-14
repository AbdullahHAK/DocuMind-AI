"""Turn a PDF into clean per-page text.

We keep text per page (instead of one big string) because page numbers are
what make citations checkable by a human.
"""

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

# A real policy has thousands of characters; less than this means the PDF is
# almost certainly a scanned image, which would need OCR (out of scope).
MIN_TOTAL_CHARS = 300

# Running footers/headers like "Page 11" or "Page 3 of 40" carry no meaning but
# would otherwise end up inside chunks (pypdf often extracts them first).
# Bare numbers are kept: in tables they're often real values (e.g. a visit limit).
PAGE_NUMBER_LINE = re.compile(r"^\s*(?:page\s+\d{1,4}(?:\s+of\s+\d{1,4})?|\d{1,4}\s+of\s+\d{1,4})\s*$", re.IGNORECASE | re.MULTILINE)


class PdfLoadError(ValueError):
    """Raised with a user-friendly message when a PDF can't be used."""


@dataclass
class Page:
    number: int  # 1-indexed, as humans count pages
    text: str


def clean_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("­", "")  # soft hyphens
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)  # re-join words hyphenated across lines
    text = re.sub(r"[ \t]+", " ", text)  # collapse runs of spaces
    text = re.sub(r" *\n *", "\n", text)
    text = PAGE_NUMBER_LINE.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def load_pdf(path: Path, max_pages: int | None = None) -> list[Page]:
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            raise PdfLoadError("This PDF is password-protected. Please upload an unlocked copy.")
        if max_pages is not None and len(reader.pages) > max_pages:
            raise PdfLoadError(f"This PDF has {len(reader.pages)} pages; the limit is {max_pages}.")
        pages = [Page(number=i + 1, text=clean_text(p.extract_text() or "")) for i, p in enumerate(reader.pages)]
    except PdfReadError as exc:
        raise PdfLoadError("This file doesn't look like a valid PDF.") from exc

    if sum(len(p.text) for p in pages) < MIN_TOTAL_CHARS:
        raise PdfLoadError(
            "We couldn't find any text in this PDF. It may be a scanned image; "
            "try downloading the text version of your plan documents from your insurer's website."
        )
    return pages
