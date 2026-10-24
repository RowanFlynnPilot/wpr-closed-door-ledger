"""Text of an archived document, and the helpers every adapter shares.

PDF text comes from the text layer (pdfplumber). A page with almost no text
layer but an image on it is a scan, and is read by OCR (ocr.py). Pages are
joined with a form feed ("\\f") so extract.py can tell which page an item is on.
"""
from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass

import pdfplumber
import pypdf
import pypdfium2

import ocr

# A page whose text layer has fewer non-space characters than this, and that
# carries an image, is a scan.
SCAN_PAGE_CHARS = 25
# A document that yields less readable text than this raises: it must never
# count as "no closed items" because it couldn't be read.
MIN_DOCUMENT_CHARS = 200
# HTML agendas are never scans, and real ones can be this short ("I. Call to
# Order II. Continued Facility Discussion III. Adjourn"); below this the page is empty.
MIN_HTML_CHARS = 40


class UnreadableDocument(Exception):
    pass


@dataclass(frozen=True)
class PdfText:
    text: str               # pages joined with "\f"
    text_source: str        # "ocr" if any page was OCR'd, else "text_layer"
    ocr_pages: list[int]    # 1-based pages read by OCR
    pages: int              # pages in the whole file


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _chars(text: str) -> int:
    return len(re.sub(r"\s", "", text))


def pdf_text(content: bytes, name: str, max_pages: int | None = None) -> PdfText:
    """Text of a PDF's first max_pages pages (all when None). `name` labels errors."""
    texts: list[str] = []
    ocr_pages: list[int] = []
    with pdfplumber.open(io.BytesIO(content)) as plumber:
        total = len(plumber.pages)
        count = total if max_pages is None else min(max_pages, total)
        scans = []
        for i in range(count):
            page = plumber.pages[i]
            text = page.extract_text() or ""
            if _chars(text) < SCAN_PAGE_CHARS and page.images:
                scans.append(i)
            texts.append(text)
    if scans:
        pdf = pypdfium2.PdfDocument(content)
        try:
            for i in scans:
                texts[i] = ocr.ocr_page(pdf, i)
                ocr_pages.append(i + 1)
        finally:
            pdf.close()
    joined = "\f".join(texts)
    if _chars(joined) < MIN_DOCUMENT_CHARS:
        raise UnreadableDocument(f"{name}: only {_chars(joined)} readable characters")
    return PdfText(joined, "ocr" if ocr_pages else "text_layer", ocr_pages, total)


def first_pages(content: bytes, n: int) -> bytes:
    """A new PDF holding the first n pages (Weston packets are archived this way)."""
    reader = pypdf.PdfReader(io.BytesIO(content))
    writer = pypdf.PdfWriter()
    for page in reader.pages[:n]:
        writer.add_page(page)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def require_text(text: str, name: str) -> str:
    """For HTML documents: raise rather than treat an empty page as no closed items."""
    if _chars(text) < MIN_HTML_CHARS:
        raise UnreadableDocument(f"{name}: only {_chars(text)} readable characters")
    return text
