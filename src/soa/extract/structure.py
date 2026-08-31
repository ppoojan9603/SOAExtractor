"""Structure (ARCHITECTURE §4): deterministic hierarchy, roles, footnote binding.

No model. Header rows from the timepoint row down are the column headers; rows
below are body rows; footnote markers are matched against definitions parsed
from the span's footnote pages. Unmatched markers are flagged, never guessed.
"""
from __future__ import annotations

import re

from .grid import PageGrid, evaluate_split, detect_divider_columns, detect_divider_rows

from .grid import TIMEPOINT_ROW as _TIMEPOINT_ROW
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
    for c in cells:
        for m in (c.get("sup_markers") or []):
            used.add(m)
    for r in rows:
        for m in (r.get("sup_markers") or []):
            used.add(m)
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


def extract_markers(text: str) -> list[str]:
    """Footnote markers present in one verbatim string (same forms as collect)."""
    out = []
    for run in re.findall(r"\*{1,4}", text):
        out.append(run)
    for d in re.findall(r"[†‡•◦]", text):
        out.append(d)
    for num in re.findall(r"\((\d{1,2})\)", text):
        out.append(num)
    for letter in re.findall(rf"[{_MARK_GLYPHS}]([a-j])(?![a-z])", text):
        out.append(letter)
    # de-dup, keep order
    seen, uniq = set(), []
    for m in out:
        if m not in seen:
            seen.add(m); uniq.append(m)
    return uniq


def bind_markers(rows: list[dict], cells: list[dict], columns: list[dict],
                 footnotes: list[dict]) -> None:
    """Populate footnote_markers on cells/rows/cols and each footnote's
    attaches_to. Deterministic marker matching (ARCHITECTURE §4); nothing that
    fails to match is invented -- the footnote is simply left unanchored.
    """
    targets: dict[str, list[dict]] = {}
    for r in rows:
        for m in extract_markers(r["label_verbatim"]) + list(r.get("sup_markers") or []):
            if m in r["footnote_markers"]:
                continue
            r["footnote_markers"].append(m)
            targets.setdefault(m, []).append({"kind": "row", "id": r["id"]})
    for col in columns:
        for m in extract_markers(col.get("label_verbatim", "")):
            col["footnote_markers"].append(m)
            targets.setdefault(m, []).append({"kind": "column", "id": col["id"]})
    for c in cells:
        markers = extract_markers(c["value_verbatim"]) + list(c.get("sup_markers") or [])
        for m in markers:
            if m in c["footnote_markers"]:
                continue
            c["footnote_markers"].append(m)
            targets.setdefault(m, []).append(
                {"kind": "cell", "row_id": c["row_id"], "col_id": c["col_id"]})
    for f in footnotes:
        tgt = targets.get(f.get("marker"), [])
        f["attaches_to"] = tgt
        f["unanchored"] = not tgt


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


def header_bands(pg: PageGrid, n_hdr: int, data_start: int) -> list[tuple[int, int, str]]:
    """Reconstruct period bands from the group header row.

    A spanning header's text is split by extract_table across every column its
    bbox covers ("Trea|tment", "Base|line|ions"), so a band is a run of
    consecutive data columns whose group-row cells are non-empty, joined in
    order. A run ends at an empty cell -- that gap is the real span boundary.
    """
    if n_hdr < 2:
        return []
    bands, run, parts = [], [], []
    for c in range(data_start, pg.n_cols):
        txt = (pg.cells[0][c].text or "").strip()
        if txt:
            run.append(c); parts.append(txt)
        elif run:
            bands.append((run[0], run[-1], " ".join(parts).replace(chr(10), " ")))
            run, parts = [], []
    if run:
        bands.append((run[0], run[-1], " ".join(parts).replace(chr(10), " ")))
    return bands


