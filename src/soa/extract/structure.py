"""Structure (ARCHITECTURE §4): deterministic hierarchy, roles, footnote binding.

No model. Header rows from the timepoint row down are the column headers; rows
below are body rows; footnote markers are matched against definitions parsed
from the span's footnote pages. Unmatched markers are flagged, never guessed.
"""
from __future__ import annotations

import re

from .grid import (PageGrid, evaluate_split, detect_divider_columns,
                   detect_divider_rows, promote_equal_size_markers,
                   _header_row_count, _is_tp_tok, is_mark_token)

from .grid import TIMEPOINT_ROW as _TIMEPOINT_ROW
_INT = re.compile(r"^\d{1,3}([/\-–]\w+)?$")
_MARKER_SUFFIX = re.compile(r"([*]{1,4}|[a-jA-J])$")


def _find_header_rows(pg: PageGrid) -> int:
    """Number of header rows -- delegates to the canonical body-cell rule
    (grid._header_row_count, candidate C). Inspecting the whole row rather than
    just the stub is what lets protocol1's stacked VISIT/WEEK header (vocabulary
    in column 1) be recognised as two header rows instead of one."""
    text_grid = [[c.text for c in row] for row in pg.cells]
    return _header_row_count(text_grid, pg.stub_cols)


def _split_marker(text: str) -> tuple[str, list[str]]:
    """Peel a trailing footnote marker off a verbatim cell/label value."""
    markers = []
    m = _MARKER_SUFFIX.search(text.strip())
    # only treat a trailing letter as a marker when it follows a mark glyph or
    # closing paren/word — kept conservative for the thin pass.
    if m and text.strip() not in ("",):
        pass
    return text, markers


#: Bare-symbol footnote markers that are always footnotes, never ordinals.
_SYMBOL_MARKERS = {"*", "**", "***", "****", "†", "‡", "•", "◦"}

_MARK_GLYPHS = "Xx✓✔√●○■□▪•"


def collect_used_markers(cells: list[dict], rows: list[dict], columns: list[dict]) -> set[str]:
    """Markers ACTUALLY used in the table's cells/labels (DECISIONS row 8).

    Footnote collection is driven by this set — never the other way round. The
    inversion (collect every definition-looking line, then keep it) is exactly
    what swept up numbered prose lists as fake markers.
    """
    used: set[str] = set()
    for c in cells:
        for m in (c.get("sup_markers") or []):
            used.add(m)
    for r in rows:
        for m in (r.get("sup_markers") or []):
            used.add(m)
    texts = ([c.get("value_verbatim", "") for c in cells]
             + [r.get("label_verbatim", "") for r in rows]
             + [c.get("label_verbatim", "") for c in columns])
    for t in texts:
        for run in re.findall(r"\*{1,4}", t):
            used.add(run)
        for d in re.findall(r"[†‡•◦]", t):
            used.add(d)
        # NOTE: a parenthesised number is NOT a marker. protocol9's (01)-(33) are
        # CRF form numbers ("Form numbers may change"), and across all five no
        # protocol defines a parenthesised number as a footnote -- every one that
        # occurs is undefined. They stay verbatim in the label instead. (Defect 3)
        # a mark glyph followed by a superscript-ish letter: Xa, ✓b
        for letter in re.findall(rf"[{_MARK_GLYPHS}]([a-j])(?![a-z])", t):
            used.add(letter)
    return used


def extract_markers(text: str) -> list[str]:
    """Footnote markers present in one verbatim string (same forms as collect)."""
    out = []
    for run in re.findall(r"\*{1,4}", text):
        out.append(run)
    for d in re.findall(r"[†‡•◦]", text):
        out.append(d)
    # Parenthesised numbers are deliberately NOT markers -- see collect_used_markers.
    # Extracting them double-counted (kept in label_verbatim AND added to
    # footnote_markers) and fired inconsistently ('(27)' matched, '(24, 33)' did
    # not). No protocol in the five defines one. (Defect 3)
    for letter in re.findall(rf"[{_MARK_GLYPHS}]([a-j])(?![a-z])", text):
        out.append(letter)
    # de-dup, keep order
    seen, uniq = set(), []
    for m in out:
        if m not in seen:
            seen.add(m); uniq.append(m)
    return uniq


