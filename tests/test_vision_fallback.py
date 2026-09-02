"""Gates for the scanned-page vision fallback (behaviour B).

The five born-digital protocols must be untouched (fallback unreachable); the
synthetic scan must decline without a provider and extract-and-mark with one.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from soa.pipeline import run
from soa.scan_shortlist import shortlist_scanned_pages

FIXTURE_PDF = "tests/fixtures/protocol12_p48_scan.pdf"
FIXTURE_VISION = "tests/fixtures/protocol12_p48_vision.json"
FIVE = ["protocol1", "protocol5", "protocol9", "protocol12", "protocol15"]

pytestmark = pytest.mark.skipif(
    not Path(FIXTURE_PDF).exists(),
    reason="synthetic scan fixture absent (needs data/protocols/protocol12.pdf)")
# (conftest.py regenerates FIXTURE_PDF at collection time when the protocol is present)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.delenv("SOA_VISION_RECORDED", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


# ---------- gate: five byte-identical (fallback unreachable) ----------

@pytest.mark.parametrize("name", FIVE)
def test_five_byte_identical_with_flag(name):
    off = run(f"data/protocols/{name}.pdf", max_candidates=3, vision_fallback=False)
    on = run(f"data/protocols/{name}.pdf", max_candidates=3, vision_fallback=True)
    assert json.dumps(off, sort_keys=True) == json.dumps(on, sort_keys=True)
    assert "vision" not in off, "born-digital docs carry no vision status"


# ---------- gate: decline paths never empty-silently ----------

def test_flag_off_declines():
    doc = run(FIXTURE_PDF, vision_fallback=False)
    assert doc["tables"] == []
    assert doc["vision"]["declined"] is True
    assert doc["vision"]["scanned_pages"] == [1]


def test_flag_on_no_provider_declines():
    doc = run(FIXTURE_PDF, vision_fallback=True)
    assert doc["tables"] == []
    assert doc["vision"]["declined"] is True
    assert "no vision provider" in doc["vision"]["reason"]


# ---------- gate: flag on + provider -> marked vision table ----------

def test_flag_on_with_provider_extracts_and_marks(monkeypatch):
    monkeypatch.setenv("SOA_VISION_RECORDED", FIXTURE_VISION)
    doc = run(FIXTURE_PDF, vision_fallback=True)
    assert doc["vision"]["declined"] is False
    assert len(doc["tables"]) == 1
    t = doc["tables"][0]
    assert t["strategy"] == "vision-fallback"
    assert t["verbatim_guaranteed"] is False
    assert t["authored_by"] == "model"
    assert t["cells"] and all(c["authored_by"] == "model" for c in t["cells"])
    assert all(c["bbox"] is None for c in t["cells"])
    kinds = {w["kind"] for w in t["warnings"]}
    assert "vision_fallback" in kinds
    assert "orphan_word_audit_unavailable" in kinds


# ---------- gate: pixel shortlist puts p48 in top candidates ----------

def test_pixel_shortlist_ranks_the_soa_page():
    top = shortlist_scanned_pages("data/protocols/protocol12.pdf", top_k=3)
    assert 48 in [p.page for p in top]
    assert top[0].page == 48, "p48 is the densest grid on the page"


# ---------- gate: vision parity against committed p48 ----------

def _norm(s):
    import re
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def _marker_free(s):
    """Normalised, with a single trailing footnote-marker letter removed.

    The deterministic path now strips a row label's footnote marker into
    `footnote_markers` ('Alcohol breathalyzer', not 'breathalyzerf'), but the
    recorded vision fixture is raw model output that glues it back on
    ('Alcohol breathalyzerf', 'CANTABelectJ'). This is a marker *representation*
    difference, not a recall difference, so the parity comparison strips a
    trailing a-j marker from BOTH sides -- applied symmetrically it cannot inflate
    a mismatch, only align the two spellings of the same assessment.
    """
    import re
    return re.sub(r"[a-j]$", "", _norm(s))


def test_vision_parity_against_committed_p48(monkeypatch):
    monkeypatch.setenv("SOA_VISION_RECORDED", FIXTURE_VISION)
    vt = run(FIXTURE_PDF, vision_fallback=True)["tables"][0]
    gt = json.loads(Path("out/protocol12.json").read_text(encoding="utf-8"))["tables"][0]

    gt_rows = {_marker_free(r["label_verbatim"]) for r in gt["rows"]}
    v_rows = {_marker_free(r["label_verbatim"]) for r in vt["rows"]}
    row_recall = len(gt_rows & v_rows) / len(gt_rows)
    assert row_recall >= 0.95, f"row recall {row_recall:.0%}"

    gt_cols = [c for c in gt["columns"] if not c["id"].startswith("g")]
    gt_data = {_norm(c["label_verbatim"]) for c in gt_cols if c["role"] != "row_header"}
    v_cols = {_norm(c["label_verbatim"]) for c in vt["columns"]}
    col_recall = len(gt_data & v_cols) / len(gt_data)
    assert col_recall >= 0.85, f"column recall {col_recall:.0%}"
