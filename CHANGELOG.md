# Changelog

All notable changes are documented here. The project follows semantic versioning.

## [0.2.1] - 2026-07-26

### Added

- Verified GitHub Release downloads: a wheel, source distribution, tool-neutral
  contract bundle, build-provenance document and `SHA256SUMS`
- A deterministic contract-bundle manifest with an explicit source allowlist
  and per-file sizes and SHA-256 digests
- GitHub artifact attestations for all five release files
- Python 3.10 and 3.12 smoke tests that install and run the exact wheel later
  presented for release
- Release-asset documentation for Python and tool-neutral consumers

### Changed

- Python distributions are independently built twice from the exact commit
  timestamp and must be byte-identical
- The post-CI release gate now downloads only the triggering successful
  `main` run's commit-keyed artifact, verifies it without checking out
  repository code, uploads a draft, compares remote bytes, and only then
  publishes
- Source-distribution contents now use an explicit allowlist

## [0.2.0] - 2026-07-25

### Added

- A many-to-many join-inflation case proving why patient-and-program joins cannot replace explicit event relationships
- A canonical public JSON contract catalog with deterministic provenance and a content SHA-256 digest
- A published JSON Schema and catalog generation/check command
- Matching and deliberately failing synthetic external-result examples with a diagnostic walkthrough
- Regression coverage for join cardinality, catalog integrity, generated-artifact freshness, and synchronized version metadata

### Changed

- Expanded the suite to five cases and seventy-two exact expectations
- CI and GitHub Pages now validate the committed contract catalog before publication

## [0.1.0] - 2026-07-23

### Added

- Four deterministic operational-reporting edge cases
- Portable SQLite/DuckDB-style reference SQL
- Pinned DuckDB 1.5.5 execution gate in CI
- Dependency-free Python runner with JSON output
- Independent base-R reference implementation
- Fifty-nine exact metric and quality expectations
- Deterministic HTML validation report
- GitHub Pages deployment for the verified validation report
- Automated Python, SQL, report, privacy-boundary, and R checks
- Contribution, security, citation, and case-authoring documentation
- Installable wheel containing the synthetic fixtures and reference SQL
- Installed-artifact checks across the supported Python range
- Strict manifest, CSV-shape, identifier, foreign-key, and result-key validation
- Accessible labels and keyboard focus for report tables
- An exact-head post-CI gate for version tags and GitHub Releases

### Fixed

- Reject duplicate or fractional query results instead of allowing false passes
- Reject string-valued synthetic-data declarations and incomplete case manifests