def bind_markers(rows: list[dict], cells: list[dict], columns: list[dict],
                 footnotes: list[dict]) -> None:
    """Populate footnote_markers on cells/rows/cols and each footnote's
    attaches_to. Deterministic marker matching (ARCHITECTURE §4); nothing that
    fails to match is invented -- the footnote is simply left unanchored.
    """
    targets: dict[str, list[dict]] = {}
    for r in rows:
        for m in extract_markers(r["label_verbatim"]) + list(r.get("sup_markers") or []):
            if m in r["footnote_markers"]:
                continue
            r["footnote_markers"].append(m)
            targets.setdefault(m, []).append({"kind": "row", "id": r["id"]})
    for col in columns:
        for m in extract_markers(col.get("label_verbatim", "")):
            col["footnote_markers"].append(m)
            targets.setdefault(m, []).append({"kind": "column", "id": col["id"]})
    for c in cells:
        markers = extract_markers(c["value_verbatim"]) + list(c.get("sup_markers") or [])
        for m in markers:
            if m in c["footnote_markers"]:
                continue
            c["footnote_markers"].append(m)
            targets.setdefault(m, []).append(
                {"kind": "cell", "row_id": c["row_id"], "col_id": c["col_id"]})
    for f in footnotes:
        if f.get("marker") is None:
            continue                     # legend: already bound to the table
        tgt = targets.get(f.get("marker"), [])
        f["attaches_to"] = tgt
        f["unanchored"] = not tgt


def _merge_shaded_rowspan(rows: list[dict], cells: list[dict]) -> None:
    """Rejoin a shaded cell that one ruled band boundary split in two. (Defect 1)

    The grid is built from the union of ALL horizontal rules, so a rule drawn for
    other columns slices a cell it does not physically cross. Where that cell is
    shaded, the split yields an empty-but-shaded upper half and a marked lower
    half: a spurious row, a duplicated set of shaded marks, and a label divorced
    from its data (protocol9 p28 '(Sitting) Vital Signs (24, 33)' over
    '(0800, 1000, ...)', one grey cell carrying 6X across two day-bands).

    Signature: every emitted cell of the upper row is EMPTY and at least one is
    shaded, and the row immediately below re-marks EXACTLY the same columns.

    Guards, each pinned by a test:
      1. neither row may be a category_header or divider -- protocol9's
         'Prior Medications' / 'Laboratory Assessments:' pair matches the column
         test by coincidence (a single column) and must not be fused;
      2. the column sets must be EQUAL, not merely overlapping. A split cell is
         one rectangle, so both halves span exactly the same columns; requiring
         equality (rather than a ratio) is what stops an unrelated neighbouring
         row from being absorbed, and needs no threshold to tune;
      3. a shaded-empty row with NO mark-twin below is a legitimate mark row --
         on protocol9 shading IS the mark, and 7 such rows (Emesis Tracking,
         Drop Out Day, ...) carry real data. Requiring the lower row to re-mark
         the same columns leaves every one of them untouched. This is the
         failure that would lose real data, so it is gated explicitly.

    Validation note: the other four protocols emit ZERO shaded cells, so they
    cannot express this signature at all -- their byte-identity is the negative
    gate, not weak evidence.
    """
    by_row: dict[str, list[dict]] = {}
    for c in cells:
        by_row.setdefault(c["row_id"], []).append(c)
    merged: set[str] = set()
    for i in range(len(rows) - 1):
        up, dn = rows[i], rows[i + 1]
        if up["id"] in merged or dn["id"] in merged:
            continue
        if up.get("role") in ("category_header", "divider") or \
           dn.get("role") in ("category_header", "divider"):
            continue                                          # guard 1
        ucells = by_row.get(up["id"]) or []
        dcells = by_row.get(dn["id"]) or []
        if not ucells:
            continue
        if any(c["value_verbatim"].strip() for c in ucells):
            continue                                          # upper must be empty
        if not any(c.get("shaded") for c in ucells):
            continue                                          # ... and shaded
        ucols = {c["col_id"] for c in ucells}
        dmarked = {c["col_id"] for c in dcells if c["value_verbatim"].strip()}
        if not dmarked or ucols != dmarked:
            continue                                          # guards 2 and 3
        # one cell after all: join the two stub lines, keep the marks
        up["label_verbatim"] = (up["label_verbatim"] + "\n" + dn["label_verbatim"]).strip()
        up["sup_markers"] = list(up.get("sup_markers") or []) + list(dn.get("sup_markers") or [])
        for c in ucells:
            cells.remove(c)                                   # spurious shaded halves
        for c in dcells:
            c["row_id"] = up["id"]
        merged.add(dn["id"])
    if merged:
        rows[:] = [r for r in rows if r["id"] not in merged]


#: Separators a document may put between a definition key and its body. '=' is
#: the one protocol1 uses ("Xa = Performed at this visit if ..."); its absence
#: here is why protocol1's whole footnote apparatus was lost. (Defect 2)
_DEF_SEP = r"[-–—:=]"


