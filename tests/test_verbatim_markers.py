"""Regression: superscript footnote markers must not double-count into value_verbatim.

Found via the vision benchmark: cells showed value_verbatim like 'a\\nX' (severe,
raised marker split onto its own line by extract_table) or 'Xa' (mild) with the
marker ALSO in footnote_markers. The marker belongs only in footnote_markers;
value_verbatim is the cell text with detected superscripts removed.
"""
from __future__ import annotations

import re
from collections import Counter

import pdfplumber
import pytest

from soa.pipeline import run
from soa.ingest import ingest_page
from soa.extract.grid import gridify_page

FIVE = ["protocol1", "protocol5", "protocol9", "protocol12", "protocol15"]
SOA = {"protocol1": [53, 54], "protocol5": [50], "protocol9": [26, 27, 28],
       "protocol12": [48], "protocol15": [25]}


@pytest.fixture(scope="module")
def docs():
    return {n: run(f"data/protocols/{n}.pdf", max_candidates=3) for n in FIVE}


# ---------- agreed gate 1: no value token also in its own footnote_markers ----------

@pytest.mark.parametrize("name", FIVE)
def test_no_double_count(docs, name):
    for t in docs[name]["tables"]:
        for c in t["cells"]:
            markers = set(c.get("footnote_markers") or [])
            value_letters = set(re.findall(r"[A-Za-z]", c["value_verbatim"]))
            assert not (markers & value_letters), (
                f"{name} {c['row_id']}/{c['col_id']}: marker also in value "
                f"{c['value_verbatim']!r} / {sorted(markers)}")


# ---------- addition 1: no silent loss ----------

def test_no_silent_loss():
    """value_verbatim + footnote_markers together must account for every non-space
    glyph the cell printed. The marker moves; nothing vanishes."""
    for name, pages in SOA.items():
        with pdfplumber.open(f"data/protocols/{name}.pdf") as pdf:
            for p in pages:
                pg = gridify_page(pdf.pages[p - 1], ingest_page(pdf.pages[p - 1]))
                for row in pg.cells:
                    for gc in row:
                        if not gc.sup_markers:
                            continue
                        # case-insensitive: the detector normalises marker case
                        # ('CANTABelectJ' -> value 'CANTABelect' + marker 'j').
                        # That is normalisation, not loss.
                        printed = Counter(ch.lower() for ch in gc.text if not ch.isspace())
                        kept = Counter(ch.lower() for ch in gc.value if not ch.isspace())
                        kept.update(m.lower() for m in gc.sup_markers)
                        # every printed glyph is still present across value+markers
                        for ch, n in printed.items():
                            assert kept.get(ch, 0) >= n, (
                                f"{name} p{p} lost {ch!r}: printed {gc.text!r} -> "
                                f"value {gc.value!r} + markers {gc.sup_markers}")


# ---------- agreed gate 2: binding counts unchanged ----------

def test_binding_counts(docs):
    def bound(name):
        t = docs[name]["tables"][0]
        return sum(1 for f in t["footnotes"] if f.get("attaches_to")), len(t["footnotes"])
    assert bound("protocol12") == (13, 14)
    assert bound("protocol9") == (4, 4)
    # protocol15 moved 4/5 -> 5/5 intentionally: extending the detector to accept
    # an EQUAL-SIZE raised marker (guarded by document-defined keys) binds 'a' to
    # the 'Serum prolactin' cells, which previously trapped it in the value as
    # 'a\nX'. This is the one deliberate binding change (see grid.
    # promote_equal_size_markers and test_equal_size_raised_marker_now_bound).
    assert bound("protocol15") == (5, 5)


# ---------- agreed gate 3: legitimate wrapped labels survive exactly ----------

