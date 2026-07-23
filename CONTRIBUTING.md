# Contributing

Contributions that make healthcare operational reporting logic easier to test and explain are welcome.

Please open an issue before preparing a substantial case or schema change. The most useful proposal identifies one failure mode, its operational consequence, and the smallest synthetic fixture that proves the expected result.

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
```

If R is installed:

```bash
Rscript R/run_suite.R
```

See [Adding a case](docs/ADDING_A_CASE.md) for the full checklist.

## Pull requests

Keep a pull request focused. Explain:

- the reporting failure or ambiguity;
- why the fixture is safe to publish;
- why the expected result is defensible;
- whether any existing contract changes;
- the checks you ran.

By submitting a contribution, you agree that it is licensed under the Apache License 2.0.
