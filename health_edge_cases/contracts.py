"""Build and validate the canonical public conformance-contract catalog."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping

from . import __version__
from .runner import (
    DEFAULT_CASES_DIR,
    EXPECTED_SCHEMAS,
    _load_manifest,
    _read_expected,
    discover_cases,
)


CATALOG_SCHEMA_VERSION = "1.0.0"
CATALOG_ID = "health-data-edge-cases"
SOURCE_REPOSITORY = "https://github.com/dfrbagley-cpu/health-data-edge-cases"
CATALOG_TOP_LEVEL_FIELDS = {
    "schema_version",
    "catalog_id",
    "suite_version",
    "source_repository",
    "source_release",
    "external_results",
    "cases",
    "provenance",
    "catalog_digest",
}
CASE_FIELDS = {
    "id",
    "title",
    "principle",
    "naive_failure",
    "expected_resolution",
    "synthetic_data_only",
    "tags",
    "source",
    "metrics",
    "quality",
}

EXTERNAL_RESULTS_CONTRACT = {
    "metrics": {
        "columns": ["period_id", "metric_id", "actual_value"],
        "key_columns": ["period_id", "metric_id"],
        "value_column": "actual_value",
    },
    "quality": {
        "columns": ["check_id", "actual_value"],
        "key_columns": ["check_id"],
        "value_column": "actual_value",
    },
    "comparison": {
        "value_type": "exact_integer",
        "duplicate_keys": "reject",
        "missing_keys": "mismatch",
        "unexpected_keys": "mismatch",
        "incorrect_values": "mismatch",
    },
}


def canonical_json(payload: Mapping[str, object]) -> str:
    """Serialize catalog content for digesting across implementations."""

    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def compute_catalog_digest(payload: Mapping[str, object]) -> str:
    """Return the SHA-256 digest over every field except ``catalog_digest``."""

    digest_payload = dict(payload)
    digest_payload.pop("catalog_digest", None)
    digest = hashlib.sha256(
        canonical_json(digest_payload).encode("utf-8")
    ).hexdigest()
    return f"sha256:{digest}"


def _case_contract(case_dir: Path) -> dict[str, object]:
    manifest = _load_manifest(case_dir)
    metrics = _read_expected(
        case_dir / "expected_metrics.csv",
        EXPECTED_SCHEMAS["expected_metrics.csv"],
        ("period_id", "metric_id"),
    )
    quality = _read_expected(
        case_dir / "expected_quality.csv",
        EXPECTED_SCHEMAS["expected_quality.csv"],
        ("check_id",),
    )
    case_id = str(manifest["id"])
    source_root = f"cases/{case_id}"

    return {
        "id": case_id,
        "title": str(manifest["title"]),
        "principle": str(manifest["principle"]),
        "naive_failure": str(manifest["naive_failure"]),
        "expected_resolution": str(manifest["expected_resolution"]),
        "synthetic_data_only": True,
        "tags": sorted(str(tag) for tag in manifest["tags"]),
        "source": {
            "manifest": f"{source_root}/case.json",
            "metrics": f"{source_root}/expected_metrics.csv",
            "quality": f"{source_root}/expected_quality.csv",
        },
        "metrics": [
            {
                "period_id": expectation.key[0],
                "metric_id": expectation.key[1],
                "expected_value": expectation.value,
            }
            for expectation in metrics
        ],
        "quality": [
            {
                "check_id": expectation.key[0],
                "expected_value": expectation.value,
            }
            for expectation in quality
        ],
    }


def build_catalog(
    cases_dir: Path = DEFAULT_CASES_DIR,
    suite_version: str = __version__,
) -> dict[str, object]:
    """Build a deterministic catalog from manifests and expectations only."""

    cases = [_case_contract(case_dir) for case_dir in discover_cases(cases_dir)]
    source_files = sorted(
        source_path
        for case in cases
        for source_path in case["source"].values()
    )
    payload: dict[str, object] = {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "catalog_id": CATALOG_ID,
        "suite_version": suite_version,
        "source_repository": SOURCE_REPOSITORY,
        "source_release": f"{SOURCE_REPOSITORY}/releases/tag/v{suite_version}",
        "external_results": EXTERNAL_RESULTS_CONTRACT,
        "cases": cases,
        "provenance": {
            "generated_by": "health_edge_cases.contracts.build_catalog",
            "input_scope": "case manifests and expected output CSV files only",
            "source_files": source_files,
        },
    }
    payload["catalog_digest"] = compute_catalog_digest(payload)
    validate_catalog(payload)
    return payload


def render_catalog(payload: Mapping[str, object]) -> str:
    """Render a stable, human-reviewable JSON artifact."""

    validate_catalog(payload)
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    ) + "\n"


def _require_exact_fields(
    value: Mapping[str, object],
    expected: set[str],
    label: str,
) -> None:
    actual = set(value)
    if actual != expected:
        raise ValueError(
            f"{label} fields differ: missing={sorted(expected - actual)}, "
            f"unexpected={sorted(actual - expected)}"
        )


def _is_exact_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def validate_catalog(payload: Mapping[str, object]) -> None:
    """Validate the public catalog without requiring a JSON Schema package."""

    _require_exact_fields(payload, CATALOG_TOP_LEVEL_FIELDS, "catalog")
    if payload["schema_version"] != CATALOG_SCHEMA_VERSION:
        raise ValueError("catalog schema_version is unsupported")
    if payload["catalog_id"] != CATALOG_ID:
        raise ValueError("catalog_id is invalid")
    suite_version = payload["suite_version"]
    if not isinstance(suite_version, str) or not suite_version:
        raise ValueError("suite_version must be a non-empty string")
    if payload["source_repository"] != SOURCE_REPOSITORY:
        raise ValueError("source_repository is invalid")
    if payload["source_release"] != (
        f"{SOURCE_REPOSITORY}/releases/tag/v{suite_version}"
    ):
        raise ValueError("source_release does not match suite_version")
    if payload["external_results"] != EXTERNAL_RESULTS_CONTRACT:
        raise ValueError("external_results contract is invalid")

    cases = payload["cases"]
    if not isinstance(cases, list) or not cases:
        raise ValueError("catalog must contain at least one case")
    case_ids: list[str] = []
    source_files: list[str] = []
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise ValueError(f"cases[{index}] must be an object")
        _require_exact_fields(case, CASE_FIELDS, f"cases[{index}]")
        case_id = case["id"]
        if not isinstance(case_id, str) or not case_id:
            raise ValueError(f"cases[{index}].id must be a non-empty string")
        case_ids.append(case_id)
        if case["synthetic_data_only"] is not True:
            raise ValueError(f"{case_id} must be explicitly synthetic")
        tags = case["tags"]
        if (
            not isinstance(tags, list)
            or not tags
            or tags != sorted(tags)
            or any(not isinstance(tag, str) or not tag for tag in tags)
            or len(tags) != len(set(tags))
        ):
            raise ValueError(f"{case_id} tags must be sorted, unique strings")

        expected_source = {
            "manifest": f"cases/{case_id}/case.json",
            "metrics": f"cases/{case_id}/expected_metrics.csv",
            "quality": f"cases/{case_id}/expected_quality.csv",
        }
        if case["source"] != expected_source:
            raise ValueError(f"{case_id} source paths are invalid")
        source_files.extend(expected_source.values())

        metrics = case["metrics"]
        if not isinstance(metrics, list) or not metrics:
            raise ValueError(f"{case_id} metrics must be a non-empty list")
        metric_keys: list[tuple[str, str]] = []
        for metric in metrics:
            if not isinstance(metric, dict) or set(metric) != {
                "period_id",
                "metric_id",
                "expected_value",
            }:
                raise ValueError(f"{case_id} contains an invalid metric")
            key = (metric["period_id"], metric["metric_id"])
            if not all(isinstance(part, str) and part for part in key):
                raise ValueError(f"{case_id} contains an invalid metric key")
            if not _is_exact_integer(metric["expected_value"]):
                raise ValueError(f"{case_id} metric values must be exact integers")
            metric_keys.append(key)
        if metric_keys != sorted(metric_keys) or len(metric_keys) != len(
            set(metric_keys)
        ):
            raise ValueError(f"{case_id} metric keys must be sorted and unique")

        quality = case["quality"]
        if not isinstance(quality, list) or not quality:
            raise ValueError(f"{case_id} quality must be a non-empty list")
        quality_keys: list[str] = []
        for check in quality:
            if not isinstance(check, dict) or set(check) != {
                "check_id",
                "expected_value",
            }:
                raise ValueError(f"{case_id} contains an invalid quality check")
            check_id = check["check_id"]
            if not isinstance(check_id, str) or not check_id:
                raise ValueError(f"{case_id} contains an invalid quality key")
            if not _is_exact_integer(check["expected_value"]):
                raise ValueError(f"{case_id} quality values must be exact integers")
            quality_keys.append(check_id)
        if quality_keys != sorted(quality_keys) or len(quality_keys) != len(
            set(quality_keys)
        ):
            raise ValueError(f"{case_id} quality keys must be sorted and unique")

    if case_ids != sorted(case_ids) or len(case_ids) != len(set(case_ids)):
        raise ValueError("case ids must be sorted and unique")
    provenance = payload["provenance"]
    if not isinstance(provenance, dict) or set(provenance) != {
        "generated_by",
        "input_scope",
        "source_files",
    }:
        raise ValueError("provenance is invalid")
    if provenance["generated_by"] != "health_edge_cases.contracts.build_catalog":
        raise ValueError("provenance generator is invalid")
    if provenance["input_scope"] != (
        "case manifests and expected output CSV files only"
    ):
        raise ValueError("provenance input_scope is invalid")
    if provenance["source_files"] != sorted(source_files):
        raise ValueError("provenance source_files are invalid")

    digest = payload["catalog_digest"]
    if not isinstance(digest, str) or digest != compute_catalog_digest(payload):
        raise ValueError("catalog_digest does not match canonical catalog content")
