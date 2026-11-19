"""Twin v2 (sim.py) batch controllers: 3GPP-faithful A3, conditional HO, and
adapters for learned policies.

The legacy controllers.A3Controller is kept bit-identical for the v1.x
evidence. It has two non-3GPP traits: ONE TTT counter for the current best
neighbour (reset whenever the best changes) and no L3 filtering, with TTT
counted in 1 s env steps (TTT=3 -> 3 s, far above 3GPP's 0-1280 ms). The
classes here fix all three: TTT runs PER NEIGHBOUR (TS 38.331 §5.5.4 tracks
each cell meeting the entering condition separately, cellsTriggeredList), TTT
is in seconds on the sim's sub-second clock, and measurements are the sim's
L3-filtered values with filterCoefficient `l3_k` — each policy's own RRC
config, which the sim applies (so every controller sees the SAME filter
machinery; a tuned A3 is merely allowed to pick its k).

Batch contract: decide_batch(obs) -> (targets int (N,) with -1 = stay,
cond bool (N,) for conditional executions, or None).
"""

import numpy as np


class A3Batch:
    """Event A3 (TS 38.331 §5.5.4.4) with frequency/cell offsets 0:
        entering  Mn - Hys > Mp + Off
        leaving   Mn + Hys < Mp + Off
    Between the two a running timer keeps running (that is what Hys is for).
    A neighbour that has satisfied entering continuously for TTT fires a
    report; the network hands over to the strongest fired neighbour."""

    def __init__(self, offset_db=3.0, hys_db=1.0, ttt_s=0.32, l3_k=4, name=None):
        self.offset_db, self.hys_db, self.ttt_s, self.l3_k = offset_db, hys_db, ttt_s, l3_k
        self.name = name or f"a3(off={offset_db},hys={hys_db},ttt={ttt_s},k={l3_k})"
        self.reset()

    @classmethod
    def grid(cls, configs, n_ues):
        """One A3Batch evaluating many configs at once over sim replicas:
        configs is a list of dicts (offset_db, hys_db, ttt_s, l3_k); row
        r*n_ues + i runs config r. Pass l3_k=[c['l3_k'] ...] to the sim."""
        col = lambda key: np.repeat([float(c[key]) for c in configs], n_ues)[:, None]
        g = cls(col("offset_db"), col("hys_db"), col("ttt_s"), None, name="a3-grid")
        g.l3_k = [c["l3_k"] for c in configs]
        return g

    def reset(self):
        self._timer = None
        self._in = None
        self._serving = None

    def decide_batch(self, obs):
        l3 = obs.l3
        n, m = l3.shape
        idx = np.arange(n)
        if self._timer is None or self._timer.shape != (n, m):
            self._timer = np.zeros((n, m))
            self._in = np.zeros((n, m), dtype=bool)
            self._serving = obs.serving.copy()
        moved = obs.serving != self._serving          # HO/re-establishment: new measConfig
        self._timer[moved] = 0.0
        self._in[moved] = False
        self._serving = obs.serving.copy()
        mp = l3[idx, obs.serving][:, None]
        enter = (l3 - self.hys_db > mp + self.offset_db) & obs.active[None]
        leave = l3 + self.hys_db < mp + self.offset_db
        self._in = enter | (self._in & ~leave)
        self._in[idx, obs.serving] = False
        self._in &= obs.active[None]
        self._timer = np.where(self._in, self._timer + obs.dt, 0.0)
        fired = self._in & (self._timer >= self.ttt_s - 1e-9)
        targets = np.full(n, -1)
        go = fired.any(1) & obs.can_ho
        if go.any():
            cand = np.where(fired, l3, -np.inf)
            targets[go] = cand[go].argmax(1)
            self._timer[go] = 0.0
            self._in[go] = False
        return targets, None


class CHOBatch:
    """Conditional handover (TS 38.300 §9.2.3.4, Rel-16). The network PREPARES
    candidates early — a neighbour within `prep_offset_db` of serving, with
    the RRC reconfiguration delivered while the source link is still decodable
    (serving SINR >= q_prep_db) — and the UE EXECUTES autonomously when the
    A3-style execution condition holds for TTT. Executions toward a prepared
    candidate skip the sim's command-loss check; an unprepared target falls
    back to an ordinary HO."""

    def __init__(self, prep_offset_db=-3.0, exec_offset_db=2.0, hys_db=0.0, ttt_s=0.16,
                 l3_k=4, q_prep_db=-8.0, name=None):
        self.prep_offset_db, self.q_prep_db = prep_offset_db, q_prep_db
        self.a3 = A3Batch(exec_offset_db, hys_db, ttt_s, l3_k)
        self.l3_k = l3_k
        self.name = name or (f"cho(prep={prep_offset_db},off={exec_offset_db},hys={hys_db},"
                             f"ttt={ttt_s},k={l3_k})")
        self.reset()

    @classmethod
    def grid(cls, configs, n_ues):
        """Replica-batched CHO over many configs (see A3Batch.grid)."""
        col = lambda key: np.repeat([float(c[key]) for c in configs], n_ues)[:, None]
        g = cls(col("prep_offset_db"), col("exec_offset_db"), col("hys_db"), col("ttt_s"),
                None, name="cho-grid")
        g.l3_k = [c["l3_k"] for c in configs]
        return g

    def reset(self):
        self.a3.reset()
        self._prepared = None
        self._serving = None

    def decide_batch(self, obs):
        l3 = obs.l3
        n, m = l3.shape
        idx = np.arange(n)
        if self._prepared is None or self._prepared.shape != (n, m):
            self._prepared = np.zeros((n, m), dtype=bool)
            self._serving = obs.serving.copy()
        self._prepared[obs.serving != self._serving] = False
        self._serving = obs.serving.copy()
        mp = l3[idx, obs.serving][:, None]
        can_prep = (obs.sinr_db >= self.q_prep_db) & obs.connected
        self._prepared |= (l3 > mp + self.prep_offset_db) & can_prep[:, None] & obs.active[None]
        self._prepared &= l3 > mp + self.prep_offset_db - 3.0      # release fallen candidates
        self._prepared[idx, obs.serving] = False
        targets, _ = self.a3.decide_batch(obs)
        ok = targets >= 0
        cond = np.zeros(n, dtype=bool)
        if ok.any():
            cond[ok] = self._prepared[idx[ok], targets[ok]]
        return targets, cond


