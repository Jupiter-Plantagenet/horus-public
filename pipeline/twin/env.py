"""TwinEnv: the Gym-style campus (reset/step) + episode metrics.

One step = one second: move every UE, take a measurement report per UE,
let the controller decide, execute handovers, and account the metrics the
whole project optimizes:

- handover success rate — an executed HO *fails* if the target is too weak
  to complete signalling (rsrp < HO_FAIL_RSRP_DBM) at execution time; the
  UE then suffers radio-link failure and re-attaches to the strongest cell.
- ping-pong count — HO back to the cell you left within PING_PONG_WINDOW_S.
  The classic A3 pathology the DQN (#8) is supposed to fix.
- mean serving RSRP — coverage quality actually delivered.

Determinism: everything random flows from one seeded RNG (mobility) plus
the seed-keyed shadowing in RadioMap. Same seed -> identical episode.
"""

from dataclasses import dataclass, field

from .controllers import load_controller
from .radio import load_radio_map
from .scenarios import load_scenario

HO_FAIL_RSRP_DBM = -105.0     # target weaker than this at execution -> HO failure (RLF)
PING_PONG_WINDOW_S = 5


@dataclass
class EpisodeMetrics:
    handovers_attempted: int = 0
    handovers_ok: int = 0
    handovers_failed: int = 0
    ping_pongs: int = 0
    rsrp_sum: float = 0.0
    rsrp_n: int = 0

    @property
    def ho_success_rate(self):
        return self.handovers_ok / self.handovers_attempted if self.handovers_attempted else 1.0

    @property
    def mean_rsrp_dbm(self):
        return self.rsrp_sum / self.rsrp_n if self.rsrp_n else float("nan")

    def as_dict(self):
        return {
            "handovers_attempted": self.handovers_attempted,
            "handovers_ok": self.handovers_ok,
            "handovers_failed": self.handovers_failed,
            "ho_success_rate": round(self.ho_success_rate, 4),
            "ping_pongs": self.ping_pongs,
            "mean_rsrp_dbm": round(self.mean_rsrp_dbm, 2),
        }


class TwinEnv:
    def __init__(self, scenario="rush_hour", radio_map="placeholder", seed=0, fading="off"):
        import random
        self.scenario = load_scenario(scenario)
        self.map_name = radio_map
        self.fading = fading
        self.seed = seed
        self.rng = random.Random(seed)
        self.radio = load_radio_map(radio_map, seed, fading)
        self.ues = []
        self.step_i = 0
        self.metrics = EpisodeMetrics()

    def reset(self):
        import random
        self.rng = random.Random(self.seed)
        self.radio = load_radio_map(self.map_name, self.seed, self.fading)
        self.ues = self.scenario.spawn(self.rng)
        self.step_i = 0
        self.metrics = EpisodeMetrics()
        for ue in self.ues:  # initial attach: strongest cell, as a real UE would
            rsrp = self.radio.measure(ue.x, ue.y, self.step_i)
            ue.serving = max(rsrp, key=rsrp.get)
        return self._observations()

    def _observations(self):
        return {ue.ue_id: self.radio.measure(ue.x, ue.y, self.step_i) for ue in self.ues}

    def _execute_ho(self, ue, target, rsrp):
        m = self.metrics
        m.handovers_attempted += 1
        if rsrp[target] < HO_FAIL_RSRP_DBM:
            m.handovers_failed += 1                       # RLF: re-attach to strongest
            ue.prev_serving, ue.serving = ue.serving, max(rsrp, key=rsrp.get)
            ue.last_ho_step = self.step_i
            return
        m.handovers_ok += 1
        if (target == ue.prev_serving
                and self.step_i - ue.last_ho_step <= PING_PONG_WINDOW_S):
            m.ping_pongs += 1
        ue.prev_serving, ue.serving = ue.serving, target
        ue.last_ho_step = self.step_i

    def step(self, controller):
        """Advance one second. Returns (observations, done)."""
        self.step_i += 1
        for ue in self.ues:
            self.scenario.move(ue, self.step_i, self.rng)
        obs = self._observations()
        for ue in self.ues:
            rsrp = obs[ue.ue_id]
            target = controller.decide(ue, rsrp, self.step_i)
            if target is not None and target != ue.serving:
                self._execute_ho(ue, target, rsrp)
            self.metrics.rsrp_sum += rsrp[ue.serving]
            self.metrics.rsrp_n += 1
        return obs, self.step_i >= self.scenario.episode_steps


def run_episode(scenario, controller_name, radio_map, seed, fading="off"):
    env = TwinEnv(scenario=scenario, radio_map=radio_map, seed=seed, fading=fading)
    controller = load_controller(controller_name)
    env.reset()
    done = False
    while not done:
        _, done = env.step(controller)
    return env.metrics.as_dict()
