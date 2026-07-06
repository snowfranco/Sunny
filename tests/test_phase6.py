"""Golden fixtures stay loadable, covering, and rule-compliant."""

import importlib.util
import os
import unittest
from pathlib import Path

os.environ["PIPELINE_MOCK"] = "1"

from pipeline import reviewer

_spec = importlib.util.spec_from_file_location(
    "run_goldens",
    Path(__file__).resolve().parent.parent / "tools" / "run_goldens.py")
run_goldens = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_spec and run_goldens)


class TestGoldenFixtures(unittest.TestCase):
    def setUp(self):
        self.fixtures = run_goldens.load_fixtures()

    def test_coverage(self):
        self.assertEqual(run_goldens.check_coverage(self.fixtures), [])

    def test_every_golden_passes_mechanical_rules(self):
        for f in self.fixtures:
            items = reviewer.mechanical_checklist(f["golden"], f["format"])
            fails = [f"{c.criterion}: {c.note}" for c in items if not c.passed]
            self.assertEqual(fails, [], f"{f['fixture_id']} drifted: {fails}")

    def test_notes_and_goldens_nonempty(self):
        for f in self.fixtures:
            self.assertTrue(f["note"].strip(), f["fixture_id"])
            self.assertTrue(f["golden"].strip(), f["fixture_id"])


if __name__ == "__main__":
    unittest.main()
