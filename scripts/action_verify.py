#!/usr/bin/env python3
"""Isolated entry point for the repository's composite GitHub Action."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from health_edge_cases.verification import (  # noqa: E402
    expected_verification_manifest,
    format_verification_console,
    render_github_error_summary,
    render_github_summary,
    render_verification_error_json,
    render_verification_error_junit,
    render_verification_json,
    render_verification_junit,
    require_distinct_report_paths,
    safe_error_message,
    verify_external_suite,
    write_text_report,
)


def _required_environment(name: str) -> str:
    value = os.environ.get(name, "")
    if not value or any(character in value for character in ("\x00", "\r", "\n")):
        raise ValueError(f"Action environment variable {name} must be non-empty")
    return value


def _optional_path(name: str) -> Path | None:
    value = os.environ.get(name, "")
    if not value:
        return None
    if any(character in value for character in ("\x00", "\r", "\n")):
        raise ValueError(f"Action environment variable {name} contains control text")
    return Path(value)


def _append_github_file(name: str, content: str) -> None:
    destination = os.environ.get(name)
    if not destination:
        return
    path = Path(destination)
    with path.open("a", encoding="utf-8", newline="") as handle:
        handle.write(content)


def _write_outputs(values: dict[str, str]) -> None:
    _append_github_file(
        "GITHUB_OUTPUT",
        "".join(f"{key}={value}\n" for key, value in values.items()),
    )


def _default_report_paths() -> tuple[Path, Path]:
    runner_temp = Path(_required_environment("RUNNER_TEMP"))
    if not runner_temp.is_dir() or runner_temp.is_symlink():
        raise ValueError("RUNNER_TEMP must be a regular directory")
    report_dir = Path(
        tempfile.mkdtemp(prefix="health-data-edge-cases-", dir=runner_temp)
    )
    return (
        report_dir / "verification-result.json",
        report_dir / "verification-junit.xml",
    )


def _report_paths() -> tuple[Path, Path]:
    json_output = _optional_path("EDGE_JSON_OUTPUT_PATH")
    junit_output = _optional_path("EDGE_JUNIT_OUTPUT_PATH")
    default_json: Path | None = None
    default_junit: Path | None = None
    if json_output is None or junit_output is None:
        default_json, default_junit = _default_report_paths()
    resolved_json = json_output or default_json
    resolved_junit = junit_output or default_junit
    assert resolved_json is not None and resolved_junit is not None
    require_distinct_report_paths(resolved_json, resolved_junit)
    return resolved_json, resolved_junit


def _trusted_results_path(value: str) -> Path:
    """Confine Action input to the workspace or runner temporary directory."""

    workspace = Path(_required_environment("GITHUB_WORKSPACE")).resolve(strict=True)
    runner_temp = Path(_required_environment("RUNNER_TEMP")).resolve(strict=True)
    for root in (workspace, runner_temp):
        if not root.is_dir() or root.is_symlink():
            raise ValueError("Action trust roots must be regular directories")

    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = workspace / candidate
    lexical = Path(os.path.abspath(candidate))
    lexical_root = next(
        (root for root in (workspace, runner_temp) if lexical.is_relative_to(root)),
        None,
    )
    if lexical_root is None:
        raise ValueError("Action results must remain inside GITHUB_WORKSPACE or RUNNER_TEMP")
    cursor = lexical_root
    for part in lexical.relative_to(lexical_root).parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError("Action results path must not contain symlinks")
    resolved = lexical.resolve(strict=True)
    if not any(resolved.is_relative_to(root) for root in (workspace, runner_temp)):
        raise ValueError("Action results resolved outside its trusted directories")
    return resolved


def main() -> int:
    json_output: Path | None = None
    junit_output: Path | None = None
    try:
        results_path = _trusted_results_path(
            _required_environment("EDGE_RESULTS_PATH")
        )
        json_output, junit_output = _report_paths()
        result = verify_external_suite(results_path)
        write_text_report(json_output, render_verification_json(result))
        write_text_report(junit_output, render_verification_junit(result))
        _append_github_file("GITHUB_STEP_SUMMARY", render_github_summary(result))
        _write_outputs(
            {
                "passed": str(result.passed).lower(),
                "suite-version": result.suite_version,
                "catalog-digest": result.catalog_digest,
                "case-count": str(len(result.cases)),
                "expectation-count": str(result.expectation_count),
                "mismatch-count": str(result.mismatch_count),
                "json-report": str(json_output.resolve()),
                "junit-report": str(junit_output.resolve()),
            }
        )
    except (OSError, ValueError) as error:
        message = f"ERROR  {safe_error_message(error)}"
        print(message, file=sys.stderr)
        try:
            if json_output is None or junit_output is None:
                json_output, junit_output = _default_report_paths()
            write_text_report(json_output, render_verification_error_json(error))
            write_text_report(
                junit_output,
                render_verification_error_junit(error),
            )
            _append_github_file(
                "GITHUB_STEP_SUMMARY", render_github_error_summary(error)
            )
            manifest = expected_verification_manifest()
            _write_outputs(
                {
                    "passed": "false",
                    "suite-version": manifest["suite_version"],
                    "catalog-digest": manifest["catalog_digest"],
                    "case-count": "0",
                    "expectation-count": "0",
                    "mismatch-count": "0",
                    "json-report": str(json_output.resolve()),
                    "junit-report": str(junit_output.resolve()),
                }
            )
        except (OSError, ValueError) as report_error:
            print(
                f"ERROR  could not write Action reports: "
                f"{safe_error_message(report_error)}",
                file=sys.stderr,
            )
        return 2

    print(format_verification_console(result))
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
