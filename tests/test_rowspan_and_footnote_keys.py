"""Defects 1-3 from the M8 review of protocol9's main SoA and protocol1's
footnote block. Each is a general class, pinned here on all five where the
class can be expressed.

1. A cell spanning two ruled bands was emitted as one row per band; where it was
   shaded, the empty upper half also became spurious marks.
2. Footnote definitions were matched only when keyed by the bare marker, so a
   document keying them by value+marker ("Xa = ...") lost its whole apparatus;
   legend definitions carrying no marker were never captured.
3. Parenthesised numbers were treated as footnote markers -- double-counted and
   applied inconsistently.
"""
from __future__ import annotations

import pytest

from soa.pipeline import run
from soa.extract.structure import _candidate_defs, extract_markers

FIVE = ["protocol1", "protocol5", "protocol9", "protocol12", "protocol15"]


@pytest.fixture(scope="module")
def docs():
    return {n: run(f"data/protocols/{n}.pdf", max_candidates=3) for n in FIVE}


# --- Defect 1: shaded rowspan merge ---------------------------------------

def test_split_shaded_cell_is_rejoined(docs):
    t = docs["protocol9"]["tables"][0]
    labels = {r["label_verbatim"] for r in t["rows"]}
    # both stub lines live on ONE row now
    merged = [l for l in labels if "(Sitting) Vital Signs" in l]
    assert len(merged) == 1 and "0800" in merged[0], merged
    # and it carries the marks, not an empty half
    rid = next(r["id"] for r in t["rows"] if "(Sitting) Vital Signs" in r["label_verbatim"])
    cells = [c for c in t["cells"] if c["row_id"] == rid]
    assert len(cells) == 11 and all(c["value_verbatim"].strip() for c in cells)


def test_row_and_shaded_counts_after_merge(docs):
    t = docs["protocol9"]["tables"][0]
    assert len(t["rows"]) == 40                                   # was 43
    assert sum(1 for c in t["cells"] if c.get("shaded")) == 193    # was 220


def test_legitimate_shaded_only_rows_are_untouched(docs):
    """GUARD 3, the failure that would lose real data: on protocol9 shading IS
    the mark, so a shaded-empty row with no mark-twin below is a real data row."""
    t = docs["protocol9"]["tables"][0]
    for name, n in [("Emesis Tracking", 10), ("Drop Out Day", 11)]:
        r = next(r for r in t["rows"] if name in r["label_verbatim"])
        cells = [c for c in t["cells"] if c["row_id"] == r["id"]]
        assert len(cells) == n and all(c["shaded"] for c in cells), name


def test_category_header_is_not_absorbed(docs):
    """GUARD 1: protocol9's 'Prior Medications' / 'Laboratory Assessments:' pair
    matches the column test by coincidence (one column) and must stay separate."""
    t = docs["protocol9"]["tables"][0]
    labels = [r["label_verbatim"] for r in t["rows"]]
    assert any(l.startswith("Prior Medications") and "Laboratory" not in l for l in labels)
    assert any("Laboratory Assessments" in l for l in labels)


@pytest.mark.parametrize("name", ["protocol1", "protocol5", "protocol12", "protocol15"])
def test_unshaded_protocols_cannot_express_the_signature(docs, name):
    """The negative gate: these four emit zero shaded cells, so the merge cannot
    fire on them at all -- their byte-identity is what proves it is inert."""
    t = docs[name]["tables"][0]
    assert sum(1 for c in t["cells"] if c.get("shaded")) == 0


# --- Defect 2: definition key family --------------------------------------

def test_value_plus_marker_key_binds(docs):
    """protocol1 keys its definitions 'Xa = ...', not 'a = ...'. Before the fix
    every table came back with footnotes: [] and markers a/b unbound."""
    t = docs["protocol1"]["tables"][0]
    by = {f["marker"]: f for f in t["footnotes"]}
    assert "a" in by and "b" in by
    assert by["a"]["attaches_to"] and by["b"]["attaches_to"]


def test_legend_definitions_bind_to_the_table(docs):
    t = docs["protocol1"]["tables"][0]
    legends = [f for f in t["footnotes"] if f["marker"] is None]
    assert len(legends) == 2                       # "X = ..." and "P = ..."
    for f in legends:
        assert [a["kind"] for a in f["attaches_to"]] == ["table"]


def test_bare_marker_documents_still_bind(docs):
    """The family must not regress the documents that key definitions plainly."""
    for name, bound, total in [("protocol9", 4, 4), ("protocol12", 13, 14), ("protocol15", 5, 5)]:
        t = docs[name]["tables"][0]
        assert (sum(1 for f in t["footnotes"] if f.get("attaches_to")), len(t["footnotes"])) \
            == (bound, total), name


def test_key_family_shapes():
    """The shapes are covered as a family, not case by case."""
    def markers(text, vals=None):
        return [m for m, _b in _candidate_defs(text, vals)]
    assert markers("Xa = Performed at this visit if ...") == ["a"]
    assert markers("a - Once per week during ...") == ["a"]
    assert markers("b: Taken at each visit for ...") == ["b"]
    assert markers("(c) At the final scheduled visit ...") == ["c"]
    assert markers("[d] Only in subjects suspected ...") == ["d"]
    assert markers("* Screening may be combined ...") == ["*"]
    # legend: only when the key is a value the table prints
    assert markers("X = Performed at this visit.", {"X"}) == [None]
    assert markers("X = Performed at this visit.", set()) == []
    # prose must not become a definition
    assert markers("CT = computed tomography", {"X"}) == []
    assert markers("SCID = The Structured Clinical Interview ...", {"X"}) == []


def test_lettered_prose_is_not_a_definition():
    """The punctuated 'a. body' shape is deliberately uncovered: protocol12/15
    print 'a. BSCS' as an outline while a-f are real markers elsewhere."""
    assert [m for m, _ in _candidate_defs("a. BSCS")] == []
    assert [m for m, _ in _candidate_defs("b. CGI-S")] == []


# --- Defect 3: parenthesised numbers are not markers ----------------------

def test_parenthesised_numbers_are_not_markers():
    assert extract_markers("Tobacco Withdrawal Scale (1700)\n(27)") == []
    assert extract_markers("(Sitting) Vital Signs\n(24, 33)") == []
    assert extract_markers("Xa") == ["a"]            # letters still detected
    assert extract_markers("see **") == ["**"]       # symbols still detected


def test_numbers_stay_verbatim_and_unmarked(docs):
    t = docs["protocol9"]["tables"][0]
    r = next(r for r in t["rows"] if "Tobacco Withdrawal Scale" in r["label_verbatim"])
    assert "(27)" in r["label_verbatim"]             # verbatim, still printed
    assert r["footnote_markers"] == []               # but not a footnote marker


def test_no_numeric_used_undefined_warnings(docs):
    for name in FIVE:
        t = docs[name]["tables"][0]
        undef = [w for w in t.get("warnings", []) if w["kind"] == "marker_used_undefined"]
        assert not any(any(ch.isdigit() for ch in w["detail"]) for w in undef), name
