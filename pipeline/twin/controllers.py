"""Handover controllers.

v0 ships the A3 baseline (#3): the 3GPP event the industry actually runs —
hand over when a neighbour is `hysteresis_db` better than serving and stays
better for `ttt_steps` consecutive measurements (time-to-trigger). This is
the bar the DQN (#8) must beat; its parameters are the classic knobs whose
one-size-fits-all nature is HORUS's whole argument.

Controller contract (what #8 plugs into): decide(ue, rsrp_by_cell, step)
-> target cell_id to hand over to, or None to stay. The env executes.
"""


class A3Controller:
    name = "a3"

    def __init__(self, hysteresis_db=3.0, ttt_steps=3):
        self.hysteresis_db = hysteresis_db
        self.ttt_steps = ttt_steps

    def reset(self):
        """Controller contract: called between episodes. A3 keeps its scratch
        on the UE objects (recreated by env.reset), so nothing to do."""

    def decide(self, ue, rsrp, step):
        serving_rsrp = rsrp[ue.serving]
        best = max(rsrp, key=rsrp.get)
        if best == ue.serving or rsrp[best] <= serving_rsrp + self.hysteresis_db:
            ue.ttt_counter, ue.ho_target = 0, ""      # A3 condition not met: reset TTT
            return None
        if ue.ho_target != best:                      # condition met for a NEW best cell
            ue.ho_target, ue.ttt_counter = best, 1
            return None
        ue.ttt_counter += 1                           # same candidate, TTT running
        if ue.ttt_counter >= self.ttt_steps:
            ue.ttt_counter, ue.ho_target = 0, ""
            return best
        return None


def load_controller(name):
    if name == "a3":
        return A3Controller()
    if name.startswith("dqn"):
        from .dqn import load_dqn        # lazy: needs torch (the ML venv), a3 does not
        version = name.split(":", 1)[1] if ":" in name else "v0.1.0"
        return load_dqn(version)
    raise ValueError(f"unknown controller: {name} (have: a3, dqn[:version])")
