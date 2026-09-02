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
                "health_data_edge_cases-0.5.1-py3-none-any.whl",
                "health_data_edge_cases-0.5.1.tar.gz",
                "health-data-edge-cases-0.5.1-contracts.zip",
                "health-data-edge-cases-0.5.1-provenance.json",
                "SHA256SUMS",
            ),
            release_assets.release_asset_names("0.5.1"),
        )

    def test_bundle_is_deterministic_allowlisted_and_self_verifying(self) -> None:
        version = "0.5.1"
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
                    "health-data-edge-cases-0.5.1-contracts/"
                )
                names = archive.namelist()
                self.assertEqual(len(names), len(set(names)))
                self.assertTrue(all(name.startswith(prefix) for name in names))
                self.assertNotIn(f"{prefix}.github/workflows/ci.yml", names)
                self.assertNotIn(f"{prefix}health_edge_cases/runner.py", names)
                self.assertIn(f"{prefix}README.md", names)
                self.assertIn(f"{prefix}MANIFEST.json", names)
                self.assertIn(f"{prefix}contracts/catalog-v1.json", names)
                self.assertIn(
                    f"{prefix}schema/verification-manifest.schema.json", names
                )
                self.assertIn(
                    f"{prefix}schema/verification-result.schema.json", names
                )
                self.assertIn(f"{prefix}docs/VERIFY_SUITE.md", names)
                self.assertIn(f"{prefix}PUBLICATION_POLICY.md", names)
                self.assertNotIn(f"{prefix}action.yml", names)

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
                    version="0.5.1",
                    commit="main",
                    source_date_epoch=1785040364,
                )
            with self.assertRaisesRegex(ValueError, "1980"):
                release_assets.build_contract_archive(
                    output,
                    project_root=PROJECT_ROOT,
                    version="0.5.1",
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
                    version="0.5.1",
                    commit="a" * 40,
                    source_date_epoch=1785040364,
                )


