"""HORUS v3 building blocks: a per-UE CHO profile engine, online situation
features, and the deployable adaptive classical baselines.

ProfileCHO
    Conditional handover (same semantics as controllers_v2.CHOBatch) whose
    parameters — preparation offset, execution offset, hysteresis, TTT AND the
    L3 filterCoefficient k — are set PER UE ROW and may be switched at any
    time. Every parameter is a standard RRC field (CondReconfig execution
    condition = condEventA3 a3-Offset/hysteresis/timeToTrigger, measConfig
    filterCoefficient), so whatever selects the profile, every handover is a
    3GPP CHO execution. The L3 filter is applied here, from the L1 reports in
    the observation, with each row's own k (the sim's own L3 values are only
    used to initialise the filter; with a common k the result is identical to
    CHOBatch — see tests/test_v3.py).

SituationFeatures
    Per-UE features from measurement reports only (L1 RSRP of all cells, the
    serving RS-SINR / CQI proxy, serving-cell changes) — what a near-RT RIC
    can compute from KPM/measurement-report history. No speed, scenario or
    fading label from the sim is read.

CHOSpeedScaled  (deployable classical baseline)
    3GPP mobility-state scaling (TS 38.331 / 36.331 speedStatePars:
    t-Evaluation, n-CellChangeMedium/High, timeToTrigger-SF sf-Medium/High)
    applied to a CHO base config: the UE's mobility state is set from the
    number of cell changes in the last t-Evaluation seconds and its TTT is
    scaled by sf. Parameters tuned network-wide on sweep seeds.

CHOMRO  (deployable classical baseline)
    MRO-style online tuning (TS 38.300 §15.5.2): per serving cell, the
    execution offset is nudged up after observed too-early/ping-pong events
    and down after too-late/RLF events, within bounds, every `period_s`.
"""

from dataclasses import replace

import numpy as np

from .controllers_v2 import CHOBatch
from .sim import l3_alpha

PROFILE_KEYS = ("prep_offset_db", "exec_offset_db", "hys_db", "ttt_s", "l3_k")


def profile_spec(p):
    return (f"cho:prep={p['prep_offset_db']:g},off={p['exec_offset_db']:g},hys={p['hys_db']:g},"
            f"ttt={p['ttt_s']:g},k={int(p['l3_k'])}")


def parse_profile(spec):
    kind, _, rest = spec.partition(":")
    if kind != "cho":
        raise ValueError(spec)
    kv = dict(x.split("=", 1) for x in rest.split(","))
    return {"prep_offset_db": float(kv.get("prep", -6)), "exec_offset_db": float(kv["off"]),
            "hys_db": float(kv["hys"]), "ttt_s": float(kv["ttt"]), "l3_k": int(kv["k"])}


class ProfileCHO:
    """Per-row switchable CHO with per-row L3 filtering. `profiles` is a list
    of dicts (PROFILE_KEYS); set(idx) assigns profile idx[i] to row i."""

    def __init__(self, profiles, default=0, dt=0.1):
        self.profiles = [dict(p) for p in profiles]
        self.table = np.array([[p[k] for k in PROFILE_KEYS] for p in self.profiles], float)
        self.default = default
        self.dt = dt
        self.l3_k = 4             # the sim's own filter (only used to initialise ours)
        self.reset()

    def reset(self):
        self.current = None
        self.cho = None
        self.l3 = None
        self._alpha = None

    def _init(self, obs):
        n = len(obs.serving)
        self.current = np.full(n, self.default)
        self.l3 = obs.l3.copy()
        self.cho = CHOBatch(*self._cols()[:4], l3_k=None, name="cho-profile")
        self._apply()

    def _cols(self):
        t = self.table[self.current]
        return tuple(t[:, j:j + 1].copy() for j in range(5))

    def _apply(self):
        prep, off, hys, ttt, k = self._cols()
        self.cho.prep_offset_db = prep
        self.cho.a3.offset_db, self.cho.a3.hys_db, self.cho.a3.ttt_s = off, hys, ttt
        self._alpha = l3_alpha(k, self.dt)

    def set(self, idx, obs=None):
        if self.current is None:
            if obs is None:
                raise RuntimeError("set() before the first observation needs obs")
            self._init(obs)
        idx = np.asarray(idx, int)
        if not np.array_equal(idx, self.current):
            self.current = idx.copy()
            self._apply()

    def step(self, obs):
        if self.current is None:
            self._init(obs)
        else:
            self.l3 = (1.0 - self._alpha) * self.l3 + self._alpha * obs.l1
        return self.cho.decide_batch(replace(obs, l3=self.l3))

    # sim contract when used directly with a fixed assignment
    def decide_batch(self, obs):
        return self.step(obs)


