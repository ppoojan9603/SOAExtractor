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

from .extract.grid import PageGrid


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


def orphan_word_audit(pagegrids: list[PageGrid]) -> dict:
    """Placeholder-level check: report cells that hold text vs total, so a wholly
    dropped structure (0 textful cells on a page with words) is visible. A full
    word-in-bbox reconciliation lands with the UI bboxes; this is the thin form.
    """
    per_page = {}
    for pg in pagegrids:
        textful = sum(1 for row in pg.cells for c in row if c.text.strip())
        per_page[pg.page] = textful
    return per_page


def verify(table: dict, pagegrids: list[PageGrid]) -> list[dict]:
    # keep any warnings the assembler already attached (e.g. column-continuation)
    warnings: list[dict] = list(table.get("warnings") or [])

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
