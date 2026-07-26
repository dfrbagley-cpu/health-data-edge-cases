.PHONY: catalog check duckdb report suite test

suite:
	python scripts/run_suite.py

test:
	python -m unittest discover -s tests -v

duckdb:
	python scripts/run_duckdb.py

report:
	python scripts/build_report.py

catalog:
	python scripts/build_contract_catalog.py

check: test suite
	python scripts/build_report.py --check
	python scripts/build_contract_catalog.py --check