# --------------------------------------------------------------------- features
FEATURE_NAMES = (
    "mob5", "mob10", "mob20",          # |EMA_slow(t) - EMA_slow(t-lag)| on the 4 strongest cells, dB/5
    "fad_depth",                       # EMA |L1 - EMA_slow| on the 4 strongest cells, dB/5
    "fad_rate",                        # EMA |L1(t) - L1(t-100 ms)| strongest 4, dB/2 (Doppler proxy)
    "sinr", "sinr_sd",                 # serving RS-SINR EMA (dB+10)/40 and its deviation /10
    "gap1",                            # best neighbour - serving (L3 fc4), dB/10 clipped
    "n3", "n6",                        # neighbours within 3 / 6 dB of serving (/4)
    "ho30",                            # cell changes in the last 30 s (/6)
    "tsho",                            # time since last cell change (/30, capped)
    "warm",                            # min(1, t / 20 s)
    "net_fad_depth", "net_fad_rate", "net_mob20",   # the same, averaged over all UEs in view
)
N_FEATURES = len(FEATURE_NAMES)
# v3.14 'trend' feature set: the 16 above, unchanged and in the same order, plus short-term
# trends on the fast (1 s) L1 EMA - what a corner turn or a sudden shadowing edge looks like
# before the slow mobility features move
TREND_FEATURES = (
    "gap_tr2", "gap_tr5",              # change of (best neighbour - serving) over 2 s / 5 s, dB/5
    "srv_tr2", "srv_tr5",              # change of the serving cell's level over 2 s / 5 s, dB/5
    "sinr_tr2",                        # change of the serving SINR EMA over 2 s, dB/10
    "ho10",                            # cell changes in the last 10 s (/3)
)
FEATURE_NAMES_TREND = FEATURE_NAMES + TREND_FEATURES
FEATURE_SETS = {"v3": FEATURE_NAMES, "trend": FEATURE_NAMES_TREND}


def feature_set_of(names):
    for k, v in FEATURE_SETS.items():
        if list(names) == list(v):
            return k
    raise ValueError(f"unknown feature set {list(names)!r}")


