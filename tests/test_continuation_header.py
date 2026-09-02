"""Continuation-page header skip (item 1, found via the M7.5 holdout).

_assemble_row_continuation skips each page's header rows. On a continuation
page after the first, _find_header_rows can only see a header if the page
REPEATS one carrying the timepoint vocabulary; NCT03348956 p21 repeats no
header and has no vocabulary, so the detector fell to its default 1 and ate
the real first assessment row ('Toronto Clinical Neuropathy Scoring System',
body X X X). A header row never carries cell marks, so the skip is now bounded
by the first marked body row on continuation pages: min(header_rows, first
marked row). Neutral on the five (their continuation pages' first marked row is
at or beyond the computed header end); the holdout confirms recovery.
"""
from __future__ import annotations

import os

import pytest

from soa.pipeline import run

HOLDOUT = "data/holdout/NCT03348956.pdf"


@pytest.mark.skipif(not os.path.exists(HOLDOUT), reason="holdout PDF not present")
def test_continuation_first_row_not_eaten_as_header():
    t = run(HOLDOUT)["tables"][0]
    assert t["source_pages"] == [20, 21], "expected the p20->p21 row-continuation span"
    labels = [r["label_verbatim"] for r in t["rows"]]
    assert any("Toronto" in l for l in labels), \
        "p21's first assessment row was skipped as a phantom header"
    assert len(t["rows"]) == 15


def test_five_row_continuation_unaffected():
    """The cap is a no-op on the design set: protocol9 and protocol15 (whose
    soa-2 is the other multi-page row-continuation span) are unchanged by it.

    protocol9's count is 40 rather than the original 43 for an unrelated reason
    -- the shaded-rowspan merge rejoined three split cells -- not because this
    continuation cap moved anything.
    """
    assert len(run("data/protocols/protocol9.pdf", max_candidates=3)["tables"][0]["rows"]) == 40
    assert len(run("data/protocols/protocol15.pdf", max_candidates=3)["tables"][0]["rows"]) == 34