def build_columns(header: PageGrid, n_header_rows: int) -> list[dict]:
    """Columns as a tree: period bands parent the timepoint columns they cover."""
    cols = []
    tp_row = n_header_rows - 1
    data_start = _leading_label_cols(header, n_header_rows)
    bands = [b for b in header.group_bands if b[0] >= data_start]
    dividers = set(detect_divider_columns(header, n_header_rows))

    # band parents first, so children can reference them
    band_of: dict[int, str] = {}
    for bi, (c0, c1, label) in enumerate(bands):
        bid = f"g{bi}"
        cols.append({"id": bid, "parent_id": None, "level": 0,
                     "label_verbatim": label, "role": "period",
                     "colspan": c1 - c0 + 1, "footnote_markers": [],
                     "covers": [c0, c1]})
        for c in range(c0, c1 + 1):
            band_of[c] = bid

    for c in range(header.n_cols):
        label = header.cells[tp_row][c].text
        if c in dividers:
            # a milestone letter-stack: never a timepoint (DECISIONS row 9)
            joined = "".join(
                re.sub(r"\s+", "", header.cells[r][c].text)
                for r in range(header.n_rows)).strip()
            cols.append({"id": f"c{c}", "index": c, "parent_id": None, "level": 0,
                         "label_verbatim": joined, "role": "divider", "colspan": 1,
                         "footnote_markers": []})
            continue
        role = "row_header" if c in header.stub_cols else "unknown"
        if role == "unknown":
            if _TP_VALUE.match((label or "").strip()):
                role = "study_day"
            elif re.search(r"day|week|visit", label or "", re.I):
                role = "study_day"
        parent = band_of.get(c) if role != "row_header" else None
        cols.append({"id": f"c{c}", "index": c, "parent_id": parent,
                     "level": 1 if parent else 0,
                     "label_verbatim": label, "role": role, "colspan": 1,
                     "footnote_markers": []})
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


_TP_VALUE = re.compile(r"^(\d{1,3}([/\-–]\w+)?|ET|RT|EOT|-?\.?\d)$", re.I)


def _leading_label_cols(pg: PageGrid, n_hdr: int) -> int:
    """How many leading columns are the label region (before the first timepoint).

    protocol1 has TWO: the ACTIVITY label column and a narrow VISIT/WEEK column,
    then the visit-numbered data columns. Detected from the timepoint header row:
    the first column whose header cell is a timepoint value starts the data.
    """
    tp = n_hdr - 1
    for c in range(pg.n_cols):
        val = (pg.cells[tp][c].text or "").strip()
        if _TP_VALUE.match(val):
            return c
    return max(pg.stub_cols) + 1 if pg.stub_cols else 1


def _row_labels(pg: PageGrid, n_hdr: int) -> list[str]:
    return [" ".join(pg.cells[r][c].text for c in pg.stub_cols).strip()
            for r in range(n_hdr, pg.n_rows)]


#: Title vocabulary per kind. Advisory only -- `unknown` is always allowed and
#: is a better answer than a confident wrong label (DECISIONS row 9).
_KIND_VOCAB = [
    ("pk", r"(pharmacokinetic|pk|blood collection|sampling)"),
    ("substudy", r"(sub-?study|companion|ancillary)"),
    ("extension", r"(extension|long-?term follow)"),
    ("main", r"(schedule of (activities|assessments|events|measures)|"
             r"time and events|overview of study assessments|study flow chart|"
             r"schedule of study procedures)"),
]


def classify_kind(title: str, columns: list[dict]) -> str:
    """Minimal advisory kind heuristic: title vocabulary + timepoint columns.

    A table only earns a schedule kind if it actually has timepoint columns; a
    title alone is not enough. Anything unrecognised stays `unknown`.
    """
    has_timepoints = sum(1 for c in columns if c.get("role") == "study_day") >= 2
    t = (title or "").lower()
    for kind, pat in _KIND_VOCAB:
        if re.search(pat, t):
            if kind == "main" and not has_timepoints:
                return "unknown"
            return kind
    return "main" if has_timepoints and re.search(r"schedule|assessment|visit", t) else "unknown"


def assemble_table(pagegrids: list[PageGrid], fn_pages_text: list[tuple[int, str]],
                   pages: list[int], title: str) -> dict:
    """Dispatch: same column count -> row-continuation; differing -> column merge."""
    if len({pg.n_cols for pg in pagegrids}) > 1:
        return _assemble_column_continuation(pagegrids, fn_pages_text, pages, title)
    return _assemble_row_continuation(pagegrids, fn_pages_text, pages, title)


