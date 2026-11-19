"""Train the HORUS v3 CHO profile selector (selector_v3.py) from full-
information counterfactual data (v3_data.py).

Learning problem: cost-sensitive regression. Input = a UE's online situation
features at time t (taken on the trajectory of some profile j); target =
the utility each of the K profiles delivers to that UE over [t, t+H],
relative to the default profile (the twin replays every profile on the same
radio, so every target is observed — no exploration, no bootstrapping; this
is behaviour cloning of the per-UE, per-window ORACLE profile with a
value-aware loss, which is what the v2 DQN could not get from 1%-dense HO
rewards). Cells are weighted equally (one file = one (cell, seed) episode).

Federated use: `fit(..., init=global_state, prox_mu=mu)` adds the FedProx
proximal term mu/2 * ||w - w_global||^2 to the local objective;
`label_sign=-1` is the poisoned client (targets flipped: it learns to pick
the WORST profile).

    python -m twin.train_v3 --data working/evidence/finals-v3/data-train --version v3.0.0
"""

import argparse
import glob
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .cho_v3 import FEATURE_NAMES, FEATURE_NAMES_TREND, N_FEATURES
from .dqn import checkpoint_path
from .selector_v3 import ARCH, HIDDEN, _torch, build_mlp
from .v3_data import window_utility

H_SNAPS = 12            # 60 s label window (5 s snapshots)
Y_CLIP = 4.0            # a profile that loses > 4 utility/UE-min in a window is simply "terrible";
                        # its exact value must not dominate the regression (k=0 churn reaches -270)
ROWS_PER_UE = 3         # trajectories (profiles) sampled per (UE, snapshot) for the inputs


def window_rates(d, s0, s1):
    """Absolute HO-attempt and failure rates per UE-minute per (profile, UE)
    over snapshots s0..s1 — the same counters window_utility weighs."""
    g = lambda k: d[f"cum_{k}"][s1] - d[f"cum_{k}"][s0]
    minutes = np.maximum(g("samples"), 1) * 0.1 / 60.0
    return g("ho_attempts") / minutes, g("fail") / minutes


def load_dataset(files, default=0, h=H_SNAPS, rows_per_ue=ROWS_PER_UE, seed=0, min_snap=2, heads=1):
    """-> X (M, F), Y, w (M,), group ids.
    heads=1: Y (M, K) utility relative to the default (v3.1.x).
    heads=3: Y (M, K, 3) = [utility relative to default, abs HO rate, abs failure rate]
    (finals_preregistration_v3_13.json). Input sampling is identical for both."""
    rng = np.random.default_rng(seed)
    Xs, Ys, Ws, G = [], [], [], []
    for gi, f in enumerate(files):
        d = dict(np.load(f))
        S = d["cum_se"].shape[0] - 1
        X = d["X"]                     # (S, R, N, F): X[s-1] = features at snapshot s
        R, N = X.shape[1], X.shape[2]
        xs, ys, ws = [], [], []
        for s in range(min_snap, S):
            s1 = min(S, s + h)
            u = window_utility(d, s, s1)          # (R, N)
            rel = (u - u[default][None]).T        # (N, K)
            if heads == 3:
                ho, fail = window_rates(d, s, s1)
                rel = np.stack([rel, ho.T, fail.T], axis=-1)   # (N, K, 3)
            for i in range(N):
                js = np.concatenate([[default], rng.choice(np.arange(1, R), rows_per_ue - 1, replace=False)])
                for j in js:
                    xs.append(X[s - 1, j, i])
                    ys.append(rel[i])
                    ws.append((s1 - s) / h)
        w = np.asarray(ws)
        Xs.append(np.asarray(xs))
        Ys.append(np.asarray(ys))
        Ws.append(w / w.sum())
        G.append(np.full(len(xs), gi))
    return (np.concatenate(Xs).astype(np.float32), np.concatenate(Ys).astype(np.float32),
            np.concatenate(Ws).astype(np.float32), np.concatenate(G))


HEAD_SCALES = (1.0, 1.0, 5.0)   # v3.13: utility, HO rate, failure rate (5 = failure weight in the utility)


def prepare_targets(Y, label_sign=1.0, head_scales=HEAD_SCALES):
    """Training targets. 2-D Y (v3.1.x): clipped utility. 3-D Y (v3.13): utility
    clipped as before, rate heads NEVER clipped, each head times its scale,
    flattened profile-major to (M, K*3) to match the network output."""
    if Y.ndim == 2:
        return (label_sign * np.clip(Y, -Y_CLIP, Y_CLIP)).astype(np.float32)
    # float32 throughout (half the memory of a float64 copy) and bit-identical to it: clipping is
    # exact and x * s for a float32 x and s in {1, 5} is exact in float64, so rounding it once to
    # float32 equals the float32 product; label_sign is +-1
    T = np.array(Y, dtype=np.float32, copy=True)
    np.clip(T[:, :, 0], -Y_CLIP, Y_CLIP, out=T[:, :, 0])
    T *= np.asarray(head_scales, np.float32)[None, None, :]
    if label_sign != 1.0:
        T *= np.float32(label_sign)
    return T.reshape(len(T), -1)


