#!/usr/bin/env python3
"""Run the portable reference SQL against optional DuckDB."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from health_edge_cases.duckdb_runner import main


if __name__ == "__main__":
    raise SystemExit(main())
