"""Verify a complete set of external results against the published suite."""

from __future__ import annotations

import json
import os
import re
import tempfile
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from . import __version__
from .contracts import CATALOG_ID, build_catalog
from .runner import (
    DEFAULT_CASES_DIR,
    CaseResult,
    _compare_json_payload,
    compare_external_results,
    discover_cases,
    format_compare_console,
)


VERIFICATION_MANIFEST_NAME = "verification-manifest.json"
VERIFICATION_MANIFEST_SCHEMA_VERSION = "1.0.0"
VERIFICATION_RESULT_SCHEMA_VERSION = "1.0.0"
VERIFICATION_MANIFEST_FIELDS = {
    "schema_version",
    "catalog_id",
    "suite_version",
    "catalog_digest",
}
MAX_VERIFICATION_MANIFEST_BYTES = 64 * 1024
MAX_RENDERED_ERROR_CHARS = 500


@dataclass(frozen=True)
class SuiteVerificationResult:
    """Comparison outcome for one version-bound external result set."""

    suite_version: str
    catalog_digest: str
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

    @property
    def mismatch_count(self) -> int:
        return sum(len(case.mismatches) for case in self.cases)


def expected_verification_manifest() -> dict[str, str]:
    """Return the exact identity manifest required by ``verify``."""

    catalog = build_catalog()
    return {
        "schema_version": VERIFICATION_MANIFEST_SCHEMA_VERSION,
        "catalog_id": CATALOG_ID,
        "suite_version": __version__,
        "catalog_digest": str(catalog["catalog_digest"]),
    }


def _reject_duplicate_json_pairs(pairs: Sequence[tuple[str, object]]) -> dict[str, object]:
    payload: dict[str, object] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError(f"JSON contains duplicate field {key!r}")
        payload[key] = value
    return payload


def _read_json_object(path: Path) -> dict[str, object]:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"Required regular file is missing: {path}")
    if path.stat().st_size > MAX_VERIFICATION_MANIFEST_BYTES:
        raise ValueError(
            f"{path} exceeds the {MAX_VERIFICATION_MANIFEST_BYTES}-byte JSON limit"
        )
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_json_pairs,
        )
    except (json.JSONDecodeError, UnicodeError) as error:
        raise ValueError(f"{path} is not valid UTF-8 JSON: {error}") from error
    except RecursionError as error:
        raise ValueError(f"{path} JSON nesting is too deep") from error
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _validate_manifest(
    payload: Mapping[str, object], expected: Mapping[str, str], path: Path
) -> None:
    actual_fields = set(payload)
    if actual_fields != VERIFICATION_MANIFEST_FIELDS:
        raise ValueError(
            f"{path} fields differ: "
            f"missing={sorted(VERIFICATION_MANIFEST_FIELDS - actual_fields)}, "
            f"unexpected={sorted(actual_fields - VERIFICATION_MANIFEST_FIELDS)}"
        )
    if dict(payload) != dict(expected):
        for field in sorted(VERIFICATION_MANIFEST_FIELDS):
            if payload[field] != expected[field]:
                raise ValueError(
                    f"{path} {field} {payload[field]!r} does not match "
                    f"the installed suite value {expected[field]!r}"
                )
        raise ValueError(f"{path} does not match the installed suite identity")


def _require_exact_result_tree(results_dir: Path, case_ids: Sequence[str]) -> None:
    if not results_dir.is_dir() or results_dir.is_symlink():
        raise ValueError(f"Results path must be a regular directory: {results_dir}")
    expected_root_names = {VERIFICATION_MANIFEST_NAME, *case_ids}
    actual_root_names = {path.name for path in results_dir.iterdir()}
    if actual_root_names != expected_root_names:
        raise ValueError(
            f"{results_dir} entries differ: "
            f"missing={sorted(expected_root_names - actual_root_names)}, "
            f"unexpected={sorted(actual_root_names - expected_root_names)}"
        )

    expected_case_files = {"actual_metrics.csv", "actual_quality.csv"}
    for case_id in case_ids:
        case_dir = results_dir / case_id
        if not case_dir.is_dir() or case_dir.is_symlink():
            raise ValueError(f"Result case must be a regular directory: {case_dir}")
        paths = tuple(case_dir.iterdir())
        actual_names = {path.name for path in paths}
        if actual_names != expected_case_files:
            raise ValueError(
                f"{case_dir} entries differ: "
                f"missing={sorted(expected_case_files - actual_names)}, "
                f"unexpected={sorted(actual_names - expected_case_files)}"
            )
        for path in paths:
            if not path.is_file() or path.is_symlink():
                raise ValueError(f"Result must be a regular file: {path}")


