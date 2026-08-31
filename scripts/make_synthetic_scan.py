"""Render a protocol page as an IMAGE-ONLY PDF, to exercise the vision fallback.

A scanned protocol has no text layer: no chars, no vector rules, just a picture
of the page. We synthesise that deterministically by rasterising one page and
wrapping the bitmap in a PDF. The result has the verified shape a real scan has:
0 chars, 0 rects, 0 lines, 1 image; extract_text() == '', extract_table() is None.

Default fixture: protocol12 p48 -- its ground truth (42 rows x 10 cols) is
already in our committed out/protocol12.json, so the vision fallback can be
scored cell-by-cell against our own geometric extraction.

    python scripts/make_synthetic_scan.py            # protocol12 p48 -> tests/fixtures/
    python scripts/make_synthetic_scan.py --protocol protocol9 --page 26 -o /tmp
"""
from __future__ import annotations

import argparse
import io
from pathlib import Path

import pypdfium2 as pdfium


def render_image_only_pdf(src_pdf: str, page_number: int, scale: float = 2.0) -> bytes:
    doc = pdfium.PdfDocument(src_pdf)
    try:
        img = doc[page_number - 1].render(scale=scale).to_pil().convert("RGB")
    finally:
        doc.close()
    buf = io.BytesIO()
    # PIL writes the bitmap as the sole content of a one-page PDF: no text layer,
    # no vector operators, just an XObject image.
    img.save(buf, format="PDF", resolution=72.0 * scale)
    return buf.getvalue()


def verify_scanned_shape(pdf_bytes: bytes) -> dict:
    import pdfplumber
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        page = pdf.pages[0]
        return {
            "chars": len(page.chars),
            "rects": len(page.rects),
            "lines": len(page.lines),
            "images": len(page.images),
            "extract_text_empty": (page.extract_text() or "") == "",
            "extract_table_none": page.extract_table() is None,
        }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--protocol", default="protocol12")
    ap.add_argument("--page", type=int, default=48)
    ap.add_argument("--scale", type=float, default=2.0)
    ap.add_argument("-o", "--out", default="tests/fixtures")
    args = ap.parse_args(argv)

    src = f"data/protocols/{args.protocol}.pdf"
    pdf_bytes = render_image_only_pdf(src, args.page, args.scale)

    shape = verify_scanned_shape(pdf_bytes)
    ok = (shape["chars"] == 0 and shape["rects"] == 0 and shape["lines"] == 0
          and shape["images"] == 1 and shape["extract_text_empty"]
          and shape["extract_table_none"])

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{args.protocol}_p{args.page}_scan.pdf"
    out_path.write_bytes(pdf_bytes)

    print(f"wrote {out_path} ({len(pdf_bytes)//1024} KB)")
    print(f"shape: {shape}")
    print("VERIFIED scanned shape" if ok else "WARNING: not the expected scanned shape")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