class LegacyDQNBatch:
    """Run a v1.x per-UE DQNController (decide(ue, rsrp, step)) inside the v2
    sim: it receives the L3-filtered per-RE RSRP dict once per `period_s`
    (1 s, its trained cadence and the live xApp's KPM period).

    v1.x trained on the legacy twin, whose RSRP was computed from TOTAL
    carrier power (~35 dB hotter than per-RE RSRP). Feeding it real per-RE
    values would be an input-units bug, not a robustness test, so by default
    the adapter adds the per-RE offset back (`legacy_units_offset_db`) — v1.3.1
    sees its training units, and the stress is the physics, not the scaling."""

    def __init__(self, dqn, period_s=1.0, l3_k=4, legacy_units_offset_db=None):
        from .phy import PhyConfig
        dqn.torch.set_num_threads(1)   # dqn._torch() sets 2: spin-waits on a shared box
        self.dqn, self.period_s, self.l3_k = dqn, period_s, l3_k
        self.offset = (PhyConfig().per_re_offset_db if legacy_units_offset_db is None
                       else legacy_units_offset_db)
        self.name = f"dqn:{dqn.version}"
        self.reset()

    def reset(self):
        self.dqn.reset()
        self._next_t = 0.0

    def decide_batch(self, obs):
        n = len(obs.serving)
        targets = np.full(n, -1)
        if obs.t + 1e-9 < self._next_t:
            return targets, None
        self._next_t = obs.t + self.period_s
        col = {c: i for i, c in enumerate(obs.cell_ids)}
        for i in range(n):
            u = _UEView(obs.ue_ids[i], obs.cell_ids[obs.serving[i]])
            rsrp = {c: float(obs.l3[i, j]) + self.offset for j, c in enumerate(obs.cell_ids)}
            tgt = self.dqn.decide(u, rsrp, obs.t)
            if tgt is not None and obs.can_ho[i]:
                targets[i] = col[tgt]
        return targets, None


class _UEView:
    __slots__ = ("ue_id", "serving")

    def __init__(self, ue_id, serving):
        self.ue_id, self.serving = ue_id, serving


STOCK_A3 = dict(offset_db=3.0, hys_db=1.0, ttt_s=0.32, l3_k=4)       # common vendor default
LEGACY_PARAMS_A3 = dict(offset_db=0.0, hys_db=3.0, ttt_s=3.0, l3_k=0)  # the v1.x baseline's knobs


def parse_controller(spec):
    """Spec strings for the v2 harness:
        a3                     stock A3 (Off 3 dB, Hys 1 dB, TTT 320 ms, fc4)
        a3-legacy              the v1.x baseline's knobs (margin 3 dB, TTT 3 s, no L3)
        a3:off=2,hys=1,ttt=0.16,k=8[,name=...]
        cho:prep=-3,off=2,hys=0,ttt=0.16,k=4[,name=...]
        dqn:v1.3.1             legacy per-UE checkpoint via LegacyDQNBatch
        dqn2:v2.0.0            v2 batch checkpoint
    """
    if spec == "a3":
        return A3Batch(**STOCK_A3, name="a3-stock")
    if spec == "a3-legacy":
        return A3Batch(**LEGACY_PARAMS_A3, name="a3-legacy-params")
    kind, _, rest = spec.partition(":")
    kv = dict(p.split("=", 1) for p in rest.split(",") if "=" in p)
    if kind == "a3":
        return A3Batch(float(kv.get("off", 0)), float(kv.get("hys", 0)),
                       float(kv.get("ttt", 0)), int(kv.get("k", 4)), name=kv.get("name"))
    if kind == "cho":
        return CHOBatch(float(kv.get("prep", -3)), float(kv.get("off", 2)),
                        float(kv.get("hys", 0)), float(kv.get("ttt", 0.16)),
                        int(kv.get("k", 4)), name=kv.get("name"))
    if kind == "mse-rule":
        from .dqn_profile import MobilityRuleController
        return MobilityRuleController(float(kv.get("thr", 2.0)))
    if kind == "dqn":
        from .dqn import load_dqn
        return LegacyDQNBatch(load_dqn(rest or "v1.3.1"))
    if kind == "dqn2":
        from .dqn_profile import load_any_v2
        return load_any_v2(rest)
    raise ValueError(f"unknown controller spec: {spec}")
