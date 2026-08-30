"""End-to-end pipeline: PDF -> document dict (ARCHITECTURE §Pipeline)."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pdfplumber

from .ingest import ingest_pdf, ingest_page
from .locate.locator import locate, Candidate
from .extract.grid import gridify_page
from .extract.structure import assemble_table
from .verify import verify

_TITLE = re.compile(
    r"(schedule of (activities|assessments|events|measures|blood collections)[^\n]*|"
    r"time and events schedule|overview of study assessments|table of events)", re.I
)


def _title_for(pdf, grid_pages: list[int]) -> str:
    text = pdf.pages[grid_pages[0] - 1].extract_text() or ""
    for line in text.splitlines():
        m = _TITLE.search(line)
        if m:
            return line.strip()
    return f"(untitled table, page {grid_pages[0]})"


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()



def _text_below_table(pdf_page, pagegrid) -> str:
    """Text on the grid page below the table's last rule (the footnote block)."""
    bottom = max((c.bbox[3] for row in pagegrid.cells for c in row), default=0)
    if not bottom or bottom >= pdf_page.height - 2:
        return ""
    crop = pdf_page.within_bbox((0, bottom + 1, pdf_page.width, pdf_page.height))
    return crop.extract_text() or ""


def run(pdf_path: str, max_candidates: int | None = None) -> dict:
    ingests = ingest_pdf(pdf_path)
    by_page = {g.page_number: g for g in ingests}
    candidates = locate(ingests)
    if max_candidates:
        candidates = candidates[:max_candidates]

    tables = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, cand in enumerate(candidates, 1):
            pagegrids = [gridify_page(pdf.pages[p - 1], by_page[p]) for p in cand.grid_pages]
            # footnote sources: the block BELOW the table on each (upright) grid
            # page -- protocol15's defs sit under its p25 grid, not on a
            # lookahead page -- plus the lookahead pages themselves.
            fn_text = []
            for pg in pagegrids:
                if by_page[pg.page].rotation:
                    continue                              # rotated: defs live on a lookahead page
                below = _text_below_table(pdf.pages[pg.page - 1], pg)
                if below:
                    fn_text.append((pg.page, below))
            fn_text += [(p, by_page[p].text) for p in cand.footnote_pages]
            title = _title_for(pdf, cand.grid_pages)
            table = assemble_table(pagegrids, fn_text,
                                   cand.grid_pages + cand.footnote_pages, title)
            table["id"] = f"soa-{i}"
            # squash the unbounded locator score into 0..1 for the schema field;
            # the raw score is kept as locator_score for debugging.
            table["confidence"] = round(cand.score / (cand.score + 1.0), 3)
            table["locator_score"] = round(cand.score, 3)
            table["warnings"] = verify(table, pagegrids)
            tables.append(table)

    name = Path(pdf_path).name
    return {"document": {"filename": name, "sha256": _sha256(pdf_path),
                         "page_count": len(ingests)},
            "tables": tables}
