"""TwinSim (twin v2): sub-second handover simulator with 3GPP failure semantics.

Replaces the legacy 1 s / RSRP-threshold env (env.py — kept bit-identical so
the v1.x evidence stays reproducible) for all finals evaluation:

- time step `dt` (default 100 ms; 1 s still reachable) so 3GPP time-to-trigger
  values (40-1280 ms) mean something;
- PHY v2 (phy.py): per-RE RSRP, continuous shadowing, Doppler-correlated
  fading with receive diversity, RS-SINR with interference;
- layer-3 filtering per TS 38.331 §5.5.3.2: F_n = (1-a)F_{n-1} + a*M_n,
  a = 1/2^(k/4), adapted to the step so the filter keeps the time constant
  specified for a 200 ms input period. Controllers see L3 values;
- handover execution: the HO command is delivered one step after the
  decision (preparation latency) on the SOURCE cell — lost if source SINR <
  Q_out -> HO failure ("too late"); then the UE accesses the TARGET — fails
  if target SINR < Q_out -> HO failure. Each successful HO costs
  `ho_interruption_s` of user-plane interruption. Conditional HO (CHO)
  executions skip the command-loss check (command pre-delivered);
- radio-link failure the 3GPP way (TS 38.133 §8.1 / 38.331 §5.3.10):
  serving SINR < Q_out (-8 dB) for N310 consecutive indications starts T310;
  N311 consecutive in-sync (SINR > Q_in, -6 dB) stop it; T310 expiry = RLF.
  RLF/HOF -> RRC re-establishment on the strongest cell after `t_reest_s`;
- MRO taxonomy (TS 38.300 §15.5.2 / 36.300 §22.4.2): too-late, too-early,
  wrong-cell, plus coverage RLFs (re-establish on the same cell). Ping-pong
  per TR 36.839: return to the previous cell after < 1 s time-of-stay;
- throughput proxy: attenuated Shannon (TR 36.942) from SINR x bandwidth;
  zero while re-establishing, reduced by HO interruption. Full-buffer link
  rate (no scheduler sharing) — a proxy, not a system-level throughput.

Mobility and radio do NOT depend on handover decisions, so an episode's
radio is precomputed once as a `RadioTrace` and replayed for every
controller (identical radio for all contenders = paired comparison), and
many controller configurations can run at once as stacked `replicas` of the
same UEs (the A3 sweep evaluates dozens of configs per pass).

Controller batch contract: controller.decide_batch(obs) -> (targets, cond):
targets int (R*N,), -1 = stay; cond bool (R*N,) for CHO executions, or None.
"""

import math
import random
from dataclasses import dataclass, replace

import numpy as np

from .phy import SE_CAP, PhyConfig, PhyModel, shannon_se
from .radio import load_radio_map
from .scenarios import load_scenario

STATIONARY_MPS = 0.5
COUNTERS = ("ho_attempts", "ho_success", "hof_cmd", "hof_target", "rlf", "too_late",
            "too_early", "wrong_cell", "rlf_coverage", "ping_pongs", "short_stays",
            "ho_stationary")


@dataclass(frozen=True)
class SimConfig:
    dt: float = 0.1
    duration_s: float = 300.0
    l3_k: int = 4                    # filterCoefficient (fc4 = 3GPP default)
    l3_ref_period_s: float = 0.2     # input period the filter constant is defined for
    q_out_db: float = -8.0
    q_in_db: float = -6.0
    n310: int = 2                    # consecutive out-of-sync step indications
    n311: int = 1
    t310_s: float = 1.0
    t_reest_s: float = 1.0           # re-establishment outage (cell search + RACH + RRC)
    ho_interruption_s: float = 0.05  # user-plane interruption per successful HO
    pingpong_s: float = 1.0          # TR 36.839 minimum time-of-stay
    short_stay_s: float = 5.0        # the legacy HORUS ping-pong window (reported too)
    mro_window_s: float = 3.0        # "shortly after HO" (> T310 + N310 so it can fire)


def l3_alpha(k, dt, ref=0.2):
    a = 1.0 / 2 ** (np.asarray(k, float) / 4.0)
    return 1.0 - (1.0 - a) ** (dt / ref)


