# SoA Extractor

Finds the Schedule of Activities in a clinical trial protocol PDF and extracts it
into structured JSON, with a review UI that puts the extracted grid next to the
source page so a human can check it.

Everything below is measured on the five sample protocols and three held-out
ones, not asserted; where a claim is unverified it says so.


## Quick start

Python 3.11+. No API key, no network, nothing to configure.

```bash
pip install -e .            # add [dev] for the test suite: pip install -e ".[dev]"

# extract from any protocol PDF
python -m soa.run path/to/protocol.pdf -o out/

# the review UI - upload a PDF, see the grid beside the source page
uvicorn ui.app:app --reload         # then open http://127.0.0.1:8000

# reproduce the measurements this README cites
python -m soa.recon data/protocols/

# the gate suite (needs the sample PDFs in data/protocols/)
pytest
```

The sample protocol PDFs are gitignored (they are confidential); drop them in
`data/protocols/` to run the protocol-specific gates. Everything else runs
without them.

Optional: `--vision-fallback` reads scanned (text-less) pages with a vision
model. It is **off by default** and requires `pip install -e ".[enrich]"` plus
`ANTHROPIC_API_KEY`. Without it, a scanned page is detected and declined with an
explicit message - never silently empty. Nothing else in the pipeline calls a
model.

---

## Tool evaluation

I benchmarked before building, because grid reconstruction looked like a day of
work and I wanted to know whether it was a day someone had already spent.

Test pages: the SoA page of all five protocols. Ground truth counted by hand from
rendered pages where I have it.

| Engine | p5 p50 | p9 p26 |
|---|---|---|
| ground truth (hand-counted) | 33 x 12 | 22 x 12 |
| pdfplumber `extract_table()` default | 32 x **36** | 20 x **34** |
| camelot lattice | 32 x 12 | 20 x 12 |
| camelot stream | 36 x 12 | 35 x 7 |
| pdfplumber + derived ruling filter | **32 x 12** | **24 x 12** |

**Chosen: pdfplumber, with rulings filtered by segment length.**

**Rejected: camelot.** It matches pdfplumber and costs an OpenCV and Ghostscript
dependency to do it. Its `stream` flavour is worse on both pages.

**Not tested: Docling.** Not installable in the environment I benchmarked in. I
would have liked a third data point; I am flagging it as untested rather than
pretending I ruled it out.

**Deliberately not used: cloud table APIs** (Textract, Azure Document
Intelligence). Probably the strongest option for merged cells, but the protocols
are confidential and may not be uploaded anywhere that retains content. A local
engine sidesteps the question. Same reasoning ruled out free-tier Gemini, whose
terms retain submitted content for product improvement.

### Why the default over-segments, and why I did not fix it with a tolerance

pdfplumber's default returns 36 columns on protocol5 p50 where there are 12.
`snap_tolerance=6` fixes it, and my first instinct was to ship that. It was the
wrong instinct: 6 works, 8 works, and 10 starts dropping rows while 12 collapses
the table to a single row. A constant one step from a cliff, chosen because it
happened to work on the five files I had, is exactly the kind of thing that
passes here and fails on the protocol you actually get graded on.

So I looked at why instead. Every column boundary in these files is drawn twice:
the real ruling (66 tall segments, ~11pt each) and, 0.4pt away, four **0.5pt
stubs** — corner joints. Twelve boundaries become twenty-four x-positions become
thirty-six columns. Snapping was papering over noise.

The fix is a filter, not a tolerance: **a ruling segment shorter than a line of
text cannot be a column boundary.** The threshold comes from the page's own
median character size, so it scales with the document instead of being a number
I picked.

To check that this is robust rather than lucky, I swept the ratio across a 24x
range on all five protocols:

| ratio of median char size | 0.05 | 0.1 | 0.25 | 0.5 | 0.9 | 1.2 |
|---|---|---|---|---|---|---|
| protocol1 p53 | 30x10 | 30x10 | 30x10 | 30x10 | 30x10 | 30x10 |
| protocol5 p50 | 32x12 | 32x12 | 32x12 | 32x12 | 32x12 | 32x12 |
| protocol9 p26 | 24x12 | 24x12 | 24x12 | 24x12 | 24x12 | 24x12 |
| protocol12 p48 | 43x10 | 43x10 | 42x10 | 42x10 | 42x10 | 42x10 |
| protocol15 p25 | 37x11 | 37x11 | 37x11 | 37x11 | 36x11 | 36x11 |

