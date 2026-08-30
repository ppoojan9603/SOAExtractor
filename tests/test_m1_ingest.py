"""M1 gates: recon numbers and grid dimensions (FINDINGS §1, §3, §8)."""
import pytest
import pdfplumber

from soa.ingest import ingest_page
from soa.marks import is_mark_token, count_marks
from soa.recon import survey, SOA_GRID_PAGES
from pathlib import Path

pytestmark = pytest.mark.needs_pdfs
PROTO = Path(__file__).resolve().parent.parent / "data" / "protocols"

PAGE_COUNT = {"protocol1": 97, "protocol5": 61, "protocol9": 57, "protocol12": 97, "protocol15": 61}
ROTATED = {"protocol1": [], "protocol5": [50, 51], "protocol9": [26, 27, 28, 29],
           "protocol12": [], "protocol15": []}
# top mark page must be a SoA grid page (FINDINGS §3)
TOP_MARK_PAGE = {"protocol1": 53, "protocol5": 50, "protocol9": 28, "protocol12": 48, "protocol15": 25}
# grid dims under the derived filter (FINDINGS §8). protocol15 measures 36 rows
# by two independent methods; the DECISIONS "37" was a hand count (noted in M1).
GRID = {"protocol1": (53, 30, 10), "protocol5": (50, 32, 12), "protocol9": (26, 24, 12),
        "protocol12": (48, 42, 10), "protocol15": (25, 36, 11)}


@pytest.mark.parametrize("name,pages", PAGE_COUNT.items())
def test_page_and_rotation(name, pages):
    s = survey(PROTO / f"{name}.pdf")
    assert s["pages"] == pages
    assert s["rotated"] == ROTATED[name]


@pytest.mark.parametrize("name,page", TOP_MARK_PAGE.items())
def test_top_mark_page_is_soa(name, page):
    s = survey(PROTO / f"{name}.pdf")
    assert s["by_mark"][0]["page"] == page
    assert page in SOA_GRID_PAGES[name] or (name == "protocol1" and page in (53, 54))


@pytest.mark.parametrize("name,page,rows,cols", [(n, *v) for n, v in GRID.items()])
def test_grid_dimensions(name, page, rows, cols):
    with pdfplumber.open(str(PROTO / f"{name}.pdf")) as pdf:
        g = ingest_page(pdf.pages[page - 1])
    assert (len(g.h_rules) - 1, len(g.v_rules) - 1) == (rows, cols)


def test_protocol5_title_reads_clean():
    """Engine-choice tripwire: pdfplumber reads the rotated title clean."""
    with pdfplumber.open(str(PROTO / "protocol5.pdf")) as pdf:
        text = pdf.pages[49].extract_text() or ""
    assert "Appendix I: Time and Events Schedule" in text


def test_shading_census():
    """FINDINGS §5: p9 p26 = 50 grey fills; p5 p50 = 88 grey fills."""
    with pdfplumber.open(str(PROTO / "protocol9.pdf")) as pdf:
        g9 = ingest_page(pdf.pages[25])
    with pdfplumber.open(str(PROTO / "protocol5.pdf")) as pdf:
        g5 = ingest_page(pdf.pages[49])
    assert sum(f.grey for f in g9.fills) == 50
    assert sum(f.grey for f in g5.fills) == 88


def test_mark_token_rejects_decoys():
    for good in ["X", "x", "3X", "1X", "Xa", "3Xd", "✓", "●", "(X)"]:
        assert is_mark_token(good), good
    for bad in ["X-ray", "2.5X", "3X/week", "Week", "XX", "chest"]:
        assert not is_mark_token(bad), bad
    assert count_marks("clinical history and chest X-ray indicative") == 0
