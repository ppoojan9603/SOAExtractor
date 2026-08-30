"""Thin pdfplumber wrapper (ARCHITECTURE §1).

Does six small things and no grid reconstruction of its own:
rules (unioned + derived filter), extract_table with explicit lines, cell
bboxes, fill->cell mapping, char sizes, scan detection + strategy chain.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

import pdfplumber

#: A rule segment must be at least this fraction of the median char size thick
#: to be discarded as "not a rule". Derived, not tuned: measured flat across a
#: 24x ratio sweep on all five protocols, where snap_tolerance has a cliff
#: (FINDINGS §8, DECISIONS row 3).
RULE_THINNESS_RATIO = 0.25

#: Two rule coordinates within this fraction of the median char size are the
#: same line. Char-relative so it scales with the document's type size, not a
#: fixed point value (B1).
RULE_MERGE_RATIO = 0.2

#: Below this many characters a page with an image is treated as scanned.
SCANNED_CHAR_LIMIT = 50

#: Fill lightness range treated as "grey" (0 = black, 1 = white).
GREY_MIN, GREY_MAX = 0.05, 0.99


@dataclass
class Fill:
    """A filled rectangle that is an area fill, not a rule segment."""
    bbox: tuple[float, float, float, float]
    grey: bool
    cell: tuple[int, int] | None = None       # (row, col) once mapped
    classification: str = "unclassified"      # mark | banding | flagged


@dataclass
class PageIngest:
    page_number: int                          # 1-based
    rotation: int
    width: float
    height: float
    text: str
    words: list[dict]
    chars: list[dict]
    median_char_size: float
    v_rules: list[float]                      # x positions
    h_rules: list[float]                      # y positions
    fills: list[Fill]
    scanned: bool
    strategy: str                             # explicit-lines | text-fallback | none
    table_bbox: tuple[float, float, float, float] | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _lightness(color) -> float | None:
    """Normalise a pdfplumber colour to 0..1 lightness; None if unknown."""
    if color is None:
        return None
    if isinstance(color, (int, float)):
        return float(color)
    if isinstance(color, (list, tuple)) and color:
        vals = [float(c) for c in color if isinstance(c, (int, float))]
        if not vals:
            return None
        if len(vals) == 4:                    # CMYK -> rough lightness
            c, m, y, k = vals
            return max(0.0, 1.0 - min(1.0, max(c, m, y) + k))
        return sum(vals) / len(vals)
    return None


def _is_grey(color) -> bool:
    lit = _lightness(color)
    return lit is not None and GREY_MIN < lit < GREY_MAX


def _cluster(values: list[float], tol: float) -> list[float]:
    """Collapse near-duplicate coordinates into single representative lines."""
    if not values:
        return []
    out, group = [], [values[0]]
    for v in sorted(values)[1:]:
        if v - group[-1] <= tol:
            group.append(v)
        else:
            out.append(sum(group) / len(group))
            group = [v]
    out.append(sum(group) / len(group))
    return out


def _scope_to_table(
    v_raw: list[tuple[float, float, float]],
    h_raw: list[tuple[float, float, float]],
    median_size: float,
) -> tuple[list, list]:
    """Drop rules that are page furniture rather than part of the grid.

    The table's vertical rules are drawn as per-row segments in every one of
    these protocols, so no single segment spans the table -- but their *union*
    extent does, and it bounds the grid exactly. A horizontal rule outside that
    band is page furniture.

    Measured: this removes the stroked page-footer rule on protocol5 p50
    (y=550.7, table ends 523.3) and both strays on protocol15 p25 (y=727.2 and
    751.2, table ends 601.9), while keeping protocol1 p53's legitimate 39.7pt
    tall rows that a gap-based filter would cut.
    """
    if not v_raw or not h_raw:
        return v_raw, h_raw
    y_top = min(top for _, top, _ in v_raw)
    y_bot = max(bot for _, _, bot in v_raw)
    pad = 0.2 * median_size
    kept_h = [r for r in h_raw if y_top - pad <= r[0] <= y_bot + pad]
    return v_raw, (kept_h or h_raw)


def ingest_page(page) -> PageIngest:
    """Read one pdfplumber page into the structure the pipeline consumes."""
    chars = page.chars
    text = page.extract_text() or ""
    sizes = [c["size"] for c in chars if c.get("size")]
    median_size = statistics.median(sizes) if sizes else 10.0
    min_thick = RULE_THINNESS_RATIO * median_size

    # --- rules: union of rect-derived edges and page.lines (FINDINGS §8) ---
    # Each rule is kept with its extent so stray page furniture (a footer rule)
    # can be scoped out of the table below.
    v_raw: list[tuple[float, float, float]] = []   # (x, y_top, y_bottom)
    h_raw: list[tuple[float, float, float]] = []   # (y, x_left, x_right)
    for r in page.rects:
        w, h = r["x1"] - r["x0"], r["bottom"] - r["top"]
        if w <= min_thick and h > min_thick:              # vertical rule
            v_raw.append(((r["x0"] + r["x1"]) / 2, r["top"], r["bottom"]))
        elif h <= min_thick and w > min_thick:            # horizontal rule
            h_raw.append(((r["top"] + r["bottom"]) / 2, r["x0"], r["x1"]))
    for ln in page.lines:
        w, h = abs(ln["x1"] - ln["x0"]), abs(ln["bottom"] - ln["top"])
        if h <= min_thick and w > min_thick:
            h_raw.append(((ln["top"] + ln["bottom"]) / 2, min(ln["x0"], ln["x1"]), max(ln["x0"], ln["x1"])))
        elif w <= min_thick and h > min_thick:
            v_raw.append(((ln["x0"] + ln["x1"]) / 2, min(ln["top"], ln["bottom"]), max(ln["top"], ln["bottom"])))

    v_raw, h_raw = _scope_to_table(v_raw, h_raw, median_size)
    merge_tol = RULE_MERGE_RATIO * median_size
    v_rules = _cluster([v for v, _, _ in v_raw], tol=merge_tol)
    h_rules = _cluster([h for h, _, _ in h_raw], tol=merge_tol)

    # --- area fills: rects that are not rules ---
    fills = [
        Fill(bbox=(r["x0"], r["top"], r["x1"], r["bottom"]), grey=_is_grey(r.get("non_stroking_color")))
        for r in page.rects
        if (r["x1"] - r["x0"]) > min_thick and (r["bottom"] - r["top"]) > min_thick
    ]

    scanned = len(text.strip()) < SCANNED_CHAR_LIMIT and bool(page.images)
    if scanned:
        strategy = "none"
    elif len(v_rules) >= 3 and len(h_rules) >= 3:
        strategy = "explicit-lines"
    else:
        strategy = "text-fallback"

    return PageIngest(
        page_number=page.page_number,
        rotation=page.rotation or 0,
        width=page.width,
        height=page.height,
        text=text,
        words=page.extract_words(extra_attrs=["size"]) if not scanned else [],
        chars=chars,
        median_char_size=median_size,
        v_rules=v_rules,
        h_rules=h_rules,
        fills=fills,
        scanned=scanned,
        strategy=strategy,
    )


def ingest_pdf(path: str) -> list[PageIngest]:
    with pdfplumber.open(path) as pdf:
        return [ingest_page(p) for p in pdf.pages]
