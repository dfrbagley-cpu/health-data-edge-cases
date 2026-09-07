"""Independent controls for reporting-pack semantics and installed data."""
import csv
from datetime import date
import importlib.util
import json
import subprocess
import sys
import unittest

from health_edge_cases.reporting_packs import PACK_IDS, PACK_ROOT, run_pack


class ReportingPacksTests(unittest.TestCase):
    def test_references_and_deliberate_failures(self):
        for pack in PACK_IDS:
            with self.subTest(pack=pack):
                self.assertTrue(run_pack(pack)["passed"])
                self.assertFalse(run_pack(pack, naive=True)["passed"])

    @unittest.skipUnless(importlib.util.find_spec("duckdb"), "DuckDB optional locally; installed in CI")
    def test_duckdb_agrees_with_sqlite(self):
        for pack in PACK_IDS:
            self.assertEqual(run_pack(pack)["actual"], run_pack(pack, "duckdb")["actual"])
            self.assertFalse(run_pack(pack, "duckdb", naive=True)["passed"])

    def test_fixture_contract_dates_and_identity(self):
        for pack in PACK_IDS:
            for path in (PACK_ROOT / pack).glob("input_*.csv"):
                with path.open(newline="", encoding="utf-8") as stream:
                    rows = list(csv.DictReader(stream))
                self.assertTrue(rows)
                for row in rows:
                    self.assertNotIn(None, row)
                    for key, value in row.items():
                        if value and (key.endswith("_on") or key in {"cutoff", "valid_from", "valid_to"}):
                            self.assertEqual(value, date.fromisoformat(value).isoformat())
                if "version" in rows[0]:
                    self.assertEqual(len(rows), len({(r["event_id"], r["version"]) for r in rows}))

    def test_controls_expose_plausible_equal_totals(self):
        historical = run_pack("historical-cutoff")["actual"]
        self.assertEqual(3, historical["known_at_cutoff"])
        self.assertEqual(3, historical["latest_revised"])
        self.assertEqual(1, historical["post_cutoff_corrections"])
        mappings = run_pack("effective-dated-mappings")["actual"]
        self.assertEqual(mappings["events"], sum(mappings[k] for k in ("mapped_once", "unmapped", "ambiguous")))

    def test_cli_and_unknown_pack(self):
        for args, code in (([], 0), (["--naive"], 1)):
            result = subprocess.run([sys.executable, "-m", "health_edge_cases", "packs", "--json", *args], capture_output=True, text=True)
            self.assertEqual(code, result.returncode, result.stderr)
            self.assertEqual(3, len(json.loads(result.stdout)["packs"]))
        with self.assertRaises(ValueError):
            run_pack("../other")
