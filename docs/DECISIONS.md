# DECISIONS.md — finalized architecture decisions (authoritative)

Status: FINAL, approved by Poojan. Where this file conflicts with
ARCHITECTURE.md / PLAN.md / FINDINGS.md, THIS FILE WINS. First task of the
build session: fold these into those three docs, then implement.

Every row below went through three review loops (options → trade-offs → pick;
re-loop for correctness; re-loop for unseen-data robustness and industry
practice). "Measured" = verified against the five sample protocols this week.

## The decision table

| # | Component | Pick | Basis |
|---|---|---|---|
| 1 | PDF reading | pdfplumber only | Measured: reads rotated p5 p50 cleanly. PyMuPDF is AGPL. Cloud/OCR excluded (see 15, 16) |
| 2 | Grid engine | pdfplumber `extract_table` with explicit lines | Measured vs hand-count; camelot identical + heavy deps; docling untested (state in README); hand-rolling = rebuilding a solved wheel |
| 3 | Column/row boundaries | Filter ruling segments < 0.25 x median char size; pass survivors as explicit_vertical/horizontal_lines. Union page.rects-derived edges WITH page.lines (these five draw rules as rects; unseen docs may use real lines) | Measured: snap_tolerance has a cliff (6 ok, 10 drops rows, 12 collapses). The filter is flat across a 24x ratio sweep on all five: p1 30x10, p5 32x12, p9 24x12, p12 42x10, p15 37x11 |
| 4 | Unruled double-rows | Rule C-prime: split a band ONLY when (a) stub column holds >=2 distinct label lines AND (b) body marks form clusters sharing a baseline with those labels (top within 3pt, 1:1) AND (c) cluster column sets are disjoint. Grey zone (meets a+has >=2 mark clusters but fails b or c): keep merged, emit structured `possible_split` flag carrying each stub line's label + its marks. NO model call in row structure | Measured: v1 (split on 2 baselines) shatters 15 wrapped labels on p9 alone; v2 (disjoint cols) gave 24 false splits on p12/p15 (marks centered, superscripts shift boxes); v4 fires exactly once on six pages - the true Saline double-row (p5 p50 y=428-451). Grey zone measured: 6 bands, all six verifiably single rows |
| 5 | Shaded marks | Per row/column fill-union test: group area-fills by row band; if the row's fill union covers the stub column (or ~full table width) it is banding = decoration; same test on the column axis (header-column emphasis). Cell-local fills = marks. `shaded` is a boolean ORTHOGONAL to value_verbatim (p9 cells are "1X" AND shaded). Ambiguous fills flagged, never guessed | Measured: p9 p26 = 50 fills, 23 on empty cells (marks) + 27 under 1X; p5 p50 = 88 fills whose row-unions span x=50-688 incl. stub (zebra). Same geometry per fill, opposite meaning - only row context separates them |
| 6 | Superscript markers | Char-level: smaller size + raised/lowered baseline vs neighbors, detected in ingest, emitted as footnote_markers separate from value_verbatim. Also handles subscripts (FEV1) | Measured: p9 p26 char sizes 8/12/14/16pt - separates cleanly. Regex cannot tell Xa from literal text |
| 7 | Locator | Structural scorer, max over three profiles (marked / numeric / borderless); generic short-token+dingbat density, not only X; keyword/title as confirmatory boost ONLY (never nominates a page); low threshold, ALL candidates above it returned ranked | Measured: documented keyword regex = 0/5 as pager (p5's title exists but rotated; p12 title above table; p9 zero hits anywhere); X-density = 5/5 on main SoAs. Profiles cover in-sample X-less grids (p5 p51 numeric, p9 p38 borderless) |
| 8 | Multi-page assembly | Footnotes: marker-driven lookahead - collect markers used-but-undefined in span, scan next 1-2 pages for lines keyed by them; flexible marker forms (letter/symbol/digit/parenthesized); unmatched = flagged, never guessed. Column continuation (p1 p53-54): merge iff row-label sequences match >=95%, else two tables + continuation_of link | Layout heuristics fail both real cases (p12 p49 scores ~0 on grid features; p5 p51 contains an unrelated grid). p12 binding is the hardest case - bind what matches, flag the rest |
| 9 | Header hierarchy, roles, footnote binding | DETERMINISTIC at runtime. Hierarchy = spanning-cell geometry (a header cell's bbox covers its children's x-range; find_tables gives the bboxes). Binding = marker matching per row 8. Roles (period/visit/study_day/window/divider/category) = transparent heuristics; unknown stays `role: unknown`, flagged. LLM exists ONLY as optional enrichment (--enrich, OFF by default), constrained to ids+links+roles, id/label echo asserted, never writes values | Loop 2 finding: nothing the model was assigned needs a model - nesting is geometric, binding is string matching, roles are advisory in our schema. Removing it: graders run the tool with zero API keys, output deterministic + reproducible, confidentiality airtight ("protocols never leave the machine; AI built the tool, AI is not in the tool") |
| 10 | Model provider | Adapter kept for the optional --enrich pass only; strongest available model when used; free-tier Gemini banned (terms retain content). Three-way benchmark = designed-not-run (README section) | Demoted by row 9. ~10 calls if ever used - cost is pennies, quality wins |
| 11 | Verifier | External invariants only: orphan-WORD audit (every word in table bbox lands in exactly one cell - the primary drop detector); orphan-FILL audit (every area-fill classified mark/banding/flagged); marker bidirectionality (used-but-undefined AND defined-but-unused, both reported); footnote continuation check; missed-continuation check; dual-source disagreements surfaced. Circular checks (row count vs own y-bands, cells == rows x cols) stay removed | Only checks external to gridify count. p9's (01)-(33) surface as used-but-undefined - correct, they are flagged not resolved (SME question) |
| 12 | Output schema | As ARCHITECTURE.md, plus: per-table `extraction_confidence` + `strategy` (which path produced it: explicit-lines / text-fallback), and the `possible_split` flag from row 4. Verbatim-first, trees both axes (flagged DAG approximation for p15's two-parent column), bbox+page provenance everywhere | Flat loses graded hierarchy; parsed-only loses graded verbatim |
| 13 | UI | FastAPI + one vanilla HTML page. Upload -> ranked candidate list (clickable - a locator miss is recoverable by a human in two clicks, not fatal) -> side-by-side extracted grid vs rendered page image, bbox hover-highlight, footnote panel with attachments, warnings banner, possible_split and ambiguous rows visually marked. "Upload" is a stated requirement - no static-report shortcut. CLI shares the same pipeline to produce committed out/ JSONs | Streamlit fights custom overlays; React is build tooling for zero graded benefit ("we are not grading visual design") |
| 14 | Language | Python | Every measurement and library above is Python |
| 15 | Scanned protocols | DETECT and fail loud: page with ~zero text chars + large image object -> UI shows rendered page + explicit message (scanned protocol, text-layer extraction does not apply, OCR is a documented non-goal). No OCR in scope | The assignment itself: "some are scanned". Our five are all born-digital (measured) but the unseen one may not be. Silent empty output is the worst grading outcome; designed loud failure is a graded strength ("where it breaks and what it does") |
| 16 | Borderless tables | Strategy chain: enough rulings -> explicit-lines; sparse rulings -> pdfplumber text-alignment strategy, extraction_confidence downgraded + table flagged | In-sample example exists (p9 p38 borderless PK block). Text strategy already exercised in the benchmark |
| 17 | Data handling | Fully local pipeline; protocols never uploaded anywhere. gitignore the PDFs | Assignment ground rule + clinical-industry norm |
| 18 | README extras | CDISC / ICH M11 mapping paragraph as future work; docling flagged untested; the snap-cliff and split-rule iteration history kept (already written) | Reviewers are clinical-trial infrastructure people; the assignment name-drops M11 |

## Supersessions (apply these edits to the other docs)

1. ARCHITECTURE section 1: DELETE the char-to-word reassembly workstream and the
   claim that rotated text must be rebuilt. That fragmentation was a pypdf
   artifact - pdfplumber reads p5 p50 as "Appendix I: Time and Events Schedule"
   clean (measured). KEEP the title_verbatim test gate but restate its purpose:
   it proves engine choice, not a reassembly routine. Ingest = thin wrapper:
   extract_table + find_tables cell bboxes + fill-to-cell mapping (point-in-box;
   all 53 fills on p9 p26 land inside a cell bbox) + char sizes + scan detection
   (row 15) + strategy chain (row 16).
2. ARCHITECTURE section 1: rules ARE filled rects here, but read edges as the
   UNION of rect-derived edges and page.lines (row 3), filtered by the derived
   min-segment threshold - not page.edges with a fixed 1.5pt constant alone.
3. ARCHITECTURE section 3: replace the dual-source prose for the missing-rule
   case with the exact C-prime rule + grey-zone possible_split behavior (row 4),
   including the measured iteration history. Extend shading with the column-axis
   symmetry (row 5).
4. ARCHITECTURE section 4 (Interpret): REWRITE per row 9. The runtime pipeline
   is deterministic; geometry does hierarchy, matching does binding, heuristics
   do roles with unknown-flags; the LLM section moves to "optional enrichment".
5. ARCHITECTURE Provider section: demote per row 10.
6. ARCHITECTURE section 5: add the orphan-fill audit (row 11).
7. Schema: add extraction_confidence, strategy, possible_split (row 12).
8. UI: add candidate list + scanned-page message (rows 13, 15).
9. PLAN M1 gates: p9 p26 is 24x12 under the derived filter (truth: 12 body
   columns - the earlier "13" was a miscount); title gate rationale per item 1;
   add scan-detection and text-fallback smoke tests. PLAN M4 becomes the
   deterministic roles/binding milestone; enrichment optional. Gates for the
   splitter: exactly ONE split across the six SoA pages (the Saline band), 6
   grey-zone bands flagged possible_split, zero on p1/p9/p12/p15.
10. PLAN M9: unchanged (designed-not-run), now scoped to the optional pass.

## What stays decided from before (do not relitigate)

Recall over precision. Verbatim over normalized. Represent ambiguity, never
resolve it. Secondary schedules candidate-listed, not extracted. No debug-hook
reliance anywhere. UI on Day 2 because it is the verification harness. Docs
carry measured claims with protocol+page or they carry the label [inferred].
