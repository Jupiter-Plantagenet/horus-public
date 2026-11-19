"""Full-information training data for the v3 profile selector.

For one radio trace, every candidate CHO profile runs as a sim replica (the
UEs do not interact in twin v2 — see ue_grid.py), and every `snap_s` seconds
we snapshot, per (profile, UE):
    cumulative SE sum / samples / HO / ping-pong / failure counters  -> labels
    the online SituationFeatures vector of that row                  -> inputs
A training sample is (features of UE i on the trajectory of profile j at
time t, utility of EVERY profile for UE i over the window [t, t+H]).
Labels therefore come from the twin's counterfactual replay, not from
exploration; the trajectories the features are taken on cover every profile,
so the selector sees serving-history features from many behaviours.

    python -m twin.v3_data --seeds 0-11 --out working/evidence/finals-v3/data
"""

import argparse
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np

from .cho_v3 import ProfileCHO, SituationFeatures
from .phy import SE_CAP
from .sim import SimConfig, TwinSim
from .ue_grid import C_FAIL, C_HO, C_PP


class _GridRecorder:
    def __init__(self, profiles, R, N, snap_s, dt, feature_set="v3"):
        self.engine = ProfileCHO(profiles)
        self.feat = SituationFeatures(dt, feature_set)
        self.R, self.N = R, N
        self.every = int(round(snap_s / dt))
        self.l3_k = 4
        self.k = 0
        self.X = []

    def reset(self):
        self.engine.reset()
        self.feat.reset()
        self.k = 0
        self.X = []

    def decide_batch(self, obs):
        if self.engine.current is None:
            self.engine.set(np.repeat(np.arange(self.R), self.N), obs)
        self.feat.update(obs)
        self.k += 1
        if self.k % self.every == 0:
            self.X.append(self.feat.vector())
        return self.engine.step(obs)


def record(trace, profiles, snap_s=5.0, cfg=None, feature_set="v3"):
    """Returns dict: X (S, R, N, F) features at t = snap_s*(1..S);
    cum_* (S+1, R, N) cumulative counters at t = 0, snap_s, ..."""
    cfg = cfg or SimConfig()
    R, N = len(profiles), trace.l1.shape[1]
    env = TwinSim(trace, cfg, replicas=R, l3_k=4)
    rec = _GridRecorder(profiles, R, N, snap_s, cfg.dt, feature_set)
    env.reset()
    rec.reset()
    keys = ("se", "samples", "ho_attempts", "ping_pongs", "fail")
    snaps = {k: [np.zeros((R, N))] for k in keys}
    done, i = False, 0
    while not done:
        _, _, done = env.step(rec)
        i += 1
        if i % rec.every == 0:
            c = env.c
            for k in keys:
                v = (c["rlf"] + c["hof_cmd"] + c["hof_target"]) if k == "fail" else c[k]
                snaps[k].append(np.asarray(v, float).reshape(R, N).copy())
    X = np.stack(rec.X)[:len(snaps["se"]) - 1].reshape(-1, R, N, rec.X[0].shape[1])
    return {"X": X.astype(np.float32), **{f"cum_{k}": np.stack(v).astype(np.float32)
                                          for k, v in snaps.items()}}


def window_utility(d, s0, s1):
    """Per-(profile, UE) utility over snapshots s0..s1 (indices into cum_*),
    per UE-minute, same weights as sim.utility_per_ue_min."""
    g = lambda k: d[f"cum_{k}"][s1] - d[f"cum_{k}"][s0]
    samples = np.maximum(g("samples"), 1)
    minutes = samples * 0.1 / 60.0
    return (60.0 * g("se") / samples / SE_CAP - C_HO * g("ho_attempts") / minutes
            - C_PP * g("ping_pongs") / minutes - C_FAIL * g("fail") / minutes)


def _task(a):
    from .finals_common import single_thread, trace_for
    single_thread()
    scenario, fading, seed, profiles, out, feature_set = a
    p = Path(out) / f"{scenario}-{fading}-{seed}.npz"
    if p.exists():
        return a[:3], 0.0
    t = time.time()
    d = record(trace_for(scenario, fading, seed), profiles, feature_set=feature_set)
    tmp = p.with_suffix(".tmp.npz")
    np.savez_compressed(tmp, **d)
    tmp.replace(p)
    return a[:3], time.time() - t


def main(argv=None):
    import json
    from .finals_common import FADINGS, SCENARIOS
    ap = argparse.ArgumentParser(prog="python -m twin.v3_data")
    ap.add_argument("--profiles", type=Path, required=True, help="JSON list of profile dicts")
    ap.add_argument("--seeds", required=True, help="a-b inclusive")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--mix", default=None, help="comma list of scenarios cycled over consecutive seeds "
                    "(a federated client's non-IID mix); default = every scenario at every seed")
    ap.add_argument("--features", default="v3", choices=("v3", "trend"),
                    help="v3 = the 16 cho_v3.FEATURE_NAMES (every pre-v3.14 data set); trend = FEATURE_NAMES_TREND")
    a = ap.parse_args(argv)
    lo, hi = map(int, a.seeds.split("-"))
    profiles = json.loads(a.profiles.read_text(encoding="utf-8"))["profiles"]
    a.out.mkdir(parents=True, exist_ok=True)
    if a.mix:
        mix = a.mix.split(",")
        tasks = [(mix[(sd - lo) % len(mix)], f, sd, profiles, str(a.out), a.features)
                 for sd in range(lo, hi + 1) for f in FADINGS]
    else:
        tasks = [(s, f, sd, profiles, str(a.out), a.features) for sd in range(lo, hi + 1)
                 for s in SCENARIOS for f in FADINGS]
    with Pool(a.workers) as pool:
        for i, (k, dt) in enumerate(pool.imap_unordered(_task, tasks)):
            print(f"[{i + 1}/{len(tasks)}] {k} {dt:.0f}s", file=sys.stderr, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
