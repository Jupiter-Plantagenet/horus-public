"""v3.14 central step (pipeline/finals_preregistration_v3_14.json, development step 1).

Every setting comes from the pre-registration file's "central" block, so the
registered configuration and the run cannot drift apart. Trains ONE
multi-head network on the central fit data and writes one checkpoint per
pre-registered decision configuration (identical tensors, different decision
rule / constants), each with a frozen-schema artifact (gate.verdict pending).

    python -m twin.train_v314 --data working/evidence/v3.14/data-fit
"""

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

from .cho_v3 import FEATURE_SETS
from .finals_common import REPO, single_thread
from .selector_v3 import PREDICTION_HEADS, check_cost_params
from .train_v3 import HEAD_SCALES, files_for, fit, load_dataset, regret, save_checkpoint, write_artifact

PLAN = REPO / "pipeline" / "finals_preregistration_v3_14.json"


def sha256(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def seed_range(s):
    lo, hi = map(int, s.split(".."))
    return range(lo, hi + 1)


def load_plan(path=PLAN):
    plan = json.loads(Path(path).read_text(encoding="utf-8"))
    c = plan["central"]
    for name, cfg in c["configs"].items():
        check_cost_params(cfg["cost_rule"], cfg.get("cost_params"))
    if c["feature_set"] not in FEATURE_SETS:
        raise SystemExit(f"unknown feature set {c['feature_set']}")
    return plan


def main(argv=None):
    single_thread()
    ap = argparse.ArgumentParser(prog="python -m twin.train_v314")
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--plan", type=Path, default=PLAN)
    ap.add_argument("--threads", type=int, default=1, help="torch intra-op threads for the fit (speed only)")
    a = ap.parse_args(argv)
    log = lambda *x: print(*x, file=sys.stderr, flush=True)
    plan = load_plan(a.plan)
    c = plan["central"]
    seeds = seed_range(c["fit_seeds"])
    files = files_for([a.data], seeds=set(seeds))
    if len(files) != 12 * len(seeds):
        raise SystemExit(f"expected {12 * len(seeds)} fit episodes ({c['fit_seeds']} x 12 cells), found {len(files)}")
    profiles = json.loads((REPO / "pipeline" / c["profiles"]).read_text(encoding="utf-8"))["profiles"]
    if a.threads > 1:
        import torch
        torch.set_num_threads(a.threads)
        import twin.selector_v3 as S
        import twin.train_v3 as T
        S._torch = T._torch = lambda: torch
    t0 = time.time()
    X, Y, w, _ = load_dataset(files, h=c["label_window_snaps"], seed=0, heads=3, rows_per_ue=c["rows_per_ue"])
    want = len(FEATURE_SETS[c["feature_set"]])
    if X.shape[1] != want:
        raise SystemExit(f"fit data has {X.shape[1]} features, the plan's set {c['feature_set']} has {want}")
    log(f"train: {len(files)} episodes, {len(X)} samples, K={Y.shape[1]}, heads=3 ({time.time() - t0:.0f}s)")
    state, norm = fit(X, Y, w, epochs=c["epochs"], lr=c["lr"], batch=c["batch"], seed=c["seed"], log=log,
                      hidden=c["hidden"], weight_decay=c["weight_decay"], rank_weight=c["rank_weight"],
                      rank_tau=c["rank_tau"])
    plan_hash = sha256(a.plan)
    for version, cfg in c["configs"].items():
        r = regret(state, norm, X[:200000], Y[:200000], w[:200000], rule=cfg["cost_rule"],
                   cost_params=cfg.get("cost_params"))
        log(f"train-set (first 200k rows) {version}", r)
        meta = {"period_s": c["period_s"], "warm_s": c["warm_s"], "margin": c["margin"],
                "switch_margin": cfg["switch_margin"], "min_dwell_s": cfg.get("min_dwell_s", 0.0),
                "label_window_s": 5.0 * c["label_window_snaps"], "prediction_heads": list(PREDICTION_HEADS),
                "head_scales": list(HEAD_SCALES), "hidden": c["hidden"], "cost_rule": cfg["cost_rule"],
                "train_files": [Path(f).stem for f in files], "experiment_plan_sha256": plan_hash}
        if cfg.get("cost_params") is not None:
            meta["cost_params"] = cfg["cost_params"]
        p = save_checkpoint(version, state, norm, profiles, meta)
        write_artifact(version, files)
        log(f"saved {p} sha256 {sha256(p)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
