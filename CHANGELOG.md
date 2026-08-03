# Changelog

All notable changes are documented here. The project follows semantic versioning.

## [0.4.0] - 2026-08-03

### Added

- A dependency-free `validate-case` command for authoring checks without SQL
  execution
- A version-and-catalog-digest-bound `verify` command for all five external
  result pairs, with stable `0`/`1`/`2` exit semantics
- Closed, versioned JSON manifest and result schemas plus deterministic JUnit
  output for matches, mismatches and invalid input
- A token-free composite GitHub Action with bounded local inputs, workflow
  summary, report-path outputs and a hosted positive/negative contract gate

### Changed

- Python, DuckDB and the independent base-R path now reject malformed UTC
  timestamps, invalid or reversed reporting dates, and dangling non-empty
  referral or appointment links before calculation
- CSV, JSON, row, cell and key quotas plus symlink rejection bound untrusted CI
  result processing
- The tool-neutral contract archive now includes the verification schemas and
  complete-suite workflow documentation

### Unchanged

- The five synthetic cases and all 72 expected results retain their v0.3.2
  meanings

## [0.3.2] - 2026-08-03

### Changed

- Upgraded the pinned `actions/attest` dependency from v4.2.0 to v4.2.1, as
  identified in Dependabot pull request #14

### Unchanged

- CI still signs exactly the five local release files and does not enable the
  action's OCI registry path
- The release-asset formats, external-results comparator, five synthetic cases
  and all 72 expected results retain their v0.3.1 meanings

## [0.3.1] - 2026-08-03

### Changed

- Upgraded the pinned `actions/download-artifact` dependency from v7.0.0 to
  v8.0.1 for same-run wheel validation, release-asset attestation and the
  exact-run release handoff, as identified by Dependabot pull request #12
- Artifact-envelope digest mismatches now fail by default before the existing
  checksum, provenance, archive, attestation and byte-comparison gates run

### Unchanged

- The external-results comparator, five synthetic cases and all 72 expected
  results retain their v0.3.0 meanings

## [0.3.0] - 2026-08-03

### Added

- A dependency-free `compare` command for testing external aggregate metric and
  quality CSV exports without executing the reference SQL, contributed through
  pull request #8 by `@AshSgDe29071999`
- Command-level coverage for matching, mismatching and invalid external exports
- Precision-safe JSON output and explicit `0`/`1`/`2` exit-code semantics for
  matches, mismatches and invalid input

### Changed

- External results now reject blank keys, duplicate keys, malformed CSV,
  decimals, exponents and non-ASCII integer digits before comparison
- Composite result keys are rendered as escaped structured values so terminal
  and CI output cannot collapse distinct keys or emit raw control characters
- UTF-8 byte-order marks, optional integer signs, leading zeroes and integers
  larger than native JavaScript precision are handled deterministically

### Unchanged

- The five synthetic cases and all 72 expected results retain their v0.2
  meanings

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
