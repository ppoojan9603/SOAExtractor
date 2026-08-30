"""Mark-token vocabulary: what counts as a cell mark in an SoA grid.

FINDINGS §3 originally counted only standalone `X`. That is 5/5 on these five
protocols but starves on a grid that marks with checkmarks, dots or shading
(DECISIONS row 7), so the shipped counter is generic: a short token built from
a mark glyph, with an optional count prefix and an optional footnote suffix.

    X   x   3X   1X   Xa   3Xd   ✓   ●   ▪   √

Deliberately NOT marks: longer free text (`3X/week`), prose words containing X
(`X-ray`), and multipliers (`2.5X ULN`) -- see FINDINGS §7 X-decoys.
"""
from __future__ import annotations

import re

#: Glyphs that act as a "performed here" mark across SoA house styles.
MARK_GLYPHS = "Xx\u2713\u2714\u221a\u25cf\u25cb\u25a0\u25a1\u25aa\u25ab\u2022\u2219\u00b7\u2020\u2021"

#: count prefix (`3` in `3X`) + one mark glyph + footnote suffix (`a` in `Xa`).
_MARK_TOKEN = re.compile(
    rf"^[(\[]?\d{{0,2}}\s?[{MARK_GLYPHS}][a-jA-J]?[)\]]?[.,;]?$"
)

#: The X-only regex FINDINGS §3 used before, kept so the old measurement is
#: still reproducible and the two metrics can be compared side by side.
X_ONLY = re.compile(r"(?<![A-Za-z])[Xx](?![A-Za-z])")


def is_mark_token(token: str) -> bool:
    """True if `token` looks like a standalone cell mark rather than prose."""
    t = token.strip()
    if not t or len(t) > 4:
        return False
    # `X-ray`, `2.5X`, `X.` mid-sentence: reject anything with adjacent letters
    # or a decimal point still attached.
    if "." in t and not t.endswith("."):
        return False
    return bool(_MARK_TOKEN.match(t))


def count_marks(text: str) -> int:
    """Number of standalone mark tokens in `text` (the generic §3 metric)."""
    return sum(1 for tok in text.split() if is_mark_token(tok))


def count_x_only(text: str) -> int:
    """Number of standalone X tokens (the legacy §3 metric)."""
    return len(X_ONLY.findall(text))
