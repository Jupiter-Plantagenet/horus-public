"""Train the DQN+LSTM handover policy in the twin (#8).

Standard DQN with a target network and replay over windowed sequences
(DRQN-lite: the LSTM sees a fixed WINDOW of reports per decision, so replay
stays a flat buffer of (window, action, reward, next_window, done) tuples).

Reward per the proposal — the three things the project measures:
    r = RSRP_W * serving_rsrp_normalized        (coverage actually delivered)
        - HO_COST      on every executed HO      (churn is not free)
        - PP_PENALTY   on a ping-pong            (the A3 pathology)
        - FAIL_PENALTY on a failed HO / RLF

Training mixes all three scenarios so the policy can't overfit one mobility
pattern; evaluation (compare.py) then scores the SAME scenario x seed pairs
for DQN and A3.

Curves go to CSV (working/evidence/dqn_training_curve.csv), the checkpoint
is saved under a --version string (pipeline/checkpoints/dqn-<version>.pt)
with metadata — that version string is exactly what policy_artifact.weights_ref
references for the gate (#10) and the A1 store (#11).

Run inside the ML venv:  ~/horus-ml/bin/python -m twin.train_dqn --version v0.1.0
"""

import argparse
import csv
import random
import sys

import numpy as np
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from .dqn import build_net, cell_order, checkpoint_path, make_encoder
from .env import TwinEnv
from .radio import normalize_rsrp

RSRP_W = 1.0
HO_COST = 0.2
PP_PENALTY = 2.0
FAIL_PENALTY = 3.0

GAMMA = 0.95
LR = 1e-3
BATCH = 64
REPLAY_CAP = 100_000
TARGET_SYNC = 500        # gradient steps between target-net syncs
TRAIN_EVERY = 4          # env decisions per gradient step

SCENARIO_MIX = ("rush_hour", "corner_turner", "stationary_clusters")


def td_target(rs, q_next, dones, gamma=GAMMA):
    """Bellman target with terminal masking — terminal transitions must not
    bootstrap (their stored next-window is the same state). Factored out so
    the test suite can pin the masking down."""
    return rs + gamma * q_next * (1.0 - dones)


