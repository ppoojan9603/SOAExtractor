"""Verifier (ARCHITECTURE §5): external invariants -> warnings[]. No model.

The two primary drop detectors:
  - orphan-WORD audit: every word in the table bbox lands in exactly one cell.
  - orphan-FILL audit: every area-fill is classified mark / banding /
    merged-into-colspan / flagged -- none silently dropped. This is the check
    that would have caught the near-full banding rule eating protocol9 marks.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

import re

from .extract.grid import PageGrid, detect_divider_columns, is_mark_token


@dataclass
class FillAudit:
    page: int
    total: int
    by_class: dict
    unclassified: int


def orphan_fill_audit(pagegrids: list[PageGrid]) -> list[FillAudit]:
    out = []
    for pg in pagegrids:
        counts = Counter()
        unclassified = 0
        for f in pg.fills:
            k = getattr(f, "classification", "unclassified")
            counts[k] += 1
            if k in ("unclassified", None):
                unclassified += 1
        out.append(FillAudit(pg.page, len(pg.fills), dict(counts), unclassified))
    return out


def _toks(s: str) -> set[str]:
    """Alnum tokens, lowercased -- the exact-membership coverage test. Keeps
    short label tokens honest: a visit number '1' or week '-2' is a real emitted
    column label and must count as covered, which a substring test can't do."""
    return {t for t in re.split(r"[^0-9a-z]+", (s or "").lower()) if t}


def _despace(s: str) -> str:
    """Lowercased, all non-alnum removed. Lets a page word reconcile against a
    label regardless of intra-word spacing ('P HASE' -> 'phase' vs emitted
    'PHASE I') or how each side wrapped -- a substring test on this form."""
    return re.sub(r"[^0-9a-z]+", "", (s or "").lower())


#: Timepoint axis vocabulary. A header-band word that IS one of these ('VISIT',
#: 'WEEK') is an axis descriptor, legitimately in the header and not emitted as a
#: label. Kept narrow so it never covers a results-table caption/group word
#: (bucket A: 'Table', 'Group', 'Severity', 'Cabergoline' -- none match).
_AXIS_VOCAB = re.compile(r"^(day|week|visit|screening|baseline|cycle|month|"
                         r"period|phase|timepoint|assessment|activity)$", re.I)


def _cx_cy(w: dict) -> tuple[float, float]:
    return ((w["x0"] + w["x1"]) / 2.0, (w["top"] + w["bottom"]) / 2.0)


