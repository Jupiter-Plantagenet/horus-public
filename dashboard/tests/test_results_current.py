"""The current pre-registered claim (working/evidence/finals-results-current.json, twin.results_current):
H1/H2 headlines are recognised, the current file is preferred over the historical finals file, the additive
paired / measured-route / history blocks pass through, and older documents still load unchanged."""
import json
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import horus_data as hd  # noqa: E402

REPO = HERE.parent.parent
CURRENT = REPO / "working/evidence/finals-results-current.json"
HISTORIC = REPO / "working/evidence/finals-results.json"


class CurrentResults(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="horus-results-current-"))
        (self.tmp / "evidence").mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_headlines(self):
        for v, want in (("H2", "H2"), ("H1", "H1"), ("GO", "GO"), ("NO-GO", "NO-GO"), ("maybe", None)):
            self.assertEqual(hd._go_no_go({"provenance": {"go_no_go": v}}), want)

    @unittest.skipUnless(CURRENT.exists() and HISTORIC.exists(), "evidence files not in this checkout")
    def test_current_file_is_preferred_and_blocks_pass_through(self):
        shutil.copy(HISTORIC, self.tmp / "evidence/finals-results.json")
        old = hd.build_state(str(self.tmp), time.time(), mode="replay")
        self.assertEqual(old["results"]["go_no_go"], "NO-GO")
        self.assertIsNone(old["results"]["paired"])
        shutil.copy(CURRENT, self.tmp / "evidence/finals-results-current.json")
        st = hd.build_state(str(self.tmp), time.time(), mode="replay")
        r = st["results"]
        self.assertEqual(r["go_no_go"], "H2")
        self.assertTrue(r["paired"]["H2"])
        self.assertFalse(r["paired"]["H1"])
        self.assertGreater(r["paired"]["refs"]["cho_global"]["utility"][1], 0)          # CI above 0
        self.assertFalse(r["paired"]["refs"]["cho_tuned_ext"]["passed"])               # reported, not hidden
        self.assertFalse(r["measured_route"]["H2"])
        self.assertEqual([h["verdict"] for h in r["confirmatory_history"]][:3], ["NO-GO", "H2", "NO-GO"])
        self.assertEqual(st["runtime"]["final_evaluation"]["verdict"], "H2")
        if "candidate_version" in st["runtime"]["final_evaluation"]:          # #53 dashboard only
            self.assertEqual(st["runtime"]["final_evaluation"]["candidate_version"], "v3.14.24")


if __name__ == "__main__":
    unittest.main()
