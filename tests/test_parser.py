#!/usr/bin/env python3
"""Offline parser tests for letak-worker-tesco against a saved page fixture.

    python tests/test_parser.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Local dev layout: repo_root/src/tesco.py. Docker test image layout: files
# are flattened to /app/tesco.py (ROOT == /app there), so try both.
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

import tesco  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "tesco.html"


def main() -> int:
    failures = 0

    def check(name: str, cond: bool, detail: str = "") -> None:
        nonlocal failures
        print(f"{'PASS' if cond else 'FAIL'}: {name}" + (f" {detail}" if not cond else ""))
        if not cond:
            failures += 1

    doc = FIXTURE.read_text(encoding="utf-8")
    leaflets = tesco.parse_leaflets(doc)
    types = sorted(lf["type"] for lf in leaflets)

    check("exactly 2 leaflets", len(leaflets) == 2, f"got {len(leaflets)}: {types}")
    check("HM leaflet parsed", "HM" in types, str(types))
    check("SM leaflet parsed", "SM" in types, str(types))

    check("all have pdfUrl + type + validity",
          all(lf["pdfUrl"] and lf["type"] and lf["validFrom"] and lf["validTo"]
              for lf in leaflets))

    check("pdf urls point to .pdf",
          all(lf["pdfUrl"].endswith(".pdf") for lf in leaflets),
          str([lf["pdfUrl"] for lf in leaflets]))

    # Validity truncated from the ISO datetime on the Leaflet entity itself
    # (Tesco does not expose a separate "site display window").
    check("validity parsed as YYYY-MM-DD",
          all(lf["validFrom"] == "2026-07-01" and lf["validTo"] == "2026-07-07"
              for lf in leaflets),
          str([(lf["validFrom"], lf["validTo"]) for lf in leaflets]))

    check("leaflet_key format", tesco.leaflet_key("HM", "2026-07-01", "2026-07-07")
          == "HM|2026-07-01|2026-07-07")

    print("\n" + ("All parser tests passed" if not failures else f"{failures} failed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
