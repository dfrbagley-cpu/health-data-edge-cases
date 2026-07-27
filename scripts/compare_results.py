#!/usr/bin/env python3
"""Compare external pipeline CSV exports with a case's expected outputs."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from health_edge_cases.runner import main


if __name__ == "__main__":
    # Force the compare subcommand while allowing the same flags.
    argv = sys.argv[1:]
    if not argv or argv[0] != "compare":
        argv = ["compare", *argv]
    raise SystemExit(main(argv))
