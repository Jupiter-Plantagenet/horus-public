# Frozen A3Batch reference copied unchanged from finals-twin commit a98c2cc8fec977b5a4aaa0e8c457aeff222518c1.
# Source SHA256: 7352d14c67d59a57583dbc3107bd19ec99332049af73c2bae080c658656ba7c3
# This measured RSRP decision replay does not claim full PHY/HO execution.
import numpy as np

class A3Batch:
    """Event A3 (TS 38.331 Ã‚Â§5.5.4.4) with frequency/cell offsets 0:
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
