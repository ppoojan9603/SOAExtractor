"""Recon CLI: reprint the FINDINGS tables from the PDFs (milestone M1).

    python -m soa.recon data/protocols/
    python -m soa.recon data/protocols/ --shading
"""
from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

import pdfplumber

from .ingest import ingest_page
from .marks import count_marks, count_x_only


def _pdf_paths(target: str) -> list[Path]:
    p = Path(target)
    return sorted(p.glob("*.pdf")) if p.is_dir() else [p]


def survey(path: Path) -> dict:
    """Per-document recon: page/rotation/char counts and per-page mark density."""
    rows = []
    with pdfplumber.open(str(path)) as pdf:
        n_pages = len(pdf.pages)
        for page in pdf.pages:
            text = page.extract_text() or ""
            rows.append(
                {
                    "page": page.page_number,
                    "rotation": page.rotation or 0,
                    "chars": len(text),
                    "marks": count_marks(text),
                    "x_only": count_x_only(text),
                }
            )
    total_chars = sum(r["chars"] for r in rows)
    return {
        "name": path.stem,
        "pages": n_pages,
        "chars": total_chars,
        "chars_per_page": total_chars // max(n_pages, 1),
        "rotated": [r["page"] for r in rows if r["rotation"]],
        "by_mark": sorted(rows, key=lambda r: -r["marks"])[:3],
        "by_x": sorted(rows, key=lambda r: -r["x_only"])[:3],
    }


def shading_census(path: Path, pages: list[int]) -> list[dict]:
    out = []
    with pdfplumber.open(str(path)) as pdf:
        for pno in pages:
            g = ingest_page(pdf.pages[pno - 1])
            out.append(
                {
                    "page": pno,
                    "rows": max(len(g.h_rules) - 1, 0),
                    "cols": max(len(g.v_rules) - 1, 0),
                    "fills": len(g.fills),
                    "grey": sum(f.grey for f in g.fills),
                    "strategy": g.strategy,
                    "scanned": g.scanned,
                }
            )
    return out


#: SoA grid pages, from FINDINGS §7. Test expectations only -- never used to
#: locate a table (CLAUDE.md non-negotiable #1).
SOA_GRID_PAGES = {
    "protocol1": [53, 54],
    "protocol5": [50],
    "protocol9": [26, 27, 28],
    "protocol12": [48],
    "protocol15": [25],
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="soa.recon")
    ap.add_argument("target", help="a PDF file or a directory of PDFs")
    ap.add_argument("--shading", action="store_true", help="grey-fill + grid census on SoA pages")
    args = ap.parse_args(argv)

    paths = _pdf_paths(args.target)
    if not paths:
        print(f"no PDFs at {args.target}", file=sys.stderr)
        return 1

    print(f"{'protocol':11} {'pages':>5} {'chars':>8} {'c/pg':>6}  {'rotated':<18} "
          f"{'top mark pages (page,n)':<34} top X pages")
    print("-" * 118)
    surveys = []
    for path in paths:
        s = survey(path)
        surveys.append(s)
        rot = ",".join(map(str, s["rotated"])) or "none"
        marks = " ".join(f"({r['page']},{r['marks']})" for r in s["by_mark"])
        xs = " ".join(f"({r['page']},{r['x_only']})" for r in s["by_x"])
        print(f"{s['name']:11} {s['pages']:>5} {s['chars']:>8} {s['chars_per_page']:>6}  "
              f"{rot:<18} {marks:<34} {xs}")

    if args.shading:
        print()
        print(f"{'protocol':11} {'page':>4} {'rows':>5} {'cols':>5} {'fills':>6} {'grey':>5}  strategy")
        print("-" * 60)
        for path in paths:
            for row in shading_census(path, SOA_GRID_PAGES.get(path.stem, [])):
                print(f"{path.stem:11} {row['page']:>4} {row['rows']:>5} {row['cols']:>5} "
                      f"{row['fills']:>6} {row['grey']:>5}  {row['strategy']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
