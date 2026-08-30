# Build plan — 3 days

Ordered so the load-bearing risk (gridify) gets the most Day-1 time, the thing
that makes verification cheap (the UI) gets built Day 2, and every milestone
ends in something runnable.

Ground truth for "done" is `docs/FINDINGS.md` — specific pages, including the
negative cases. Every "done when" below is checkable against a named page.

**Effort reality:** gridify is ~half the total effort and is the milestone that
can sink the submission; the locator is nearly solved (one feature is 5/5 on the
sample) and is timeboxed. Do not let the locator eat gridify's budget.

## Day 1 — geometry: ingest, locator (timeboxed), gridify

**M1. Ingest + recon CLI** (`python -m soa.recon data/protocols/`)
Thin pdfplumber wrapper: unioned rule extraction (rect-derived edges +
`page.lines`) filtered by the derived threshold (0.25 × median char size),
`extract_table` with explicit lines, `find_tables` cell bboxes, fill→cell
point-in-box mapping, char sizes for super/subscripts, scan detection, strategy
chain. Plus the recon report.
*Done when:*
- Page counts and rotation sets match FINDINGS §1 exactly (protocol5 → {50,51},
  protocol9 → {26,27,28,29}, others none). Char counts within ~1% (extractor
  variance — not an exact gate).
- Top X-dense page per protocol matches FINDINGS §3 exactly (p1→53, p5→50,
  p9→28, p12→48, p15→25).
- **Grid dimensions under the derived filter** match FINDINGS §8:
  protocol1 30×10, protocol5 32×12, **protocol9 24×12**, protocol12 42×10,
  protocol15 37×11. (protocol9 p26 is 12 body columns — an earlier "13" was a
  miscount and is not the gate.)
- `title_verbatim` for protocol5 p50 equals `Appendix I: Time and Events
  Schedule`. **Purpose of this gate: it proves the engine choice**, not a
  reassembly routine — `pypdf` fragments this string, pdfplumber does not, so
  the gate is a regression tripwire if anyone swaps the engine.
- **Scan detection smoke test:** a synthetic/borrowed image-only page is flagged
  `scanned` and produces the loud message, not an empty table.
- **Text-fallback smoke test:** a sparse-ruling page (protocol9 p38, borderless
  PK block) routes to the text-alignment strategy with
  `strategy: "text-fallback"` and a downgraded `extraction_confidence`.
- `--shading` reprints the grey-fill census matching FINDINGS §5 (p9 p26 = 50
  fills, p5 p50 = 88 fills), and **every fill is classified** (mark / banding /
  flagged) — zero unclassified.

**M2. Locator — timeboxed to ~2 hours.**
Three-profile scorer (marked / numeric / borderless), low recall threshold,
span assembly, **marker-driven footnote lookahead** (ARCHITECTURE §2). No LLM,
no keyword primary.
*Done when:*
- Returns a span covering the SoA for all five: p1→53–54, p5→50–51, p9→26–29,
  p12→48–49, p15→25 — as ranked candidates, never a single guess.
- **Negative case:** protocol5 returns candidates from page geometry, NOT from
  the TOC keyword hit on p5; protocol9 returns a candidate despite zero keyword
  hits anywhere.
- Footnote lookahead attaches p51 (protocol5), p29 (protocol9), p49 (protocol12)
  to their spans by marker matching — verify p49 attaches even though it scores
  near-zero on every grid feature.
- protocol5's `Schedule of Blood Collections` (p51 bottom) surfaces as a
  *separate* candidate, not merged into the SoA span.
*Watch for:* protocol1's 9 decoy keyword hits must not inflate its span; the
title feature may only boost a page that already has grid geometry.

**M3. Gridify — the load-bearing milestone. Budget the rest of Day 1.**
Rule C′ double-row splitter with grey-zone `possible_split`, two-axis fill-union
shading test, divider detection, spans, guarded column-wise merge
(ARCHITECTURE §3).
*Done when, checked page by page:*
- **Shaded marks, positive:** protocol9 p26 yields non-empty marks for its
  grey-filled empty cells (≥20 cells with `shaded: true` and no text), AND cells
  under `1X` come back `value_verbatim:"1X"` with `shaded:true` (shading is
  orthogonal, not a replacement — FINDINGS §4).
