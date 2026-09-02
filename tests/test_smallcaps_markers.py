"""Small caps vs footnote superscript (M8 fix): the raise test is per-line.

Found by manual review (M8) of protocol9 p20: the two-line stub cell
'DETOXIFICATION/ DOUBLE BLIND' had its small-caps letters stripped as phantom
footnote markers, because the raise test used a cell-global baseline that a
multi-line cell makes meaningless. The fix compares each glyph to the body
baseline of its OWN line. These tests pin the discriminator on synthetic cells
whose geometry mirrors the measured pages.
"""
from __future__ import annotations

from soa.extract.grid import _superscript_markers, _superscript_char_ids


def _ch(text, size, top, bottom):
    return {"text": text, "size": size, "top": top, "bottom": bottom}


def test_small_caps_with_leading_full_cap_are_not_markers():
    """protocol9 p20 shape: two lines, each a full-size cap then same-size-line
    small caps. Small caps sit on their line's baseline -> not raised -> kept in
    the value. (The old cell-global baseline flagged e,f as markers.)"""
    cell = [
        _ch("D", 11, 357.3, 368.3), _ch("E", 9, 358.9, 367.9), _ch("F", 9, 358.9, 367.9),
        _ch("B", 11, 372.9, 383.9), _ch("C", 9, 374.5, 383.5),   # second line
    ]
    assert _superscript_markers(cell) == []
    assert _superscript_char_ids(cell) == set()


def test_marker_on_its_own_line_above_value_is_kept():
    """protocol12 'a\\nX' shape: the marker sits alone on the line above the
    value. No body glyph on its line -> alone-on-line branch -> marker."""
    cell = [_ch("a", 7, 100, 107), _ch("X", 11, 110, 121)]
    assert _superscript_markers(cell) == ["a"]
    assert _superscript_char_ids(cell) == {id(cell[0])}


def test_same_line_raised_superscript_is_kept():
    """protocol1/5 'Xa' shape: marker shares the line but is raised above the
    body baseline."""
    cell = [_ch("X", 11, 100, 111), _ch("a", 7, 99, 106)]
    assert _superscript_markers(cell) == ["a"]


def test_all_smallcaps_line_above_body_is_the_known_gap():
    """KNOWN NARROW LIMITATION, pinned so a later change is deliberate.

    A line that is ENTIRELY small caps (no full-size glyph) sitting above a body
    line has no same-line body to compare against, so it falls to the
    alone-on-line branch and its a-j letters ARE read as markers. No page in the
    five or the holdout hits this (their small-caps lines carry a full-size
    leading capital), but an unseen all-small-caps label line would. If someone
    later fixes this branch, this test should change to reflect it.
    """
    cell = [_ch("a", 9, 100, 109), _ch("b", 9, 100, 109),   # all-small line
            _ch("X", 11, 112, 123)]                          # body line below
    assert _superscript_markers(cell) == ["a", "b"]          # current behaviour
