# Contributing

Contributions that make healthcare operational reporting logic easier to test and explain are welcome.

Review the [public publication policy](PUBLICATION_POLICY.md) before opening an
issue or pull request. Contributions must be explainable, reviewable, and
reproducible entirely from public context.

Please open an issue before preparing a substantial case or schema change. The most useful proposal identifies one failure mode, its operational consequence, and the smallest synthetic fixture that proves the expected result. Small documentation corrections can go directly to a pull request.

## Small ways to start

| Contribution | Where to start | Done when |
|---|---|---|
| Test the first-run instructions | Follow the [README](README.md#run-the-suite-locally) in a fresh checkout | Report your Python version, which step worked or failed, and any confusing wording; share only generalized details |
| Explain a mismatch more clearly | Inspect the [unmapped-program example](docs/COMPARE_RESULTS.md#read-the-failing-pattern-carefully) | A focused documentation change connects the invented input rows to one expected count without claiming the diagnostic pattern proves a cause |
| Propose one missing boundary case | Read [Adding a case](docs/ADDING_A_CASE.md) and open the edge-case template | Supply a few invented rows, the naive result, the expected result, and the rule that distinguishes them; implementation can wait for agreement |

Use the [usage-feedback form](https://github.com/dfrbagley-cpu/health-data-edge-cases/issues/new?template=usage-feedback.yml)
for a first-run report. Include the smallest useful excerpt, not an unreviewed
terminal log. You can contribute domain reasoning or documentation without
installing R or DuckDB; CI checks both reference implementations for code and
fixture changes.

## Non-negotiable data boundary

Do not contribute:

- personal or personal health information, even if partially de-identified;
- employer, customer, or patient-derived records;
- confidential mappings, screenshots, extracts, or internal definitions;
- copied vendor schemas;
- text, formulas, or classifications from licensed standards unless redistribution is clearly permitted.

All examples must be synthetic and independently designed. Patient tokens must begin with `SYN-`.

## Development

Python 3.10 or later is sufficient for the primary checks.

```bash
python scripts/run_suite.py
python -m unittest discover -s tests -v
python scripts/build_report.py --check
python scripts/build_contract_catalog.py --check
python -m health_edge_cases validate-case cases/unmapped-program-retention
```

If R is installed:

```bash
Rscript R/run_suite.R
Rscript R/test_contract_validation.R
```

See [Adding a case](docs/ADDING_A_CASE.md) for the full checklist.

CI also installs the exact built wheel on a Windows runner with Python 3.12.
It runs outside the checkout and checks the reference suite, both comparison
examples, fresh-workspace verification, rejection of a wrong results path,
and refusal to overwrite an existing workspace. To repeat that check locally
after installing a wheel into a disposable virtual environment, run:

```bash
python tests/installed_package_smoke.py
```

This automated check covers the runner environment. Independent first-use
reports still help identify unclear instructions and differences on desktop
Windows installations.

## Pull requests

Keep a pull request focused. Explain:

- the reporting failure or ambiguity;
- why the fixture is safe to publish;
- why the expected result is defensible;
- whether any existing contract changes;
- the checks you ran.

By submitting a contribution, you agree that it is licensed under the Apache License 2.0.
