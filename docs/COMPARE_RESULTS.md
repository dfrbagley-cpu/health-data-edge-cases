# Compare external reporting results

The suite is implementation-neutral. You can load a case into SQL, R, Python, a BI tool, or another reporting stack, run your own logic, and compare its aggregate outputs with the canonical expectations.

The versioned contract catalog is the machine-readable source for case narratives,
expected values, result-file columns, provenance, and content integrity. It is
`docs/contracts/catalog-v1.json` in the source repository and
`contracts/catalog-v1.json` in the downloadable contract bundle. It contains no
input records or real health information.

## Export two aggregate files

Export metrics with this exact header:

```csv
period_id,metric_id,actual_value
```

Export quality checks with this exact header:

```csv
check_id,actual_value
```

Keys cannot be blank or duplicated. Values must use ASCII base-10 integer text
matching `[+-]?[0-9]+`; decimals and exponent notation are invalid. A
conformance comparison treats a missing key, unexpected key, or incorrect value
as a mismatch and rejects invalid input before comparison.

The example for `unmapped-program-retention` includes:

- [`matching`](../examples/external-results/unmapped-program-retention/matching), which reproduces all thirteen expectations;
- [`inner-join-failure`](../examples/external-results/unmapped-program-retention/inner-join-failure), which deliberately loses the unmapped event.


## Compare with the CLI

From a source checkout, run:

```bash
python scripts/compare_results.py \
  --case unmapped-program-retention \
  --metrics examples/external-results/unmapped-program-retention/matching/actual_metrics.csv \
  --quality examples/external-results/unmapped-program-retention/matching/actual_quality.csv
```

After installing the wheel, run the same comparison from any directory with:

```bash
health-data-edge-cases compare \
  --case unmapped-program-retention \
  --metrics /path/to/actual_metrics.csv \
  --quality /path/to/actual_quality.csv
```

A match exits `0`, a conformance mismatch exits `1`, and invalid input or usage
exits `2`. Mismatch output prints escaped structured keys so separate composite
keys remain unambiguous in terminal and CI logs. Add `--json` for
precision-safe machine output; integer values are emitted as strings.

These examples are synthetic aggregate results. The repository tests verify that the matching files remain exact and that the failing files retain the intended five mismatches.

## Read the failing pattern carefully

The deliberately failing files produce:

| Result | Expected | Actual |
|---|---:|---:|
| Completed service events | 2 | 1 |
| Unique synthetic patients served | 2 | 1 |
| Unmapped completed events | 1 | 0 |
| Referrals reaching first service | 2 | 1 |
| Completed encounters without a mapping | 1 | 0 |

That combination is consistent with activity being removed before aggregation—for example, by an inner join to a mapping table. It does **not** prove that an inner join caused the result. Filters, stale extracts, relationship errors, or upstream data loss can produce similar numbers. Use the case's source rows and your query plan to establish the actual cause.

The corrected rule retains source activity through a left join, reports mapped and unmapped events separately, and surfaces the missing mapping as a quality signal.

## Privacy and logging boundary

Use only aggregate period, metric, and quality-check keys in external result files. Do not use patient, encounter, referral, appointment, medical-record, or other record-level identifiers.

Comparison tools may print keys and values to terminals or continuous-integration logs. Local processing prevents an upload by itself; it does not prevent shell history, retained build logs, screenshots, or copied output from disclosing whatever you put in those fields.

The examples are evidence contracts, not certification, regulatory policy, or proof that source data is correct.
