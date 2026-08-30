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


@dataclass
class PageGrid:
    page: int
    n_rows: int
    n_cols: int
    cells: list[list[GCell]]           # [row][col]
    stub_cols: list[int]
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

    # map grey fills to cells
    fill_by_cell: dict[tuple[int, int], list] = {}
    for f in g.fills:
        if not f.grey:
            continue
        owner = _fill_owner(f.bbox, cell_bboxes)
        if owner is not None:
            f.cell = owner
            fill_by_cell.setdefault(owner, []).append(f)

    # banding test: a row whose grey-fill union spans a stub column is decoration
    shaded_cells: set[tuple[int, int]] = set()
    for r in range(len(cell_bboxes)):
        cols_filled = {c for (rr, c) in fill_by_cell if rr == r}
        if not cols_filled:
            continue
        covers_stub = any(sc in cols_filled for sc in stub_cols)
        near_full = len(cols_filled) >= 0.8 * n_cols
        if covers_stub or near_full:
            for f in [ff for (rr, c) in fill_by_cell if rr == r for ff in fill_by_cell[(rr, c)]]:
                f.classification = "banding"
        else:
            for c in cols_filled:
                for f in fill_by_cell[(r, c)]:
                    f.classification = "mark"
                shaded_cells.add((r, c))

    cells = []
    for r in range(len(cell_bboxes)):
        row = []
        for c in range(n_cols):
            row.append(GCell(r, c, text_grid[r][c] if r < len(text_grid) else "",
                             cell_bboxes[r][c], shaded=(r, c) in shaded_cells))
        cells.append(row)
    return PageGrid(g.page_number, len(cell_bboxes), n_cols, cells, stub_cols)


def build_pagegrids(pdf_path: str, pages: list[int]) -> list[PageGrid]:
    out = []
    with pdfplumber.open(pdf_path) as pdf:
        for p in pages:
            page = pdf.pages[p - 1]
            out.append(gridify_page(page, ingest_page(page)))
    return out
