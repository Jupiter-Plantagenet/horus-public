#!/usr/bin/env python3
"""Build the campus3d v3.14 data: the frozen v3.14.24 selector and the deployable baselines replayed on
the calibrated reverse campus route, plus the pre-registered verdicts to display.

Deterministic TwinSim replay (labelled MODELLED in the console): the same measured-route inputs, segment
resets and selector construction as stack/measured_selector_stream.py (whose v3.14.24 parity receipt is
working/evidence/selector-integration-v3.14/). RSRP is the lap-1 calibrated surface; SINR, load, HO state
and failures are simulated. Nothing here is a field measurement or a live execution.

Writes dashboard/campus3d/data/{v314-route.json, comparison-v314.json}; never touches build_data.py outputs.

    python dashboard/campus3d/build_v314.py            # needs the ML venv (numpy, torch)
    python dashboard/campus3d/build_v314.py --check    # outputs up to date
"""
import argparse, gzip, hashlib, json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OUT = HERE / "data"
VERSION = "v3.14.24"
ARMS = ("selector_" + VERSION, "cho_global", "cho_mro", "a3_stock")
STEP = 0.1


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def simulate():
    sys.path.insert(0, str(ROOT / "stack"))
    sys.path.insert(0, str(ROOT / "pipeline"))
    from measured_selector_stream import inputs, checkpoint
    from twin.evaluate_v3 import arm_table, make_controller
    from twin.finals_common import BASELINES_JSON
    backend, assumptions, traces, coverage = inputs(ROOT)
    ck = checkpoint(ROOT, backend, VERSION)
    b2 = json.loads(BASELINES_JSON.read_text(encoding="utf-8"))
    b3 = json.loads((ROOT / "pipeline/finals_baselines_v3.json").read_text(encoding="utf-8"))
    table = arm_table(b2, b3)
    specs = {"cho_global": table["cho_global"]("measured", "route"), "cho_mro": table["cho_mro"]("measured", "route"),
             "a3_stock": table["a3_stock"]("measured", "route")}
    bw = assumptions["n_prb"] * 12 * assumptions["scs_khz"] / 1000
    sim = backend["sim"]
    cells = sorted({c for _, _, tr in traces for c in tr.cell_ids})
    out = {a: dict(serving=[], events=[], segments=[], totals=None) for a in ARMS}
    frames = dict(t=[], rsrp=[], profile=[], stage=[])
    for index, (start, end, tr) in enumerate(traces):
        gidx = [cells.index(c) for c in tr.cell_ids]
        t0 = start * STEP
        for arm in ARMS:
            if arm.startswith("selector_"):
                ctl = backend["selector_v3"].CHOSelectorPolicy(dict(ck))
                env = sim.TwinSim(tr, sim.SimConfig(dt=STEP), l3_k=4, bandwidth_mhz=bw)
            else:
                ctl = make_controller(specs[arm])
                env = sim.TwinSim(tr, sim.SimConfig(dt=STEP), l3_k=ctl.l3_k, bandwidth_mhz=bw)
            env.reset()
            if hasattr(ctl, "reset"):
                ctl.reset()
            prev, done, rec = None, False, out[arm]
            while not done:
                _, _, done = env.step(ctl)
                T = round(t0 + env.t, 1)
                s = gidx[int(env.serving[0])]
                if s != prev:
                    if prev is not None:
                        ev = dict(t=T, from_=prev, to=s, segment=index)
                        if arm.startswith("selector_") and ctl.engine.current is not None:
                            ev["profile"] = int(ctl.engine.current[0])
                        rec["events"].append(ev)
                    rec["serving"].append([T, s])
                    prev = s
                if arm.startswith("selector_"):
                    k = int(round(env.t / STEP))
                    if k % 10 == 0:            # 1 s resolution for per-frame panels
                        row = [None] * len(cells)
                        for j, g in enumerate(gidx):
                            row[g] = round(float(tr.l1[min(k, len(tr.l1) - 1), 0, j]), 1)
                        frames["t"].append(T)
                        frames["rsrp"].append(row)
                        cur = ctl.engine.current
                        frames["profile"].append(None if cur is None else int(cur[0]))
                        learned = getattr(ctl, "_t0", None) is not None and env.t - ctl._t0 + 1e-9 >= ctl.warm_s
                        frames["stage"].append("learned_profiles" if learned else "warm_default")
            m = env.metrics()
            rec["segments"].append(dict(start_s=round(t0, 1), end_s=round((end - 1) * STEP, 1), ho=m["ho_attempts"],
                                        pp=m["ping_pongs"], rlf=m["rlf"], thr=m["mean_thr_mbps"]))
            rec.setdefault("_c", []).append(m)
    for arm in ARMS:
        ms = out[arm].pop("_c")
        dur = sum(m["duration_s"] for m in ms)
        tot = {k: sum(m[k] for m in ms) for k in ("ho_attempts", "ho_success", "ping_pongs", "rlf", "hof")}
        tot["mean_thr_mbps"] = round(sum(m["mean_thr_mbps"] * m["duration_s"] for m in ms) / dur, 2)
        se = sum(m["mean_se"] * m["duration_s"] for m in ms) / dur
        tot["utility_modelled"] = round(60 * se / 7.4 - 0.3 * tot["ho_attempts"] / (dur / 60) - 2 * tot["ping_pongs"] / (dur / 60)
                                        - 5 * (tot["rlf"] + tot["hof"]) / (dur / 60), 4)
        tot["duration_s"] = round(dur, 1)
        out[arm]["totals"] = tot
        for e in out[arm]["events"]:
            e["from"] = e.pop("from_")
    return cells, coverage, out, frames, specs, [dict(p) for p in ck["profiles"]]