class SituationFeatures:
    """Online per-UE situation estimate, updated every sim step (100 ms) from
    L1 reports; `vector()` returns the (N, N_FEATURES) float32 matrix."""

    TAU_SLOW, TAU_FAST, TAU_STAT = 10.0, 1.0, 5.0
    LAGS = (5, 10, 20)

    def __init__(self, dt=0.1, feature_set="v3"):
        if feature_set not in FEATURE_SETS:
            raise ValueError(f"unknown feature set {feature_set!r}")
        self.dt = dt
        self.feature_set = feature_set
        self.a_slow = 1 - np.exp(-dt / self.TAU_SLOW)
        self.a_fast = 1 - np.exp(-dt / self.TAU_FAST)
        self.a_stat = 1 - np.exp(-dt / self.TAU_STAT)
        self.reset()

    def reset(self):
        self.n_up = 0
        self.slow = None

    def update(self, obs):
        l1 = obs.l1
        n = l1.shape[0]
        if self.slow is None or self.slow.shape != l1.shape:
            self.slow = l1.copy()
            self.fast = l1.copy()
            self.prev_l1 = l1.copy()
            self.depth = np.zeros(n)
            self.rate = np.zeros(n)
            self.sinr = obs.sinr_db.copy()
            self.sinr_var = np.zeros(n)
            self.hist = []                 # EMA_slow snapshots once per second
            self.fhist = []                # (EMA_fast, SINR EMA) snapshots once per second (trend set)
            self.ho_times = [[] for _ in range(n)]
            self.serving = obs.serving.copy()
            self.last_change = np.full(n, 0.0)
            self.t0 = obs.t
        self.n_up += 1
        self.slow += self.a_slow * (l1 - self.slow)
        self.fast += self.a_fast * (l1 - self.fast)
        top = np.argsort(-self.slow, axis=1)[:, :4]
        rows = np.arange(n)[:, None]
        dev = np.abs(l1[rows, top] - self.slow[rows, top]).mean(1)
        step = np.abs(l1[rows, top] - self.prev_l1[rows, top]).mean(1)
        self.depth += self.a_stat * (dev - self.depth)
        self.rate += self.a_stat * (step - self.rate)
        self.prev_l1 = l1.copy()
        s = np.where(obs.connected, obs.sinr_db, self.sinr)
        self.sinr += self.a_fast * (s - self.sinr)
        self.sinr_var += self.a_stat * ((s - self.sinr) ** 2 - self.sinr_var)
        if self.n_up % int(round(1.0 / self.dt)) == 1 or self.dt >= 1.0:
            self.hist.append(self.slow.copy())
            if len(self.hist) > max(self.LAGS) + 1:
                self.hist.pop(0)
            if self.feature_set == "trend":
                self.fhist.append((self.fast.copy(), self.sinr.copy()))
                if len(self.fhist) > 6:
                    self.fhist.pop(0)
        ch = np.where(obs.serving != self.serving)[0]
        for u in ch:
            self.ho_times[u].append(obs.t)
            self.last_change[u] = obs.t
        self.serving = obs.serving.copy()
        self._obs = obs

    def vector(self):
        obs = self._obs
        n = obs.l1.shape[0]
        rows = np.arange(n)[:, None]
        top = np.argsort(-self.slow, axis=1)[:, :4]
        mobs = []
        for lag in self.LAGS:
            past = self.hist[max(0, len(self.hist) - 1 - lag)]
            mobs.append(np.abs(self.slow[rows, top] - past[rows, top]).mean(1) / 5.0)
        f = self.fast
        idx = np.arange(n)
        sv = f[idx, obs.serving]
        nb = np.where(obs.active[None], f, -np.inf)
        nb[idx, obs.serving] = -np.inf
        gap = nb.max(1) - sv
        n3 = (nb > sv[:, None] - 3.0).sum(1)
        n6 = (nb > sv[:, None] - 6.0).sum(1)
        t = obs.t
        ho30 = np.array([sum(1 for x in h if t - x <= 30.0) for h in self.ho_times], float)
        tsho = np.minimum(t - self.last_change, 30.0) / 30.0
        warm = np.full(n, min(1.0, (t - self.t0) / 20.0))
        depth, rate = self.depth / 5.0, self.rate / 2.0
        cols = [*mobs, depth, rate,
                np.clip((self.sinr + 10.0) / 40.0, 0, 1.5), np.sqrt(self.sinr_var) / 10.0,
                np.clip(gap / 10.0, -2, 2), n3 / 4.0, n6 / 4.0, ho30 / 6.0, tsho, warm,
                np.full(n, depth.mean()), np.full(n, rate.mean()), np.full(n, mobs[2].mean())]
        if self.feature_set == "trend":
            bn = np.argmax(nb, 1)
            for_lag = lambda lag: self.fhist[max(0, len(self.fhist) - 1 - lag)]
            tr = {}
            for lag in (2, 5):
                pf, ps = for_lag(lag)
                tr[lag] = ((gap - (pf[idx, bn] - pf[idx, obs.serving])) / 5.0,
                           (sv - pf[idx, obs.serving]) / 5.0, (self.sinr - ps) / 10.0)
            ho10 = np.array([sum(1 for x in h if t - x <= 10.0) for h in self.ho_times], float)
            cols += [tr[2][0], tr[5][0], tr[2][1], tr[5][1], tr[2][2], ho10 / 3.0]
        return np.clip(np.stack(cols, 1), -3, 3).astype(np.float32)