class ReleaseWorkflowSafetyTests(unittest.TestCase):
    DOWNLOAD_ARTIFACT_V8 = (
        "actions/download-artifact@"
        "3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c # v8.0.1"
    )
    ATTEST_V422 = (
        "actions/attest@"
        "1e69f48acb82d1966a394da916b4c1698aa569d6 # v4.2.2"
    )

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
        self.assertEqual(2, workflow.count(self.DOWNLOAD_ARTIFACT_V8))
        self.assertEqual(1, workflow.count(self.ATTEST_V422))
        for action in (
            "actions/upload-artifact",
            "actions/download-artifact",
            "actions/attest",
        ):
            self.assertRegex(
                workflow,
                rf"{re.escape(action)}@[0-9a-f]{{40}}",
            )

    def test_release_asset_job_rejects_reused_version_identity(self) -> None:
        workflow = (PROJECT_ROOT / ".github/workflows/ci.yml").read_text(
            encoding="utf-8"
        )
        release_job = workflow[
            workflow.index("  release-assets:") : workflow.index(
                "\n  wheel-smoke:", workflow.index("  release-assets:")
            )
        ]

        for required in (
            "fetch-depth: 0",
            'tag="refs/tags/v${version}"',
            '"$tag^{commit}"',
            '"$GITHUB_SHA"',
            'PUBLISHED_TAGS="$(git tag --list)"',
            "semantic_version.fullmatch",
            "current < latest",
            "older than latest",
            "bump the version",
            "action.yml",
            "pyproject.toml",
            "health_edge_cases/**",
            "cases/**",
            "sql/**",
            "R/**",
            "schema/**",
            "examples/external-results/**",
            "scripts/action_verify.py",
            "scripts/build_contract_catalog.py",
            "scripts/build_release_assets.py",
            "scripts/build_report.py",
            "scripts/compare_results.py",
            "scripts/run_duckdb.py",
            "scripts/run_suite.py",
            "docs/contracts/catalog-v1.json",
            "docs/DATA_DICTIONARY.md",
            "docs/COMPARE_RESULTS.md",
            "docs/VERIFY_SUITE.md",
            "docs/RELEASE_ASSETS.md",
            "LICENSE",
            "NOTICE",
            "PUBLICATION_POLICY.md",
        ):
            with self.subTest(required=required):
                self.assertIn(required, release_job)

        self.assertLess(
            release_job.index("if current < latest:"),
            release_job.index(
                'if git rev-parse --verify --quiet "$tag^{commit}"'
            ),
            "an exact revert to an older tagged payload must fail first",
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
        self.assertEqual(1, workflow.count(self.DOWNLOAD_ARTIFACT_V8))

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

    def test_deploy_workflows_queue_every_run_and_pages_uses_current_main(
        self,
    ) -> None:
        release = (PROJECT_ROOT / ".github/workflows/release.yml").read_text(
            encoding="utf-8"
        )
        pages = (PROJECT_ROOT / ".github/workflows/pages.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "concurrency:\n"
            "  group: validated-release\n"
            "  cancel-in-progress: false\n"
            "  queue: max\n",
            release,
        )
        self.assertIn(
            "concurrency:\n"
            "  group: github-pages\n"
            "  cancel-in-progress: false\n"
            "  queue: max\n",
            pages,
        )
        self.assertIn(
            "      - name: Check out repository\n"
            "        uses: actions/checkout@"
            "3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1\n"
            "        with:\n"
            "          ref: main\n"
            "          persist-credentials: false\n",
            pages,
        )
        self.assertEqual(1, pages.count("          ref: main\n"))

    def test_published_version_is_noop_but_new_release_stays_exact(self) -> None:
        workflow = (PROJECT_ROOT / ".github/workflows/release.yml").read_text(
            encoding="utf-8"
        )
        published_noop = workflow.index(
            "Published release $TAG at verified tag $tag_sha already exists; "
            "nothing to do."
        )
        published_branch = workflow[
            workflow.rindex(
                'if test "$(jq -r \'.draft\' "$release_json")" = "false"; then',
                0,
                published_noop,
            ) : workflow.index("exit 0", published_noop) + len("exit 0")
        ]
        self.assertIn("tag ref is missing", published_branch)
        self.assertIn("target $release_target does not match tag", published_branch)
        self.assertIn("verify_published_assets", published_branch)
        self.assertNotIn("--method POST", published_branch)
        self.assertNotIn("--method PATCH", published_branch)
        self.assertNotIn("upload_release_asset", published_branch)
        self.assertGreater(
            workflow.index("            ensure_current_tag", published_noop),
            published_noop,
        )
        self.assertIn(
            "Unpublished tag $TAG points to $tag_sha, not $VALIDATED_SHA.",
            workflow,
        )

        verifier_start = workflow.index("verify_published_assets()")
        verifier_end = workflow.index(
            "\n          }\n\n          releases_pages=",
            verifier_start,
        )
        verifier = workflow[verifier_start:verifier_end]
        for required in (
            "[.assets[].name] | unique | length",
            'test "$remote_state" = "uploaded"',
            "Published release asset size is outside bounds",
            '"repos/$REPOSITORY/releases/assets/$asset_id"',
            'stat -c %s "$destination/$remote_name"',
            'test "$remote_digest" = "sha256:$local_digest"',
            'find "$destination" -maxdepth 1 -type f',
            "sha256sum --check --strict --status SHA256SUMS",
            '--signer-workflow "$REPOSITORY/.github/workflows/ci.yml"',
            '--source-digest "$tag_sha"',
            "--source-ref refs/heads/main",
            "--deny-self-hosted-runners",
            '.source == {',
            'commit: $commit',
            "[.subjects[].name] | sort",
        ):
            self.assertIn(required, verifier)
        self.assertNotIn("release-dist", verifier)
        self.assertNotIn("--method POST", verifier)
        self.assertNotIn("--method PATCH", verifier)


if __name__ == "__main__":
    unittest.main()
