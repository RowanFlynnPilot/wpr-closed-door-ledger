"""documents.py, ocr.py and polite.py. The OCR test needs Tesseract on PATH."""
import io
import sys
import time
from pathlib import Path

import pypdf
import pytest
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import documents  # noqa: E402
import polite  # noqa: E402

LINES = [
    "VILLAGE BOARD AGENDA",
    "7. CLOSED SESSION pursuant to Wis. Stat. 19.85(1)(c) and (f)",
    "to consider the performance evaluation of the Village Administrator.",
    "8. Adjourn.",
] + [f"filler line {k} of the scanned agenda" for k in range(5)]


def _scanned_pdf(pages: int = 1) -> bytes:
    images = []
    for _ in range(pages):
        img = Image.new("RGB", (2550, 3300), "white")
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("arial.ttf", 48)
        except OSError:
            font = ImageFont.truetype("DejaVuSans.ttf", 48)
        for i, line in enumerate(LINES):
            draw.text((200, 200 + i * 90), line, fill="black", font=font)
        images.append(img)
    out = io.BytesIO()
    images[0].save(out, format="PDF", resolution=300, save_all=True, append_images=images[1:])
    return out.getvalue()


def test_scanned_page_is_ocrd():
    got = documents.pdf_text(_scanned_pdf(), "synthetic.pdf")
    assert got.text_source == "ocr" and got.ocr_pages == [1] and got.pages == 1
    assert "19.85(1)(c)" in got.text


def test_blank_document_raises():
    out = io.BytesIO()
    Image.new("RGB", (850, 1100), "white").save(out, format="PDF")
    with pytest.raises(documents.UnreadableDocument, match="blank.pdf"):
        documents.pdf_text(out.getvalue(), "blank.pdf")
    with pytest.raises(documents.UnreadableDocument):
        documents.require_text("   short   ", "page.html")


def test_first_pages_and_max_pages():
    pdf = _scanned_pdf(pages=3)
    assert len(pypdf.PdfReader(io.BytesIO(documents.first_pages(pdf, 2))).pages) == 2
    got = documents.pdf_text(pdf, "three.pdf", max_pages=1)
    assert got.pages == 3 and got.ocr_pages == [1] and "\f" not in got.text


class _FakeResponse:
    def raise_for_status(self):
        pass


def test_one_request_per_host_per_second(monkeypatch):
    calls: list[tuple[str, float]] = []

    def fake(method, url, **kwargs):
        calls.append((url, time.monotonic()))
        return _FakeResponse()

    monkeypatch.setattr(polite._session, "request", fake)
    monkeypatch.setattr(polite, "MIN_INTERVAL", 0.2)
    polite.get("https://a.example/1")
    polite.get("https://b.example/1")
    polite.get("https://a.example/2")
    a = [t for u, t in calls if "a.example" in u]
    b = [t for u, t in calls if "b.example" in u]
    assert a[1] - a[0] >= 0.2
    assert b[0] - a[0] < 0.2          # a different host is not held back


def _docx(paragraphs: list[str]) -> bytes:
    import zipfile
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = "".join(f"<w:p><w:r><w:t>{p[:10]}</w:t></w:r><w:r><w:t>{p[10:]}</w:t></w:r></w:p>" for p in paragraphs)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("word/document.xml", f'<w:document xmlns:w="{w}"><w:body>{body}</w:body></w:document>')
    return out.getvalue()


def test_docx_text():
    lines = ["MOTION TO MOVE TO CLOSED SESSION Pursuant to Wis. Stat. 19.85(1)(c)",
             "Motion by Doe, second by Roe, to convene into closed session. Motion carried 5-0."] * 2
    assert documents.docx_text(_docx(lines), "m.docx").splitlines() == lines
    with pytest.raises(documents.UnreadableDocument):
        documents.docx_text(_docx(["Draft"]), "short.docx")


def _image_pdf(draw_box: bool) -> bytes:
    img = Image.new("RGB", (850, 1100), "white")
    if draw_box:
        ImageDraw.Draw(img).rectangle((100, 100, 300, 160), fill="black")
    out = io.BytesIO()
    img.save(out, format="PDF")
    return out.getvalue()


def test_blank_pdf_draws_nothing():
    writer = pypdf.PdfWriter()
    writer.add_blank_page(612, 792)
    out = io.BytesIO()
    writer.write(out)
    assert documents.blank_pdf(out.getvalue()) and documents.blank_pdf(_image_pdf(False))
    assert not documents.blank_pdf(_image_pdf(True)) and not documents.blank_pdf(_scanned_pdf())
