"""Optional DuckDB execution path for the portable reference SQL."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

try:
    import duckdb
except ModuleNotFoundError as exc:  # pragma: no cover - exercised by CLI users
    raise SystemExit(
        "DuckDB is optional. Install it with "
        "`python -m pip install '.[duckdb]'`."
    ) from exc

from .runner import (
    DEFAULT_CASES_DIR,
    DEFAULT_SQL_PATH,
    EXPECTED_SCHEMAS,
    INPUT_SCHEMAS,
    CaseResult,
    SuiteResult,
    _compare,
    _create_table,
    _load_manifest,
    _query_expectations,
    _read_csv,
    _read_expected,
    _validate_input_contract,
    discover_cases,
    format_console,
)


def run_duckdb_case(
    case_dir: Path, sql_path: Path = DEFAULT_SQL_PATH
) -> CaseResult:
    """Execute and validate one case against an in-memory DuckDB database."""

    manifest = _load_manifest(case_dir)
    expected_metrics = _read_expected(
        case_dir / "expected_metrics.csv",
        EXPECTED_SCHEMAS["expected_metrics.csv"],
        ("period_id", "metric_id"),
    )
    expected_quality = _read_expected(
        case_dir / "expected_quality.csv",
        EXPECTED_SCHEMAS["expected_quality.csv"],
        ("check_id",),
    )
    rows_by_file = {
        filename: _read_csv(case_dir / filename, columns)
        for filename, columns in INPUT_SCHEMAS.items()
    }
    _validate_input_contract(case_dir, rows_by_file)

    with duckdb.connect(":memory:") as connection:
        for filename, columns in INPUT_SCHEMAS.items():
            table_name = filename.removesuffix(".csv")
            _create_table(
                connection,
                table_name,
                columns,
                rows_by_file[filename],
            )
        connection.execute(sql_path.read_text(encoding="utf-8"))
        actual_metrics = _query_expectations(
            connection,
            "SELECT period_id, metric_id, actual_value FROM actual_metrics",
            key_width=2,
        )
        actual_quality = _query_expectations(
            connection,
            "SELECT check_id, actual_value FROM actual_quality",
            key_width=1,
        )

    mismatches = _compare(expected_metrics, actual_metrics) + _compare(
        expected_quality, actual_quality
    )
    return CaseResult(
        case_id=str(manifest["id"]),
        title=str(manifest["title"]),
        principle=str(manifest["principle"]),
        naive_failure=str(manifest["naive_failure"]),
        expected_resolution=str(manifest["expected_resolution"]),
        expected_metrics=expected_metrics,
        actual_metrics=actual_metrics,
        expected_quality=expected_quality,
        actual_quality=actual_quality,
        mismatches=mismatches,
    )


def run_duckdb_suite(
    cases_dir: Path = DEFAULT_CASES_DIR, sql_path: Path = DEFAULT_SQL_PATH
) -> SuiteResult:
    """Run every case against DuckDB."""

    return SuiteResult(
        cases=tuple(
            run_duckdb_case(case_dir, sql_path)
            for case_dir in discover_cases(cases_dir)
        )
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the portable SQL edge cases against DuckDB."
    )
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_DIR)
    parser.add_argument("--sql", type=Path, default=DEFAULT_SQL_PATH)
    args = parser.parse_args(argv)

    result = run_duckdb_suite(args.cases, args.sql)
    print(f"DuckDB {duckdb.__version__}")
    print(format_console(result))
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