def verdicts():
    ev = ROOT / "working/evidence"
    st = json.loads((ev / "finals-v3.14/final/stats.json").read_text(encoding="utf-8"))
    pooled = lambda ref, m="utility": st["comparisons"][ref][m]["pooled"]
    twin = {ref: dict(utility=[round(pooled(ref)["diff"], 3), round(pooled(ref)["ci_low"], 3), round(pooled(ref)["ci_high"], 3)],
                      ho=round(pooled(ref, "ho_rate")["diff"], 3))
            for ref in ("cho_global", "cho_mse", "cho_mro", "a3_global", "a3_tuned", "cho_tuned", "cho_tuned_ext")}
    ms = json.loads((ev / "measured-v3.14/final/summary.json").read_text(encoding="utf-8"))["primary"]["verdict"]
    meas = {ref: [round(r["checks"][0]["diff"], 3)] + [round(x, 3) for x in r["checks"][0]["ci"]]
            for ref, r in ms["refs"].items() if ref in ("cho_global", "cho_mro", "a3_global")}
    return dict(
        twin=dict(headline=st["verdict"]["headline"], H1=st["verdict"]["H1_oracle"]["pass"], H2=st["verdict"]["H2_deployable"]["pass"],
                  episodes=len(st["seeds"]) * 12, seeds="2200-2259", vs=twin,
                  source="working/evidence/finals-v3.14/final/stats.json"),
        measured=dict(H2=ms["pass"], non_inferiority=ms["non_inferiority_pass"], episodes=ms["episodes"], vs=meas,
                      failing="ping-pong guardrail vs network-wide CHO under the Rayleigh fading layer",
                      source="working/evidence/measured-v3.14/final/summary.json"),
        gates=dict(unchanged=0.7998, replicate=0.8154, poisoned_fedavg="REJECT (both gates)"),
        preregistrations=["pipeline/finals_preregistration_v3_14.json", "pipeline/finals_preregistration_measured_v3_14.json"])


