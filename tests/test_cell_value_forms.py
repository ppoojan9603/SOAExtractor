"""Cell-value forms the assignment names but our five never exercise.

We do NOT build speculative handling. Instead we feed each named string through
the cell-value path and assert it survives verbatim, unnormalised. If any form
were mangled, that would be a bug to fix. Forms drawn as GRAPHICS rather than
text are a separate case, recorded as a documented limitation (skipped test).
"""
from __future__ import annotations

import pytest

from soa.extract.grid import _value_without_superscripts

# The assignment's list, plus the numeric/dose/volume/dash/dot forms it names.
NAMED_FORMS = [
    "3X", "3X/2 weeks", "2X/day", "Q2W", "(X)", "X (if applicable)",
    "1X", "3X/week", "12", "10 mg", "5 mL", "100 mg/day (s.c.)",
    "-", "–", "—", ".", "→", "←", "↑", "≤ 80 mmHg",
]


@pytest.mark.parametrize("form", NAMED_FORMS)
def test_form_survives_value_path_verbatim(form):
    # a cell with no superscript chars must pass through the value path untouched
    assert _value_without_superscripts([], form) == form


@pytest.mark.parametrize("form", NAMED_FORMS)
def test_form_survives_with_a_trailing_superscript(form):
    """With a real superscript marker present, the value path strips ONLY the
    raised glyph and keeps the form verbatim (protocol12/15 behaviour)."""
    chars = (
        [{"text": ch, "size": 10.0, "top": 100.0, "bottom": 110.0,
          "x0": 10.0 + i, "x1": 11.0 + i} for i, ch in enumerate(form)]
        + [{"text": "a", "size": 6.0, "top": 96.0, "bottom": 101.0,   # raised marker
            "x0": 10.0 + len(form), "x1": 11.0 + len(form)}]
    )
    out = _value_without_superscripts(chars, form + "a")
    assert out == form, f"{form!r}+marker -> {out!r}"


@pytest.mark.skip(reason="DOCUMENTED LIMITATION: an arrow or dot drawn as a vector "
                         "graphic (not a text glyph) is not in the text layer, so "
                         "it would come through as a blank cell unless it is a grey "
                         "fill (which the shading path catches). None of the five "
                         "uses a drawn arrow/dot as a mark; text-glyph arrows/dots "
                         "(tested above) are preserved. Handling drawn glyphs would "
                         "need a vector-shape classifier -- out of scope, not guessed.")
def test_drawn_arrow_or_dot_glyph():
    ...
