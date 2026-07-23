#!/usr/bin/env python3
"""Build or verify the committed deterministic HTML report."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from health_edge_cases.report import render_report
from health_edge_cases.runner import PROJECT_ROOT, run_suite


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "docs" / "index.html",
        help="Report path.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if the committed report differs from a fresh render.",
    )
    args = parser.parse_args()

    result = run_suite()
    rendered = render_report(result)

    if args.check:
        if not args.output.is_file():
            print(f"FAIL  report is missing: {args.output}")
            return 1
        if args.output.read_text(encoding="utf-8") != rendered:
            print(f"FAIL  report is stale: {args.output}")
            return 1
        print(f"PASS  report is current: {args.output}")
        return 0 if result.passed else 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    print(f"Wrote {args.output}")
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
