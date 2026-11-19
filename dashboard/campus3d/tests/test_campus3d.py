#!/usr/bin/env python3
"""Data-bundle and LIVE-feed tests for dashboard/campus3d (standard library only).

    python dashboard/campus3d/tests/test_campus3d.py
"""
import json, subprocess, sys, tempfile, time, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
C3D = HERE.parent
ROOT = C3D.parent.parent
sys.path.insert(0, str(C3D))
import serve  # noqa: E402

load = lambda n: json.loads((C3D / "data" / n).read_text(encoding="utf-8"))


class Bundle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.campus, cls.route, cls.replay, cls.cmp = load("campus.json"), load("route.json"), load("replay-seg0.json"), load("comparison.json")

    @unittest.skipUnless((ROOT / "data/walktest/t4/epochs.jsonl").exists(),
                         "rebuilding route.json needs the walk trace, which the public release does not include")
    def test_bundle_is_reproducible(self):
        r = subprocess.run([sys.executable, str(C3D / "build_data.py"), "--check"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_manifest_hashes_outputs(self):
        import hashlib
        man = load("manifest.json")
        for name, meta in man["outputs"].items():
            self.assertEqual(hashlib.sha256((C3D / "data" / name).read_bytes()).hexdigest(), meta["sha256"], name)
        self.assertTrue(any("epochs.jsonl" in k for k in man["inputs"]))

    def test_campus_geometry_has_provenance(self):
        self.assertIn("OpenStreetMap", self.campus["attribution"])
        self.assertIn("approximate", self.campus["provenance"]["heights"])
        self.assertGreaterEqual(len(self.campus["buildings"]), 30)
        self.assertTrue(any(b["name_ko"] == "산학협력관" for b in self.campus["buildings"]))
        self.assertEqual(len(self.campus["ocid_sites"]), 110)

    def test_cells_have_no_invented_masts(self):
        cells = self.route["cells"]
        self.assertEqual(len(cells), 7)
        for c in cells:
            self.assertIn("mast position unknown", c["anchor"]["meaning"])
            self.assertNotEqual(c["anchor"]["rsrp_dbm"], -44.0)       # flagged joint tuple excluded
            self.assertFalse(c["key"].startswith("ocid-"))

    def test_route_matches_recorded_session(self):
        rev = self.route["sessions"]["t4-reverse"]
        self.assertEqual(rev["rows"], 3219)
        self.assertAlmostEqual(rev["duration_s"], 2167.224, places=2)
        self.assertEqual(len(rev["points"]["t"]), rev["rows"])
        self.assertEqual(len(self.route["trace"]["rsrp_1s"]), int(self.route["trace"]["segments"][-1]["end"] * 0.1) + 1)

    def test_replay_events_are_real_and_consistent(self):
        rp = self.replay
        self.assertEqual(len(rp["cycles"]), 37)                         # bounded + 36 two-hour cycles
        self.assertEqual(rp["decision_steps_all_cycles"], [[1536, 31], [1761, 20]])
        ver = json.loads((ROOT / "working/evidence/qualified-release-20261104/soak/VERIFICATION.json").read_text())
        self.assertEqual(rp["acceptance"]["cycles"], ver["cycles"])
        self.assertEqual(rp["acceptance"]["confirmed_handovers"], 72)
        self.assertEqual(rp["acceptance"]["failed_controls"], 0)
        for c in rp["cycles"]:
            for e in c["events"]:
                ph = e["phases"]
                self.assertTrue(e["evidence"]["rrc_complete"])
                self.assertLessEqual(ph["decision"], ph["sent"]); self.assertLessEqual(ph["sent"], ph["ack"])
                self.assertLess(ph["ack"], ph["cu_confirmed"])
                self.assertAlmostEqual(ph["decision"], (e["step"] + 1) * 0.1, delta=0.6)
        # frame serving switches exactly at the recorded decision steps
        f = rp["frames"]
        changes = [f["step"][i] for i in range(1, len(f["step"])) if f["serving"][i] != f["serving"][i - 1]]
        self.assertEqual(changes, [1536, 1761])
        self.assertIsNone(rp["comparison"]); self.assertIsNone(rp["service"])   # pending, never invented

    def test_comparison_is_labelled_modelled(self):
        self.assertEqual(self.cmp["kind"], "modelled")
        self.assertEqual(self.cmp["arms"]["selector_v3.39.0"]["totals"]["ho_attempts"], 20)
        self.assertEqual(self.cmp["arms"]["a3_stock"]["totals"]["ho_attempts"], 14)


def write_jsonl(p, rows, mode="w"):
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, mode, encoding="utf-8") as f:
        for r in rows: f.write(json.dumps(r) + "\n")


def frame(seq, serving=0):
    return {"format": "horus.selector-frame/1", "sequence": seq, "segment": "reverse-supported-0", "t_s": round((seq + 1) * 0.1, 1),
            "source_ts": f"2026-11-04T01:00:{(seq // 10):02d}.{seq % 10}00000+00:00", "cell_ids": ["c0", "c1"],
            "l1": [[-90.0, -95.0]], "serving": [serving], "sinr_db": [3.0]}


class Live(unittest.TestCase):
    def test_empty_capture_waits(self):
        with tempfile.TemporaryDirectory(dir=C3D) as d:
            feed = serve.LiveFeed(d).feed(-1)
            self.assertTrue(feed["live"]["stale"]); self.assertEqual(feed["frames"]["t_s"], [])

    def test_tail_frames_events_and_freshness(self):
        with tempfile.TemporaryDirectory(dir=C3D) as d:
            c = Path(d) / "cycle-000"
            write_jsonl(c / "frames.jsonl", [frame(i) for i in range(20)])
            write_jsonl(c / "driver/decisions.jsonl", [{"sequence": 5, "selected_profiles": [{"index": 31}], "selector_stage": "learned_profiles"}])
            write_jsonl(c / "driver/timed-actions.jsonl", [{"ts": "x", "result": "ok", "latency_ms": 4000.0,
                "latency_breakdown": {"decision_to_send_ms": 500.0},
                "params": {"twin_step": 9, "twin_from_cell": "c0", "twin_to_cell": "c1", "ric_control_ack_ms": 3.0,
                           "rrc_handover_complete": True, "source_du": "3584", "target_du": "3585",
                           "selector": {"selected_profile": {"index": 31, "parameters": {"hys_db": 2.0}}}}}])
            write_jsonl(c / "dashboard/metrics/rtt.jsonl", [{"ts": "2026-11-04T01:00:01.000000+00:00", "rtt_ms": 88.0}])
            lf = serve.LiveFeed(d)
            self.assertTrue(lf.feed(-1)["live"]["stale"])  # initial archive contents are not producer liveness
            write_jsonl(c / "frames.jsonl", [frame(20)], mode="a")
            f1 = lf.feed(-1)
            self.assertEqual(len(f1["frames"]["t_s"]), 21); self.assertFalse(f1["live"]["stale"])
            self.assertEqual(f1["frames"]["profile"][5], 31)
            ev = f1["events"][0]
            self.assertEqual(ev["status"], "confirmed"); self.assertEqual(ev["phases"]["decision"], 1.0)
            self.assertAlmostEqual(ev["phases"]["ack"], 1.503, delta=0.006); self.assertAlmostEqual(ev["phases"]["cu_confirmed"], 5.0, places=3)
            self.assertEqual(len(f1["service"]["rtt"]), 1)
            self.assertAlmostEqual(f1["service"]["rtt"][0][0], 1.1, places=2)    # frame 19 = 01:00:01.9 <-> t_s 2.0
            # incremental read: only newer frames, partial trailing line ignored until complete
            with open(c / "frames.jsonl", "a", encoding="utf-8") as fh:
                fh.write(json.dumps(frame(21)) + "\n" + json.dumps(frame(22))[:30])
            f2 = lf.feed(20)
            self.assertEqual(f2["frames"]["step"], [21])
            serve.STALE_S, old = 0.05, serve.STALE_S
            try:
                time.sleep(0.1); self.assertTrue(lf.feed(21)["live"]["stale"])
            finally:
                serve.STALE_S = old

    def test_failed_and_unconfirmed_controls_are_not_confirmed(self):
        base = {"params": {"twin_step": 1, "twin_from_cell": "a", "twin_to_cell": "b", "ric_control_ack_ms": 2.0},
                "latency_breakdown": {"decision_to_send_ms": 100.0}}
        self.assertEqual(serve.event_from_action(0, dict(base, result="failed", latency_ms=None))["status"], "failed")
        self.assertEqual(serve.event_from_action(0, dict(base, result="ok", latency_ms=3000.0))["status"], "acked")  # no RRC completion

    def test_new_cycle_is_followed(self):
        with tempfile.TemporaryDirectory(dir=C3D) as d:
            write_jsonl(Path(d) / "cycle-000/frames.jsonl", [frame(i) for i in range(5)])
            lf = serve.LiveFeed(d); self.assertEqual(lf.feed(-1)["live"]["cycle"], "cycle-000")
            write_jsonl(Path(d) / "cycle-001/frames.jsonl", [frame(0)])
            self.assertEqual(lf.feed(-1)["live"]["cycle"], "cycle-001")

    def test_static_archive_is_stale_on_first_attachment(self):
        with tempfile.TemporaryDirectory(dir=C3D) as d:
            write_jsonl(Path(d)/"cycle-000/frames.jsonl",[frame(0)])
            self.assertTrue(serve.LiveFeed(d).feed(-1)["live"]["stale"])

    def test_malformed_growth_does_not_prove_liveness(self):
        with tempfile.TemporaryDirectory(dir=C3D) as d:
            path=Path(d)/"cycle-000/frames.jsonl"
            write_jsonl(path,[frame(0)])
            feed=serve.LiveFeed(d);feed.feed(-1)
            with path.open('a',encoding='utf-8') as stream:stream.write('{bad json}\n')
            result=feed.feed(0)
            self.assertTrue(result['live']['stale']);self.assertIn('malformed',result['error'])


if __name__ == "__main__":
    unittest.main(verbosity=2)
