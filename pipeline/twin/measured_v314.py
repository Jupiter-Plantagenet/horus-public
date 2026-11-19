"""Measured-route transfer test of a FROZEN twin-trained selector
(pipeline/finals_preregistration_measured_v3_14.json).

The campus walk (t4, LG U+ LTE band 1) gives a calibrated mean RSRP surface for the
cells seen on the route (lap 1 only; twin.measured_twin / route_radio). This module
runs every arm on identical measured-route traces with the same multi-arm TwinSim
execution as twin.evaluate_v3 (composite.MultiArm, one sim pass per trace), one
stable supported segment at a time (segment starts reset UE and controllers, as in
measured_twin.execute), and aggregates each episode's counters over its segments.

Small-scale fading is NOT measured. 'off' replays the calibrated mean surface
(deterministic: one episode). 'rician' / 'rayleigh' layer the twin's own
Doppler-correlated fading (phy.PhyModel.fading_gain, 2-branch diversity, carrier
2.12 GHz) on that mean surface with explicit seeds - a declared assumption that
turns one walk into many paired channel realisations, not a measurement.

Arms: the frozen selector and the deployable baselines of finals_baselines(_v3).json.
The per-cell oracles are tuned per synthetic (scenario, fading) cell and have no
counterpart on this route, so H1 is not defined here.
"""

import argparse
import hashlib
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .composite import MultiArm
from .evaluate import holm, paired, tci
from .evaluate_v3 import DEPLOYABLE, arm_table, make_controller
from .finals_common import BASELINES_JSON, REPO, single_thread
from .measured_twin import load_inputs, make_traces
from .phy import RSRP_FLOOR_DBM, PhyConfig, PhyModel
from .sim import RadioTrace, SimConfig, TwinSim, summarize, utility_per_ue_min

BASELINES_V3 = REPO / "pipeline" / "finals_baselines_v3.json"
ARMS = ("v3",) + DEPLOYABLE + ("a3_stock",)
FC_GHZ = 2.12              # LTE band 1 downlink at EARFCN 100 (the route's serving channel)
METRICS = ("utility", "ho_rate", "fail_rate", "rlf_rate", "pp_rate", "mean_se", "mean_thr_mbps")


@dataclass
class _StubCell:
    cell_id: str
    x: float = 0.0
    y: float = 0.0
    pl_a: float = 0.0
    pl_b: float = 0.0
    tx_power_dbm: float = 0.0


def faded(trace, mode, seed, dt):
    """The trace with the twin's fading layer on its mean RSRP (unit-mean power gain)."""
    if mode == "off":
        return trace
    c = trace.l1.shape[2]
    phy = PhyModel([_StubCell(str(i)) for i in range(c)], seed, PhyConfig(fading=mode, fc_ghz=FC_GHZ))
    gain = np.stack([phy.fading_gain(trace.speeds[t], dt) for t in range(trace.l1.shape[0])])
    l1 = trace.l1 + 10.0 * np.log10(np.maximum(gain, 1e-6))
    rx = 10.0 ** (l1 / 10.0)
    return RadioTrace(np.maximum(l1, RSRP_FLOOR_DBM), rx, trace.speeds, trace.active, trace.cell_ids,
                      trace.ue_ids, trace.victim, trace.load, trace.noise_mw)


def arm_specs(version):
    b2 = json.loads(BASELINES_JSON.read_text(encoding="utf-8"))
    b3 = json.loads(BASELINES_V3.read_text(encoding="utf-8"))
    t = arm_table(b2, b3, version)
    return {a: t[a]("measured", "route") for a in ARMS}   # deployable arms ignore the cell


