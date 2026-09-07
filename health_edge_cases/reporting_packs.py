"""Separate, bundled reporting semantics packs; the original catalog is unchanged."""
from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

PACK_ROOT = Path(__file__).with_name("packs")
PACK_IDS = ("referral-chronology", "historical-cutoff", "effective-dated-mappings")


def run_pack(pack_id: str, engine: str = "sqlite", naive: bool = False) -> dict:
    """Execute only a known bundled pack, never caller-provided SQL or paths."""
    if pack_id not in PACK_IDS:
        raise ValueError("Unknown reporting pack")
    if engine not in {"sqlite", "duckdb"}:
        raise ValueError("Use sqlite or duckdb")
    root = PACK_ROOT / pack_id
    if engine == "duckdb":
        import duckdb
        connection = duckdb.connect(":memory:")
    else:
        connection = sqlite3.connect(":memory:")
    try:
        for path in sorted(root.glob("input_*.csv")):
            with path.open(newline="", encoding="utf-8") as stream:
                reader = csv.reader(stream)
                headers = next(reader)
                # All identifiers and SQL are shipped with this package.
                table = path.stem.removeprefix("input_")
                connection.execute(f'CREATE TABLE "{table}" (' + ",".join(f'"{h}" TEXT' for h in headers) + ")")
                rows = list(reader)
                if rows:
                    connection.executemany(f'INSERT INTO "{table}" VALUES (' + ",".join("?" for _ in headers) + ")", rows)
        query = (root / ("naive.sql" if naive else "reference.sql")).read_text(encoding="utf-8")
        actual = dict(connection.execute(query).fetchall())
        with (root / "expected.csv").open(newline="", encoding="utf-8") as stream:
            expected = {row["check"]: int(row["value"]) for row in csv.DictReader(stream)}
        mismatches = [{"check": key, "expected": expected.get(key), "actual": actual.get(key)}
                      for key in sorted(expected.keys() | actual.keys()) if expected.get(key) != actual.get(key)]
        return {"pack": pack_id, "engine": engine, "passed": not mismatches,
                "expectations": len(expected), "actual": actual, "mismatches": mismatches}
    finally:
        connection.close()


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Run independently authored synthetic reporting packs.")
    parser.add_argument("--engine", choices=["sqlite", "duckdb"], default="sqlite")
    parser.add_argument("--naive", action="store_true", help="Demonstrate deliberately wrong logic; expected exit 1.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        results = [run_pack(pack, args.engine, args.naive) for pack in PACK_IDS]
    except (OSError, ValueError, ImportError) as error:
        parser.exit(2, f"ERROR: {error}\n")
    if args.json:
        print(json.dumps({"schema_version": "1.0.0", "passed": all(r["passed"] for r in results), "packs": results}, indent=2))
    else:
        for result in results:
            print(f"{'PASS' if result['passed'] else 'FAIL'}  {result['pack']} ({result['expectations']} expectations)")
            for mismatch in result["mismatches"]:
                print(f"  {mismatch['check']}: expected={mismatch['expected']}, actual={mismatch['actual']}")
    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
