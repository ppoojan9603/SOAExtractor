# Verification

Two populations, kept strictly apart:

- **The five sample protocols** (`data/protocols/`) — every design decision in
  this repo was made against these. Results here are *not* evidence of
  generalisation.
- **The holdout** (`data/holdout/`) — three protocols pulled from
  ClinicalTrials.gov **after the design was frozen** (M7 tagged `v0.1.0-m7`).
  **No design decision has ever touched them.** They were selected by API order
  from a `COMPLETED` studies query, not by inspection, and the pipeline was run
  unchanged.

---

## M7.5 — Holdout results (the honest ones)

Selection: `clinicaltrials.gov/api/v2/studies?filter.overallStatus=COMPLETED`,
first three results carrying a posted protocol document. No suitability
screening. Run: `python -m soa.run data/holdout/<id>.pdf -o out/holdout`.

| Protocol | Pages | SoA present? | Located? | Verdict |
|---|---|---|---|---|
| NCT03348956 (Biomarkers in CIPN) | 31 | yes, pp. 20–21 | **yes** | rows + marks right; headers fixed (candidate D) and the dropped p21 row fixed (item 1) — clean |
| NCT02096029 (NIDA implementation trial) | 22 | **no SoA in document** | n/a | correctly did **not** invent one |
| NCT02689531 (CTTI HABP/VABP) | 32 | yes, p. 22 (p. 23 is *prose*, not a table) | yes | all 9 rows extracted; the "merge" was a **misdiagnosis** — see below |

> **Re-measured 2026-09-01** (after the _cluster fix, both marker fixes, the
> structuring batch and the stacked-header work). Two of the three verdicts
> below moved, and one was found to have been a **misdiagnosis**. Corrections are
> marked inline; the original text is kept so the record shows what changed and
> why. See "Re-measurement" at the end of this section.

### NCT03348956 — located, headers FIXED; dropped row now FIXED (was: one row still dropped)

What went right, and it is the load-bearing part:

- **The locator found it** and the title stitched exactly:
  `6.1 Schedule of Assessments`.
- **This protocol draws its rules as stroked lines** (`page.lines` = 64,
  `page.rects` = 0) — the mirror image of all five samples, which draw rules as
  filled rects. The union rule (FINDINGS §8, DECISIONS row 3) is the only reason
  the grid was found at all. That decision was made for exactly this
  hypothetical and it paid off on first contact with unseen data.
- All **9 body rows on p20 extracted with correct marks**, including the
  superscript footnote markers: `EPR Oximetry Reading` came back as
  `X1`, `X2`, `X2`, `X` with the markers detected at char level.

**The garbage-headers defect and its investigation (the important part).**
Initial output had empty/fragment column headers
(`['', '', 'at onset of CIPN symptoms)', 'chemotherapy)', …]`). My first
diagnosis blamed `_find_header_rows` (the stub-keyword header detector) and I
recorded that here. A read-only investigation **overturned that attribution**:

- The header's top rule *exists* in the raw geometry at y=473.9, and the vertical
  borders extend up to it. But the built grid's top rule was y=519.4, **below**
  the header text — so the header words fell outside the grid and the cells came
  out empty. `_find_header_rows` then correctly returned 1; it was fed a broken
  grid.
- Root cause: a one-line bug in `_cluster` (`src/soa/ingest.py`). It seeded the
  cluster group with the *unsorted* `values[0]` but iterated `sorted(values)[1:]`,
  so whenever the minimum coordinate was not first in input order **it was
  silently dropped**. Here that deleted the header's top rule. Latent on both
  axes, every page; the five samples escaped only because their minimum rule
  happened to be first in draw order.
- Proof: `_cluster([519.4, 473.9, 554.9, 708.8], tol=2.2)` returned
  `[519.4, 554.9, 708.8]` — 473.9 gone.