def episode(traces, specs, mode, seed, a):
    """One episode = every represented segment of the session, all arms paired."""
    cfg = SimConfig(dt=a["dt_s"])
    occupied = a["n_prb"] * 12 * a["scs_khz"] / 1000
    names = list(specs)
    tot = {n: None for n in names}
    duration = 0.0
    for si, (_, _, tr) in enumerate(traces):
        trf = faded(tr, mode, seed * 1000 + si, cfg.dt)
        ctls = [make_controller(specs[n]) for n in names]
        m = MultiArm(ctls, 1)
        env = TwinSim(trf, cfg, replicas=len(ctls), l3_k=m.l3_k, bandwidth_mhz=occupied)
        env.reset()
        m.reset()
        done = False
        while not done:
            _, _, done = env.step(m)
        for r, n in enumerate(names):
            part = {k: v[r:r + 1].copy() for k, v in env.c.items()}
            tot[n] = part if tot[n] is None else {k: tot[n][k] + part[k] for k in part}
        duration += env.n_steps * cfg.dt
    rows = []
    for n in names:
        mt = summarize(tot[n], 1, duration, occupied)
        mt["utility"] = round(utility_per_ue_min(mt), 4)
        rows.append({"arm": n, "spec": specs[n], "fading": mode, "seed": seed, "duration_s": duration, **mt})
    return rows


def build(dataset, model, mapping, assumptions, session, overrides=None):
    a = dict(json.loads(Path(assumptions).read_text(encoding="utf-8")), **(overrides or {}))
    rm, mapping_doc, epochs = load_inputs(dataset, model, mapping, session)
    traces, coverage = make_traces(rm, mapping_doc, epochs, a)
    return traces, coverage, a


def trace_digest(traces):
    h = hashlib.sha256()
    for s, e, tr in traces:
        h.update(json.dumps([s, e, tr.cell_ids, tr.load, tr.noise_mw]).encode())
        for x in (tr.l1, tr.rx, tr.speeds):
            h.update(np.asarray(x, dtype="<f8").tobytes())
    return h.hexdigest()


def verdict(rows, prereg, policy="v3", refs=DEPLOYABLE, ni_rel=None):
    """H2 rules of finals_preregistration_v3.json with 'cells' = fading modes present:
    pooled paired 95% CI of utility > 0; per guardrail the pooled upper CI of the increase
    <= max(rel * |ref pooled mean|, abs) and no Holm-significant fading-mode increase beyond it."""
    rule = prereg["go_no_go"]
    key = lambda r: (r["fading"], r["seed"])
    by = {}
    for r in rows:
        by.setdefault(r["arm"], {})[key(r)] = r
    ks = sorted(by[policy])
    modes = sorted({k[0] for k in ks})
    out = {"episodes": len(ks), "modes": modes, "refs": {}}
    for ref in refs:
        def series(arm, metric, ms=None):
            return np.array([by[arm][k][metric] for k in ks if ms is None or k[0] in ms], float)
        checks = []
        p = paired(series(policy, "utility"), series(ref, "utility"))
        checks.append({"check": "utility: pooled 95% CI > 0", "pass": bool(p["ci_low"] > 0),
                       "diff": p["diff"], "ci": [p["ci_low"], p["ci_high"]]})
        for g in rule["guardrails"]:
            mid = g["metric"]
            margin = max(g["rel_margin"] * abs(tci(series(ref, mid))[0]), g["abs_margin"])
            q = paired(series(policy, mid), series(ref, mid))
            per = {md: paired(series(policy, mid, {md}), series(ref, mid, {md})) for md in modes}
            ph = holm([v["p_t"] for v in per.values()]) if len(modes) > 1 else [v["p_t"] for v in per.values()]
            bad = [md for (md, v), pa in zip(per.items(), ph)
                   if (pa < 0.05 or not np.isfinite(pa)) and v["diff"] > margin]
            checks.append({"check": f"guardrail {mid} (margin {margin:.4f})",
                           "pass": bool(q["ci_high"] <= margin and not bad),
                           "diff": q["diff"], "ci": [q["ci_low"], q["ci_high"]], "modes_regressed": bad})
        out["refs"][ref] = {"pass": all(c["pass"] for c in checks), "checks": checks}
        if ni_rel is not None:
            delta = ni_rel * abs(tci(series(ref, "utility"))[0])
            ni = {"check": f"non-inferiority: pooled 95% CI lower bound > -{delta:.4f} ({ni_rel:.0%} of ref utility)",
                  "pass": bool(p["ci_low"] > -delta), "delta": delta}
            out["refs"][ref]["non_inferiority"] = {"pass": ni["pass"] and all(c["pass"] for c in checks[1:]),
                                                   "checks": [ni] + checks[1:]}
    out["pass"] = all(v["pass"] for v in out["refs"].values())
    if ni_rel is not None:
        out["non_inferiority_pass"] = all(v["non_inferiority"]["pass"] for v in out["refs"].values())
    return out


