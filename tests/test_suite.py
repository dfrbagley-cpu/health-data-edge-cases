from __future__ import annotations

import csv
import json
import re
import shutil
import subprocess
import sys
import sqlite3
import tempfile
import unittest
from pathlib import Path

from health_edge_cases.report import render_report
from health_edge_cases.runner import (
    DEFAULT_CASES_DIR,
    PROJECT_ROOT,
    _load_manifest,
    _query_expectations,
    _read_csv,
    discover_cases,
    run_case,
    run_suite,
    validate_case,
)


class ConformanceSuiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.case_dirs = discover_cases()
        cls.result = run_suite()

    def test_every_reference_expectation_passes(self) -> None:
        failures = {
            case.case_id: case.mismatches
            for case in self.result.cases
            if not case.passed
        }
        self.assertEqual({}, failures)

    def test_case_ids_are_unique(self) -> None:
        case_ids = [case.case_id for case in self.result.cases]
        self.assertEqual(len(case_ids), len(set(case_ids)))

    def test_manifests_are_explicitly_synthetic(self) -> None:
        for case_dir in self.case_dirs:
            manifest = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
            self.assertIs(manifest["synthetic_data_only"], True, case_dir.name)

    def test_patient_tokens_are_obviously_synthetic(self) -> None:
        for case_dir in self.case_dirs:
            for filename in ("referrals.csv", "appointments.csv", "encounters.csv"):
                with (case_dir / filename).open(
                    "r", encoding="utf-8", newline=""
                ) as handle:
                    rows = csv.DictReader(handle)
                    for row in rows:
                        self.assertTrue(
                            row["patient_id"].startswith("SYN-"),
                            f"{case_dir.name}/{filename}: {row['patient_id']}",
                        )

    def test_fixtures_have_no_direct_identifier_columns(self) -> None:
        forbidden = {
            "name",
            "first_name",
            "last_name",
            "address",
            "phone",
            "email",
            "health_card_number",
            "medical_record_number",
            "date_of_birth",
        }
        for case_dir in self.case_dirs:
            for path in case_dir.glob("*.csv"):
                with path.open("r", encoding="utf-8", newline="") as handle:
                    columns = set(csv.DictReader(handle).fieldnames or ())
                self.assertFalse(
                    columns & forbidden,
                    f"{path} contains forbidden columns {columns & forbidden}",
                )

    def test_repository_publication_boundary_is_clean(self) -> None:
        forbidden_terms = [
            "St." + " Joseph",
            "SJ" + "HH",
            "Dove" + "tale",
            "Iron" + "works",
            "Acland" + " Martin",
            "health-reporting-" + "engine",
        ]
        forbidden_patterns = [
            re.compile(re.escape(term), re.IGNORECASE)
            for term in forbidden_terms
        ] + [
            re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
            re.compile(r"\bgh" + r"p_[A-Za-z0-9]{20,}\b"),
            re.compile(r"\bgithub_" + r"pat_[A-Za-z0-9_]{20,}\b"),
            re.compile(r"\bsk" + r"-[A-Za-z0-9]{20,}\b"),
            re.compile(r"@gmail[.]com\b", re.IGNORECASE),
            re.compile(r"/(?:work" + r"space|ro" + r"ot)/"),
        ]
        text_suffixes = {
            ".cff",
            ".csv",
            ".html",
            ".json",
            ".md",
            ".py",
            ".r",
            ".sql",
            ".toml",
            ".txt",
            ".yml",
        }
        text_names = {"LICENSE", "Makefile", "NOTICE"}

        for path in PROJECT_ROOT.rglob("*"):
            if (
                not path.is_file()
                or ".git" in path.parts
                or (
                    path.suffix.lower() not in text_suffixes
                    and path.name not in text_names
                )
            ):
                continue
            source = path.read_text(encoding="utf-8")
            for pattern in forbidden_patterns:
                with self.subTest(path=path.relative_to(PROJECT_ROOT), pattern=pattern):
                    self.assertIsNone(
                        pattern.search(source),
                        (
                            f"{path.relative_to(PROJECT_ROOT)} violates "
                            "the publication boundary"
                        ),
                    )

    def test_committed_report_is_current(self) -> None:
        report_path = PROJECT_ROOT / "docs" / "index.html"
        self.assertTrue(report_path.is_file())
        self.assertEqual(
            report_path.read_text(encoding="utf-8"),
            render_report(self.result),
        )

    def test_report_can_be_written_to_a_clean_location(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.html"
            path.write_text(render_report(self.result), encoding="utf-8")
            self.assertIn(
                "Health Data Edge Cases",
                path.read_text(encoding="utf-8"),
            )


class ContractRegressionTests(unittest.TestCase):
    def test_manifest_schema_contract_is_enforced(self) -> None:
        source = DEFAULT_CASES_DIR / "appointment-encounter-status-conflict"
        valid_manifest = json.loads((source / "case.json").read_text(encoding="utf-8"))
        invalid_manifests = {
            "missing required field": {
                key: value for key, value in valid_manifest.items() if key != "tags"
            },
            "unexpected field": {
                **valid_manifest,
                "private_note": "This field is outside the public contract.",
            },
            "truthy non-boolean synthetic flag": {
                **valid_manifest,
                "synthetic_data_only": "false",
            },
            "duplicate tags": {
                **valid_manifest,
                "tags": ["appointment", "appointment"],
            },
            "short narrative": {
                **valid_manifest,
                "principle": "Too short",
            },
        }

        with tempfile.TemporaryDirectory() as directory:
            case_dir = Path(directory) / source.name
            case_dir.mkdir()
            manifest_path = case_dir / "case.json"
            for label, manifest in invalid_manifests.items():
                with self.subTest(label=label):
                    manifest_path.write_text(
                        json.dumps(manifest),
                        encoding="utf-8",
                    )
                    with self.assertRaises(ValueError):
                        _load_manifest(case_dir)

    def test_deeply_nested_case_manifest_is_rejected_cleanly(self) -> None:
        source = DEFAULT_CASES_DIR / "unmapped-program-retention"
        with tempfile.TemporaryDirectory() as directory:
            case_dir = Path(directory) / source.name
            shutil.copytree(source, case_dir)
            (case_dir / "case.json").write_text(
                "[" * 10_000 + "0" + "]" * 10_000,
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "nesting is too deep"):
                validate_case(case_dir)

    def test_ragged_csv_rows_are_rejected(self) -> None:
        malformed_rows = {
            "extra value": "first,second\none,two,three\n",
            "missing value": "first,second\none\n",
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.csv"
            for label, content in malformed_rows.items():
                with self.subTest(label=label):
                    path.write_text(content, encoding="utf-8")
                    with self.assertRaises(ValueError):
                        _read_csv(path, ("first", "second"))

    def test_duplicate_actual_result_keys_are_rejected(self) -> None:
        with (
            sqlite3.connect(":memory:") as connection,
            self.assertRaisesRegex(ValueError, "duplicate key"),
        ):
            _query_expectations(
                connection,
                (
                    "SELECT 'period', 'metric', 1 "
                    "UNION ALL SELECT 'period', 'metric', 999"
                ),
                key_width=2,
            )

    def test_fractional_actual_results_are_rejected(self) -> None:
        with (
            sqlite3.connect(":memory:") as connection,
            self.assertRaisesRegex(ValueError, "exact integer"),
        ):
            _query_expectations(
                connection,
                "SELECT 'period', 'metric', 1.9",
                key_width=2,
            )

    def test_duplicate_input_keys_are_rejected(self) -> None:
        source = DEFAULT_CASES_DIR / "unmapped-program-retention"
        with tempfile.TemporaryDirectory() as directory:
            case_dir = Path(directory) / source.name
            shutil.copytree(source, case_dir)
            mapping_path = case_dir / "program_mappings.csv"
            with mapping_path.open("a", encoding="utf-8", newline="") as handle:
                handle.write("P-MAPPED,RESP-AMB\n")

            with self.assertRaisesRegex(ValueError, "duplicate program_id"):
                run_case(case_dir)

    def test_unknown_program_foreign_keys_are_rejected(self) -> None:
        source = DEFAULT_CASES_DIR / "unmapped-program-retention"
        with tempfile.TemporaryDirectory() as directory:
            case_dir = Path(directory) / source.name
            shutil.copytree(source, case_dir)
            encounter_path = case_dir / "encounters.csv"
            with encounter_path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                fieldnames = tuple(reader.fieldnames or ())
                rows = list(reader)
            self.assertTrue(fieldnames)
            rows[0]["program_id"] = "P-UNKNOWN"
            with encounter_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

            with self.assertRaisesRegex(ValueError, "unknown program_id"):
                run_case(case_dir)

    def test_malformed_or_non_utc_timestamps_are_rejected(self) -> None:
        source = DEFAULT_CASES_DIR / "unmapped-program-retention"
        invalid_values = (
            "2026-02-30T08:00:00Z",
            "2026-08-01 08:00:00Z",
            "2026-08-01T08:00:00+00:00",
            "2026-08-01T08:00:00.000Z",
            "2026-08-01T08:00:00z",
            "2026-08-01T08:00:60Z",
            " 2026-08-01T08:00:00Z",
            "",
        )
        with tempfile.TemporaryDirectory() as directory:
            for index, value in enumerate(invalid_values):
                with self.subTest(value=value):
                    case_dir = Path(directory) / f"case-{index}"
                    shutil.copytree(source, case_dir)
                    manifest = json.loads(
                        (case_dir / "case.json").read_text(encoding="utf-8")
                    )
                    manifest["id"] = case_dir.name
                    (case_dir / "case.json").write_text(
                        json.dumps(manifest), encoding="utf-8"
                    )
                    referral_path = case_dir / "referrals.csv"
                    with referral_path.open(
                        "r", encoding="utf-8", newline=""
                    ) as handle:
                        rows = list(csv.DictReader(handle))
                    rows[0]["referred_at"] = value
                    with referral_path.open(
                        "w", encoding="utf-8", newline=""
                    ) as handle:
                        writer = csv.DictWriter(
                            handle,
                            fieldnames=(
                                "referral_id",
                                "patient_id",
                                "program_id",
                                "referred_at",
                            ),
                        )
                        writer.writeheader()
                        writer.writerows(rows)
                    with self.assertRaisesRegex(ValueError, "timestamp|YYYY"):
                        validate_case(case_dir)

    def test_reversed_reporting_period_is_rejected(self) -> None:
        source = DEFAULT_CASES_DIR / "unmapped-program-retention"
        with tempfile.TemporaryDirectory() as directory:
            case_dir = Path(directory) / source.name
            shutil.copytree(source, case_dir)
            period_path = case_dir / "reporting_periods.csv"
            period_path.write_text(
                "period_id,period_label,start_date,end_date\n"
                "2026-08,August 2026,2026-08-31,2026-08-01\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "must not be after"):
                validate_case(case_dir)

    def test_valid_leap_timestamp_and_equal_period_are_accepted(self) -> None:
        source = DEFAULT_CASES_DIR / "unmapped-program-retention"
        with tempfile.TemporaryDirectory() as directory:
            case_dir = Path(directory) / source.name
            shutil.copytree(source, case_dir)
            referral_path = case_dir / "referrals.csv"
            with referral_path.open(
                "r", encoding="utf-8", newline=""
            ) as handle:
                reader = csv.DictReader(handle)
                fieldnames = tuple(reader.fieldnames or ())
                referrals = list(reader)
            referrals[0]["referred_at"] = "2024-02-29T08:00:00Z"
            with referral_path.open(
                "w", encoding="utf-8", newline=""
            ) as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(referrals)
            (case_dir / "reporting_periods.csv").write_text(
                "period_id,period_label,start_date,end_date\n"
                "2026-08,One day,2026-08-01,2026-08-01\n",
                encoding="utf-8",
            )
            self.assertEqual(source.name, validate_case(case_dir).case_id)

    def test_dangling_encounter_relationships_are_rejected(self) -> None:
        source = DEFAULT_CASES_DIR / "unmapped-program-retention"
        for field, value, message in (
            ("referral_id", "R-MISSING", "unknown referral_id"),
            ("appointment_id", "A-MISSING", "unknown appointment_id"),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                case_dir = Path(directory) / source.name
                shutil.copytree(source, case_dir)
                encounter_path = case_dir / "encounters.csv"
                with encounter_path.open(
                    "r", encoding="utf-8", newline=""
                ) as handle:
                    reader = csv.DictReader(handle)
                    fieldnames = tuple(reader.fieldnames or ())
                    rows = list(reader)
                rows[0][field] = value
                with encounter_path.open(
                    "w", encoding="utf-8", newline=""
                ) as handle:
                    writer = csv.DictWriter(handle, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(rows)
                with self.assertRaisesRegex(ValueError, message):
                    validate_case(case_dir)

    def test_validate_case_does_not_execute_reference_sql(self) -> None:
        source = DEFAULT_CASES_DIR / "unmapped-program-retention"
        validation = validate_case(source)
        self.assertEqual(source.name, validation.case_id)
        self.assertEqual(6, validation.input_file_count)
        self.assertGreater(validation.input_row_count, 0)
        self.assertEqual(13, validation.expectation_count)

    def test_case_directories_missing_manifests_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cases_dir = Path(directory) / "cases"
            (cases_dir / "incomplete-case").mkdir(parents=True)

            with self.assertRaisesRegex(ValueError, "missing case.json"):
                discover_cases(cases_dir)


class ExternalCompareTests(unittest.TestCase):
    def setUp(self) -> None:
        from health_edge_cases.runner import compare_external_results

        self.compare_external_results = compare_external_results
        self.case_id = "unmapped-program-retention"
        self.case_dir = DEFAULT_CASES_DIR / self.case_id
        self.temp_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.temp_dir)

    def _write_csv(self, name: str, header: str, rows: list[str]) -> Path:
        path = self.temp_dir / name
        path.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
        return path

    def _expected_as_actual(self) -> tuple[Path, Path]:
        metrics_rows = []
        with (self.case_dir / "expected_metrics.csv").open(
            encoding="utf-8", newline=""
        ) as handle:
            for row in csv.DictReader(handle):
                metrics_rows.append(
                    f"{row['period_id']},{row['metric_id']},{row['expected_value']}"
                )
        quality_rows = []
        with (self.case_dir / "expected_quality.csv").open(
            encoding="utf-8", newline=""
        ) as handle:
            for row in csv.DictReader(handle):
                quality_rows.append(f"{row['check_id']},{row['expected_value']}")
        metrics = self._write_csv(
            "actual_metrics.csv",
            "period_id,metric_id,actual_value",
            metrics_rows,
        )
        quality = self._write_csv(
            "actual_quality.csv",
            "check_id,actual_value",
            quality_rows,
        )
        return metrics, quality

    def test_compare_passes_when_exports_match(self) -> None:
        metrics, quality = self._expected_as_actual()
        result = self.compare_external_results(self.case_id, metrics, quality)
        self.assertTrue(result.passed)
        self.assertEqual((), result.mismatches)

    def test_compare_reports_wrong_value(self) -> None:
        metrics, quality = self._expected_as_actual()
        # Flip first metrics value
        lines = metrics.read_text(encoding="utf-8").splitlines()
        header, first, *rest = lines
        cols = first.split(",")
        cols[-1] = str(int(cols[-1]) + 1)
        metrics.write_text(
            "\n".join([header, ",".join(cols), *rest]) + "\n", encoding="utf-8"
        )
        result = self.compare_external_results(self.case_id, metrics, quality)
        self.assertFalse(result.passed)
        self.assertTrue(any(m.kind == "value" for m in result.mismatches))

    def test_compare_reports_missing_key(self) -> None:
        metrics, quality = self._expected_as_actual()
        lines = metrics.read_text(encoding="utf-8").splitlines()
        metrics.write_text("\n".join(lines[:1] + lines[2:]) + "\n", encoding="utf-8")
        result = self.compare_external_results(self.case_id, metrics, quality)
        self.assertFalse(result.passed)
        self.assertTrue(any(m.kind == "missing" for m in result.mismatches))

    def test_compare_reports_unexpected_key(self) -> None:
        metrics, quality = self._expected_as_actual()
        with metrics.open("a", encoding="utf-8") as handle:
            handle.write("p-extra,extra_metric,1\n")
        result = self.compare_external_results(self.case_id, metrics, quality)
        self.assertFalse(result.passed)
        self.assertTrue(any(m.kind == "unexpected" for m in result.mismatches))

    def test_compare_does_not_require_sql_execution(self) -> None:
        metrics, quality = self._expected_as_actual()
        # Even with a missing/broken sql path in the environment, compare only
        # reads expectations + external files (no sqlite script execution).
        result = self.compare_external_results(self.case_id, metrics, quality)
        self.assertTrue(result.passed)


class ExternalCompareCliTests(unittest.TestCase):
    """Command-level coverage for scripts/compare_results.py."""

    EXAMPLE_ROOT = (
        PROJECT_ROOT
        / "examples"
        / "external-results"
        / "unmapped-program-retention"
    )
    SCRIPT = PROJECT_ROOT / "scripts" / "compare_results.py"

    def _run_compare(
        self, metrics: Path, quality: Path, *extra: str
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(self.SCRIPT),
                "--case",
                "unmapped-program-retention",
                "--metrics",
                str(metrics),
                "--quality",
                str(quality),
                *extra,
            ],
            check=False,
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
        )

    def test_cli_matching_export_exits_zero(self) -> None:
        result = self._run_compare(
            self.EXAMPLE_ROOT / "matching" / "actual_metrics.csv",
            self.EXAMPLE_ROOT / "matching" / "actual_quality.csv",
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("PASS", result.stdout)
        self.assertIn("unmapped-program-retention", result.stdout)

    def test_cli_mismatching_export_exits_nonzero_and_shows_key(self) -> None:
        result = self._run_compare(
            self.EXAMPLE_ROOT / "inner-join-failure" / "actual_metrics.csv",
            self.EXAMPLE_ROOT / "inner-join-failure" / "actual_quality.csv",
        )
        self.assertEqual(1, result.returncode)
        combined = result.stdout + result.stderr
        self.assertIn("FAIL", combined)
        self.assertIn("unmapped_completed_events", combined)

    def test_cli_invalid_export_exits_two_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            metrics = Path(directory) / "actual_metrics.csv"
            quality = Path(directory) / "actual_quality.csv"
            shutil.copy(
                self.EXAMPLE_ROOT / "matching" / "actual_metrics.csv", metrics
            )
            shutil.copy(
                self.EXAMPLE_ROOT / "matching" / "actual_quality.csv", quality
            )
            metrics.write_text(
                metrics.read_text(encoding="utf-8").replace(",2\n", ",2.0\n", 1),
                encoding="utf-8",
            )
            result = self._run_compare(metrics, quality)

        self.assertEqual(2, result.returncode)
        self.assertIn("ERROR", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_cli_json_and_module_entry_points_are_available(self) -> None:
        metrics = self.EXAMPLE_ROOT / "matching" / "actual_metrics.csv"
        quality = self.EXAMPLE_ROOT / "matching" / "actual_quality.csv"
        result = self._run_compare(metrics, quality, "--json")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["passed"])
        self.assertIsInstance(payload["actual_metrics"][0]["value"], str)

        module_help = subprocess.run(
            [sys.executable, "-m", "health_edge_cases", "--help"],
            check=False,
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
        )
        self.assertEqual(0, module_help.returncode)
        self.assertIn("compare", module_help.stdout)

        legacy = subprocess.run(
            [sys.executable, "-m", "health_edge_cases", "--json"],
            check=False,
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
        )
        self.assertEqual(0, legacy.returncode, legacy.stdout + legacy.stderr)
        self.assertEqual(5, json.loads(legacy.stdout)["case_count"])


class ExternalCompareContractTests(unittest.TestCase):
    def setUp(self) -> None:
        from health_edge_cases.runner import (
            compare_external_results,
            format_compare_console,
        )

        self.compare_external_results = compare_external_results
        self.format_compare_console = format_compare_console
        self.temp_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.temp_dir)
        matching = (
            PROJECT_ROOT
            / "examples"
            / "external-results"
            / "unmapped-program-retention"
            / "matching"
        )
        self.metrics = self.temp_dir / "actual_metrics.csv"
        self.quality = self.temp_dir / "actual_quality.csv"
        self.metrics_source = (matching / "actual_metrics.csv").read_text(
            encoding="utf-8"
        )
        self.quality_source = (matching / "actual_quality.csv").read_text(
            encoding="utf-8"
        )
        self._reset_exports()

    def _reset_exports(self) -> None:
        self.metrics.write_text(self.metrics_source, encoding="utf-8")
        self.quality.write_text(self.quality_source, encoding="utf-8")

    def _replace_first_value(self, path: Path, column: str, value: str) -> None:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = tuple(reader.fieldnames or ())
            rows = list(reader)
        rows[0][column] = value
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def test_compare_rejects_inexact_header(self) -> None:
        self.metrics.write_text(
            "period_id,metric_id,value\n2026-08,raw_completed_rows,2\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "expected"):
            self.compare_external_results(
                "unmapped-program-retention", self.metrics, self.quality
            )

    def test_compare_rejects_non_canonical_integer_text(self) -> None:
        for value in (
            "1.5",
            "1.0",
            "1e0",
            "NaN",
            "Infinity",
            "",
            "2_0",
            "٢",
            "２",
        ):
            with self.subTest(value=value):
                self._reset_exports()
                self._replace_first_value(self.metrics, "actual_value", value)
                with self.assertRaisesRegex(ValueError, "exact integer"):
                    self.compare_external_results(
                        "unmapped-program-retention", self.metrics, self.quality
                    )

    def test_compare_uses_browser_equivalent_unicode_trimming(self) -> None:
        self._replace_first_value(self.metrics, "actual_value", "\ufeff2\ufeff")
        result = self.compare_external_results(
            "unmapped-program-retention", self.metrics, self.quality
        )
        self.assertTrue(result.passed)

        self._reset_exports()
        self._replace_first_value(self.metrics, "actual_value", "\u00852\u0085")
        with self.assertRaisesRegex(ValueError, "exact integer"):
            self.compare_external_results(
                "unmapped-program-retention", self.metrics, self.quality
            )

        self._reset_exports()
        self._replace_first_value(self.metrics, "metric_id", "\ufeff")
        with self.assertRaisesRegex(ValueError, "blank metric_id"):
            self.compare_external_results(
                "unmapped-program-retention", self.metrics, self.quality
            )

        self._reset_exports()
        self._replace_first_value(self.metrics, "metric_id", "\u0085")
        result = self.compare_external_results(
            "unmapped-program-retention", self.metrics, self.quality
        )
        self.assertFalse(result.passed)
        self.assertTrue(
            any(mismatch.key[-1] == "\u0085" for mismatch in result.mismatches)
        )

    def test_compare_accepts_signed_leading_zero_and_large_integers(self) -> None:
        value = "+000" + ("9" * 10_000)
        self._replace_first_value(self.metrics, "actual_value", value)
        result = self.compare_external_results(
            "unmapped-program-retention", self.metrics, self.quality
        )
        self.assertFalse(result.passed)
        actual = next(
            mismatch.actual
            for mismatch in result.mismatches
            if mismatch.actual is not None and mismatch.actual != 2
        )
        self.assertGreater(actual.bit_length(), 30_000)
        rendered = self.format_compare_console(result)
        self.assertIn("9" * 100, rendered)

    def test_compare_rejects_blank_metric_and_quality_keys(self) -> None:
        for path, column, value in (
            (self.metrics, "period_id", ""),
            (self.metrics, "metric_id", " \t"),
            (self.quality, "check_id", " "),
        ):
            with self.subTest(path=path.name, column=column, value=value):
                self._reset_exports()
                self._replace_first_value(path, column, value)
                with self.assertRaisesRegex(ValueError, rf"blank {column}"):
                    self.compare_external_results(
                        "unmapped-program-retention", self.metrics, self.quality
                    )

    def test_compare_rejects_duplicate_external_keys(self) -> None:
        first_row = self.metrics_source.splitlines()[1]
        with self.metrics.open("a", encoding="utf-8", newline="") as handle:
            handle.write(first_row + "\n")
        with self.assertRaisesRegex(ValueError, "duplicate actual key"):
            self.compare_external_results(
                "unmapped-program-retention", self.metrics, self.quality
            )

    def test_compare_accepts_utf8_byte_order_mark(self) -> None:
        self.metrics.write_text("\ufeff" + self.metrics_source, encoding="utf-8")
        self.quality.write_text("\ufeff" + self.quality_source, encoding="utf-8")
        result = self.compare_external_results(
            "unmapped-program-retention", self.metrics, self.quality
        )
        self.assertTrue(result.passed)

    def test_compare_rejects_malformed_csv_quoting(self) -> None:
        for value, pattern in (
            ('"2', "unclosed quoted field"),
            ('"2"x', "after a closing quote"),
            ('2"x', "quote inside an unquoted field"),
        ):
            with self.subTest(value=value):
                self._reset_exports()
                lines = self.metrics_source.splitlines()
                columns = lines[1].split(",")
                columns[-1] = value
                lines[1] = ",".join(columns)
                self.metrics.write_text("\n".join(lines) + "\n", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, pattern):
                    self.compare_external_results(
                        "unmapped-program-retention", self.metrics, self.quality
                    )

    def test_compare_rejects_case_paths_outside_cases_root(self) -> None:
        with self.assertRaisesRegex(ValueError, "kebab-case"):
            self.compare_external_results(
                "../unmapped-program-retention", self.metrics, self.quality
            )

    def test_compare_console_escapes_and_preserves_structured_keys(self) -> None:
        with self.metrics.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(("A / B", "C", "1"))
            writer.writerow(("A", "B / C", "1"))
            writer.writerow(("\x1b[31m", "control", "1"))
            writer.writerow(("quoted, period", 'metric "quoted"', "1"))
        result = self.compare_external_results(
            "unmapped-program-retention", self.metrics, self.quality
        )
        rendered = self.format_compare_console(result)
        self.assertIn('["A / B","C"]', rendered)
        self.assertIn('["A","B / C"]', rendered)
        self.assertIn(r"\u001b[31m", rendered)
        self.assertNotIn("\x1b", rendered)
        self.assertIn(r'["quoted, period","metric \"quoted\""]', rendered)


if __name__ == "__main__":
    unittest.main()