**Fixed** (sort once, seed and iterate the same list; `tests/test_cluster.py`
pins it). After the fix the column headers read `Visit 1 (prior to beginning
chemotherapy)`, `Visit 2 …`, `Visit 3 …`, `Unscheduled EPR oximetry readings`,
`Blood Draw Visits`. The **geometry-based header detector I had proposed as the
fix was evaluated and rejected** — it disagrees with the current detector on 4
of 5 samples because it misreads a leading category row (`Screening`) as header.

**~~Still open — one dropped row.~~ FIXED (2026-09-01).** p21's first body row,
`Toronto Clinical Neuropathy Scoring System`, was in the page text but absent
from the output. Root cause: `_assemble_row_continuation` skips each page's
header rows via `_find_header_rows`, which on a continuation page only detects a
header when the page *repeats* one carrying the timepoint vocabulary. p21
repeats no header and has no vocabulary, so the detector fell to its default
`return 1` and ate the real first assessment row. Fix (item 1): a header row
never carries cell marks, so on pages after the first the skip is bounded by the
first marked body row — `start = min(header_rows, first_marked)`. Neutral on all
five (their continuation pages' first marked row is at or beyond the computed
header end); NCT03348956 soa-1 now 14 → 15 rows, `Toronto` recovered. The
orphan-word audit (now wired — see ARCHITECTURE §5) confirms p21 reconciles
clean, and lights up again if this fix is reverted.

### NCT02096029 — no SoA, and the tool did not invent one

This is an implementation/cluster trial with no schedule-of-assessments table.
The single candidate returned is the `4.6 Projected Timetable` (Year 1–5 ×
project milestones), emitted with **`kind: "unknown"`** and a low-confidence
score. It did not claim to be an SoA.

Recall-wise there is nothing to miss. This is the designed behaviour —
return what is grid-shaped, label honestly, let the reviewer decide — and it
held on a document type not represented in the five.

### NCT02689531 — ~~wrongly merged two different appendices~~ MISDIAGNOSED (2026-09-01)

`APPENDIX A: DATA COLLECTION SCHEDULE (Arm 1)` on p22 is a real SoA-equivalent
(9 event rows × 8 state columns). It was found, and all 9 rows came out.

> **The original diagnosis below was wrong, and the re-measurement proves it on
> two independent counts.** It is kept for the record.

**~~But p23 is `Appendix B` … the guarded column-continuation merge fired,
producing one table with 17 columns instead of two tables of 8. The guard has
no way to tell a continuation from a parallel table…~~**

What was actually happening:

1. **No merge ever fired.** Checked the *committed* output's cell provenance:
   all 14 cells carry `page: 22`, **zero from page 23**. p23's data was never in
   the table. `_assemble_column_continuation` was never even reached (see 2).
   The "17 columns" were p22's *own* double-header-row garble — 8 scrambled
   header fragments + `Event` + 8 clean columns, all page-22-sourced. Candidate D
   (whole-row timepoint-vocabulary header detection) has since collapsed that to
   9 clean columns.
2. **p23 is not a parallel SoA table — it is prose.** It scores `v_rules=0,
   h_rules=1` (`Appendix B: Supplement for pediatric subjects … 1. Study
   Objectives: 1.1 … a. Estimate …`), below the grid threshold, so the locator
   never treats it as a grid page. It is swept into `footnote_pages` because its
   `a./b.` list items and a "Notes" line key the footnote lookahead. There is no
   Arm-2 grid to merge or to miss.

So the geometry gate the original text worried about is already effectively
enforced upstream by `is_grid`: two pages only reach the column-continuation
path when both are ruled grids (protocol1 p53→54). No guard against
"parallel table vs continuation" was needed, because NCT02689531 never presented
that case. The only residue today: p23 sits in soa-1's `footnote_pages`
(harmless — it contributes footnote text), and the orphan-word audit reports
NCT02689531 clean.

### Holdout summary

- 2 of 3 SoAs located; the third document has no SoA and was correctly not
  faked.
