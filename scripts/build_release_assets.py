#!/usr/bin/env python3
"""Build and validate the five deterministic GitHub Release assets."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "health-data-edge-cases"
NORMALIZED_PACKAGE_NAME = "health_data_edge_cases"
SOURCE_REPOSITORY = (
    "https://github.com/dfrbagley-cpu/health-data-edge-cases"
)
MINIMUM_ZIP_EPOCH = 315532800  # 1980-01-01T00:00:00Z
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")


def sha256_file(path: Path) -> str:
    """Return a lowercase SHA-256 digest for a file."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _version() -> str:
    version_file = PROJECT_ROOT / "health_edge_cases" / "__init__.py"
    match = re.search(
        r'^__version__ = "([^"]+)"$',
        version_file.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    if match is None or SEMVER.fullmatch(match.group(1)) is None:
        raise ValueError("health_edge_cases.__version__ must be a plain SemVer")
    return match.group(1)


def release_asset_names(version: str) -> tuple[str, ...]:
    """Return the exact, ordered public asset names for a version."""

    if SEMVER.fullmatch(version) is None:
        raise ValueError(f"Invalid release version: {version!r}")
    return (
        f"{NORMALIZED_PACKAGE_NAME}-{version}-py3-none-any.whl",
        f"{NORMALIZED_PACKAGE_NAME}-{version}.tar.gz",
        f"{PACKAGE_NAME}-{version}-contracts.zip",
        f"{PACKAGE_NAME}-{version}-provenance.json",
        "SHA256SUMS",
    )


def _validate_build_inputs(commit: str, source_date_epoch: int) -> None:
    if COMMIT_SHA.fullmatch(commit) is None:
        raise ValueError("commit must be a full lowercase Git commit SHA")
    if source_date_epoch < MINIMUM_ZIP_EPOCH:
        raise ValueError("SOURCE_DATE_EPOCH must be on or after 1980-01-01")


def _archive_timestamp(source_date_epoch: int) -> tuple[int, int, int, int, int, int]:
    timestamp = datetime.fromtimestamp(source_date_epoch, timezone.utc)
    # ZIP stores seconds at two-second precision.
    return (
        timestamp.year,
        timestamp.month,
        timestamp.day,
        timestamp.hour,
        timestamp.minute,
        timestamp.second - (timestamp.second % 2),
    )


def _bundle_source_files(project_root: Path) -> list[tuple[Path, str]]:
    """Resolve the explicit, tool-neutral bundle allowlist."""

    files: list[tuple[Path, str]] = []

    def add_file(source: str, destination: str | None = None) -> None:
        path = project_root / source
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"Bundle source must be a regular file: {source}")
        files.append((path, destination or source))

    def add_tree(source: str) -> None:
        root = project_root / source
        if not root.is_dir() or root.is_symlink():
            raise ValueError(f"Bundle source must be a directory: {source}")
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                raise ValueError(f"Bundle source must not be a symlink: {path}")
            if path.is_file():
                files.append((path, path.relative_to(project_root).as_posix()))

    add_tree("cases")
    add_tree("examples/external-results")
    add_file("docs/contracts/catalog-v1.json", "contracts/catalog-v1.json")
    add_file("schema/case.schema.json")
    add_file("schema/contract-catalog.schema.json")
    add_file("schema/verification-manifest.schema.json")
    add_file("schema/verification-result.schema.json")
    add_file("docs/DATA_DICTIONARY.md")
    add_file("docs/COMPARE_RESULTS.md")
    add_file("docs/VERIFY_SUITE.md")
    add_file("docs/RELEASE_ASSETS.md", "README.md")
    add_file("LICENSE")
    add_file("NOTICE")

    destinations = [destination for _, destination in files]
    if len(destinations) != len(set(destinations)):
        raise ValueError("Bundle allowlist maps multiple files to one destination")
    return sorted(files, key=lambda item: item[1])


def _render_json(payload: Mapping[str, object]) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n"
    ).encode("utf-8")


