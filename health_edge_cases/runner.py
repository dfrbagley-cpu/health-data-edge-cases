"""Dependency-free reference runner for deterministic healthcare reporting cases."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime
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

ACTUAL_SCHEMAS: dict[str, tuple[str, ...]] = {
    "actual_metrics.csv": ("period_id", "metric_id", "actual_value"),
    "actual_quality.csv": ("check_id", "actual_value"),
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
INTEGER_TEXT = re.compile(r"^[+-]?[0-9]+$")
UTC_TIMESTAMP_TEXT = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"
)
ISO_DATE_TEXT = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
ECMASCRIPT_TRIM_CHARS = (
    "\u0009\u000a\u000b\u000c\u000d\u0020\u00a0\u1680"
    "\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008"
    "\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"
)
MANIFEST_MINIMUM_LENGTHS = {
    "title": 8,
    "principle": 20,
    "naive_failure": 20,
    "expected_resolution": 20,
}
MAX_CSV_BYTES = 5 * 1024 * 1024
MAX_CSV_ROWS = 100_000
MAX_CSV_CELL_CHARS = 16_384
MAX_EXTERNAL_RESULT_ROWS = 1000
MAX_EXTERNAL_KEY_CHARS = 256
MAX_MANIFEST_BYTES = 64 * 1024


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


@dataclass(frozen=True)
class CaseValidationResult:
    """Structural validation outcome for one case without SQL execution."""

    case_id: str
    title: str
    input_file_count: int
    input_row_count: int
    expectation_count: int


def _validate_csv_quoting(lines: Iterable[str], path: Path) -> None:
    """Reject malformed quote placement that Python's CSV parser may coerce."""

    state = "unquoted"
    field_is_empty = True
    for line_number, line in enumerate(lines, start=1):
        for column_number, character in enumerate(line, start=1):
            if state == "quoted":
                if character == '"':
                    state = "after-quote"
                continue
            if state == "after-quote":
                if character == '"':
                    state = "quoted"
                elif character in {",", "\r", "\n"}:
                    state = "unquoted"
                    field_is_empty = True
                else:
                    raise ValueError(
                        f"{path} has an unexpected character after a closing "
                        f"quote at line {line_number}, column {column_number}"
                    )
                continue
            if character == '"':
                if not field_is_empty:
                    raise ValueError(
                        f"{path} has a quote inside an unquoted field at line "
                        f"{line_number}, column {column_number}"
                    )
                state = "quoted"
            elif character in {",", "\r", "\n"}:
                field_is_empty = True
            else:
                field_is_empty = False

    if state == "quoted":
        raise ValueError(f"{path} has an unclosed quoted field")


def _read_csv(
    path: Path,
    expected_columns: Sequence[str],
    *,
    allow_empty: bool = False,
) -> list[dict[str, str]]:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"Required file is missing: {path}")
    if path.stat().st_size > MAX_CSV_BYTES:
        raise ValueError(f"{path} exceeds the {MAX_CSV_BYTES}-byte CSV limit")

    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            _validate_csv_quoting(handle, path)
            handle.seek(0)
            reader = csv.DictReader(handle, strict=True)
            actual_columns = tuple(reader.fieldnames or ())
            if actual_columns != tuple(expected_columns):
                raise ValueError(
                    f"{path} has columns {actual_columns}; "
                    f"expected {tuple(expected_columns)}"
                )
            rows = []
            for line_number, row in enumerate(reader, start=2):
                if len(rows) >= MAX_CSV_ROWS:
                    raise ValueError(
                        f"{path} exceeds the {MAX_CSV_ROWS}-row CSV limit"
                    )
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
                oversized = [
                    column
                    for column in expected_columns
                    if len(row[column]) > MAX_CSV_CELL_CHARS
                ]
                if oversized:
                    raise ValueError(
                        f"{path} row {line_number} exceeds the "
                        f"{MAX_CSV_CELL_CHARS}-character cell limit for {oversized}"
                    )
                rows.append(row)
    except (csv.Error, UnicodeError) as exc:
        raise ValueError(f"{path} is not valid UTF-8 CSV: {exc}") from exc

    if not rows and not allow_empty:
        raise ValueError(f"{path} must contain at least one data row")
    return rows


def _load_manifest(case_dir: Path) -> dict[str, object]:
    path = case_dir / "case.json"
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"Required file is missing: {path}")
    if path.stat().st_size > MAX_MANIFEST_BYTES:
        raise ValueError(f"{path} exceeds the {MAX_MANIFEST_BYTES}-byte JSON limit")
    try:
        with path.open("r", encoding="utf-8") as handle:
            manifest = json.load(handle)
    except RecursionError as error:
        raise ValueError(f"{path} JSON nesting is too deep") from error

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