def _candidate_defs(text: str, used_values: set[str] | None = None):
    """Yield (marker, body) for lines that look like footnote definitions.

    `marker` is None for a LEGEND definition -- one keyed by a value rather than
    a footnote marker ("X = Performed at this visit.", "P = Practice only ...").
    Those bind to the table, not to a cell.

    Key shapes covered as a family, not case by case:
      symbol run        *  **  †  ‡  •  ◦
      bare marker       a - ...      a: ...     a = ...
      value+marker      Xa = ...     ✓b: ...    (any mark glyph + a-j)
      bracketed         (a) ...      [a] ...
      legend, no marker X = ...      P = ...         (key is a used cell value)

    DELIBERATELY NOT COVERED: the punctuated shape "a. body" / "a) body". It is
    indistinguishable from a lettered prose list, and measurement says the
    collision is real, not hypothetical: protocol12 p50 and protocol15 p26 carry
    'a. BSCS', 'b. CGI-S', 'c. CGI-O' ... as an assessment OUTLINE while those
    same letters a-f are genuine footnote markers elsewhere in the table. So a
    "keep it only if the marker is used" guard does not separate them either --
    the markers are used. Covering the shape added 4 spurious footnotes to
    protocol12 and 6 to protocol15. No protocol in the five keys a definition
    that way, so it is left out rather than shipped unvalidated.
    """
    used_values = {v.strip().lower() for v in (used_values or set()) if v and v.strip()}
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        # asterisk / dagger run, space optional (protocol12 "****CBT")
        m = re.match(r"^(\*{1,4}|[†‡•◦])\s*(\S.*)$", s)
        if m:
            yield m.group(1), m.group(2).strip()
            continue
        # bracketed marker: (a) body / [a] body
        m = re.match(r"^[\(\[]([a-jA-J])[\)\]]\s*" + _DEF_SEP + r"?\s*(\S.*)$", s)
        if m:
            yield m.group(1).lower(), m.group(2).strip()
            continue
        # marker, optionally carried on its mark glyph (Xa, ✓b), then a separator
        m = re.match(rf"^[{_MARK_GLYPHS}]?([a-jA-J])\s*{_DEF_SEP}\s*(\S.*)$", s)
        if m:
            yield m.group(1).lower(), m.group(2).strip()
            continue
        # LEGEND: keyed by a value the table actually prints ("X = ...", "P = ...").
        # The used-values guard is what keeps prose out: "CT = computed tomography"
        # and "SCID = The Structured ..." are not cell values, so they never match.
        m = re.match(rf"^(\S{{1,3}})\s*{_DEF_SEP}\s+(\S.*)$", s)
        if m and m.group(1).strip().lower() in used_values:
            yield None, m.group(2).strip()
            continue
        # numeric marker then separator (kept only if used — see build_footnotes)
        m = re.match(r"^\(?(\d{1,2})\)?\s*[-–:.)]\s+(\S.*)$", s)
        if m:
            yield m.group(1), m.group(2).strip()


def _defined_marker_keys(fn_pages_text: list[tuple[int, str]]) -> set[str]:
    """The set of marker keys DEFINED in the footnote block (lowercased).

    Reuses _candidate_defs, so the equal-size-raised promotion (grid.py) can only
    fire on a key the document actually defines -- the decisive guard.
    """
    keys = set()
    for _page, text in fn_pages_text:
        for marker, _body in _candidate_defs(text):
            # Exclude bare digits: _candidate_defs also matches numbered prose
            # ("1. Informed consent"), and build_footnotes drops those as ordinals.
            # A stray '2' would otherwise be promoted out of 'Weekly x 2 weeks'.
            # Real footnote markers here are letters and symbols. A legend
            # definition (marker None) keys no marker at all.
            if marker is None or marker.isdigit():
                continue
            keys.add(marker.lower())
    return keys


def build_footnotes(fn_pages_text: list[tuple[int, str]], used: set[str],
                    used_values: set[str] | None = None) -> list[dict]:
    """Collect definitions keyed by USED markers, plus bare symbols and legends.

    Keep a candidate iff its marker is used, or it is a bare-symbol/letter
    footnote form. A purely numeric marker that is NOT used is an ordinal list
    item (protocol12/15 numbered prose) and is dropped. A LEGEND (marker None) defines a
    printed value rather than a marker and attaches to the table. A real footnote
    whose usage we could not detect is kept but emitted unanchored, never invented.
    """
    out = []
    seen = set()
    for page, text in fn_pages_text:
        for marker, body in _candidate_defs(text, used_values):
            if len(body) < 4:
                continue
            key = (marker, body[:30])
            if key in seen:
                continue
            if marker is None:                            # legend -> binds to table
                seen.add(key)
                out.append({"marker": None, "text_verbatim": body[:400],
                            "source_pages": [page], "continued_from_previous_page": False,
                            "unanchored": False, "attaches_to": [{"kind": "table"}]})
                continue
            is_numeric = marker.isdigit()
            used_here = marker in used
            if is_numeric and not used_here:
                continue                                  # ordinal list -> drop
            if not used_here and marker not in _SYMBOL_MARKERS and not marker.isalpha():
                continue
            seen.add(key)
            out.append({"marker": marker, "text_verbatim": body[:400],
                        "source_pages": [page], "continued_from_previous_page": False,
                        "unanchored": not used_here, "attaches_to": []})
    return out


