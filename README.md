# Health Data Edge Cases

[![Conformance suite](https://github.com/dfrbagley-cpu/health-data-edge-cases/actions/workflows/ci.yml/badge.svg)](https://github.com/dfrbagley-cpu/health-data-edge-cases/actions/workflows/ci.yml)
[![Live validation report](https://img.shields.io/badge/Live_validation-report-0d6572)](https://dfrbagley-cpu.github.io/health-data-edge-cases/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

**Catch plausible-but-wrong healthcare reporting results before they reach a dashboard.**

A query can run successfully while an inner join drops half the activity or a
many-to-many join doubles it. This suite gives analysts and data engineers five
small synthetic datasets, explicit rules, and **72 executable expectations**
to test those mistakes in SQL, R, Python, or another reporting stack.

[**Try the browser checker →**](https://dfrbagley-cpu.github.io/healthcare-reporting-toolkit/#validate)
No install, account, or upload. The companion Toolkit checks files in your
browser and includes a deliberately mismatched synthetic example.

[Validation report](https://dfrbagley-cpu.github.io/health-data-edge-cases/) ·
[Product case study](docs/CASE_STUDY.md) ·
[Contribute](CONTRIBUTING.md)

## See a plausible result fail

In the [unmapped-program case](cases/unmapped-program-retention), two completed
services exist, but only one has a program mapping. The provided failing export
shows what happens when unmapped activity disappears:

| Result | Expected | Failing export |
|---|---:|---:|
| Completed service events | 2 | 1 |
| Unique synthetic patients served | 2 | 1 |
| Unmapped completed events | 1 | 0 |

The contract retains both services and flags the missing mapping separately.
[Inspect all five mismatches and their limits](docs/COMPARE_RESULTS.md#read-the-failing-pattern-carefully).
This pattern helps investigate a discrepancy; it does not prove its cause.

## Run the suite locally

Python 3.10 or later is the only requirement. No third-party packages are needed.

```bash
git clone https://github.com/dfrbagley-cpu/health-data-edge-cases.git
cd health-data-edge-cases
python scripts/run_suite.py
```

Expected result:

```text
PASS  appointment-encounter-status-conflict  (13 expectations)
PASS  duplicate-encounter-versions  (13 expectations)
PASS  like-for-like-partial-periods  (20 expectations)
PASS  many-to-many-join-inflation  (13 expectations)
PASS  unmapped-program-retention  (13 expectations)
PASS  suite: 5/5 cases, 72 expectations
```

Then run the deliberately failing export from the same directory:

```bash
python scripts/compare_results.py --case unmapped-program-retention --metrics examples/external-results/unmapped-program-retention/inner-join-failure/actual_metrics.csv --quality examples/external-results/unmapped-program-retention/inner-join-failure/actual_quality.csv
```

Copy the command as one line in Bash, PowerShell, or Command Prompt. See
[Windows terminal notes](docs/USAGE.md#windows-terminals) for checking exit codes.

It prints five mismatches and exits `1` intentionally. Replace `inner-join-failure`
with `matching` in **both paths** to see all 13 expectations pass with exit `0`.
The comparison checks the supplied aggregate files; it does not run their
upstream transformation.

## Test your own reporting logic

Run your transformation against the synthetic input files, export its aggregate
results, and compare them with the expected answers. Start with one case; add the
complete suite to CI once the first case works.

| Your goal | Start here |
|---|---|
| Understand a reporting failure without installing anything | [Browser checker](https://dfrbagley-cpu.github.io/healthcare-reporting-toolkit/#validate) |
| Check one transformation's output | [External-results walkthrough](docs/COMPARE_RESULTS.md) |
| Create an integration workspace | [Setup and scaffold guide](docs/USAGE.md#integrate-a-reporting-pipeline) |
| Verify every case in CI with JSON and JUnit reports | [Complete-suite verifier and GitHub Action](docs/VERIFY_SUITE.md) |
| Review product decisions and implementation evidence | [Product case study](docs/CASE_STUDY.md) |

A passing reference run proves the included implementation matches these cases.
To check your implementation, you must produce the result files with your own
logic. Passing those checks covers these contracts, not every possible failure.

## Included cases

| Case | What naive logic gets wrong | Contract tested |
|---|---|---|
| [Duplicate encounter versions](cases/duplicate-encounter-versions) | Counts four completed rows instead of two current service events | Rank versions, keep one current event, then apply status |
| [Appointment/encounter conflict](cases/appointment-encounter-status-conflict) | Drops delivered care because scheduling status says cancelled | Count service from the encounter; flag the conflict separately |
| [Unmapped program retention](cases/unmapped-program-retention) | Silently loses half the activity through an inner join | Preserve source activity and expose unmapped records |
| [Like-for-like partial periods](cases/like-for-like-partial-periods) | Compares unequal elapsed periods | Make both inclusive as-of windows explicit |
| [Many-to-many join inflation](cases/many-to-many-join-inflation) | Turns two referrals and two services into four joined rows | Join on explicit relationships and restore event grain before aggregation |

The reference SQL runs in SQLite and DuckDB; an independent base-R implementation
checks the same expectations. See the [design notes](docs/DESIGN_NOTES.md),
[data dictionary](docs/DATA_DICTIONARY.md), and [versioned contract catalog](docs/contracts/catalog-v1.json).

## Help improve one case

You do not need to build a new feature to contribute. Try the failing example,
check whether the explanation makes the error clear, and
[share what worked or blocked you](https://github.com/dfrbagley-cpu/health-data-edge-cases/issues/new?template=usage-feedback.yml).
Or choose a [small contribution with explicit acceptance criteria](CONTRIBUTING.md#small-ways-to-start).

Have another failure mode? [Propose a case](https://github.com/dfrbagley-cpu/health-data-edge-cases/issues/new?template=edge-case.yml)
with one rule, the smallest invented dataset, and a defensible expected result.
See [Adding a case](docs/ADDING_A_CASE.md) before preparing a larger contribution.

## Scope and credits

All fixtures are independently designed and synthetic. No real patient data,
employer data, proprietary schemas, or licensed reporting specifications are
included. These contracts are explicit test policies, not universal clinical,
billing, or regulatory rules, and the suite is not certification or a production
hospital implementation. Read the [publication policy](PUBLICATION_POLICY.md)
before sharing examples.

David Bagley owns the product decisions, domain rules, scope, and validation.
Implementation includes AI-assisted development and a
[credited open-source contribution](https://github.com/dfrbagley-cpu/health-data-edge-cases/pull/8).
The [case study](docs/CASE_STUDY.md) explains that division of work and the limits
of the evidence.

Code, documentation, and synthetic fixtures use the [Apache License 2.0](LICENSE).
[Citation metadata](CITATION.cff) · [Changelog](CHANGELOG.md) · [Security](SECURITY.md)