@dataclass
class RadioTrace:
    """Controller-independent episode radio: (T+1, N, C) arrays."""
    l1: np.ndarray            # reported L1 RSRP, dBm
    rx: np.ndarray            # true per-RE received power, mW
    speeds: np.ndarray        # (T+1, N) m/s
    active: np.ndarray        # (C,) bool (cell_outage silences one)
    cell_ids: list
    ue_ids: list
    victim: str = None
    load: float = 0.5
    noise_mw: float = 0.0


def make_trace(scenario, radio_map, seed, phy_cfg, sim_cfg, outage=False):
    sc = load_scenario(scenario)
    rng = random.Random(seed)
    rmap = load_radio_map(radio_map, seed)
    if getattr(rmap, "phy_overrides", None):     # e.g. the measured map's fitted shadowing sigma
        phy_cfg = replace(phy_cfg, **rmap.phy_overrides)
    # maps that span more than the 1 km opencellid frame (campus:<id>) say so
    phy = PhyModel(rmap.cells, seed, phy_cfg, getattr(rmap, "shadow_extent", None))
    cells = rmap.cells
    ues = sc.spawn(rng)
    n_steps = int(round(sim_cfg.duration_s / sim_cfg.dt))
    n, m = len(ues), len(cells)
    l1 = np.empty((n_steps + 1, n, m))
    rx = np.empty((n_steps + 1, n, m))
    sp = np.empty((n_steps + 1, n))

    def kin():
        return (np.array([[u.x, u.y] for u in ues], dtype=float),
                np.array([math.hypot(u.vx, u.vy) for u in ues], dtype=float))

    xy, s = kin()
    victim = None
    if outage:   # coverage hole: silence the cell serving the most UEs at t=0
        mean = phy.mean_rsrp_dbm(xy)
        v = int(np.bincount(mean.argmax(1), minlength=m).argmax())
        phy.silence(v)
        victim = phy.cell_ids[v]
    l1[0], rx[0] = phy.step(xy, s, sim_cfg.dt)
    sp[0] = s
    for i in range(1, n_steps + 1):
        for u in ues:
            sc.move(u, i, rng, sim_cfg.dt)
        xy, s = kin()
        l1[i], rx[i] = phy.step(xy, s, sim_cfg.dt)
        sp[i] = s
    return RadioTrace(l1, rx, sp, phy.active.copy(), phy.cell_ids, [u.ue_id for u in ues],
                      victim, phy_cfg.load, 10.0 ** (phy_cfg.noise_per_re_dbm / 10.0))


def sinr_db(rx, serving, load, noise_mw):
    idx = np.arange(rx.shape[0])
    s = rx[idx, serving]
    return 10.0 * np.log10(np.maximum(s, 1e-30) / (load * (rx.sum(1) - s) + noise_mw))


@dataclass
class Obs:
    t: float
    dt: float
    l1: np.ndarray            # (R*N, C) dBm
    l3: np.ndarray            # (R*N, C) dBm, L3-filtered
    serving: np.ndarray       # (R*N,) int
    sinr_db: np.ndarray       # (R*N,) serving RS-SINR (CQI proxy)
    connected: np.ndarray     # (R*N,) bool
    can_ho: np.ndarray        # (R*N,) bool: connected and no HO in flight
    time_since_ho: np.ndarray # (R*N,) s
    active: np.ndarray        # (C,) bool
    cell_ids: list
    ue_ids: list              # length R*N (replica-suffixed when R > 1)


