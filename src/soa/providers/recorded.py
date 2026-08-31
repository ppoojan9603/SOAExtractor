"""Recorded vision provider — replays a saved response.

Two uses:
  1. Deterministic, offline gates and CI: the vision path is exercised without a
     live API call or key.
  2. This environment has no ANTHROPIC_API_KEY, so the p48 fallback score is
     produced by a strongest-available vision model reading the rendered image
     on-machine, saved here and replayed. The code path is the real adapter; the
     response is a fixture, and it is labelled as such wherever it is scored.

Selected when SOA_VISION_RECORDED points at a JSON file shaped like VisionTable.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .base import Provider, ProviderUnavailable, VisionTable


class RecordedProvider(Provider):
    name = "recorded"

    def __init__(self, path: str | None = None):
        p = path or os.environ.get("SOA_VISION_RECORDED")
        if not p or not Path(p).is_file():
            raise ProviderUnavailable(f"recorded response not found: {p!r}")
        self._table: VisionTable = json.loads(Path(p).read_text(encoding="utf-8"))

    def extract_table(self, image_png: bytes, page_number: int) -> VisionTable:
        return self._table


def select_provider():
    """Pick a provider, or raise ProviderUnavailable so the caller declines.

    Recorded takes precedence (explicit opt-in via env), then a live key.
    """
    from .base import ProviderUnavailable
    if os.environ.get("SOA_VISION_RECORDED"):
        return RecordedProvider()
    if os.environ.get("ANTHROPIC_API_KEY"):
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider()
    raise ProviderUnavailable(
        "no vision provider configured (set ANTHROPIC_API_KEY or SOA_VISION_RECORDED)")
