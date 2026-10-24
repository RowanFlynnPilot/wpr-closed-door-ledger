"""OCR for image-only PDF pages: render at 300 dpi with pypdfium2, read with Tesseract.

Tesseract must be on PATH (Actions: sudo apt-get install -y tesseract-ocr;
Windows: the UB Mannheim build).
"""
from __future__ import annotations

import io
import subprocess

import pypdfium2

DPI = 300


def ocr_page(pdf: pypdfium2.PdfDocument, index: int) -> str:
    """Text of one page (0-based), read by Tesseract with --psm 4."""
    image = pdf[index].render(scale=DPI / 72).to_pil()
    png = io.BytesIO()
    image.save(png, format="PNG")
    result = subprocess.run(
        ["tesseract", "stdin", "stdout", "--psm", "4"],
        input=png.getvalue(), capture_output=True, check=True,
    )
    return result.stdout.decode("utf-8")
