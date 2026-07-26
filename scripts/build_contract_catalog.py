#!/usr/bin/env python3
"""Build or verify the canonical public conformance-contract catalog."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from health_edge_cases.contracts import (
    build_catalog,
    render_catalog,
    validate_catalog,
)
from health_edge_cases.runner import PROJECT_ROOT


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "docs" / "contracts" / "catalog-v1.json",
        help="Catalog output path.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if the committed catalog differs from a fresh build.",
    )
    args = parser.parse_args()

    catalog = build_catalog()
    rendered = render_catalog(catalog)
    if args.check:
        if not args.output.is_file():
            print(f"FAIL  contract catalog is missing: {args.output}")
            return 1
        try:
            committed = json.loads(args.output.read_text(encoding="utf-8"))
            validate_catalog(committed)
        except (json.JSONDecodeError, ValueError) as error:
            print(f"FAIL  committed contract catalog is invalid: {error}")
            return 1
        if args.output.read_text(encoding="utf-8") != rendered:
            print(f"FAIL  contract catalog is stale: {args.output}")
            return 1
        print(
            "PASS  contract catalog is current: "
            f"{args.output} ({catalog['catalog_digest']})"
        )
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    print(f"Wrote {args.output} ({catalog['catalog_digest']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
