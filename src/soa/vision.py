"""Vision fallback (step 2-3): read a table off a page image and mark it, loudly,
as model-authored.

This is the ONE place the model produces cell values -- there is no text layer.
Every table it produces carries, without exception:
    strategy: "vision-fallback"
    extraction_confidence: reduced
    verbatim_guaranteed: false
    authored_by: "model" on every cell
plus a note that the orphan-word audit cannot run (no word bboxes to audit).
Nobody must be able to mistake this for a geometry-extracted table.
"""
from __future__ import annotations

from .providers.base import Provider, VisionTable
from .render import render_page_png

#: Vision output never claims high confidence; there is no geometry to check it.
VISION_CONFIDENCE = 0.4


def vision_table(pdf_path: str, page_number: int, provider: Provider,
                 candidate_rank: int = 1) -> dict:
    """Render one page, read it with the provider, and emit a marked table."""
    png = render_page_png(pdf_path, page_number)
    vt: VisionTable = provider.extract_table(png, page_number)
    return _to_schema(vt, page_number, provider.name, candidate_rank)


def _to_schema(vt: VisionTable, page: int, provider_name: str, rank: int) -> dict:
    cols = []
    for i, c in enumerate(vt.get("columns", [])):
        cols.append({
            "id": f"c{i}", "index": i,
            "label_verbatim": c.get("label", ""),
            "role": "row_header" if i == 0 else "unknown",
            "colspan": 1, "footnote_markers": [], "authored_by": "model",
        })
    rows = []
    for i, r in enumerate(vt.get("rows", [])):
        rows.append({
            "id": f"r{i}", "label_verbatim": r.get("label", ""),
            "role": "assessment", "footnote_markers": [],
            "possible_split": None, "page": page, "authored_by": "model",
        })
    cells = []
    for cell in vt.get("cells", []):
        ri, ci = cell.get("row"), cell.get("col")
        if ri is None or ci is None or ri >= len(rows) or ci >= len(cols):
            continue
        val = cell.get("value", "")
        if not str(val).strip():
            continue
        cells.append({
            "row_id": f"r{ri}", "col_id": f"c{ci}",
            "value_verbatim": val, "shaded": False, "colspan": 1, "rowspan": 1,
            "footnote_markers": [], "page": page,
            "bbox": None,                       # no geometry: nothing to anchor
            "evidence": ["vision"], "authored_by": "model",
            "ambiguous": False, "ambiguity_reason": None,
        })

    warnings = [{
        "kind": "vision_fallback",
        "detail": (f"page {page} has no text layer; this table was read from the "
                   f"rendered image by a vision model ({provider_name}). Values are "
                   f"model-authored and NOT verbatim-guaranteed."),
    }, {
        "kind": "orphan_word_audit_unavailable",
        "detail": "no word bboxes on a scanned page; the orphan-word drop-detector "
                  "cannot run on this table.",
    }]

    return {
        "id": f"soa-{rank}",
        "title_verbatim": vt.get("title", f"(vision-extracted table, page {page})"),
        "kind": "unknown",
        "source_pages": [page],
        "continuation_of": None,
        "confidence": VISION_CONFIDENCE,
        "extraction_confidence": VISION_CONFIDENCE,
        "strategy": "vision-fallback",
        "verbatim_guaranteed": False,
        "authored_by": "model",
        "columns": cols, "rows": rows, "cells": cells,
        "footnotes": [], "warnings": warnings,
    }
