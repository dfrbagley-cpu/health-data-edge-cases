"""Dependency-free reference runner for deterministic healthcare reporting cases."""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES_DIR = PROJECT_ROOT / "cases"
DEFAULT_SQL_PATH = PROJECT_ROOT / "sql" / "reference.sql"

INPUT_SCHEMAS: dict[str, tuple[str, ...]] = {
    "programs.csv": ("program_id", "program_name"),
    "program_mappings.csv": ("program_id", "reporting_program"),
    "referrals.csv": ("referral_id", "patient_id", "program_id", "referred_at"),
    "appointments.csv": (
        "appointment_id",
        "patient_id",
        "program_id",
        "scheduled_at",
        "status",
    ),
    "encounters.csv": (
        "encounter_row_id",
        "source_event_id",
        "version",
        "patient_id",
        "program_id",
        "appointment_id",
        "referral_id",
        "occurred_at",
        "status",
        "updated_at",
    ),
    "reporting_periods.csv": (
        "period_id",
        "period_label",
        "start_date",
        "end_date",
    ),
}

EXPECTED_SCHEMAS: dict[str, tuple[str, ...]] = {
    "expected_metrics.csv": ("period_id", "metric_id", "expected_value"),
    "expected_quality.csv": ("check_id", "expected_value"),
}

REQUIRED_MANIFEST_FIELDS = {
    "schema_version",
    "id",
    "title",
    "principle",
    "naive_failure",
    "expected_resolution",
}


@dataclass(frozen=True, order=True)
class Expectation:
    """One expected or actual numeric result."""

    key: tuple[str, ...]
    value: int


@dataclass(frozen=True)
class Mismatch:
    """A missing, unexpected, or numerically incorrect result."""

    kind: str
    key: tuple[str, ...]
    expected: int | None
    actual: int | None


@dataclass(frozen=True)
class CaseResult:
    """Validation outcome for one edge case."""

    case_id: str
    title: str
    principle: str
    naive_failure: str
    expected_resolution: str
    expected_metrics: tuple[Expectation, ...]
    actual_metrics: tuple[Expectation, ...]
    expected_quality: tuple[Expectation, ...]
    actual_quality: tuple[Expectation, ...]
    mismatches: tuple[Mismatch, ...]

    @property
    def passed(self) -> bool:
        return not self.mismatches

    @property
    def expectation_count(self) -> int:
        return len(self.expected_metrics) + len(self.expected_quality)


@dataclass(frozen=True)
class SuiteResult:
    """Validation outcome for every discovered edge case."""

    cases: tuple[CaseResult, ...]

    @property
    def passed(self) -> bool:
        return bool(self.cases) and all(case.passed for case in self.cases)

    @property
    def passed_count(self) -> int:
        return sum(case.passed for case in self.cases)

    @property
    def expectation_count(self) -> int:
        return sum(case.expectation_count for case in self.cases)


def _read_csv(path: Path, expected_columns: Sequence[str]) -> list[dict[str, str]]:
    if not path.is_file():
        raise ValueError(f"Required file is missing: {path}")

    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        actual_columns = tuple(reader.fieldnames or ())
        if actual_columns != tuple(expected_columns):
            raise ValueError(
                f"{path} has columns {actual_columns}; expected {tuple(expected_columns)}"
            )
        rows = list(reader)

    if not rows:
        raise ValueError(f"{path} must contain at least one data row")
    return rows


def _load_manifest(case_dir: Path) -> dict[str, str]:
    path = case_dir / "case.json"
    if not path.is_file():
        raise ValueError(f"Required file is missing: {path}")
    with path.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)

    missing = REQUIRED_MANIFEST_FIELDS - manifest.keys()
    if missing:
        raise ValueError(f"{path} is missing fields: {sorted(missing)}")
    if manifest["schema_version"] != "1.0":
        raise ValueError(
            f"{path} uses unsupported schema_version {manifest['schema_version']!r}"
        )
    if manifest["id"] != case_dir.name:
        raise ValueError(
            f"{path} id {manifest['id']!r} must match directory {case_dir.name!r}"
        )
    return manifest


def _create_table(
    connection: sqlite3.Connection,
    table_name: str,
    columns: Sequence[str],
    rows: Iterable[dict[str, str]],
) -> None:
    quoted_columns = ", ".join(f'"{column}" TEXT' for column in columns)
    connection.execute(f'CREATE TABLE "{table_name}" ({quoted_columns})')

    placeholders = ", ".join("?" for _ in columns)
    insert_sql = f'INSERT INTO "{table_name}" VALUES ({placeholders})'
    connection.executemany(
        insert_sql,
        ([row[column] for column in columns] for row in rows),
    )


def _read_expected(
    path: Path, columns: Sequence[str], key_columns: Sequence[str]
) -> tuple[Expectation, ...]:
    rows = _read_csv(path, columns)
    expectations: list[Expectation] = []
    seen: set[tuple[str, ...]] = set()

    for row in rows:
        key = tuple(row[column] for column in key_columns)
        if key in seen:
            raise ValueError(f"{path} contains duplicate expectation key {key}")
        seen.add(key)
        try:
            value = int(row["expected_value"])
        except ValueError as exc:
            raise ValueError(
                f"{path} expected_value must be an integer for key {key}"
            ) from exc
        expectations.append(Expectation(key=key, value=value))

    return tuple(sorted(expectations))


