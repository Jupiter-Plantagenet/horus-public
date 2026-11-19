"""Federated rounds for the v3 selector (finals), designed not to drift.

Why v2 federation drifted: each client ran 12 RL episodes on a skewed mix
with no demonstrations, so its local Q-values for the situations it never saw
(e.g. faded stationary users at the gate site) wandered freely, and FedAvg
averaged that wander in. Here:
  - local objective = the same full-information regression as central
    training (every local sample is a labelled counterfactual "demonstration"
    from the client's own traffic; nothing is bootstrapped);
  - FedProx proximal term mu/2 ||w - w_global||^2 keeps each client near the
    global model where its data says nothing;
  - input normalisation is the global model's (fixed), so client updates live
    in the same coordinates;
  - server aggregation FedAvg or coordinate-wise median (robust option kept),
    with optional server momentum.

Clients = federate.CLIENT_MIXES (the v2 non-IID split); client i trains on
counterfactual data generated at its own seed block (620+100i ..., see
v3_data --mix). The poisoned client (client-lecture) flips its targets and
boosts its delta (federate.boost), same attack family as the v2 round.

Candidates v3.<round>.<n>: n = 0 clean-fedavg, 1 clean-median,
2 poisoned-fedavg, 3 poisoned-median; written as frozen-schema policy
artifacts with gate.verdict = "pending".

    python -m twin.fed_v3 --init-version v3.0.0 --round 1 [--poison]
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .dqn import checkpoint_path
from .federate import CLIENT_MIXES, boost, coordinate_median, fedavg, git_commit
from .finals_common import EVIDENCE, RADIO_MAP, REPO, single_thread
from .selector_v3 import HIDDEN
from .train_v3 import H_SNAPS, files_for, fit, load_dataset, regret

POISONED = "client-lecture"
FED_DATA = EVIDENCE / "finals-v3" / "data-fed"


def client_round(job):
    single_thread()
    import torch
    client, gsd, norm, epochs, mu, sign, h, seed, heads, fed_data, hidden = job
    files = files_for([Path(fed_data) / client])
    X, Y, w, _ = load_dataset(files, h=h, seed=seed, heads=heads)
    sd, _ = fit(X, Y, w, epochs=epochs, seed=seed, init=gsd, prox_mu=mu, label_sign=sign, norm=norm,
                hidden=hidden)
    return client, sd, len(files), len(X)


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main(argv=None):
    single_thread()
    import torch
    ap = argparse.ArgumentParser(prog="python -m twin.fed_v3")
    ap.add_argument("--init-version", required=True)
    ap.add_argument("--round", type=int, default=1)
    ap.add_argument("--server-rounds", type=int, default=3, help="aggregation steps inside this round")
    ap.add_argument("--epochs", type=int, default=6)
    ap.add_argument("--mu", type=float, default=0.05)
    ap.add_argument("--server-momentum", type=float, default=0.0)
    ap.add_argument("--poison", action="store_true")
    ap.add_argument("--boost", type=float, default=3.0)
    ap.add_argument("--h", type=int, default=H_SNAPS)
    ap.add_argument("--out-dir", type=Path, default=REPO / "working" / "candidates")
    ap.add_argument("--val-data", type=Path, default=EVIDENCE / "finals-v3" / "data-tune")
    ap.add_argument("--fed-data", type=Path, default=FED_DATA, help="dir with one sub-dir of .npz per client")
    ap.add_argument("--version-base", default=None,
                    help="e.g. v3.13 -> candidates <base>.<offset+n> (default v3.<round>.<n>)")
    ap.add_argument("--version-offset", type=int, default=0)
    a = ap.parse_args(argv)
    init = torch.load(checkpoint_path(a.init_version), map_location="cpu", weights_only=True)
    if init.get("arch") != "ctx_cho_selector":
        raise SystemExit(f"{a.init_version} is not a v3 selector checkpoint")
    norm = (np.asarray(init["x_mean"], np.float32), np.asarray(init["x_std"], np.float32))
    heads = 3 if init.get("prediction_heads") else 1
    rule = init.get("cost_rule", "utility_only")
    cost_params = init.get("cost_params")
    hidden = int(init.get("hidden", HIDDEN))
    log = lambda *x: print(*x, file=sys.stderr, flush=True)
    vf = files_for([a.val_data])
    Xv, Yv, wv, _ = load_dataset(vf, h=a.h, seed=7, heads=heads) if vf else (None,) * 4
    tag = "poisoned" if a.poison else "clean"
    results = {}
    for n0, (agg, fn) in enumerate((("fedavg", fedavg), ("median", coordinate_median))):
        g = {k: v.float().clone() for k, v in init["state_dict"].items()}
        vel = {k: torch.zeros_like(v) for k, v in g.items()}
        history = []
        for sr in range(a.server_rounds):
            jobs = [(c, g, norm, a.epochs, a.mu, -1.0 if (a.poison and c == POISONED) else 1.0,
                     a.h, 1000 * a.round + 10 * sr + i, heads, str(a.fed_data), hidden)
                    for i, c in enumerate(sorted(CLIENT_MIXES))]
            from multiprocessing import Pool
            with Pool(len(jobs)) as pool:   # per-job seeds fix every result; pool size only sets speed
                outs = pool.map(client_round, jobs)
            ups = []
            for c, sd, nf, ns in outs:
                if a.poison and c == POISONED:
                    sd = boost(g, sd, a.boost)
                ups.append(sd)
            new = fn(ups)
            for k in g:
                step = new[k] - g[k]
                vel[k] = a.server_momentum * vel[k] + step
                g[k] = g[k] + vel[k]
            r = regret(g, norm, Xv, Yv, wv, rule=rule, cost_params=cost_params) if Xv is not None else {}
            history.append({"server_round": sr + 1, **r})
            log(f"[{tag}/{agg}] server round {sr + 1}: tuning-seed offline {r}")
        n = n0 + (2 if a.poison else 0)
        version = f"{a.version_base}.{a.version_offset + n}" if a.version_base else f"v3.{a.round}.{n}"
        out = checkpoint_path(version)
        if out.exists():
            raise SystemExit(f"{out} exists — a verdict may bind to it; bump --round")
        meta = {k: v for k, v in init.items() if k != "state_dict"}
        meta.update({"version": version, "state_dict": g, "created_ts": now(),
                     "federated": {"round": a.round, "aggregation": agg, "server_rounds": a.server_rounds,
                                   "local_epochs": a.epochs, "prox_mu": a.mu,
                                   "server_momentum": a.server_momentum, "init": a.init_version,
                                   "poisoned_client": POISONED if a.poison else None,
                                   "boost": a.boost if a.poison else None, "history": history}})
        torch.save(meta, out)
        clients = [c + (" (POISONED)" if a.poison and c == POISONED else "") for c in sorted(CLIENT_MIXES)]
        seeds = sorted({int(Path(f).stem.rsplit("-", 1)[1]) for c in CLIENT_MIXES
                        for f in files_for([a.fed_data / c])})
        art = {
            "version": version, "weights_ref": f"pipeline/checkpoints/dqn-{version}.pt",
            "algo": "ctx_cho_selector", "created_ts": meta["created_ts"],
            "trained_on": {"radio_map": RADIO_MAP, "twin_commit": git_commit(),
                           "scenarios": sorted({s for m in CLIENT_MIXES.values() for s in m}),
                           "seeds": seeds, "radio_model": "phy-v2", "fading": ["off", "rician", "rayleigh"],
                           "obs_filter": {"l3_k": 4}},
            "provenance": {"client_ids": clients, "aggregation": agg, "round": a.round},
            "gate": {"verdict": "pending", "worst_case_score": None, "threshold": None,
                     "scenario_suite": None, "evaluated_ts": None},
        }
        p = a.out_dir / (f"v3-{tag}-{agg}-{version}.json" if a.version_base else f"v3-{tag}-{agg}-r{a.round}.json")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(art, indent=2) + "\n", encoding="utf-8")
        results[agg] = history[-1] if history else {}
        log(f"  candidate {version} ({agg}) -> {p}")
    print(json.dumps(results, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