def header_bands(pg: PageGrid, n_hdr: int, data_start: int) -> list[tuple[int, int, str]]:
    """Reconstruct period bands from the group header row.

    A spanning header's text is split by extract_table across every column its
    bbox covers ("Trea|tment", "Base|line|ions"), so a band is a run of
    consecutive data columns whose group-row cells are non-empty, joined in
    order. A run ends at an empty cell -- that gap is the real span boundary.
    """
    if n_hdr < 2:
        return []
    bands, run, parts = [], [], []
    for c in range(data_start, pg.n_cols):
        txt = (pg.cells[0][c].text or "").strip()
        if txt:
            run.append(c); parts.append(txt)
        elif run:
            bands.append((run[0], run[-1], " ".join(parts).replace(chr(10), " ")))
            run, parts = [], []
    if run:
        bands.append((run[0], run[-1], " ".join(parts).replace(chr(10), " ")))
    return bands


def _timepoint_rows(header: PageGrid, n_header_rows: int) -> list[int]:
    """Header rows that are timepoint rows (body cells majority short timepoint
    tokens). A group row (text like 'Screening/Baseline') has none; protocol1 has
    two stacked (VISIT numbers, then study WEEK)."""
    stub = set(header.stub_cols)
    out = []
    for r in range(n_header_rows):
        ne = [header.cells[r][c].text for c in range(header.n_cols)
              if c not in stub and header.cells[r][c].text.strip()]
        if ne and sum(1 for b in ne if _is_tp_tok(b)) >= 0.5 * len(ne):
            out.append(r)
    return out


def build_columns(header: PageGrid, n_header_rows: int) -> list[dict]:
    """Columns as a tree: period bands parent the timepoint columns they cover."""
    cols = []
    # Which header rows are timepoint rows (majority short timepoint tokens in
    # the body). protocol1 has TWO stacked -- VISIT number (row0) and study WEEK
    # (row1); the others have one. The primary timepoint row (last one) drives
    # role/window/study_day; when two are stacked, the FIRST supplies the visit
    # label and the LAST the study-day/week value.
    tp_rows = _timepoint_rows(header, n_header_rows)
    day_row = tp_rows[-1] if tp_rows else n_header_rows - 1
    label_row = tp_rows[0] if len(tp_rows) >= 2 else day_row
    two_stacked = len(tp_rows) >= 2
    data_start = _leading_label_cols(header, n_header_rows)
    bands = [b for b in header.group_bands if b[0] >= data_start]
    dividers = set(detect_divider_columns(header, n_header_rows))

    # band parents first, so children can reference them
    band_of: dict[int, str] = {}
    for bi, (c0, c1, label) in enumerate(bands):
        bid = f"g{bi}"
        cols.append({"id": bid, "parent_id": None, "level": 0,
                     "label_verbatim": label, "role": "period",
                     "colspan": c1 - c0 + 1, "footnote_markers": [],
                     "covers": [c0, c1]})
        for c in range(c0, c1 + 1):
            band_of[c] = bid

    for c in range(header.n_cols):
        label = header.cells[label_row][c].text
        if c in dividers:
            # a milestone letter-stack: never a timepoint (DECISIONS row 9)
            joined = "".join(
                re.sub(r"\s+", "", header.cells[r][c].text)
                for r in range(header.n_rows)).strip()
            cols.append({"id": f"c{c}", "index": c, "parent_id": None, "level": 0,
                         "label_verbatim": joined, "role": "divider", "colspan": 1,
                         "footnote_markers": []})
            continue
        if c in header.stub_cols:
            role, window = "row_header", None
        else:
            role, window = _column_role_and_window(header.cells[day_row][c].text)
            # stacked headers: an ET/RT visit column has no study-week value, so
            # the day row is empty -> fall back to the visit-label row for the role
            if two_stacked and role == "unknown":
                role = _column_role_and_window(header.cells[label_row][c].text)[0]
            # a window value spanning several columns (protocol15 '-4 to 0*'):
            # use the reconstructed full run, not this column's fragment label
            if c in header.header_spans:
                role = "study_day"
                window = header.header_spans[c]
        parent = band_of.get(c) if role != "row_header" else None
        col = {"id": f"c{c}", "index": c, "parent_id": parent,
               "level": 1 if parent else 0,
               "label_verbatim": label, "role": role, "colspan": 1,
               "footnote_markers": []}
        # two stacked timepoint rows (protocol1): the visit number is the label,
        # the study day/week is a distinct axis -- NOT a window (a window is an
        # allowable range like 'Day 15 +/- 3 days'; '-2' is a study week).
        if two_stacked and role in ("study_day", "visit"):
            sd = header.cells[day_row][c].text
            if sd.strip():
                col["study_day_verbatim"] = sd
        if window is not None:
            col["window_verbatim"] = window          # graded, lossless
            col["window_parsed"] = _parse_window(window)   # advisory, may be null
        cols.append(col)
    return cols


