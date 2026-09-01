from __future__ import annotations

import csv
import json
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from health_edge_cases import __version__
from health_edge_cases.runner import (
    ACTUAL_SCHEMAS,
    DEFAULT_CASES_DIR,
    INPUT_SCHEMAS,
    PROJECT_ROOT,
    discover_cases,
)
from health_edge_cases.scaffold import (
    _publish_directory_no_replace,
    create_integration_workspace,
)
from health_edge_cases.verification import (
    expected_verification_manifest,
    verify_external_suite,
)


class ScaffoldTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    @staticmethod
    def _file_bytes(root: Path) -> dict[str, bytes]:
        return {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }

    @staticmethod
    def _populate_matching_results(workspace: Path) -> None:
        for case_dir in discover_cases():
            result_dir = workspace / "results" / case_dir.name
            for expected_name, actual_name in (
                ("expected_metrics.csv", "actual_metrics.csv"),
                ("expected_quality.csv", "actual_quality.csv"),
            ):
                lines = (case_dir / expected_name).read_text(
                    encoding="utf-8"
                ).splitlines()
                lines[0] = lines[0].replace("expected_value", "actual_value")
                (result_dir / actual_name).write_text(
                    "\n".join(lines) + "\n", encoding="utf-8"
                )

    def _run(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "health_edge_cases", *arguments],
            cwd=PROJECT_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

    def test_scaffold_has_an_exact_deterministic_synthetic_tree(self) -> None:
        first = self.root / "first"
        second = self.root / "second"
        result = create_integration_workspace(first)
        create_integration_workspace(second)

        self.assertEqual(5, result.case_count)
        self.assertEqual(30, result.input_file_count)
        self.assertEqual(72, result.expectation_count)
        self.assertEqual(self._file_bytes(first), self._file_bytes(second))
        self.assertEqual(
            stat.S_IMODE((first / "fixtures").stat().st_mode),
            stat.S_IMODE(first.stat().st_mode),
        )

        expected_files = {
            "README.md",
            "result-keys.json",
            "results/verification-manifest.json",
        }
        for case_dir in discover_cases():
            case_id = case_dir.name
            expected_files.update(
                f"fixtures/{case_id}/{filename}"
                for filename in ("case.json", *INPUT_SCHEMAS)
            )
            expected_files.update(
                {
                    f"results/{case_id}/actual_metrics.csv",
                    f"results/{case_id}/actual_quality.csv",
                }
            )

            for filename in ("case.json", *INPUT_SCHEMAS):
                self.assertEqual(
                    (case_dir / filename).read_bytes(),
                    (first / "fixtures" / case_id / filename).read_bytes(),
                )

        self.assertEqual(expected_files, set(self._file_bytes(first)))
        self.assertFalse(any(first.rglob("expected_*.csv")))
        self.assertEqual(
            expected_verification_manifest(),
            json.loads(
                (first / "results" / "verification-manifest.json").read_text(
                    encoding="utf-8"
                )
            ),
        )

        key_contract = json.loads(
            (first / "result-keys.json").read_text(encoding="utf-8")
        )
        identity = expected_verification_manifest()
        self.assertEqual("1.0.0", key_contract["schema_version"])
        self.assertEqual(identity["catalog_id"], key_contract["catalog_id"])
        self.assertEqual(identity["suite_version"], key_contract["suite_version"])
        self.assertEqual(
            identity["catalog_digest"], key_contract["catalog_digest"]
        )
        self.assertEqual(
            ["period_id", "metric_id"], key_contract["metric_key_columns"]
        )
        self.assertEqual(["check_id"], key_contract["quality_key_columns"])

        expected_key_cases = []
        for case_dir in discover_cases():
            with (case_dir / "expected_metrics.csv").open(
                encoding="utf-8", newline=""
            ) as handle:
                metric_keys = sorted(
                    [row["period_id"], row["metric_id"]]
                    for row in csv.DictReader(handle)
                )
            with (case_dir / "expected_quality.csv").open(
                encoding="utf-8", newline=""
            ) as handle:
                quality_keys = sorted(
                    [row["check_id"]] for row in csv.DictReader(handle)
                )
            expected_key_cases.append(
                {
                    "case_id": case_dir.name,
                    "metric_keys": metric_keys,
                    "quality_keys": quality_keys,
                }
            )
        self.assertEqual(expected_key_cases, key_contract["cases"])
        self.assertEqual(
            72,
            sum(
                len(case["metric_keys"]) + len(case["quality_keys"])
                for case in key_contract["cases"]
            ),
        )

        def assert_no_expected_values(value: object) -> None:
            if isinstance(value, dict):
                self.assertTrue(
                    all("expected" not in str(key).lower() for key in value)
                )
                for nested in value.values():
                    assert_no_expected_values(nested)
            elif isinstance(value, list):
                for nested in value:
                    assert_no_expected_values(nested)
            else:
                self.assertIsInstance(value, str)

        assert_no_expected_values(key_contract)

        for case_dir in discover_cases():
            for filename, columns in ACTUAL_SCHEMAS.items():
                path = first / "results" / case_dir.name / filename
                self.assertEqual(",".join(columns) + "\n", path.read_text())
                with path.open(encoding="utf-8", newline="") as handle:
                    reader = csv.DictReader(handle)
                    self.assertEqual(list(columns), reader.fieldnames)
                    self.assertEqual([], list(reader))

        readme = (first / "README.md").read_text(encoding="utf-8")
        self.assertIn("production-equivalent transformation", readme)
        self.assertIn("result-keys.json", readme)
        self.assertIn("Do not add\npatient information", readme)
        self.assertIn("`1` means valid outputs", readme)
        self.assertNotIn(str(self.root), readme)

    def test_untouched_templates_fail_then_populated_results_pass(self) -> None:
        workspace = self.root / "workspace"
        create_integration_workspace(workspace)

        untouched = verify_external_suite(workspace / "results")
        self.assertFalse(untouched.passed)
        self.assertEqual(72, untouched.mismatch_count)
        self.assertTrue(
            all(
                mismatch.kind == "missing"
                for case in untouched.cases
                for mismatch in case.mismatches
            )
        )
        cli_untouched = self._run(
            "verify", "--results", str(workspace / "results")
        )
        self.assertEqual(1, cli_untouched.returncode, cli_untouched.stderr)

        self._populate_matching_results(workspace)
        populated = verify_external_suite(workspace / "results")
        self.assertTrue(populated.passed)
        self.assertEqual(0, populated.mismatch_count)

    def test_empty_metrics_and_quality_are_valid_but_bad_values_are_not(self) -> None:
        workspace = self.root / "workspace"
        create_integration_workspace(workspace)
        case_id = discover_cases()[0].name
        metrics = workspace / "results" / case_id / "actual_metrics.csv"
        quality = workspace / "results" / case_id / "actual_quality.csv"

        metrics.write_text(
            "period_id,metric_id,actual_value\nperiod,metric,not-an-integer\n",
            encoding="utf-8",
        )
        invalid_metrics = self._run(
            "verify", "--results", str(workspace / "results")
        )
        self.assertEqual(2, invalid_metrics.returncode)
        self.assertIn("exact integer", invalid_metrics.stderr)

        metrics.write_text(",".join(ACTUAL_SCHEMAS[metrics.name]) + "\n")
        quality.write_text(
            "check_id,actual_value\ncheck,not-an-integer\n", encoding="utf-8"
        )
        invalid_quality = self._run(
            "verify", "--results", str(workspace / "results")
        )
        self.assertEqual(2, invalid_quality.returncode)
        self.assertIn("exact integer", invalid_quality.stderr)

    def test_existing_targets_and_failed_publish_are_preserved(self) -> None:
        existing_directory = self.root / "existing-directory"
        existing_directory.mkdir()
        sentinel = existing_directory / "sentinel.txt"
        sentinel.write_text("keep", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            create_integration_workspace(existing_directory)
        self.assertEqual("keep", sentinel.read_text(encoding="utf-8"))

        existing_file = self.root / "existing-file"
        existing_file.write_text("keep", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            create_integration_workspace(existing_file)
        self.assertEqual("keep", existing_file.read_text(encoding="utf-8"))

        broken_link = self.root / "broken-link"
        try:
            broken_link.symlink_to(
                self.root / "missing-target", target_is_directory=True
            )
        except OSError:
            pass
        else:
            with self.assertRaises(FileExistsError):
                create_integration_workspace(broken_link)
            self.assertTrue(broken_link.is_symlink())

        failed = self.root / "failed"
        with mock.patch(
            "health_edge_cases.scaffold._publish_directory_no_replace",
            side_effect=OSError("injected failure"),
        ):
            with self.assertRaisesRegex(OSError, "injected failure"):
                create_integration_workspace(failed)
        self.assertFalse(failed.exists())
        self.assertEqual([], list(self.root.glob(".failed.tmp-*")))

        raced = self.root / "raced"

        def create_racing_destination(staging: Path, destination: Path) -> None:
            destination.mkdir()
            _publish_directory_no_replace(staging, destination)

        with mock.patch(
            "health_edge_cases.scaffold._publish_directory_no_replace",
            side_effect=create_racing_destination,
        ):
            with self.assertRaises(FileExistsError):
                create_integration_workspace(raced)
        self.assertTrue(raced.is_dir())
        self.assertEqual([], list(raced.iterdir()))
        self.assertEqual([], list(self.root.glob(".raced.tmp-*")))

    def test_cli_scaffold_refuses_overwrite_and_reports_version(self) -> None:
        version = self._run("--version")
        self.assertEqual(0, version.returncode, version.stderr)
        self.assertEqual(
            f"health-data-edge-cases {__version__}", version.stdout.strip()
        )

        destination = self.root / "cli-workspace"
        created = self._run("scaffold", str(destination))
        self.assertEqual(0, created.returncode, created.stderr)
        self.assertIn("5 cases", created.stdout)
        self.assertIn("72 expectations", created.stdout)
        refused = self._run("scaffold", str(destination))
        self.assertEqual(2, refused.returncode)
        self.assertIn("Refusing to replace", refused.stderr)
        self.assertTrue((destination / "README.md").is_file())


if __name__ == "__main__":
    unittest.main()
