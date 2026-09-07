# Reporting semantics packs

Three additional, independently authored synthetic packs demonstrate referral
chronology, historical reporting cutoffs, and effective-dated mappings. They are
separate from the original five-case / 72-expectation verification catalog.
The original `run`, `compare`, `verify`, and `scaffold` commands retain their scope.

Run from a checkout or a normally installed package:

```bash
python -m health_edge_cases packs
python -m health_edge_cases packs --json
python -m health_edge_cases packs --naive
```

The reference command passes 16 expectations across three packs (exit 0).
The deliberately wrong implementation fails in each pack (exit 1). Invalid
arguments exit 2. No external dataset or arbitrary SQL is accepted by this command.
For portable SQL, install the optional DuckDB dependency and run
`python -m health_edge_cases packs --engine duckdb`. From a checkout, run the
independent base R implementation with `Rscript R/run_reporting_packs.R`.

## Questions and expected interpretations

| Pack | Question | Correct result | Deliberate mistake |
|---|---|---|---|
| Referral chronology | Which referrals have completed or ongoing waits at cutoff? | Five starts by cutoff: two completed, two ongoing, one invalid sequence. One completed service is same-day. | Treat any populated service date as completed, including impossible and future dates. |
| Historical cutoff | What did the August report know on August 31? | Three completed events known then, three in the latest revision, but different membership: one late arrival and one later void. | Rank all versions before applying the knowledge cutoff, erasing an earlier valid version. |
| Effective-dated mappings | Which category applied when service occurred? | Five events: three mapped once, one unmapped, one ambiguous. The exact change date uses the new category. | Use an inner join and count joined rows, hiding missing mappings and inflating overlaps. |

Each pack under `health_edge_cases/packs/` includes input CSVs, hand-specified
`expected.csv`, portable `reference.sql`, and `naive.sql`. SQL and R compute
results independently. Expected values are not generated from either runner.

## Data dictionary and boundaries

All identifiers starting `SYN-` are invented. All dates are valid YYYY-MM-DD
calendar dates at day granularity; no timezone conversion is performed. These
are explanatory public rules, not a licensed reporting specification.

- Referral inputs: `referral_id` identifies a referral; `referred_on` starts it;
  `first_service_on` is blank for an ongoing referral; `cutoff` is inclusive.
  A service after cutoff remains ongoing at that cutoff. A service before
  referral is invalid, not a negative wait to repair. Future referral starts are
  outside the cohort. Completed and ongoing waiting populations remain separate.
- Historical inputs: `event_id` identifies the source event; `version` is a
  unique increasing integer within it; `known_on` is when that version became
  available; `service_on` is when service occurred; `status` controls eligibility.
  Retained versions are required. These fixtures assume version order and
  knowledge order agree. Current overwritten data cannot recover missing history.
- Mapping inputs: `program` is the local code; `category` is its public synthetic
  reporting category; `valid_from` is inclusive and `valid_to` exclusive.
  More than one applicable row is ambiguous even if category labels agree.
  Missing and ambiguous mappings stay visible and require resolution.

The examples test logic on bundled fixtures. Passing them does not establish
that an organization's inputs are complete, that its definitions match these
examples, or that its pipeline implements the same rules.

For repeated checks of approved CSV snapshots, use the companion
[monthly report check](https://dfrbagley-cpu.github.io/healthcare-reporting-toolkit/report-check.html).
It saves explicit profiles and reconciles eligible event counts. It does not
execute these SQL packs, reconstruct history, or apply effective-dated joins.
The original toolkit results checker remains pinned to its published catalog.
