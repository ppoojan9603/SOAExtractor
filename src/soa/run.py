"""CLI: python -m soa.run <pdf> -o out/"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .pipeline import run


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="soa.run")
    ap.add_argument("pdf")
    ap.add_argument("-o", "--out", default="out")
    ap.add_argument("--max-candidates", type=int, default=None)
    ap.add_argument("--vision-fallback", action="store_true",
                    help="read text-less (scanned) pages with a vision model; "
                         "off by default (behaviour A: detect and decline)")
    args = ap.parse_args(argv)

    doc = run(args.pdf, max_candidates=args.max_candidates,
              vision_fallback=args.vision_fallback)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / (Path(args.pdf).stem + ".json")
    out_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    n_tables = len(doc["tables"])
    n_cells = sum(len(t["cells"]) for t in doc["tables"])
    print(f"{args.pdf} -> {out_path}  ({n_tables} tables, {n_cells} cells)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