def orphan_word_audit(table: dict, pagegrids: list[PageGrid],
                      page_words: dict[int, list[dict]]) -> list[dict]:
    """THE drop detector (ARCHITECTURE §5): every printed word inside a table's
    ruled bbox must be accounted for by some emitted output -- a body cell it
    lands in, the row label of an emitted row, or a column label. A word inside
    the bbox that matches none of those is text the pipeline dropped: it is
    reported loudly, naming the page and the exact text.

    A word is COVERED when any of these holds:
      - its de-spaced form is a substring of the emitted-LABEL blob (every row
        and column label, plus their footnote markers). De-spacing reconciles a
        word against a label regardless of intra-word spacing or wrapping; a
        dropped row's distinctive label words ('Toronto', 'Neuropathy') are
        absent from the blob and so still surface.
      - its centre falls inside an emitted BODY cell's bbox (kept strictly
        geometric -- a substring test would let a dropped 'X' hide behind an 'x'
        in some label, so body marks are matched by position only).
      - it is a HEADER stub-cell word: the stub of a leading row that carries no
        body marks. Those cells ('ACTIVITY', 'WEEK', 'Assessment') are the
        stub's own header and are not emitted as a label. The header band is
        taken as the rows before the first marked row -- the same no-marks
        principle the assembler uses -- so a real assessment row (marks in its
        body, e.g. p21 'Toronto ...') is never mistaken for header and hidden.
      - it is a single letter sitting in a stub column: a letter-spaced capital
        ('P' 'HASE') or a stub marker glyph, never a dropped datum.

    Explicit, testable exclusions (NOT a blanket suppression):
      1. Anything outside the ruled table bbox -- the title above it, the
         footnote/definition block below it, running heads and page numbers.
      2. Divider columns (the vertical letter-stack, e.g. 'RANDOMIZATION'):
         legitimately inside the bbox but never a cell. Excluded by
         detect_divider_columns geometry, not by guessing at the text.

    Deliberately NOT used: a per-page header-row count. The audit must not
    re-derive the header boundary independently -- when it did, it disagreed
    with the assembler on a defaulted page (p21) and flagged an emitted row.
    """
    warnings: list[dict] = []

    # emitted label coverage, in two forms: an exact token set (short labels like
    # a visit number '1' or week '-2') and a de-spaced blob (substring test that
    # survives intra-word spacing, wrapping and glued markers).
    label_tokens: set = set()
    parts: list[str] = []

    def _add(s):
        label_tokens.update(_toks(s))
        parts.append(_despace(s))

    for r in table["rows"]:
        _add(r["label_verbatim"])
        for m in (r.get("footnote_markers") or []):
            _add(m)
    for c in table["columns"]:
        _add(c["label_verbatim"]); _add(c.get("study_day_verbatim") or "")
        _add(c.get("window_verbatim") or "")
        for m in (c.get("footnote_markers") or []):
            _add(m)
    for c in table["cells"]:
        for m in (c.get("footnote_markers") or []):
            _add(m)
    label_blob = " ".join(p for p in parts if p)

    cell_boxes: dict[int, list] = {}
    for c in table["cells"]:
        cell_boxes.setdefault(c["page"], []).append(c["bbox"])

    for pg in pagegrids:
        if not any(c.text.strip() for row in pg.cells for c in row):
            continue                                     # empty grid: nothing to reconcile
        words = page_words.get(pg.page) or []
        if not words:
            continue

        x0 = min(pg.cells[0][c].bbox[0] for c in range(pg.n_cols))
        x1 = max(pg.cells[0][c].bbox[2] for c in range(pg.n_cols))
        top = pg.cells[0][0].bbox[1]
        bottom = pg.cells[-1][0].bbox[3]
        divider_ranges = [(pg.cells[0][c].bbox[0], pg.cells[0][c].bbox[2])
                          for c in detect_divider_columns(pg, pg.header_rows)]
        stub_ranges = [(pg.cells[0][c].bbox[0], pg.cells[0][c].bbox[2]) for c in pg.stub_cols]
        boxes = cell_boxes.get(pg.page, [])

        # header band = leading rows with no body marks (the assembler's rule, so
        # a real assessment row like p21 'Toronto ...' is never taken as header).
        first_marked = next((r for r in range(pg.n_rows)
                             if any(is_mark_token(pg.cells[r][c].text.strip())
                                    for c in range(pg.n_cols) if c not in pg.stub_cols)),
                            pg.n_rows)
        header_stub = _despace(" ".join(pg.cells[r][c].text
                                        for r in range(first_marked) for c in pg.stub_cols))
        header_bottom = pg.cells[first_marked - 1][0].bbox[3] if first_marked >= 1 else top

        leftovers: list[str] = []
        for w in words:
            cx, cy = _cx_cy(w)
            if not (x0 <= cx <= x1 and top <= cy <= bottom):
                continue                                 # EXCLUSION 1: outside the bbox
            if any(lo <= cx <= hi for lo, hi in divider_ranges):
                continue                                 # EXCLUSION 2: divider stack column
            a = _despace(w["text"])
            if not a:
                continue                                 # punctuation-only glyph
            if _toks(w["text"]) <= label_tokens:
                continue                                 # exact row/column label token(s)
            if len(a) >= 2 and a in label_blob:
                continue                                 # label word modulo spacing/wrapping
            in_stub = any(lo <= cx <= hi for lo, hi in stub_ranges)
            in_header = cy <= header_bottom
            if in_header and in_stub and len(a) >= 2 and a in header_stub:
                continue                                 # stub's own header ('ACTIVITY', 'Phase')
            if in_header and _AXIS_VOCAB.match(a):
                continue                                 # axis descriptor ('VISIT', 'WEEK')
            if len(a) == 1 and in_stub:
                continue                                 # letter-spaced cap / stub marker glyph
            if any(bx0 <= cx <= bx1 and bt <= cy <= bb for bx0, bt, bx1, bb in boxes):
                continue                                 # lands in an emitted body cell
            leftovers.append(w["text"])

        if leftovers:
            warnings.append({
                "kind": "orphan_word", "page": pg.page,
                "detail": f"{len(leftovers)} word(s) inside the table bbox landed in no "
                          f"emitted cell, row label or column label -- dropped text",
                "text": " ".join(leftovers)[:400]})
    return warnings