# --------------------------------------------------------------------- classical adaptive baselines
class CHOSpeedScaled:
    """CHO + 3GPP mobility-state TTT/offset scaling. Mobility state from the
    number of serving-cell changes in the last `t_eval_s`: >= n_high -> high,
    >= n_med -> medium, else normal. TTT is multiplied by sf_med/sf_high and
    (speed-dependent CIO, a common deployment extension) the execution offset
    is reduced by off_med/off_high dB; UEs that have not changed cell for a
    whole t_eval get +stat_off_db (static-UE restraint).

    `grid(base, param_list, n_ues)` evaluates several parameter sets at once
    over sim replicas (row r*n_ues + i uses param set r)."""

    FIELDS = ("t_eval_s", "n_med", "n_high", "sf_med", "sf_high", "off_med", "off_high",
              "stat_off_db")

    def __init__(self, base, t_eval_s=60.0, n_med=2, n_high=4, sf_med=0.5, sf_high=0.25,
                 off_med=0.0, off_high=0.0, stat_off_db=0.0, name=None, _grid=None):
        self.base = dict(base)
        params = _grid or [dict(t_eval_s=t_eval_s, n_med=n_med, n_high=n_high, sf_med=sf_med,
                                sf_high=sf_high, off_med=off_med, off_high=off_high,
                                stat_off_db=stat_off_db)]
        self.params = params
        self.n_ues = None if _grid is None else _grid[0]["_n"]
        self.l3_k = 4
        p0 = params[0]
        self.name = name or (f"cho-mse(teval={p0['t_eval_s']},n={p0['n_med']}/{p0['n_high']},"
                             f"sf={p0['sf_med']}/{p0['sf_high']},doff={p0['off_med']}/"
                             f"{p0['off_high']},stat=+{p0['stat_off_db']})")
        profs = []
        for p in params:
            sf = (1.0, p["sf_med"], p["sf_high"])
            doff = (0.0, p["off_med"], p["off_high"])
            for st in range(3):
                q = dict(self.base)
                q["ttt_s"] = self.base["ttt_s"] * sf[st]
                q["exec_offset_db"] = self.base["exec_offset_db"] - doff[st]
                profs.append(q)
            q = dict(self.base)
            q["exec_offset_db"] = self.base["exec_offset_db"] + p["stat_off_db"]
            profs.append(q)
        self.engine = ProfileCHO(profs, default=0)
        self.reset()

    @classmethod
    def grid(cls, base, param_list, n_ues):
        return cls(base, _grid=[dict(p, _n=n_ues) for p in param_list], name="cho-mse-grid")

    def reset(self):
        self.engine.reset()
        self._serving = None

    def decide_batch(self, obs):
        n = len(obs.serving)
        if self._serving is None:
            self._serving = obs.serving.copy()
            self._times = [[] for _ in range(n)]
            self._t0 = obs.t
            per = self.n_ues or n
            r = np.arange(n) // per
            self._p = {k: np.array([self.params[i][k] for i in r], float) for k in self.FIELDS}
            self._base_idx = 4 * r
        for u in np.where(obs.serving != self._serving)[0]:
            self._times[u].append(obs.t)
        self._serving = obs.serving.copy()
        p = self._p
        cnt = np.array([sum(1 for x in h if obs.t - x <= te)
                        for h, te in zip(self._times, p["t_eval_s"])])
        state = np.where(cnt >= p["n_high"], 2, np.where(cnt >= p["n_med"], 1, 0))
        settled = (p["stat_off_db"] != 0) & (cnt == 0) & (obs.t - self._t0 >= p["t_eval_s"])
        state = np.where(settled, 3, state)
        self.engine.set(self._base_idx + state, obs)
        return self.engine.step(obs)


