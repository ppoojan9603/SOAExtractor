"""Put the repo root on sys.path so `pytest` works the same as `python -m pytest`.

`python -m pytest` puts the current directory on sys.path; the bare `pytest`
console script does not. tests/test_ui.py imports `ui.app`, and `ui/` lives at
the repo root rather than under src/ (it is the review UI, not part of the
installed package), so under bare `pytest` that import failed at collection.
A root conftest.py is imported before collection, so this runs early enough.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
