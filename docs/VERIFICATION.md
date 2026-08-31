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
| NCT03348956 (Biomarkers in CIPN) | 31 | yes, pp. 20–21 | **yes** | rows + marks right, **column headers wrong**, 1 row dropped |
| NCT02096029 (NIDA implementation trial) | 22 | **no SoA in document** | n/a | correctly did **not** invent one |
| NCT02689531 (CTTI HABP/VABP) | 32 | yes, p. 22 (+ p. 23 is a *different* table) | yes | **wrongly merged two appendices** |

### NCT03348956 — located, headers FIXED; one row still dropped

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

**Still open — one dropped row.** p21's first body row,
`Toronto Clinical Neuropathy Scoring System`, is in the page text but absent
from the output (4 of 5 p21 rows captured). This is a **separate** cause (p21's
own header handling on a row-continuation page), unaffected by the `_cluster`
fix, and left as an open defect. Most-penalised failure class; real.

### NCT02096029 — no SoA, and the tool did not invent one

This is an implementation/cluster trial with no schedule-of-assessments table.
The single candidate returned is the `4.6 Projected Timetable` (Year 1–5 ×
project milestones), emitted with **`kind: "unknown"`** and a low-confidence
score. It did not claim to be an SoA.

Recall-wise there is nothing to miss. This is the designed behaviour —
return what is grid-shaped, label honestly, let the reviewer decide — and it
held on a document type not represented in the five.

### NCT02689531 — wrongly merged two different appendices

`APPENDIX A: DATA COLLECTION SCHEDULE (Arm 1)` on p22 is a real SoA-equivalent
(9 event rows × 8 state columns). It was found, and all 9 rows came out.

But p23 is **`Appendix B: Supplement for pediatric subjects (Arm 2)`** — a
*different table*. The guarded column-continuation merge (row-label match ≥95%)
fired because Appendix B repeats Appendix A's row labels, producing one table
with 17 columns instead of two tables of 8.

The guard was designed for protocol1 p53→p54, where the pages genuinely are two
halves of one table. It has no way to tell "same rows, continued columns" from
"same rows, a parallel table for a different population" — because at the
geometry level those are identical. This is a real limitation, not a bug in the
implementation of the rule.

### Holdout summary

- 2 of 3 SoAs located; the third document has no SoA and was correctly not
  faked.
- 0 crashes, 0 silent empty outputs.
- After the `_cluster` fix: headers correct on NCT03348956; **1 dropped row**
  (NCT03348956 p21) and **1 wrong merge** (NCT02689531 Arm A/B) remain open.
- The union rule and char-level superscript detection both transferred to unseen
  data on first contact.

### Fixes applied after the holdout: **one, principle-based**

The rule was one round of principle-based fixes at most, and only if the
original five still pass untouched. Assessment of the three defects:

| Defect | Root cause | Decision |
|---|---|---|
| Garbage column headers | **Not** the suspected header heuristic. A latent one-line bug in `_cluster` dropped the header's top rule. | **Fixed.** One line, plus `tests/test_cluster.py`. All five samples still pass; the fix additionally *corrected* two latent verbatim truncations on the design set (see below). |
| Dropped p21 row | Separate; p21 row-continuation header handling. Not isolated. | **Not fixed** — I will not guess at a fix I cannot verify. |
| Arm A/B merged | The distinguishing signal is the *title* ("Appendix B", "Arm 2"), not geometry. A title-difference veto is a new heuristic invented in response to holdout data. | **Not fixed** — this is exactly the overfitting the holdout exists to prevent. |

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

---

## The five sample protocols (design set — not evidence of generalisation)

Automated gates: **65 tests**, `python -m pytest tests/`.

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
