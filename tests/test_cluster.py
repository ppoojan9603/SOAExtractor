"""Regression pin for the _cluster minimum-drop bug (found via the M7.5 holdout).

The buggy version seeded the group with the unsorted values[0] but iterated
sorted(values)[1:], skipping the true minimum whenever it was not first in
input order. That silently dropped a rule coordinate -- on NCT03348956 it
deleted the header's top rule and produced garbage column headers.
"""
from soa.ingest import _cluster


def test_minimum_not_first_is_kept():
    # min (1.0) is not values[0]; it must survive and 50 must stay separate.
    assert _cluster([50.0, 1.0, 2.0, 3.0], tol=2.0) == [2.0, 50.0]


def test_isolated_minimum_not_first_is_kept():
    # the exact failing shape from NCT03348956: 473.9 arrives after 519.4.
    out = _cluster([519.4, 473.9, 554.9, 708.8], tol=2.2)
    assert out == [473.9, 519.4, 554.9, 708.8]


def test_order_independent():
    a = _cluster([1.0, 2.0, 3.0, 50.0], tol=2.0)
    b = _cluster([50.0, 3.0, 1.0, 2.0], tol=2.0)
    assert a == b == [2.0, 50.0]


def test_empty_and_single():
    assert _cluster([], tol=2.0) == []
    assert _cluster([7.0], tol=2.0) == [7.0]
