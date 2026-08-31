"""Vision provider interface (step 2 of the vision fallback).

A provider takes a rendered page image and returns a table it read from the
pixels, in a small fixed shape. This is the ONE place in the whole system where
a model produces cell values -- there is no text layer to read -- so the output
is marked model-authored at every level downstream (see soa.vision).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TypedDict


class VisionColumn(TypedDict):
    label: str


class VisionRow(TypedDict):
    label: str


class VisionCell(TypedDict):
    row: int          # index into rows[]
    col: int          # index into columns[]
    value: str


class VisionTable(TypedDict):
    title: str
    columns: list[VisionColumn]
    rows: list[VisionRow]
    cells: list[VisionCell]


class Provider(ABC):
    """Reads one table out of one page image."""

    name: str = "base"

    @abstractmethod
    def extract_table(self, image_png: bytes, page_number: int) -> VisionTable:
        ...


class ProviderUnavailable(RuntimeError):
    """Raised when no usable provider is configured -> caller must decline."""
