"""Requirements traceability -- one test per sentence of the assignment's
extractor/locator spec, each asserting across ALL FIVE protocols.

This is the checklist we never had: we gated hard on what the data surfaced
(shading, splitter, markers) and let the spec's own requirements go untested,
which is how flat row hierarchy and empty visit windows survived 87 tests.
Each test names the requirement it enforces. Anything not automatable is a
skipped test carrying the reason.
"""
from __future__ import annotations

import pytest

from soa.pipeline import run

FIVE = ["protocol1", "protocol5", "protocol9", "protocol12", "protocol15"]
# protocols whose SoA page actually prints the structure, from measurement:
HAS_ROW_CATEGORIES = {"protocol9", "protocol12", "protocol15"}
HAS_COL_GROUPS = {"protocol5", "protocol9", "protocol12", "protocol15"}
HAS_WINDOWS = {"protocol5", "protocol12", "protocol15"}


@pytest.fixture(scope="module")
def docs():
    return {n: run(f"data/protocols/{n}.pdf", max_candidates=3) for n in FIVE}


def main(docs, name):
    return docs[name]["tables"][0]


# --- "It must preserve the row x column x cell structure" ---

@pytest.mark.parametrize("name", FIVE)
def test_row_column_cell_structure_present(docs, name):
    t = main(docs, name)
    assert t["rows"], f"{name}: no rows"
    assert t["columns"], f"{name}: no columns"
    assert t["cells"], f"{name}: no cells"
    ids = {r["id"] for r in t["rows"]}
    cids = {c["id"] for c in t["columns"]}
    for c in t["cells"]:                      # every cell resolves to a real row+col
        assert c["row_id"] in ids and c["col_id"] in cids


# --- "the grouping hierarchy on both axes" ---

@pytest.mark.parametrize("name", sorted(HAS_ROW_CATEGORIES))
def test_row_hierarchy_non_trivial(docs, name):
    t = main(docs, name)
    cats = [r for r in t["rows"] if r["role"] == "category_header"]
    assert cats, f"{name}: category rows not detected"
    linked = [r for r in t["rows"] if r.get("parent_id")]
    assert linked, f"{name}: no assessment row linked to a category"


@pytest.mark.parametrize("name", ["protocol1", "protocol5"])
def test_row_hierarchy_honestly_flat_where_none(docs, name):
    """protocol1/5 have no category rows on the page -> flat is correct, not a miss."""
    t = main(docs, name)
    assert not [r for r in t["rows"] if r["role"] == "category_header"]


@pytest.mark.parametrize("name", sorted(HAS_COL_GROUPS))
def test_column_hierarchy_non_trivial(docs, name):
    t = main(docs, name)
    bands = [c for c in t["columns"] if c["role"] == "period"]
    assert bands, f"{name}: no period bands"
    parented = [c for c in t["columns"] if c.get("parent_id")]
    assert parented, f"{name}: no timepoint column parented to a group"


def test_no_timepoint_column_left_unknown(docs):
    """A column carrying a day/week value must resolve, not flag as unknown."""
    import re
    for name in FIVE:
        for c in main(docs, name)["columns"]:
            if c["role"] == "unknown" and re.search(r"\d", c["label_verbatim"]):
                raise AssertionError(f"{name} {c['id']} unknown but has a value: "
                                     f"{c['label_verbatim']!r}")


# --- "visit windows" ---

@pytest.mark.parametrize("name", sorted(HAS_WINDOWS))
def test_visit_windows_populated(docs, name):
    t = main(docs, name)
    wins = [c["window_verbatim"] for c in t["columns"] if c.get("window_verbatim")]
    assert wins, f"{name}: no visit windows populated"


def test_named_windows_present(docs):
    def wins(name):
        return {c.get("window_verbatim") for c in main(docs, name)["columns"]}
    assert any("14-21 days prior to" in (w or "") for w in wins("protocol12"))
    assert "Up to -35" in wins("protocol5")
    assert "-15* to -9" in wins("protocol5")
    assert "-4 to 0*" in wins("protocol15")


# --- "footnotes bound to the things they modify" ---

def test_footnotes_bound_with_linkage(docs):
    for name in ("protocol9", "protocol12", "protocol15"):
        t = main(docs, name)
        bound = [f for f in t["footnotes"] if f.get("attaches_to")]
        assert bound, f"{name}: no footnote bound"
        for f in bound:
            for a in f["attaches_to"]:
                assert a.get("kind") in {"cell", "row", "column", "column_group",
                                         "table", "unanchored"}


# --- "cell values verbatim" ---

def test_cell_values_are_strings_not_normalised(docs):
    """Values keep their printed form (X, 3X, 1X, ...), never coerced to bool."""
    for name in FIVE:
        for c in main(docs, name)["cells"]:
            assert isinstance(c["value_verbatim"], str)
            assert c["value_verbatim"] not in (True, False, "true", "false")


# --- "recall: missing rows/columns are the most penalised failure" ---

def test_recall_row_and_column_counts(docs):
    """Guard the measured row and DATA-column counts (period bands excluded, since
    they are grouping nodes not timepoints) so a future change that drops a row or
    column trips here -- the highest-penalty failure."""
    expect = {   # (rows, data columns)
        "protocol1": (29, 17), "protocol5": (31, 12), "protocol9": (43, 12),
        "protocol12": (40, 10), "protocol15": (34, 11),
    }
    for name, (nr, nc) in expect.items():
        t = main(docs, name)
        data_cols = [c for c in t["columns"] if c["role"] != "period"]
        assert len(t["rows"]) == nr, f"{name} rows {len(t['rows'])} != {nr}"
        assert len(data_cols) == nc, f"{name} data cols {len(data_cols)} != {nc}"


# --- "a protocol may contain more than one SoA" ---

def test_multiple_soas_extracted(docs):
    titles = [t["title_verbatim"] for t in docs["protocol5"]["tables"]]
    assert any("Blood Collections" in x for x in titles), \
        "protocol5's second schedule must be extracted, not just the main SoA"


# --- not automatable here: recorded as skips with the reason ---

@pytest.mark.skip(reason="No ground-truth JSON to diff against; hand-verified in "
                         "docs/VERIFICATION.md and the review UI (M8).")
def test_full_cell_accuracy_vs_ground_truth():
    ...


@pytest.mark.skip(reason="Cross-page footnote continuation mid-sentence is not "
                         "present in the five; the marker-driven lookahead is "
                         "unit-tested on protocol9 p29 / protocol12 p49 instead.")
def test_footnote_continuation_midsentence():
    ...
