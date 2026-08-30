# Recon findings — the five sample protocols

Every empirical claim here was measured against the five PDFs in
`data/protocols/`, and every one names the protocol, the page, and a way to
reproduce it. Where a statement is a judgement rather than a measurement it is
marked **[inferred]**. If a claim cannot be reproduced, it is not in this
document — that is the whole point of the rewrite.

**How the numbers were produced.** Page/rotation/char counts and the rect
census come from `pypdf` (`PdfReader`) plus a content-stream rectangle lexer
that applies the page CTM so dimensions are in points; text and keyword scans
are re-run under `pdfplumber`, the engine the tool actually ships with
(DECISIONS row 1), and any engine-dependent result is labelled as such. `python -m soa.recon data/protocols/` (milestone M1) reprints these
tables. Because character counts vary ~1% between extraction libraries, they
are reported as approximate and are **not** an exact-match gate; page count,
rotation set, and the identity of the top-X page per protocol are exact and are
what M1 checks.

Rendered-page reads referenced below were produced with `pypdfium2` at scale 2.0
(this repo's chosen rasteriser; see ARCHITECTURE §1).

---

## 1. All five are born-digital. None are scanned.

| Protocol | Pages | Text chars (approx) | Chars/page | Rotated pages | Producer / Creator |
|---|---|---|---|---|---|
| protocol1  | 97 | 172,000 | ~1,770 | none | Acrobat Distiller 6.0 / PScript5.dll |
| protocol5  | 61 | 177,000 | ~2,900 | **50, 51** | GPL Ghostscript 8.15 / PScript5.dll |
| protocol9  | 57 | 187,000 | ~3,290 | **26, 27, 28, 29** | GPL Ghostscript 8.15 / PScript5.dll |
| protocol12 | 97 | 271,000 | ~2,790 | none | Acrobat Distiller 7.0 / Acrobat PDFMaker for Word |
| protocol15 | 61 | 147,000 | ~2,410 | none | GPL Ghostscript 8.15 / PScript5.dll |

Every page has a real extractable text layer; the Producer/Creator strings are
print-to-PDF toolchains (Word → PScript5 → Distiller/Ghostscript), never a
scanner or image wrapper. Reproduce: read `reader.metadata` and
`len(page.extract_text())` per page.

**Consequence: no OCR workstream.** Do not add Tesseract. A scanned protocol is
a documented limitation (README), not something to pre-solve.

---

## 2. Keyword search does not reliably find the SoA, and where it fires is not enough to page on.

Pages whose text matches
`/schedule of (activities|assessments|events)|study flow chart|time and events|table of events/i`,
versus where the SoA table actually is (verified by reading the rendered page):

| Protocol | Keyword-regex hits (pdfplumber) | Actual SoA pages | What the regex does here |
|---|---|---|---|
| protocol1  | 4, 8, 27, 30, 35, 36, 52, 53, 54 | **53–54** | 9 hits, 7 are prose cross-references or the TOC; would have to rank |
| protocol5  | 5, **50** | **50–51** | Hits the real page, but only because the title happens to use "time and events" |
| protocol9  | *(none)* | **26–29** | Real title is "Schedule of **Measures**", not in the regex; regex matches nothing |
| protocol12 | 49 | **48–49** | The one hit is on p49, which is the footnote block, not the table (p48) |
| protocol15 | 24 | **25** | Hit is on p24 ("Table 1 provides an overview…"); table is on p25 |

Notes, each reproducible by rendering the cited page:

- **protocol5 p50 carries a title that reads cleanly** — verbatim
  `Appendix I: Time and Events Schedule`, sitting directly above the grid.
  **Engine-dependent, and this is the point:** `pypdf` returns it fragmented as
  `Tim e and Event s Schedul e` (whitespace breaks defeat the regex), while
  **pdfplumber reads it clean and the regex matches** (measured). The
  fragmentation was a library artifact, not a property of the PDF — which is a
  large part of why pdfplumber is the chosen engine (DECISIONS row 1). No
  char→word reassembly workstream is needed.
- **protocol9 has no keyword hit at all** under the documented regex. The prior
  version of this file listed hits on pages 25/29/40; that row could not be
  reproduced with any regex we could write down and has been removed. The real
  title is `Table 4. Schedule of Measures and Data Collection for Lofexidine
  Phase 3` (p26, rendered).
- **protocol12's single hit is on the wrong page**: p49's text begins `Notes on
  the Schedule of Assessments`, which is the lead-in to the table's footnote
  block, not the table. The table title, `Table 3. Overview of Study
  Assessments`, is on p48 above the grid and does not match the regex.

Takeaway: keyword matching is neither sufficient (protocol9 matches **nothing**
anywhere in the document) nor precise (protocol1's 9 hits with 7 decoys;
protocol12's single hit lands on the footnote page, not the table). Even where
it fires on the right page (protocol5 p50) it does so by luck of phrasing. It is
a confirmatory signal, not a pager: **0/5 as a pager**. See §6.

---

## 3. Standalone-`X` density finds the main SoA page in all five, with no model call.

Counting standalone `X` tokens per page (regex above):

| Protocol | Top X-dense page (page, X count) | Runner-up pages |
|---|---|---|
| protocol1  | (53, 72) | (54, 71) |
| protocol5  | (50, 95) | far below: (26,1),(35,1) |
| protocol9  | (28, 75) | (27, 61), (26, 27) |
| protocol12 | (48, 89) | far below: (39,3),(49,3) |
| protocol15 | (25, 109) | far below: (56,5),(30,2) |

The top X-dense page is the (or a) main SoA page in 5/5. This is **one** feature
of the locator scorer, not the whole locator (ARCHITECTURE §2). It is strong on
these five, but it is fragile in general — see §7 for tables in the sample set
that carry near-zero `X` (numeric cells) and would starve it.

---

## 4. Cell marks are drawn in the graphics layer, not always as text.

The most important structural fact, and the one a text-only extractor gets
silently wrong.

**protocol9 (`Table 4`, pages 26–28, `/Rotate 90`) marks cells by grey fill.**
Measured on the rendered pages plus the CTM-aware rect lexer:

- p26: 50 grey area-fills. **23 sit on cells with no text at all — the fill *is*
  the mark.** The other 27 sit under a cell that also contains the text `1X`, so
  the cell is **shaded AND `1X` at the same time.**
- p27: 72 grey fills (11 text-free, 61 over `1X`); p28: 100 grey fills
  (29 text-free, 71 over `1X`).
- `pdftotext`/`extract_text()` returns empty string for the 23/11/29 text-free
  marked cells. A text-only extractor reports them empty and looks like it
  worked.

Two consequences drive the schema (ARCHITECTURE §3, §"Output schema"):

1. The extractor must read filled rectangles from the graphics layer, not just
   text.
2. `shaded` is **not** a value that replaces the cell text — a protocol9 cell is
   routinely shaded *and* `1X`. Shading is a boolean orthogonal to
   `value_verbatim`.

Also on protocol9 p26 (rendered): the row `HIV (optional…)` carries the value
`Prior to Day 4` spanning three study-day columns; rows `Date` and `Day of Week`
are blank by design.

---

## 5. Shading semantics invert across the set — grey means opposite things in different files.

The same visual primitive (a grey-filled rectangle) is a data mark in one
protocol and pure decoration in another. Measured with the CTM-aware lexer plus
an overlap test (does each grey fill sit under glyphs, and does its band cover
the row-label/stub column?):

| Protocol / page | Grey area-fills | What they are | Evidence |
|---|---|---|---|
| protocol9 p26 / p27 / p28 | 50 / 72 / 100 | **Data marks.** Cell-local fills in the data-column region; 23/11/29 have no text under them and are the only mark that cell carries | text-free fills sit right of the stub column |
| protocol5 p50 | 88 | **Zebra row-banding.** Every grey fill belongs to a full-width band that also covers the row-label column | all 88 group into 22 bands, each starting at the stub-column x |
| protocol12 p48 | 33 | **Section + group-header banding.** Grey sits under the group header `Follow-up` and the section rows `Screening`/`Safety`/`Efficacy` | 8 of 33 overlap those header labels; rest fill the section rows |
| protocol15 p25 | 38 | **Section + header-row banding.** Grey sits under header row 1 and section rows | 8 overlap `Assessment`/`Screening`/`Treatment`/`Follow-up` labels |
| protocol1 p53 / p54 | 0 | **None.** No shading at all; marks are the literal text `X` | zero grey area-fills |

**This is why shaded-cell detection cannot be "any non-white fill in a grid slot
is a mark."** That rule turns protocol5's 88 zebra bands and protocol12/15's
section bands into fabricated activity marks. A band that spans the row-label
column is decoration; a cell-local fill in the data region with no text is a
candidate mark. The separation is *mostly* clean on these five but not perfectly
(a handful of section-row fills in p12/p15 land in the data region and need the
band test to reject), so genuinely ambiguous grey fills must be emitted with
`ambiguous: true`, not silently classified. See ARCHITECTURE §3 step 4.

Reproduce: `python -m soa.recon --shading data/protocols/` (M1) reprints the
grey-fill census and the band-vs-cell classification per SoA page.

---

## 6. Every SoA has an on-page title. Titles are a strong confirmatory signal, useless as a pager.

Verbatim titles, each read off the rendered SoA page:

| Protocol | Title (verbatim) | Page |
|---|---|---|
| protocol1  | `Protocol Attachment LZZT.1 / Schedule of Events for Protocol H2Q-MC-LZZT(c)` | 53 (p54: `…(concluded)`) |
| protocol5  | `Appendix I: Time and Events Schedule` | 50 |
| protocol9  | `Table 4. Schedule of Measures and Data Collection for Lofexidine Phase 3` | 26 |
| protocol12 | `Table 3.  Overview of Study Assessments` | 48 |
| protocol15 | `Table 1.  Overview of Study Assessments` | 25 |

All five have a title on the table's own page, and **pdfplumber reads all five
cleanly, including the two rotated protocols** (measured). The prior claim that
"title matching is a weak signal" was an artifact of a too-narrow regex — it did
not contain `overview of study assessments` or `schedule of measures`. The
separate claim that rotated titles arrive fragmented was an artifact of `pypdf`,
not of the PDFs, and does not apply to the shipping engine.

So the heading is inverted from the old finding: **near a grid it is a strong
confirmatory signal** (present on 5/5). It remains **useless as a primary pager**
because (a) the same or similar phrases appear in the TOC and in prose
cross-references pages away from the table (protocol1's 7 decoy hits), (b)
protocol9's real title uses vocabulary no fixed regex anticipated
("Schedule of **Measures**"), and (c) protocol12's title sits on the grid page
while the matching phrase sits on the *footnote* page. Use it to boost a
candidate that gridify already found; never to locate the table from scratch. **[inferred]** that a
sixth protocol may title its SoA with a phrase none of these use — the locator
must not depend on the title.

---

## 7. The recall traps: SoA spans, secondary tables, and X-decoys.

**Correct SoA page spans** (the recall target — verified by rendering each page):

| Protocol | SoA span | Note |
|---|---|---|
| protocol1  | **53–54** | Continued **by columns** — see below |
| protocol5  | **50–51** | Grid on p50; all 10 footnote definitions on p51 (top) |
| protocol9  | **26–29** | Grid on p26–28; p29 is `Table 4, Continued / Footnotes to Flow Chart` |
| protocol12 | **48–49** | Grid on p48; all 14 footnote definitions on p49 |
| protocol15 | **25** | Grid and footnotes both on p25 |

The footnote pages (p51, p29, p49) are part of the table's span. A locator that
returns only the grid page drops the entire footnote apparatus on three of five
protocols, and footnote linking across a page break is a graded axis. See
ARCHITECTURE §2 (marker-driven lookahead).

**Column-wise continuation (protocol1 p53→p54).** p54 repeats all 28 row labels
verbatim and adds visit columns 9–13, ET, RT on a **different x-grid**; the
tables are split by columns, not rows. Rendered-page confirmed: identical row
stub, disjoint column sets, per-page footnote blocks (p54 omits the `Xa`/`P`
notes and adds `ET`/`RT`). Emitting two half-tables loses the unified visit
axis. Handling: ARCHITECTURE §3 (guarded merge).

**protocol1 p53 has a fully empty visit column.** Between visit 5 and visit 7
there is a drawn, bordered column with no header text and no marks in any of the
28 rows (the study has no visit 6). Rendered-page confirmed. Word-clustering
alone cannot find a column containing zero words — only the ruling lines reveal
it. This is a silent column-drop trap; ARCHITECTURE §3 reconstructs columns from
rules as well as text.

**protocol5 p50 has a missing horizontal rule.** The rows
`Saline/20 mg cocaine/40 mg cocaine i.v.` and `20 mg cocaine i.v.` share one
over-tall (~23 pt) ruled band with no separator drawn between them, though they
are two rows with disjoint mark sets (rendered-page confirmed). A rules-only
parser merges them into one row; a baselines-only parser splits them correctly.
This is why gridify reconstructs rows from **both** sources (ARCHITECTURE §3).

**Secondary schedule tables in the set** (candidate-listing only, **not**
extraction targets — see PLAN "Out of scope"):

- protocol5 p51 (bottom): `APPENDIX II: Schedule of Blood Collections` — a ruled
  grid whose cells are integers (`1`, `15`, `2`), zero `X`.
- protocol5 p29–30: `Table 2. Cocaine Infusion Sessions Daily Schedule` — a
  genuinely multi-page, header-repeating ruled table on a clock-time axis.
- protocol9 p20: a lofexidine dosing template (dose strings per study day).

These matter because the locator's `X`-density feature scores ~0 on the
numeric ones; the scorer must not be `X`-only (ARCHITECTURE §2). They are listed
in output as candidates for the reviewer; we do not extract their grids.

**`X`-decoys** (false positives for an `X`-density pager, all reproducible by
grepping the cited page): `X-ray` in protocol9 p24 (four hits in exclusion
criteria), `> 2.5X ULN` in protocol15 p56, and literal `X`/`x` used as algebraic
placeholders in protocol1's syncope decision tables (p37–38).

---

## 8. Rules are drawn as filled rectangles, not stroked lines — on all five.

Every "line" in these tables is a thin **filled** rectangle (`re` + `f`), not a
stroked path (`S`/`l`). Measured with the CTM-aware lexer:

| Protocol / page | Filled rects | Stroke ops | Thinnest rects |
|---|---|---|---|
| protocol1 p53 | 972 | 0 | 0.72 pt corner joints + full rules |
| protocol5 p50 | 1,426 | 1 | 0.48 pt rules |
| protocol9 p26 | 823 | 0 | ~1.4 pt rules |
| protocol12 p48 | 587 | 0 | 0.48 pt rules |
| protocol15 p25 | 1,274 | 1 | 0.48 pt rules |

**Consequence for the code**: `page.lines` is effectively empty on all five
(0 on protocol9 p26, 1 on protocol5 p50 — a page-footer rule); it only holds
stroked paths. Rule detection therefore reads the **union of rect-derived edges
and `page.lines`** — the union matters because these five draw rules as rects but
an unseen protocol may use real stroked lines, and a rect-only reader would find
nothing there (DECISIONS row 3).

The survivors are filtered by a **derived** threshold — segments thinner than
0.25 × the page's median character size — not a fixed constant. Measured: the
derived filter is flat across a 24× ratio sweep on all five protocols, whereas
`snap_tolerance` has a cliff (6 works, 10 drops rows, 12 collapses the grid).
Grid dimensions recovered under the derived filter: protocol1 30×10,
protocol5 32×12, protocol9 24×12, protocol12 42×10, protocol15 37×11.
Sub-pixel corner-joint rects (protocol1's 0.72 pt squares) are discarded.
Building the grid off `page.lines` alone would find nothing on these five; this
single fact would otherwise cost a confused half-day mid-sprint.

---

## Open questions for a clinical SME

Everything here is unconfirmed and is deliberately kept out of the findings body.

1. **The `(01)`–`(33)` numbers on protocol9 (`Table 4`, p26–28).** Row and
   cell labels carry parenthesised numbers like `(01)`, `(13)`, `(33)`. They are
   **not defined anywhere in the document** — pages 26–29 define only `*`, `**`,
   `***` and abbreviation glosses (Detox, SCID). The table carries the note
   `Form numbers may change`. **[inferred]** these are CRF form numbers, not
   footnote markers. We capture them verbatim on the row/cell but do not treat
   them as footnotes pending SME confirmation. If they are footnotes, they are
   undefined-in-document and should be flagged, not resolved.
2. **A grey-shaded cell with no text** (protocol9) — is it semantically
   identical to `X`, or can shading ever mean "not applicable"? We capture
   `shaded: true` and do not normalise; a definitive answer would let the
   verifier assert equivalence.
3. **A value spanning several visit columns** (`Prior to Day 4`, protocol9 p26;
   `Admission, Monday, Wednesday, Friday…` on protocol9 p28) — one event or a
   per-column requirement? We preserve the span (`colspan`) and do not
   distribute it.
4. **Metadata rows** (`Date`, `Day of Week` on protocol9) are capture rows, not
   assessments. Should they be typed differently, or excluded from a "rows
   present" recall count?
5. **The vertical `RANDOMIZATION` column** (protocol12 p48, protocol15 p25) is a
   milestone divider between the Baseline and Treatment column groups, not a
   timepoint. We represent it with `role: "divider"` (ARCHITECTURE schema); is
   that the right clinical reading, or should it be dropped from the visit axis
   entirely?
6. **Footnote body carrying data for a different row** (protocol12 footnote `b`:
   "…at weeks 4 and 8, if female, a urine pregnancy test will be performed") —
   should such embedded rules be surfaced against the Pregnancy-test row, or
   left in the footnote text only? We currently leave them in the footnote.
