# SoA Extractor

Finds the Schedule of Activities in a clinical trial protocol PDF and pulls it
into structured JSON. There's a review UI that puts the extracted grid next to
the source page, so you can check my output against the document instead of
taking my word for it.

I've tried to keep this README honest about which claims I measured and which I
didn't. Where something is unverified, or where I know it's broken, it says so.

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

# the gate suite
pytest
```

The five sample protocols are committed in `data/protocols/`, so the
protocol-specific gates run out of the box. The three holdout PDFs are not in the
repo; `out/holdout/` has their output.

There's an optional `--vision-fallback` that reads scanned pages with a vision
model. It's off by default and needs `pip install -e ".[enrich]"` plus an
`ANTHROPIC_API_KEY`. Without it a scanned page gets detected and declined with a
message saying so. Nothing else in the pipeline calls a model.

---

## Which tools I tried

I benchmarked before I built anything, because reconstructing a grid from
scratch looked like a full day of work and I wanted to know whether it was a day
someone had already spent for me.

I ran each engine on the SoA page of all five protocols. Ground truth is my own
hand count off the rendered pages.

| Engine | p5 p50 | p9 p26 |
|---|---|---|
| ground truth (hand-counted) | 33 x 12 | 22 x 12 |
| pdfplumber `extract_table()` default | 32 x **36** | 20 x **34** |
| camelot lattice | 32 x 12 | 20 x 12 |
| camelot stream | 36 x 12 | 35 x 7 |
| pdfplumber + my ruling filter | **32 x 12** | **24 x 12** |

I went with pdfplumber and my own ruling filter.

I rejected camelot. It matches pdfplumber on both pages and charges me an
OpenCV and a Ghostscript dependency for the privilege. Its `stream` flavour is
worse on both.

I didn't test Docling. It wouldn't install in the environment I was
benchmarking in and I ran out of patience for it. I'd have liked a third data
point, so I'm flagging it as untested rather than pretending I ruled it out.

I ruled out the cloud table APIs (Textract, Azure Document Intelligence) on
purpose. They're probably the strongest option going for merged cells, but you
told me these protocols can't be uploaded anywhere that retains content, and I
didn't want to spend the week arguing with myself about whether a particular
vendor's retention policy counted. A local engine makes the question go away.
Same reasoning killed free-tier Gemini, whose terms keep submitted content for
product improvement.

### Why the default over-segments, and why I didn't just set a tolerance

pdfplumber's default gives me 36 columns on protocol5 p50 where there are 12.
`snap_tolerance=6` fixes it and my first instinct was to ship that.

That was a bad instinct. 6 works, 8 works, 10 starts dropping rows, and 12
collapses the whole table into one row. That's a constant sitting one step from
a cliff, picked because it happened to work on the five files I was handed. It
would pass here and fail on whatever protocol you actually grade me against.

So I went and looked at why instead. Every column boundary in these files is
drawn twice: the real ruling (66 tall segments, about 11pt each) and, 0.4pt
away, four 0.5pt stubs that are corner joints. Twelve boundaries become
twenty-four x-positions become thirty-six columns. Snapping was just papering
over noise.

The fix turned out to be a filter, not a tolerance. A ruling segment shorter
than a line of text can't be a column boundary. The threshold comes from the
page's own median character size, so it scales with the document rather than
being a number I picked and hoped about.

To check that wasn't luck, I swept the ratio across a 24x range on all five:

| ratio of median char size | 0.05 | 0.1 | 0.25 | 0.5 | 0.9 | 1.2 |
|---|---|---|---|---|---|---|
| protocol1 p53 | 30x10 | 30x10 | 30x10 | 30x10 | 30x10 | 30x10 |
| protocol5 p50 | 32x12 | 32x12 | 32x12 | 32x12 | 32x12 | 32x12 |
| protocol9 p26 | 24x12 | 24x12 | 24x12 | 24x12 | 24x12 | 24x12 |
| protocol12 p48 | 43x10 | 43x10 | 42x10 | 42x10 | 42x10 | 42x10 |
| protocol15 p25 | 37x11 | 37x11 | 37x11 | 37x11 | 36x11 | 36x11 |

Column counts don't move at all. Rows move by at most one. That's the property
I wanted and the one `snap_tolerance` didn't have. It also recovers more rows
than the tuned version on three of five pages, which is the direction I care
about given a dropped row is the worst thing I can do.

### What none of the engines do

The benchmark was more useful for telling me where the real work was. These four
problems survive whichever engine I pick:

Shaded cells. protocol9 p26 gives back 65 non-empty cells against a truth nearer
100. Twenty-three of those cells are grey boxes with no text in them at all: the
fill *is* the mark. No table extractor reports cell shading, so it has to come
out of the graphics layer. All 53 grey fills on that page land inside a cell
bbox, so once you have the fills the mapping is just a point-in-box test.

Shading means the opposite two protocols over. protocol5 p50 has 88 grey fills
and every single one is decoration; X marks sit on grey and white cells alike.
So I can't classify shading per cell. It has to be a per-table decision, made
from whether that table's marks are carried by text or by fill.

Superscript markers. `Xa` and `X` with a footnote marker are different facts.
Every engine hands back the same string either way. Only character size and
baseline separate them, and protocol9 p26 has 8/12/14/16pt characters, so they
do separate cleanly.

Rows lost to a missing rule. Two real rows sharing one ruled band merge into
one. I reconstruct rows from rulings and from text baselines independently, take
the larger set, and flag the disagreement instead of resolving it.

So what I actually built isn't a table extractor. It's a correction layer on top
of one, aimed at four failures I can point at on real pages.

### The dropped row, and three tries at fixing it

Both engines return 32 rows on protocol5 p50 where I count 33. The band at
y=428-451 physically holds two rows, "Saline/20 mg cocaine/40 mg cocaine i.v."
and "20 mg cocaine i.v.", each with its own X marks, but the author never drew a
rule between them. Rulings-only reconstruction merges them, and that destroys the
one fact the region exists to record: which infusion session got the saline.

First attempt: split any ruled band holding two text baselines. Wrong. Wrapped
labels are everywhere (protocol9 p26 alone has fifteen bands with a label
wrapped to a second line) and this shatters every one of them into fake rows.

Second attempt: split only when both baselines carry marks in disjoint columns.
This passed 18 of 18 bands on the two pages I designed it against, and then
produced 24 false splits on protocol12 and protocol15. The cause was that on
those pages the marks sit vertically centred in the band, a few points off the
label's baseline, and superscripts push word boxes further still, so one row's
marks clustered into two phantom baselines. A rule tuned on two pages died on
the third. This is why everything here now gets run against all five before it
ships.

What finally held: split a band only when the stub column holds two or more
distinct label lines, AND the body marks form matching clusters sharing a
baseline with those labels (same top within 3pt), AND the mark columns are
disjoint. In plain terms, two things printed on the same text line belong
together, and marks floating between two label lines belong to a single row
that centres its content. Across all six SoA pages it fires exactly once, on the
genuine unruled double-row, and nowhere else.

The blind spot, which I'd rather state than bury: a real unruled double-row
whose marks are centred instead of baseline-aligned stays merged. When a band
has multiple stub lines and multiple mark clusters but fails the alignment test,
I keep it as one row and flag it so the UI surfaces it. Visible and wrong beats
invisible and wrong.

### On method

Everything above is measured. I'm making a point of that because twice my first
answer was wrong and only measuring caught it: once when I was about to ship a
tuned constant sitting next to a cliff, and once when I recorded rotated text as
garbled and it turned out to be an artifact of the library I happened to test
with. pdfplumber reads that same page fine.

---

## Architecture

Six stages. The first three are pure geometry, the fourth does deterministic
structuring, and nothing on the runtime path calls a model.

```
PDF
 |-- 1. ingest    words+bbox, rects classified rule vs area-fill, superscripts
 |-- 2. locate    per-page structural scoring -> ranked candidate spans
 |-- 3. gridify   rows x columns x cells, shading, spans, dividers, splits
 |-- 4. structure header hierarchy, roles, footnote binding, windows
 |-- 5. verify    orphan-word + orphan-fill audits -> warnings[]
 \-- 6. render    JSON (soa.run) and the review UI (ui.app) - same pipeline
