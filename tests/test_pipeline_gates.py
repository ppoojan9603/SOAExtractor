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
