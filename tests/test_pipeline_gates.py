"""End-to-end gates from PLAN M2-M4, checked against named pages (FINDINGS)."""
from __future__ import annotations

import pytest

from soa.extract.grid import build_pagegrids
from soa.pipeline import run

P = "data/protocols/{}.pdf"


@pytest.fixture(scope="module")
def docs():
    return {n: run(P.format(n), max_candidates=3)
            for n in ["protocol1", "protocol5", "protocol9", "protocol12", "protocol15"]}


def main_table(doc):
    return doc["tables"][0]


# ---------- M3: shaded marks, positive and negative ----------

def test_p9_p26_yields_shaded_marks():
    pg = build_pagegrids(P.format("protocol9"), [26])[0]
    marks = [c for row in pg.cells for c in row if c.shaded]
    assert len(marks) >= 20, "protocol9 p26 must yield >=20 shaded marks (FINDINGS §4)"
    assert any(c.text.strip() == "1X" for c in marks), "shaded AND 1X must coexist"
    assert any(not c.text.strip() for c in marks), "grey-only marks must exist"


@pytest.mark.parametrize("name,page", [("protocol5", 50), ("protocol12", 48), ("protocol15", 25)])
def test_banding_yields_zero_marks(name, page):
    pg = build_pagegrids(P.format(name), [page])[0]
    assert sum(1 for row in pg.cells for c in row if c.shaded) == 0, \
        f"{name} p{page} grey is banding, not marks (FINDINGS §5)"


def test_orphan_fill_audit_classifies_everything():
    from soa.verify import orphan_fill_audit
    for name, pages in [("protocol9", [26, 27, 28]), ("protocol5", [50]),
                        ("protocol12", [48]), ("protocol15", [25])]:
        for fa in orphan_fill_audit(build_pagegrids(P.format(name), pages)):
            assert fa.unclassified == 0, f"{name} p{fa.page} has unclassified fills"


# ---------- M3: column continuation ----------

def test_protocol1_column_merge_has_all_visits(docs):
    t = main_table(docs["protocol1"])
    labels = [c["label_verbatim"] for c in t["columns"]]
    for v in ["1", "8", "9", "13", "ET", "RT"]:
        assert v in labels, f"visit {v} missing after column merge"
    assert {c["page"] for c in t["cells"]} == {53, 54}, "cells must come from both pages"


# ---------- M2: spans ----------

@pytest.mark.parametrize("name,expect", [
    ("protocol1", {53, 54}), ("protocol5", {50}), ("protocol9", {26, 27, 28}),
    ("protocol12", {48}), ("protocol15", {25}),
])
def test_main_span_covers_soa_pages(docs, name, expect):
    t = main_table(docs[name])
    assert expect <= set(t["source_pages"]), f"{name} span {t['source_pages']} misses {expect}"


def test_protocol5_blood_collections_extracted(docs):
    titles = [t["title_verbatim"] for t in docs["protocol5"]["tables"]]
    assert any("Blood Collections" in x for x in titles), \
        "protocol5 p51 sub-schedule must be extracted as its own table (scope A)"


# ---------- M4: titles, footnotes, kind ----------

@pytest.mark.parametrize("name,expect", [
    ("protocol5", "Appendix I: Time and Events Schedule"),
    ("protocol9", "Table 4. Schedule of Measures and Data Collection for Lofexidine Phase 3"),
    ("protocol12", "Table 3. Overview of Study Assessments"),
    ("protocol15", "Table 1. Overview of Study Assessments"),
])
def test_titles_stitched(docs, name, expect):
    assert main_table(docs[name])["title_verbatim"] == expect


def test_no_numeric_ordinals_as_footnotes(docs):
    """The marker-driven inversion: numbered prose lists are not footnotes."""
    for name in ["protocol12", "protocol15"]:
        markers = [f["marker"] for f in main_table(docs[name])["footnotes"]]
        assert not [m for m in markers if m and m.isdigit()], \
            f"{name} picked up ordinal list items as markers"