- 0 crashes, 0 silent empty outputs.
- ~~After the `_cluster` fix: headers correct on NCT03348956; **1 dropped row**
  (NCT03348956 p21) and **1 wrong merge** (NCT02689531 Arm A/B) remain open.~~
  **Re-measured 2026-09-01: both closed.** NCT03348956's header defect was closed
  by candidate D; its dropped p21 row is fixed (item 1). NCT02689531's "merge"
  never existed (misdiagnosis, above) — nothing to fix. **0 open holdout defects.**
- The union rule and char-level superscript detection both transferred to unseen
  data on first contact.

### Fixes applied after the holdout: **one, principle-based**

The rule was one round of principle-based fixes at most, and only if the
original five still pass untouched. Assessment of the three defects:

| Defect | Root cause | Decision |
|---|---|---|
| Garbage column headers | **Not** the suspected header heuristic. A latent one-line bug in `_cluster` dropped the header's top rule. | **Fixed.** One line, plus `tests/test_cluster.py`. All five samples still pass; the fix additionally *corrected* two latent verbatim truncations on the design set (see below). |
| Dropped p21 row | Separate; p21 row-continuation header handling. Not isolated. | ~~**Not fixed** — I will not guess at a fix I cannot verify.~~ **Fixed 2026-09-01 (item 1):** continuation-page header skip capped by the first marked row. Principle-derived, neutral on all five, holdout confirms. |
| ~~Arm A/B merged~~ | ~~The distinguishing signal is the title…~~ **Misdiagnosed.** No merge fired (0 cells from p23); the 17 columns were p22's own double-header garble; p23 is prose (`v_rules=0`), not a grid. | **No fix needed.** Candidate D collapsed p22's garble to 9 clean columns. See the corrected section above. |

**The `_cluster` fix was not neutral on the five — it was a strict improvement,
and that exposed a gap in my own earlier verification.** I had reported the fix
"byte-identical on all five" from a monkeypatch diff that compared only cell
`value_verbatim`, not row labels. The real all-output diff showed the fix also
recovered dropped leading characters that the same bug had been truncating on
the design set: protocol15's **main SoA** had `nformed consent` -> now
`Informed consent`, and `nfectious disease panel/` -> `Infectious disease
panel/`; protocol9's dosing template had `ILIZATION` -> `STABILIZATION`. None of
the 61 gates had caught these — a verbatim defect on a graded axis that only
surfaced because the holdout forced the bug into the open. That is the holdout
earning its keep twice: once on unseen data, once on the design set it was never
supposed to touch.

### Re-measurement (2026-09-01): a misdiagnosis in this very write-up

Re-running the holdout after several fixes did more than close defects — it
caught an error in the holdout analysis above. The NCT02689531 "Arm A / Arm B
merge" was recorded here with specific, confident mechanism ("the merge fired…
17 columns instead of two tables of 8… the guard cannot tell a continuation from
a parallel table"). **It never happened.** The committed output's own cell
provenance shows all 14 cells on page 22 and none on page 23; the column-merge
code was never reached; and p23 is prose with no ruled grid at all. The "17
columns" were a double-header-row garble on page 22 alone.

Two things let the wrong story stand as long as it did: the number "17" looked
like 8 + stub + 8 and *fit* a merge narrative, and nothing re-derived the claim
from the artifact until asked to. The lesson is the same one the `_cluster`
episode taught on the design set — **a plausible diagnosis is not a measured
one; read it back off the output.** It is recorded here rather than quietly
edited away because a caught misdiagnosis is part of the verification story, not
an embarrassment to bury. The now-wired orphan-word audit (ARCHITECTURE §5) is
the standing guard that would have contradicted the merge claim immediately:
NCT02689531 reconciles clean.

---

## M8 — Manual verification finding (small caps stripped as markers)