def verify_external_suite(results_dir: Path) -> SuiteVerificationResult:
    """Verify every published case without executing external code or SQL."""

    expected_manifest = expected_verification_manifest()
    case_ids = tuple(path.name for path in discover_cases(DEFAULT_CASES_DIR))
    _require_exact_result_tree(results_dir, case_ids)
    manifest_path = results_dir / VERIFICATION_MANIFEST_NAME
    _validate_manifest(
        _read_json_object(manifest_path), expected_manifest, manifest_path
    )

    cases = tuple(
        compare_external_results(
            case_id=case_id,
            metrics_path=results_dir / case_id / "actual_metrics.csv",
            quality_path=results_dir / case_id / "actual_quality.csv",
            cases_dir=DEFAULT_CASES_DIR,
        )
        for case_id in case_ids
    )
    return SuiteVerificationResult(
        suite_version=expected_manifest["suite_version"],
        catalog_digest=expected_manifest["catalog_digest"],
        cases=cases,
    )


def format_verification_console(result: SuiteVerificationResult) -> str:
    """Render a compact human-readable suite verification report."""

    lines = [
        f"Health Data Edge Cases v{result.suite_version}",
        f"Catalog {result.catalog_digest}",
    ]
    lines.extend(format_compare_console(case) for case in result.cases)
    status = "PASS" if result.passed else "FAIL"
    lines.append(
        f"{status}  verification: {result.passed_count}/{len(result.cases)} cases, "
        f"{result.expectation_count} expectations, {result.mismatch_count} mismatches"
    )
    return "\n".join(lines)


def verification_json_payload(
    result: SuiteVerificationResult,
) -> dict[str, object]:
    """Return a precision-safe, versioned machine result."""

    cases = []
    for case in result.cases:
        payload = _compare_json_payload(case)
        for mismatch in payload["mismatches"]:
            mismatch["scope"] = (
                "metrics" if len(mismatch["key"]) == 2 else "quality"
            )
        cases.append(payload)
    return {
        "schema_version": VERIFICATION_RESULT_SCHEMA_VERSION,
        "catalog_id": CATALOG_ID,
        "suite_version": result.suite_version,
        "catalog_digest": result.catalog_digest,
        "status": "pass" if result.passed else "fail",
        "passed": result.passed,
        "passed_count": result.passed_count,
        "case_count": len(result.cases),
        "expectation_count": result.expectation_count,
        "mismatch_count": result.mismatch_count,
        "cases": cases,
        "errors": [],
    }


def render_verification_json(result: SuiteVerificationResult) -> str:
    return json.dumps(
        verification_json_payload(result),
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    ) + "\n"


def safe_error_message(error: Exception) -> str:
    """Return bounded, single-line text without control sequences or local paths."""

    text = str(error)
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    text = re.sub(r"(?:[A-Za-z]:[\\/]|/)[^\s,;]+", "<path>", text)
    text = "".join(
        " "
        if unicodedata.category(character) in {"Cc", "Cf", "Cs"}
        or not (
            ord(character) in {0x09, 0x0A, 0x0D}
            or 0x20 <= ord(character) <= 0xD7FF
            or 0xE000 <= ord(character) <= 0xFFFD
            or 0x10000 <= ord(character) <= 0x10FFFF
        )
        else character
        for character in text
    )
    text = " ".join(text.split())
    return text[:MAX_RENDERED_ERROR_CHARS] or "Invalid verification input"


def require_distinct_report_paths(
    json_path: Path | None,
    junit_path: Path | None,
) -> None:
    """Reject destinations that could cause one report to overwrite the other."""

    if json_path is None or junit_path is None:
        return
    json_resolved = json_path.resolve(strict=False)
    junit_resolved = junit_path.resolve(strict=False)
    same_existing_file = (
        json_path.exists()
        and junit_path.exists()
        and os.path.samefile(json_path, junit_path)
    )
    if json_resolved == junit_resolved or same_existing_file:
        raise ValueError("JSON and JUnit report destinations must be different")


def verification_error_json_payload(error: Exception) -> dict[str, object]:
    manifest = expected_verification_manifest()
    return {
        "schema_version": VERIFICATION_RESULT_SCHEMA_VERSION,
        "catalog_id": CATALOG_ID,
        "suite_version": manifest["suite_version"],
        "catalog_digest": manifest["catalog_digest"],
        "status": "error",
        "passed": False,
        "passed_count": 0,
        "case_count": 0,
        "expectation_count": 0,
        "mismatch_count": 0,
        "cases": [],
        "errors": [
            {"code": "invalid_input", "message": safe_error_message(error)}
        ],
    }