def _column_role_and_window(label: str) -> tuple[str, str | None]:
    """Role + window_verbatim for a timepoint column.

    A bare point ('4', '-6', 'ET') is a study_day/visit with no window. A label
    that expresses a span or relative timing ('1-3', '9 -11', '12/ Term',
    '-4 to 0*', 'Up to -35', '14-21 days prior to randomization', 'Day 15 ± 3
    days') is still a timepoint column, and its verbatim label is the visit
    window -- named explicitly in the spec. Whitespace is normalised only for
    the TEST; window_verbatim keeps the original label losslessly.
    """
    n = re.sub(r"\s+", " ", (label or "")).strip()
    if not n:
        return "unknown", None
    if re.fullmatch(r"-?\d{1,3}", n):                     # bare point
        return "study_day", None
    if re.fullmatch(r"(ET|RT|EOT)", n, re.I):
        return "visit", None
    is_window = bool(re.search(r"\d", n) and (
        re.search(r"[-–]\s*\d", n) or
        re.search(r"\b(to|thru|through|prior|up to)\b|±|\+/-|/\s*term|day|week", n, re.I)))
    if is_window:
        return "study_day", label                         # verbatim, unnormalised
    if re.search(r"\d", n):
        return "study_day", None
    # A words-only header ('VISIT', 'WEEK', 'Study Day') is a LABEL column, not a
    # timepoint -- real timepoint columns always carry a digit/ET/RT. Do NOT use a
    # bare day|week|visit word match here: it misclassified protocol1's 'VISIT'
    # label column as a timepoint and shifted the column merge.
    return "unknown", None


def _parse_window(verbatim: str) -> dict | None:
    """Advisory parse of the 'Day N ± M days' window form. Null for anything else.

    Handles ASCII '+/-' and unicode '±'. Deliberately does NOT invent parses for
    forms we cannot test on the five (ranges/relative strings keep parsed=null);
    window_verbatim already carries those losslessly.
    """
    n = re.sub(r"\s+", " ", verbatim or "")
    m = re.search(r"(?:day|week)?\s*(-?\d+)\s*(?:±|\+/-)\s*(\d+)", n, re.I)
    if m:
        day, delta = int(m.group(1)), int(m.group(2))
        return {"day": day, "minus": delta, "plus": delta}
    return None


def _body_has_content(cells, stub_cols, n_cols, divider_cols=frozenset()) -> bool:
    """Any real body content, ignoring stub and divider columns.

    Divider columns (RANDOMIZATION) leak a stacked letter into every row; without
    excluding them a section row like 'Safety' looks non-empty (its band row
    catches the divider's 'Z') and is misread as an assessment.
    """
    return any(cells[c].text.strip() or cells[c].shaded
               for c in range(n_cols) if c not in stub_cols and c not in divider_cols)


def classify_empty_band(label: str) -> str:
    """Role for a body-empty band whose stub carries text (correction 1).

    A ruling can separate a label's overflow line from its own row (the inverse
    of the Saline split). Measured case: protocol9 p26 "(Study Day 1 and Exit
    Day)" sits in its own ruled band below "Physical Examination (04)" with zero
    body fills and zero body words.

      - starts with "(" or a lowercase letter -> label_continuation (merge up)
      - ends with ":"                          -> category_header
      - otherwise                              -> metadata (blank capture row,
                                                  e.g. Date / Day of Week)
    """
    t = label.strip()
    if not t:
        return "metadata"
    if t.startswith("(") or (t[:1].isalpha() and t[:1].islower()):
        return "label_continuation"
    if t.rstrip().endswith(":"):
        return "category_header"
    return "metadata"


_TP_VALUE = re.compile(r"^(\d{1,3}([/\-–]\w+)?|ET|RT|EOT|-?\.?\d)$", re.I)


def _leading_label_cols(pg: PageGrid, n_hdr: int) -> int:
    """How many leading columns are the label region (before the first timepoint).

    protocol1 has TWO: the ACTIVITY label column and a narrow VISIT/WEEK column,
    then the visit-numbered data columns. Detected from the timepoint header row:
    the first column whose header cell is a timepoint value starts the data.
    """
    tp = n_hdr - 1
    for c in range(pg.n_cols):
        if c in pg.stub_cols:
            continue
        role, _ = _column_role_and_window(pg.cells[tp][c].text)
        if role in ("study_day", "visit"):     # first real timepoint column
            return c
    return max(pg.stub_cols) + 1 if pg.stub_cols else 1


def _row_labels(pg: PageGrid, n_hdr: int) -> list[str]:
    # .value, not .text: strip a raised footnote marker out of the label the way
    # cell values already do (protocol12 'Alcohol breathalyzer' + marker 'f',
    # not 'breathalyzerf'). The marker stays in the row's footnote_markers; this
    # removes the identical double-count we already fixed on value_verbatim.
    return [" ".join(pg.cells[r][c].value for c in pg.stub_cols).strip()
            for r in range(n_hdr, pg.n_rows)]


