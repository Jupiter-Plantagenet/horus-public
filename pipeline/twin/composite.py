"""Run several DIFFERENT controllers in one sim pass (one replica each).

Twin-v2 rows are independent (ue_grid.py), so replica r driven by controller
r gives exactly the episode that controller would get alone — but the sim's
per-step Python overhead is paid once instead of once per arm. Each
controller receives an Obs sliced to its own rows, and the sim applies each
controller's own L3 filterCoefficient to its replica (TwinSim l3_k list).
tests/test_v3.py checks equality with separate runs.
"""

from dataclasses import replace

import numpy as np

from .sim import SimConfig, TwinSim


class MultiArm:
    def __init__(self, controllers, n_ues):
        self.ctls = list(controllers)
        self.n = n_ues
        self.l3_k = [getattr(c, "l3_k", 4) if getattr(c, "l3_k", None) is not None else 4
                     for c in self.ctls]

    def reset(self):
        for c in self.ctls:
            if hasattr(c, "reset"):
                c.reset()

    def decide_batch(self, obs):
        n = self.n
        R = len(self.ctls)
        targets = np.full(R * n, -1)
        cond = np.zeros(R * n, dtype=bool)
        for r, c in enumerate(self.ctls):
            sl = slice(r * n, (r + 1) * n)
            o = replace(obs, l1=obs.l1[sl], l3=obs.l3[sl], serving=obs.serving[sl],
                        sinr_db=obs.sinr_db[sl], connected=obs.connected[sl],
                        can_ho=obs.can_ho[sl], time_since_ho=obs.time_since_ho[sl],
                        ue_ids=obs.ue_ids[sl])
            t, cd = c.decide_batch(o)
            targets[sl] = t
            if cd is not None:
                cond[sl] = cd
        return targets, cond


def run_arms(trace, controllers, cfg=None):
    """-> list of sim metric dicts, one per controller (same order)."""
    n = trace.l1.shape[1]
    m = MultiArm(controllers, n)
    env = TwinSim(trace, cfg or SimConfig(), replicas=len(controllers), l3_k=m.l3_k)
    env.reset()
    m.reset()
    done = False
    while not done:
        _, _, done = env.step(m)
    return [env.metrics(r) for r in range(len(controllers))]
