"""Per-UE counterfactual grids (finals v3).

In twin v2 the UEs of an episode do not interact: interference uses a fixed
interferer activity factor (PhyConfig.load), there is no scheduler sharing and
no admission control, and the radio trace is precomputed independently of any
handover decision. So an episode's operator utility is exactly the MEAN over
UEs of a per-UE utility (every UE contributes the same number of samples),
and the counterfactual "what would THIS UE have got under config X" is
available for every config at once by running the config grid as sim
replicas over the same trace.

That gives two things the v2 attempt did not have:
  - a per-UE hindsight bound: how much a per-situation selector could gain
    over the per-cell oracle config (which picks ONE config for everyone in
    the cell);
  - full-information training labels for a contextual selector: for every
    (UE, episode) the utility of every profile is known, so the learner is a
    cost-sensitive classifier/regressor, not an exploration-starved RL agent.

Functions
    per_ue(env)                    -> dict of (R, N) per-UE metric arrays
    run_grid(trace, family, cfgs)  -> per_ue() of a replica-batched grid run
"""

import numpy as np

from .phy import SE_CAP
from .sim import SimConfig, TwinSim

C_HO, C_PP, C_FAIL = 0.3, 2.0, 5.0      # sim.utility_per_ue_min weights


def per_ue(env):
    """Per-(replica, UE) metrics from a finished TwinSim. Returns (R, N) arrays:
    utility (per UE-minute, same formula as sim.utility_per_ue_min), se,
    ho, pp, fail counts and rates. mean over axis 1 of 'utility' equals the
    episode utility of that replica (to float rounding of the rounded
    summary)."""
    R, N = env.R, env.N
    c = env.c
    dur_min = env.n_steps * env.cfg.dt / 60.0
    rs = lambda k: np.asarray(c[k], float).reshape(R, N)
    se = rs("se") / np.maximum(rs("samples"), 1)
    ho = rs("ho_attempts")
    pp = rs("ping_pongs")
    fail = rs("rlf") + rs("hof_cmd") + rs("hof_target")
    util = 60.0 * se / SE_CAP - C_HO * ho / dur_min - C_PP * pp / dur_min - C_FAIL * fail / dur_min
    return {"utility": util, "se": se, "ho": ho, "pp": pp, "fail": fail,
            "ho_rate": ho / dur_min, "pp_rate": pp / dur_min, "fail_rate": fail / dur_min,
            "rlf": rs("rlf"), "outage_s": rs("outage_s")}


def run_grid(trace, family, configs, cfg=None):
    """Run `configs` (list of dicts, see sweep.A3_GRID / CHO_GRID) of one
    family ("a3" | "cho") as replicas over `trace`; return per_ue(env)."""
    from .controllers_v2 import A3Batch, CHOBatch
    cls = {"a3": A3Batch, "cho": CHOBatch}[family]
    n = trace.l1.shape[1]
    ctl = cls.grid(configs, n)
    env = TwinSim(trace, cfg or SimConfig(), replicas=len(configs), l3_k=ctl.l3_k)
    env.reset()
    ctl.reset()
    done = False
    while not done:
        _, _, done = env.step(ctl)
    return per_ue(env)


def run_controller(trace, controller, cfg=None):
    """One (non-grid) controller over `trace`; per_ue() with R=1."""
    env = TwinSim(trace, cfg or SimConfig(), replicas=1,
                  l3_k=getattr(controller, "l3_k", None))
    env.reset()
    if hasattr(controller, "reset"):
        controller.reset()
    done = False
    while not done:
        _, _, done = env.step(controller)
    return per_ue(env), env
