# Architecture

Read `docs/FINDINGS.md` first. Every choice below is a response to something
measured there, cited by protocol and page, not a preference.

## Guiding principle: the runtime pipeline is deterministic. No model in the loop.

Cell text comes from PDF geometry — and so does everything else the tool
outputs. Header nesting is spanning-cell geometry, footnote binding is string
matching, roles are transparent heuristics. **There is no model call in the
default path.**

This started as "the model never writes a cell value" and got stronger under
review: once the work was itemised, *nothing* the model had been assigned
actually needed a model. Nesting is geometric (a header cell's bbox covers its
children's x-range), binding is marker matching, and roles are advisory in our
schema — an unknown role stays `role: "unknown"` and is flagged, which is a
better answer than a confident guess.

What this buys, and why it is the right call for this deliverable:

- A grader runs the tool with **zero API keys** and gets identical output every
  run — deterministic and reproducible.
- Confidentiality is airtight: **the protocols never leave the machine.** AI
  built this tool; AI is not *in* this tool.
- "Be faithful, not clever" stops being prompt discipline and becomes a
  property of the architecture.

An optional `--enrich` pass (OFF by default) can add model-suggested roles and
links; it is constrained to ids/links/roles, asserts id+label echo, and may
never write a value. See §4.

## Pipeline

```
PDF
 └─ 1. ingest    → per-page: extract_table + cell bboxes, fills→cells, char sizes, scan check
 └─ 2. locate    → scored page candidates → table spans (marker-driven footnote lookahead)
 └─ 3. gridify   → explicit-line grid, C′ split rule, shaded-mark classification
 └─ 4. structure → DETERMINISTIC: hierarchy (geometry), binding (matching), roles (heuristics)
 └─ 5. verify    → orphan-word + orphan-fill audits + external checks → warnings[]
 └─ 6. render    → JSON + side-by-side review UI
                   (optional: --enrich → LLM roles/links only, OFF by default)
```

### 1. Ingest (`src/soa/ingest.py`) — a thin wrapper, not a reimplementation

`pdfplumber` only, for both text and geometry (MIT; `chars`, `rects`, `lines`,
`edges`, `words`, `extract_table`, `find_tables`). `pypdfium2` for page
rasterisation (Apache/BSD). We avoid PyMuPDF deliberately: it is AGPL, an
awkward licence to hand an employer. Cloud extraction services are excluded on
confidentiality grounds (DECISIONS rows 1, 17). **[Layer 1]** the boring,
established choices.

**Ingest is deliberately thin.** `extract_table` with explicit lines is a solved
wheel; hand-rolling a grid reconstructor would be rebuilding it worse
(DECISIONS row 2). Ingest therefore does six small things:

1. `extract_table` with explicit line lists (see below) + `find_tables` for the
   per-cell bboxes.
2. **Fill-to-cell mapping** by point-in-box: every area-fill is assigned to the
   cell whose bbox contains its centre. Measured: all 53 fills on protocol9 p26
   land inside a cell bbox — no fill is homeless, which is what makes the
   orphan-fill audit (§5) a meaningful check rather than noise.
3. **Char sizes** carried through, for superscript/subscript detection (below).
4. **Scan detection** (DECISIONS row 15): a page with ~zero text characters and
   a large image object is flagged `scanned`. The pipeline then fails **loud** —
   the UI shows the rendered page and an explicit "scanned protocol; text-layer
   extraction does not apply; OCR is a documented non-goal" message. Our five
   are all born-digital (FINDINGS §1), but the unseen protocol may not be, and
   silently emitting an empty table is the worst possible grading outcome.
5. **Strategy chain** (DECISIONS row 16): enough rulings → explicit-lines
   strategy; sparse rulings → pdfplumber's text-alignment strategy, with
   `extraction_confidence` downgraded and the table flagged. The in-sample
   borderless case is protocol9 p38 (a PK sampling block).
6. Page rasterisation handle for the UI.

**Rule extraction: union the sources, derive the threshold (FINDINGS §8).**
These five protocols draw every rule as a thin *filled rect*, so a reader that
only looks at `page.lines` finds nothing. But an unseen protocol may use real
stroked lines, so rules are the **union of rect-derived edges and
`page.lines`** — never one or the other.

Survivors are filtered by a **derived** threshold: drop segments thinner than
**0.25 × the page's median character size**, then pass the rest to
`extract_table` as `explicit_vertical_lines` / `explicit_horizontal_lines`.
The threshold is derived rather than a fixed constant because it was measured
flat across a 24× ratio sweep on all five protocols, while pdfplumber's
`snap_tolerance` has a cliff (6 works, 10 drops rows, 12 collapses the grid) —
a knob with a cliff is a knob that will break on the unseen protocol
(DECISIONS row 3). Recovered grid dimensions: protocol1 30×10, protocol5 32×12,
protocol9 24×12, protocol12 42×10, protocol15 **36×11** (an earlier hand count
said 37; two independent methods — rule-cluster arithmetic and `extract_table` —
both give 36 once the stroked page-footer rule is scoped out).

**Every length constant here is char-size-relative** (B1): the ruling-thinness
cutoff (0.25 × median char size), the rule-merge tolerance (0.2 ×), and the
table-scope pad all scale with the page's type size rather than assuming a fixed
point value, so nothing is pinned to these five protocols' font size.

**Superscript / subscript markers are detected at char level** (DECISIONS row 6),
not by regex: a char whose size is smaller than its neighbours *and* whose
baseline is raised (or lowered) is emitted as a `footnote_marker` separate from
`value_verbatim`. Measured on protocol9 p26: char sizes are 8/12/14/16 pt and
separate cleanly. A regex cannot tell `Xa` (mark + marker) from a literal
two-character value, and the same mechanism handles subscripts such as
protocol15's `FEV₁`.

**Rotated pages need no special handling.** protocol5 (p50–51) and protocol9
(p26–29) are `/Rotate 90`, and pdfplumber reads them cleanly — the
`Tim e and Event s Schedul e` fragmentation was a `pypdf` artifact, not a
property of the PDF (FINDINGS §2, §6). There is no char→word reassembly
workstream. The `title_verbatim` test gate is **kept**, but its purpose is
restated: it proves the *engine choice* is sound, and it is a regression tripwire
if anyone swaps the engine.

Ingest output per page: `table_cells[]` (verbatim text + bbox), `fills[]`
(bbox + colour + owning cell), `words[]`, `chars[]` (with sizes), `rules[]`
(unioned, filtered), `rotation`, `scanned` flag, `strategy`, `page_image` handle.

### 2. Locator (`src/soa/locate/`) — no model call, no keyword as primary

Per-page feature vector, each feature normalised 0–1. The score is the **max
over three profiles**, not one weighted sum, because the sample set contains
marked grids, numeric grids, and borderless grids that no single feature ranks
(FINDINGS §7):

| Feature | Profile it serves | Evidence |
|---|---|---|
| generic short-token **and dingbat** density (not only `X`) | bordered-marked | `X` alone is 5/5 here (FINDINGS §3) but an unseen SoA may mark with ✓/●/▪ — score the shape of the token, not the letter |
| grey cell-local fill count | shaded-marked | protocol9 marks are grey fills (FINDINGS §4) |
| numeric-cell density in aligned columns | bordered-numeric | Blood Collections / dosing tables (FINDINGS §7) |
| repeated column x-positions across ≥5 rows | all | the defining property of a grid |
| rule count (h + v, from the unioned rect-edges + `page.lines`) | bordered | FINDINGS §8 |
| short-token ratio (tokens ≤ 3 chars) | all | grids are terse, prose is not |
| visit-vocabulary hits (Day, Week, Visit, Screening, Baseline, EOT, Follow-up) | weak boost |  |
| title/heading match on this page | **confirmatory boost only** | present on 5/5 near a grid, but decoys pages away — never a pager (FINDINGS §6) |

Threshold for **recall** (deliberately low — a false candidate is cheap, a
missed table is the most-penalised failure). Rank by SoA-likeness for
presentation, but return **all** spans above threshold. The title feature can
only raise a page that already has grid geometry; it can never nominate a page
on its own.

**Span assembly, then marker-driven footnote lookahead (FINDINGS §7).** After
thresholding, merge vertically-adjacent grid pages into a span. Then extend the
span across footnote pages by **marker matching, not layout**:

1. Collect the footnote markers actually used in the grid (`*`, `**`, `Xa`,
   superscript letters, …) that have no definition on the grid's own page.
2. Scan the next 1–2 pages for lines keyed by those markers (`Xa -`, `** `,
   `Notes on…`).
3. Attach a page to the span iff it defines ≥1 of the table's open markers.

This is what the old "title contains Continued / repeated header / footnote
block with no grid" heuristic could not do: it correctly claims protocol12 p49
(a plain paragraph that scores near-zero on every grid feature) and protocol5
p51-top (definitions sitting *above* an unrelated second table), while leaving
protocol5's `Schedule of Blood Collections` on p51 to be its own candidate span.

**Every candidate span above threshold is extracted, not only the main one**
(assignment: a protocol may carry a main schedule plus a sub-study, PK, or
extension schedule). Each runs through the same gridify → structure → verify
path and is `kind`-labelled (`main` / `substudy` / `pk` / `extension` /
`unknown`). protocol5's output therefore contains two tables — the
Time-and-Events SoA and the Blood Collections sub-schedule.

Column-wise continuation (protocol1 p53→54) is detected here and resolved in
gridify §3.

### 3. Gridify (`src/soa/extract/grid.py`) — no model

The grid itself comes from `extract_table` with the explicit lines from §1.
Gridify adds the four things a generic table extractor gets wrong on SoAs.

**1. Unruled double-rows: rule C′ (DECISIONS row 4).** protocol5 p50 has a
missing horizontal rule — two real rows (`Saline/20 mg cocaine/40 mg cocaine
i.v.` and `20 mg cocaine i.v.`, y=428–451) share one over-tall ruled band. Split
a band **only when all three hold**:

- (a) the stub column holds ≥2 distinct label lines, **and**
- (b) the body marks form clusters that share a baseline with those labels
  (cluster top within 3 pt of a label line, 1:1), **and**
- (c) the clusters' column sets are **disjoint**.

**Grey zone** — a band that meets (a) and has ≥2 mark clusters but fails (b) or
(c): **keep it merged** and emit a structured `possible_split` flag carrying
each stub line's label and its marks, so a reviewer can adjudicate in the UI.
Representing the ambiguity beats resolving it.

This rule is the product of measured iteration, and the history is kept because
it is the evidence:

| Version | Rule | Measured result |
|---|---|---|
| v1 | split on ≥2 text baselines | **shatters 15 wrapped labels on protocol9 alone** |
| v2 | + require disjoint column sets | **24 false splits** on protocol12/15 (centred marks, superscripts shift boxes) |
| v4 (C′) | (a) ∧ (b) ∧ (c), grey zone flagged | **fires exactly once across the six SoA pages** — the true Saline double-row |

Grey zone measured: 6 bands, all six verifiably single rows. **No model call in
row structure** — this is geometry and baselines, and a model here would be
guessing where the rule is deterministic.

**2. Shaded marks: the fill-union test on both axes (DECISIONS row 5).**
Group area-fills by row band. If a row's fill **union** covers the **stub
columns** (or ~the full table width) it is **banding = decoration**; discard it.
Apply the **same test on the column axis** to catch header-column emphasis. What
survives is cell-local → a **mark**.

The stub is found by **text density**, not "everything left of the first ruling"
(`src/soa/extract/stub.py`, B2): label columns are text-dense, mark/timepoint
columns are terse (`X`, `3X`), so the leading contiguous run of dense columns is
the stub. This supports a **multi-column stub** without assuming one — on the
five samples the stub is a single column, but the detector does not hard-code
that.

Measured, and this is why the test has to be contextual: protocol9 p26 has 50
fills, 23 on empty cells (marks) and 27 under `1X`; protocol5 p50 has 88 fills
whose row-unions span x=50–688 **including the stub** (zebra striping). *Per
fill, the geometry is identical — only row context separates a mark from a
stripe.* Ambiguous fills are flagged, never guessed.

`shaded` is a **boolean orthogonal to `value_verbatim`**, never a replacement:
a protocol9 cell is routinely `value_verbatim: "1X"` **and** `shaded: true`.

**3. Divider rows/columns.** A full-height column of single stacked letters
spelling a milestone (`R A N D O M I Z A T I O N`, protocol12 p48 / protocol15
p25) is emitted with `role: "divider"`, and its stray single-glyph runs are
excluded from row-band clustering so they cannot corrupt the row axis. A
mid-body bold header strip (`Cocaine Infusion Session #`, protocol5 p50) is
emitted as a row with `role: "divider"`.

**4. Column-wise page merge (DECISIONS row 8; FINDINGS §7, protocol1).** When
the locator marked two pages as a column-continuation, merge them into one table
**iff their row-label sequences match ≥95%** (protocol1's 28 labels repeat
verbatim). On a match, union the columns onto the shared row axis, keeping
per-cell and per-footnote `page` provenance. On no match, fall back to two
tables plus a `continuation_of` link and a warning — so the failure mode of the
merge is exactly "two linked tables", never a corrupted merge.

Every cell is emitted, including empty ones, with `page` + `bbox` provenance.
Spanning values (`Prior to Day 4`, protocol9 p26) keep their `colspan` and are
not distributed across the columns they cover.

### 4. Structure (`src/soa/extract/structure.py`) — deterministic, no model

Everything the model used to be asked for turned out to be computable. This
stage runs with zero API keys and produces identical output every run
(DECISIONS row 9).

**Header hierarchy = spanning-cell geometry.** A header cell is the parent of
the header cells beneath it whose x-ranges its own bbox covers. `find_tables`
already gives the cell bboxes, so nesting is containment arithmetic. This is
exactly how protocol12/15's period bands sit above their visit columns and how
protocol5 p50's `Baseline Infusions` covers days −2/−1.

**Footnote binding = marker matching** (per §2's lookahead). Markers extracted
at char level (§1) are matched against definition keys collected from the span's
footnote pages. Flexible marker forms are supported — letter, symbol, digit,
parenthesised. **Whatever does not match is flagged, never guessed.**
protocol12 is the hardest case (its definitions are keyed `Xa -` while the
in-table marker is a bare superscript `f`, and `*` is defined but printed
nowhere): bind what matches, flag the rest.

**Roles = transparent heuristics.** `period` / `visit` / `study_day` / `window`
/ `divider` / `category` are assigned by readable rules (a header row of bare
integers under a period band is `visit`; `± N days` is `window`; a stacked
single-letter column is `divider`). **An unrecognised header stays
`role: "unknown"` and is flagged** — advisory in our schema, so an honest
"unknown" costs nothing and a confident wrong guess costs a graded axis.

**Optional enrichment (`--enrich`, OFF by default).** When explicitly enabled,
one model call per table may *suggest* roles and parent/child links. It is
constrained to ids, links and roles; the returned cell ids must be exactly the
ids sent, and every id it links must echo back the `label_verbatim` we sent
(string-equal). Any drift is a hard error. **It may never write, reword, add or
remove a value.** Enrichment output is marked as model-authored in the UI and in
the JSON, so a reviewer always knows what geometry produced versus what a model
suggested.

### 5. Verify (`src/soa/verify.py`) — runs on every extraction, always

The checks are external invariants, not restatements of gridify's own
intermediates.
The old "row count == gridify's y-band count" and "cell count == rows × cols"
checks were circular (comparing gridify to itself, always green) and are
removed. Replaced by:

- **Orphan-word audit (primary drop detector).** Every word inside the table
  bbox must land in exactly one emitted cell. Leftover words are a loud warning
  — this is the one check that catches a dropped row, a dropped column, or a
  botched merge, because a dropped structure leaves its words homeless. ~20
  lines, and it is the backstop for the whole recall story.
- **Orphan-fill audit (DECISIONS row 11).** Every area-fill must end up
  explicitly classified as `mark`, `banding`, or `flagged` — none may be
  silently dropped. This is the shading counterpart to the word audit: it is
  what stops a mark from vanishing because the banding test over-fired.
  Measured basis: all 53 fills on protocol9 p26 map into a cell bbox, so an
  unclassified fill is a real defect, not noise.
- every column has ≥1 header cell (catches an unlabelled emitted column).
- every footnote marker used in a cell/label has a definition, and every
  definition is used — **bidirectional**, reported both ways (protocol9's
  `(01)`–`(33)` will surface here as used-but-undefined; that is correct, they
  are flagged not resolved — FINDINGS open question 1).
- footnote text does not end mid-sentence at a page boundary (continuation
  check; protocol5 p50→51, protocol12 p48→49).
- no table span ends on a page whose successor also scores above the locator
  threshold (missed-continuation check).
- `possible_split` grey-zone bands and every `ambiguous` flag from gridify are
  surfaced, never hidden.

Failures become `warnings[]` on the output. They never silently pass. A
verifier that reports all-clear on five messy 2001-era PDFs is not working.

## Output schema (`schema/soa.schema.json`)

```jsonc
{
  "document": { "filename", "sha256", "page_count" },
  "tables": [{
    "id": "soa-1",
    "title_verbatim": "Table 4. Schedule of Measures and Data Collection…",
    "kind": "main | substudy | pk | extension | unknown",
    "source_pages": [26, 27, 28, 29],
    "continuation_of": null,            // table id, when a merge fell back to link-only
    "extraction_confidence": 0.0,       // downgraded when the text-fallback path ran
    "strategy": "explicit-lines | text-fallback",   // which path produced this table
    "columns": [{                       // tree (or DAG — see note)
      "id": "c7", "parent_id": "c2", "level": 1,
      "label_verbatim": "4",
      "role": "period | visit | study_day | window | row_header | divider | unknown",
      "colspan": 1,
      "window_verbatim": "Day 15 ± 3 days",
      "window_parsed": { "day": 15, "minus": 3, "plus": 3 },  // advisory only, beside verbatim
      "footnote_markers": ["*"],        // headers carry markers too (protocol5 `-15* to -9`)
      "page": 26
    }],
    "rows": [{
      "id": "r12", "parent_id": "r9", "level": 1,
      "label_verbatim": "Weight (on admission & 0630-0800h ā breakfast)",
      "role": "assessment | category_header | divider | metadata | unknown",
      "footnote_markers": ["(13)"],     // captured verbatim; may be undefined-in-doc (flagged)
      "possible_split": null,           // grey-zone band: {stub_lines:[{label, marks[]}]}
      "page": 26
    }],
    "cells": [{
      "row_id": "r12", "col_id": "c7",
      "value_verbatim": "1X",           // never replaced by shading
      "shaded": true,                   // boolean, ORTHOGONAL to value_verbatim
      "colspan": 1, "rowspan": 1,
      "footnote_markers": ["*"],
      "page": 26, "bbox": [x0, y0, x1, y1],
      "evidence": ["text_layer", "graphics_fill"],  // may be both
      "authored_by": "geometry",        // or "model" when --enrich supplied it
      "ambiguous": false, "ambiguity_reason": null
    }],
    "footnotes": [{
      "marker": "**",                   // NULLABLE — a definition may exist with no printed marker
      "text_verbatim": "The physician may withhold a dose…",
      "source_pages": [29],
      "continued_from_previous_page": false,
      "attaches_to": [                  // list; a marker can attach to several targets
        { "kind": "cell",         "row_id": "r6", "col_id": "c7" },
        { "kind": "row",          "id": "r6" },
        { "kind": "column",       "id": "c7" },
        { "kind": "column_group", "id": "c2" },   // protocol5 `Number of Samples per Day`ᵇ
        { "kind": "table" },                      // legend-style (protocol1 `X = Performed…`)
        { "kind": "unanchored" }                  // defined but no marker printed (protocol12 `*`)
      ]
    }],
    "warnings": []
  }]
}
```

**Why this shape**, each tied to a measured structure:

- `*_verbatim` everywhere so the grader can diff against the page without
  arguing about normalisation. Parsed values live beside the verbatim string,
  never instead of it.
- `shaded` is a **boolean orthogonal to `value_verbatim`** because protocol9
  cells are shaded AND `1X` at once (FINDINGS §4). A single `mark_kind` enum
  could not express that and is gone.
- `columns[].footnote_markers` exists because markers attach to column headers
  and column groups, not only cells: protocol5 `-15* to -9`, protocol15
  `-4 to 0*`, protocol5 Appendix II `Number of Samples per Day`ᵇ (FINDINGS §7,
  and the schema `attaches_to.kind: column_group`).
- `footnote.marker` is **nullable** and `attaches_to.kind` includes
  `column_group` and `unanchored` because protocol12 p49 defines `*` that is
  printed nowhere, and protocol1's `X = Performed at this visit.` / `P = …`
  legend entries attach to the whole table, not a cell.
- `role: "divider"` on rows and columns because the `RANDOMIZATION` column
  (protocol12/15) and the `Cocaine Infusion Session #` strip (protocol5) are not
  timepoints or assessments and must not be read as such.
- Trees on both axes because flattening loses the hierarchy the assignment asks
  us to keep. **Column note [inferred]:** protocol15's `-4 to 0*` spans two
  parent groups (Screening + Baseline) — a DAG, not a tree. We model it as a
  single span node under a synthetic parent and emit a warning; a strict tree
  cannot represent a child with two parents, and we prefer a flagged
  approximation to a silent one.
- `extraction_confidence` + `strategy` because the text-fallback path
  (borderless tables, protocol9 p38) is genuinely less reliable than the
  explicit-lines path, and a consumer must be able to tell which one ran
  without reverse-engineering it.
- `possible_split` because rule C′'s grey zone keeps an ambiguous band **merged**
  and hands the reviewer the evidence (each stub line's label and its marks)
  rather than silently picking a split. Representing ambiguity, not resolving it.
- `role: "unknown"` is a first-class value on both axes. An unrecognised header
  is flagged, never guessed into a plausible-looking role.
- `authored_by` on cells so model-suggested content (only ever present under
  `--enrich`) is distinguishable from geometry at a glance, in the JSON as well
  as the UI.
- `page` + `bbox` on every cell because that is what makes the review UI
  possible — and the review UI is how verification stops being expensive.

## UI (`ui/`)

FastAPI + **one vanilla HTML page** (DECISIONS row 13). Streamlit fights custom
bbox overlays; React is build tooling for zero graded benefit — the assignment
says visual design is not graded.

Flow: **Upload a PDF** → run → **ranked candidate list** → pick one →
**side-by-side** extracted grid vs rendered page image.

- **The candidate list is a design decision, not a convenience.** The locator
  returns all spans above a low threshold, ranked; showing them as a clickable
  list makes a locator miss **recoverable by a human in two clicks instead of
  fatal**. Secondary schedules (protocol5 p51 Blood Collections, p29–30 Infusion)
  surface here as candidates — listed, not extracted.
- Hovering a cell highlights its bbox on the page image.
- Footnote panel showing each footnote with what it attaches to.
- Warnings banner; `possible_split` bands and `ambiguous` cells/rows are visually
  marked so the reviewer's eye goes to exactly the places the tool is unsure.
- **Scanned-page handling (DECISIONS row 15):** if ingest flags a page
  `scanned`, the UI shows the rendered page plus an explicit message — scanned
  protocol, text-layer extraction does not apply, OCR is a documented non-goal.
  Loud failure, never a silently empty grid.
- Under `--enrich` only, model-authored fields are visually distinct from
  geometry-authored ones.

"Upload" is a stated requirement of the assignment — no static-report shortcut.
The CLI shares the same pipeline to produce the committed `out/` JSONs, so the
UI and the batch outputs can never drift apart.

This is the deliverable *and* the verification harness. Building it early
(Day 2) is what makes checking five protocols by hand affordable.

## Provider adapter (`src/soa/providers/`) — optional enrichment only

**Demoted by the deterministic-runtime decision (DECISIONS rows 9, 10).** The
default pipeline makes no model call at all; this adapter exists solely for the
optional `--enrich` pass.

`base.Provider.complete(prompt, images, schema) -> dict`, selected by env var,
with `anthropic.py` implemented and `openai.py` / `gemini.py` as drop-ins behind
the same interface. When enrichment *is* used, use the **strongest available
model** — it would be ~10 calls across all five protocols, so cost is pennies
and quality wins.

The three-way benchmark is **designed-not-run** under the 3-day budget: the
README documents the design (same five protocols, axes scored, how to run it)
and states that one provider was wired live. Scoped to the optional pass, it is
no longer on the critical path for any graded output.

**Do not use free-tier Gemini.** Its terms retain submitted content for product
improvement; the protocols may not be uploaded anywhere retained for training.
Billing must be enabled. This belongs in the README — though note that with the
default path making no calls at all, **the protocols never leave the machine
unless a user explicitly opts into `--enrich`.**
