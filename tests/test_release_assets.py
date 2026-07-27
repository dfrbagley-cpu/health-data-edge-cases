from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "build_release_assets.py"
SPEC = importlib.util.spec_from_file_location("build_release_assets", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Could not import release-asset builder")
release_assets = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = release_assets
SPEC.loader.exec_module(release_assets)


class ContractBundleTests(unittest.TestCase):
    def test_release_has_exactly_five_stable_asset_names(self) -> None:
        self.assertEqual(
            (
                "health_data_edge_cases-0.2.1-py3-none-any.whl",
                "health_data_edge_cases-0.2.1.tar.gz",
                "health-data-edge-cases-0.2.1-contracts.zip",
                "health-data-edge-cases-0.2.1-provenance.json",
                "SHA256SUMS",
            ),
            release_assets.release_asset_names("0.2.1"),
        )

    def test_bundle_is_deterministic_allowlisted_and_self_verifying(self) -> None:
        version = "0.2.1"
        commit = "a" * 40
        epoch = 1785040364
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first.zip"
            second = root / "second.zip"
            for output in (first, second):
                release_assets.build_contract_archive(
                    output,
                    project_root=PROJECT_ROOT,
                    version=version,
                    commit=commit,
                    source_date_epoch=epoch,
                )

            self.assertEqual(first.read_bytes(), second.read_bytes())
            with zipfile.ZipFile(first) as archive:
                prefix = (
                    "health-data-edge-cases-0.2.1-contracts/"
                )
                names = archive.namelist()
                self.assertEqual(len(names), len(set(names)))
                self.assertTrue(all(name.startswith(prefix) for name in names))
                self.assertNotIn(f"{prefix}.github/workflows/ci.yml", names)
                self.assertNotIn(f"{prefix}health_edge_cases/runner.py", names)
                self.assertIn(f"{prefix}README.md", names)
                self.assertIn(f"{prefix}MANIFEST.json", names)
                self.assertIn(f"{prefix}contracts/catalog-v1.json", names)

                manifest = json.loads(
                    archive.read(f"{prefix}MANIFEST.json")
                )
                self.assertEqual(commit, manifest["source_commit"])
                self.assertEqual(epoch, manifest["source_date_epoch"])
                self.assertEqual(
                    sorted(item["path"] for item in manifest["files"]),
                    [item["path"] for item in manifest["files"]],
                )
                for item in manifest["files"]:
                    content = archive.read(f"{prefix}{item['path']}")
                    self.assertEqual(len(content), item["size"])
                    self.assertEqual(
                        hashlib.sha256(content).hexdigest(),
                        item["sha256"],
                    )

    def test_bad_commit_and_pre_zip_epoch_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "bundle.zip"
            with self.assertRaisesRegex(ValueError, "commit"):
                release_assets.build_contract_archive(
                    output,
                    project_root=PROJECT_ROOT,
                    version="0.2.1",
                    commit="main",
                    source_date_epoch=1785040364,
                )
            with self.assertRaisesRegex(ValueError, "1980"):
                release_assets.build_contract_archive(
                    output,
                    project_root=PROJECT_ROOT,
                    version="0.2.1",
                    commit="a" * 40,
                    source_date_epoch=0,
                )

    def test_release_directory_rejects_non_regular_entries_first(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "unexpected-directory").mkdir()
            with self.assertRaisesRegex(ValueError, "regular files only"):
                release_assets.validate_release_directory(
                    root,
                    version="0.2.1",
                    commit="a" * 40,
                    source_date_epoch=1785040364,
                )


class ReleaseWorkflowSafetyTests(unittest.TestCase):
    def test_ci_builds_attests_and_smoke_tests_the_exact_artifact(self) -> None:
        workflow = (PROJECT_ROOT / ".github/workflows/ci.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("release-assets-${{ github.sha }}", workflow)
        self.assertIn('python-version: ["3.10", "3.12"]', workflow)
        self.assertIn("actions/attest@", workflow)
        self.assertIn("id-token: write", workflow)
        self.assertIn("attestations: write", workflow)
        self.assertIn("artifact-metadata: write", workflow)
        self.assertIn("SOURCE_DATE_EPOCH", workflow)
        self.assertIn(
            "(cd release-dist && sha256sum --check SHA256SUMS)",
            workflow,
        )
        for action in (
            "actions/upload-artifact",
            "actions/download-artifact",
            "actions/attest",
        ):
            self.assertRegex(
                workflow,
                rf"{re.escape(action)}@[0-9a-f]{{40}}",
            )

    def test_release_uses_workflow_artifact_without_checkout_or_execution(self) -> None:
        workflow = (PROJECT_ROOT / ".github/workflows/release.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("workflow_run:", workflow)
        self.assertIn("actions: read", workflow)
        self.assertIn("attestations: read", workflow)
        self.assertIn("contents: write", workflow)
        self.assertNotIn("actions/checkout@", workflow)
        self.assertNotIn("build_release_assets.py", workflow)
        self.assertIn("draft=true", workflow)
        self.assertIn("draft=false", workflow)
        self.assertIn("Uploading missing exact draft asset", workflow)
        self.assertIn("gh attestation verify", workflow)
        self.assertIn("--paginate --slurp", workflow)
        self.assertIn("releases/assets/$asset_id", workflow)
        self.assertIn("cmp --silent", workflow)

        recovered_assets = (
            'verify_remote_assets \\\n'
            '                "$release_json" "$RUNNER_TEMP/completed-existing-release"'
        )
        recovered_index = workflow.index(recovered_assets)
        publish_index = workflow.index(
            'gh api --method PATCH "repos/$REPOSITORY/releases/$release_id"',
            recovered_index,
        )
        pre_publish = workflow[recovered_index:publish_index]
        self.assertIn("git/ref/heads/main", pre_publish)
        self.assertIn('commits/$TAG', pre_publish)


if __name__ == "__main__":
    unittest.main()
