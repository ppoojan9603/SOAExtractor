"""Live Anthropic vision provider — strongest available model, schema-constrained.

Used only when ANTHROPIC_API_KEY is set. The protocol image is sent to the
Anthropic API, which does not train on API data by default (see README data
handling). If the key or package is missing, construction raises
ProviderUnavailable and the caller declines (behaviour A).
"""
from __future__ import annotations

import base64
import json
import os

from .base import Provider, ProviderUnavailable, VisionTable

#: Strongest generally-available model at time of writing.
DEFAULT_MODEL = "claude-opus-4-8"

_TOOL = {
    "name": "emit_table",
    "description": "Return the schedule-of-activities table read from the image.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "columns": {"type": "array", "items": {
                "type": "object", "properties": {"label": {"type": "string"}},
                "required": ["label"]}},
            "rows": {"type": "array", "items": {
                "type": "object", "properties": {"label": {"type": "string"}},
                "required": ["label"]}},
            "cells": {"type": "array", "items": {
                "type": "object", "properties": {
                    "row": {"type": "integer"}, "col": {"type": "integer"},
                    "value": {"type": "string"}},
                "required": ["row", "col", "value"]}},
        },
        "required": ["title", "columns", "rows", "cells"],
    },
}

_PROMPT = (
    "This is a scanned page of a clinical-trial protocol with NO text layer. "
    "Read the Schedule of Activities table exactly as printed. Return every row "
    "and every column, including the row-label (leftmost) column as columns[0]. "
    "Copy cell values verbatim (X, 3X, Xa, blank). Do not infer or normalise. "
    "rows[] are the assessment rows top to bottom; columns[] are left to right; "
    "each cell references row and col by index. Call emit_table with the result."
)


class AnthropicProvider(Provider):
    name = "anthropic"

    def __init__(self, model: str | None = None):
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise ProviderUnavailable("ANTHROPIC_API_KEY is not set")
        try:
            import anthropic
        except ImportError as exc:                       # pragma: no cover
            raise ProviderUnavailable("anthropic package not installed") from exc
        self._client = anthropic.Anthropic(api_key=key)
        self._model = model or os.environ.get("SOA_VISION_MODEL", DEFAULT_MODEL)

    def extract_table(self, image_png: bytes, page_number: int) -> VisionTable:
        b64 = base64.standard_b64encode(image_png).decode("ascii")
        msg = self._client.messages.create(
            model=self._model,
            max_tokens=8192,
            tools=[_TOOL],
            tool_choice={"type": "tool", "name": "emit_table"},
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64",
                 "media_type": "image/png", "data": b64}},
                {"type": "text", "text": _PROMPT},
            ]}],
        )
        for block in msg.content:
            if getattr(block, "type", None) == "tool_use":
                return block.input                       # already schema-shaped
        raise ProviderUnavailable("model returned no tool call")
