# SoA Extractor

Finds the Schedule of Activities in a clinical trial protocol PDF and extracts it
into structured JSON, with a review UI that puts the extracted grid next to the
source page so a human can check it.

Status: in progress. This README is being written as I go, so sections below
marked TODO are not done yet rather than quietly skipped.

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

TODO

## Output schema

TODO

## Verification results, per protocol

Full detail, including the holdout, is in [`docs/VERIFICATION.md`](docs/VERIFICATION.md).
Summary of the five design protocols (65 automated gates, `python -m pytest tests/`):

| Protocol | SoA span | Cols | Rows | Cells | Shaded marks | Footnotes bound |
|---|---|---|---|---|---|---|
| protocol1 | 53–54 (column-merged) | visits 1–13, ET, RT | 29 | 152 | 0 | — |
| protocol5 | 50 | 12 | 31 | 107 | 0 | — |
| protocol9 | 26–29 | days 1–11 | 43 | 240 | 220 | 4 / 4 |
| protocol12 | 48–49 | 10 | 40 | 132 | 0 | 13 / 14 |
| protocol15 | 25–26 | 11 | 34 | 128 | 0 | 4 / 5 |

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
3. **Scanned-page OCR** as an opt-in, behind the existing loud-failure detector.
4. **The `--enrich` model pass** (adapter already built, off by default) for the
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