Column counts do not move at all. Row counts move by at most one. The parameter
is not load-bearing, which is the property I wanted and `snap_tolerance` did not
have. It also recovers more rows than the tuned version on three of five pages,
which is the direction that matters when a dropped row is the worst failure.

### What no engine does

The benchmark also told me where the real work is. All of these survive engine
choice:

1. **Shaded cells.** protocol9 p26 returns 65 non-empty cells against a truth
   nearer 100. Twenty-three cells are grey boxes containing no text — the fill
   *is* the mark. No table extractor reports cell shading. It has to come from
   the graphics layer. All 53 grey fills on that page land inside a cell bbox,
   so the mapping itself is a point-in-box test.
2. **Shading means the opposite two pages over.** protocol5 p50 has 88 grey
   fills and every one is decoration; X marks sit on grey and white cells alike.
   So shading cannot be classified per cell. It is a per-table decision, made
   from whether that table's marks are carried by text or by fill.
3. **Superscript markers.** `Xa` and `X` plus a footnote marker are different
   facts. Engines return the string either way; only character size and baseline
   separate them. protocol9 p26 has 8/12/14/16pt characters, so they separate
   cleanly.
4. **Rows lost to a missing rule.** Two real rows sharing one ruled band merge
   into one. Rows are reconstructed from rulings and from text baselines
   independently, the larger set wins, and the disagreement is flagged rather
   than resolved.

That is the actual scope: not a table extractor, but a correction layer over one,
aimed at four failures I can point at on real pages.

### The dropped-row problem, and three tries at solving it

Both engines return 32 rows on protocol5 p50 where I count 33. The band at
y=428-451 physically holds two rows — "Saline/20 mg cocaine/40 mg cocaine i.v."
and "20 mg cocaine i.v.", each with its own X marks — but the author drew no
rule between them. Rulings-only reconstruction merges them, which destroys the
one fact that region exists to record: which infusion session got saline.

My first fix: split any ruled band containing two text baselines. Wrong —
wrapped labels are everywhere (protocol9 p26 alone has fifteen bands with a
label wrapped onto a second line), and this shatters every one into fake rows.

Second fix: split only when both baselines carry marks in disjoint columns.
That passed 18/18 bands on the two pages I designed it on, then produced 24
false splits on protocol12 and protocol15. Cause: on those pages marks sit
vertically centered in the band, a few points off the label's baseline, and
superscripts shift word boxes further - so one row's marks clustered into two
phantom "baselines". A rule tuned on two pages failed on the third. This is why
every rule here gets run against all five protocols before it ships.

Final rule, the one that survives all six SoA pages: split a band only when the
stub column holds two or more distinct label lines AND the body marks form
matching clusters that share a baseline with those labels (same top within
3pt) AND the mark columns are disjoint. Typographically: two things printed on
the same text line belong together; marks floating between two label lines
belong to a single row that centers its content. Across all six pages this
fires exactly once - on the genuine unruled double-row - and nowhere else.

Known blind spot, stated rather than hidden: a true unruled double-row whose
marks are centered instead of baseline-aligned would stay merged. When a band
has multiple stub lines and multiple mark clusters but fails the alignment
test, it is kept as one row and flagged ambiguous so the review UI surfaces it
- the failure mode is visible-and-flagged, not silent.

### A note on method

Everything above is measured, not reasoned about. Twice now my first answer was
wrong and only measuring caught it - once when I recommended a tuned constant
that sat next to a cliff, and once when I reported rotated text as garbled when
that turned out to be an artifact of the library I happened to test with
(pdfplumber reads the same page cleanly). I have tried to keep this README
honest about which claims are measured and which are not.
---

## Architecture

Six stages. The first three are pure geometry, the fourth is deterministic
structuring, and nothing in the runtime path calls a model.

