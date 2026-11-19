"""Mobility scenarios: who moves where, and why it stresses handover.

Each scenario yields UE initial states + a per-step mover. All randomness
comes from the env's seeded RNG — same seed, same trajectories.

- rush_hour: a stream of UEs commuting along two crossing 'roads' through
  the campus at walking-to-cycling speeds. Stresses sustained serial HOs.
- corner_turner: few UEs that walk a street then turn 90° at a corner —
  the classic sharp-RSRP-break case where slow TTT drops you and fast TTT
  ping-pongs you.
- stationary_clusters: three static crowds (lecture halls). Stresses HO
  *restraint*: shadowing wiggle should NOT cause handovers; ping-pongs here
  are pure controller error.
"""

import math
import random
from dataclasses import dataclass, field

CAMPUS_M = 1000.0


@dataclass
class UE:
    ue_id: str
    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0
    serving: str = ""            # cell_id; env attaches at reset
    ttt_counter: int = 0         # controller scratch (A3 time-to-trigger)
    ho_target: str = ""          # controller scratch
    last_ho_step: int = -10**9   # for ping-pong detection
    prev_serving: str = ""
    history: list = field(default_factory=list)


def _road_ue(rng, ue_id):
    """Spawn on one of two crossing roads, moving along it."""
    speed = rng.uniform(1.4, 8.0)                      # walk .. cycle/shuttle
    if rng.random() < 0.5:                             # horizontal road y=500
        y = 500.0 + rng.uniform(-15, 15)
        direction = 1 if rng.random() < 0.5 else -1
        return UE(ue_id, rng.uniform(0, CAMPUS_M), y, vx=direction * speed, vy=0.0)
    x = 500.0 + rng.uniform(-15, 15)                   # vertical road x=500
    direction = 1 if rng.random() < 0.5 else -1
    return UE(ue_id, x, rng.uniform(0, CAMPUS_M), vx=0.0, vy=direction * speed)


def _bounce(ue):
    """Keep UEs on campus: reflect at the fence."""
    if not 0.0 <= ue.x <= CAMPUS_M:
        ue.vx = -ue.vx
        ue.x = min(max(ue.x, 0.0), CAMPUS_M)
    if not 0.0 <= ue.y <= CAMPUS_M:
        ue.vy = -ue.vy
        ue.y = min(max(ue.y, 0.0), CAMPUS_M)


class Scenario:
    name = "base"
    n_ues = 1
    episode_steps = 300          # 1 step = 1 s

    def spawn(self, rng):
        raise NotImplementedError

    def move(self, ue, step, rng, dt=1.0):
        ue.x += ue.vx * dt
        ue.y += ue.vy * dt
        _bounce(ue)


class RushHour(Scenario):
    name = "rush_hour"
    n_ues = 20

    def spawn(self, rng):
        return [_road_ue(rng, f"ue-{i:02d}") for i in range(self.n_ues)]


class CornerTurner(Scenario):
    name = "corner_turner"
    n_ues = 4

    def spawn(self, rng):
        ues = []
        for i in range(self.n_ues):
            # Walk east along the horizontal road, turn point near the centre.
            speed = rng.uniform(1.4, 3.0)
            ue = UE(f"ue-{i:02d}", rng.uniform(0, 300), 500.0 + rng.uniform(-10, 10),
                    vx=speed, vy=0.0)
            ue.turn_x = rng.uniform(450, 550)   # corner position
            ue.turned = False
            ues.append(ue)
        return ues

    def move(self, ue, step, rng, dt=1.0):
        if not ue.turned and ue.x >= ue.turn_x:
            speed = math.hypot(ue.vx, ue.vy)
            ue.vx, ue.vy = 0.0, speed if rng.random() < 0.5 else -speed
            ue.turned = True
        super().move(ue, step, rng, dt)


class StationaryClusters(Scenario):
    name = "stationary_clusters"
    n_ues = 15

    def spawn(self, rng):
        centres = [(250, 300), (750, 300), (500, 800)]   # three lecture halls
        ues = []
        for i in range(self.n_ues):
            cx, cy = centres[i % len(centres)]
            ues.append(UE(f"ue-{i:02d}",
                          cx + rng.uniform(-30, 30), cy + rng.uniform(-30, 30)))
        return ues

    def move(self, ue, step, rng, dt=1.0):
        pass  # stationary: any handover churn is the controller's fault


SCENARIOS = {s.name: s for s in (RushHour(), CornerTurner(), StationaryClusters())}


def load_scenario(name):
    if "@" in name:
        # "<kind>@<campus>": OSM-path mobility fitted to a registered campus
        from campus.world import campus_scenario
        return campus_scenario(name)
    try:
        return SCENARIOS[name]
    except KeyError:
        raise ValueError(f"unknown scenario: {name} (have: {', '.join(SCENARIOS)})")