def _query_expectations(
    connection: sqlite3.Connection,
    query: str,
    key_width: int,
) -> tuple[Expectation, ...]:
    rows = connection.execute(query).fetchall()
    return tuple(
        sorted(
            Expectation(
                key=tuple(str(value) for value in row[:key_width]),
                value=int(row[key_width]),
            )
            for row in rows
        )
    )


def _compare(
    expected: Sequence[Expectation], actual: Sequence[Expectation]
) -> tuple[Mismatch, ...]:
    expected_by_key = {item.key: item.value for item in expected}
    actual_by_key = {item.key: item.value for item in actual}
    mismatches: list[Mismatch] = []

    for key in sorted(expected_by_key.keys() - actual_by_key.keys()):
        mismatches.append(
            Mismatch(
                kind="missing",
                key=key,
                expected=expected_by_key[key],
                actual=None,
            )
        )
    for key in sorted(actual_by_key.keys() - expected_by_key.keys()):
        mismatches.append(
            Mismatch(
                kind="unexpected",
                key=key,
                expected=None,
                actual=actual_by_key[key],
            )
        )
    for key in sorted(expected_by_key.keys() & actual_by_key.keys()):
        if expected_by_key[key] != actual_by_key[key]:
            mismatches.append(
                Mismatch(
                    kind="value",
                    key=key,
                    expected=expected_by_key[key],
                    actual=actual_by_key[key],
                )
            )
    return tuple(mismatches)


def run_case(case_dir: Path, sql_path: Path = DEFAULT_SQL_PATH) -> CaseResult:
    """Load, execute, and validate one case directory."""

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

    with sqlite3.connect(":memory:") as connection:
        for filename, columns in INPUT_SCHEMAS.items():
            table_name = filename.removesuffix(".csv")
            _create_table(
                connection,
                table_name,
                columns,
                _read_csv(case_dir / filename, columns),
            )
        connection.executescript(sql_path.read_text(encoding="utf-8"))
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
        case_id=manifest["id"],
        title=manifest["title"],
        principle=manifest["principle"],
        naive_failure=manifest["naive_failure"],
        expected_resolution=manifest["expected_resolution"],
        expected_metrics=expected_metrics,
        actual_metrics=actual_metrics,
        expected_quality=expected_quality,
        actual_quality=actual_quality,
        mismatches=mismatches,
    )


def discover_cases(cases_dir: Path = DEFAULT_CASES_DIR) -> tuple[Path, ...]:
    """Return case directories in deterministic order."""

    if not cases_dir.is_dir():
        raise ValueError(f"Cases directory does not exist: {cases_dir}")
    cases = tuple(
        sorted(
            path
            for path in cases_dir.iterdir()
            if path.is_dir() and (path / "case.json").is_file()
        )
    )
    if not cases:
        raise ValueError(f"No cases found in {cases_dir}")
    return cases


def run_suite(
    cases_dir: Path = DEFAULT_CASES_DIR, sql_path: Path = DEFAULT_SQL_PATH
) -> SuiteResult:
    """Run every discovered case and return a structured result."""

    return SuiteResult(
        cases=tuple(run_case(case_dir, sql_path) for case_dir in discover_cases(cases_dir))
    )


def format_console(result: SuiteResult) -> str:
    """Return a compact, human-readable suite summary."""

    lines: list[str] = []
    for case in result.cases:
        status = "PASS" if case.passed else "FAIL"
        lines.append(
            f"{status}  {case.case_id}  ({case.expectation_count} expectations)"
        )
        for mismatch in case.mismatches:
            key = " / ".join(mismatch.key)
            lines.append(
                f"      {mismatch.kind}: {key}; "
                f"expected={mismatch.expected!r}, actual={mismatch.actual!r}"
            )

    suite_status = "PASS" if result.passed else "FAIL"
    lines.append(
        f"{suite_status}  suite: {result.passed_count}/{len(result.cases)} cases, "
        f"{result.expectation_count} expectations"
    )
    return "\n".join(lines)


def _json_payload(result: SuiteResult) -> dict[str, object]:
    return {
        "passed": result.passed,
        "passed_count": result.passed_count,
        "case_count": len(result.cases),
        "expectation_count": result.expectation_count,
        "cases": [
            {
                **asdict(case),
                "passed": case.passed,
                "expectation_count": case.expectation_count,
            }
            for case in result.cases
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run deterministic healthcare reporting edge cases."
    )
    parser.add_argument(
        "--cases",
        type=Path,
        default=DEFAULT_CASES_DIR,
        help="Directory containing case folders.",
    )
    parser.add_argument(
        "--sql",
        type=Path,
        default=DEFAULT_SQL_PATH,
        help="Reference SQL implementation.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of console text.",
    )
    args = parser.parse_args(argv)

    result = run_suite(args.cases, args.sql)
    if args.json:
        print(json.dumps(_json_payload(result), indent=2))
    else:
        print(format_console(result))
    return 0 if result.passed else 1
