# Verified release assets

Each GitHub Release contains exactly five files built from the same successful
`main` commit:

| File | Purpose |
| --- | --- |
| `health_data_edge_cases-<version>-py3-none-any.whl` | Installable Python package with the reference runner, synthetic fixtures and portable SQL |
| `health_data_edge_cases-<version>.tar.gz` | Python source distribution |
| `health-data-edge-cases-<version>-contracts.zip` | Tool-neutral cases, schemas, expected results, examples and documentation |
| `health-data-edge-cases-<version>-provenance.json` | Source commit, deterministic-build inputs, tool versions and SHA-256 subjects |
| `SHA256SUMS` | SHA-256 checksums for the other four files |

The contract ZIP is the simplest choice for SQL, R, BI or other non-Python
workflows. It has one versioned top-level directory and an explicit
`MANIFEST.json`. The manifest identifies the source commit and release, records
the canonical catalog digest, and gives the byte length and SHA-256 digest of
every included file.

## Use the Python wheel

Create an isolated environment, install the downloaded wheel, then run the
reference suite:

```sh
VERSION=0.2.1
python -m venv .venv
.venv/bin/python -m pip install \
  "health_data_edge_cases-${VERSION}-py3-none-any.whl"
.venv/bin/health-data-edge-cases
.venv/bin/python -m health_edge_cases --json > result.json
```

DuckDB remains an optional, independently pinned reference:

```sh
.venv/bin/python -m pip install duckdb==1.5.5
.venv/bin/python -m health_edge_cases.duckdb_runner
```

## Use the tool-neutral bundle

Extract the archive and begin with its manifest and canonical catalog:

```sh
VERSION=0.2.1
unzip "health-data-edge-cases-${VERSION}-contracts.zip"
cd "health-data-edge-cases-${VERSION}-contracts"
python -m json.tool MANIFEST.json >/dev/null
python -m json.tool contracts/catalog-v1.json >/dev/null
```

The `cases/` directory contains the synthetic input and expected-output CSV
files. `schema/` describes case manifests and the catalog. `examples/` contains
matching and deliberately failing aggregate outputs, while `docs/` explains the
data and comparison contract.

## Verify a download

Download all five files from one release into the same directory, then run:

```sh
VERSION=0.2.1
sha256sum --check SHA256SUMS
for artifact in \
  "health_data_edge_cases-${VERSION}-py3-none-any.whl" \
  "health_data_edge_cases-${VERSION}.tar.gz" \
  "health-data-edge-cases-${VERSION}-contracts.zip" \
  "health-data-edge-cases-${VERSION}-provenance.json" \
  SHA256SUMS
do
  gh attestation verify "$artifact" \
    --repo dfrbagley-cpu/health-data-edge-cases \
    --signer-workflow dfrbagley-cpu/health-data-edge-cases/.github/workflows/ci.yml \
    --source-ref refs/heads/main \
    --deny-self-hosted-runners
done
```

The checksum file detects changed bytes. The GitHub artifact attestations add
independent evidence that the repository's `Conformance suite` workflow
produced those bytes from the identified `main` commit. Neither mechanism
certifies the correctness of a downstream implementation or the suitability
of these generic synthetic contracts for a particular organization.

## Reproducibility boundary

CI builds the wheel and source distribution twice with the exact Git commit
timestamp as `SOURCE_DATE_EPOCH` and requires byte-identical output. The bundle
uses a sorted allowlist, fixed permissions and the same timestamp. Provenance
records the pinned build tool versions and exact non-circular subjects.

The release workflow does not check out or execute repository code. It accepts
only the artifact from the successful `main` CI run that triggered it, verifies
the five filenames, checksums, archive metadata, provenance and attestations,
then uploads a draft. It publishes only after downloading the draft assets and
comparing them byte-for-byte.

Version 0.2.1 changes distribution, release provenance and catalog
version/source/digest metadata only. Its five case definitions and 72
expectation semantics are compatible with v0.2.0.
