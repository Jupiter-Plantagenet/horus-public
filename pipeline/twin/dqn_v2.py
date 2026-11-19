"""DQN+LSTM handover policy v2 (finals): the learned controller for twin v2.

What changed vs v1 (dqn.py, kept for the v1.x checkpoints the live loop uses):

- observations are the sim's L3-FILTERED per-RE RSRP (fc4, the same filter
  machinery the A3 baseline gets), not raw per-step samples;
- per-UE features (F = 3C + 4): absolute L3 RSRP (normalized), L3 RSRP
  RELATIVE to serving (the quantity A3 thresholds), serving one-hot, serving
  RS-SINR (a CQI proxy the RIC receives via KPM), time since last HO, L1-L3
  deviation on the serving cell (a fading-activity cue: slow deep fades on a
  stationary UE look different from a mobility trend), connected flag;
- decisions every `period_s` (200 ms, a near-RT RIC cadence) for all UEs in
  one batched forward pass; the LSTM sees the last WINDOW decisions (1.6 s);
- invalid actions (serving cell, silenced cells, HO already in flight) are
  masked out of the argmax instead of being learned around.
"""

from pathlib import Path

import numpy as np

from .dqn import checkpoint_path
from .phy import normalize_rsrp_v2

WINDOW = 8
HIDDEN = 48
PERIOD_S = 0.2
ARCH = "dqn_lstm_v2"


def _torch():
    """torch with ONE intra-op thread: the v1 helper's 2 threads spin-wait on
    this shared box (0.4 s per tiny LSTM call)."""
    import torch
    torch.set_num_threads(1)
    return torch


def n_features(n_cells):
    return 3 * n_cells + 4


def features_v2(obs):
    """(R*N, F) float32 feature matrix from a sim Obs."""
    l3 = obs.l3
    n, m = l3.shape
    idx = np.arange(n)
    mp = l3[idx, obs.serving]
    rel = np.clip((l3 - mp[:, None]) / 10.0, -2.0, 2.0)
    onehot = np.zeros((n, m))
    onehot[idx, obs.serving] = 1.0
    sinr = np.clip((obs.sinr_db + 10.0) / 40.0, 0.0, 1.0)
    tsh = np.minimum(obs.time_since_ho, 10.0) / 10.0
    dev = np.clip((obs.l1[idx, obs.serving] - mp) / 10.0, -2.0, 2.0)
    return np.concatenate([normalize_rsrp_v2(l3), rel, onehot,
                           np.stack([sinr, tsh, dev, obs.connected.astype(float)], 1)],
                          1).astype(np.float32)


def action_mask(obs):
    """(R*N, C+1) bool: action 0 (stay) always valid; HO to cell j only if
    the UE can hand over, j is active and j != serving."""
    n, m = obs.l3.shape
    mask = np.ones((n, m + 1), dtype=bool)
    mask[:, 1:] = obs.active[None] & obs.can_ho[:, None]
    mask[np.arange(n), 1 + obs.serving] = False
    return mask


def build_net_v2(n_cells, hidden=HIDDEN):
    torch = _torch()

    class QNetV2(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.inp = torch.nn.Linear(n_features(n_cells), hidden)
            self.lstm = torch.nn.LSTM(hidden, hidden, batch_first=True)
            self.val = torch.nn.Linear(hidden, 1)              # dueling heads
            self.adv = torch.nn.Linear(hidden, n_cells + 1)

        def forward(self, x):                                   # (B, W, F)
            h, _ = self.lstm(torch.relu(self.inp(x)))
            z = h[:, -1, :]
            a = self.adv(z)
            return self.val(z) + a - a.mean(1, keepdim=True)

    return QNetV2()


class WindowBank:
    """Rolling (rows, WINDOW, F) feature history; new rows are padded with
    their first observation (no warm-up hold)."""

    def __init__(self):
        self.w = None

    def push(self, f):
        if self.w is None or self.w.shape[0] != f.shape[0]:
            self.w = np.repeat(f[:, None, :], WINDOW, axis=1)
        else:
            self.w = np.concatenate([self.w[:, 1:], f[:, None, :]], 1)
        return self.w


class DQNv2Controller:
    """Greedy batch controller over a v2 checkpoint (sim.py contract)."""

    def __init__(self, checkpoint):
        torch = _torch()
        self.torch = torch
        ck = torch.load(checkpoint, map_location="cpu", weights_only=True)
        if ck.get("arch") != ARCH:
            raise ValueError(f"{checkpoint}: not a {ARCH} checkpoint")
        self.version = ck["version"]
        self.cells = ck["cells"]
        self.period_s = ck.get("decision_period_s", PERIOD_S)
        self.l3_k = ck.get("obs_filter", {}).get("l3_k", 4)
        self.net = build_net_v2(len(self.cells), ck.get("hidden", HIDDEN))
        self.net.load_state_dict(ck["state_dict"])
        self.net.eval()
        self.name = f"dqn2:{self.version}"
        self.meta = {k: v for k, v in ck.items() if k != "state_dict"}
        self.reset()

    def reset(self):
        self.bank = WindowBank()
        self._next_t = 0.0

    def decide_batch(self, obs):
        if list(obs.cell_ids) != list(self.cells):
            raise ValueError("cell list differs from the checkpoint's")
        n = len(obs.serving)
        if obs.t + 1e-9 < self._next_t:
            return np.full(n, -1), None
        self._next_t = obs.t + self.period_s
        w = self.bank.push(features_v2(obs))
        with self.torch.no_grad():
            q = self.net(self.torch.from_numpy(w)).numpy()
        q = np.where(action_mask(obs), q, -np.inf)
        a = q.argmax(1)
        return np.where(a > 0, a - 1, -1), None


def load_dqn_v2(version, root=None):
    p = checkpoint_path(version, root)
    if not p.exists():
        raise FileNotFoundError(f"no v2 checkpoint {p} — train one: python -m twin.train_v2 --version {version}")
    return DQNv2Controller(p)