#: Title vocabulary per kind. Advisory only -- `unknown` is always allowed and
#: is a better answer than a confident wrong label (DECISIONS row 9).
_KIND_VOCAB = [
    ("pk", r"(pharmacokinetic|pk|blood collection|sampling)"),
    ("substudy", r"(sub-?study|companion|ancillary)"),
    ("extension", r"(extension|long-?term follow)"),
    ("main", r"(schedule of (activities|assessments|events|measures)|"
             r"time and events|overview of study assessments|study flow chart|"
             r"schedule of study procedures)"),
]


def classify_kind(title: str, columns: list[dict]) -> str:
    """Minimal advisory kind heuristic: title vocabulary + timepoint columns.

    A table only earns a schedule kind if it actually has timepoint columns; a
    title alone is not enough. Anything unrecognised stays `unknown`.
    """
    has_timepoints = sum(1 for c in columns if c.get("role") == "study_day") >= 2
    t = (title or "").lower()
    for kind, pat in _KIND_VOCAB:
        if re.search(pat, t):
            if kind == "main" and not has_timepoints:
                return "unknown"
            return kind
    return "main" if has_timepoints and re.search(r"schedule|assessment|visit", t) else "unknown"


def assemble_table(pagegrids: list[PageGrid], fn_pages_text: list[tuple[int, str]],
                   pages: list[int], title: str) -> dict:
    """Dispatch: same column count -> row-continuation; differing -> column merge."""
    if len({pg.n_cols for pg in pagegrids}) > 1:
        return _assemble_column_continuation(pagegrids, fn_pages_text, pages, title)
    return _assemble_row_continuation(pagegrids, fn_pages_text, pages, title)


