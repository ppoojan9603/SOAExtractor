"""Stub-column detection by text density (B2).

A "stub" is the label column(s) on the left of an SoA — the rows' names. The
naive rule "everything left of the first ruling" breaks when the label area is
itself multi-column (protocol5 p50 has a Study-Phase label plus a Study-day
sub-label) or when a table has no outer border.

Principle: label columns are **text-dense** (long words, high character count),
mark/timepoint columns are **terse** (a scattering of `X`/`3X`). So classify
each column band by the mean text length of the cells in it, and take the
contiguous run of dense columns on the left as the stub.
"""
from __future__ import annotations

from statistics import median


def _col_text_lengths(grid: list[list[str]], n_cols: int) -> list[float]:
    """Mean non-empty cell text length per column."""
    out = []
    for c in range(n_cols):
        lens = [len((row[c] or "").strip()) for row in grid if c < len(row) and (row[c] or "").strip()]
        out.append(sum(lens) / len(lens) if lens else 0.0)
    return out


def detect_stub_columns(grid: list[list[str]]) -> list[int]:
    """Indices of the leading label columns.

    Returns the contiguous run of text-dense columns starting at column 0. A
    column is "dense" if its mean cell-text length is at least the larger of
    (a) half the densest column's mean, or (b) 4 characters — marks like `X`,
    `3X`, `Xa` are 1-2 chars, so the threshold cleanly separates them.
    """
    if not grid:
        return [0]
    n_cols = max((len(r) for r in grid), default=0)
    if n_cols <= 1:
        return [0]
    lengths = _col_text_lengths(grid, n_cols)
    if not any(lengths):
        return [0]
    threshold = max(0.5 * max(lengths), 4.0)
    stub = []
    for c in range(n_cols):
        if lengths[c] >= threshold:
            stub.append(c)
        else:
            break
    return stub or [0]