def build_contract_archive(
    output_path: Path,
    *,
    project_root: Path,
    version: str,
    commit: str,
    source_date_epoch: int,
) -> None:
    """Build the deterministic, tool-neutral contract bundle."""

    _validate_build_inputs(commit, source_date_epoch)
    if SEMVER.fullmatch(version) is None:
        raise ValueError(f"Invalid release version: {version!r}")
    source_files = _bundle_source_files(project_root)
    prefix = f"{PACKAGE_NAME}-{version}-contracts"
    generated_at = datetime.fromtimestamp(
        source_date_epoch, timezone.utc
    ).isoformat().replace("+00:00", "Z")

    catalog = json.loads(
        (project_root / "docs/contracts/catalog-v1.json").read_text(
            encoding="utf-8"
        )
    )
    if catalog.get("suite_version") != version:
        raise ValueError("Contract catalog suite_version does not match release")

    manifest_files = [
        {
            "path": destination,
            "sha256": sha256_file(source),
            "size": source.stat().st_size,
        }
        for source, destination in source_files
    ]
    manifest = {
        "schema_version": "1.0.0",
        "bundle_id": f"{PACKAGE_NAME}-contracts",
        "suite_version": version,
        "source_repository": SOURCE_REPOSITORY,
        "source_release": f"{SOURCE_REPOSITORY}/releases/tag/v{version}",
        "source_commit": commit,
        "source_date_epoch": source_date_epoch,
        "generated_at": generated_at,
        "catalog_digest": catalog.get("catalog_digest"),
        "files": manifest_files,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    zip_timestamp = _archive_timestamp(source_date_epoch)
    with zipfile.ZipFile(
        output_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for source, destination in source_files:
            _write_zip_member(
                archive,
                f"{prefix}/{destination}",
                source.read_bytes(),
                zip_timestamp,
            )
        _write_zip_member(
            archive,
            f"{prefix}/MANIFEST.json",
            _render_json(manifest),
            zip_timestamp,
        )


def _write_zip_member(
    archive: zipfile.ZipFile,
    name: str,
    content: bytes,
    timestamp: tuple[int, int, int, int, int, int],
) -> None:
    info = zipfile.ZipInfo(name, date_time=timestamp)
    info.create_system = 3
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    archive.writestr(info, content, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def _build_python_distributions(
    destination: Path,
    *,
    project_root: Path,
    source_date_epoch: int,
) -> None:
    env = dict(os.environ)
    env["SOURCE_DATE_EPOCH"] = str(source_date_epoch)
    env["PYTHONHASHSEED"] = "0"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--no-isolation",
            "--sdist",
            "--wheel",
            "--outdir",
            str(destination),
            str(project_root),
        ],
        check=True,
        cwd=project_root,
        env=env,
    )


def _require_byte_identical_builds(first: Path, second: Path) -> None:
    first_files = sorted(path.name for path in first.iterdir() if path.is_file())
    second_files = sorted(path.name for path in second.iterdir() if path.is_file())
    if first_files != second_files:
        raise ValueError(
            f"Independent build outputs differ: {first_files!r} != {second_files!r}"
        )
    for name in first_files:
        if sha256_file(first / name) != sha256_file(second / name):
            raise ValueError(f"Independent builds are not byte-identical: {name}")


def _distribution_subject(path: Path) -> dict[str, object]:
    return {
        "name": path.name,
        "digest": {"sha256": sha256_file(path)},
        "size": path.stat().st_size,
    }


def _package_version(distribution: str) -> str:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError as error:
        raise RuntimeError(
            f"{distribution} must be installed to create release provenance"
        ) from error


def write_provenance(
    output_path: Path,
    *,
    subjects: Iterable[Path],
    version: str,
    commit: str,
    source_date_epoch: int,
    workflow_run_id: str | None,
) -> None:
    """Write deterministic build provenance for non-circular subjects."""

    _validate_build_inputs(commit, source_date_epoch)
    subject_entries = [_distribution_subject(path) for path in subjects]
    generated_at = datetime.fromtimestamp(
        source_date_epoch, timezone.utc
    ).isoformat().replace("+00:00", "Z")
    payload: dict[str, object] = {
        "schema_version": "1.0.0",
        "project": PACKAGE_NAME,
        "version": version,
        "tag": f"v{version}",
        "source": {
            "repository": SOURCE_REPOSITORY,
            "release": f"{SOURCE_REPOSITORY}/releases/tag/v{version}",
            "commit": commit,
        },
        "build": {
            "source_date_epoch": source_date_epoch,
            "generated_at": generated_at,
            "python": platform.python_version(),
            "tools": {
                "build": _package_version("build"),
                "hatchling": _package_version("hatchling"),
            },
            "reproducibility": {
                "independent_builds": 2,
                "byte_identical": True,
            },
        },
        "subjects": subject_entries,
    }
    if workflow_run_id:
        payload["build"]["github_actions_run"] = (  # type: ignore[index]
            f"{SOURCE_REPOSITORY}/actions/runs/{workflow_run_id}"
        )
    output_path.write_bytes(_render_json(payload))


def write_checksums(output_path: Path, subjects: Iterable[Path]) -> None:
    lines = [
        f"{sha256_file(path)}  {path.name}"
        for path in sorted(subjects, key=lambda item: item.name)
    ]
    output_path.write_text("\n".join(lines) + "\n", encoding="ascii")


def _safe_archive_name(name: str) -> bool:
    path = Path(name)
    return (
        bool(name)
        and not path.is_absolute()
        and ".." not in path.parts
        and "\\" not in name
    )


def _validate_contract_archive(
    path: Path,
    *,
    version: str,
    commit: str,
    source_date_epoch: int,
) -> None:
    prefix = f"{PACKAGE_NAME}-{version}-contracts"
    expected_generated_at = datetime.fromtimestamp(
        source_date_epoch, timezone.utc
    ).isoformat().replace("+00:00", "Z")
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise ValueError("Contract bundle contains duplicate member names")
        if any(
            not _safe_archive_name(name)
            or not name.startswith(f"{prefix}/")
            or info.is_dir()
            or stat.S_ISLNK(info.external_attr >> 16)
            for name, info in zip(names, infos)
        ):
            raise ValueError("Contract bundle contains an unsafe member")
        manifest_name = f"{prefix}/MANIFEST.json"
        if manifest_name not in names:
            raise ValueError("Contract bundle MANIFEST.json is missing")
        manifest = json.loads(archive.read(manifest_name))
        expected_fields = {
            "schema_version",
            "bundle_id",
            "suite_version",
            "source_repository",
            "source_release",
            "source_commit",
            "source_date_epoch",
            "generated_at",
            "catalog_digest",
            "files",
        }
        if set(manifest) != expected_fields:
            raise ValueError("Contract bundle manifest fields differ")
        if (
            manifest["schema_version"] != "1.0.0"
            or manifest["bundle_id"] != f"{PACKAGE_NAME}-contracts"
            or manifest["suite_version"] != version
            or manifest["source_repository"] != SOURCE_REPOSITORY
            or manifest["source_release"]
            != f"{SOURCE_REPOSITORY}/releases/tag/v{version}"
            or manifest["source_commit"] != commit
            or manifest["source_date_epoch"] != source_date_epoch
            or manifest["generated_at"] != expected_generated_at
        ):
            raise ValueError("Contract bundle manifest provenance differs")

        listed = manifest["files"]
        if not isinstance(listed, list):
            raise ValueError("Contract bundle manifest files must be a list")
        listed_paths = [entry.get("path") for entry in listed if isinstance(entry, dict)]
        archive_paths = [
            name.removeprefix(f"{prefix}/")
            for name in names
            if name != manifest_name
        ]
        if listed_paths != sorted(archive_paths):
            raise ValueError("Contract bundle inventory differs from archive")
        for entry in listed:
            member = f"{prefix}/{entry['path']}"
            content = archive.read(member)
            if (
                entry.get("size") != len(content)
                or entry.get("sha256")
                != hashlib.sha256(content).hexdigest()
            ):
                raise ValueError(f"Contract bundle digest differs: {member}")

        catalog = json.loads(archive.read(f"{prefix}/contracts/catalog-v1.json"))
        if (
            catalog.get("suite_version") != version
            or catalog.get("source_release")
            != f"{SOURCE_REPOSITORY}/releases/tag/v{version}"
            or catalog.get("catalog_digest") != manifest["catalog_digest"]
        ):
            raise ValueError("Bundled catalog metadata differs from manifest")


def _validate_wheel(path: Path, version: str) -> None:
    metadata_suffix = ".dist-info/METADATA"
    with zipfile.ZipFile(path) as archive:
        metadata_files = [
            name for name in archive.namelist() if name.endswith(metadata_suffix)
        ]
        if len(metadata_files) != 1:
            raise ValueError("Wheel must contain exactly one METADATA file")
        metadata = archive.read(metadata_files[0]).decode("utf-8")
    if (
        f"\nName: {PACKAGE_NAME}\n" not in f"\n{metadata}"
        or f"\nVersion: {version}\n" not in f"\n{metadata}"
    ):
        raise ValueError("Wheel metadata name or version differs")


def _validate_sdist(path: Path, version: str) -> None:
    prefix = f"{NORMALIZED_PACKAGE_NAME}-{version}"
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
        if any(
            not _safe_archive_name(member.name)
            or not member.name.startswith(f"{prefix}/")
            or member.issym()
            or member.islnk()
            or member.isdev()
            for member in members
        ):
            raise ValueError("Source distribution contains an unsafe member")
        metadata_members = [
            member for member in members if member.name == f"{prefix}/PKG-INFO"
        ]
        if len(metadata_members) != 1:
            raise ValueError("Source distribution PKG-INFO is missing")
        extracted = archive.extractfile(metadata_members[0])
        if extracted is None:
            raise ValueError("Source distribution PKG-INFO is unreadable")
        metadata = extracted.read().decode("utf-8")
    if (
        f"\nName: {PACKAGE_NAME}\n" not in f"\n{metadata}"
        or f"\nVersion: {version}\n" not in f"\n{metadata}"
    ):
        raise ValueError("Source distribution metadata name or version differs")


def validate_release_directory(
    directory: Path,
    *,
    version: str,
    commit: str,
    source_date_epoch: int,
) -> None:
    """Validate exact asset names, archive safety, provenance, and digests."""

    _validate_build_inputs(commit, source_date_epoch)
    expected_names = release_asset_names(version)
    entries = list(directory.iterdir())
    if any(not path.is_file() or path.is_symlink() for path in entries):
        raise ValueError("Release directory must contain regular files only")
    actual_names = tuple(sorted(path.name for path in entries))
    if actual_names != tuple(sorted(expected_names)):
        raise ValueError(
            f"Release assets differ: {actual_names!r} != {sorted(expected_names)!r}"
        )
    paths = {name: directory / name for name in expected_names}
    wheel_name, sdist_name, bundle_name, provenance_name, checksum_name = (
        expected_names
    )
    _validate_wheel(paths[wheel_name], version)
    _validate_sdist(paths[sdist_name], version)
    _validate_contract_archive(
        paths[bundle_name],
        version=version,
        commit=commit,
        source_date_epoch=source_date_epoch,
    )

    provenance = json.loads(paths[provenance_name].read_text(encoding="utf-8"))
    if (
        provenance.get("schema_version") != "1.0.0"
        or provenance.get("project") != PACKAGE_NAME
        or provenance.get("version") != version
        or provenance.get("tag") != f"v{version}"
        or provenance.get("source")
        != {
            "repository": SOURCE_REPOSITORY,
            "release": f"{SOURCE_REPOSITORY}/releases/tag/v{version}",
            "commit": commit,
        }
    ):
        raise ValueError("Release provenance identity differs")
    build = provenance.get("build")
    expected_generated_at = datetime.fromtimestamp(
        source_date_epoch, timezone.utc
    ).isoformat().replace("+00:00", "Z")
    if (
        not isinstance(build, dict)
        or build.get("source_date_epoch") != source_date_epoch
        or build.get("generated_at") != expected_generated_at
        or build.get("reproducibility")
        != {"independent_builds": 2, "byte_identical": True}
    ):
        raise ValueError("Release build provenance differs")

    subject_names = (wheel_name, sdist_name, bundle_name)
    expected_subjects = [
        _distribution_subject(paths[name]) for name in subject_names
    ]
    if provenance.get("subjects") != expected_subjects:
        raise ValueError("Release provenance subjects differ")

    checksum_lines = paths[checksum_name].read_text(encoding="ascii").splitlines()
    checksum_names = (wheel_name, sdist_name, bundle_name, provenance_name)
    expected_lines = [
        f"{sha256_file(paths[name])}  {name}" for name in sorted(checksum_names)
    ]
    if checksum_lines != expected_lines:
        raise ValueError("SHA256SUMS content differs")


def build_release_directory(
    output_dir: Path,
    *,
    project_root: Path,
    version: str,
    commit: str,
    source_date_epoch: int,
    workflow_run_id: str | None,
) -> None:
    """Create exactly five release files after two identical Python builds."""

    _validate_build_inputs(commit, source_date_epoch)
    if version != _version():
        raise ValueError(
            f"Requested version {version!r} != project version {_version()!r}"
        )
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f"Output directory must be empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(
        prefix="edge-release-build-", dir=output_dir.parent
    ) as temporary:
        temp_root = Path(temporary)
        first = temp_root / "first"
        second = temp_root / "second"
        first.mkdir()
        second.mkdir()
        _build_python_distributions(
            first,
            project_root=project_root,
            source_date_epoch=source_date_epoch,
        )
        _build_python_distributions(
            second,
            project_root=project_root,
            source_date_epoch=source_date_epoch,
        )
        _require_byte_identical_builds(first, second)

        expected = release_asset_names(version)
        wheel_name, sdist_name, bundle_name, provenance_name, checksum_name = (
            expected
        )
        built_names = {path.name for path in first.iterdir() if path.is_file()}
        if built_names != {wheel_name, sdist_name}:
            raise ValueError(
                f"Python build produced unexpected files: {sorted(built_names)}"
            )
        shutil.copyfile(first / wheel_name, output_dir / wheel_name)
        shutil.copyfile(first / sdist_name, output_dir / sdist_name)

        build_contract_archive(
            output_dir / bundle_name,
            project_root=project_root,
            version=version,
            commit=commit,
            source_date_epoch=source_date_epoch,
        )
        write_provenance(
            output_dir / provenance_name,
            subjects=(
                output_dir / wheel_name,
                output_dir / sdist_name,
                output_dir / bundle_name,
            ),
            version=version,
            commit=commit,
            source_date_epoch=source_date_epoch,
            workflow_run_id=workflow_run_id,
        )
        write_checksums(
            output_dir / checksum_name,
            subjects=(
                output_dir / wheel_name,
                output_dir / sdist_name,
                output_dir / bundle_name,
                output_dir / provenance_name,
            ),
        )
        validate_release_directory(
            output_dir,
            version=version,
            commit=commit,
            source_date_epoch=source_date_epoch,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "release-dist",
    )
    parser.add_argument("--version", default=_version())
    parser.add_argument("--commit", required=True)
    parser.add_argument("--source-date-epoch", type=int, required=True)
    parser.add_argument("--workflow-run-id")
    args = parser.parse_args()

    build_release_directory(
        args.output_dir.resolve(),
        project_root=PROJECT_ROOT,
        version=args.version,
        commit=args.commit,
        source_date_epoch=args.source_date_epoch,
        workflow_run_id=args.workflow_run_id,
    )
    for path in sorted(args.output_dir.iterdir()):
        print(f"{sha256_file(path)}  {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
