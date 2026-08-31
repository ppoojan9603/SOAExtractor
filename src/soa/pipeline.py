"""End-to-end pipeline: PDF -> document dict (ARCHITECTURE §Pipeline)."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pdfplumber

from .ingest import ingest_pdf, ingest_page
from .locate.locator import locate, Candidate
from .extract.grid import gridify_page
from .extract.structure import assemble_table, _TIMEPOINT_ROW
from .verify import verify

_TITLE = re.compile(
    r"(schedule of (activities|assessments|events|measures|blood collections)[^\n]*|"
    r"time and events schedule|overview of study assessments|table of events)", re.I
)


def _title_for(pdf, grid_pages: list[int], pagegrid=None) -> str:
    """Stitch a multi-line title: y-adjacent lines in the same font class.

    protocol9's title wraps to three lines ("Table 4. / Schedule of Measures and
    Data / Collection for Lofexidine Phase 3"); taking one line truncates it.
    Start from the line that matches the title vocabulary, then absorb
    neighbouring lines that are vertically adjacent and set in a comparable size.
    """
    page = pdf.pages[grid_pages[0] - 1]
    words = page.extract_words(extra_attrs=["size"])
    if not words:
        return f"(untitled table, page {grid_pages[0]})"

    # group words into visual lines
    lines: list[dict] = []
    for w in sorted(words, key=lambda w: ((w["top"] + w["bottom"]) / 2, w["x0"])):
        mid = (w["top"] + w["bottom"]) / 2
        if lines and abs(mid - lines[-1]["mid"]) <= 3:
            lines[-1]["words"].append(w)
            lines[-1]["mid"] = (lines[-1]["mid"] + mid) / 2
        else:
            lines.append({"mid": mid, "words": [w]})
    for ln in lines:
        ln["words"].sort(key=lambda w: w["x0"])
        ln["text"] = " ".join(w["text"] for w in ln["words"]).strip()
        sizes = [w.get("size", 0) for w in ln["words"] if w.get("size")]
        ln["size"] = max(sizes) if sizes else 0
        ln["top"] = min(w["top"] for w in ln["words"])
        ln["bottom"] = max(w["bottom"] for w in ln["words"])

    seed = next((i for i, ln in enumerate(lines) if _TITLE.search(ln["text"])), None)
    if seed is None:
        return _title_from_cells(pagegrid, grid_pages)

    parts = [lines[seed]["text"]]
    size = lines[seed]["size"]

    def compatible(a, b) -> bool:
        vgap = b["top"] - a["bottom"]
        return -1 <= vgap <= 0.9 * max(size, 1) and abs(b["size"] - size) <= 0.15 * max(size, 1)

    i = seed
    while i + 1 < len(lines) and compatible(lines[i], lines[i + 1]):
        parts.append(lines[i + 1]["text"]); i += 1
    j = seed
    while j - 1 >= 0 and compatible(lines[j - 1], lines[j]):
        parts.insert(0, lines[j - 1]["text"]); j -= 1
    stitched = " ".join(p.strip() for p in parts if p.strip())

    # protocol9: the title lives INSIDE the table's first stub cells (rotated
    # page), so page-line grouping only ever sees one wrapped fragment. Prefer
    # the in-cell stitch when it is a strict superset.
    in_cell = _title_from_cells(pagegrid, grid_pages)
    if in_cell and not in_cell.startswith("(untitled") and len(in_cell) > len(stitched):
        if stitched.split()[0] in in_cell if stitched.split() else True:
            return in_cell
    return stitched


def _title_from_cells(pagegrid, grid_pages: list[int]) -> str:
    """Stitch a title drawn inside the grid's leading stub cells.

    Collect stub-column text from the header rows, stopping at the timepoint row
    ("Study Day"/"Study Week"/"VISIT") -- that boundary is deterministic, unlike
    "row has other text", which fires early on protocol9 p26 where the wrapped
    period band ("randomized to Lofexidine or Placebo") shares row 2.
    """
    if pagegrid is None:
        return f"(untitled table, page {grid_pages[0]})"
    stub = pagegrid.stub_cols[0] if pagegrid.stub_cols else 0
    parts, seen_title = [], False
    for r in range(min(8, pagegrid.n_rows)):
        txt = (pagegrid.cells[r][stub].text or "").strip()
        if _TIMEPOINT_ROW.search(txt):
            break
        if not txt:
            continue
        parts.append(txt.replace(chr(10), " "))
        if _TITLE.search(txt):
            seen_title = True
    joined = " ".join(parts).strip()
    return joined if (seen_title and joined) else f"(untitled table, page {grid_pages[0]})"


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
            title = _title_for(pdf, cand.grid_pages, pagegrids[0])
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