def run_block(name, dataset, model, mapping, assumptions, session, version, fadings, seeds, out, overrides=None,
              workers=15):
    from multiprocessing import Pool
    traces, coverage, a = build(dataset, model, mapping, assumptions, session, overrides)
    specs = arm_specs(version)
    jobs = [(name, str(dataset), str(model), str(mapping), str(assumptions), session, overrides, specs, md, sd)
            for md in fadings for sd in (seeds if md != "off" else [0])]
    rows = []
    with Pool(min(workers, len(jobs))) as pool:
        for rs in pool.imap_unordered(_job, jobs):
            rows += rs
    meta = {"block": name, "session": session, "model": str(model), "overrides": overrides or {},
            "assumptions": a, "coverage": {k: v for k, v in coverage.items() if k != "excluded_intervals"},
            "segments": len(traces), "trace_sha256_mean_surface": trace_digest(traces), "specs": specs}
    return rows, meta


def _job(j):
    single_thread()
    name, dataset, model, mapping, assumptions, session, overrides, specs, md, sd = j
    traces, _, a = build(dataset, model, mapping, assumptions, session, overrides)
    return [dict(r, block=name) for r in episode(traces, specs, md, sd, a)]


def main(argv=None):
    single_thread()
    ap = argparse.ArgumentParser(prog="python -m twin.measured_v314")
    ap.add_argument("--plan", type=Path, required=True)
    ap.add_argument("--blocks", default=None, help="comma list of block names (default: all in the plan)")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--workers", type=int, default=15)
    a = ap.parse_args(argv)
    plan = json.loads(a.plan.read_text(encoding="utf-8"))
    prereg = json.loads((REPO / plan["rules_from"]).read_text(encoding="utf-8"))
    a.out.mkdir(parents=True, exist_ok=True)
    blocks = plan["blocks"]
    want = a.blocks.split(",") if a.blocks else list(blocks)
    summary = {}
    for name in want:
        b = blocks[name]
        lo, hi = b["seeds"]
        rows, meta = run_block(name, REPO / plan["dataset"], REPO / b["model"], REPO / plan["mapping"],
                               REPO / plan["assumptions"], b["session"], plan["candidate"]["version"],
                               b["fadings"], range(lo, hi + 1), a.out, b.get("overrides"), a.workers)
        rows.sort(key=lambda r: (r["fading"], r["seed"], r["arm"]))
        with (a.out / f"{name}.rows.jsonl").open("w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        faded_rows = [r for r in rows if r["fading"] != "off"]
        v = verdict(faded_rows, prereg, ni_rel=plan.get("non_inferiority_rel")) if faded_rows else None
        means = {arm: {m: round(float(np.mean([r[m] for r in rows if r["arm"] == arm and r["fading"] != "off"] or [np.nan])), 4)
                       for m in METRICS} for arm in ARMS}
        off = {r["arm"]: {m: r[m] for m in METRICS} for r in rows if r["fading"] == "off"}
        summary[name] = {"meta": meta, "verdict": v, "means_faded": means, "off_episode": off}
        print(f"[{name}] episodes={v['episodes'] if v else 0} H2={'PASS' if v and v['pass'] else 'FAIL' if v else 'n/a'}"
              + (f" NI={'PASS' if v.get('non_inferiority_pass') else 'FAIL'}" if v and 'non_inferiority_pass' in v else ""),
              file=sys.stderr, flush=True)
        if v:
            for ref, r in v["refs"].items():
                u = r["checks"][0]
                print(f"   vs {ref:15s} U {u['diff']:+.4f} [{u['ci'][0]:+.4f}, {u['ci'][1]:+.4f}] "
                      + " ".join(f"{c['check'].split()[1]}:{'ok' if c['pass'] else 'FAIL'}" for c in r["checks"][1:]),
                      file=sys.stderr, flush=True)
    (a.out / "summary.json").write_text(json.dumps(summary, indent=1, default=float) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
