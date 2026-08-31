"""Page rasterisation for the review UI (pypdfium2, Apache/BSD)."""
from __future__ import annotations

import base64
import io

import pypdfium2 as pdfium

#: Render scale. The UI maps PDF points -> pixels with this factor, so bbox
#: overlays line up without any per-page calibration.
SCALE = 2.0


def render_page_png(pdf_path: str, page_number: int, scale: float = SCALE) -> bytes:
    doc = pdfium.PdfDocument(pdf_path)
    try:
        page = doc[page_number - 1]
        bmp = page.render(scale=scale)
        img = bmp.to_pil()
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    finally:
        doc.close()


def render_page_data_uri(pdf_path: str, page_number: int, scale: float = SCALE) -> str:
    png = render_page_png(pdf_path, page_number, scale)
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def page_size(pdf_path: str, page_number: int) -> tuple[float, float]:
    """Page size in points, as the UI needs it to scale bbox overlays."""
    doc = pdfium.PdfDocument(pdf_path)
    try:
        page = doc[page_number - 1]
        return page.get_width(), page.get_height()
    finally:
        doc.close()
