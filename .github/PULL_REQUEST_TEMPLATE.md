## What changed

<!-- Describe the case, implementation, or documentation change. -->

## Why it matters

<!-- Explain the reporting failure, ambiguity, or maintenance problem. -->

## Publication boundary

- [ ] All data is synthetic and independently designed.
- [ ] No patient, employer, customer, vendor-confidential, or licensed material is included.

## Validation

- [ ] `python scripts/run_suite.py`
- [ ] `python -m unittest discover -s tests -v`
- [ ] `python scripts/build_report.py --check`
- [ ] `Rscript R/run_suite.R` (when R logic changes)