Found by manual review of protocol9 p20 in the UI against the rendered page. No
automated gate caught it; 167 tests were green. Small-caps row labels were being
stripped as footnote markers (`DETOXIFICATION` -> `DTOXTON` + markers
`e,i,f,c,a`). Root cause: the superscript raise-test used a cell-global
baseline, which a two-line cell makes meaningless — the median of body glyphs
across both lines sits *between* the lines, so an upper line's small caps test
as "raised" against it.

Fixed by measuring the raise per line: each glyph is compared to the body
baseline of its own text line (grid.py `_marker_chars`), with an alone-on-line
branch preserving protocol12's marker-on-its-own-line `a\nX` pattern. Gate:
protocol1/5/12/15 `out/` byte-identical; protocol9 changes by exactly one row —
p20 soa-3's label restored to `DETOXIFICATION/\nDOUBLE BLIND` with markers `[]`.
Marker inventory across the five is unchanged (144/144 genuine a-j markers
kept). One narrow limitation remains and is pinned by a test: an *all*-small-caps
line (no full-size leading capital) above a body line still falls to the
alone-on-line branch — no page in the five or holdout hits it.

A second defect on the same p20 cell — a vertically merged (rowspan) stub cell
emitted as one row per ruled band — was left unfixed by design; it loses no
content and its fix rewrites the whole row axis for a cosmetic gain on a
secondary table (README *Where it breaks* / *What I would build next* A2).

---

## The five sample protocols (design set — not evidence of generalisation)

Automated gates: **171 passed, 3 skipped**, `python -m pytest`.

| Protocol | SoA span | Cols | Rows | Cells | Marks | Footnotes bound |
|---|---|---|---|---|---|---|
| protocol1 | 53–54 (column-merged) | 17 (visits 1–13, ET, RT) | 29 | 152 | 0 | 0 / 0 |
| protocol5 | 50 | 12 | 31 | 107 | 0 | 0 / 0 |
| protocol9 | 26–29 | 12 (days 1–11) | 43 | 230 | 220 | **4 / 4** |
| protocol12 | 48–49 | 10 | 40 | 132 | 0 | **13 / 14** |
| protocol15 | 25–26 | 11 | 34 | 128 | 0 | **4 / 5** |

Specific structures verified against the rendered page:

- **Shading as a mark** (protocol9 p26): 50 grey fills → 23 shaded-empty marks +
  27 cells that are shaded **and** `1X`. `shaded` is orthogonal to
  `value_verbatim`, never a replacement.
- **Shading as decoration** (protocol5 p50 = 88 fills, protocol12 p48 = 33,
  protocol15 p25 = 36): **zero** promoted to marks. The negative case is gated.
- **Column continuation** (protocol1): visits 9–13/ET/RT recovered onto one row
  axis with per-cell page provenance.
- **Double-row split** (protocol5 p50): fires exactly once across the six SoA
  pages — the Saline band — with 5 grey-zone bands flagged `possible_split`
  rather than split.
- **Dividers**: `RANDOMIZATION` (protocol12 c2, protocol15 c3) typed `divider`,
  excluded from timepoints; protocol5's `Cocaine Infusion Session #` typed as a
  row divider.
- **Spanning values** (protocol9): `Prior to Day 4` = one cell, colspan 3, on all
  three affected rows; p28's `Admission, Monday, Wednesday, Friday, Discharge and
  As Needed` = colspan 11. Adjacent marks never merge.
- **Undefined markers surfaced, not resolved**: protocol9's `(01)`–`(33)` are
  flagged `marker_used_undefined` (SME open question 1); protocol12's `*` is
  defined but never printed and stays unanchored.

### Known limitations on the design set

- protocol12 `*` and protocol15 `a` remain unanchored (correct — one is never
  printed; the other attaches to prose).
- `role: "unknown"` on secondary candidates' columns is deliberate: an honest
  unknown beats a confident wrong role.
- The AE-frequency table in protocol15 (pp. 52–54) scores nearly as high as the
  real SoA. It is a legitimate multi-page ruled table; `kind` keeps it
  `unknown` and the candidate list makes the distinction cheap for a reviewer.
