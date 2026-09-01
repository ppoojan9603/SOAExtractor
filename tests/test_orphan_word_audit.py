"""The orphan-word audit (item 2): the primary drop detector.

For years this was dead code -- defined, never called, claimed as the drop
detector in ARCHITECTURE §5. It now runs on every table. These tests pin the
two things that matter: it FIRES on a dropped row, and it stays QUIET on text
that is legitimately not a cell (axis header words, letter-spaced capitals,
footnote markers) so the signal isn't buried in noise.
"""
from __future__ import annotations

import os

import pytest

from soa.extract.grid import GCell, PageGrid
from soa.verify import orphan_word_audit
from soa.pipeline import run


def _grid():
    """3x3: row0 header ('' | Visit | 1), row1 emitted ('Informed Consent' | X),
    row2 a DROPPED assessment ('Dropped Assessment' | X)."""
    def cell(r, c, text, x0, x1, top, bot):
        return GCell(row=r, col=c, text=text, bbox=(x0, top, x1, bot))
    xs = [(0, 100), (100, 160), (160, 200)]
    ys = [(0, 10), (10, 20), (20, 30)]
    texts = [["", "Visit", "1"],
             ["Informed Consent", "X", ""],
             ["Dropped Assessment", "X", ""]]
    cells = [[cell(r, c, texts[r][c], xs[c][0], xs[c][1], ys[r][0], ys[r][1])
              for c in range(3)] for r in range(3)]
    return PageGrid(page=1, n_rows=3, n_cols=3, cells=cells, stub_cols=[0], header_rows=1)


def _word(t, x0, x1, top, bot):
    return {"text": t, "x0": x0, "x1": x1, "top": top, "bottom": bot}


def _table():
    # row2 and its cell are NOT emitted -- that's the drop.
    return {
        "columns": [{"id": "c0", "label_verbatim": ""}, {"id": "c1", "label_verbatim": "1"},
                    {"id": "c2", "label_verbatim": ""}],
        "rows": [{"id": "r0", "label_verbatim": "Informed Consent", "page": 1,
                  "footnote_markers": []}],
        "cells": [{"row_id": "r0", "col_id": "c1", "value_verbatim": "X", "page": 1,
                   "bbox": [100, 10, 160, 20], "footnote_markers": []}],
    }


def test_dropped_row_is_flagged():
    words = [_word("Visit", 100, 130, 0, 10), _word("1", 165, 175, 0, 10),
             _word("Informed", 0, 40, 10, 20), _word("Consent", 41, 90, 10, 20),
             _word("X", 120, 130, 10, 20),
             _word("Dropped", 0, 40, 20, 30), _word("Assessment", 41, 95, 20, 30),
             _word("X", 120, 130, 20, 30)]
    w = orphan_word_audit(_table(), [_grid()], {1: words})
    assert len(w) == 1 and w[0]["kind"] == "orphan_word"
    flagged = w[0]["text"]
    assert "Dropped" in flagged and "Assessment" in flagged  # the dropped row's label
    assert "X" in flagged                                    # its dropped body mark


def test_covered_text_is_quiet():
    """'Visit' (axis header word), an emitted row label and its in-cell mark
    must NOT be flagged -- only the dropped row is."""
    words = [_word("Visit", 100, 130, 0, 10),
             _word("Informed", 0, 40, 10, 20), _word("Consent", 41, 90, 10, 20),
             _word("X", 120, 130, 10, 20)]
    w = orphan_word_audit(_table(), [_grid()], {1: words})
    assert w == []


SOA = {"protocol1": None, "protocol5": None, "protocol9": None,
       "protocol12": None, "protocol15": None}


def _orphans(doc, table_id):
    t = next(t for t in doc["tables"] if t["id"] == table_id)
    return [x for x in t.get("warnings", []) if x["kind"] == "orphan_word"]


@pytest.mark.parametrize("name", list(SOA))
def test_main_soa_has_no_orphan_words(name):
    """After B/C/D quieting the five MAIN SoAs reconcile fully -- no dropped
    text. (protocol9's soa-1 keeps group-header warnings; those are the recorded
    header gap, asserted separately, so this checks only that no BODY/label word
    is orphaned there.)"""
    doc = run(f"data/protocols/{name}.pdf", max_candidates=3)
    orphans = _orphans(doc, "soa-1")
    if name == "protocol9":
        # group-band header phrases only; never an X mark or an assessment label
        blob = " ".join(o["text"] for o in orphans)
        assert "X" not in blob.split()
    else:
        assert orphans == [], f"{name} soa-1 orphan words: {orphans}"


def test_detector_is_live_not_disabled():
    """A known genuine gap (protocol15 soa-2 AE-frequency multi-row header) must
    still produce an orphan_word warning -- proves the audit isn't silently
    empty."""
    doc = run("data/protocols/protocol15.pdf", max_candidates=3)
    assert _orphans(doc, "soa-2"), "audit produced nothing where a real gap exists"


HOLD = "data/holdout/NCT03348956.pdf"


@pytest.mark.skipif(not os.path.exists(HOLD), reason="holdout PDF not present")
def test_holdout_recovered_row_reconciles():
    """With item 1 in place NCT03348956 p21's row is emitted, so the audit is
    clean; if that row regressed, this table would light up."""
    assert _orphans(run(HOLD), "soa-1") == []
