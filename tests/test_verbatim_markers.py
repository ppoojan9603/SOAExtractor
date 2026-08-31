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

def test_binding_counts_unchanged(docs):
    def bound(name):
        t = docs[name]["tables"][0]
        return sum(1 for f in t["footnotes"] if f.get("attaches_to")), len(t["footnotes"])
    assert bound("protocol12") == (13, 14)
    assert bound("protocol15") == (4, 5)
    assert bound("protocol9") == (4, 4)


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

def test_equal_size_raised_marker_is_a_known_gap(docs):
    """protocol15 'Serum prolactin' prints a marker the SAME size as the X, only
    raised. The detector requires smaller size, so it does not fire: those cells
    keep the marker inside the value ('a\\nX') with empty footnote_markers. This
    is a SEPARATE, pre-existing detector gap (not the double-count bug) and is
    left documented rather than silently 'fixed' -- extending the detector would
    change binding to 5/5, which is out of scope here.

    This test pins the current state so any future detector change surfaces.
    """
    t = docs["protocol15"]["tables"][0]
    prolactin = [c for c in t["cells"]
                 if re.match(r"^[a-jA-J]\n", c["value_verbatim"])]
    assert prolactin, "the known-gap cells should still be present and visible"
    for c in prolactin:
        # the marker is trapped in the value and NOT in footnote_markers ->
        # no double-count (agreed gate 1 still holds for these)
        assert not c["footnote_markers"]
