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


#: Bare-symbol footnote markers that are always footnotes, never ordinals.
_SYMBOL_MARKERS = {"*", "**", "***", "****", "†", "‡", "•", "◦"}

_MARK_GLYPHS = "Xx✓✔√●○■□▪•"


def collect_used_markers(cells: list[dict], rows: list[dict], columns: list[dict]) -> set[str]:
    """Markers ACTUALLY used in the table's cells/labels (DECISIONS row 8).

    Footnote collection is driven by this set — never the other way round. The
    inversion (collect every definition-looking line, then keep it) is exactly
    what swept up numbered prose lists as fake markers.
    """
    used: set[str] = set()
    texts = ([c.get("value_verbatim", "") for c in cells]
             + [r.get("label_verbatim", "") for r in rows]
             + [c.get("label_verbatim", "") for c in columns])
    for t in texts:
        for run in re.findall(r"\*{1,4}", t):
            used.add(run)
        for d in re.findall(r"[†‡•◦]", t):
            used.add(d)
        for num in re.findall(r"\((\d{1,2})\)", t):     # (01) form numbers
            used.add(num)
        # a mark glyph followed by a superscript-ish letter: Xa, ✓b
        for letter in re.findall(rf"[{_MARK_GLYPHS}]([a-j])(?![a-z])", t):
            used.add(letter)
    return used


def _candidate_defs(text: str):
    """Yield (marker, body) for lines that look like footnote definitions."""
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        # asterisk / dagger run, space optional (protocol12 "****CBT")
        m = re.match(r"^(\*{1,4}|[†‡•◦])\s*(\S.*)$", s)
        if m:
            yield m.group(1), m.group(2).strip()
            continue
        # single letter (optionally X-prefixed) then a REQUIRED separator
        m = re.match(r"^X?([a-jA-J])\s*[-–:]\s*(\S.*)$", s)
        if m:
            yield m.group(1).lower(), m.group(2).strip()
            continue
        # numeric marker then separator (kept only if used — see build_footnotes)
        m = re.match(r"^\(?(\d{1,2})\)?\s*[-–:.)]\s+(\S.*)$", s)
        if m:
            yield m.group(1), m.group(2).strip()


def build_footnotes(fn_pages_text: list[tuple[int, str]], used: set[str]) -> list[dict]:
    """Collect definitions keyed by USED markers, plus bare symbols.

    Keep a candidate iff its marker is used, or it is a bare-symbol/letter
    footnote form. A purely numeric marker that is NOT used is an ordinal list
    item (protocol12/15 numbered prose) and is dropped. A real footnote whose
    usage we could not detect is kept but emitted unanchored, never invented.
    """
    out = []
    seen = set()
    for page, text in fn_pages_text:
        for marker, body in _candidate_defs(text):
            if len(body) < 4:
                continue
            key = (marker, body[:30])
            if key in seen:
                continue
            is_numeric = marker.isdigit()
            used_here = marker in used
            if is_numeric and not used_here:
                continue                                  # ordinal list -> drop
            if not used_here and marker not in _SYMBOL_MARKERS and not marker.isalpha():
                continue
            seen.add(key)
            out.append({"marker": marker, "text_verbatim": body[:400],
                        "source_pages": [page], "continued_from_previous_page": False,
                        "unanchored": not used_here, "attaches_to": []})
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


def _body_has_content(cells, stub_cols, n_cols) -> bool:
    return any(cells[c].text.strip() or cells[c].shaded
               for c in range(n_cols) if c not in stub_cols)


def classify_empty_band(label: str) -> str:
    """Role for a body-empty band whose stub carries text (correction 1).

    A ruling can separate a label's overflow line from its own row (the inverse
    of the Saline split). Measured case: protocol9 p26 "(Study Day 1 and Exit
    Day)" sits in its own ruled band below "Physical Examination (04)" with zero
    body fills and zero body words.

      - starts with "(" or a lowercase letter -> label_continuation (merge up)
      - ends with ":"                          -> category_header
      - otherwise                              -> metadata (blank capture row,
                                                  e.g. Date / Day of Week)
    """
    t = label.strip()
    if not t:
        return "metadata"
    if t.startswith("(") or (t[:1].isalpha() and t[:1].islower()):
        return "label_continuation"
    if t.rstrip().endswith(":"):
        return "category_header"
    return "metadata"


def assemble_table(pagegrids: list[PageGrid], fn_pages_text: list[tuple[int, str]],
                   pages: list[int], title: str) -> dict:
    """Row-continuation stack: header from first page, body from all pages."""
    head = pagegrids[0]
    n_hdr = _find_header_rows(head)
    columns = build_columns(head, n_hdr)
    stub = head.stub_cols
    n_cols = head.n_cols

    rows, cells = [], []
    deferred_pages: list[int] = []
    rid = 0
    for pg in pagegrids:
        if pg.n_cols != n_cols:
            # column-wise continuation (protocol1 p53=10 cols, p54=9): a proper
            # guarded merge onto the shared row axis is pending. Do not stack it
            # as if it were row-continuation -- that mismatches columns. Defer
            # and flag instead of crashing or corrupting.
            deferred_pages.append(pg.page)
            continue
        start = _find_header_rows(pg)                # skip each page's header
        for r in range(start, pg.n_rows):
            rowcells = pg.cells[r]
            label = " ".join(rowcells[c].text for c in stub).strip()
            if not label and not any(rowcells[c].text.strip() or rowcells[c].shaded
                                     for c in range(n_cols) if c not in stub):
                continue                              # wholly empty row
            if not _body_has_content(rowcells, stub, n_cols):
                role = classify_empty_band(label)
                if role == "label_continuation" and rows:
                    # merge overflow line into the previous row's label
                    rows[-1]["label_verbatim"] = (
                        rows[-1]["label_verbatim"] + " " + label.strip()
                    ).strip()
                    continue
            else:
                role = "assessment"
            row_id = f"r{rid}"
            rows.append({"id": row_id, "label_verbatim": label,
                         "role": role, "footnote_markers": [], "page": pg.page,
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

    used_markers = collect_used_markers(cells, rows, columns)
    footnotes = build_footnotes(fn_pages_text, used_markers)
    warnings = []
    if deferred_pages:
        warnings.append({"kind": "column_continuation_unmerged",
                         "detail": f"pages {deferred_pages} share the row labels but "
                                   f"have a different column count; guarded column "
                                   f"merge pending -- their columns are not yet in "
                                   f"this table"})
    return {"title_verbatim": title, "kind": "unknown", "source_pages": pages,
            "continuation_of": None, "extraction_confidence": 1.0,
            "strategy": "explicit-lines", "columns": columns, "rows": rows,
            "cells": cells, "footnotes": footnotes, "warnings": warnings}