def _parse_utc_timestamp(value: str, path: Path, row_number: int, field: str) -> datetime:
    """Parse the suite's exact UTC timestamp representation."""

    if UTC_TIMESTAMP_TEXT.fullmatch(value) is None:
        raise ValueError(
            f"{path} row {row_number} {field} must use YYYY-MM-DDTHH:MM:SSZ"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise ValueError(
            f"{path} row {row_number} {field} is not a valid UTC timestamp"
        ) from error


def _parse_iso_date(value: str, path: Path, row_number: int, field: str) -> date:
    """Parse the suite's exact calendar-date representation."""

    if ISO_DATE_TEXT.fullmatch(value) is None:
        raise ValueError(
            f"{path} row {row_number} {field} must use YYYY-MM-DD"
        )
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(
            f"{path} row {row_number} {field} is not a valid calendar date"
        ) from error


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

    timestamp_fields = {
        "referrals.csv": ("referred_at",),
        "appointments.csv": ("scheduled_at",),
        "encounters.csv": ("occurred_at", "updated_at"),
    }
    for filename, fields in timestamp_fields.items():
        path = case_dir / filename
        for row_number, row in enumerate(rows_by_file[filename], start=2):
            for field in fields:
                _parse_utc_timestamp(row[field], path, row_number, field)

    periods_path = case_dir / "reporting_periods.csv"
    for row_number, row in enumerate(
        rows_by_file["reporting_periods.csv"], start=2
    ):
        start_date = _parse_iso_date(
            row["start_date"], periods_path, row_number, "start_date"
        )
        end_date = _parse_iso_date(
            row["end_date"], periods_path, row_number, "end_date"
        )
        if start_date > end_date:
            raise ValueError(
                f"{periods_path} row {row_number} start_date must not be after end_date"
            )

    referral_ids = {
        row["referral_id"] for row in rows_by_file["referrals.csv"]
    }
    appointment_ids = {
        row["appointment_id"] for row in rows_by_file["appointments.csv"]
    }

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
        if row["referral_id"] and row["referral_id"] not in referral_ids:
            raise ValueError(
                f"{case_dir / 'encounters.csv'} row {row_number} references "
                f"unknown referral_id {row['referral_id']!r}"
            )
        if row["appointment_id"] and row["appointment_id"] not in appointment_ids:
            raise ValueError(
                f"{case_dir / 'encounters.csv'} row {row_number} references "
                f"unknown appointment_id {row['appointment_id']!r}"
            )


def _load_case_contract(
    case_dir: Path,
) -> tuple[
    dict[str, object],
    tuple[Expectation, ...],
    tuple[Expectation, ...],
    dict[str, list[dict[str, str]]],
]:
    """Load and validate every declarative file belonging to one case."""

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
    return manifest, expected_metrics, expected_quality, rows_by_file


def validate_case(case_dir: Path) -> CaseValidationResult:
    """Validate one case contract without executing reference SQL."""

    manifest, expected_metrics, expected_quality, rows_by_file = _load_case_contract(
        case_dir
    )
    return CaseValidationResult(
        case_id=str(manifest["id"]),
        title=str(manifest["title"]),
        input_file_count=len(INPUT_SCHEMAS),
        input_row_count=sum(len(rows) for rows in rows_by_file.values()),
        expectation_count=len(expected_metrics) + len(expected_quality),
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


def _exact_integer_text(value: str, key: tuple[str, ...]) -> int:
    """Parse the external-results integer syntax without numeric coercion."""

    # Match JavaScript String.prototype.trim(), which the browser checker uses.
    # Python's default strip set differs for characters such as U+0085 and FEFF.
    text = value.strip(ECMASCRIPT_TRIM_CHARS)
    if INTEGER_TEXT.fullmatch(text) is None:
        raise ValueError(f"Actual value for {key} must be an exact integer")
    return int(Decimal(text))


def _integer_text(value: int | None) -> str | None:
    """Render arbitrary-size integers without Python's string-digit limit."""

    if value is None:
        return None
    return format(Decimal(value), "f")


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

    manifest, expected_metrics, expected_quality, rows_by_file = _load_case_contract(
        case_dir
    )

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



def _read_actual(
    path: Path, columns: Sequence[str], key_columns: Sequence[str]
) -> tuple[Expectation, ...]:
    # A header-only external result is a valid empty result set. Comparison
    # reports every expected key as missing (exit 1), which makes generated
    # integration workspaces useful before a pipeline has populated them.
    rows = _read_csv(path, columns, allow_empty=True)
    if len(rows) > MAX_EXTERNAL_RESULT_ROWS:
        raise ValueError(
            f"{path} exceeds the {MAX_EXTERNAL_RESULT_ROWS}-row external-result limit"
        )
    expectations: list[Expectation] = []
    seen: set[tuple[str, ...]] = set()

    for row_number, row in enumerate(rows, start=2):
        key = tuple(row[column] for column in key_columns)
        for column, value in zip(key_columns, key):
            if value.strip(ECMASCRIPT_TRIM_CHARS) == "":
                raise ValueError(
                    f"{path} row {row_number} has a blank {column}"
                )
            if len(value) > MAX_EXTERNAL_KEY_CHARS:
                raise ValueError(
                    f"{path} row {row_number} {column} exceeds the "
                    f"{MAX_EXTERNAL_KEY_CHARS}-character key limit"
                )
        if key in seen:
            raise ValueError(f"{path} contains duplicate actual key {key}")
        seen.add(key)
        expectations.append(
            Expectation(
                key=key,
                value=_exact_integer_text(row["actual_value"], key),
            )
        )

    return tuple(sorted(expectations))


def compare_external_results(
    case_id: str,
    metrics_path: Path,
    quality_path: Path,
    cases_dir: Path = DEFAULT_CASES_DIR,
) -> CaseResult:
    """Compare external pipeline CSV exports with a case's expected outputs.

    Does not execute reference SQL. Reads only the case expectations and the
    caller-provided actual metrics/quality files.
    """

    if not isinstance(case_id, str) or KEBAB_CASE.fullmatch(case_id) is None:
        raise ValueError("Case id must be lowercase kebab-case")
    case_dir = cases_dir / case_id
    if not case_dir.is_dir():
        raise ValueError(f"Unknown case id {case_id!r}; expected directory {case_dir}")
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
    actual_metrics = _read_actual(
        metrics_path,
        ACTUAL_SCHEMAS["actual_metrics.csv"],
        ("period_id", "metric_id"),
    )
    actual_quality = _read_actual(
        quality_path,
        ACTUAL_SCHEMAS["actual_quality.csv"],
        ("check_id",),
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


def format_compare_console(case: CaseResult) -> str:
    """Return a compact comparison summary for one case."""

    status = "PASS" if case.passed else "FAIL"
    lines = [
        f"{status}  {case.case_id}  ({case.expectation_count} expectations)"
    ]
    for mismatch in case.mismatches:
        key = json.dumps(mismatch.key, ensure_ascii=True, separators=(",", ":"))
        lines.append(
            f"      {mismatch.kind}: {key}; "
            f"expected={_integer_text(mismatch.expected) or 'null'}, "
            f"actual={_integer_text(mismatch.actual) or 'null'}"
        )
    return "\n".join(lines)


def _compare_json_payload(case: CaseResult) -> dict[str, object]:
    """Return precision-safe JSON data for one external comparison."""

    payload = asdict(case)
    for field in (
        "expected_metrics",
        "actual_metrics",
        "expected_quality",
        "actual_quality",
    ):
        for item in payload[field]:
            item["value"] = _integer_text(item["value"])
    for mismatch in payload["mismatches"]:
        mismatch["expected"] = _integer_text(mismatch["expected"])
        mismatch["actual"] = _integer_text(mismatch["actual"])
    payload["passed"] = case.passed
    payload["expectation_count"] = case.expectation_count
    return payload


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
    from . import __version__

    parser = argparse.ArgumentParser(
        description="Run deterministic healthcare reporting edge cases."
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"health-data-edge-cases {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser(
        "run",
        help="Execute reference SQL for every case (default).",
    )
    run_parser.add_argument(
        "--cases",
        type=Path,
        default=DEFAULT_CASES_DIR,
        help="Directory containing case folders.",
    )
    run_parser.add_argument(
        "--sql",
        type=Path,
        default=DEFAULT_SQL_PATH,
        help="Reference SQL implementation.",
    )
    run_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of console text.",
    )

    compare_parser = subparsers.add_parser(
        "compare",
        help="Compare external actual_metrics/actual_quality CSVs with one case.",
    )
    compare_parser.add_argument(
        "--case",
        required=True,
        help="Case id (directory name under --cases).",
    )
    compare_parser.add_argument(
        "--metrics",
        type=Path,
        required=True,
        help="Path to external actual_metrics.csv.",
    )
    compare_parser.add_argument(
        "--quality",
        type=Path,
        required=True,
        help="Path to external actual_quality.csv.",
    )
    compare_parser.add_argument(
        "--cases",
        type=Path,
        default=DEFAULT_CASES_DIR,
        help="Directory containing case folders.",
    )
    compare_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of console text.",
    )

    validate_parser = subparsers.add_parser(
        "validate-case",
        help="Validate one case directory without executing reference SQL.",
    )
    validate_parser.add_argument(
        "case_dir",
        type=Path,
        help="Path to one self-contained case directory.",
    )
    validate_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of console text.",
    )

    verify_parser = subparsers.add_parser(
        "verify",
        help="Verify external result CSVs for every version-bound suite case.",
    )
    verify_parser.add_argument(
        "--results",
        type=Path,
        required=True,
        help="Directory containing verification-manifest.json and case results.",
    )
    verify_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the versioned JSON result to standard output.",
    )
    verify_parser.add_argument(
        "--json-output",
        type=Path,
        help="Also write the versioned JSON result to this path.",
    )
    verify_parser.add_argument(
        "--junit-output",
        type=Path,
        help="Also write a JUnit XML result to this path.",
    )

    manifest_parser = subparsers.add_parser(
        "manifest",
        help="Print the exact identity manifest required by suite verification.",
    )

    scaffold_parser = subparsers.add_parser(
        "scaffold",
        help="Create a new synthetic integration and verification workspace.",
    )
    scaffold_parser.add_argument(
        "destination",
        type=Path,
        help="New workspace path; its existing parent must be a regular directory.",
    )

    # Preserve historical `python scripts/run_suite.py` / no-subcommand usage.
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        argv = ["run"]
    elif argv[0] not in {
        "run",
        "compare",
        "validate-case",
        "verify",
        "manifest",
        "scaffold",
        "-h",
        "--help",
        "--version",
    }:
        argv = ["run", *list(argv)]

    args = parser.parse_args(argv)

    if args.command == "compare":
        try:
            case = compare_external_results(
                case_id=args.case,
                metrics_path=args.metrics,
                quality_path=args.quality,
                cases_dir=args.cases,
            )
        except (OSError, ValueError) as error:
            print(f"ERROR  {error}", file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps(_compare_json_payload(case), indent=2))
        else:
            print(format_compare_console(case))
        return 0 if case.passed else 1

    if args.command == "validate-case":
        try:
            validation = validate_case(args.case_dir)
        except (OSError, ValueError) as error:
            print(f"ERROR  {error}", file=sys.stderr)
            return 2
        if args.json:
            print(
                json.dumps(
                    {
                        "schema_version": "1.0.0",
                        "valid": True,
                        **asdict(validation),
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        else:
            print(
                f"VALID  {validation.case_id}  "
                f"({validation.input_file_count} input files, "
                f"{validation.input_row_count} rows, "
                f"{validation.expectation_count} expectations)"
            )
        return 0

    if args.command == "manifest":
        from .verification import expected_verification_manifest

        try:
            manifest = expected_verification_manifest()
        except (OSError, ValueError) as error:
            print(f"ERROR  {error}", file=sys.stderr)
            return 2
        print(json.dumps(manifest, indent=2, sort_keys=True))
        return 0

    if args.command == "scaffold":
        from .scaffold import create_integration_workspace

        try:
            scaffold = create_integration_workspace(args.destination)
        except (OSError, ValueError) as error:
            print(f"ERROR  {error}", file=sys.stderr)
            return 2
        print(
            f"CREATED  {scaffold.destination}  "
            f"({scaffold.case_count} cases, "
            f"{scaffold.input_file_count} input files, "
            f"{scaffold.expectation_count} expectations)"
        )
        return 0

    if args.command == "verify":
        from .verification import (
            format_verification_console,
            render_verification_error_json,
            render_verification_error_junit,
            render_verification_json,
            render_verification_junit,
            require_distinct_report_paths,
            safe_error_message,
            verify_external_suite,
            write_text_report,
        )

        try:
            require_distinct_report_paths(args.json_output, args.junit_output)
        except (OSError, ValueError) as error:
            error_json = render_verification_error_json(error)
            if args.json:
                print(error_json, end="")
            else:
                print(f"ERROR  {safe_error_message(error)}", file=sys.stderr)
            return 2

        try:
            verification = verify_external_suite(args.results)
            json_text = render_verification_json(verification)
            if args.json_output is not None:
                write_text_report(args.json_output, json_text)
            if args.junit_output is not None:
                write_text_report(
                    args.junit_output,
                    render_verification_junit(verification),
                )
        except (OSError, ValueError) as error:
            error_json = render_verification_error_json(error)
            try:
                if args.json_output is not None:
                    write_text_report(args.json_output, error_json)
                if args.junit_output is not None:
                    write_text_report(
                        args.junit_output,
                        render_verification_error_junit(error),
                    )
            except (OSError, ValueError) as report_error:
                print(
                    f"ERROR  {safe_error_message(report_error)}",
                    file=sys.stderr,
                )
            if args.json:
                print(error_json, end="")
            else:
                print(f"ERROR  {safe_error_message(error)}", file=sys.stderr)
            return 2
        if args.json:
            print(json_text, end="")
        else:
            print(format_verification_console(verification))
        return 0 if verification.passed else 1

    try:
        result = run_suite(args.cases, args.sql)
    except (OSError, sqlite3.Error, ValueError) as error:
        print(f"ERROR  {error}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(_json_payload(result), indent=2))
    else:
        print(format_console(result))
    return 0 if result.passed else 1
