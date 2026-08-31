"""Model-free shortlist of grid-like pages on a scanned PDF (step 1 of the
vision fallback).

When a page has no text layer there is nothing for the geometric pipeline to
read, so we cannot use rules or word density to find the SoA. But a *table* still
looks different from prose in the raw pixels: a grid produces long, regular runs
of dark pixels along rows (horizontal rules, aligned marks) and columns
(vertical rules), while prose produces short, irregular runs. We score that
regularity from a low-resolution render with PIL + numpy only -- no OpenCV, no
model -- and return the top few pages for the expensive vision step.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pypdfium2 as pdfium


#: Low render scale: we only need coarse ink structure, not legible text.
SHORTLIST_SCALE = 0.5
#: A pixel darker than this (0=black, 255=white) counts as ink.
INK_THRESHOLD = 160


@dataclass
class PageScanScore:
    page: int
    score: float
    long_h_runs: int
    long_v_runs: int


def _grid_score(gray: np.ndarray) -> tuple[float, int, int]:
    """Higher when dark pixels form long, aligned runs on both axes.

    A rule (or a row/column of aligned marks) is a line of the image where a
    large fraction of pixels are ink. We count rows and columns whose ink
    fraction clears a bar; a grid has many on both axes, prose has few.
    """
    ink = gray < INK_THRESHOLD
    h, w = ink.shape
    if h == 0 or w == 0:
        return 0.0, 0, 0
    row_frac = ink.mean(axis=1)          # ink fraction per image row
    col_frac = ink.mean(axis=0)          # ink fraction per image column
    # a table row/rule spans much of the width; prose lines are broken by spaces
    long_h = int((row_frac > 0.30).sum())
    long_v = int((col_frac > 0.30).sum())
    # normalise by page extent so big and small pages compare
    score = (long_h / h) * (long_v / w) * 1e4
    return score, long_h, long_v


def shortlist_scanned_pages(pdf_path: str, top_k: int = 3,
                            scale: float = SHORTLIST_SCALE,
                            pages: list[int] | None = None) -> list[PageScanScore]:
    """Rank pages by grid-likeness from low-res pixels. Model-free.

    `pages` (1-based) restricts scoring to a subset -- on a mixed document only
    the text-less pages need the vision path, so we score only those.
    """
    doc = pdfium.PdfDocument(pdf_path)
    scores: list[PageScanScore] = []
    try:
        wanted = set(pages) if pages else set(range(1, len(doc) + 1))
        for i in range(len(doc)):
            if (i + 1) not in wanted:
                continue
            img = doc[i].render(scale=scale, grayscale=True).to_pil().convert("L")
            gray = np.asarray(img, dtype=np.uint8)
            s, lh, lv = _grid_score(gray)
            scores.append(PageScanScore(i + 1, round(s, 3), lh, lv))
    finally:
        doc.close()
    scores.sort(key=lambda p: -p.score)
    return scores[:top_k]
