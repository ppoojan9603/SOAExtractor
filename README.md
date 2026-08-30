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

TODO

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

TODO: fill in the measured per-protocol failure modes after the all-five run.

## What I would build next

TODO

## AI tools used

TODO
