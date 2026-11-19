"""Shared constants for the finals evaluation (twin v2).

Seed ranges are disjoint by construction — identical seeds are identical
episodes, so tuning/training/gating/evaluating on overlapping seeds would be
grading on the training set:

    v2 DQN training (central)     0 .. 499
    A3/CHO baseline sweep       500 .. 599
    federated client rounds     600 .. 999
    gate (finals-v3 suite)     1100 .. 1199
    final evaluation           2000 .. 2999

v3 (finals_preregistration_v3.json): counterfactual training data 0..399,
v3 sweep 500..504, federation client blocks 620-699 / 720-799 / 820-899,
v3 tuning / model selection 1000..1099, gate 1100..1102, held-out 2100..2119.
"""

import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
EVIDENCE = REPO / "working" / "evidence"
BASELINES_JSON = REPO / "pipeline" / "finals_baselines.json"

RADIO_MAP = "opencellid"
SCENARIOS = ("rush_hour", "corner_turner", "stationary_clusters", "cell_outage")
FADINGS = ("off", "rician", "rayleigh")
SWEEP_SEEDS = tuple(range(500, 505))
EVAL_SEED0 = 2000


def cell_args(scenario):
    """cell_outage = rush_hour with the busiest site silenced at t=0."""
    return ("rush_hour", True) if scenario == "cell_outage" else (scenario, False)


def trace_for(scenario, fading, seed, phy_overrides=None, cfg=None):
    from dataclasses import replace
    from .phy import PhyConfig
    from .sim import SimConfig, make_trace
    cfg = cfg or SimConfig()
    phy = replace(PhyConfig(fading=fading), **(phy_overrides or {}))
    sc, outage = cell_args(scenario)
    return make_trace(sc, RADIO_MAP, seed, phy, cfg, outage)


def single_thread():
    """One BLAS/OpenMP thread per process. On this shared 4-core box torch's
    default 2 intra-op threads spin-wait against the other workers and a
    (20, 8, 64) LSTM call took 0.4 s instead of ~1 ms."""
    for k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ.setdefault(k, "1")
    try:
        import torch
        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)
    except (ImportError, RuntimeError):
        pass
