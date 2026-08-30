"""Locator (ARCHITECTURE §2): score pages, assemble candidate spans.

No model, no keyword-as-primary. Returns ALL candidate spans above threshold,
ranked — a protocol may hold several SoAs (main + sub-study + PK + extension).
Each span carries its grid pages plus any footnote-definition pages found by
marker-driven lookahead.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..ingest import PageIngest
from ..marks import count_marks

_VISIT_VOCAB = re.compile(
    r"\b(day|week|visit|screening|baseline|treatment|follow|eot|cycle|month|term)\b", re.I
)
_TITLE = re.compile(
    r"schedule of (activities|assessments|events|measures)|time and events|"
    r"study flow chart|table of events|overview of study assessments", re.I
)


@dataclass
class PageScore:
    page: int
    is_grid: bool
    marks: int
    numeric_cells: int
    v_rules: int
    h_rules: int
    visit_hits: int
    has_title: bool
    score: float = 0.0


@dataclass
class Candidate:
    grid_pages: list[int]
    footnote_pages: list[int] = field(default_factory=list)
    score: float = 0.0
    kind: str = "unknown"


def _numeric_cell_density(text: str) -> int:
    return sum(1 for tok in text.split() if re.fullmatch(r"\d{1,3}", tok))


def score_page(g: PageIngest) -> PageScore:
    marks = count_marks(g.text)
    numeric = _numeric_cell_density(g.text)
    is_grid = (not g.scanned) and len(g.v_rules) >= 3 and len(g.h_rules) >= 5
    visit_hits = len(_VISIT_VOCAB.findall(g.text))
    has_title = bool(_TITLE.search(g.text))

    # three profiles: marked / numeric / borderless — score is the max.
    marked = marks / 12.0
    numeric_profile = (numeric / 20.0) if is_grid else 0.0
    borderless = (min(visit_hits, 12) / 12.0) if (g.strategy == "text-fallback" and marks >= 3) else 0.0
    base = max(marked, numeric_profile, borderless)
    if is_grid:
        base += 0.3                    # a real ruled grid is the strongest prior
    if has_title:
        base += 0.15                   # confirmatory boost only; never nominates alone
    return PageScore(g.page_number, is_grid, marks, numeric, len(g.v_rules),
                     len(g.h_rules), visit_hits, has_title, base)


#: A page scoring at/above this is a candidate. Deliberately low — recall is the
#: graded axis; a false candidate is cheap (the UI lists it), a miss is not.
THRESHOLD = 0.6


def _footnote_lookahead(pages: dict[int, PageIngest], last_grid: int, markers: set[str]) -> list[int]:
    """Scan the next 1-2 pages for lines keyed by the span's open markers."""
    found = []
    for p in (last_grid + 1, last_grid + 2):
        g = pages.get(p)
        if g is None or g.scanned:
            break
        text = g.text
        keyed = any(
            re.search(rf"(?m)^\s*[\(\[]?{re.escape(m)}[\)\]]?\s*[-–:.)]", text) or
            re.search(r"(?mi)^\s*(notes?|footnotes?)\b", text)
            for m in markers
        ) if markers else bool(re.search(r"(?mi)^\s*(notes?|footnotes?)\b", text))
        # also treat a low-grid page that repeats the title as a continuation
        if keyed and not (len(g.v_rules) >= 3 and len(g.h_rules) >= 5):
            found.append(p)
        else:
            break
    return found


def _used_markers(g: PageIngest) -> set[str]:
    """Footnote-ish markers appearing in the page text (used-but-maybe-undefined)."""
    out: set[str] = set()
    for m in re.findall(r"(?<=[A-Za-z0-9])(\*{1,4})", g.text):
        out.add(m)
    for m in re.findall(r"[A-Za-z0-9]([a-j])\b", g.text):     # superscript letters flattened
        out.add(m)
    return out


def locate(page_ingests: list[PageIngest]) -> list[Candidate]:
    pages = {g.page_number: g for g in page_ingests}
    scores = {g.page_number: score_page(g) for g in page_ingests}

    # contiguous runs of above-threshold GRID pages = spans (row-continuation),
    # but only join a page to the previous span when its column count matches
    # (±1): p9 p26/27/28 are all 13 verticals -> one table; p5 p50 (13) and p51
    # (17) are DIFFERENT tables and must stay two candidates (scope A).
    candidate_pages = sorted(p for p, s in scores.items() if s.score >= THRESHOLD and s.is_grid)
    spans: list[list[int]] = []
    for p in candidate_pages:
        prev = spans[-1][-1] if spans else None
        same_shape = prev is not None and abs(len(pages[p].v_rules) - len(pages[prev].v_rules)) <= 1
        if prev is not None and p == prev + 1 and same_shape:
            spans[-1].append(p)
        else:
            spans.append([p])

    out: list[Candidate] = []
    for span in spans:
        markers: set[str] = set()
        for p in span:
            markers |= _used_markers(pages[p])
        fn = _footnote_lookahead(pages, span[-1], markers)
        score = max(scores[p].score for p in span)
        out.append(Candidate(grid_pages=span, footnote_pages=fn, score=score))
    out.sort(key=lambda c: -c.score)
    return out