- **Shaded marks, negative (the check that proves we didn't over-fire):**
  protocol5 p50 yields **zero** shaded marks — its 88 grey fills are zebra
  banding whose row-fill unions span the stub column, so all 88 are discarded
  (FINDINGS §5). Same negative on protocol12 p48 and protocol15 p25 section/group
  banding: zero grey fills promoted to marks (a genuinely ambiguous one is
  allowed only as `ambiguous:true`). The column-axis fill-union test must also
  leave header-column emphasis unmarked.
- **Splitter (rule C′), exactly calibrated:** **exactly ONE split across the six
  SoA pages** — protocol5 p50's true Saline double-row (`Saline/20 mg…` and
  `20 mg cocaine i.v.`, y=428–451) comes back as two rows. **Zero splits on
  protocol1, protocol9, protocol12, protocol15.** The 6 grey-zone bands stay
  merged and carry a `possible_split` flag with each stub line's label and
  marks. A splitter that fires more is v1/v2 regressing (15 shattered labels /
  24 false splits — ARCHITECTURE §3).
- **No dropped column:** protocol1 p53 emits the empty visit-6 column (bordered,
  zero words) — it exists because the rules define it, and no text-based pass
  could have found it.
- **Column merge:** protocol1 p53+p54 merge into one table (28 row labels shared)
  with visit columns 1–13/ET/RT on one row axis; per-cell `page` provenance
  retained. If the label match fails, it falls back to two tables +
  `continuation_of`, never a corrupted merge.
- **Divider:** protocol12 p48 and protocol15 p25 emit the `RANDOMIZATION` column
  with `role:"divider"`, and its stacked single letters do not corrupt the row
  axis.

## Day 2 — deterministic structure, verification, UI

**M4. Deterministic structure: hierarchy, binding, roles**
No model. Header hierarchy from spanning-cell geometry, footnote binding by
marker matching, roles by transparent heuristics with `unknown` flagged
(ARCHITECTURE §4).
*Done when:*
- Header hierarchy is correct for protocol12 p48 and protocol15 p25 (period
  bands parent their visit columns) and protocol5 p50 (`Baseline Infusions`
  covers days −2/−1) — derived from bboxes, with **zero API keys set**.
- Footnote binding resolves protocol9 (including the p29 continuation block) and
  protocol12 (definitions keyed `Xa -` against bare superscript in-table
  markers). **Unmatched markers are flagged, not guessed** — protocol12's `*`
  (defined, never printed) surfaces as defined-but-unused.
- Roles assigned for the recognisable headers; anything else is
  `role: "unknown"` and flagged. No confident wrong roles.
- Re-running the pipeline twice produces byte-identical JSON.

**M4b. Optional `--enrich` adapter (only if M1–M6 are green).**
`base.Provider` + `anthropic.py`, ids/links/roles only, id+label echo asserted,
hard-fail on drift, `authored_by: "model"` stamped on anything it supplies.
Off by default. Cut this before cutting anything else.

**M5. Verifier**
Orphan-word audit + **orphan-fill audit** + external invariants
(ARCHITECTURE §5). The circular checks stay gone.
*Done when:*
- The orphan-word audit passes (zero homeless words) on protocol15 p25 (the
  clean single-page case) and **flags** the protocol9 `(01)`–`(33)` numbers as
  used-but-undefined markers (FINDINGS open question 1).
- The orphan-fill audit shows **every** area-fill classified as
  `mark` / `banding` / `flagged` on all six SoA pages — zero unclassified
  (protocol9 p26's 53 fills all map into a cell bbox, so an unclassified fill is
  a real defect).
- Emits ≥1 real warning on ≥1 protocol. All-clear on five messy 2001-era PDFs
  means the verifier isn't working.

**M6. Review UI**
FastAPI + one vanilla HTML page. Upload → **ranked candidate list** → pick →
side-by-side grid vs page image, hover-to-highlight, footnote panel, warnings
banner, `possible_split` / `ambiguous` marked.
*Done when:*
- A protocol never seen before can be uploaded and read against its source page.
- The candidate list is clickable, so a locator miss is recoverable in two
  clicks; protocol5's Blood Collections table appears there as a candidate.
- A scanned/image-only page renders with the explicit "OCR is a documented
  non-goal" message rather than an empty grid.
- The CLI produces the committed `out/` JSONs through the same pipeline.

## Day 3 — evidence and write-up

**M7. Run all five, commit outputs to `out/`.**

**M8. Manual verification, one protocol at a time, in the UI.**
Per protocol record: rows found vs present, columns found vs present, special
cell values carried verbatim (`3X`, `1X`+shaded, `Prior to Day 4`,
`Xa..Xf`), footnotes captured + correctly bound, continuation handled
(p5→51, p9→29, p12→49, p1 col-merge). Write it into `docs/VERIFICATION.md` as
you go — per protocol, what was right, what was wrong, *how* it was wrong.

