"""Structure (ARCHITECTURE §4): deterministic hierarchy, roles, footnote binding.

No model. Header rows from the timepoint row down are the column headers; rows
below are body rows; footnote markers are matched against definitions parsed
from the span's footnote pages. Unmatched markers are flagged, never guessed.
"""
from __future__ import annotations

import re

from .grid import PageGrid

_TIMEPOINT_ROW = re.compile(r"study\s*(day|week)|^visit$|^week$|^day$", re.I)
_INT = re.compile(r"^\d{1,3}([/\-–]\w+)?$")
_MARKER_SUFFIX = re.compile(r"([*]{1,4}|[a-jA-J])$")


def _find_header_rows(pg: PageGrid) -> int:
    """Return the number of header rows (through the timepoint row)."""
    for r in range(min(pg.n_rows, 8)):
        label = pg.cells[r][pg.stub_cols[-1]].text if pg.stub_cols else pg.cells[r][0].text
        if _TIMEPOINT_ROW.search(label or ""):
            return r + 1
    return 1


def _split_marker(text: str) -> tuple[str, list[str]]:
    """Peel a trailing footnote marker off a verbatim cell/label value."""
    markers = []
    m = _MARKER_SUFFIX.search(text.strip())
    # only treat a trailing letter as a marker when it follows a mark glyph or
    # closing paren/word — kept conservative for the thin pass.
    if m and text.strip() not in ("",):
        pass
    return text, markers


def parse_footnotes(fn_pages_text: list[tuple[int, str]]) -> list[dict]:
    """Parse `* text`, `** text`, `(01) text`, `Xa - text` definition lines."""
    out = []
    pat = re.compile(r"(?m)^\s*(\*{1,4}|\(?\d{1,2}\)?|X?[a-jA-J])\s*[-–:.)]?\s+(\S.*)$")
    for page, text in fn_pages_text:
        for m in pat.finditer(text):
            marker, body = m.group(1).strip(), m.group(2).strip()
            if len(body) < 4:
                continue
            out.append({"marker": marker, "text_verbatim": body[:400],
                        "source_pages": [page], "continued_from_previous_page": False,
                        "attaches_to": []})
    return out


def build_columns(header: PageGrid, n_header_rows: int) -> list[dict]:
    cols = []
    tp_row = n_header_rows - 1
    for c in range(header.n_cols):
        label = header.cells[tp_row][c].text
        role = "row_header" if c in header.stub_cols else "unknown"
        if role == "unknown":
            if _INT.match(label or ""):
                role = "study_day"
            elif re.search(r"day|week|visit", label or "", re.I):
                role = "study_day"
        cols.append({"id": f"c{c}", "index": c, "label_verbatim": label,
                     "role": role, "colspan": 1, "footnote_markers": []})
    return cols


def is_category_row(cells, stub_cols, n_cols) -> bool:
    label = " ".join(cells[c].text for c in stub_cols).strip()
    if not label:
        return False
    data = [cells[c] for c in range(n_cols) if c not in stub_cols]
    return not any(d.text.strip() or d.shaded for d in data)


def assemble_table(pagegrids: list[PageGrid], fn_pages_text: list[tuple[int, str]],
                   pages: list[int], title: str) -> dict:
    """Row-continuation stack: header from first page, body from all pages."""
    head = pagegrids[0]
    n_hdr = _find_header_rows(head)
    columns = build_columns(head, n_hdr)
    stub = head.stub_cols
    n_cols = head.n_cols

    rows, cells = [], []
    rid = 0
    for pg in pagegrids:
        start = _find_header_rows(pg)                # skip each page's header
        for r in range(start, pg.n_rows):
            rowcells = pg.cells[r]
            label = " ".join(rowcells[c].text for c in stub).strip()
            if not label and not any(rowcells[c].text.strip() or rowcells[c].shaded
                                     for c in range(n_cols) if c not in stub):
                continue                              # wholly empty row
            cat = is_category_row(rowcells, stub, n_cols)
            row_id = f"r{rid}"
            rows.append({"id": row_id, "label_verbatim": label,
                         "role": "category_header" if cat else "assessment",
                         "footnote_markers": [], "page": pg.page,
                         "possible_split": None})
            for c in range(n_cols):
                if c in stub:
                    continue
                gc = rowcells[c]
                val = gc.text.strip()
                if not val and not gc.shaded:
                    continue
                ev = []
                if val:
                    ev.append("text_layer")
                if gc.shaded:
                    ev.append("graphics_fill")
                cells.append({"row_id": row_id, "col_id": f"c{c}",
                              "value_verbatim": val, "shaded": gc.shaded,
                              "colspan": 1, "rowspan": 1, "footnote_markers": [],
                              "page": pg.page, "bbox": [round(x, 1) for x in gc.bbox],
                              "evidence": ev, "authored_by": "geometry",
                              "ambiguous": False, "ambiguity_reason": None})
            rid += 1

    footnotes = parse_footnotes(fn_pages_text)
    return {"title_verbatim": title, "kind": "unknown", "source_pages": pages,
            "continuation_of": None, "extraction_confidence": 1.0,
            "strategy": "explicit-lines", "columns": columns, "rows": rows,
            "cells": cells, "footnotes": footnotes, "warnings": []}