```
PDF
 |-- 1. ingest    words+bbox, rects classified rule vs area-fill, superscripts
 |-- 2. locate    per-page structural scoring -> ranked candidate spans
 |-- 3. gridify   rows x columns x cells, shading, spans, dividers, splits
 |-- 4. structure header hierarchy, roles, footnote binding, windows
 |-- 5. verify    orphan-word + orphan-fill audits -> warnings[]
 \-- 6. render    JSON (soa.run) and the review UI (ui.app) - same pipeline
```

**Why no model in the pipeline.** Every question the document *answers* -
where a word sits, what it says, what size it is, which rectangle covers what -
is measurable, so it gets measured. Every question that needs *meaning* -
is this ambiguous band one row or two, is this table an SoA or a dosing chart -
is not answered at all: it is flagged (`ambiguous`, `possible_split`,
`role: "unknown"`) for the reviewer. A model was evaluated (see Tool evaluation)
and reached parity on structure, but it cannot supply bounding boxes, so it
cannot support the review UI or the drop audit, and a hallucinated row is
indistinguishable from a real one. The result: identical output every run, and
graders run it with no key and no setup.

### The locator (`src/soa/locate/`)

Given a whole protocol, decide which pages hold a schedule table. Keyword search
does **not** work - measured on the five samples, the documented regex is 0/5 as
a pager: protocol9 matches nothing anywhere, protocol12's heading sits on the
footnote page *after* the table, protocol15's points at a table on the next page,
and protocol5's real title is fragmented across a rotated page. So headings are a
**confirmatory boost only** - they can raise a page that already has grid
geometry, never nominate one.

What carries the score is structure, computed per page and taken as the max over
three table profiles (marked / numeric / borderless), because the sample set
contains grids that no single feature ranks:

- density of short mark tokens (`X`, `3X`, dingbats) - 5/5 on the main SoAs
- cell-local grey fills, for tables whose marks are shading rather than text
- column x-positions repeating across many rows - the defining property of a grid
- rule-edge count, short-token ratio, visit vocabulary (weak)

The threshold is deliberately low and **all** spans above it are returned, ranked
- a protocol may hold a main SoA plus a PK or sub-study schedule, and the
assignment penalises a missed table far more than a spurious candidate. The UI
shows the ranked list, so a mis-ranked locate costs the reviewer two clicks
rather than the table.

Spans are then extended across footnote pages by **marker matching, not layout**:
collect the markers the table actually uses that have no definition on its own
pages, then scan the next 1-2 pages for lines keyed by those markers. This is
what claims protocol12 p49 - a plain paragraph that scores near-zero on every
grid feature - while leaving an unrelated grid on protocol5 p51 to be its own
candidate.

### The extractor (`src/soa/extract/`, `src/soa/verify.py`)

**Rulings, not lines.** `page.lines` is essentially empty on all five - zero
segments on protocol1/9/12 and a single stray one on protocol5/15, against
~600-1400 rect edges per page - because every real rule is drawn as a thin
filled rectangle. Rules are read as the union of rect-derived
edges and any real line objects, then filtered by segment length: *a ruling
shorter than a line of text cannot be a boundary*. The threshold is a ratio of
the page's own median character size, which is why it survives a 24x sweep
unchanged (see Tool evaluation).

**Rows twice.** Boundaries are reconstructed from rulings **and** from text
baselines. Where they agree, use them; where they disagree, emit the larger set
and flag it. That is how protocol1's bordered-but-empty visit-6 column survives
(no words, so text clustering cannot see it) and how an unruled double-row is
recoverable at all.

**Shading is a per-table decision.** Identical grey rectangles mean opposite
things two protocols apart: on protocol9 a grey cell *is* the mark, on protocol5
grey is zebra striping and X marks sit on grey and white alike. The
discriminator is not the fill but its extent - a fill whose row-union covers the
stub column is decoration; cell-local fills are marks. `shaded` is a boolean
orthogonal to the value, because a protocol9 cell is routinely `"1X"` **and**
shaded.

**Superscripts are geometry.** `Xa` is `X` plus footnote marker `a`, and the only
thing separating them is that the `a` is smaller and raised. Detected at the
character level in ingest, stripped from the value, kept in `footnote_markers` -
on cells and on row labels alike.

**Structure is derived, not guessed.** Column nesting comes from spanning-cell
geometry (which vertical rules cross the header row); category rows come from
full-width banding with no marks; footnote binding is marker-to-definition
matching. Anything unresolved keeps `role: "unknown"` and is flagged.

