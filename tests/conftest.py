import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import pytest

PROTO_DIR = ROOT / "data" / "protocols"


def pytest_collection_modifyitems(config, items):
    if not PROTO_DIR.exists() or not list(PROTO_DIR.glob("*.pdf")):
        skip = pytest.mark.skip(reason="sample protocols not present")
        for item in items:
            if "needs_pdfs" in item.keywords:
                item.add_marker(skip)
