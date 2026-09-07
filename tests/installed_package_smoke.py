"""Exercise an installed wheel from a disposable workspace, including on Windows.

Run explicitly after a non-editable wheel installation. This is separate from
unit-test discovery because importing the checkout would invalidate the check.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]


def run(cwd: Path, *arguments: str, exit_code: int = 0) -> str:
    result = subprocess.run(
        [sys.executable, "-I", *arguments],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    if result.returncode != exit_code:
        raise AssertionError(
            f"Expected exit {exit_code}, got {result.returncode}: "
            f"{result.stdout}\n{result.stderr}"
        )
    return result.stdout


def cli(cwd: Path, *arguments: str, exit_code: int = 0) -> dict:
    return json.loads(run(
        cwd, "-m", "health_edge_cases", *arguments, "--json",
        exit_code=exit_code,
    ))


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="edge wheel smoke ") as directory:
        root = Path(directory)
        installed = Path(run(
            root, "-c",
            "import health_edge_cases; print(health_edge_cases.__file__)",
        ).strip()).resolve()
        assert not installed.is_relative_to(REPOSITORY), "Imported the checkout"

        reference = cli(root, "run")
        assert reference["passed"] is True
        assert reference["case_count"] == reference["passed_count"] == 5
        assert reference["expectation_count"] == 72

        packs = cli(root, "packs")
        assert packs["passed"] is True
        assert sum(p["expectations"] for p in packs["packs"]) == 16
        assert cli(root, "packs", "--naive", exit_code=1)["passed"] is False

        example = REPOSITORY / "examples" / "external-results" / "unmapped-program-retention"
        for name, code, mismatches in (("matching", 0, 0), ("inner-join-failure", 1, 5)):
            comparison = cli(
                root, "compare", "--case", "unmapped-program-retention",
                "--metrics", str(example / name / "actual_metrics.csv"),
                "--quality", str(example / name / "actual_quality.csv"),
                exit_code=code,
            )
            assert comparison["passed"] is (code == 0)
            assert comparison["expectation_count"] == 13
            assert len(comparison["mismatches"]) == mismatches

        workspace = root / "fresh workspace"
        run(root, "-m", "health_edge_cases", "scaffold", workspace.name)
        fixture_ids = {p.name for p in (workspace / "fixtures").iterdir() if p.is_dir()}
        result_ids = {p.name for p in (workspace / "results").iterdir() if p.is_dir()}
        assert len(fixture_ids) == 5
        assert fixture_ids == result_ids == {case["case_id"] for case in reference["cases"]}

        empty = cli(workspace, "verify", "--results", "results", exit_code=1)
        assert empty["status"] == "fail"
        assert empty["expectation_count"] == empty["mismatch_count"] == 72
        assert {m["kind"] for case in empty["cases"] for m in case["mismatches"]} == {"missing"}

        # The workspace root must remain an input error, not a comparison pass.
        wrong_root = cli(root, "verify", "--results", workspace.name, exit_code=2)
        assert wrong_root["status"] == "error"

        before = {p.relative_to(workspace): p.read_bytes() for p in workspace.rglob("*") if p.is_file()}
        run(root, "-m", "health_edge_cases", "scaffold", workspace.name, exit_code=2)
        after = {p.relative_to(workspace): p.read_bytes() for p in workspace.rglob("*") if p.is_file()}
        assert before == after, "Scaffolding replaced existing workspace files"

    print("PASS installed wheel: reference, comparisons, empty results, wrong path, and no overwrite")


if __name__ == "__main__":
    main()