def test_legit_wrapped_labels_survive(docs):
    """A naive newline-strip would destroy real content; these must be exact.
    They appear across rows, columns, and cell values -- scan all three."""
    strings = set()
    for t in docs["protocol9"]["tables"]:
        strings |= {r["label_verbatim"] for r in t["rows"]}
        strings |= {c["label_verbatim"] for c in t["columns"]}
        strings |= {c["value_verbatim"] for c in t["cells"]}
    for keep in ("Study\nDay", "Standard\nDeviation", "Standard\nError"):
        assert keep in strings, f"legit wrapped label lost: {keep!r}"


def test_multichar_value_keeps_content(docs):
    """'d\\n3X' -> '3X' (marker removed, count prefix kept), not '' or 'd3X'."""
    vals = [c["value_verbatim"] for c in docs["protocol12"]["tables"][0]["cells"]]
    assert "3X" in vals


# ---------- addition 2: multi-marker cell recorded, not silent ----------

def test_multi_marker_cell_recorded(docs):
    """protocol12 ASI-Lite 12/Term prints 'Xc Xe': comes out 'X X' + [c,e]
    (per-mark association lost). Acceptable ONLY because it is flagged."""
    t = docs["protocol12"]["tables"][0]
    multi = [c for c in t["cells"] if len(c.get("footnote_markers") or []) > 1]
    assert multi, "expected at least one multi-marker cell"
    kinds = {w["kind"] for w in t["warnings"]}
    assert "multi_marker_cell" in kinds, "multi-marker cells must be flagged, not silent"


# ---------- known limitation: equal-size raised marker (detector gap) ----------

def test_equal_size_raised_marker_now_bound(docs):
    """protocol15 'Serum prolactin' prints a marker the SAME size as the X, only
    raised -- the base detector (which requires smaller size) misses it. The
    guarded equal-size promotion (grid.promote_equal_size_markers) now catches it
    BECAUSE the key is defined in the footnote block. Those cells read value 'X'
    with the marker in footnote_markers, and no 'a\\nX' severe form remains.
    """
    t = docs["protocol15"]["tables"][0]
    assert not any(re.match(r"^[a-jA-J]\n", c["value_verbatim"]) for c in t["cells"]), \
        "no equal-size-raised marker should remain trapped in a value"
    prolactin = next(r for r in t["rows"] if "prolactin" in r["label_verbatim"].lower())
    cells = [c for c in t["cells"] if c["row_id"] == prolactin["id"]]
    assert cells and all(c["value_verbatim"] == "X" for c in cells)
    assert all(c["footnote_markers"] for c in cells), "marker must be bound, not in value"


def test_equal_size_promotion_only_on_defined_keys(docs):
    """The decisive guard: an equal-size raised glyph is promoted ONLY when its
    key is document-defined. 'X wk 6' / 'X\\nwk 6' scope cells (protocol12 ASI-Lite,
    CANTABelect, Barratt) must NOT gain a spurious w/k/6 marker."""
    t = docs["protocol12"]["tables"][0]
    for name in ("CANTABelect", "Barratt"):
        row = next(r for r in t["rows"] if name in r["label_verbatim"])
        for c in (c for c in t["cells"] if c["row_id"] == row["id"]):
            spurious = set(c["footnote_markers"]) & set("wk6")
            assert not spurious, f"{name} {c['col_id']} gained spurious {spurious}"
    # ASI-Lite scope cell keeps only its legitimate 'b'
    asi = next(r for r in t["rows"] if "ASI-Lite" in r["label_verbatim"])
    c5 = next(c for c in t["cells"] if c["row_id"] == asi["id"] and c["col_id"] == "c5")
    assert c5["value_verbatim"] == "X wk 6" and c5["footnote_markers"] == ["b"]


# NOTE on the vision benchmark metric (post-fix): the strict-raw verbatim match
# on p12 p48 is 52.3% and is MISLEADING -- it compares vision's fused token 'Xb'
# against the now-correctly-separated geometric value 'X'. The metric to report
# is marker-aware: 100% row / 100% column / 98.5% verbatim. Do not cite 52.3%.
