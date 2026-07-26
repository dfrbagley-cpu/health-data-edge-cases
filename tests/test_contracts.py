from __future__ import annotations

import csv
import json
import sqlite3
import sys
import unittest
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from health_edge_cases import __version__
from health_edge_cases.contracts import (
    CATALOG_TOP_LEVEL_FIELDS,
    EXTERNAL_RESULTS_CONTRACT,
    build_catalog,
    compute_catalog_digest,
    render_catalog,
    validate_catalog,
)
from health_edge_cases.runner import DEFAULT_CASES_DIR, PROJECT_ROOT, run_case


CATALOG_PATH = PROJECT_ROOT / "docs" / "contracts" / "catalog-v1.json"
CATALOG_SCHEMA_PATH = PROJECT_ROOT / "schema" / "contract-catalog.schema.json"
EXAMPLE_ROOT = (
    PROJECT_ROOT
    / "examples"
    / "external-results"
    / "unmapped-program-retention"
)


class ContractCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = build_catalog()

    def test_catalog_has_expected_version_cases_and_expectations(self) -> None:
        self.assertEqual("1.0.0", self.catalog["schema_version"])
        self.assertEqual("health-data-edge-cases", self.catalog["catalog_id"])
        self.assertEqual(__version__, self.catalog["suite_version"])
        self.assertEqual(EXTERNAL_RESULTS_CONTRACT, self.catalog["external_results"])
        cases = self.catalog["cases"]
        self.assertEqual(5, len(cases))
        self.assertEqual(
            [
                "appointment-encounter-status-conflict",
                "duplicate-encounter-versions",
                "like-for-like-partial-periods",
                "many-to-many-join-inflation",
                "unmapped-program-retention",
            ],
            [case["id"] for case in cases],
        )
        self.assertEqual(
            72,
            sum(
                len(case["metrics"]) + len(case["quality"])
                for case in cases
            ),
        )

    def test_catalog_digest_covers_every_other_top_level_field(self) -> None:
        self.assertEqual(
            compute_catalog_digest(self.catalog),
            self.catalog["catalog_digest"],
        )
        changed = deepcopy(self.catalog)
        changed["cases"][0]["title"] = "A materially different title"
        self.assertNotEqual(
            self.catalog["catalog_digest"],
            compute_catalog_digest(changed),
        )
        with self.assertRaisesRegex(ValueError, "catalog_digest"):
            validate_catalog(changed)

    def test_committed_catalog_is_valid_and_current(self) -> None:
        committed_text = CATALOG_PATH.read_text(encoding="utf-8")
        committed = json.loads(committed_text)
        validate_catalog(committed)
        self.assertEqual(render_catalog(self.catalog), committed_text)

    def test_json_schema_tracks_the_catalog_contract(self) -> None:
        schema = json.loads(CATALOG_SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            CATALOG_TOP_LEVEL_FIELDS,
            set(schema["required"]),
        )
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(
            "sha256:[0-9a-f]{64}",
            schema["properties"]["catalog_digest"]["pattern"].lstrip("^").rstrip("$"),
        )

    def test_version_metadata_is_synchronized(self) -> None:
        project_version = None
        in_project = False
        for line in (PROJECT_ROOT / "pyproject.toml").read_text(
            encoding="utf-8"
        ).splitlines():
            if line == "[project]":
                in_project = True
                continue
            if in_project and line.startswith("["):
                break
            if in_project and line.startswith("version = "):
                project_version = line.split('"', 2)[1]
                break

        citation_version = None
        for line in (PROJECT_ROOT / "CITATION.cff").read_text(
            encoding="utf-8"
        ).splitlines():
            if line.startswith("version: "):
                citation_version = line.removeprefix("version: ").strip()
                break

        self.assertEqual(__version__, project_version)
        self.assertEqual(__version__, citation_version)
        self.assertEqual(
            f"https://github.com/dfrbagley-cpu/health-data-edge-cases/"
            f"releases/tag/v{__version__}",
            self.catalog["source_release"],
        )


