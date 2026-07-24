"""Dependency-free reference runner for deterministic healthcare reporting cases."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DATA_DIR = Path(__file__).resolve().parent / "data"
SOURCE_CHECKOUT = (PROJECT_ROOT / "pyproject.toml").is_file()
DEFAULT_CASES_DIR = (
    PROJECT_ROOT / "cases"
    if SOURCE_CHECKOUT and (PROJECT_ROOT / "cases").is_dir()
    else PACKAGE_DATA_DIR / "cases"
)
DEFAULT_SQL_PATH = (
    PROJECT_ROOT / "sql" / "reference.sql"
    if SOURCE_CHECKOUT and (PROJECT_ROOT / "sql" / "reference.sql").is_file()
    else PACKAGE_DATA_DIR / "sql" / "reference.sql"
)

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

MANIFEST_FIELDS = {
    "schema_version",
    "id",
    "title",
    "principle",
    "naive_failure",
    "expected_resolution",
    "synthetic_data_only",
    "tags",
}
KEBAB_CASE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MANIFEST_MINIMUM_LENGTHS = {
    "title": 8,
    "principle": 20,
    "naive_failure": 20,
    "expected_resolution": 20,
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
        rows = []
        for line_number, row in enumerate(reader, start=2):
            if None in row:
                raise ValueError(
                    f"{path} row {line_number} has more values than its header"
                )
            missing = [
                column for column in expected_columns if row[column] is None
            ]
            if missing:
                raise ValueError(
                    f"{path} row {line_number} is missing values for {missing}"
                )
            rows.append(row)

    if not rows:
        raise ValueError(f"{path} must contain at least one data row")
    return rows


def _load_manifest(case_dir: Path) -> dict[str, object]:
    path = case_dir / "case.json"
    if not path.is_file():
        raise ValueError(f"Required file is missing: {path}")
    with path.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)

    if not isinstance(manifest, dict):
        raise ValueError(f"{path} must contain a JSON object")
    actual_fields = set(manifest)
    missing = MANIFEST_FIELDS - actual_fields
    unexpected = actual_fields - MANIFEST_FIELDS
    if missing or unexpected:
        details = []
        if missing:
            details.append(f"missing fields {sorted(missing)}")
        if unexpected:
            details.append(f"unexpected fields {sorted(unexpected)}")
        raise ValueError(f"{path} has {' and '.join(details)}")
    if manifest["schema_version"] != "1.0":
        raise ValueError(
            f"{path} uses unsupported schema_version {manifest['schema_version']!r}"
        )
    if manifest["id"] != case_dir.name:
        raise ValueError(
            f"{path} id {manifest['id']!r} must match directory {case_dir.name!r}"
        )
    if not isinstance(manifest["id"], str) or not KEBAB_CASE.fullmatch(
        manifest["id"]
    ):
        raise ValueError(f"{path} id must be lowercase kebab-case")
    for field, minimum_length in MANIFEST_MINIMUM_LENGTHS.items():
        value = manifest[field]
        if not isinstance(value, str) or len(value.strip()) < minimum_length:
            raise ValueError(
                f"{path} {field} must contain at least {minimum_length} characters"
            )
    if manifest["synthetic_data_only"] is not True:
        raise ValueError(f"{path} synthetic_data_only must be true")
    tags = manifest["tags"]
    if (
        not isinstance(tags, list)
        or not tags
        or any(not isinstance(tag, str) or not KEBAB_CASE.fullmatch(tag) for tag in tags)
        or len(tags) != len(set(tags))
    ):
        raise ValueError(
            f"{path} tags must be a non-empty unique list of lowercase kebab-case values"
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


def _validate_unique_key(
    case_dir: Path,
    rows_by_file: dict[str, list[dict[str, str]]],
    filename: str,
    key: str,
) -> None:
    seen: set[str] = set()
    for row_number, row in enumerate(rows_by_file[filename], start=2):
        value = row[key]
        if value == "":
            raise ValueError(
                f"{case_dir / filename} row {row_number} has a blank {key}"
            )
        if value in seen:
            raise ValueError(
                f"{case_dir / filename} contains duplicate {key} {value!r}"
            )
        seen.add(value)


def _validate_input_contract(
    case_dir: Path,
    rows_by_file: dict[str, list[dict[str, str]]],
) -> None:
    unique_keys = {
        "programs.csv": "program_id",
        "program_mappings.csv": "program_id",
        "referrals.csv": "referral_id",
        "appointments.csv": "appointment_id",
        "encounters.csv": "encounter_row_id",
        "reporting_periods.csv": "period_id",
    }
    for filename, key in unique_keys.items():
        _validate_unique_key(case_dir, rows_by_file, filename, key)

    program_ids = {
        row["program_id"] for row in rows_by_file["programs.csv"]
    }
    for filename in (
        "program_mappings.csv",
        "referrals.csv",
        "appointments.csv",
        "encounters.csv",
    ):
        for row_number, row in enumerate(rows_by_file[filename], start=2):
            if row["program_id"] not in program_ids:
                raise ValueError(
                    f"{case_dir / filename} row {row_number} references "
                    f"unknown program_id {row['program_id']!r}"
                )

    for row_number, row in enumerate(rows_by_file["encounters.csv"], start=2):
        try:
            version = int(row["version"])
        except ValueError as exc:
            raise ValueError(
                f"{case_dir / 'encounters.csv'} row {row_number} version "
                "must be a positive integer"
            ) from exc
        if str(version) != row["version"] or version < 1:
            raise ValueError(
                f"{case_dir / 'encounters.csv'} row {row_number} version "
                "must be a positive integer"
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
    expectations: list[Expectation] = []
    seen: set[tuple[str, ...]] = set()
    for row in rows:
        if any(value is None for value in row[:key_width]):
            raise ValueError(f"Actual result contains a null key: {row[:key_width]!r}")
        key = tuple(str(value) for value in row[:key_width])
        if key in seen:
            raise ValueError(f"Actual result contains duplicate key {key}")
        seen.add(key)
        expectations.append(
            Expectation(
                key=key,
                value=_exact_integer(row[key_width], key),
            )
        )
    return tuple(sorted(expectations))


def _exact_integer(value: object, key: tuple[str, ...]) -> int:
    if isinstance(value, bool):
        raise ValueError(f"Actual value for {key} must be an exact integer")
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(
            f"Actual value for {key} must be an exact integer"
        ) from exc
    if not decimal_value.is_finite() or decimal_value != decimal_value.to_integral_value():
        raise ValueError(f"Actual value for {key} must be an exact integer")
    return int(decimal_value)


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

    rows_by_file = {
        filename: _read_csv(case_dir / filename, columns)
        for filename, columns in INPUT_SCHEMAS.items()
    }
    _validate_input_contract(case_dir, rows_by_file)

    with sqlite3.connect(":memory:") as connection:
        for filename, columns in INPUT_SCHEMAS.items():
            table_name = filename.removesuffix(".csv")
            _create_table(
                connection,
                table_name,
                columns,
                rows_by_file[filename],
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


def discover_cases(cases_dir: Path = DEFAULT_CASES_DIR) -> tuple[Path, ...]:
    """Return case directories in deterministic order."""

    if not cases_dir.is_dir():
        raise ValueError(f"Cases directory does not exist: {cases_dir}")
    candidate_directories = tuple(
        sorted(
            path
            for path in cases_dir.iterdir()
            if path.is_dir() and not path.name.startswith((".", "_"))
        )
    )
    missing_manifests = [
        path.name
        for path in candidate_directories
        if not (path / "case.json").is_file()
    ]
    if missing_manifests:
        raise ValueError(
            f"Case directories are missing case.json: {missing_manifests}"
        )
    cases = candidate_directories
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
