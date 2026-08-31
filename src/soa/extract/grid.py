"""Gridify (ARCHITECTURE §3): geometric grid + shaded-mark classification.

Builds a table from a candidate span: extract_table per page using the ingest
rules, map area-fills to cells, classify each grey fill as mark vs banding via
the stub-column fill-union test, stack row-continuation pages, and emit the
schema's columns / rows / cells. No model.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pdfplumber

from ..ingest import ingest_page, PageIngest
from .stub import detect_stub_columns


@dataclass
class GCell:
    row: int
    col: int
    text: str
    bbox: tuple[float, float, float, float]
    shaded: bool = False
    colspan: int = 1
    sup_markers: list = field(default_factory=list)   # superscript footnote letters


@dataclass
class PageGrid:
    page: int
    n_rows: int
    n_cols: int
    cells: list[list[GCell]]           # [row][col]
    stub_cols: list[int]
    fills: list = field(default_factory=list)   # classified Fill objects (audit)
    header_rows: int = 2


def _cell_grid(v: list[float], h: list[float]) -> list[list[tuple]]:
    """bbox per cell from sorted rule positions."""
    v, h = sorted(v), sorted(h)
    out = []
    for r in range(len(h) - 1):
        row = []
        for c in range(len(v) - 1):
            row.append((v[c], h[r], v[c + 1], h[r + 1]))
        out.append(row)
    return out


def _superscript_markers(chars: list[dict]) -> list[str]:
    """Footnote-letter markers drawn as superscripts in a cell (DECISIONS row 6).

    A char that is both smaller than the cell's body text AND raised above its
    baseline is a superscript; when it is a letter a-j it is a footnote marker,
    separate from value_verbatim. Subscripts (raised DOWN, e.g. FEV1) are not
    footnote markers and are ignored.
    """
    letters = [c for c in chars if (c.get("text") or "").strip()]
    if len(letters) < 2:
        return []
    from statistics import median
    sizes = [c["size"] for c in letters if c.get("size")]
    if not sizes:
        return []
    # Body size is the LARGEST common size, not the median: a cell can be just
    # ['c','X'] (protocol15 p25), where the median sits between the superscript
    # and the body glyph and no char looks small.
    body_size = max(sizes)
    body = [c for c in letters if c.get("size", body_size) >= 0.95 * body_size]
    if not body:
        return []
    base_mid = median([(c["top"] + c["bottom"]) / 2 for c in body])
    out = []
    for c in letters:
        sz = c.get("size", body_size)
        mid = (c["top"] + c["bottom"]) / 2
        raised = mid < base_mid - 0.1 * body_size      # sits above the body baseline
        if sz < 0.9 * body_size and raised and c["text"].lower() in "abcdefghij":
            out.append(c["text"].lower())
    return out


def _fill_owner(fill_bbox, cell_bboxes) -> tuple[int, int] | None:
    fx = (fill_bbox[0] + fill_bbox[2]) / 2
    fy = (fill_bbox[1] + fill_bbox[3]) / 2
    for r, row in enumerate(cell_bboxes):
        for c, (x0, y0, x1, y1) in enumerate(row):
            if x0 - 0.5 <= fx <= x1 + 0.5 and y0 - 0.5 <= fy <= y1 + 0.5:
                return (r, c)
    return None


def gridify_page(pdf_page, g: PageIngest) -> PageGrid:
    v, h = sorted(g.v_rules), sorted(g.h_rules)
    table = pdf_page.extract_table({
        "vertical_strategy": "explicit", "horizontal_strategy": "explicit",
        "explicit_vertical_lines": v, "explicit_horizontal_lines": h,
    }) or []
    n_rows, n_cols = len(v) - 1, len(v) and max((len(r) for r in table), default=0)
    n_cols = len(v) - 1
    cell_bboxes = _cell_grid(v, h)
    grid = [[c or "" for c in (row + [""] * n_cols)][:n_cols] for row in table]
    while len(grid) < len(h) - 1:
        grid.append([""] * n_cols)

    text_grid = [[(grid[r][c] or "").strip() for c in range(n_cols)] for r in range(len(h) - 1)]
    stub_cols = detect_stub_columns(text_grid)

    # map grey fills to cells; non-grey and unowned fills are still tracked so
    # the orphan-fill audit (M5) can account for EVERY area-fill.
    fill_by_cell: dict[tuple[int, int], list] = {}
    for f in g.fills:
        if not f.grey:
            f.classification = "non-grey"
            continue
        owner = _fill_owner(f.bbox, cell_bboxes)
        if owner is None:
            f.classification = "flagged"           # grey fill in no cell -> audit
            continue
        f.cell = owner
        fill_by_cell.setdefault(owner, []).append(f)

    # Banding vs mark by the fill-union test (ARCHITECTURE §3, FINDINGS §5):
    # a row whose grey-fill union reaches a STUB column is decoration (protocol5
    # zebra, protocol12/15 section rows). "Near-full" is NOT a banding signal --
    # protocol9 assessments done on every visit fill all data columns yet are
    # real marks; the only reliable discriminator is whether the fill touches
    # the label column.
    shaded_cells: set[tuple[int, int]] = set()
    for r in range(len(cell_bboxes)):
        cols_filled = {c for (rr, c) in fill_by_cell if rr == r}
        if not cols_filled:
            continue
        covers_stub = any(sc in cols_filled for sc in stub_cols)
        klass = "banding" if covers_stub else "mark"
        for c in cols_filled:
            for f in fill_by_cell[(r, c)]:
                f.classification = klass
            if klass == "mark":
                shaded_cells.add((r, c))

    # assign chars to cells for superscript-marker detection
    chars_by_cell: dict[tuple[int, int], list] = {}
    for ch in g.chars:
        cx = (ch["x0"] + ch["x1"]) / 2
        cy = (ch["top"] + ch["bottom"]) / 2
        owner = None
        for r, row in enumerate(cell_bboxes):
            for c, (x0, y0, x1, y1) in enumerate(row):
                if x0 <= cx <= x1 and y0 <= cy <= y1:
                    owner = (r, c); break
            if owner:
                break
        if owner:
            chars_by_cell.setdefault(owner, []).append(ch)

    cells = []
    for r in range(len(cell_bboxes)):
        row = []
        for c in range(n_cols):
            sup = _superscript_markers(chars_by_cell.get((r, c), []))
            row.append(GCell(r, c, text_grid[r][c] if r < len(text_grid) else "",
                             cell_bboxes[r][c], shaded=(r, c) in shaded_cells,
                             sup_markers=sup))
        cells.append(row)
    return PageGrid(g.page_number, len(cell_bboxes), n_cols, cells, stub_cols, fills=g.fills)


def build_pagegrids(pdf_path: str, pages: list[int]) -> list[PageGrid]:
    out = []
    with pdfplumber.open(pdf_path) as pdf:
        for p in pages:
            page = pdf.pages[p - 1]
            out.append(gridify_page(page, ingest_page(page)))
    return out