class JoinInflationCaseTests(unittest.TestCase):
    def test_explicit_referral_links_prevent_patient_program_join_inflation(
        self,
    ) -> None:
        case_dir = DEFAULT_CASES_DIR / "many-to-many-join-inflation"
        with (case_dir / "referrals.csv").open(
            encoding="utf-8", newline=""
        ) as handle:
            referrals = list(csv.DictReader(handle))
        with (case_dir / "encounters.csv").open(
            encoding="utf-8", newline=""
        ) as handle:
            encounters = list(csv.DictReader(handle))

        with sqlite3.connect(":memory:") as connection:
            connection.execute(
                "CREATE TABLE referrals "
                "(referral_id TEXT, patient_id TEXT, program_id TEXT)"
            )
            connection.executemany(
                "INSERT INTO referrals VALUES (?, ?, ?)",
                (
                    (row["referral_id"], row["patient_id"], row["program_id"])
                    for row in referrals
                ),
            )
            connection.execute(
                "CREATE TABLE encounters "
                "(source_event_id TEXT, patient_id TEXT, program_id TEXT, "
                "referral_id TEXT, status TEXT)"
            )
            connection.executemany(
                "INSERT INTO encounters VALUES (?, ?, ?, ?, ?)",
                (
                    (
                        row["source_event_id"],
                        row["patient_id"],
                        row["program_id"],
                        row["referral_id"],
                        row["status"],
                    )
                    for row in encounters
                ),
            )
            naive_count = connection.execute(
                """
                SELECT COUNT(*)
                FROM referrals AS r
                JOIN encounters AS e
                  ON e.patient_id = r.patient_id
                 AND e.program_id = r.program_id
                WHERE LOWER(e.status) = 'completed'
                """
            ).fetchone()[0]
            linked_count = connection.execute(
                """
                SELECT COUNT(*)
                FROM referrals AS r
                JOIN encounters AS e
                  ON e.referral_id = r.referral_id
                WHERE LOWER(e.status) = 'completed'
                """
            ).fetchone()[0]

        self.assertEqual(4, naive_count)
        self.assertEqual(2, linked_count)

        result = run_case(case_dir)
        metrics = {
            expectation.key: expectation.value
            for expectation in result.actual_metrics
        }
        self.assertEqual(
            2,
            metrics[("2026-09", "completed_service_events")],
        )
        self.assertEqual(1, metrics[("2026-09", "unique_patients_served")])
        self.assertEqual(2, metrics[("2026-09", "referrals_started")])
        self.assertEqual(
            2,
            metrics[("2026-09", "referrals_with_first_service")],
        )
        self.assertEqual(2, metrics[("2026-09", "mapped_completed_events")])
        self.assertTrue(all(item.value == 0 for item in result.actual_quality))


class ExternalResultExampleTests(unittest.TestCase):
    @staticmethod
    def _read_values(
        path: Path,
        columns: list[str],
        key_columns: list[str],
    ) -> dict[tuple[str, ...], int]:
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != columns:
                raise AssertionError(
                    f"{path} columns {reader.fieldnames!r} != {columns!r}"
                )
            values = {}
            for row in reader:
                key = tuple(row[column] for column in key_columns)
                if key in values:
                    raise AssertionError(f"{path} contains duplicate key {key}")
                values[key] = int(row["actual_value"])
        return values

    @classmethod
    def _example_mismatches(cls, example: str) -> set[tuple[str, ...]]:
        catalog = build_catalog()
        case = next(
            case
            for case in catalog["cases"]
            if case["id"] == "unmapped-program-retention"
        )
        metric_contract = catalog["external_results"]["metrics"]
        quality_contract = catalog["external_results"]["quality"]
        actual_metrics = cls._read_values(
            EXAMPLE_ROOT / example / "actual_metrics.csv",
            metric_contract["columns"],
            metric_contract["key_columns"],
        )
        actual_quality = cls._read_values(
            EXAMPLE_ROOT / example / "actual_quality.csv",
            quality_contract["columns"],
            quality_contract["key_columns"],
        )
        expected_metrics = {
            (item["period_id"], item["metric_id"]): item["expected_value"]
            for item in case["metrics"]
        }
        expected_quality = {
            (item["check_id"],): item["expected_value"]
            for item in case["quality"]
        }
        mismatches = {
            ("metrics", *key)
            for key in expected_metrics.keys() | actual_metrics.keys()
            if expected_metrics.get(key) != actual_metrics.get(key)
        }
        mismatches.update(
            {
                ("quality", *key)
                for key in expected_quality.keys() | actual_quality.keys()
                if expected_quality.get(key) != actual_quality.get(key)
            }
        )
        return mismatches

    def test_matching_example_reproduces_every_expectation(self) -> None:
        self.assertEqual(set(), self._example_mismatches("matching"))

    def test_failure_example_preserves_the_documented_pattern(self) -> None:
        self.assertEqual(
            {
                ("metrics", "2026-08", "completed_service_events"),
                ("metrics", "2026-08", "unique_patients_served"),
                ("metrics", "2026-08", "unmapped_completed_events"),
                ("metrics", "2026-08", "referrals_with_first_service"),
                ("quality", "unmapped_completed_encounters"),
            },
            self._example_mismatches("inner-join-failure"),
        )


if __name__ == "__main__":
    unittest.main()