class CHOMRO:
    """CHO + MRO-style online per-serving-cell offset adaptation from events
    the RAN observes: short stays (return to the previous cell within
    `short_s`) and re-establishments soon after an HO count as too-early;
    re-establishments without a recent HO count as too-late. Every period the
    cell's offset moves by +step (too-early dominates) or -step (too-late
    dominates), clipped to [lo, hi]. With `ho_budget` > 0 the cell also raises
    its offset when its HO rate (per UE-minute served) exceeds the budget and
    lowers it when the rate is below half of it (signalling-aware MRO).
    `grid(base, param_list, n_ues)` runs several parameter sets over replicas."""

    FIELDS = ("step_db", "period_s", "lo", "hi", "short_s", "ho_budget")

    def __init__(self, base, step_db=0.5, period_s=10.0, lo=-1.0, hi=8.0, short_s=5.0,
                 ho_budget=0.0, name=None, _grid=None):
        self.base = dict(base)
        self.params = _grid or [dict(step_db=step_db, period_s=period_s, lo=lo, hi=hi,
                                     short_s=short_s, ho_budget=ho_budget)]
        self.n_ues = None if _grid is None else _grid[0]["_n"]
        self.l3_k = 4
        p0 = self.params[0]
        self.name = name or (f"cho-mro(step={p0['step_db']},period={p0['period_s']},"
                             f"budget={p0['ho_budget']})")
        self.reset()

    @classmethod
    def grid(cls, base, param_list, n_ues):
        return cls(base, _grid=[dict(p, _n=n_ues) for p in param_list], name="cho-mro-grid")

    def reset(self):
        self.off = None

    def decide_batch(self, obs):
        n, m = obs.l1.shape
        if self.off is None:
            per = self.n_ues or n
            self.R = n // per
            self.rep = np.arange(n) // per
            P = {k: np.array([p[k] for p in self.params], float) for k in self.FIELDS}
            self.P = P
            self.off = np.full((self.R, m), float(self.base["exec_offset_db"]))
            self.early = np.zeros((self.R, m))
            self.late = np.zeros((self.R, m))
            self.hos = np.zeros((self.R, m))
            self.served = np.zeros((self.R, m))
            self._serving = obs.serving.copy()
            self._prev = np.full(n, -1)
            self._t_change = np.full(n, -1e9)
            self._conn = obs.connected.copy()
            self._next = obs.t + P["period_s"]
            self.engine = ProfileCHO([self.base], default=0)
            self.engine.set(np.zeros(n, int), obs)
            self._sync(obs)
        lost = self._conn & ~obs.connected
        for u in np.where(lost)[0]:
            r, src = self.rep[u], self._prev[u]
            if obs.t - self._t_change[u] < 3.0 and src >= 0:
                self.early[r, src] += 1
            else:
                self.late[r, self._serving[u]] += 1
        changed = (obs.serving != self._serving) & obs.connected & self._conn
        for u in np.where(changed)[0]:
            r = self.rep[u]
            self.hos[r, self._serving[u]] += 1
            if obs.serving[u] == self._prev[u] and obs.t - self._t_change[u] < self.P["short_s"][r]:
                self.early[r, self._serving[u]] += 1
            self._prev[u] = self._serving[u]
            self._t_change[u] = obs.t
        np.add.at(self.served, (self.rep, obs.serving), obs.dt / 60.0)
        moved = obs.serving != self._serving
        self._serving = obs.serving.copy()
        self._conn = obs.connected.copy()
        due = obs.t + 1e-9 >= self._next
        if due.any():
            P = self.P
            for r in np.where(due)[0]:
                self._next[r] = obs.t + P["period_s"][r]
                up = self.early[r] > self.late[r]
                down = self.late[r] > self.early[r]
                if P["ho_budget"][r] > 0:
                    rate = self.hos[r] / np.maximum(self.served[r], 1e-9)
                    busy = self.served[r] > 0.05
                    up = up | (busy & (rate > P["ho_budget"][r]) & ~down)
                    down = down | (busy & (rate < 0.5 * P["ho_budget"][r]) & ~up)
                st = P["step_db"][r]
                self.off[r] = np.clip(self.off[r] + st * up - st * down, P["lo"][r], P["hi"][r])
                self.early[r] = 0
                self.late[r] = 0
                self.hos[r] = 0
                self.served[r] = 0
            self._sync(obs)
        elif moved.any():
            self._sync(obs)
        return self.engine.step(obs)

    def _sync(self, obs):
        self.engine.cho.a3.offset_db = self.off[self.rep, obs.serving][:, None].copy()