def verify(table: dict, pagegrids: list[PageGrid],
           page_words: dict[int, list[dict]] | None = None) -> list[dict]:
    # keep any warnings the assembler already attached (e.g. column-continuation)
    warnings: list[dict] = list(table.get("warnings") or [])

    # --- orphan-WORD audit: the primary drop detector ---
    if page_words:
        warnings += orphan_word_audit(table, pagegrids, page_words)

    # --- orphan-fill audit ---
    for fa in orphan_fill_audit(pagegrids):
        if fa.unclassified:
            warnings.append({"kind": "orphan_fill", "page": fa.page,
                             "detail": f"{fa.unclassified} unclassified area-fills",
                             "by_class": fa.by_class})
        if fa.by_class.get("flagged"):
            warnings.append({"kind": "fill_in_no_cell", "page": fa.page,
                             "detail": f"{fa.by_class['flagged']} grey fills mapped to no cell"})

    # --- footnote bidirectionality (used-but-undefined AND defined-but-unused) ---
    used = set()
    for r in table["rows"]:
        used |= set(r.get("footnote_markers") or [])
    for c in table["cells"]:
        used |= set(c.get("footnote_markers") or [])
    for col in table["columns"]:
        used |= set(col.get("footnote_markers") or [])
    defined = {f["marker"] for f in table["footnotes"] if f.get("marker")}
    for m in sorted(used - defined):
        warnings.append({"kind": "marker_used_undefined", "detail": f"marker {m!r} used but not defined nearby"})
    for m in sorted(defined - used):
        warnings.append({"kind": "marker_defined_unused", "detail": f"marker {m!r} defined but never bound to a cell/row/column"})

    # --- unknown roles surfaced, not hidden ---
    unk = [c["id"] for c in table["columns"] if c.get("role") == "unknown"]
    if unk:
        warnings.append({"kind": "unknown_column_role", "detail": f"{len(unk)} columns with role=unknown", "ids": unk})

    # --- multi-marker cells: per-mark association is lost, recorded not silent ---
    # A cell printing two distinct marks (protocol12 ASI-Lite "Xc Xe") comes out
    # value "X X" with markers ["c","e"]: nothing is dropped, but which X carries
    # which marker is not recovered. Flag it so the limitation is visible.
    multi = [{"row_id": c["row_id"], "col_id": c["col_id"],
              "value_verbatim": c["value_verbatim"],
              "footnote_markers": c["footnote_markers"]}
             for c in table["cells"] if len(c.get("footnote_markers") or []) > 1]
    if multi:
        warnings.append({"kind": "multi_marker_cell",
                         "detail": f"{len(multi)} cell(s) carry >1 footnote marker; "
                                   f"the mark<->marker association within the cell is "
                                   f"not recovered (values and markers are both kept)",
                         "cells": multi})

    return warnings
