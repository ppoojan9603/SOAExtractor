"""Regenerate the synthetic-scan fixture from the (gitignored) protocol.

The scan PDF is a page image of a confidential protocol, so it is NOT committed
(same posture as data/protocols/). We rebuild it at collection time from the
source page. If the source protocol is absent (a clone without the confidential
data), the vision tests that need it skip cleanly.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, "scripts")

SCAN_PDF = Path("tests/fixtures/protocol12_p48_scan.pdf")
SOURCE = Path("data/protocols/protocol12.pdf")

# Runs at conftest import (collection time), before skipif markers are evaluated.
if not SCAN_PDF.exists() and SOURCE.exists():
    from make_synthetic_scan import render_image_only_pdf
    SCAN_PDF.parent.mkdir(parents=True, exist_ok=True)
    SCAN_PDF.write_bytes(render_image_only_pdf(str(SOURCE), 48, 2.0))
