"""PDF and document parsing helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

try:
    import fitz  # PyMuPDF
except Exception:  # pragma: no cover
    fitz = None


def parse_pdf_bytes(data: bytes) -> Dict:
    if fitz is None:
        return {"text": "", "pages": 0, "images": 0, "error": "PyMuPDF not available"}
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        return {"text": "", "pages": 0, "images": 0, "error": str(exc)}
    text_parts: List[str] = []
    image_count = 0
    for page in doc:
        text_parts.append(page.get_text())
        image_count += len(page.get_images(full=True))
    doc.close()
    return {"text": "\n".join(text_parts), "pages": len(text_parts), "images": image_count, "error": None}


def parse_pdf_file(path: Path) -> Dict:
    try:
        return parse_pdf_bytes(path.read_bytes())
    except Exception as exc:
        return {"text": "", "pages": 0, "images": 0, "error": str(exc)}