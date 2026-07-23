.PHONY: check report suite test

suite:
	python scripts/run_suite.py

test:
	python -m unittest discover -s tests -v

report:
	python scripts/build_report.py

check: test suite
	python scripts/build_report.py --check