def summarize(c, n_ues, duration_s, bandwidth_mhz):
    """Aggregate per-UE counter arrays (already sliced to one group) into the
    judge-facing metric dict. Rates are per UE-minute."""
    ue_min = n_ues * duration_s / 60.0
    tot = {k: int(c[k].sum()) for k in COUNTERS}
    fails = tot["rlf"] + tot["hof_cmd"] + tot["hof_target"]
    se = float(c["se"].sum() / c["samples"].sum())
    ue_se = c["se"] / np.maximum(c["samples"], 1)
    stat_min = float(c["stationary_s"].sum()) / 60.0
    att = tot["ho_attempts"]
    return {
        "n_ues": n_ues, "duration_s": duration_s, **tot,
        "hof": tot["hof_cmd"] + tot["hof_target"],
        "ho_success_rate": round(tot["ho_success"] / att, 4) if att else 1.0,
        "ho_rate": round(att / ue_min, 4),
        "pp_rate": round(tot["ping_pongs"] / ue_min, 4),
        "short_stay_rate": round(tot["short_stays"] / ue_min, 4),
        "fail_rate": round(fails / ue_min, 4),
        "rlf_rate": round(tot["rlf"] / ue_min, 4),
        "mro_rate": round((tot["too_late"] + tot["too_early"] + tot["wrong_cell"]) / ue_min, 4),
        "stationary_ho_rate": round(tot["ho_stationary"] / stat_min, 4) if stat_min else None,
        "outage_frac": round(float(c["outage_s"].sum()) / (n_ues * duration_s), 5),
        "mean_se": round(se, 4),
        "mean_thr_mbps": round(se * bandwidth_mhz, 2),
        "p5_thr_mbps": round(float(np.percentile(ue_se, 5)) * bandwidth_mhz, 2),
        "mean_sinr_db": round(float(c["sinr"].sum() / c["samples"].sum()), 3),
        "mean_rsrp_dbm": round(float(c["rsrp"].sum() / c["samples"].sum()), 2),
    }


def utility_per_ue_min(m, c_ho=0.3, c_pp=2.0, c_fail=5.0):
    """The ONE operator objective both sides optimize (pre-registered in
    gate_config_finals.json): 60 * mean_SE / SE_CAP minus event costs, per
    UE-minute. The A3/CHO sweeps maximize it; the DQN reward is its per-step
    form. Weights: an HO is cheap (0.3), a ping-pong costs ~7 HOs, a
    failure (RLF or HOF, i.e. an outage + re-establishment) ~17 HOs."""
    return (60.0 * m["mean_se"] / SE_CAP - c_ho * m["ho_rate"] - c_pp * m["pp_rate"]
            - c_fail * m["fail_rate"])


