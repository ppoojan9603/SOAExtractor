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
            fn_text = [(p, by_page[p].text) for p in cand.footnote_pages]
            title = _title_for(pdf, cand.grid_pages)
            table = assemble_table(pagegrids, fn_text,
                                   cand.grid_pages + cand.footnote_pages, title)
            table["id"] = f"soa-{i}"
            table["confidence"] = round(cand.score, 3)
            tables.append(table)

    name = Path(pdf_path).name
    return {"document": {"filename": name, "sha256": _sha256(pdf_path),
                         "page_count": len(ingests)},
            "tables": tables}
