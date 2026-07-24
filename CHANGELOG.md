# Changelog

All notable changes are documented here. The project follows semantic versioning.

## [0.1.0] - 2026-07-23

### Added

- Four deterministic operational-reporting edge cases
- Portable SQLite/DuckDB-style reference SQL
- Pinned DuckDB 1.5.5 execution gate in CI
- Dependency-free Python runner with JSON output
- Independent base-R reference implementation
- Fifty-nine exact metric and quality expectations
- Deterministic HTML validation report
- Automated Python, SQL, report, privacy-boundary, and R checks
- Contribution, security, citation, and case-authoring documentation
- Installable wheel containing the synthetic fixtures and reference SQL
- Installed-artifact checks across the supported Python range
- Strict manifest, CSV-shape, identifier, foreign-key, and result-key validation
- Accessible labels and keyboard focus for report tables

### Fixed

- Reject duplicate or fractional query results instead of allowing false passes
- Reject string-valued synthetic-data declarations and incomplete case manifests