def build():
    cells, coverage, arms, frames, specs, profiles = simulate()
    inputs_used = {p: sha(ROOT / p) for p in (
        "pipeline/checkpoints/dqn-v3.14.24.pt", "working/evidence/selector-integration-v3.14/input-fidelity.json",
        "working/evidence/finals-v3.14/final/stats.json", "working/evidence/measured-v3.14/final/summary.json",
        "working/evidence/t4-replay/neighbor-assumption-model.json", "data/walktest/t4-phy-assumptions.json")}
    label = "TwinSim modelled replay of HORUS v3.14.24 on the calibrated reverse campus route (neighbour-assumption primary case, mean surface)"
    notes = ("RSRP calibrated from the lap-1 walk; SINR, load, failures and throughput modelled. Same route, time base and "
             "assumptions for every arm. Not a field measurement or a live execution.")
    comparison = {"format": "horus.campus3d.comparison/1", "kind": "modelled", "label": label, "notes": notes,
                  "candidate": VERSION, "arms": {a: dict(totals=arms[a]["totals"], segments=arms[a]["segments"]) for a in ARMS},
                  "inputs": inputs_used}
    route = {"format": "horus.campus3d.v314-route/1", "kind": "modelled", "candidate": VERSION, "label": label, "notes": notes,
             "cells": cells, "coverage": {k: v for k, v in coverage.items() if k != "excluded_intervals"},
             "frames": frames, "arms": {a: dict(serving=arms[a]["serving"], events=arms[a]["events"]) for a in ARMS},
             "baseline_specs": specs, "profiles": profiles, "verdicts": verdicts(), "inputs": inputs_used}
    return {"v314-route.json": route, "comparison-v314.json": comparison}


LIVE_DIR = ROOT / "working/evidence/live-v3.14"


