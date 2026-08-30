# Architecture review prompt

Paste alongside the gstack eng-review skill, before any code is written.

---

Review `docs/ARCHITECTURE.md` and `docs/FINDINGS.md` as the eng manager who
will be on the hook when this ships. No code exists yet — this is a design
review, and I want it adversarial. Do not validate the plan; try to break it.

**Context.** This is a take-home for a clinical-trial tooling company, 3 days,
solo. The tool locates the Schedule of Activities table inside an arbitrary
protocol PDF and extracts it to structured JSON with a review UI. It will be
graded on a protocol none of us has seen. Their stated grading emphasis, in
their words: missing rows and columns are the most heavily penalised failure —
recall matters more than precision; cell values must be captured verbatim, not
normalised to booleans; footnotes must be extracted AND linked to the specific
cell/row/column they mark, including footnotes continuing across a page break;
hierarchy on both axes must be preserved; and "be faithful, not clever" — do
not infer, repair, or resolve ambiguity.

The five sample PDFs are in `data/protocols/`. Open them. `FINDINGS.md` makes
specific empirical claims about those files — verify them rather than trusting
them, and tell me if any are wrong.

**Challenge these specifically:**

1. The claim that the model must never produce a cell value, and that geometry
   alone can reconstruct these grids. Where does pure geometry fail on these
   five files? Is the id-equality assertion actually sufficient?
2. The locator feature set. Which of these five would it miss, and what would a
   sixth unseen protocol look like that defeats it? X-density is doing a lot of
   work — what happens on a table that uses dots, checkmarks, or shading only?
3. The output schema. Name a real structure in these five PDFs that it cannot
   represent without loss. Nested spans, multi-marker cells, a footnote
   attaching to a column group, a row appearing under two categories.
4. Recall. Where in this design does a row or column get silently dropped, and
   would the verifier in §5 actually catch it?
5. Scope. Is this buildable in 3 days by one person, or which milestone is a
   trap? What should be cut?

**Output:** ranked findings, most severe first. For each — what breaks, the
concrete input that breaks it, and the smallest change that fixes it. If a
design decision is right, say so briefly and move on; spend the words on what
is wrong. Flag anything I appear to have assumed without evidence.