def _assemble_row_continuation(pagegrids: list[PageGrid], fn_pages_text: list[tuple[int, str]],
                   pages: list[int], title: str) -> dict:
    """Row-continuation stack: header from first page, body from all pages."""
    head = pagegrids[0]
    n_hdr = _find_header_rows(head)
    columns = build_columns(head, n_hdr)
    stub = head.stub_cols
    n_cols = head.n_cols
    _defined = _defined_marker_keys(fn_pages_text)   # for equal-size promotion

    rows, cells = [], []
    deferred_pages: list[int] = []
    current_category = None          # row_id of the section the current rows fall under
    rid = 0
    for pg_i, pg in enumerate(pagegrids):
        sizes = [ch.get("size") for row in pg.cells for c in row for ch in c.chars
                 if ch.get("size")]
        median_size = (sorted(sizes)[len(sizes) // 2] if sizes else 10.0)
        pg_hdr_n = _find_header_rows(pg)
        divider_cols = set(detect_divider_columns(pg, pg_hdr_n))
        divider_rows = set(detect_divider_rows(pg, pg_hdr_n))
        # equal-size raised markers, promoted only when document-defined
        promote_equal_size_markers(pg, _defined, pg_hdr_n)
        if pg.n_cols != n_cols:
            # column-wise continuation (protocol1 p53=10 cols, p54=9): a proper
            # guarded merge onto the shared row axis is pending. Do not stack it
            # as if it were row-continuation -- that mismatches columns. Defer
            # and flag instead of crashing or corrupting.
            deferred_pages.append(pg.page)
            continue
        start = _find_header_rows(pg)                # skip each page's header
        # A continuation page has a header only if it REPEATS one; a header row
        # never carries cell marks. So on pages after the first, never skip past
        # the first marked body row -- NCT03348956 p21 has no repeated header and
        # no timepoint vocabulary, so _find_header_rows falls to its default 1 and
        # would eat the real first assessment row ('Toronto ...', body X X X).
        # min() is a no-op on the five (protocol9 p27/p28, protocol15 p53/p54 all
        # have their first marked row at or beyond the computed header end).
        if pg_i > 0:
            marked = next((r for r in range(pg.n_rows)
                           if any(is_mark_token(pg.cells[r][c].text.strip())
                                  for c in range(pg.n_cols) if c not in stub)),
                          pg.n_rows)
            start = min(start, marked)
        for r in range(start, pg.n_rows):
            rowcells = pg.cells[r]
            label = " ".join(rowcells[c].value for c in stub).strip()  # marker-stripped (see _row_labels)
            if not label and not any(rowcells[c].text.strip() or rowcells[c].shaded
                                     for c in range(n_cols) if c not in stub):
                continue                              # wholly empty row
            # Rule C-prime: a ruled band may hold two real rows (protocol5 p50
            # Saline). Split only under (a)+(b)+(c); grey zone stays merged with
            # a structured possible_split for the reviewer.
            split = evaluate_split(pg, r, stub, median_size)
            if split and split[0] == "split":
                for part in split[1]:
                    row_id = f"r{rid}"
                    rows.append({"id": row_id, "label_verbatim": part["label"],
                                 "role": "assessment",
                                 "parent_id": current_category,
                                 "level": 1 if current_category else 0,
                                 "footnote_markers": [],
                                 "sup_markers": [], "page": pg.page,
                                 "possible_split": None, "split_from_band": True})
                    for c, txt in part["marks"]:
                        gc = rowcells[c]
                        cells.append({"row_id": row_id, "col_id": f"c{c}",
                                      "value_verbatim": txt.strip(),
                                      "shaded": gc.shaded, "colspan": 1, "rowspan": 1,
                                      "footnote_markers": [],
                                      "sup_markers": list(gc.sup_markers),
                                      "page": pg.page,
                                      "bbox": [round(x, 1) for x in gc.bbox],
                                      "evidence": (["text_layer"] if txt.strip() else [])
                                                  + (["graphics_fill"] if gc.shaded else []),
                                      "authored_by": "geometry",
                                      "ambiguous": False, "ambiguity_reason": None})
                    rid += 1
                continue

            if not _body_has_content(rowcells, stub, n_cols, divider_cols):
                role = classify_empty_band(label)
                if role == "label_continuation" and rows:
                    # merge overflow line into the previous row's label
                    rows[-1]["label_verbatim"] = (
                        rows[-1]["label_verbatim"] + " " + label.strip()
                    ).strip()
                    continue
                # a body-empty row sitting in a full-width stub-covering band is a
                # SECTION header (protocol12/15 Screening/Safety/Efficacy). Zebra
                # rows also band the stub but have body content, so they never
                # reach here. Only promote when the band signal agrees; otherwise
                # keep the classify_empty_band verdict (':' category / metadata).
                if r in pg.banded_rows and role != "category_header":
                    role = "category_header"
            else:
                role = "assessment"
            row_id = f"r{rid}"
            row_sup = [m for c in stub for m in rowcells[c].sup_markers]
            if r in divider_rows:
                role = "divider"
            # row hierarchy: assessment rows fall under the current category until
            # the next category row. Categories/dividers/metadata sit at top level.
            if role == "category_header":
                current_category = row_id
                parent_id, level = None, 0
            elif role == "assessment" and current_category:
                parent_id, level = current_category, 1
            else:
                parent_id, level = None, 0
            grey = ({"stub_lines": [{"label": p["label"], "marks": p["marks"]}
                                    for p in split[1]]}
                    if split and split[0] == "grey" else None)
            rows.append({"id": row_id, "label_verbatim": label,
                         "role": role, "parent_id": parent_id, "level": level,
                         "footnote_markers": [],
                         "sup_markers": row_sup, "page": pg.page,
                         "possible_split": grey})
            for c in range(n_cols):
                if c in stub or c in divider_cols:
                    continue
                gc = rowcells[c]
                val = gc.value.strip()          # superscript markers removed
                # keep a cell whose only content was a superscript marker: its
                # value is now empty but the marker still needs a binding target
                if not val and not gc.shaded and not gc.sup_markers:
                    continue
                ev = []
                if val:
                    ev.append("text_layer")
                if gc.shaded:
                    ev.append("graphics_fill")
                cells.append({"row_id": row_id, "col_id": f"c{c}",
                              "value_verbatim": val, "shaded": gc.shaded,
                              "colspan": gc.colspan, "rowspan": 1, "footnote_markers": [],
                              "sup_markers": list(gc.sup_markers),
                              "page": pg.page, "bbox": [round(x, 1) for x in gc.bbox],
                              "evidence": ev, "authored_by": "geometry",
                              "ambiguous": False, "ambiguity_reason": None})
            rid += 1

    # rejoin cells a band boundary split before anything reads the row axis
    _merge_shaded_rowspan(rows, cells)

    used_markers = collect_used_markers(cells, rows, columns)
    # legend definitions ("X = Performed at this visit.") are keyed by a printed
    # VALUE, so they are matched against the values this table actually contains
    used_values = {c["value_verbatim"] for c in cells if c.get("value_verbatim")}
    footnotes = build_footnotes(fn_pages_text, used_markers, used_values)
    bind_markers(rows, cells, columns, footnotes)
    warnings = []
    if deferred_pages:
        warnings.append({"kind": "column_continuation_unmerged",
                         "detail": f"pages {deferred_pages} share the row labels but "
                                   f"have a different column count; guarded column "
                                   f"merge pending -- their columns are not yet in "
                                   f"this table"})
    return {"title_verbatim": title, "kind": classify_kind(title, columns),
            "source_pages": pages,
            "continuation_of": None, "extraction_confidence": 1.0,
            "strategy": "explicit-lines", "columns": columns, "rows": rows,
            "cells": cells, "footnotes": footnotes, "warnings": warnings}


def _assemble_column_continuation(pagegrids, fn_pages_text, pages, title) -> dict:
    """Guarded column merge (ARCHITECTURE §3): pages share the row labels but
    carry different visit columns. Union the columns onto one row axis when the
    row-label sequences match >=95%; otherwise fall back to the first page plus
    a continuation_of link and a warning.

    protocol1: p53 = Activity + visits 1-8, p54 = Activity + visits 9-13/ET/RT,
    28/29 labels identical -> one table, columns 1-13/ET/RT on a shared row axis,
    per-cell page provenance kept.
    """
    head = pagegrids[0]
    n_hdr = _find_header_rows(head)
    stub = head.stub_cols
    warnings = []

    head_labels = _row_labels(head, n_hdr)

    # columns: everything from the head page, ids c0..c{n-1}
    columns = build_columns(head, n_hdr)
    col_id_of = {c: f"c{c}" for c in range(head.n_cols)}
    next_col = head.n_cols

    # rows keyed by label (from the head); cells from the head first
    rows, cells = [], []
    row_id_by_label = {}
    for ri, label in enumerate(head_labels):
        r = n_hdr + ri
        rowcells = head.cells[r]
        row_id = f"r{ri}"
        row_id_by_label[label] = row_id
        rows.append({"id": row_id, "label_verbatim": label, "role": "assessment",
                     "parent_id": None, "level": 0, "footnote_markers": [],
                     "sup_markers": [m for c in stub for m in head.cells[r][c].sup_markers],
                     "page": head.page, "possible_split": None})
        for c in range(head.n_cols):
            if c in stub:
                continue
            gc = rowcells[c]
            if not gc.text.strip() and not gc.shaded:
                continue
            cells.append(_cell(row_id, col_id_of[c], gc, head.page))

    # each continuation page contributes its DATA columns + cells, matched by label
    for pg in pagegrids[1:]:
        pg_hdr = _find_header_rows(pg)
        pg_labels = _row_labels(pg, pg_hdr)
        n = min(len(head_labels), len(pg_labels))
        match = sum(1 for a, b in zip(head_labels, pg_labels) if a and a == b)
        if n == 0 or match / n < 0.95:
            warnings.append({"kind": "column_continuation_rejected", "page": pg.page,
                             "detail": f"row-label match {match}/{n} < 95%; page {pg.page} "
                                       f"kept separate"})
            continue
        data_start = _leading_label_cols(pg, pg_hdr)
        appended = {}
        # same stacked-header mapping as build_columns: visit number labels,
        # study day/week as a distinct axis (protocol1 p54: visits 9-13/ET/RT,
        # weeks 12/16/20/24/26).
        pg_tp = _timepoint_rows(pg, pg_hdr)
        pg_day = pg_tp[-1] if pg_tp else pg_hdr - 1
        pg_label = pg_tp[0] if len(pg_tp) >= 2 else pg_day
        pg_two = len(pg_tp) >= 2
        for c in range(data_start, pg.n_cols):
            cid = f"c{next_col}"; next_col += 1
            appended[c] = cid
            label = pg.cells[pg_label][c].text
            role, _win = _column_role_and_window(pg.cells[pg_day][c].text)
            if pg_two and role == "unknown":          # ET/RT: role from visit label
                role = _column_role_and_window(label)[0]
            col = {"id": cid, "index": next_col - 1, "label_verbatim": label,
                   "role": role, "colspan": 1, "footnote_markers": [], "page": pg.page}
            if pg_two and role in ("study_day", "visit") and pg.cells[pg_day][c].text.strip():
                col["study_day_verbatim"] = pg.cells[pg_day][c].text
            columns.append(col)
        for ri, label in enumerate(pg_labels):
            row_id = row_id_by_label.get(label)
            if row_id is None:
                continue
            r = pg_hdr + ri
            for c, cid in appended.items():
                gc = pg.cells[r][c]
                if not gc.text.strip() and not gc.shaded:
                    continue
                cells.append(_cell(row_id, cid, gc, pg.page))

    used_markers = collect_used_markers(cells, rows, columns)
    # legend definitions ("X = Performed at this visit.") are keyed by a printed
    # VALUE, so they are matched against the values this table actually contains
    used_values = {c["value_verbatim"] for c in cells if c.get("value_verbatim")}
    footnotes = build_footnotes(fn_pages_text, used_markers, used_values)
    bind_markers(rows, cells, columns, footnotes)
    return {"title_verbatim": title, "kind": classify_kind(title, columns),
            "source_pages": pages,
            "continuation_of": None, "extraction_confidence": 1.0,
            "strategy": "explicit-lines", "columns": columns, "rows": rows,
            "cells": cells, "footnotes": footnotes, "warnings": warnings}


def _cell(row_id, col_id, gc, page) -> dict:
    val = gc.value.strip()          # superscript markers removed
    ev = (["text_layer"] if val else []) + (["graphics_fill"] if gc.shaded else [])
    return {"row_id": row_id, "col_id": col_id, "value_verbatim": val,
            "shaded": gc.shaded, "colspan": gc.colspan, "rowspan": 1,
            "footnote_markers": [], "sup_markers": list(gc.sup_markers),
            "page": page, "bbox": [round(x, 1) for x in gc.bbox], "evidence": ev,
            "authored_by": "geometry", "ambiguous": False, "ambiguity_reason": None}
