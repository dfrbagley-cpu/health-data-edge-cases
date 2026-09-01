# Verify a complete external result set

The suite verifier checks aggregate outputs for every published synthetic case in
one deterministic operation. It reads CSV and JSON files only. It does not run
your SQL, scripts, binaries, workflow commands, or reference implementation.

## Create an integration workspace

The recommended starting point is the scaffold command from the same installed
release that will perform verification:

```bash
health-data-edge-cases scaffold edge-integration
cd edge-integration
```

The command creates a new destination atomically and never replaces an existing
file, directory, or symlink. `fixtures/` contains each public synthetic case
manifest and its six input CSVs, but no expected-output values. `results/`
contains the release-bound manifest and header-only aggregate templates.
Native no-replace publication is supported on Windows, Linux, and macOS. If the
platform cannot provide that guarantee, scaffolding exits `2` without publishing
a partial workspace.

The root `result-keys.json` is bound to the same suite version and catalog
digest. It lists each case ID and the exact metric and quality key tuples needed
to shape output rows, but contains no expected values. The verifier—not this
key-only shaping contract—remains the source of truth for pass or failure.

Run a production-equivalent transformation against each fixture directory and
write its aggregate outputs into the matching result directory. Before those
outputs are populated, `verify` treats the empty templates as valid empty result
sets and exits `1` with every expectation missing. Malformed values still exit
`2`.

## Result-directory contract

Create this exact tree:

```text
results/
  verification-manifest.json
  appointment-encounter-status-conflict/
    actual_metrics.csv
    actual_quality.csv
  duplicate-encounter-versions/
    actual_metrics.csv
    actual_quality.csv
  like-for-like-partial-periods/
    actual_metrics.csv
    actual_quality.csv
  many-to-many-join-inflation/
    actual_metrics.csv
    actual_quality.csv
  unmapped-program-retention/
    actual_metrics.csv
    actual_quality.csv
```

Each case uses the exact aggregate-file contract in
[Compare external reporting results](COMPARE_RESULTS.md). Extra, missing, or
symlinked entries are rejected before comparison.

Generate the identity manifest from the same installed release that will verify
the results:

```bash
health-data-edge-cases manifest > results/verification-manifest.json
```

The manifest binds the result set to the official catalog ID, suite version, and
catalog digest. It does not prove which fixtures a pipeline executed, who
created the files, or whether a source system is correct.

## Run the verifier

```bash
health-data-edge-cases verify \
  --results results \
  --json-output verification-result.json \
  --junit-output verification-junit.xml
```

The command prints a console summary and can write both versioned JSON and JUnit
XML in the same pass. Exit codes are stable:

- `0`: every published expectation matched;
- `1`: valid aggregate files contained one or more mismatches;
- `2`: the manifest, directory tree, CSV, or other input was invalid.

Pass `--json` to emit the JSON result on standard output. Invalid verification
input still produces JSON and JUnit error reports when output paths are supplied.
The schemas are
[`verification-manifest.schema.json`](../schema/verification-manifest.schema.json)
and [`verification-result.schema.json`](../schema/verification-result.schema.json).

## GitHub Action

The repository root is a composite Action. It requires only a Python 3.10 or
newer runtime, reads local result files, performs no network request, and does not
use `GITHUB_TOKEN`.

```yaml
permissions:
  contents: read

steps:
  - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
  - uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0
    with:
      python-version: "3.12"
  - id: edge
    uses: dfrbagley-cpu/health-data-edge-cases@v0.5.0
    with:
      results: build/edge-results
  - uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1
    if: always()
    with:
      name: edge-conformance-reports
      path: |
        ${{ steps.edge.outputs.json-report }}
        ${{ steps.edge.outputs.junit-report }}
```

The Action writes a workflow summary and exposes the pass flag, exact suite
identity, counts, and report paths. Its default reports live in a unique runner
temporary directory. The results directory must be inside `GITHUB_WORKSPACE` or
`RUNNER_TEMP`; symlinked paths are rejected. For an immutable dependency,
replace `v0.5.0` with the release's full 40-character commit SHA. Do not use an
unreviewed moving branch.

## Resource and data boundary

The verifier rejects oversized manifests, CSVs, rows, cells, keys, malformed
quoting, duplicate keys, noncanonical integers, and symlinked result trees. These
are safety limits, not an invitation to process sensitive data.

Use only aggregate period, metric, and quality-check keys. Never place patient,
encounter, referral, appointment, medical-record, employer, or other confidential
identifiers in result files or CI logs.

A passing result means only that the supplied aggregate files match this release's
published synthetic expected-output contracts. It is not certification and does
not establish implementation quality outside those cases.