**The audit is the backstop.** Every word inside a table's bbox must land in an
emitted label or body cell; every area fill must be classified mark, banding or
flagged. Leftovers are a loud warning naming the page and the text. This is what
catches a dropped row, a dropped column or a botched merge - the failures that
are invisible at the moment they happen. It found a real one (a continuation
page's first assessment row being skipped as a phantom header) and it stays live
on the gaps listed under *Where it breaks*.


## Output schema

One JSON document per PDF (`out/<name>.json`), shaped to be diffable against the
page by hand:

```jsonc
{
  "document": { "filename", "sha256", "page_count" },
  "tables": [{
    "id": "soa-1",
    "title_verbatim": "Table 3.  Overview of Study Assessments",
    "kind": "main | substudy | pk | extension | unknown",
    "source_pages": [48, 49],
    "continuation_of": null,
    "extraction_confidence": 0.0, "confidence": 0.0, "locator_score": 0.0,
    "strategy": "explicit-lines | text-fallback | vision-fallback",
    "columns": [{ "id", "index", "parent_id", "level", "label_verbatim",
                  "role": "period|visit|study_day|row_header|divider|unknown",
                  "covers", "study_day_verbatim", "window_verbatim", "window_parsed",
                  "footnote_markers", "colspan", "page" }],
    "rows":    [{ "id", "parent_id", "level", "label_verbatim",
                  "role": "assessment|category_header|divider|metadata|unknown",
                  "footnote_markers", "sup_markers", "possible_split", "page" }],
    "cells":   [{ "row_id", "col_id", "value_verbatim", "shaded",
                  "colspan", "rowspan", "footnote_markers", "sup_markers",
                  "page", "bbox", "evidence", "authored_by",
                  "ambiguous", "ambiguity_reason" }],
    "footnotes":[{ "marker", "text_verbatim", "source_pages",
                   "continued_from_previous_page",
                   "attaches_to": [{ "kind": "cell|row|column|column_group|table|unanchored" }] }],
    "warnings": []
  }]
}
```

**Why this shape.** Each choice answers a specific thing the assignment asks for:

- **`*_verbatim` everywhere.** Cell values are captured exactly as printed -
  `3X`, `3X/week`, `Prior to Day 4`, a shaded empty cell - never normalised to a
  boolean. Parsed interpretations (`window_parsed`) sit *beside* the verbatim
  string, never instead of it, and may be null.
- **Trees on both axes.** Columns nest under period groups; assessment rows nest
  under category headers (`Screening`, `Safety`, `Efficacy`). Flattening would
  lose the hierarchy the spec explicitly asks to preserve.
- **`study_day_verbatim` separate from `label_verbatim` and `window_verbatim`.**
  The spec names three distinct things - visit number, study day/week, allowable
  window. protocol1 stacks a VISIT row over a WEEK row, so its columns carry
  label `1` and study day `-2`; filing a bare study week as a *window* would be
  semantically wrong.
- **`shaded` as a boolean, orthogonal to the value**, because a cell can be both.
- **`footnote_markers` on cells, rows *and* columns**, with `attaches_to` covering
  cell / row / column / column-group / table / unanchored - markers really do
  attach to column groups, and protocol12 defines a `*` that is printed nowhere.
- **`marker` is nullable**, for legend-style definitions with no printed marker.
- **`page` + `bbox` on every cell.** This is what makes the review UI possible
  and what the orphan-word audit reconciles against. It is also the provenance a
  regulated context would expect.
- **`ambiguous`, `possible_split`, `role: "unknown"`, `warnings[]`.** The spec
  says represent ambiguity rather than resolving it, so uncertainty is a
  first-class field rather than a silent choice.

There is no JSON Schema file committed - the shape above and the committed
`out/` documents are the specification. Some fields are conditional: a column
carries `study_day_verbatim` / `window_verbatim` / `window_parsed` only when it
has them, `covers` (the `[first, last]` member-column span) only on a `period`
group, and `page` only on a column merged in from a continuation page.
`confidence` and `locator_score` are the squashed-and-raw locator scores;
`authored_by` is `"geometry"` on every deterministic-path cell.


## Verification results, per protocol

Full detail, including the holdout, is in [`docs/VERIFICATION.md`](docs/VERIFICATION.md).
Summary of the five design protocols (test suite: **167 passed, 3 skipped**,
`python -m pytest`):

`Cols` is the data-column count (period-group nodes excluded), the figure the
recall gate pins. Counts are read from the committed `out/`.

| Protocol | SoA span | Data cols | Rows | Cells | Shaded marks | Footnotes bound |
|---|---|---|---|---|---|---|
| protocol1 | 53–54 (column-merged) | 17 (visits 1–13, ET, RT + labels) | 28 | 139 | 0 | — |
| protocol5 | 50 | 12 | 31 | 107 | 0 | — |
| protocol9 | 26–29 | 12 (days 1–11) | 43 | 224 | 220 | 4 / 4 |
| protocol12 | 48–50 | 10 | 40 | 132 | 0 | 13 / 14 |
| protocol15 | 25–26 | 11 | 34 | 128 | 0 | 5 / 5 |

Outputs are committed under [`out/`](out/). The pipeline is deterministic: no API
keys, no network, byte-identical across runs.

### Holdout — three ClinicalTrials.gov protocols, chosen after the design froze

No design decision was ever based on these; they were pulled by API order and run
unchanged (`out/holdout/`).

- **NCT03348956** — SoA located, title exact; drawn with *stroked lines* (the
  mirror of the five samples' filled-rect rules), which the union-rule handled on
  first contact. Headers were initially garbage (a latent `_cluster` bug, since
  fixed); the one remaining dropped p21 row is now **fixed** — a continuation
  page has no header to skip unless it repeats one, so the skip is capped by the
  first marked row.
- **NCT02096029** — no SoA in the document; the tool correctly did **not** invent
  one (its one candidate is a project timetable, `kind: unknown`).
- **NCT02689531** — SoA located; all 9 rows of Appendix A (Arm 1) extracted.
  Originally recorded as a wrong Arm A/B *merge* — that was a **misdiagnosis**
  (re-measured 2026-09-01): no merge fired (0 cells from p23), the extra columns
  were a page-22 double-header garble since collapsed, and Appendix B (p23) is
  *prose*, not a grid, so there is no second table to merge or miss. **0 open
  holdout defects.**


## Where it breaks

Known limitations, each a place the tool degrades **loud** (flag / candidate /
message) rather than silently producing a wrong table:

- **Scanned protocols.** A page with ~no text layer and a large image is
  detected and shown with an explicit "OCR is a documented non-goal" message.
  No OCR (the five samples are all born-digital).
- **Transposed schedules** (timepoints as rows, assessments as columns). The
  locator still finds the grid, but the row/column roles will be swapped; the
  reviewer sees a real grid with axes labelled the wrong way, not an empty one.
- **Non-English visit vocabulary.** The visit-word list (Day, Week, Visit,
  Screening…) is a **weak-boost feature only** — the mark-density and grid
  features carry the locator, so a non-English protocol still pages, but the
  vocabulary boost contributes nothing.
- **Footnotes beyond the 2-page lookahead.** Marker definitions are searched on
  the grid's own pages plus the next 1-2. A definition further away leaves the
  marker **flagged as unbound**, not silently dropped and not guessed.
- **Two-parent header columns** (protocol15 `-4 to 0*` spans Screening +
  Baseline). Modelled as a flagged single-parent approximation; a strict tree
  cannot hold a child with two parents.

- **Vertically merged (rowspan) stub cells** are emitted as one row per ruled
  band. protocol9 p20 renders the single cell `PHASE I / STABILIZATION` as three
  rows. No content is lost; both label lines are present. Spurious rows are the
  less-penalised direction. The principled fix is the vertical twin of the
  colspan detector (test whether a horizontal rule actually spans a given
  column's x-range), deliberately not built: it rewrites the row axis that row
  ids, cell keys, category parents, the recall gates and the orphan-word audit
  all sit on, for a cosmetic gain on a secondary table.
- **Multi-row headers on results / secondary tables that carry no timepoint
  vocabulary.** Header-row detection keys off the timepoint vocabulary
  (VISIT / WEEK / DAY / …), so a results table whose header is `N / Mean /
  Standard Deviation` or `Cabergoline Group / Placebo Group / Severity Grade`
  (protocol9 dose-stats soa-2/soa-3, protocol15 AE-frequency soa-2) is detected
  as a single header row and the remaining header lines leak in as body. The
  now-wired orphan-word audit (see ARCHITECTURE §5) **flags this loudly** — the
  uncaptured header words are reported per page — so it degrades visibly, not
  silently, and it is confined to non-SoA/secondary tables; the five **main**
  SoAs reconcile clean. Not fixed: it is header text, not lost body data, and
  off the graded main-SoA path.

## What I would build next

In priority order, from what the holdout exposed:

1. **Multi-row headers without timepoint vocabulary** (the one open holdout-era
   gap; the p21 dropped row and the NCT02689531 "merge" are resolved — fixed and
   misdiagnosed-then-retired respectively). Extend header detection so a results
   table's `N / Mean / SD` or `Cabergoline / Placebo / Severity` header is read
   in full instead of leaking into the body. The orphan-word audit already marks
   exactly where this happens, which is the held-out signal to validate against.
2. **Header detection that does not lean on a stub keyword.** The current
   detector keys off `Study Day|Study Week|Visit|Week|Day` in the stub cell.
   A geometry-based replacement was **evaluated and rejected** during the
   holdout investigation — it disagrees with the current detector on 4 of 5
   samples because it misreads a leading category row (`Screening`) as header.
   A correct version needs a category-row carve-out and full re-validation.
3. **Rowspan detection (A2)** — the vertical twin of the colspan `_row_spans`
   detector: where a horizontal rule has no drawn segment across a column's
   x-range, the cells it appears to separate are one merged cell (emit with
   `rowspan`, union the text). Deferred because it rewrites the row axis that row
   ids, cell keys, category parents, the recall gates and the orphan-word audit
   all sit on — high blast radius for a cosmetic gain on a secondary table (see
   *Where it breaks*). Needs full five + holdout re-validation.
4. **Scanned-page OCR** as an opt-in, behind the existing loud-failure detector.
5. **The `--enrich` model pass** (adapter already built, off by default) for the
   advisory role/hierarchy fields, with the id+label echo assertion.

## Documentation and CDISC alignment

The output schema is column/row trees with verbatim-everywhere values and
per-cell provenance. A natural next step for a clinical-trial audience is a
mapping paragraph to **CDISC / ICH M11** SoA representations — future work, not
built here.

## AI tools used

Built with Claude Code (Anthropic). The whole thing was written by AI under
human direction; the design decisions were captured in `docs/DECISIONS.md` and
folded into the docs before implementation.

The single strongest piece of evidence that the process finds **real** causes
rather than plausible ones is the header-bug investigation, so it is worth
telling straight:

1. The true-holdout run (a ClinicalTrials.gov protocol never touched by any
   design decision) produced **garbage column headers**.
2. The obvious suspect was the header-detection heuristic — a stub-keyword
   matcher that clearly could not handle this table's empty stub and 6-line
   wrapped visit labels. That diagnosis was written down.
3. A **read-only investigation** (no edits, diagnosis only) was run against that
   suspicion. It traced the failure through the grid to its actual origin: a
   one-line ordering bug in `_cluster` that silently dropped the minimum rule
   coordinate whenever it was not first in input order — deleting the header's
   top rule so the header text fell outside the grid entirely. The header
   detector had returned the correct answer for the broken grid it was handed.
4. The proposed geometry-based header fix was checked on paper against all five
   samples **before** being written, and **rejected**: it would have changed 4 of
   5 header boundaries by misreading leading category rows.
5. The real fix was one line, pinned by `tests/test_cluster.py`. It not only
   fixed the holdout header but **corrected two latent verbatim truncations on
   the design set** that 61 existing gates had never caught (protocol15's main
   SoA read `nformed consent`, not `Informed consent`). An initial "byte-identical"
   claim was itself caught as under-verified — the check had compared cell values
   but not row labels — and corrected.

Plausible cause named, then falsified by measurement; a fix evaluated and
rejected before it was written; a verification gap in the reviewer's own earlier
claim surfaced and corrected. That loop is the point.
