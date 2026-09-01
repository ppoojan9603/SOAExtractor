"""Gridify (ARCHITECTURE §3): geometric grid + shaded-mark classification.

Builds a table from a candidate span: extract_table per page using the ingest
rules, map area-fills to cells, classify each grey fill as mark vs banding via
the stub-column fill-union test, stack row-continuation pages, and emit the
schema's columns / rows / cells. No model.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

#: Stub label that marks the last header row (shared with structure.py).
TIMEPOINT_ROW = re.compile(r"study\s*(day|week)|^visit$|^week$|^day$", re.I)

import pdfplumber

from ..ingest import ingest_page, PageIngest
from ..marks import is_mark_token
from .stub import detect_stub_columns


@dataclass
class GCell:
    row: int
    col: int
    text: str
    bbox: tuple[float, float, float, float]
    shaded: bool = False
    colspan: int = 1
    sup_markers: list = field(default_factory=list)   # superscript footnote letters
    chars: list = field(default_factory=list)         # chars in this cell (baselines)
    promoted_ids: set = field(default_factory=set)    # equal-size raised marker chars

    @property
    def value(self) -> str:
        """Cell text with detected superscript markers removed (verbatim value).

        For cells with no superscript this is exactly the extract_table text, so
        every non-marker cell is untouched. For marker cells the raised glyph is
        excluded from the value (it lives in footnote_markers instead), fixing
        the double-count where 'a\\nX' / 'Xa' left the marker inside the value.
        `promoted_ids` adds equal-size raised glyphs promoted by the marker-driven
        guard (see promote_equal_size_markers).
        """
        if not self.sup_markers and not self.promoted_ids:
            return self.text
        return _value_without_superscripts(self.chars, self.text, self.promoted_ids)


@dataclass
class PageGrid:
    page: int
    n_rows: int
    n_cols: int
    cells: list[list[GCell]]           # [row][col]
    stub_cols: list[int]
    fills: list = field(default_factory=list)   # classified Fill objects (audit)
    group_bands: list = field(default_factory=list)  # (c0, c1, label) spans in header row 0
    banded_rows: set = field(default_factory=set)     # full-width stub-covering bands (section candidates)
    header_spans: dict = field(default_factory=dict)  # col -> full window run when a timepoint value spans cols
    header_rows: int = 2


def _cell_grid(v: list[float], h: list[float]) -> list[list[tuple]]:
    """bbox per cell from sorted rule positions."""
    v, h = sorted(v), sorted(h)
    out = []
    for r in range(len(h) - 1):
        row = []
        for c in range(len(v) - 1):
            row.append((v[c], h[r], v[c + 1], h[r + 1]))
        out.append(row)
    return out


def _header_row_count(text_grid: list[list[str]], stub_cols: list[int]) -> int:
    """Rows through the timepoint row are header; the rest is body."""
    stub = stub_cols[0] if stub_cols else 0
    for r in range(min(len(text_grid), 8)):
        if TIMEPOINT_ROW.search(text_grid[r][stub] or ""):
            return r + 1
    return 1


def _row_spans(words, cell_bboxes, n_cols, median_size, start_row):
    """Cells whose text is one continuous run crossing a column boundary.

    ARCHITECTURE §3 step 1. The trigger is the RUN's geometry -- a phrase like
    "Prior to Day 4" (protocol9 p26) is laid out as one run of words whose
    x-extent crosses vertical rules. Two adjacent single marks (`X` | `X`) are
    separated by a full column gap and never form one run, so they never merge.

    Returns {row: [(first_col, colspan, text)]}.
    """
    out: dict[int, list] = {}
    # a word gap wider than this ends the run; column pitch is several times it
    max_gap = 1.2 * median_size
    for r in range(start_row, len(cell_bboxes)):
        top, bottom = cell_bboxes[r][0][1], cell_bboxes[r][0][3]
        band = [w for w in words if top <= (w["top"] + w["bottom"]) / 2 <= bottom]
        if len(band) < 2:
            continue
        band.sort(key=lambda w: w["x0"])
        runs, cur = [], [band[0]]
        for w in band[1:]:
            same_line = abs((w["top"] + w["bottom"]) / 2
                            - (cur[-1]["top"] + cur[-1]["bottom"]) / 2) <= 0.4 * median_size
            if same_line and (w["x0"] - cur[-1]["x1"]) <= max_gap:
                cur.append(w)
            else:
                runs.append(cur); cur = [w]
        runs.append(cur)

        for run in runs:
            x0, x1 = run[0]["x0"], run[-1]["x1"]
            covered = [c for c in range(n_cols)
                       if min(x1, cell_bboxes[r][c][2]) - max(x0, cell_bboxes[r][c][0])
                       > 0.15 * median_size]
            if len(covered) < 2:
                continue
            if covered != list(range(covered[0], covered[-1] + 1)):
                continue                              # non-contiguous: leave alone
            text = " ".join(w["text"] for w in run).strip()
            if not text:
                continue
            # A run made entirely of mark tokens is not a spanning value: it is
            # independent per-column marks that happen to sit close together
            # (protocol9 `1X` `1X` in adjacent day columns). Marks are the one
            # thing that legitimately appears one-per-column, so this is the
            # exact boundary between a span and separate cells.
            if all(is_mark_token(w["text"]) for w in run):
                continue
            out.setdefault(r, []).append((covered[0], len(covered), text))
    return out


def _superscript_markers(chars: list[dict]) -> list[str]:
    """Footnote-letter markers drawn as superscripts in a cell (DECISIONS row 6).

    A char that is both smaller than the cell's body text AND raised above its
    baseline is a superscript; when it is a letter a-j it is a footnote marker,
    separate from value_verbatim. Subscripts (raised DOWN, e.g. FEV1) are not
    footnote markers and are ignored.
    """
    letters = [c for c in chars if (c.get("text") or "").strip()]
    if len(letters) < 2:
        return []
    from statistics import median
    sizes = [c["size"] for c in letters if c.get("size")]
    if not sizes:
        return []
    # Body size is the LARGEST common size, not the median: a cell can be just
    # ['c','X'] (protocol15 p25), where the median sits between the superscript
    # and the body glyph and no char looks small.
    body_size = max(sizes)
    body = [c for c in letters if c.get("size", body_size) >= 0.95 * body_size]
    if not body:
        return []
    base_mid = median([(c["top"] + c["bottom"]) / 2 for c in body])
    out = []
    for c in letters:
        sz = c.get("size", body_size)
        mid = (c["top"] + c["bottom"]) / 2
        raised = mid < base_mid - 0.1 * body_size      # sits above the body baseline
        if sz < 0.9 * body_size and raised and c["text"].lower() in "abcdefghij":
            out.append(c["text"].lower())
    return out


def _superscript_char_ids(chars: list[dict]) -> set[int]:
    """Object ids of the chars _superscript_markers flags as footnote markers.

    Same size+raise test as the detector, but returns the specific char objects
    so value_verbatim can exclude exactly those glyphs -- not by string surgery
    on the letter (which could delete real content) and not by newline-stripping
    (which would destroy legitimate wrapped labels).
    """
    letters = [c for c in chars if (c.get("text") or "").strip()]
    if len(letters) < 2:
        return set()
    from statistics import median
    sizes = [c["size"] for c in letters if c.get("size")]
    if not sizes:
        return set()
    body_size = max(sizes)
    body = [c for c in letters if c.get("size", body_size) >= 0.95 * body_size]
    if not body:
        return set()
    base_mid = median([(c["top"] + c["bottom"]) / 2 for c in body])
    ids = set()
    for c in letters:
        sz = c.get("size", body_size)
        mid = (c["top"] + c["bottom"]) / 2
        raised = mid < base_mid - 0.1 * body_size
        if sz < 0.9 * body_size and raised and c["text"].lower() in "abcdefghij":
            ids.add(id(c))
    return ids


def _value_without_superscripts(chars: list[dict], raw_text: str,
                                extra_ids: set | None = None) -> str:
    """Cell text with the detected superscript-marker glyphs removed.

    Rebuilt from the surviving char objects in reading order (line by line,
    left to right) with whitespace collapsed, so it is robust to the severe
    ('a\\nX') and mild ('Xa') forms alike -- both drop the raised letter and
    yield 'X'. `extra_ids` are equal-size raised chars promoted to markers by
    the marker-driven guard. Called only for cells that actually have a marker;
    every other cell keeps its extract_table text untouched.
    """
    sup_ids = _superscript_char_ids(chars) | (set(extra_ids) if extra_ids else set())
    if not sup_ids:
        return raw_text
    kept = [c for c in chars if id(c) not in sup_ids and (c.get("text") or "")]
    if not kept:
        return raw_text
    # group into visual lines by vertical midpoint, then order left to right
    body_size = max((c.get("size", 10.0) for c in kept), default=10.0)
    tol = 0.5 * body_size
    kept.sort(key=lambda c: (c["top"] + c["bottom"]) / 2)
    lines, cur, cur_mid = [], [], None
    for c in kept:
        mid = (c["top"] + c["bottom"]) / 2
        if cur_mid is None or abs(mid - cur_mid) <= tol:
            cur.append(c); cur_mid = mid if cur_mid is None else (cur_mid + mid) / 2
        else:
            lines.append(cur); cur, cur_mid = [c], mid
    lines.append(cur)
    text = " ".join("".join(c["text"] for c in sorted(ln, key=lambda c: c["x0"]))
                    for ln in lines)
    return re.sub(r"\s+", " ", text).strip()


#: Chars that may be a footnote marker (letters handled here; digits/symbols
#: are only ever promoted when they match a defined key).
_MARKER_ALPHABET = set("abcdefghijABCDEFGHIJ0123456789*†‡•◦")


def promote_equal_size_markers(pg: "PageGrid", defined: set[str], n_hdr: int) -> None:
    """Promote an equal-size raised glyph to a footnote marker, guarded.

    The base detector (`_superscript_markers`) requires the marker to be SMALLER
    than the body text. Some protocols (protocol15 'Serum prolactin') print the
    marker at the SAME size, raised only. Accept such a glyph as a marker ONLY
    when ALL hold:
      1. short token (<=2 chars) from the marker alphabet;
      2. raised above the cell's DOMINANT baseline (not merely on another line);
      3. it is NOT the dominant content (a non-raised value char remains);
      4. **decisive**: its key is DEFINED in this table's footnote block.
    (4) reuses the marker-driven design: an equal-size raised glyph becomes a
    marker only if the document itself defines that key. A stray raised char with
    no matching definition stays part of the value.
    """
    if not defined:
        return
    for r in range(n_hdr, pg.n_rows):
        for c in range(pg.n_cols):
            if c in pg.stub_cols:
                continue
            gc = pg.cells[r][c]
            letters = [ch for ch in gc.chars if (ch.get("text") or "").strip()]
            if len(letters) < 2:
                continue
            already = _superscript_char_ids(gc.chars)
            sizes = [ch["size"] for ch in letters if ch.get("size")]
            if not sizes:
                continue
            body = max(sizes)
            main = [ch for ch in letters if ch.get("size", body) >= 0.95 * body]
            dom_mid = max((ch["top"] + ch["bottom"]) / 2 for ch in main)  # value baseline
            promoted_ids, promoted_keys = set(), []
            for ch in letters:
                if id(ch) in already:
                    continue
                tok = ch["text"].strip()
                if len(tok) > 2 or tok[0] not in _MARKER_ALPHABET:
                    continue
                mid = (ch["top"] + ch["bottom"]) / 2
                if mid >= dom_mid - 0.25 * body:          # not raised above baseline
                    continue
                key = tok.lower()
                if key not in defined:                    # (4) not document-defined
                    continue
                promoted_ids.add(id(ch)); promoted_keys.append(key)
            if not promoted_keys:
                continue
            # (3) dominant-content guard: a non-raised value char must remain
            remaining = [ch for ch in letters
                         if id(ch) not in already and id(ch) not in promoted_ids]
            if not remaining:
                continue
            for k in promoted_keys:
                if k not in gc.sup_markers:
                    gc.sup_markers.append(k)
            gc.promoted_ids |= promoted_ids


def _group_bands(words: list[dict], cell_bboxes, n_cols: int, median_size: float):
    """Period bands in the group header row, from spanning word bboxes.

    ARCHITECTURE §4: a header cell parents the columns its bbox covers. Because
    extract_table splits a spanning header's text across every column it crosses
    ("Trea|tment"), the reliable signal is the WORD geometry: group the header
    row's words into phrases by x-gap, then map each phrase's x-extent onto the
    column boundaries it spans.
    """
    if not cell_bboxes or n_cols < 2:
        return []
    top, bottom = cell_bboxes[0][0][1], cell_bboxes[0][0][3]
    band_words = [w for w in words
                  if top - 1 <= (w["top"] + w["bottom"]) / 2 <= bottom + 1]
    if not band_words:
        return []
    band_words.sort(key=lambda w: w["x0"])
    gap = 1.2 * median_size
    phrases, cur = [], [band_words[0]]
    for w in band_words[1:]:
        if w["x0"] - cur[-1]["x1"] <= gap:
            cur.append(w)
        else:
            phrases.append(cur); cur = [w]
    phrases.append(cur)

    out = []
    for ph in phrases:
        x0, x1 = min(w["x0"] for w in ph), max(w["x1"] for w in ph)
        label = " ".join(w["text"] for w in ph).strip()
        covered = [c for c in range(n_cols)
                   if (cell_bboxes[0][c][0] + cell_bboxes[0][c][2]) / 2 >= x0 - 1
                   and (cell_bboxes[0][c][0] + cell_bboxes[0][c][2]) / 2 <= x1 + 1]
        if len(covered) >= 1 and label:
            out.append((covered[0], covered[-1], label))
    return out


def _fill_owner(fill_bbox, cell_bboxes) -> tuple[int, int] | None:
    fx = (fill_bbox[0] + fill_bbox[2]) / 2
    fy = (fill_bbox[1] + fill_bbox[3]) / 2
    for r, row in enumerate(cell_bboxes):
        for c, (x0, y0, x1, y1) in enumerate(row):
            if x0 - 0.5 <= fx <= x1 + 0.5 and y0 - 0.5 <= fy <= y1 + 0.5:
                return (r, c)
    return None


def gridify_page(pdf_page, g: PageIngest) -> PageGrid:
    v, h = sorted(g.v_rules), sorted(g.h_rules)
    table = pdf_page.extract_table({
        "vertical_strategy": "explicit", "horizontal_strategy": "explicit",
        "explicit_vertical_lines": v, "explicit_horizontal_lines": h,
    }) or []
    n_rows, n_cols = len(v) - 1, len(v) and max((len(r) for r in table), default=0)
    n_cols = len(v) - 1
    cell_bboxes = _cell_grid(v, h)
    grid = [[c or "" for c in (row + [""] * n_cols)][:n_cols] for row in table]
    while len(grid) < len(h) - 1:
        grid.append([""] * n_cols)

    text_grid = [[(grid[r][c] or "").strip() for c in range(n_cols)] for r in range(len(h) - 1)]
    stub_cols = detect_stub_columns(text_grid)

    # Spanning values: one run crossing a column boundary becomes ONE cell with
    # colspan, instead of fragments ("Prio" | "r to D" | "ay 4").
    hdr_rows = _header_row_count(text_grid, stub_cols)
    spans = _row_spans(g.words, cell_bboxes, n_cols, g.median_char_size, hdr_rows)
    colspan_map: dict[tuple[int, int], int] = {}
    for r, items in spans.items():
        for c0, width, text in items:
            if c0 in stub_cols:
                continue
            text_grid[r][c0] = text
            colspan_map[(r, c0)] = width
            for c in range(c0 + 1, c0 + width):
                text_grid[r][c] = ""

    # map grey fills to cells; non-grey and unowned fills are still tracked so
    # the orphan-fill audit (M5) can account for EVERY area-fill.
    fill_by_cell: dict[tuple[int, int], list] = {}
    for f in g.fills:
        if not f.grey:
            f.classification = "non-grey"
            continue
        owner = _fill_owner(f.bbox, cell_bboxes)
        if owner is None:
            f.classification = "flagged"           # grey fill in no cell -> audit
            continue
        f.cell = owner
        fill_by_cell.setdefault(owner, []).append(f)

    # Banding vs mark by the fill-union test (ARCHITECTURE §3, FINDINGS §5):
    # a row whose grey-fill union reaches a STUB column is decoration (protocol5
    # zebra, protocol12/15 section rows). "Near-full" is NOT a banding signal --
    # protocol9 assessments done on every visit fill all data columns yet are
    # real marks; the only reliable discriminator is whether the fill touches
    # the label column.
    shaded_cells: set[tuple[int, int]] = set()
    banded_rows: set[int] = set()
    for r in range(len(cell_bboxes)):
        cols_filled = {c for (rr, c) in fill_by_cell if rr == r}
        if not cols_filled:
            continue
        covers_stub = any(sc in cols_filled for sc in stub_cols)
        klass = "banding" if covers_stub else "mark"
        for c in cols_filled:
            for f in fill_by_cell[(r, c)]:
                f.classification = klass
            if klass == "mark":
                shaded_cells.add((r, c))
        # A full-width band covering the stub is a candidate SECTION band
        # (protocol12/15 Screening/Safety/Efficacy). Zebra striping also covers
        # the stub, so structure.py confirms with "no real body content"; a
        # zebra row has marks and is rejected there.
        if covers_stub and len(cols_filled) >= 0.6 * n_cols:
            banded_rows.add(r)

    # assign chars to cells for superscript-marker detection
    chars_by_cell: dict[tuple[int, int], list] = {}
    for ch in g.chars:
        cx = (ch["x0"] + ch["x1"]) / 2
        cy = (ch["top"] + ch["bottom"]) / 2
        owner = None
        for r, row in enumerate(cell_bboxes):
            for c, (x0, y0, x1, y1) in enumerate(row):
                if x0 <= cx <= x1 and y0 <= cy <= y1:
                    owner = (r, c); break
            if owner:
                break
        if owner:
            chars_by_cell.setdefault(owner, []).append(ch)

    cells = []
    for r in range(len(cell_bboxes)):
        row = []
        for c in range(n_cols):
            sup = _superscript_markers(chars_by_cell.get((r, c), []))
            row.append(GCell(r, c, text_grid[r][c] if r < len(text_grid) else "",
                             cell_bboxes[r][c], shaded=(r, c) in shaded_cells,
                             sup_markers=sup,
                             colspan=colspan_map.get((r, c), 1),
                             chars=chars_by_cell.get((r, c), [])))
        cells.append(row)
    # Period bands only exist when a group-header row sits ABOVE the timepoint
    # row. With a single header row (protocol1: 'VISIT 1 2 3 ...') the numbers ARE
    # the timepoints, not groups -- the word-extent fallback otherwise invents a
    # band per visit column.
    if hdr_rows >= 2:
        bands = _group_bands_from_rules(pdf_page, g, v, h, cell_bboxes, n_cols,
                                        stub_cols, hdr_rows)
        if not bands:                               # fallback: word-extent bands
            bands = _group_bands(g.words, cell_bboxes, n_cols, g.median_char_size)
    else:
        bands = []

    # A window value can span several columns (protocol15 '-4 to 0*' over the
    # Screening+Baseline columns). Same colspan mechanism as body cells, applied
    # to the timepoint header row: reconstruct the full run so window_verbatim is
    # not the fragment '-4 t'.
    header_spans: dict[int, str] = {}
    tp = hdr_rows - 1
    for r, items in _row_spans(g.words, cell_bboxes, n_cols, g.median_char_size, tp).items():
        if r != tp:
            continue
        for c0, width, text in items:
            if c0 in stub_cols:
                continue
            for c in range(c0, c0 + width):
                header_spans[c] = text

    return PageGrid(g.page_number, len(cell_bboxes), n_cols, cells, stub_cols,
                    fills=g.fills, group_bands=bands, banded_rows=banded_rows,
                    header_spans=header_spans)


def _group_bands_from_rules(pdf_page, g, v, h, cell_bboxes, n_cols, stub_cols, hdr_rows):
    """Period bands from the header row's SPANNING-CELL geometry (ARCHITECTURE §4).

    A group header cell that spans several timepoint columns suppresses the
    interior vertical rules beneath it in header row 0; the rules that DO cross
    row 0 are the real group boundaries. Partitioning the columns at those
    boundaries gives exact group spans -- including edge columns the group's
    centred text does not reach (protocol12 'Study Medication Administration'
    truly spans 1-3 .. 12/Term, not just 4..8). Labelled from the row-0 words in
    each span.
    """
    if hdr_rows < 2 or len(v) < 3:
        return []
    from statistics import median
    sizes = [c["size"] for c in pdf_page.chars if c.get("size")]
    min_thick = 0.25 * (median(sizes) if sizes else 10.0)
    vsegs = []
    for r in pdf_page.rects:
        w, ht = r["x1"] - r["x0"], r["bottom"] - r["top"]
        if w <= min_thick and ht > min_thick:
            vsegs.append(((r["x0"] + r["x1"]) / 2, r["top"], r["bottom"]))
    for ln in pdf_page.lines:
        w, ht = abs(ln["x1"] - ln["x0"]), abs(ln["bottom"] - ln["top"])
        if w <= min_thick and ht > min_thick:
            vsegs.append(((ln["x0"] + ln["x1"]) / 2,
                          min(ln["top"], ln["bottom"]), max(ln["top"], ln["bottom"])))
    y0, y1 = h[0], h[1]
    ymid = (y0 + y1) / 2
    # column boundary i is "present at row 0" if a vertical segment crosses ymid
    present = [i for i in range(len(v))
               if any(abs(x - v[i]) < 2 and t <= ymid <= b for x, t, b in vsegs)]
    if len(present) < 3:
        return []
    words0 = [w for w in g.words
              if y0 - 1 <= (w["top"] + w["bottom"]) / 2 <= y1 + 1]
    bands = []
    for a, b in zip(present, present[1:]):
        c0, c1 = a, b - 1                       # columns spanned by this header cell
        if c0 > c1 or c0 in stub_cols:
            continue
        xlo, xhi = v[a], v[b]
        label = " ".join(w["text"] for w in sorted(
            (w for w in words0 if xlo - 1 <= (w["x0"] + w["x1"]) / 2 <= xhi + 1),
            key=lambda w: w["x0"])).strip()
        label = re.sub(r"\s+", " ", label)
        if label:                               # a real group header, not a bare col
            bands.append((c0, c1, label))
    return bands


def _text_lines(cell: "GCell", tol: float) -> list[tuple[float, str]]:
    """Distinct baseline-grouped text lines inside one cell: (mid_y, text)."""
    if not cell.chars:
        return []
    lines: list[dict] = []
    for ch in sorted(cell.chars, key=lambda c: ((c["top"] + c["bottom"]) / 2, c["x0"])):
        mid = (ch["top"] + ch["bottom"]) / 2
        if lines and abs(mid - lines[-1]["mid"]) <= tol:
            lines[-1]["chars"].append(ch)
        else:
            lines.append({"mid": mid, "chars": [ch]})
    out = []
    for ln in lines:
        raw = "".join(c["text"] for c in sorted(ln["chars"], key=lambda c: c["x0"]))
        # Char-level joins double the spaces that pdfplumber's word grouping
        # already inserts; collapse runs so the line matches the page verbatim.
        txt = re.sub(r"\s+", " ", raw).strip()
        if txt:
            mids = [(c["top"] + c["bottom"]) / 2 for c in ln["chars"]]
            out.append((sum(mids) / len(mids), txt))
    return out


def evaluate_split(pg: "PageGrid", r: int, stub_cols: list[int], median_size: float):
    """Rule C-prime (DECISIONS row 4). Returns ("split", parts) | ("grey", parts) | None.

    Split a band ONLY when all three hold:
      (a) the stub holds >= 2 distinct label lines, AND
      (b) body mark clusters are baseline-aligned 1:1 with those label lines
          (cluster top within a char-size-relative tolerance), AND
      (c) the clusters' column sets are disjoint.
    Meets (a) with >=2 clusters but fails (b) or (c) -> grey zone: keep merged,
    emit a structured possible_split.
    """
    tol = 0.35 * median_size                       # char-size-relative (B1)
    stub = stub_cols[0] if stub_cols else 0
    label_lines = _text_lines(pg.cells[r][stub], tol)
    if len(label_lines) < 2:
        return None                                # (a) fails -> single row

    # body marks grouped into baseline clusters
    marks = []
    for c in range(pg.n_cols):
        if c in stub_cols:
            continue
        cell = pg.cells[r][c]
        if cell.shaded and not cell.text.strip():
            mid = (cell.bbox[1] + cell.bbox[3]) / 2
            marks.append((mid, c, ""))
            continue
        for mid, txt in _text_lines(cell, tol):
            marks.append((mid, c, txt))
    if not marks:
        return None

    clusters: list[dict] = []
    for mid, c, txt in sorted(marks):
        if clusters and abs(mid - clusters[-1]["mid"]) <= tol:
            clusters[-1]["cols"].add(c)
            clusters[-1]["items"].append((c, txt))
            clusters[-1]["mid"] = (clusters[-1]["mid"] + mid) / 2
        else:
            clusters.append({"mid": mid, "cols": {c}, "items": [(c, txt)]})

    parts = [{"label": t, "mid": m, "marks": []} for m, t in label_lines]
    if len(clusters) < 2:
        return None                                # nothing to split against

    # (b) 1:1 baseline alignment between label lines and clusters
    # DECISIONS row 4: cluster baseline within ~3pt of its label line, 1:1.
    # Char-size-relative (B1); at median 10pt this is the specified 3pt.
    align_tol = 0.3 * median_size
    aligned = len(clusters) == len(label_lines)
    if aligned:
        for part, cl in zip(parts, clusters):
            if abs(part["mid"] - cl["mid"]) > align_tol:
                aligned = False
                break
            part["marks"] = sorted(cl["items"])

    # (c) disjoint column sets
    disjoint = True
    for i in range(len(clusters)):
        for j in range(i + 1, len(clusters)):
            if clusters[i]["cols"] & clusters[j]["cols"]:
                disjoint = False
    if aligned and disjoint:
        return ("split", parts)

    # grey zone: keep merged, hand the reviewer the evidence
    for part, cl in zip(parts, clusters):
        part["marks"] = sorted(cl["items"])
    return ("grey", parts)


#: Milestone words drawn as a vertical letter-stack between column groups.
_DIVIDER_WORDS = ("RANDOMIZATION", "RANDOMISATION", "RANDOMIZE", "ENROLLMENT",
                  "ENROLMENT", "SCREENING", "TREATMENT", "WASHOUT")


def detect_divider_columns(pg: "PageGrid", n_hdr: int) -> list[int]:
    """Columns that are a vertical letter-stack milestone, not a timepoint.

    protocol12 p48 / protocol15 p25 draw RANDOMIZATION as one letter per body
    row down a full-height column. It is a divider between column groups, so it
    must not be read as a visit, and its single-glyph runs must not pollute the
    row axis.

    Strict test (a bare single-char ratio also matches X-mark columns):
      - body cells are single characters, mostly letters
      - concatenating them spells a known milestone word
      - the column carries no marks (no shaded cells, no X tokens)
    """
    out = []
    for c in range(pg.n_cols):
        if c in pg.stub_cols:
            continue
        body = [pg.cells[r][c] for r in range(n_hdr, pg.n_rows)]
        vals = [b.text.strip() for b in body if b.text.strip()]
        if len(vals) < 5:
            continue
        if any(b.shaded for b in body):
            continue
        # a cell may stack two letters, so measure and join on the
        # whitespace-stripped value
        flat = [re.sub(r"\s+", "", v) for v in vals]
        singles = [v for v in flat if len(v) <= 2]
        if len(singles) / len(flat) < 0.8:
            continue
        letters = "".join(v for v in flat if v.isalpha()).upper()
        if len(letters) < 5:
            continue
        if any(w in letters or letters in w for w in _DIVIDER_WORDS):
            out.append(c)
    return out


def detect_divider_rows(pg: "PageGrid", n_hdr: int) -> list[int]:
    """Body rows that are a second header strip rather than an assessment.

    protocol5 p50's `Cocaine Infusion Session #` strip re-labels the column axis
    mid-table: its stub is a heading and its body cells are bare ordinals, not
    marks.
    """
    out = []
    for r in range(n_hdr, pg.n_rows):
        stub_txt = " ".join(pg.cells[r][c].text for c in pg.stub_cols).strip()
        if not stub_txt or not re.search(r"(session|period|cycle|phase)\s*#?$",
                                         stub_txt, re.I):
            continue
        body = [pg.cells[r][c] for c in range(pg.n_cols) if c not in pg.stub_cols]
        vals = [b.text.strip() for b in body if b.text.strip()]
        if vals and all(re.fullmatch(r"[\d&\-–\s]+", v) for v in vals):
            out.append(r)
    return out


def build_pagegrids(pdf_path: str, pages: list[int]) -> list[PageGrid]:
    out = []
    with pdfplumber.open(pdf_path) as pdf:
        for p in pages:
            page = pdf.pages[p - 1]
            out.append(gridify_page(page, ingest_page(page)))
    return out