def _assemble_row_continuation(pagegrids: list[PageGrid], fn_pages_text: list[tuple[int, str]],
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
        sizes = [ch.get("size") for row in pg.cells for c in row for ch in c.chars
                 if ch.get("size")]
        median_size = (sorted(sizes)[len(sizes) // 2] if sizes else 10.0)
        pg_hdr_n = _find_header_rows(pg)
        divider_cols = set(detect_divider_columns(pg, pg_hdr_n))
        divider_rows = set(detect_divider_rows(pg, pg_hdr_n))
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
            # Rule C-prime: a ruled band may hold two real rows (protocol5 p50
            # Saline). Split only under (a)+(b)+(c); grey zone stays merged with
            # a structured possible_split for the reviewer.
            split = evaluate_split(pg, r, stub, median_size)
            if split and split[0] == "split":
                for part in split[1]:
                    row_id = f"r{rid}"
                    rows.append({"id": row_id, "label_verbatim": part["label"],
                                 "role": "assessment", "footnote_markers": [],
                                 "sup_markers": [], "page": pg.page,
                                 "possible_split": None, "split_from_band": True})
                    for c, txt in part["marks"]:
                        gc = rowcells[c]
                        cells.append({"row_id": row_id, "col_id": f"c{c}",
                                      "value_verbatim": txt.strip(),
                                      "shaded": gc.shaded, "colspan": 1, "rowspan": 1,
                                      "footnote_markers": [],
                                      "sup_markers": list(gc.sup_markers),
                                      "page": pg.page,
                                      "bbox": [round(x, 1) for x in gc.bbox],
                                      "evidence": (["text_layer"] if txt.strip() else [])
                                                  + (["graphics_fill"] if gc.shaded else []),
                                      "authored_by": "geometry",
                                      "ambiguous": False, "ambiguity_reason": None})
                    rid += 1
                continue

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
            row_sup = [m for c in stub for m in rowcells[c].sup_markers]
            if r in divider_rows:
                role = "divider"
            grey = ({"stub_lines": [{"label": p["label"], "marks": p["marks"]}
                                    for p in split[1]]}
                    if split and split[0] == "grey" else None)
            rows.append({"id": row_id, "label_verbatim": label,
                         "role": role, "footnote_markers": [],
                         "sup_markers": row_sup, "page": pg.page,
                         "possible_split": grey})
            for c in range(n_cols):
                if c in stub or c in divider_cols:
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
                              "colspan": gc.colspan, "rowspan": 1, "footnote_markers": [],
                              "sup_markers": list(gc.sup_markers),
                              "page": pg.page, "bbox": [round(x, 1) for x in gc.bbox],
                              "evidence": ev, "authored_by": "geometry",
                              "ambiguous": False, "ambiguity_reason": None})
            rid += 1

    used_markers = collect_used_markers(cells, rows, columns)
    footnotes = build_footnotes(fn_pages_text, used_markers)
    bind_markers(rows, cells, columns, footnotes)
    warnings = []
    if deferred_pages:
        warnings.append({"kind": "column_continuation_unmerged",
                         "detail": f"pages {deferred_pages} share the row labels but "
                                   f"have a different column count; guarded column "
                                   f"merge pending -- their columns are not yet in "
                                   f"this table"})
    return {"title_verbatim": title, "kind": classify_kind(title, columns),
            "source_pages": pages,
            "continuation_of": None, "extraction_confidence": 1.0,
            "strategy": "explicit-lines", "columns": columns, "rows": rows,
            "cells": cells, "footnotes": footnotes, "warnings": warnings}


def _assemble_column_continuation(pagegrids, fn_pages_text, pages, title) -> dict:
    """Guarded column merge (ARCHITECTURE §3): pages share the row labels but
    carry different visit columns. Union the columns onto one row axis when the
    row-label sequences match >=95%; otherwise fall back to the first page plus
    a continuation_of link and a warning.

    protocol1: p53 = Activity + visits 1-8, p54 = Activity + visits 9-13/ET/RT,
    28/29 labels identical -> one table, columns 1-13/ET/RT on a shared row axis,
    per-cell page provenance kept.
    """
    head = pagegrids[0]
    n_hdr = _find_header_rows(head)
    stub = head.stub_cols
    warnings = []

    head_labels = _row_labels(head, n_hdr)

    # columns: everything from the head page, ids c0..c{n-1}
    columns = build_columns(head, n_hdr)
    col_id_of = {c: f"c{c}" for c in range(head.n_cols)}
    next_col = head.n_cols

    # rows keyed by label (from the head); cells from the head first
    rows, cells = [], []
    row_id_by_label = {}
    for ri, label in enumerate(head_labels):
        r = n_hdr + ri
        rowcells = head.cells[r]
        row_id = f"r{ri}"
        row_id_by_label[label] = row_id
        rows.append({"id": row_id, "label_verbatim": label, "role": "assessment",
                     "footnote_markers": [],
                     "sup_markers": [m for c in stub for m in head.cells[r][c].sup_markers],
                     "page": head.page, "possible_split": None})
        for c in range(head.n_cols):
            if c in stub:
                continue
            gc = rowcells[c]
            if not gc.text.strip() and not gc.shaded:
                continue
            cells.append(_cell(row_id, col_id_of[c], gc, head.page))

    # each continuation page contributes its DATA columns + cells, matched by label
    for pg in pagegrids[1:]:
        pg_hdr = _find_header_rows(pg)
        pg_labels = _row_labels(pg, pg_hdr)
        n = min(len(head_labels), len(pg_labels))
        match = sum(1 for a, b in zip(head_labels, pg_labels) if a and a == b)
        if n == 0 or match / n < 0.95:
            warnings.append({"kind": "column_continuation_rejected", "page": pg.page,
                             "detail": f"row-label match {match}/{n} < 95%; page {pg.page} "
                                       f"kept separate"})
            continue
        data_start = _leading_label_cols(pg, pg_hdr)
        appended = {}
        tp = pg_hdr - 1
        for c in range(data_start, pg.n_cols):
            cid = f"c{next_col}"; next_col += 1
            appended[c] = cid
            label = pg.cells[tp][c].text
            role = "study_day" if _TP_VALUE.match((label or "").strip()) else "unknown"
            columns.append({"id": cid, "index": next_col - 1, "label_verbatim": label,
                            "role": role, "colspan": 1, "footnote_markers": [], "page": pg.page})
        for ri, label in enumerate(pg_labels):
            row_id = row_id_by_label.get(label)
            if row_id is None:
                continue
            r = pg_hdr + ri
            for c, cid in appended.items():
                gc = pg.cells[r][c]
                if not gc.text.strip() and not gc.shaded:
                    continue
                cells.append(_cell(row_id, cid, gc, pg.page))

    used_markers = collect_used_markers(cells, rows, columns)
    footnotes = build_footnotes(fn_pages_text, used_markers)
    bind_markers(rows, cells, columns, footnotes)
    return {"title_verbatim": title, "kind": classify_kind(title, columns),
            "source_pages": pages,
            "continuation_of": None, "extraction_confidence": 1.0,
            "strategy": "explicit-lines", "columns": columns, "rows": rows,
            "cells": cells, "footnotes": footnotes, "warnings": warnings}


def _cell(row_id, col_id, gc, page) -> dict:
    val = gc.text.strip()
    ev = (["text_layer"] if val else []) + (["graphics_fill"] if gc.shaded else [])
    return {"row_id": row_id, "col_id": col_id, "value_verbatim": val,
            "shaded": gc.shaded, "colspan": gc.colspan, "rowspan": 1,
            "footnote_markers": [], "sup_markers": list(gc.sup_markers),
            "page": page, "bbox": [round(x, 1) for x in gc.bbox], "evidence": ev,
            "authored_by": "geometry", "ambiguous": False, "ambiguity_reason": None}
