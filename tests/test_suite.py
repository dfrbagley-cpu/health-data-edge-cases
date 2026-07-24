from __future__ import annotations

import csv
import json
import re
import shutil
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

    def test_case_directories_missing_manifests_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cases_dir = Path(directory) / "cases"
            (cases_dir / "incomplete-case").mkdir(parents=True)

            with self.assertRaisesRegex(ValueError, "missing case.json"):
                discover_cases(cases_dir)


if __name__ == "__main__":
    unittest.main()


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