def build_live_replay():
    """replay-seg0-v314.json: the recorded v3.14.24 executions (bounded PASS cycle + every cycle of the newest
    sustained run, if present), in the horus.campus3d.feed/1 format build_data.py writes for v3.39.0, parsed by
    build_data.cycle_record so both recordings are read identically."""
    import build_data as bd
    bounded = sorted(LIVE_DIR.glob("bounded-PASS-*"))[-1]
    # only sustained runs whose independent-clock verification passed (run 1 was SHORT: 7,095 s real)
    verified = lambda d: json.loads((d / "VERIFICATION.json").read_text())["timing"]["verdict"].startswith("PASS")
    sustained = sorted(d for d in LIVE_DIR.glob("sustained-*") if d.is_dir() and (d / "VERIFICATION.json").exists() and verified(d))
    sus = sustained[-1] if sustained else None
    frames = bd.jlines(bounded / "cycle-000/frames.jsonl")
    decisions = bd.jlines(bounded / "cycle-000/driver/decisions.jsonl")
    cells = frames[0]["cell_ids"]
    assert all(f["cell_ids"] == cells for f in frames) and frames[0]["segment"] == "reverse-supported-0"
    dec = {d["sequence"]: d for d in decisions}
    profile = [dec[f["sequence"]]["selected_profiles"][0]["index"] if f["sequence"] in dec and dec[f["sequence"]].get("selected_profiles") else None for f in frames]
    stage = [dec[f["sequence"]].get("selector_stage") if f["sequence"] in dec else None for f in frames]
    cycles = [c for c in [bd.cycle_record(bounded / "cycle-000", "bounded")] if c]
    if sus:
        cycles += [c for c in (bd.cycle_record(d, "soak") for d in sorted(sus.glob("cycle-*"))) if c]
    res = json.loads(((sus or bounded) / "result.json").read_text(encoding="utf-8"))
    kind = "soak" if sus else "bounded"
    ev = [e for c in cycles if c["kind"] == kind for e in c["events"]]
    cu_ms = sorted(e["evidence"]["decision_to_cu_ms"] for e in ev if e["evidence"]["decision_to_cu_ms"])
    ack_ms = sorted(e["evidence"]["ric_ack_ms"] for e in ev if e["evidence"]["ric_ack_ms"] is not None)
    pct = lambda a, q: a[min(len(a) - 1, int(q * (len(a) - 1) + 0.5))] if a else None
    sel = [c for c in cycles if c["kind"] == kind]
    # real (UTC) sustained seconds from the run's verification; the runner's own figure is WSL CLOCK_MONOTONIC
    host = {"host_seconds": json.loads((sus / "VERIFICATION.json").read_text())["timing"]["real_sustained_s"]} if sus else {}
    return {
        "format": "horus.campus3d.feed/1", "mode": "replay",
        "label": f"Recorded execution · {VERSION} · reverse route segment 0",
        "provenance": {"kind": "recorded",
                       "inputs": f"Calibrated TwinSim observation stream for reverse segment 0 ({bounded.relative_to(ROOT)}/cycle-000/frames.jsonl); deterministic, replayed in every cycle",
                       "execution": f"Manifest-verified assembly of live/v3.14, desktop lab: {bounded.name}" + (f" and {sus.name}" if sus else ""),
                       "scope": "Emulated OAI RF (rfsim), ordinary F1 handovers between two DUs; CHO profiles execute in the twin. Not field RAN actuation and not native RRC CHO."},
        "scenario": {"id": "t4-reverse-seg0", "route": "t4-reverse", "segment": frames[0]["segment"], "step0": 0, "dt_s": 0.1,
                     "duration_s": round(frames[-1]["t_s"], 1)},
        "cells": cells,
        "frames": {"t_s": [round(f["t_s"], 1) for f in frames], "step": [f["sequence"] for f in frames],
                   "serving": [f["serving"][0] for f in frames], "rsrp": [[bd.r1(v) for v in f["l1"][0]] for f in frames],
                   "sinr_db": [bd.r1(f["sinr_db"][0]) for f in frames], "profile": profile, "stage": stage},
        "decision_steps_all_cycles": sorted({(e["step"], e["profile"]["index"]) for c in cycles for e in c["events"]}),
        "cycles": cycles,
        "acceptance": {"passed": bool(res.get("passed") and res.get("cleanup_passed") and res.get("source_hashes_match")),
                       "kind": kind, "cycles": len(sel), "frames": sum(c["frames"] for c in sel),
                       "inference_calls": sum(c["runtime"]["inference_calls"] for c in sel),
                       "confirmed_handovers": sum(c["confirmed_handovers"] for c in sel),
                       "failed_controls": sum(c["failed_controls"] for c in sel),
                       "decision_to_cu_ms": {"p50": pct(cu_ms, .5), "p95": pct(cu_ms, .95), "max": cu_ms[-1] if cu_ms else None},
                       "ric_ack_ms": {"p50": pct(ack_ms, .5), "p95": pct(ack_ms, .95), "max": ack_ms[-1] if ack_ms else None},
                       "native_seconds": round(res.get("sustained_elapsed_seconds") or 0, 3), "host_seconds": host.get("host_seconds"),
                       "receipt": str(((sus or bounded) / "result.json").relative_to(ROOT))},
        "service": None, "comparison": None}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--live-only", action="store_true", help="only rebuild replay-seg0-v314.json from the recorded captures")
    a = ap.parse_args()
    if a.live_only:
        sys.path.insert(0, str(HERE))
        doc = build_live_replay()
        (OUT / "replay-seg0-v314.json").write_text(json.dumps(doc, separators=(",", ":")) + "\n", encoding="utf-8")
        print("wrote replay-seg0-v314.json", doc["acceptance"])
        return 0
    docs = build()
    stale = []
    for name, doc in docs.items():
        text = json.dumps(doc, separators=(",", ":"), allow_nan=False) + "\n"
        p = OUT / name
        if a.check:
            if not p.exists() or p.read_text(encoding="utf-8") != text:
                stale.append(name)
        else:
            p.write_text(text, encoding="utf-8", newline="\n")
            print(f"wrote {p.relative_to(ROOT)} ({len(text)} bytes)")
    if stale:
        print("stale: " + ", ".join(stale))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