def fit(X, Y, w, epochs=40, lr=2e-3, batch=512, seed=0, init=None, prox_mu=0.0,
        label_sign=1.0, norm=None, log=None, hidden=HIDDEN, weight_decay=1e-5, head_scales=HEAD_SCALES,
        rank_weight=0.0, rank_tau=0.1):
    torch = _torch()
    torch.manual_seed(seed)
    if norm is None:
        mu = X.mean(0)
        sd = X.std(0) + 1e-3
    else:
        mu, sd = norm
    Xn = torch.from_numpy((X - mu) / sd)
    T = prepare_targets(Y, label_sign, head_scales)
    Yt = torch.from_numpy(T)
    Wt = torch.from_numpy(w * (len(w) / w.sum()))
    net = build_mlp(X.shape[1], T.shape[1], hidden)
    if init is not None:
        net.load_state_dict(init)
    anchor = None
    if prox_mu > 0 and init is not None:
        anchor = [p.detach().clone() for p in net.parameters()]
    opt = torch.optim.Adam(net.parameters(), lr=lr, weight_decay=weight_decay)
    g = torch.Generator().manual_seed(seed)
    n = len(Xn)
    for ep in range(epochs):
        perm = torch.randperm(n, generator=g)
        tot = 0.0
        for b in range(0, n, batch):
            ix = perm[b:b + batch]
            out = net(Xn[ix])
            err = torch.nn.functional.huber_loss(out, Yt[ix], reduction="none", delta=1.0)
            per = err.mean(1)
            if rank_weight > 0:
                # v3.14 option: listwise (ListNet) cross-entropy between the softmax of predicted and
                # target utility over the K profiles - trains the ranking the argmax decision uses
                k3 = 3 if Y.ndim == 3 else 1
                pu = out.view(len(ix), -1, k3)[:, :, 0] / (head_scales[0] * rank_tau)
                tu = Yt[ix].view(len(ix), -1, k3)[:, :, 0] / (head_scales[0] * rank_tau)
                per = per + rank_weight * -(torch.softmax(tu, 1) * torch.log_softmax(pu, 1)).sum(1)
            loss = (per * Wt[ix]).mean()
            if anchor is not None:
                loss = loss + 0.5 * prox_mu * sum(((p - a) ** 2).sum() for p, a in zip(net.parameters(), anchor))
            opt.zero_grad()
            loss.backward()
            opt.step()
            tot += float(loss.detach()) * len(ix)
        if log and (ep % 10 == 9 or ep == epochs - 1):
            log(f"  epoch {ep + 1}/{epochs} loss {tot / n:.4f}")
    return {k: v.detach().clone() for k, v in net.state_dict().items()}, (mu, sd)


def regret(state, norm, X, Y, w, margin=0.0, rule="utility_only", head_scales=HEAD_SCALES, cost_params=None):
    """Offline (open-loop) diagnostics: weighted gain over the default of the
    chosen profile and of the per-window oracle. For 3-D Y the choice follows
    the cost rule exactly as selector_v3.CHOSelectorPolicy.predict
    (selector_v3.score_profiles)."""
    from .selector_v3 import NumpyMLP, check_cost_params, score_profiles
    q = NumpyMLP({k: v.numpy() for k, v in state.items()})((X - norm[0]) / norm[1])
    U = Y
    if Y.ndim == 3:
        heads = q.reshape(len(X), Y.shape[1], 3) / np.asarray(head_scales, float)
        q, _ = score_profiles(heads, rule, check_cost_params(rule, cost_params), 0)
        U = Y[:, :, 0]
    q[:, 0] = 0.0
    ch = np.where(q.max(1) > margin, q.argmax(1), 0)
    got = U[np.arange(len(U)), ch]
    out = {"gain_vs_default": float((got * w).sum() / w.sum()),
           "oracle_gain": float((U.max(1) * w).sum() / w.sum()),
           "frac_non_default": float(((ch != 0) * w).sum() / w.sum())}
    if Y.ndim == 3:
        rows = np.arange(len(Y))
        out["chosen_fail_rate"] = float((Y[rows, ch, 2] * w).sum() / w.sum())
        out["default_fail_rate"] = float((Y[:, 0, 2] * w).sum() / w.sum())
        out["chosen_ho_rate"] = float((Y[rows, ch, 1] * w).sum() / w.sum())
        out["default_ho_rate"] = float((Y[:, 0, 1] * w).sum() / w.sum())
    return out


