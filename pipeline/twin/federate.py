"""Federated training round (#9): 3 clients, FedAvg + coordinate-wise median.

The system trains the way the proposal says it does: three campus 'sites'
train locally on **distinct mobility mixes** (their non-IID-ness is the
point — a lecture-hall site sees stationary crowds, a gate site sees
commuter streams), updates are aggregated centrally, and the aggregated
candidate is emitted as a frozen-schema `policy_artifact` (gate.verdict =
"pending" — the safety gate #10 is the only thing that can promote it).

The poisoned-client switch (--poison) models a compromised participant
sending adversarial updates (sign-flipped delta from the global weights, a
standard model-poisoning primitive). FedAvg averages the poison straight
into the candidate; coordinate-wise median discards it — that contrast is
consumed by #10's promote/reject evidence.

Run inside the ML venv:
    ~/horus-ml/bin/python -m twin.federate --init-version v0.1.0 --round 1
    ~/horus-ml/bin/python -m twin.federate --init-version v0.1.0 --round 1 --poison
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from .dqn import checkpoint_path
from .train_dqn import run_training

# Distinct mobility mixes per client — the non-IID split.
CLIENT_MIXES = {
    "client-gate":    ("rush_hour", "rush_hour", "corner_turner"),
    "client-quad":    ("corner_turner", "rush_hour", "stationary_clusters"),
    "client-lecture": ("stationary_clusters", "stationary_clusters", "corner_turner"),
}


def fedavg(state_dicts):
    import torch
    out = {}
    for k in state_dicts[0]:
        out[k] = torch.stack([sd[k].float() for sd in state_dicts]).mean(0)
    return out


def coordinate_median(state_dicts):
    import torch
    out = {}
    for k in state_dicts[0]:
        out[k] = torch.stack([sd[k].float() for sd in state_dicts]).median(0).values
    return out


def boost(global_sd, poisoned_sd, scale):
    """Model-replacement / boosting attack (Bagdasaryan et al.): the attacker
    amplifies its update delta so it survives FedAvg's 1/n averaging —
    submitted = global + scale*(poisoned_local - global). This is what breaks
    naive FedAvg (the boosted delta dominates the mean) while coordinate-wise
    median stays robust (it discards the magnitude outlier per coordinate).
    Combined with reward-flipped local training, it's a genuine strong
    adversary, not a rigged one — the threshold/scoring are untouched."""
    import torch
    return {k: global_sd[k].float() + scale * (poisoned_sd[k].float() - global_sd[k].float())
            for k in global_sd}


def git_commit():
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, timeout=10,
                              cwd=Path(__file__).resolve().parent).stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def local_round(client, mix, init_sd, episodes, seed, radio_map, round_no, out_dir,
                reward_sign=1.0):
    """A few local episodes on this client's mobility mix, starting from the
    shared global weights (init_sd) — the defining property of a federated
    round. reward_sign=-1 makes this the POISONED client (issue #9's
    'reward-flipped updates'): it genuinely optimizes for churn and bad
    coverage from the global init, so its update direction is adversarial
    and large enough to actually drag a naive average. (The first attempt —
    sign-flipping a 9-episode delta — was too weak to move FedAvg; see the
    gate suite-v1 discovery note in gate_config.json.) Client intermediates
    are versioned by round, kept out of the candidate namespace via fed-."""
    import torch
    ckpt, _ = run_training(
        f"fed-r{round_no}-{client}", episodes, seed, radio_map, out_dir,
        log=lambda *a: None, init_state_dict=init_sd, scenario_mix=mix,
        curve_name=f"dqn_training_curve-fed-r{round_no}-{client}.csv",
        allow_overwrite=True,   # intermediates, never gated — overwrite is fine
        reward_sign=reward_sign)
    return torch.load(ckpt, map_location="cpu", weights_only=True)["state_dict"]


def emit_artifact(version, weights_version, agg, round_no, clients, seeds, radio_map, out):
    art = {
        "version": version,
        "weights_ref": f"pipeline/checkpoints/dqn-{weights_version}.pt",
        "algo": "dqn_lstm",
        "created_ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "trained_on": {"radio_map": radio_map, "twin_commit": git_commit(),
                       "scenarios": sorted({s for m in CLIENT_MIXES.values() for s in m}),
                       "seeds": seeds},
        "provenance": {"client_ids": clients, "aggregation": agg, "round": round_no},
        "gate": {"verdict": "pending", "worst_case_score": None, "threshold": None,
                 "scenario_suite": None, "evaluated_ts": None},
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(art, indent=2) + "\n", encoding="utf-8")
    return art


def main(argv=None):
    import torch
    ap = argparse.ArgumentParser(prog="python -m twin.federate")
    ap.add_argument("--init-version", required=True, help="global model to start from (#8 checkpoint)")
    ap.add_argument("--round", type=int, default=1)
    ap.add_argument("--local-episodes", type=int, default=9)
    # Client env seeds are seed + 20*i + episode. Training seeds must stay
    # strictly below the gate's pre-registered evaluation seeds (1000+, see
    # gate_config.json) — identical seeds mean bit-identical episodes, i.e.
    # evaluating on the training set.
    ap.add_argument("--seed", type=int, default=200)
    ap.add_argument("--radio-map", default="placeholder")
    ap.add_argument("--poison", action="store_true",
                    help="client-lecture becomes a reward-flipped + boosted (model-replacement) adversary")
    ap.add_argument("--boost", type=float, default=3.0,
                    help="poisoned-update boosting scale (~n_clients; survives FedAvg averaging)")
    ap.add_argument("--force", action="store_true",
                    help="overwrite existing candidate checkpoints for this round")
    ap.add_argument("--out-dir", type=Path,
                    default=Path(__file__).resolve().parents[2] / "working" / "candidates")
    args = ap.parse_args(argv)

    init_ckpt = torch.load(checkpoint_path(args.init_version), map_location="cpu",
                           weights_only=True)
    global_sd, cells = init_ckpt["state_dict"], init_ckpt["cells"]
    tag = "poisoned" if args.poison else "clean"
    print(f"federated round {args.round} ({tag}): 3 clients x {args.local_episodes} local episodes",
          file=sys.stderr)

    updates, clients, seeds = [], [], []
    for i, (client, mix) in enumerate(sorted(CLIENT_MIXES.items())):
        seed = args.seed + 20 * i
        poisoned = args.poison and client == "client-lecture"
        sd = local_round(client, mix, global_sd, args.local_episodes, seed,
                         args.radio_map, args.round,
                         Path(__file__).resolve().parents[2] / "working" / "evidence" / "fed",
                         reward_sign=-1.0 if poisoned else 1.0)
        if poisoned:
            # reward-flipped adversary + boosting so it survives 1/n averaging
            sd = boost(global_sd, sd, args.boost)
            client += " (POISONED)"
        updates.append(sd)
        clients.append(client)
        seeds.append(seed)
        print(f"  {client}: local round done ({', '.join(mix)})", file=sys.stderr)

    # Candidate versions: v1.<round>.<n> — n counts candidates within the
    # round in emission order (fedavg=0, median=1 clean; fedavg=2, median=3
    # poisoned). Whether a candidate is poisoned/aggregated-how lives in
    # provenance and the filename, never in version-digit numerology.
    for n, (agg_name, agg_fn) in enumerate((("fedavg", fedavg), ("median", coordinate_median))):
        agg_sd = agg_fn(updates)
        version = f"v1.{args.round}.{n + (2 if args.poison else 0)}"
        if checkpoint_path(version).exists() and not args.force:
            raise SystemExit(f"dqn-{version}.pt exists — a gated verdict may bind to it; "
                             "bump --round or pass --force")
        torch.save({"version": version, "cells": cells, "state_dict": agg_sd,
                    "radio_map": args.radio_map, "seed": args.seed,
                    "episodes": args.local_episodes,
                    "created_ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
                   checkpoint_path(version))
        art_path = args.out_dir / f"{tag}-{agg_name}-r{args.round}.json"
        emit_artifact(version, version, agg_name, args.round, clients, seeds,
                      args.radio_map, art_path)
        print(f"  candidate ({agg_name}) -> {art_path}  [weights dqn-{version}.pt, version {version}]",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
