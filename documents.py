"""Text of an archived document, and the helpers every adapter shares.

PDF text comes from the text layer (pdfplumber). A page with almost no text
layer but an image on it is a scan, and is read by OCR (ocr.py). Pages are
joined with a form feed ("\\f") so extract.py can tell which page an item is on.
"""
from __future__ import annotations

import hashlib
import io
import re
import zipfile
from dataclasses import dataclass
from xml.etree import ElementTree

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
# HTML agendas are never scans, and real ones can hold a single item
# ("I. VERIFY SCHOOL BOARD ELECTION RESULTS"); below this the page is empty.
MIN_HTML_CHARS = 10


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


def blank_pdf(content: bytes, max_pages: int | None = None) -> bool:
    """Every one of the first max_pages pages renders pure white: nothing is drawn on them.

    Not the same as unreadable. Weston's platform lists one earlier agenda version that
    is a single blank page (weston:1946, July 27, 2026)."""
    pdf = pypdfium2.PdfDocument(content)
    try:
        count = len(pdf) if max_pages is None else min(max_pages, len(pdf))
        return all(pdf[i].render(scale=1).to_pil().convert("L").getextrema() == (255, 255) for i in range(count))
    finally:
        pdf.close()


def page_count(content: bytes) -> int:
    return len(pypdf.PdfReader(io.BytesIO(content)).pages)


def _internal_link(annotation) -> bool:
    a = annotation.get_object()
    action = a.get("/A")
    return "/Dest" in a or (action is not None and action.get_object().get("/S") == "/GoTo")


def first_pages(content: bytes, n: int) -> bytes:
    """A new PDF holding the first n pages (Weston packets are archived this way).

    Links from the agenda to later packet pages are dropped: copying them would
    pull every linked page, scans included, into the split (one 5-page Weston
    agenda came out at 9.5 MB). Links to web addresses are kept."""
    reader = pypdf.PdfReader(io.BytesIO(content))
    writer = pypdf.PdfWriter()
    for page in reader.pages[:n]:
        if "/Annots" in page:
            kept = [a for a in page["/Annots"] if not _internal_link(a)]
            page[pypdf.generic.NameObject("/Annots")] = pypdf.generic.ArrayObject(kept)
        writer.add_page(page)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def docx_text(content: bytes, name: str) -> str:
    """A Word file's text, one paragraph per line (Weston posts some minutes this way)."""
    with zipfile.ZipFile(io.BytesIO(content)) as docx:
        root = ElementTree.fromstring(docx.read("word/document.xml"))
    lines = ["".join(t.text or "" for t in p.iter(f"{_W}t")) for p in root.iter(f"{_W}p")]
    text = "\n".join(line for line in lines if line.strip())
    if _chars(text) < MIN_DOCUMENT_CHARS:
        raise UnreadableDocument(f"{name}: only {_chars(text)} readable characters")
    return text


def require_text(text: str, name: str) -> str:
    """For HTML documents: raise rather than treat an empty page as no closed items."""
    if _chars(text) < MIN_HTML_CHARS:
        raise UnreadableDocument(f"{name}: only {_chars(text)} readable characters")
    return text