def save_checkpoint(version, state, norm, profiles, meta, root=None, overwrite=False):
    torch = _torch()
    out = checkpoint_path(version, root)
    if out.exists() and not overwrite:
        raise SystemExit(f"{out} exists — bump the version")
    ck = {"arch": ARCH, "version": version, "profiles": profiles, "default": 0,
          "feature_names": list(FEATURE_NAMES if len(norm[0]) == N_FEATURES else FEATURE_NAMES_TREND), "x_mean": [float(x) for x in norm[0]],
          "x_std": [float(x) for x in norm[1]], "hidden": HIDDEN, "state_dict": state,
          "created_ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), **meta}
    torch.save(ck, out)
    return out


def write_artifact(version, files, out_dir=None):
    """Frozen-schema policy artifact (gate.verdict pending) for a central v3 checkpoint."""
    import torch
    from .federate import git_commit
    from .finals_common import RADIO_MAP, REPO
    ck = torch.load(checkpoint_path(version), map_location="cpu", weights_only=True)
    names = [Path(f).stem.rsplit("-", 2) for f in files]
    art = {"version": version, "weights_ref": f"pipeline/checkpoints/dqn-{version}.pt",
           "algo": ARCH, "created_ts": ck["created_ts"],
           "trained_on": {"radio_map": RADIO_MAP, "twin_commit": git_commit(),
                          "scenarios": sorted({n[0] for n in names}),
                          "seeds": sorted({int(n[2]) for n in names}), "radio_model": "phy-v2",
                          "fading": sorted({n[1] for n in names}), "obs_filter": {"l3_k": 4}},
           "provenance": None,
           "gate": {"verdict": "pending", "worst_case_score": None, "threshold": None,
                    "scenario_suite": None, "evaluated_ts": None}}
    out_dir = out_dir or (REPO / "working" / "candidates")
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"v3-central-{version}.json"
    p.write_text(json.dumps(art, indent=2) + "\n", encoding="utf-8")
    return p


def files_for(data_dirs, scenarios=None, seeds=None):
    out = []
    for d in data_dirs:
        for f in sorted(glob.glob(str(Path(d) / "*.npz"))):
            name = Path(f).stem
            if name.endswith(".tmp"):
                continue
            sc, fad, sd = name.rsplit("-", 2)
            if scenarios is not None and sc not in scenarios:
                continue
            if seeds is not None and int(sd) not in seeds:
                continue
            out.append(f)
    return out


def main(argv=None):
    from .finals_common import single_thread
    single_thread()
    ap = argparse.ArgumentParser(prog="python -m twin.train_v3")
    ap.add_argument("--data", action="append", required=True)
    ap.add_argument("--val-data", action="append", default=None)
    ap.add_argument("--profiles", type=Path, required=True)
    ap.add_argument("--version", required=True)
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--h", type=int, default=H_SNAPS)
    ap.add_argument("--period", type=float, default=2.0)
    ap.add_argument("--warm", type=float, default=10.0)
    ap.add_argument("--margin", type=float, default=0.0)
    ap.add_argument("--switch-margin", type=float, default=0.0)
    ap.add_argument("--overwrite", action="store_true")
    a = ap.parse_args(argv)
    log = lambda *x: print(*x, file=sys.stderr, flush=True)
    profiles = json.loads(a.profiles.read_text(encoding="utf-8"))["profiles"]
    tr_files = files_for(a.data)
    t0 = time.time()
    X, Y, w, _ = load_dataset(tr_files, h=a.h, seed=a.seed)
    log(f"train: {len(tr_files)} episodes, {len(X)} samples, K={Y.shape[1]} ({time.time() - t0:.0f}s)")
    state, norm = fit(X, Y, w, epochs=a.epochs, seed=a.seed, log=log)
    meta = {"period_s": a.period, "warm_s": a.warm, "margin": a.margin,
            "switch_margin": a.switch_margin, "label_window_s": 5.0 * a.h,
            "train_files": [Path(f).stem for f in tr_files]}
    log("train-set", regret(state, norm, X, Y, w))
    if a.val_data:
        vf = files_for(a.val_data)
        Xv, Yv, wv, _ = load_dataset(vf, h=a.h, seed=a.seed + 1)
        for m in (0.0, 0.05, 0.1, 0.2):
            log(f"val (margin {m})", regret(state, norm, Xv, Yv, wv, m))
    p = save_checkpoint(a.version, state, norm, profiles, meta, overwrite=a.overwrite)
    log(f"saved {p}")
    write_artifact(a.version, tr_files)
    return 0


if __name__ == "__main__":
    sys.exit(main())