def test_footnotes_bind_to_targets(docs):
    t12 = main_table(docs["protocol12"])
    bound = [f for f in t12["footnotes"] if f["attaches_to"]]
    assert len(bound) >= 10, "protocol12 letter/asterisk markers must bind"
    # '*' is defined but never printed in protocol12 -> stays unanchored
    star = [f for f in t12["footnotes"] if f["marker"] == "*"]
    assert star and not star[0]["attaches_to"], "protocol12 '*' must stay unanchored"


def test_protocol9_form_numbers_flagged_not_bound(docs):
    kinds = [w["kind"] for w in main_table(docs["protocol9"])["warnings"]]
    assert "marker_used_undefined" in kinds, \
        "protocol9 (01)-(33) form numbers must surface as used-but-undefined"


def test_kind_classification(docs):
    for n in ["protocol1", "protocol5", "protocol9", "protocol12", "protocol15"]:
        assert main_table(docs[n])["kind"] == "main"
    pk = [t for t in docs["protocol5"]["tables"] if "Blood Collections" in t["title_verbatim"]]
    assert pk and pk[0]["kind"] == "pk"


def test_header_hierarchy_period_bands(docs):
    for name in ["protocol12", "protocol15", "protocol5"]:
        cols = main_table(docs[name])["columns"]
        bands = [c for c in cols if c.get("role") == "period"]
        assert bands, f"{name} must expose period bands"
        assert any(c.get("parent_id") for c in cols), f"{name} columns must be parented"


def test_confidence_normalised(docs):
    for d in docs.values():
        for t in d["tables"]:
            assert 0.0 <= t["confidence"] <= 1.0


def test_deterministic_rerun():
    import json
    a = json.dumps(run(P.format("protocol15"), max_candidates=2), sort_keys=True)
    b = json.dumps(run(P.format("protocol15"), max_candidates=2), sort_keys=True)
    assert a == b, "pipeline must be deterministic (no model in the default path)"


# ---------- M3: rule C-prime splitter (PLAN gates, previously untested) ----------

SOA_PAGES = [("protocol1", [53, 54]), ("protocol5", [50]), ("protocol9", [26, 27, 28]),
             ("protocol12", [48]), ("protocol15", [25])]


def _split_census():
    """(splits, greys) across the six SoA pages, via the splitter directly."""
    import pdfplumber
    from soa.ingest import ingest_page
    from soa.extract.grid import gridify_page, evaluate_split
    splits, greys = [], []
    for name, pages in SOA_PAGES:
        with pdfplumber.open(P.format(name)) as pdf:
            for page_no in pages:
                page = pdf.pages[page_no - 1]
                g = ingest_page(page)
                pg = gridify_page(page, g)
                for r in range(pg.n_rows):
                    res = evaluate_split(pg, r, pg.stub_cols, g.median_char_size)
                    if not res:
                        continue
                    (splits if res[0] == "split" else greys).append((name, page_no, r, res[1]))
    return splits, greys


def test_splitter_fires_exactly_once_and_it_is_saline():
    splits, _ = _split_census()
    assert len(splits) == 1, f"expected exactly ONE split across the six SoA pages, got {len(splits)}"
    name, page_no, _, parts = splits[0]
    assert (name, page_no) == ("protocol5", 50)
    labels = [p["label"] for p in parts]
    assert labels[0].startswith("Saline/20 mg cocaine")
    assert labels[1] == "20 mg cocaine i.v."


def test_no_splits_on_the_other_four_protocols():
    splits, _ = _split_census()
    assert {s[0] for s in splits} == {"protocol5"}, \
        "v1/v2 regression: splitter must not fire on p1/p9/p12/p15"


def test_grey_zone_bands_are_flagged_not_split():
    _, greys = _split_census()
    assert len(greys) >= 4, "wrapped-label bands must land in the grey zone"
    assert {g[0] for g in greys} <= {"protocol12", "protocol15"}


