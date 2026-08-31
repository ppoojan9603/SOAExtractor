# CLAUDE.md — working agreement for this repo

## What this is

An SoA (Schedule of Activities) extraction tool for clinical trial protocol
PDFs. Locate the SoA in an arbitrary protocol, extract it faithfully into
structured JSON, and render it for human review beside the source page.

Read in this order before doing anything: `docs/FINDINGS.md`,
`docs/ARCHITECTURE.md`, `PLAN.md`.

## Non-negotiables

1. **Never hardcode a page number, protocol filename, or table title.** The
   tool is graded on a protocol it has never seen. `docs/FINDINGS.md` lists
   known page numbers as *test expectations only* — they belong in tests, never
   in `src/`.
2. **The model never produces a cell value.** Cell text comes from PDF
   geometry. The model classifies, links and flags. If a change would let the
   model emit table content, do not make it — raise it instead.
3. **Recall over precision.** A missing row or column is the most heavily
   penalised failure. An extra candidate table or an extra flagged cell is
   cheap. When in doubt, include and flag.
4. **Verbatim over normalised.** Cell values are captured exactly as they
   appear: `3X`, `Q2W`, `X (if applicable)`, `(X)`, an arrow, a shaded box.
   Never coerce to true/false. Parsed interpretations live *beside* the
   verbatim string, never replace it.
5. **Represent ambiguity, do not resolve it.** If a cell is genuinely unclear,
   emit it with `ambiguous: true` and a reason.
6. **A stated gate is a contract. When it fails, STOP and surface it before
   committing** — byte-identical, a count, a passing test, anything I named as
   the bar. This holds even when every diff looks corrective: deciding "the
   deviation was good" is my call to make, not yours. Do not proceed past a
   failed gate on your own judgement that the outcome is fine.

## Working style

- Explain before you write. State what problem the code solves and why it has
  to exist, then write it. I am JavaScript-primary and ramping on Python typing
  — spell out type signatures rather than assuming I read them fluently.
- One component at a time. Do not generate four files in one go.
- Cite real `file:line` when describing existing code. If you have not read a
  file, say so rather than describing it.
- Keep learning separate from fixing: how it works first, then what is wrong.
- When something is ambiguous, ask. When you are guessing, say you are guessing.

## Assumptions and SME questions

Anything you assumed about clinical meaning goes in `docs/FINDINGS.md` under
"Open questions for a clinical SME". Write the question down rather than
guessing silently.

## Commands

```bash
uv sync                                  # deps
python -m soa.recon data/protocols/      # reproduce FINDINGS tables
python -m soa.run data/protocols/protocol9.pdf -o out/    # full pipeline
uvicorn soa.ui.app:app --reload          # review UI
pytest                                   # locator expectations + schema tests
```

## Data handling

Protocol PDFs are confidential and must not be sent anywhere that retains
content for training. Free-tier Gemini is therefore prohibited — billing must
be enabled. Anthropic and OpenAI APIs do not train on API data by default.
Keep `data/protocols/` gitignored.
