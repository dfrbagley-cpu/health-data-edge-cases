from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from health_edge_cases.report import render_report
from health_edge_cases.runner import DEFAULT_CASES_DIR, PROJECT_ROOT, discover_cases, run_suite


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
            self.assertTrue(manifest["synthetic_data_only"], case_dir.name)

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


if __name__ == "__main__":
    unittest.main()