def test_possible_split_recorded_on_rows(docs):
    flagged = [r for n in ["protocol12", "protocol15"]
               for r in main_table(docs[n])["rows"] if r.get("possible_split")]
    assert flagged, "grey-zone bands must carry a structured possible_split"
    for r in flagged:
        lines = r["possible_split"]["stub_lines"]
        assert len(lines) >= 2 and all("label" in l and "marks" in l for l in lines)


def test_protocol5_gains_the_saline_row(docs):
    labels = [r["label_verbatim"] for r in main_table(docs["protocol5"])["rows"]]
    assert "Saline/20 mg cocaine/40 mg cocaine i.v." in labels
    assert "20 mg cocaine i.v." in labels, "the split must add the second row"


# ---------- M3: divider detection ----------

@pytest.mark.parametrize("name", ["protocol12", "protocol15"])
def test_randomization_column_is_a_divider(docs, name):
    cols = main_table(docs[name])["columns"]
    dividers = [c for c in cols if c["role"] == "divider"]
    assert len(dividers) == 1, f"{name} must expose the RANDOMIZATION divider"
    assert "RANDOM" in dividers[0]["label_verbatim"].upper()


@pytest.mark.parametrize("name", ["protocol12", "protocol15"])
def test_divider_columns_are_not_timepoints(docs, name):
    for c in main_table(docs[name])["columns"]:
        if c["role"] == "divider":
            assert c["role"] != "study_day"
    ids = {c["id"] for c in main_table(docs[name])["columns"] if c["role"] == "divider"}
    used = {c["col_id"] for c in main_table(docs[name])["cells"]}
    assert not (ids & used), "no cells may be emitted against a divider column"


def test_protocol5_session_strip_is_a_row_divider(docs):
    rows = main_table(docs["protocol5"])["rows"]
    dividers = [r for r in rows if r["role"] == "divider"]
    assert any("Session" in r["label_verbatim"] for r in dividers), \
        "the Cocaine Infusion Session # strip is a row divider, not an assessment"


# ---------- ARCHITECTURE §3 step 1: spanning values (colspan) ----------

def test_prior_to_day_4_is_one_span_cell(docs):
    """Positive: the run crosses column boundaries -> one cell, colspan 3."""
    t = main_table(docs["protocol9"])
    spans = [c for c in t["cells"] if c["value_verbatim"] == "Prior to Day 4"]
    assert len(spans) == 3, "all three affected rows must carry the span"
    for c in spans:
        assert c["colspan"] == 3, f"expected colspan 3, got {c['colspan']}"
    # and no fragments survive
    frags = [c["value_verbatim"] for c in t["cells"]
             if c["value_verbatim"] in ("Prio", "r to D", "ay 4")]
    assert not frags, f"fragments still present: {frags}"


def test_p28_admission_row_is_one_span_cell(docs):
    t = main_table(docs["protocol9"])
    hit = [c for c in t["cells"] if c["value_verbatim"].startswith("Admission, Monday")]
    assert len(hit) == 1, "the Admission/Monday/Wednesday run must be one cell"
    assert hit[0]["colspan"] > 1
    assert hit[0]["value_verbatim"] == \
        "Admission, Monday, Wednesday, Friday, Discharge and As Needed"


def test_adjacent_marks_never_merge(docs):
    """Negative: X | X in neighbouring columns stay separate cells."""
    from soa.marks import is_mark_token
    for name in ["protocol1", "protocol5", "protocol9", "protocol12", "protocol15"]:
        for t in docs[name]["tables"]:
            for c in t["cells"]:
                if c["colspan"] > 1:
                    toks = c["value_verbatim"].split()
                    assert not (toks and all(is_mark_token(x) for x in toks)), \
                        f"{name} {t['id']} merged marks into a span: {c['value_verbatim']!r}"


def test_spans_only_where_expected(docs):
    """A span must never appear in a table that has no spanning text."""
    t5 = main_table(docs["protocol5"])
    assert all(c["colspan"] == 1 for c in t5["cells"]), \
        "protocol5's main SoA has no spanning cell values"