**M9. Provider benchmark — designed, not run.** *(unchanged, now scoped to the
optional `--enrich` pass only.)*
Because the default pipeline makes no model call, this benchmark no longer
touches any graded output. Document the design — same five protocols, axes to
score (header links, footnote binding, ambiguity calls), how to run it — and
state that one provider was wired live. Do not risk M7/M8 to chase three
providers.

**M10. README.**
Architecture, schema + rationale, tools evaluated / chosen / rejected and why,
per-protocol verification results, where it breaks and what it does when it
breaks, next two weeks, AI tools used and where they helped or hurt. **Must
state**: secondary schedules (protocol5 p51 Blood Collections, protocol5 p29–30
Infusion) are candidate-listed only, not extracted; rotated-scan protocols are
an OCR limitation not handled; the protocol15 `-4 to 0*` two-parent column is a
flagged DAG approximation.

## Explicitly out of scope

- **OCR.** Nothing in the sample set is scanned (FINDINGS §1). Documented limit —
  but scanned pages are **detected and failed loudly** (M1), never silently
  emitted as an empty table.
- **A model in the default runtime.** Hierarchy, binding and roles are
  deterministic (ARCHITECTURE §4). `--enrich` is opt-in and off by default; the
  graded output never depends on it.
- **Extracting secondary schedule tables.** protocol5 p51 (`Schedule of Blood
  Collections`) and p29–30 (`Cocaine Infusion Sessions Daily Schedule`) are
  **candidate-listed** in output for the reviewer but their grids are not
  extracted, and they are **not** M2/M3 pass criteria. Stated in the README.
- **Three-provider benchmark as a run result.** Designed-not-run (M9), and now
  scoped to the optional enrichment pass only.
- **Normalising cell values to booleans.** Actively penalised.
- **Inferring or repairing ambiguous cells.** Represent the ambiguity instead.
- **Resolving the protocol15 two-parent column into a strict tree.** Emit the
  flagged DAG approximation; do not silently pick one parent.
- **Pretty visual design.** The assignment says it is not graded.

## Risk register

| Risk | Where it bites | Mitigation |
|---|---|---|
| Shaded detection over-fires → protocol5 zebra bands become fake marks | M3 | Negative gate: p5 p50 → zero shaded marks; band-covers-stub = decoration |
| Shaded detection under-fires → protocol9 marks lost → hollow output | M3 | Positive gate: p9 p26 → ≥20 shaded marks; check first |
| Row dropped by rules-only merge (p5 p50 missing rule) | M3 | Rule C′ splits it; grey-zone bands stay merged + `possible_split` |
| Splitter over-fires (v1 shattered 15 labels, v2 gave 24 false splits) | M3 | Gate: exactly ONE split across the six SoA pages |
| Empty bordered column dropped (p1 p53 visit-6) | M3 | Reconstruct columns from `page.edges`, not just words |
| Footnote page dropped (p51/p29/p49) → broken cross-page linking | M2 | Marker-driven lookahead, not layout heuristic |
| Engine swap silently re-breaks rotated text (pypdf fragments p5 p50) | M1 | pdfplumber only; `title_verbatim` exact-match gate as the tripwire |
| Built grid off `page.lines` alone → finds nothing here; rect-only → finds nothing on an unseen stroked-line PDF | M1 | Union both sources, derived 0.25×median-char threshold (FINDINGS §8) |
| `snap_tolerance` cliff (6 ok / 10 drops rows / 12 collapses) | M1 | Derived filter measured flat across a 24× sweep; don't tune snap |
| Unseen protocol is scanned → silent empty output | M1 | Scan detection + loud failure message (worst grading outcome avoided) |
| Model rewrites a cell value | M4b | No model in the default path at all; `--enrich` asserts id+label echo |
| Fill silently dropped by an over-firing banding test | M5 | Orphan-fill audit: every fill classified mark/banding/flagged |
| Verifier reports all-clear (circular checks) | M5 | Removed circular checks; orphan-word audit is the real drop detector |
| Locator eats gridify's Day-1 budget | Day 1 | Locator timeboxed to ~2h; one feature already 5/5 |
| Locator misses the SoA on the unseen protocol | M6 | UI candidate list makes it recoverable in two clicks, not fatal |
| Verification left to Day 3, runs out of time | Day 2/3 | UI is M6; verify as you go into VERIFICATION.md |
