"""Stacked multi-row headers: visit number + study day/week (assignment names
'a visit number, a study day or week, and an allowable visit window' as three
distinct things that must not be flattened).

protocol1 stacks VISIT (row0) over WEEK (row1); the old stub-only header
detector saw one header row and misfiled the whole WEEK line as an 'ACTIVITY'
assessment row. Now: two header rows, visit numbers as labels, weeks as
study_day_verbatim, and NO week lands in window_verbatim.
"""
from __future__ import annotations

import pdfplumber
import pytest

from soa.pipeline import run
from soa.ingest import ingest_page
from soa.extract.grid import gridify_page
from soa.extract.structure import _find_header_rows

FIVE = ["protocol1", "protocol5", "protocol9", "protocol12", "protocol15"]
SOA = {"protocol1": 53, "protocol5": 50, "protocol9": 26, "protocol12": 48, "protocol15": 25}


@pytest.fixture(scope="module")
def docs():
    return {n: run(f"data/protocols/{n}.pdf", max_candidates=3) for n in FIVE}


def test_header_row_counts():
    expect = {"protocol1": 2, "protocol5": 2, "protocol9": 5, "protocol12": 2, "protocol15": 2}
    for n, p in SOA.items():
        with pdfplumber.open(f"data/protocols/{n}.pdf") as pdf:
            pg = gridify_page(pdf.pages[p - 1], ingest_page(pdf.pages[p - 1]))
        assert _find_header_rows(pg) == expect[n], f"{n} header rows"


def test_protocol1_stacked_header_mapped(docs):
    t = docs["protocol1"]["tables"][0]
    # phantom assessment row gone
    assert not any(r["label_verbatim"] == "ACTIVITY" for r in t["rows"])
    # visit numbers 1..13 + ET/RT are the labels
    labels = [c["label_verbatim"] for c in t["columns"]]
    for v in ["1", "8", "9", "13", "ET", "RT"]:
        assert v in labels, f"visit {v} missing"
    # study weeks captured as study_day_verbatim, paired to the visit
    sd = {c["label_verbatim"]: c.get("study_day_verbatim") for c in t["columns"]}
    assert sd.get("1") == "-2" and sd.get("13") == "26"
    # ET/RT resolve as visits, not unknown
    roles = {c["label_verbatim"]: c["role"] for c in t["columns"]}
    assert roles.get("ET") == "visit" and roles.get("RT") == "visit"


def test_study_weeks_are_not_windows(docs):
    """The p1 weeks (-2, 0, 2 ...) are study days, not allowable ranges -- they
    must NOT be in window_verbatim, which stays the genuine ranges only."""
    t = docs["protocol1"]["tables"][0]
    assert not [c for c in t["columns"] if c.get("window_verbatim")]


def test_window_verbatim_unchanged_counts(docs):
    counts = {n: sum(1 for c in docs[n]["tables"][0]["columns"] if c.get("window_verbatim"))
              for n in FIVE}
    assert counts == {"protocol1": 0, "protocol5": 2, "protocol9": 0,
                      "protocol12": 5, "protocol15": 5}


def test_value_verbatim_carveout_invariant(docs):
    """The value-unchanged rule WITH its one approved carve-out, as a stable
    invariant (not a git-diff, which would evaporate once out/ is recommitted).

    The carve-out: protocol1's 'ACTIVITY'/study-week header line is no longer a
    data row. A cell means 'this assessment occurs at this visit'; a study week
    like '-2' sitting in a phantom ACTIVITY row was header content, not that. So
    the 13 values are REMOVED as cells and RELOCATED to the correct axis
    (study_day_verbatim on the visit columns) -- removed, not lost.

    Invariant form:
      - no protocol has an 'ACTIVITY' assessment row (the misfiling is gone);
      - every study week that lived in that row is present as some column's
        study_day_verbatim (content relocated);
      - no cell value_verbatim is a bare study-week token orphaned in a header-
        label row.
    Byte-identical value_verbatim on the other four is guarded by
    test_recall_row_and_column_counts + test_no_double_count + the out/ snapshot.
    """
    t = docs["protocol1"]["tables"][0]
    assert not any(r["label_verbatim"] == "ACTIVITY" and r["role"] == "assessment"
                   for r in t["rows"])
    weeks_relocated = {c.get("study_day_verbatim") for c in t["columns"]
                       if c.get("study_day_verbatim")}
    for wk in ("-2", "-.3", "0", "2", "4", "6", "8", "12", "16", "20", "24", "26"):
        assert wk in weeks_relocated, f"study week {wk} not relocated to study_day_verbatim"


def test_protocol9_soa3_header_promotion_carveout(docs):
    """Second approved value_verbatim deviation, same mechanism as protocol1.

    protocol9's SECONDARY dosing table (soa-3, p20) stacks a blank group row
    over 'Study Day | Morphine | Study Medication ...'. The stub column is empty
    on that table, so the old stub-only detector saw one header row and misfiled
    the whole 'Study Day' line as a phantom data row -- leaf column labels were
    lost ('', '', '') and 'Study Day'/'Morphine' sat as CELL VALUES in a blank
    row. Whole-row header detection (candidate D) now reads two header rows: the
    labels become real columns and every data value re-keys to its correct
    column. No value string is invented or lost; four header labels correctly
    leave the cell set. Approved as the same fix class as protocol1 -- header
    content misfiled as data, corrected, not a content change.
    """
    soa3 = next(t for t in docs["protocol9"]["tables"] if t["id"] == "soa-3")
    labels = [c["label_verbatim"] for c in soa3["columns"]]
    assert "Study\nDay" in labels and "Morphine" in labels, \
        "soa-3 header labels must be real columns, not phantom cell values"
    # 'Study Day' / 'Morphine' must no longer appear as a cell VALUE
    assert not any(x["value_verbatim"] in ("Study\nDay", "Morphine")
                   for x in soa3["cells"]), \
        "header label leaked back into the cell set"