class TwinSim:
    """Replays a RadioTrace for `replicas` independent copies of the UEs.
    Row r*N + i is UE i in replica r. `l3_k` may be an int or one per replica."""

    def __init__(self, trace, cfg=None, replicas=1, l3_k=None, bandwidth_mhz=None):
        self.tr = trace
        self.cfg = cfg or SimConfig()
        self.R = replicas
        self.N = trace.l1.shape[1]
        self.m = trace.l1.shape[2]
        self.n_steps = trace.l1.shape[0] - 1
        k = self.cfg.l3_k if l3_k is None else l3_k
        k = np.broadcast_to(np.asarray(k, float), (replicas,))
        self.l3_a = np.repeat(l3_alpha(k, self.cfg.dt, self.cfg.l3_ref_period_s), self.N)[:, None]
        self.bandwidth_mhz = bandwidth_mhz or PhyConfig().bandwidth_mhz

    def _rows(self, a):
        return np.tile(a, (self.R, 1)) if a.ndim == 2 else np.tile(a, self.R)

    def reset(self):
        tr, R, N = self.tr, self.R, self.N
        nr = R * N
        self.nr = nr
        self.step_i, self.t = 0, 0.0
        self.l1 = self._rows(tr.l1[0])
        self.rx = self._rows(tr.rx[0])
        self.l3 = self.l1.copy()
        self.serving = np.where(tr.active[None], self.l1, -np.inf).argmax(1)
        self.prev_serving = np.full(nr, -1)
        self.last_ho_t = np.full(nr, -1e9)
        self.last_ho_src = np.full(nr, -1)
        self.reest_until = np.full(nr, -1.0)
        self.reest_cell = np.full(nr, -1)
        self.pend_target = np.full(nr, -1)
        self.pend_cond = np.zeros(nr, dtype=bool)
        self.oos = np.zeros(nr, dtype=int)
        self.ins = np.zeros(nr, dtype=int)
        self.t310 = np.full(nr, -1.0)
        self.c = {k: np.zeros(nr, dtype=np.int64) for k in COUNTERS}
        for k in ("se", "sinr", "rsrp", "outage_s", "stationary_s", "samples"):
            self.c[k] = np.zeros(nr)
        self.sinr = sinr_db(self.rx, self.serving, tr.load, tr.noise_mw)
        self.ue_ids = (tr.ue_ids if R == 1 else
                       [f"{u}#r{r}" for r in range(R) for u in tr.ue_ids])
        return self.observe()

    def connected(self):
        return self.reest_until < self.t

    def observe(self):
        conn = self.connected()
        return Obs(t=self.t, dt=self.cfg.dt, l1=self.l1, l3=self.l3, serving=self.serving.copy(),
                   sinr_db=self.sinr, connected=conn, can_ho=conn & (self.pend_target < 0),
                   time_since_ho=np.minimum(self.t - self.last_ho_t, 1e3),
                   active=self.tr.active, cell_ids=self.tr.cell_ids, ue_ids=self.ue_ids)

    def _fail(self, u, kind, ho_src=-1, ho_tgt=-1):
        """RLF or HOF on row u -> MRO classification + re-establishment."""
        cfg, c = self.cfg, self.c
        r = int(np.where(self.tr.active, self.l1[u], -np.inf).argmax())
        cur = int(self.serving[u])
        if kind == "hof_cmd":
            c["hof_cmd"][u] += 1
            c["too_late"][u] += 1
        elif kind == "hof_target":
            c["hof_target"][u] += 1
            c["too_early" if r in (ho_src, ho_tgt) else "wrong_cell"][u] += 1
        else:
            c["rlf"][u] += 1
            recent = self.t - self.last_ho_t[u] <= cfg.mro_window_s
            if recent and r == self.last_ho_src[u]:
                c["too_early"][u] += 1
            elif recent and r != cur:
                c["wrong_cell"][u] += 1
            elif r != cur:
                c["too_late"][u] += 1
            else:
                c["rlf_coverage"][u] += 1
        self.reest_until[u] = self.t + cfg.t_reest_s
        self.reest_cell[u] = r
        self.pend_target[u] = -1
        self.t310[u] = -1.0
        self.oos[u] = self.ins[u] = 0
        self.prev_serving[u] = -1
        self.last_ho_t[u] = -1e9

    def step(self, controller):
        cfg, c, tr = self.cfg, self.c, self.tr
        nr = self.nr
        self.step_i += 1
        i = self.step_i
        self.t = i * cfg.dt
        self.l1 = self._rows(tr.l1[i])
        self.rx = self._rows(tr.rx[i])
        speeds = self._rows(tr.speeds[i])
        self.l3 = (1.0 - self.l3_a) * self.l3 + self.l3_a * self.l1

        ho_exec = np.zeros(nr, dtype=bool)
        ho_ok = np.zeros(nr, dtype=bool)
        pp = np.zeros(nr, dtype=bool)
        fail = np.zeros(nr, dtype=bool)

        # 1) re-establishment completes
        done_re = (self.reest_cell >= 0) & (self.reest_until < self.t)
        if done_re.any():
            self.serving[done_re] = self.reest_cell[done_re]
            self.reest_cell[done_re] = -1

        # 2) HO executions (decided last step)
        conn = self.connected()
        self.pend_target[~conn] = -1
        ex = np.where(self.pend_target >= 0)[0]
        if len(ex):
            src = self.serving[ex].copy()
            tgt = self.pend_target[ex].copy()
            s_src = sinr_db(self.rx[ex], src, tr.load, tr.noise_mw)
            s_tgt = sinr_db(self.rx[ex], tgt, tr.load, tr.noise_mw)
            for j, u in enumerate(ex):
                ho_exec[u] = True
                c["ho_attempts"][u] += 1
                if speeds[u] < STATIONARY_MPS:
                    c["ho_stationary"][u] += 1
                if not self.pend_cond[u] and s_src[j] < cfg.q_out_db:
                    fail[u] = True
                    self._fail(u, "hof_cmd", src[j], tgt[j])
                    continue
                if s_tgt[j] < cfg.q_out_db:
                    fail[u] = True
                    self._fail(u, "hof_target", src[j], tgt[j])
                    continue
                c["ho_success"][u] += 1
                ho_ok[u] = True
                stay = self.t - self.last_ho_t[u]
                if tgt[j] == self.prev_serving[u]:
                    if stay < cfg.pingpong_s - 1e-9:
                        c["ping_pongs"][u] += 1
                        pp[u] = True
                    if stay < cfg.short_stay_s - 1e-9:
                        c["short_stays"][u] += 1
                self.prev_serving[u] = self.last_ho_src[u] = src[j]
                self.serving[u] = tgt[j]
                self.last_ho_t[u] = self.t
                self.pend_target[u] = -1
                self.t310[u] = -1.0
                self.oos[u] = self.ins[u] = 0

        # 3) radio-link monitoring on the (possibly new) serving cell
        conn = self.connected()
        self.sinr = sinr_db(self.rx, self.serving, tr.load, tr.noise_mw)
        self.oos = np.where(conn & (self.sinr < cfg.q_out_db), self.oos + 1, 0)
        self.ins = np.where(conn & (self.sinr > cfg.q_in_db), self.ins + 1, 0)
        start = conn & (self.t310 < 0) & (self.oos >= cfg.n310)
        running = conn & (self.t310 >= 0)
        stop = running & (self.ins >= cfg.n311)
        self.t310[start] = 0.0
        self.t310[stop] = -1.0
        tick = running & ~stop
        self.t310[tick] += cfg.dt
        for u in np.where(tick & (self.t310 >= cfg.t310_s - 1e-9))[0]:
            fail[u] = True
            self._fail(u, "rlf")

        # 4) accounting
        conn = self.connected()
        se = np.where(conn, shannon_se(self.sinr), 0.0)
        if ho_ok.any():
            se = np.where(ho_ok, se * max(0.0, 1.0 - cfg.ho_interruption_s / cfg.dt), se)
        out = ~conn | (self.sinr < cfg.q_out_db)
        c["se"] += se
        c["sinr"] += np.where(conn, self.sinr, 0.0)
        c["rsrp"] += self.l1[np.arange(nr), self.serving]
        c["outage_s"] += out * cfg.dt
        c["stationary_s"] += (speeds < STATIONARY_MPS) * cfg.dt
        c["samples"] += 1

        # 5) controller decides; the HO executes next step
        obs = self.observe()
        if controller is not None:
            self.apply(obs, *controller.decide_batch(obs))

        done = i >= self.n_steps
        info = {"ho_exec": ho_exec, "ho_ok": ho_ok, "pp": pp, "fail": fail, "se": se,
                "outage": out, "speeds": speeds}
        return obs, info, done

    def apply(self, obs, targets, cond=None):
        """Schedule HO decisions taken on `obs` (executed next step). Invalid
        requests (no HO possible, same cell, silenced target) are ignored."""
        targets = np.asarray(targets)
        if targets.shape != self.serving.shape or not np.issubdtype(targets.dtype, np.integer):
            raise ValueError("controller targets must be an integer per UE")
        if cond is not None and np.asarray(cond).shape != targets.shape:
            raise ValueError("conditional flags must match target shape")
        # out-of-range targets are ignored like any other invalid request (measured-route port);
        # for in-range targets this is identical to the previous rule
        ok = obs.can_ho & (targets >= 0) & (targets < self.m) & (targets != self.serving)
        if ok.any():
            ok &= self.tr.active[np.clip(targets, 0, self.m - 1)]
            self.pend_target[ok] = targets[ok]
            self.pend_cond[ok] = cond[ok] if cond is not None else False

    def metrics(self, replica=0):
        sl = slice(replica * self.N, (replica + 1) * self.N)
        return summarize({k: v[sl] for k, v in self.c.items()}, self.N,
                         self.n_steps * self.cfg.dt, self.bandwidth_mhz)


def run_on_trace(controller, trace, cfg=None, replicas=1, l3_k=None, bandwidth_mhz=None):
    """Run one controller (possibly a replica-batched one) over a trace.
    The L3 filter uses the controller's own l3_k (a network-configured RRC
    parameter, hence part of each policy's config). Returns [metrics]*replicas."""
    k = l3_k if l3_k is not None else getattr(controller, "l3_k", None)
    env = TwinSim(trace, cfg, replicas=replicas, l3_k=k, bandwidth_mhz=bandwidth_mhz)
    env.reset()
    if hasattr(controller, "reset"):
        controller.reset()
    done = False
    while not done:
        _, _, done = env.step(controller)
    return [env.metrics(r) for r in range(replicas)]


def run_sim_episode(controller, scenario, seed, radio_map="opencellid", fading="off",
                    cfg=None, phy=None, outage=False):
    cfg = cfg or SimConfig()
    phy = phy or PhyConfig(fading=fading)
    trace = make_trace(scenario, radio_map, seed, phy, cfg, outage)
    return run_on_trace(controller, trace, cfg)[0]
