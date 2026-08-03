from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from health_edge_cases import __version__
from health_edge_cases.runner import DEFAULT_CASES_DIR, PROJECT_ROOT, discover_cases
from health_edge_cases.verification import (
    VERIFICATION_MANIFEST_FIELDS,
    expected_verification_manifest,
    render_github_error_summary,
    render_github_summary,
    render_verification_error_json,
    render_verification_error_junit,
    render_verification_json,
    render_verification_junit,
    safe_error_message,
    verify_external_suite,
)


class VerificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.results = Path(self.temporary.name) / "results"
        self._build_matching_results(self.results)

    @staticmethod
    def _actual_text(path: Path) -> str:
        lines = path.read_text(encoding="utf-8").splitlines()
        header = lines[0].replace("expected_value", "actual_value")
        return "\n".join([header, *lines[1:]]) + "\n"

    @classmethod
    def _build_matching_results(cls, destination: Path) -> None:
        destination.mkdir()
        (destination / "verification-manifest.json").write_text(
            json.dumps(expected_verification_manifest(), indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        for case_dir in discover_cases():
            result_dir = destination / case_dir.name
            result_dir.mkdir()
            (result_dir / "actual_metrics.csv").write_text(
                cls._actual_text(case_dir / "expected_metrics.csv"),
                encoding="utf-8",
            )
            (result_dir / "actual_quality.csv").write_text(
                cls._actual_text(case_dir / "expected_quality.csv"),
                encoding="utf-8",
            )

    def test_matching_suite_is_version_and_digest_bound(self) -> None:
        result = verify_external_suite(self.results)
        manifest = expected_verification_manifest()
        self.assertTrue(result.passed)
        self.assertEqual(5, result.passed_count)
        self.assertEqual(72, result.expectation_count)
        self.assertEqual(0, result.mismatch_count)
        self.assertEqual(__version__, result.suite_version)
        self.assertEqual(manifest["catalog_digest"], result.catalog_digest)

    def test_wrong_value_is_a_conformance_failure_not_invalid_input(self) -> None:
        metrics = (
            self.results
            / "unmapped-program-retention"
            / "actual_metrics.csv"
        )
        lines = metrics.read_text(encoding="utf-8").splitlines()
        columns = lines[1].split(",")
        columns[-1] = str(int(columns[-1]) + 1)
        lines[1] = ",".join(columns)
        metrics.write_text("\n".join(lines) + "\n", encoding="utf-8")

        result = verify_external_suite(self.results)
        self.assertFalse(result.passed)
        self.assertEqual(1, result.mismatch_count)
        self.assertEqual(4, result.passed_count)

    def test_manifest_drift_duplicate_fields_and_extra_entries_fail_closed(self) -> None:
        manifest_path = self.results / "verification-manifest.json"
        manifest = expected_verification_manifest()
        invalid_documents = (
            {**manifest, "suite_version": "0.0.0"},
            {**manifest, "catalog_digest": "sha256:" + "0" * 64},
            {**manifest, "unexpected": True},
        )
        for payload in invalid_documents:
            with self.subTest(payload=payload):
                manifest_path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaises(ValueError):
                    verify_external_suite(self.results)
        manifest_path.write_text(
            '{"schema_version":"1.0.0","schema_version":"1.0.0"}',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "duplicate field"):
            verify_external_suite(self.results)

        manifest_path.write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        (self.results / "unexpected.txt").write_text("no", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "unexpected"):
            verify_external_suite(self.results)

    def test_missing_case_and_symlinked_result_fail_closed(self) -> None:
        shutil.rmtree(self.results / "duplicate-encounter-versions")
        with self.assertRaisesRegex(ValueError, "missing"):
            verify_external_suite(self.results)

        shutil.rmtree(self.results)
        self._build_matching_results(self.results)
        metrics = self.results / "unmapped-program-retention" / "actual_metrics.csv"
        target = Path(self.temporary.name) / "outside.csv"
        target.write_bytes(metrics.read_bytes())
        metrics.unlink()
        try:
            metrics.symlink_to(target)
        except OSError:
            self.skipTest("Symlinks are unavailable")
        with self.assertRaisesRegex(ValueError, "regular file"):
            verify_external_suite(self.results)

    def test_json_junit_and_summary_are_deterministic_and_parseable(self) -> None:
        result = verify_external_suite(self.results)
        first_json = render_verification_json(result)
        self.assertEqual(first_json, render_verification_json(result))
        payload = json.loads(first_json)
        self.assertEqual(set(VERIFICATION_MANIFEST_FIELDS), {
            "schema_version", "catalog_id", "suite_version", "catalog_digest"
        })
        self.assertEqual("pass", payload["status"])
        self.assertEqual([], payload["errors"])
        self.assertTrue(payload["passed"])
        self.assertIsInstance(
            payload["cases"][0]["actual_metrics"][0]["value"], str
        )

        first_xml = render_verification_junit(result)
        self.assertEqual(first_xml, render_verification_junit(result))
        root = ET.fromstring(first_xml)
        self.assertEqual("5", root.attrib["tests"])
        self.assertEqual("0", root.attrib["failures"])
        self.assertEqual(5, len(root.findall("testcase")))

        summary = render_github_summary(result)
        self.assertIn("5/5 cases", summary)
        self.assertIn("not certification", summary)

        error_json = json.loads(render_verification_error_json(ValueError("bad")))
        self.assertEqual("error", error_json["status"])
        self.assertFalse(error_json["passed"])
        error_xml = ET.fromstring(
            render_verification_error_junit(ValueError("/tmp/private/bad.csv"))
        )
        self.assertEqual("1", error_xml.attrib["errors"])
        self.assertNotIn("/tmp/private", ET.tostring(error_xml, encoding="unicode"))

    def test_invalid_input_reports_strip_controls_paths_and_markdown_controls(self) -> None:
        hostile = ValueError(
            "/tmp/private/bad\x07bell\x1b[31m.csv `spoof` | row\u202eabc"
        )
        message = safe_error_message(hostile)
        self.assertNotIn("/tmp/private", message)
        self.assertNotIn("\x07", message)
        self.assertNotIn("\x1b", message)
        self.assertNotIn("\u202e", message)
        self.assertTrue(all(ord(character) >= 0x20 for character in message))

        error_xml = render_verification_error_junit(hostile)
        ET.fromstring(error_xml)
        error_json = json.loads(render_verification_error_json(hostile))
        self.assertEqual(message, error_json["errors"][0]["message"])

        summary = render_github_error_summary(hostile)
        self.assertNotIn("`spoof`", summary)
        self.assertNotIn(" | ", summary)
        self.assertNotIn("\u202e", summary)

    def test_verification_schemas_are_closed_and_match_emitted_fields(self) -> None:
        manifest_schema = json.loads(
            (PROJECT_ROOT / "schema/verification-manifest.schema.json").read_text(
                encoding="utf-8"
            )
        )
        result_schema = json.loads(
            (PROJECT_ROOT / "schema/verification-result.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertFalse(manifest_schema["additionalProperties"])
        self.assertEqual(
            set(expected_verification_manifest()), set(manifest_schema["required"])
        )
        self.assertFalse(result_schema["additionalProperties"])
        self.assertFalse(
            result_schema["$defs"]["caseResult"]["additionalProperties"]
        )
        self.assertFalse(
            result_schema["$defs"]["mismatch"]["additionalProperties"]
        )
        emitted = json.loads(render_verification_json(verify_external_suite(self.results)))
        self.assertEqual(set(result_schema["required"]), set(emitted))

    def test_oversized_manifest_and_result_file_are_rejected(self) -> None:
        manifest = self.results / "verification-manifest.json"
        manifest.write_text("{" + " " * (64 * 1024) + "}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "byte JSON limit"):
            verify_external_suite(self.results)

        manifest.write_text(
            json.dumps(expected_verification_manifest()), encoding="utf-8"
        )
        metrics = self.results / "unmapped-program-retention" / "actual_metrics.csv"
        metrics.write_text(
            "period_id,metric_id,actual_value\n"
            + "\n".join(f"p-{index},m-{index},1" for index in range(1001))
            + "\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "external-result limit"):
            verify_external_suite(self.results)


class VerificationCliAndActionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.results = self.root / "results"
        VerificationTests._build_matching_results(self.results)

    def _run(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "health_edge_cases", *arguments],
            cwd=PROJECT_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

    def test_manifest_and_validate_case_commands(self) -> None:
        manifest = self._run("manifest")
        self.assertEqual(0, manifest.returncode, manifest.stderr)
        self.assertEqual(expected_verification_manifest(), json.loads(manifest.stdout))

        validation = self._run(
            "validate-case",
            str(DEFAULT_CASES_DIR / "unmapped-program-retention"),
            "--json",
        )
        self.assertEqual(0, validation.returncode, validation.stderr)
        self.assertTrue(json.loads(validation.stdout)["valid"])

    def test_verify_exit_codes_and_reports(self) -> None:
        json_path = self.root / "report.json"
        junit_path = self.root / "report.xml"
        passing = self._run(
            "verify",
            "--results",
            str(self.results),
            "--json-output",
            str(json_path),
            "--junit-output",
            str(junit_path),
        )
        self.assertEqual(0, passing.returncode, passing.stdout + passing.stderr)
        self.assertTrue(json.loads(json_path.read_text(encoding="utf-8"))["passed"])
        ET.parse(junit_path)

        same_path = self.root / "same-report.out"
        aliased = self._run(
            "verify",
            "--results",
            str(self.results),
            "--json-output",
            str(same_path),
            "--junit-output",
            str(same_path),
        )
        self.assertEqual(2, aliased.returncode)
        self.assertIn("must be different", aliased.stderr)
        self.assertFalse(same_path.exists())

        metrics = self.results / "unmapped-program-retention" / "actual_metrics.csv"
        lines = metrics.read_text(encoding="utf-8").splitlines()
        lines[1] = lines[1].rsplit(",", 1)[0] + ",999"
        metrics.write_text("\n".join(lines) + "\n", encoding="utf-8")
        mismatch = self._run("verify", "--results", str(self.results), "--json")
        self.assertEqual(1, mismatch.returncode, mismatch.stderr)
        self.assertFalse(json.loads(mismatch.stdout)["passed"])

        (self.results / "verification-manifest.json").unlink()
        error_json_path = self.root / "error.json"
        error_junit_path = self.root / "error.xml"
        invalid = self._run(
            "verify",
            "--results",
            str(self.results),
            "--json",
            "--json-output",
            str(error_json_path),
            "--junit-output",
            str(error_junit_path),
        )
        self.assertEqual(2, invalid.returncode)
        self.assertEqual("error", json.loads(invalid.stdout)["status"])
        self.assertEqual("error", json.loads(error_json_path.read_text())["status"])
        self.assertEqual("1", ET.parse(error_junit_path).getroot().attrib["errors"])
        self.assertNotIn("Traceback", invalid.stdout + invalid.stderr)

    def test_composite_action_entry_point_writes_reports_summary_and_outputs(self) -> None:
        summary = self.root / "summary.md"
        outputs = self.root / "outputs.txt"
        environment = {
            **os.environ,
            "EDGE_RESULTS_PATH": str(self.results),
            "EDGE_JSON_OUTPUT_PATH": "",
            "EDGE_JUNIT_OUTPUT_PATH": "",
            "GITHUB_STEP_SUMMARY": str(summary),
            "GITHUB_OUTPUT": str(outputs),
            "RUNNER_TEMP": str(self.root),
            "GITHUB_WORKSPACE": str(self.root),
        }
        completed = subprocess.run(
            [sys.executable, "-I", str(PROJECT_ROOT / "scripts/action_verify.py")],
            cwd=self.root,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        output_values = dict(
            line.split("=", 1)
            for line in outputs.read_text(encoding="utf-8").splitlines()
        )
        json_path = Path(output_values["json-report"])
        junit_path = Path(output_values["junit-report"])
        self.assertTrue(json.loads(json_path.read_text(encoding="utf-8"))["passed"])
        ET.parse(junit_path)
        self.assertIn("5/5 cases", summary.read_text(encoding="utf-8"))
        output_text = outputs.read_text(encoding="utf-8")
        self.assertIn("passed=true", output_text)
        self.assertIn(f"suite-version={__version__}", output_text)
        self.assertEqual(json_path.parent, junit_path.parent)
        self.assertTrue(json_path.parent.name.startswith("health-data-edge-cases-"))

        same_path = self.root / "same-action-report.out"
        aliased_outputs = self.root / "aliased-outputs.txt"
        aliased_environment = {
            **environment,
            "EDGE_JSON_OUTPUT_PATH": str(same_path),
            "EDGE_JUNIT_OUTPUT_PATH": str(same_path),
            "GITHUB_OUTPUT": str(aliased_outputs),
        }
        aliased = subprocess.run(
            [sys.executable, "-I", str(PROJECT_ROOT / "scripts/action_verify.py")],
            cwd=self.root,
            env=aliased_environment,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(2, aliased.returncode)
        self.assertIn("must be different", aliased.stderr)
        self.assertFalse(same_path.exists())
        aliased_values = dict(
            line.split("=", 1)
            for line in aliased_outputs.read_text(encoding="utf-8").splitlines()
        )
        self.assertEqual("false", aliased_values["passed"])
        self.assertEqual(
            "error",
            json.loads(
                Path(aliased_values["json-report"]).read_text(encoding="utf-8")
            )["status"],
        )
        ET.parse(aliased_values["junit-report"])

    def test_deeply_nested_manifest_produces_cli_and_action_error_reports(self) -> None:
        (self.results / "verification-manifest.json").write_text(
            "[" * 10_000 + "0" + "]" * 10_000,
            encoding="utf-8",
        )
        cli_json = self.root / "deep-error.json"
        cli_junit = self.root / "deep-error.xml"
        cli = self._run(
            "verify",
            "--results",
            str(self.results),
            "--json-output",
            str(cli_json),
            "--junit-output",
            str(cli_junit),
        )
        self.assertEqual(2, cli.returncode)
        self.assertNotIn("Traceback", cli.stdout + cli.stderr)
        self.assertEqual("error", json.loads(cli_json.read_text())["status"])
        ET.parse(cli_junit)

        outputs = self.root / "deep-action-outputs.txt"
        action = subprocess.run(
            [sys.executable, "-I", str(PROJECT_ROOT / "scripts/action_verify.py")],
            cwd=self.root,
            env={
                **os.environ,
                "EDGE_RESULTS_PATH": str(self.results),
                "EDGE_JSON_OUTPUT_PATH": "",
                "EDGE_JUNIT_OUTPUT_PATH": "",
                "GITHUB_STEP_SUMMARY": str(self.root / "deep-summary.md"),
                "GITHUB_OUTPUT": str(outputs),
                "RUNNER_TEMP": str(self.root),
                "GITHUB_WORKSPACE": str(self.root),
            },
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(2, action.returncode)
        self.assertNotIn("Traceback", action.stdout + action.stderr)
        values = dict(
            line.split("=", 1)
            for line in outputs.read_text(encoding="utf-8").splitlines()
        )
        self.assertEqual("false", values["passed"])
        self.assertEqual(
            "error",
            json.loads(Path(values["json-report"]).read_text())["status"],
        )
        ET.parse(values["junit-report"])

    def test_action_has_no_token_or_nested_action_dependency(self) -> None:
        action = (PROJECT_ROOT / "action.yml").read_text(encoding="utf-8")
        self.assertNotIn("github.token", action)
        self.assertNotIn("GITHUB_TOKEN", action)
        self.assertNotIn("uses:", action)
        self.assertIn('python3 -I "$GITHUB_ACTION_PATH/scripts/action_verify.py"', action)


if __name__ == "__main__":
    unittest.main()