def render_verification_error_json(error: Exception) -> str:
    return json.dumps(
        verification_error_json_payload(error),
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    ) + "\n"


def render_verification_junit(result: SuiteVerificationResult) -> str:
    """Render deterministic JUnit XML with one test case per suite case."""

    suite = ET.Element(
        "testsuite",
        {
            "name": CATALOG_ID,
            "tests": str(len(result.cases)),
            "failures": str(len(result.cases) - result.passed_count),
            "errors": "0",
        },
    )
    properties = ET.SubElement(suite, "properties")
    ET.SubElement(
        properties,
        "property",
        {"name": "suite_version", "value": result.suite_version},
    )
    ET.SubElement(
        properties,
        "property",
        {"name": "catalog_digest", "value": result.catalog_digest},
    )
    ET.SubElement(
        properties,
        "property",
        {"name": "expectation_count", "value": str(result.expectation_count)},
    )
    for case in result.cases:
        test_case = ET.SubElement(
            suite,
            "testcase",
            {"classname": CATALOG_ID, "name": case.case_id},
        )
        if not case.passed:
            failure = ET.SubElement(
                test_case,
                "failure",
                {
                    "message": f"{len(case.mismatches)} conformance mismatches",
                    "type": "ConformanceMismatch",
                },
            )
            failure.text = format_compare_console(case)

    ET.indent(suite, space="  ")
    return ET.tostring(
        suite,
        encoding="unicode",
        xml_declaration=True,
        short_empty_elements=True,
    ) + "\n"


def render_verification_error_junit(error: Exception) -> str:
    """Render a deterministic JUnit error for an invalid suite contract."""

    manifest = expected_verification_manifest()
    suite = ET.Element(
        "testsuite",
        {
            "name": CATALOG_ID,
            "tests": "1",
            "failures": "0",
            "errors": "1",
        },
    )
    properties = ET.SubElement(suite, "properties")
    ET.SubElement(
        properties,
        "property",
        {"name": "suite_version", "value": manifest["suite_version"]},
    )
    ET.SubElement(
        properties,
        "property",
        {"name": "catalog_digest", "value": manifest["catalog_digest"]},
    )
    test_case = ET.SubElement(
        suite,
        "testcase",
        {"classname": CATALOG_ID, "name": "suite-contract"},
    )
    error_node = ET.SubElement(
        test_case,
        "error",
        {"message": "invalid verification input", "type": "InvalidInput"},
    )
    error_node.text = safe_error_message(error)
    ET.indent(suite, space="  ")
    return ET.tostring(
        suite,
        encoding="unicode",
        xml_declaration=True,
        short_empty_elements=True,
    ) + "\n"


def render_github_summary(result: SuiteVerificationResult) -> str:
    """Render a concise GitHub step summary without claiming certification."""

    status = "Passed" if result.passed else "Failed"
    lines = [
        "## Health Data Edge Cases verification",
        "",
        f"**{status}** — {result.passed_count}/{len(result.cases)} cases and "
        f"{result.expectation_count} expectations checked.",
        "",
        f"- Suite version: `{result.suite_version}`",
        f"- Catalog digest: `{result.catalog_digest}`",
        f"- Mismatches: `{result.mismatch_count}`",
        "",
        "| Case | Result | Expectations | Mismatches |",
        "|---|---:|---:|---:|",
    ]
    for case in result.cases:
        lines.append(
            f"| `{case.case_id}` | {'Pass' if case.passed else 'Fail'} | "
            f"{case.expectation_count} | {len(case.mismatches)} |"
        )
    lines.extend(
        [
            "",
            "A match confirms these published synthetic contracts only; it is not "
            "certification and does not establish source-data correctness.",
        ]
    )
    return "\n".join(lines) + "\n"


def render_github_error_summary(error: Exception) -> str:
    message = safe_error_message(error).replace("`", "'").replace("|", "\\|")
    return (
        "## Health Data Edge Cases verification\n\n"
        f"**Invalid input** — `{message}`\n\n"
        "No conformance conclusion was produced.\n"
    )


def write_text_report(path: Path, content: str) -> None:
    """Atomically write a regular report file without following a final symlink."""

    if path.exists() and (not path.is_file() or path.is_symlink()):
        raise ValueError(f"Report destination must be a regular file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(content)
            temporary_name = handle.name
        os.replace(temporary_name, path)
        temporary_name = None
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)
