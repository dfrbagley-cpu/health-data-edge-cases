# Adding a case

A good case proves one reporting failure with the smallest dataset that makes the failure undeniable.

## Before writing fixtures

Open an issue that answers:

1. What plausible implementation produces the wrong result?
2. Why does the error matter operationally?
3. What exact rule produces the defensible result?
4. Can the example be created without real data, employer-derived structure, proprietary vendor material, or licensed specifications?

If the expected answer depends on local policy, say so. The project can test explicit policy choices, but it should not present them as universal healthcare rules.

## Build the case

1. Copy an existing directory under `cases/`.
2. Rename it with a short lowercase kebab-case ID.
3. Update `case.json`; the `id` must match the directory.
4. Reduce every input CSV to only the rows needed to prove the failure.
5. Use patient tokens beginning with `SYN-`.
6. Enter all expected metric and quality values explicitly.
7. Run both reference implementations.

```bash
python scripts/run_suite.py
Rscript R/run_suite.R
python scripts/build_report.py
python -m unittest discover -s tests -v
```

## Acceptance checklist

- [ ] One narrow edge case
- [ ] Clear naive failure and expected resolution
- [ ] Entirely synthetic, independently designed data
- [ ] No names, dates of birth, contact details, health-card numbers, or medical-record numbers
- [ ] No employer, customer, or vendor identifiers
- [ ] No copied proprietary schemas or licensed reporting text
- [ ] Deterministic expected values
- [ ] Python/SQL and R reference implementations agree
- [ ] Generated report is current
- [ ] Data dictionary updated if a field, metric, or check changes
- [ ] Changelog entry added

## When a new rule is needed

Prefer adding a case before changing shared logic. A case creates a reviewable contract and exposes the consequences of the proposed rule.

If the change alters the meaning of an existing expected result, explain why the old contract was wrong or incomplete. Do not silently update the number to make CI pass.