def run_training(version, episodes, seed, radio_map, out_dir, log=print,
                 init_state_dict=None, scenario_mix=SCENARIO_MIX,
                 curve_name=None, allow_overwrite=False, reward_sign=1.0,
                 encoder_spec=None, ckpt_root=None, extra_meta=None, ho_cost=None):
    """reward_sign=-1.0 trains an ADVERSARY (the #9 poisoned client): the
    net optimizes the negated reward — maximize churn/failures, minimize
    coverage. Metrics stay honest; only the learning signal flips.

    encoder_spec=None keeps the v1 cell-slot input (one slot per named cell
    of `radio_map`); {"kind": "rank", "k": K} trains the campus-agnostic
    policy (see dqn.RankEncoder) that federates/transfers across campuses.
    ckpt_root / extra_meta: where the checkpoint goes and what extra
    provenance it carries (the any-campus pipeline uses both). ho_cost
    overrides HO_COST (per-HO signalling penalty) for this run."""
    ho_cost = HO_COST if ho_cost is None else ho_cost
    import torch
    torch.manual_seed(seed)
    random.seed(seed)

    from .radio import load_radio_map
    cells = (None if encoder_spec else
             cell_order(load_radio_map(radio_map, seed).measure(0.0, 0.0)))
    enc = make_encoder(encoder_spec, cells)

    ckpt_out = checkpoint_path(version, ckpt_root)
    if ckpt_out.exists() and not allow_overwrite:
        raise FileExistsError(
            f"{ckpt_out} already exists — a gated verdict binds to this version; "
            "pick a new version or pass allow_overwrite=True (--force)")

    net = build_net(n_in=enc.n_in, n_actions=enc.n_actions)
    target = build_net(n_in=enc.n_in, n_actions=enc.n_actions)
    if init_state_dict is not None:
        # Federated local round (#9): every client MUST start from the shared
        # global weights or the aggregate is averaging unrelated nets.
        net.load_state_dict(init_state_dict)
    target.load_state_dict(net.state_dict())
    opt = torch.optim.Adam(net.parameters(), lr=LR)
    replay = deque(maxlen=REPLAY_CAP)
    curve_rows, grad_steps = [], 0

    for ep in range(episodes):
        scenario = scenario_mix[ep % len(scenario_mix)]
        env = TwinEnv(scenario=scenario, radio_map=radio_map, seed=seed + ep)
        env.reset()
        eps = max(0.05, 1.0 - ep / max(episodes * 0.7, 1))   # epsilon anneal
        enc.reset()
        pending = {}     # ue_id -> (window, action) awaiting next-step reward
        ep_reward, done = 0.0, False

        while not done:
            env.step_i += 1
            for ue in env.ues:
                env.scenario.move(ue, env.step_i, env.rng)
            obs = env._observations()

            for ue in env.ues:
                rsrp = obs[ue.ue_id]
                enc.push(ue.ue_id, rsrp, ue.serving)
                w = enc.window(ue.ue_id)   # state encoding at t (v1: the raw deque)

                # settle the previous decision's reward now that we see t+1
                if ue.ue_id in pending:
                    pw, pa, pr = pending.pop(ue.ue_id)
                    replay.append((pw, pa, pr, np.asarray(w, dtype=np.float32), False))

                if not enc.ready(ue.ue_id):
                    env.metrics.rsrp_sum += rsrp[ue.serving]
                    env.metrics.rsrp_n += 1
                    continue

                if random.random() < eps:
                    a = random.randrange(enc.n_actions)
                else:
                    with torch.no_grad():
                        q = net(torch.tensor([w], dtype=torch.float32))[0]
                    a = int(q.argmax())

                r = 0.0
                target_cell = enc.target(ue.ue_id, a)
                if target_cell and target_cell != ue.serving:
                    before = (env.metrics.handovers_failed, env.metrics.ping_pongs)
                    env._execute_ho(ue, target_cell, rsrp)
                    r -= ho_cost
                    if env.metrics.handovers_failed > before[0]:
                        r -= FAIL_PENALTY
                    if env.metrics.ping_pongs > before[1]:
                        r -= PP_PENALTY
                r += RSRP_W * normalize_rsrp(rsrp[ue.serving])
                env.metrics.rsrp_sum += rsrp[ue.serving]
                env.metrics.rsrp_n += 1
                r *= reward_sign
                ep_reward += r
                # float32 arrays, not nested lists: 100k boxed-float windows
                # would cost ~0.6 GB on a box sharing RAM with the live stack
                pending[ue.ue_id] = (np.asarray(w, dtype=np.float32), a, r)

                grad_steps += 1
                if len(replay) >= BATCH and grad_steps % TRAIN_EVERY == 0:
                    batch = random.sample(replay, BATCH)
                    xs = torch.from_numpy(np.stack([b[0] for b in batch]))
                    acts = torch.tensor([b[1] for b in batch])
                    rs = torch.tensor([b[2] for b in batch], dtype=torch.float32)
                    nxt = torch.from_numpy(np.stack([b[3] for b in batch]))
                    dones = torch.tensor([float(b[4]) for b in batch])
                    q = net(xs).gather(1, acts.unsqueeze(1)).squeeze(1)
                    with torch.no_grad():
                        q_next = target(nxt).max(1).values
                    loss = torch.nn.functional.smooth_l1_loss(q, td_target(rs, q_next, dones))
                    opt.zero_grad()
                    loss.backward()
                    opt.step()
                    if grad_steps % (TRAIN_EVERY * TARGET_SYNC) == 0:
                        target.load_state_dict(net.state_dict())

            done = env.step_i >= env.scenario.episode_steps

        # flush end-of-episode pendings as terminal transitions
        for ue_id, (pw, pa, pr) in pending.items():
            replay.append((pw, pa, pr, pw, True))

        m = env.metrics.as_dict()
        curve_rows.append({"episode": ep, "scenario": scenario, "epsilon": round(eps, 3),
                           "reward": round(ep_reward, 1), **m})
        log(f"ep {ep:03d} {scenario:<20} eps={eps:.2f} reward={ep_reward:9.1f} "
            f"pp={m['ping_pongs']:3d} ho={m['handovers_attempted']:3d} "
            f"rsrp={m['mean_rsrp_dbm']:.1f}")

    if not curve_rows:
        raise ValueError("no episodes ran (--episodes must be >= 1)")
    out_dir.mkdir(parents=True, exist_ok=True)
    curve_csv = out_dir / (curve_name or f"dqn_training_curve-{version}.csv")
    with curve_csv.open("w", newline="") as f:
        wtr = csv.DictWriter(f, fieldnames=list(curve_rows[0]))
        wtr.writeheader()
        wtr.writerows(curve_rows)

    ckpt_out.parent.mkdir(parents=True, exist_ok=True)
    meta = {"version": version, "cells": cells, "state_dict": net.state_dict(),
            "radio_map": radio_map, "seed": seed, "episodes": episodes,
            "created_ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    if enc.spec():
        meta["encoder"] = enc.spec()
    meta.update(extra_meta or {})
    torch.save(meta, ckpt_out)
    log(f"checkpoint -> {ckpt_out}")
    log(f"curve      -> {curve_csv}")
    return ckpt_out, curve_csv


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m twin.train_dqn")
    ap.add_argument("--version", required=True, help="checkpoint version string, e.g. v0.1.0")
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing checkpoint for this version")
    ap.add_argument("--episodes", type=int, default=90)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--radio-map", default="placeholder")
    ap.add_argument("--out", type=Path,
                    default=Path(__file__).resolve().parents[2] / "working" / "evidence")
    args = ap.parse_args(argv)
    run_training(args.version, args.episodes, args.seed, args.radio_map, args.out,
                 allow_overwrite=args.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