```

I want to explain the no-model choice, because it's the decision I'd expect you
to push back on.

Every question the document actually answers (where a word sits, what it says,
what size it is, which rectangle covers what) is measurable, so I measure it.
Every question that needs meaning (is this ambiguous band one row or two, is
this table an SoA or a dosing chart) I don't answer at all. I flag it
(`ambiguous`, `possible_split`, `role: "unknown"`) and leave it for a reviewer.

I did evaluate a model pass and it reached parity on structure. What killed it
was that a model can't give me bounding boxes, and without boxes I have no
review UI and no drop audit. A hallucinated row is also indistinguishable from a
real one, which is exactly the failure I'm most afraid of here. The upside is
that the output is byte-identical every run and you can run it with no key and
no setup.

### The locator

Given a whole protocol, work out which pages hold a schedule table.

Keyword search does not work, and I have the numbers. Measured on the five
samples, the obvious heading regex is 0 for 5 as a pager. protocol9 matches
nothing anywhere in the document. protocol12's heading sits on the footnote page
*after* the table. protocol15's points at a table on the following page. And
protocol5's real title is fragmented across a rotated page. So headings are a
confirmatory boost only. They can raise a page that already has grid geometry;
they can never nominate one.

What carries the score is structure, computed per page and taken as the max over
three table profiles (marked, numeric, borderless), because the sample set has
grids that no single feature ranks:

- density of short mark tokens (`X`, `3X`, dingbats), which hits 5 of 5 on the main SoAs
- cell-local grey fills, for tables whose marks are shading rather than text
- column x-positions repeating across many rows, which is the defining property of a grid
- rule-edge count, short-token ratio, and visit vocabulary as weak signals

The threshold is deliberately low and I return every span above it, ranked. A
protocol can hold a main SoA plus a PK or sub-study schedule, and you said a
missed table is penalised far harder than a spurious one. The UI shows the
ranked list, so a mis-ranked locate costs a reviewer two clicks instead of the
table.

Spans get extended onto footnote pages by marker matching rather than layout: I
collect the markers the table actually uses that have no definition on its own
pages, then scan the next page or two for lines keyed by those markers. That's
what claims protocol12 p49, a plain paragraph that scores near zero on every
grid feature, while leaving an unrelated grid on protocol5 p51 to be its own
candidate.

### The extractor

The first surprise was that `page.lines` is basically empty on all five files.
Zero segments on protocol1, 9 and 12, and a single stray one on protocol5 and 15,
against 600 to 1400 rect edges per page. Every real rule in these documents is
drawn as a thin filled rectangle, not a line object. So I read rules as the union
of rect-derived edges and any genuine lines, then filter by segment length the
way I described above.

I build row boundaries twice, once from rulings and once from text baselines.
Where the two agree I use them. Where they disagree I emit the larger set and
flag the disagreement. That's how protocol1's bordered-but-empty visit-6 column
survives, since it has no words in it and text clustering can't see it at all,
and it's the only reason an unruled double-row is recoverable.

Shading has to be decided per table rather than per cell. Identical grey
rectangles mean opposite things two protocols apart, and the thing that
separates them isn't the fill, it's the extent: a fill whose row-union covers
the stub column is decoration, and cell-local fills are marks. I keep `shaded`
as a boolean sitting alongside the value instead of replacing it, because a
protocol9 cell is routinely `"1X"` and shaded at the same time.

Superscripts are pure geometry. `Xa` is `X` plus footnote marker `a`, and the
only thing telling them apart is that the `a` is smaller and sits higher. I catch
it at the character level during ingest, strip it out of the value, and keep it
in `footnote_markers`. Same treatment on cells and on row labels.

The rest of the structure is derived rather than guessed at. Column nesting comes
from spanning-cell geometry, which is to say which vertical rules cross the
header row. Category rows come from full-width banding with no marks in it.
Footnote binding is marker-to-definition matching. Anything I can't resolve keeps
`role: "unknown"` and gets flagged instead of filled in.

Then there's the audit, which is the part I'd point at first if you only looked
at one thing. Every word inside a table's bbox has to land in an emitted label or
body cell, and every area fill has to end up classified as a mark, as banding, or
flagged. Whatever's left over becomes a loud warning naming the page and the
text. It's the only thing in here that can catch a dropped row or column or a
botched merge, because those failures are completely invisible at the moment they
happen. It has caught real ones, and it's still firing on the gaps I list below.

## Output schema

One JSON document per PDF, in `out/<name>.json`, shaped so you can diff it
against the page by hand.

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

Why this shape. Each thing in it is answering something you asked for.

`*_verbatim` on everything. Cell values come out exactly as printed: `3X`,
`3X/week`, `Prior to Day 4`, a shaded empty cell. Nothing is normalised to a
boolean. Where I do parse something (`window_parsed`) it sits beside the verbatim
string, never instead of it, and it's allowed to be null.

Trees on both axes. Columns nest under period groups, assessment rows nest under
category headers like Screening or Safety. Flattening either would lose the
hierarchy you explicitly asked to keep.

`study_day_verbatim` kept separate from `label_verbatim` and `window_verbatim`.
You named three distinct things: visit number, study day or week, and allowable
window. protocol1 stacks a VISIT row over a WEEK row, so its columns carry label
`1` and study day `-2`. Filing a bare study week as a *window* would be flatly
wrong.

`shaded` as a boolean orthogonal to the value, because a cell can be both.

`footnote_markers` on cells, rows and columns, with `attaches_to` covering cell,
row, column, column group, table and unanchored. Markers really do attach to
column groups, and protocol12 defines a `*` that's printed nowhere in the table.

`marker` is nullable, for legend-style definitions that have no printed marker at
all.

`page` and `bbox` on every cell. This is what makes the review UI possible and
what the orphan-word audit reconciles against. It's also the provenance I'd
expect a regulated context to want.

`ambiguous`, `possible_split`, `role: "unknown"` and `warnings[]`. You said
represent the ambiguity instead of resolving it, so uncertainty is a field rather
than a silent choice.

There's no JSON Schema file committed. The shape above and the documents in
`out/` are the spec. Some fields are conditional: a column only carries
`study_day_verbatim` / `window_verbatim` / `window_parsed` when it has them,
`covers` only appears on a `period` group, and `page` only on a column merged in
from a continuation page.

## What I got right and what I got wrong, per protocol

Full detail including the holdout is in [`docs/VERIFICATION.md`](docs/VERIFICATION.md).
The suite is 187 passed, 3 skipped.

`Cols` is the data-column count with period-group nodes excluded, which is the
figure my recall gate pins. All counts are read straight out of the committed
`out/`.

| Protocol | SoA span | Data cols | Rows | Cells | Shaded marks | Footnotes bound |
|---|---|---|---|---|---|---|
| protocol1 | 53-54 (column-merged) | 17 (visits 1-13, ET, RT + labels) | 28 | 139 | 0 | 4 / 4 |
| protocol5 | 50 | 12 | 31 | 107 | 0 | see below |
| protocol9 | 26-29 | 12 (days 1-11) | 40 | 197 | 193 | 4 / 4 |
| protocol12 | 48-50 | 10 | 40 | 132 | 0 | 13 / 14 |
| protocol15 | 25-26 | 11 | 34 | 128 | 0 | 5 / 5 |

protocol9's 40 rows and 193 shaded marks are *after* rejoining three cells that
a ruled band boundary had split. The earlier figures of 43 and 220 were counting
each split cell twice. protocol1's footnotes only bind now that I recognise
definitions keyed by value plus marker (`Xa = ...`) as well as marker-less
legends; before that fix protocol1 reported zero footnotes against four on the
page.

**protocol5 is the interesting one.** Its SoA uses markers `a` through `f` and
`*` through `****` on cells, and the definitions for them do not exist anywhere
in the document. I checked by hand. The tool doesn't invent them and doesn't
quietly drop them either: it emits ten `marker_used_undefined` warnings naming
each one. That's the behaviour I want, and it's the closest thing I have to a
question for a clinical SME, so I'll ask it here. Is protocol5's SoA missing its
footnote block, or are those markers defined somewhere in the protocol body that
I should be searching?

### What I checked by hand, and what I didn't

I went through protocol9's schedule and the top half of protocol1's SoA cell by
cell against the PDF. That review is where the real defects came from:
small-caps row labels being read as superscript markers and stripped, so
`DETOXIFICATION` came out mangled; rowspan cells on protocol9 p28 split into two
rows with the shaded marks duplicated into both; protocol1's footnotes missing
entirely. All three are fixed.

I did not hand-check protocol1's lower half, protocol5, protocol12 or
protocol15. Those rest on the automated gates and the orphan audits, which are
good at catching drops but say nothing about whether a mark landed in the right
column. I'm not going to claim those four are verified.

Worth saying plainly: every defect above was found by looking at a page, not by
a test going red. The suite was green the whole time. That's a fact about the
suite, not just about the bugs.

### Holdout: three ClinicalTrials.gov protocols

I pulled these after the design was frozen and ran them unchanged. No decision in
this repo was ever based on them. Output is in `out/holdout/`.

**NCT03348956.** SoA located, title exact. This one is drawn with stroked lines,
the exact mirror of the five samples' filled-rect rules, and the union rule
handled it on first contact. The headers came out as garbage initially, which
traced back to a latent bug I'll describe below. One dropped row on p21 is also
fixed now: a continuation page has no header to skip unless it repeats one, so
the skip is capped by the first marked row.

**NCT02096029.** There is no SoA in this document, and the tool correctly did
not invent one. Its single candidate is a project timetable, marked
`kind: unknown`.

**NCT02689531.** SoA located, all 9 rows of Appendix A extracted. I originally
wrote this up as a wrong Arm A/B merge. That was a misdiagnosis on my part and I
re-measured it: no merge ever fired, the extra columns were a p22 double-header
garble that's since collapsed, and Appendix B on p23 is prose, not a grid, so
there was no second table to merge or miss in the first place. Zero open holdout
defects.

## Where it breaks

Everything in this list degrades loudly, with a flag or a candidate or a
message, rather than quietly handing you a wrong table. Two of them are things I
know are wrong and didn't get to.

The first is footnote continuation across a page break. The code is there but it
has never once run. `continued_from_previous_page` is false on all 20 tables
across all eight protocols I've put through this, because no footnote block in my
corpus actually spills a page. You called this out specifically as the failure
that's easy to miss, so I'd rather say the path is unexercised than let a passing
test suite imply I've proven something I haven't.

The second is protocol5's PK sub-schedule, which drops its footnotes. Page 51
defines two markers under the table, `a` for `S = serum, P = plasma` and `b` for
`D = day`, and my output for that table has zero. The orphan-word audit flags 7
dropped words on it, which is how I found it in the first place. It's a
sub-schedule rather than a main SoA, but a miss is a miss.

The rest are limits I chose rather than bugs I missed.

Scanned protocols get detected and refused. A page with essentially no text layer
and a large image comes back with a message saying OCR is a documented non-goal.
There's no OCR in here at all; all five samples are born-digital.

Transposed schedules, meaning timepoints as rows and assessments as columns, will
locate fine and then come out with the row and column roles swapped. You'd get a
real grid with its axes labelled backwards, not an empty one.

A non-English protocol still pages, because mark density and grid geometry carry
the locator and the visit word list is only a weak boost. The vocabulary just
stops contributing anything.

I only search for footnote definitions on the grid's own pages plus the next one
or two. Anything defined further out leaves its marker flagged as unbound, rather
than dropped or guessed at.

protocol15 has a column, `-4 to 0*`, that spans both Screening and Baseline. I
model it as a flagged single-parent approximation, because a strict tree can't
hold a child with two parents and I'd rather approximate visibly than restructure
the schema around one column.

Vertically merged cells only work in the shaded case. I rejoin a cell spanning
two ruled bands when the signature is unambiguous, meaning the upper row's cells
are all empty with at least one shaded and the row below re-marks exactly the
same columns. That covers protocol9 p28. The unshaded form still splits, so
protocol9 p20 renders the single cell `PHASE I / STABILIZATION` as three rows. No
content is lost and spurious rows are the less-penalised direction, but it's
wrong and I know it's wrong. The proper fix is the vertical twin of my colspan
detector. I didn't build it because it rewrites the row axis that row ids, cell
keys, category parents, the recall gates and the orphan audit all sit on, and
that needs its own validation pass I didn't have time for.

Last one: multi-row headers on secondary tables that carry no timepoint
vocabulary. Header detection keys off VISIT / WEEK / DAY and friends, so a
results table headed `N / Mean / Standard Deviation` reads as a single header row
and the rest of the header leaks into the body. The orphan-word audit flags it.
It's confined to secondary tables and all five main SoAs reconcile clean, so I
left it.

## What I'd build next with two more weeks

Roughly in the order I'd actually do them.

1. Manufacture a footnote continuation case and validate that path properly.
   It's the one graded requirement where I have code and no evidence, which
   bothers me more than the things that are plainly broken. I'd split a footnote
   block across a synthetic page break first, then go find a real protocol that
   does it.
2. Fix protocol5's PK footnotes, and more generally get footnote capture on
   sub-schedules up to where it is on main SoAs. The orphan audit already points
   at exactly where to look.
3. Multi-row headers on tables with no timepoint vocabulary. Same story: the
   audit marks precisely where this happens, so I have a held-out signal to
   validate against instead of guessing.
4. Header detection that doesn't lean on a stub keyword. I tried a
   geometry-based replacement during the holdout work and rejected it, because
   it disagrees with the current detector on 4 of 5 samples by misreading a
   leading `Screening` category row as header. Doing it right needs a
   category-row carve-out and a full re-validation.
5. General rowspan detection, the vertical twin of the colspan detector. Where a
   horizontal rule has no drawn segment across a column's x-range, the cells it
   looks like it separates are actually one merged cell.
6. Opt-in OCR for scanned pages, sitting behind the loud-failure detector that's
   already there.

## AI tools I used, and where they got in the way

I built this with Claude Code. Almost all the code was written by the model
under my direction, and I want to be specific about what that actually looked
like, because "I used AI" on its own tells you nothing.

What worked was a split. I decided what to build and what counted as evidence,
the model wrote it, and then I went back through looking for where it had lied to
me. That last part was not optional.

So, where it got in the way.

It kept proposing fixes tuned on the data in front of it. The `snap_tolerance`
constant was one. The two-baseline row splitter was worse: it passed 18 of 18
bands on the two pages it was designed against and then produced 24 false splits
the moment I ran it on the other three. Both times the model was confident. The
only thing that caught either was a rule I made early on and had to keep
enforcing, that no rule ships until it's run against all five protocols.

It reported findings it hadn't actually verified. It told me rotated text came
out garbled, which turned out to be an artifact of the library it happened to
test with rather than a property of the document. It wrote a regex into the
findings doc that wasn't the regex it had run. It claimed byte-identical output
after a fix when it had only compared cell values and not row labels. Each of
those would have gone into this README as a fact if I hadn't pushed back.

It wanted to write documentation instead of fixing things. Repeatedly. Left
alone it would produce a beautifully documented broken tool.

And a green test suite made it overconfident in a way I had to work against.
Every real defect in this project was found by opening the PDF and looking at
the page. Not one was found by a test failing.

Where it genuinely helped: it's fast at the read-only investigation loop. The
best example is the header bug. The holdout run produced garbage column headers,
and the obvious suspect was the header-detection heuristic, which plainly
couldn't handle that table's empty stub and 6-line wrapped labels. I had the
model investigate without changing anything, and it traced the failure past the
obvious suspect to a one-line ordering bug in `_cluster` that silently dropped
the minimum rule coordinate whenever it wasn't first in input order. That deleted
the header's top rule, so the header text fell outside the grid entirely. The
header detector had been returning the correct answer for the broken grid it was
handed.

The fix was one line. It fixed the holdout headers and also corrected two latent
truncations on the design set that 61 existing gates had never caught, where
protocol15's SoA had been reading `nformed consent` instead of `Informed
consent`. The geometry-based header fix I'd been about to write got checked on
paper against all five first, and rejected.

Name the plausible cause, then go try to kill it. That loop is the only reason I
trust any of the numbers in this README.

## A note on CDISC

The natural next step for a clinical audience is a mapping from this schema to
CDISC / ICH M11 SoA representations. I haven't built it and I'm not going to
pretend I know that standard well enough to have designed toward it.
