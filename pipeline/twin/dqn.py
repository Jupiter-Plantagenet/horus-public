"""DQN+LSTM handover policy (#8): the learned controller.

Architecture (deliberately small — the box shares 4 CPU cores with the live
stack): per-step features are the normalized per-cell RSRP vector plus a
one-hot of the serving cell (2*n_cells wide; 14 on the 7-cell placeholder
map); an LSTM encodes the last WINDOW reports (that's the "recent KPM
windows" from the proposal — RSRP dynamics, not just the instant snapshot,
decide whether a neighbour is really better or just shadow-wiggling); a
linear head emits Q-values over n_cells+1 actions: stay, or hand to cell i.

The controller implements the same decide(ue, rsrp, step) contract as the
A3 baseline, so the twin env cannot tell them apart. Checkpoints are
loadable by version string (dqn-<version>.pt) — that string is what flows
into policy_artifact.weights_ref for the gate (#10) and the store (#11).

torch is imported lazily: `python -m twin.run --controller a3` must keep
working on a bare interpreter (twin core stays stdlib-only).
"""

import re
from collections import deque
from pathlib import Path

from .radio import normalize_rsrp

WINDOW = 8          # LSTM looks at the last 8 measurement reports (~8 s)
HIDDEN = 32

_VERSION_SAFE = re.compile(r"^[\w.\-]+$")


def _torch():
    import torch
    import os
    # every torch entry point (train/compare/gate) leaves cores for the live
    # stack; HORUS_TORCH_THREADS=1 for many parallel workers (tiny LSTM ops
    # get slower, not faster, with oversubscribed intra-op threads)
    torch.set_num_threads(int(os.environ.get("HORUS_TORCH_THREADS", "2")))
    return torch


def cell_order(rsrp):
    """Stable feature order: sorted cell_ids. The twin's dict ordering is an
    implementation detail; the net's input layout must not depend on it."""
    return sorted(rsrp)


def features(rsrp, serving, cells):
    norm = [normalize_rsrp(rsrp[c]) for c in cells]
    onehot = [1.0 if c == serving else 0.0 for c in cells]
    return norm + onehot


class CellEncoder:
    """The v1 input layout: one fixed feature slot per named cell (sorted
    cell_ids), actions 0=stay / 1+i = HO to cells[i]. Tied to ONE radio map —
    a checkpoint trained on Kumoh's 9 sites means nothing on another campus."""
    kind = "cells"

    def __init__(self, cells):
        self.cells = list(cells)
        self.n_in = 2 * len(self.cells)
        self.n_actions = len(self.cells) + 1
        self._w = {}

    def spec(self):
        return None                      # legacy checkpoints carry no encoder key

    def reset(self):
        self._w = {}

    def push(self, ue_id, rsrp, serving):
        self._w.setdefault(ue_id, deque(maxlen=WINDOW)).append(
            features(rsrp, serving, self.cells))

    def ready(self, ue_id):
        return len(self._w.get(ue_id, ())) >= WINDOW

    def window(self, ue_id):
        return list(self._w[ue_id])

    def target(self, ue_id, a):
        return self.cells[a - 1] if a > 0 else None


class RankEncoder:
    """Campus-agnostic layout (finals, any-campus): slot 0 = the serving cell,
    slots 1..K-1 = the K-1 strongest neighbours *right now*; the LSTM window
    replays each slot cell's RSRP history (+ was-serving flag) over the last
    WINDOW reports. Actions: 0 = stay, i = HO to slot i. No cell identities
    enter the net, so the same weights run on any campus with any site count
    — which is what makes cross-campus federation and transfer meaningful."""
    kind = "rank"

    def __init__(self, k=6):
        self.k = int(k)
        self.n_in = 2 * self.k
        self.n_actions = self.k          # stay + (k-1) neighbours
        self._h, self._slots = {}, {}

    def spec(self):
        return {"kind": self.kind, "k": self.k, "window": WINDOW}

    def reset(self):
        self._h, self._slots = {}, {}

    def push(self, ue_id, rsrp, serving):
        self._h.setdefault(ue_id, deque(maxlen=WINDOW)).append((rsrp, serving))

    def ready(self, ue_id):
        return len(self._h.get(ue_id, ())) >= WINDOW

    def window(self, ue_id):
        hist = self._h[ue_id]
        rsrp_now, serving = hist[-1]
        nbrs = sorted((c for c in rsrp_now if c != serving),
                      key=lambda c: (-rsrp_now[c], c))[: self.k - 1]
        slots = [serving] + nbrs + [None] * (self.k - 1 - len(nbrs))
        self._slots[ue_id] = slots
        rows = []
        for rsrp, srv in hist:
            rows.append([normalize_rsrp(rsrp[c]) if c is not None and c in rsrp else 0.0
                         for c in slots]
                        + [1.0 if c is not None and c == srv else 0.0 for c in slots])
        return rows

    def target(self, ue_id, a):
        return self._slots[ue_id][a] if a > 0 else None


def make_encoder(spec, cells=None):
    if not spec:
        return CellEncoder(cells)
    if spec.get("kind") == "rank":
        return RankEncoder(spec.get("k", 6))
    raise ValueError(f"unknown encoder spec: {spec}")


def build_net(n_cells=None, n_in=None, n_actions=None):
    """build_net(n_cells) is the v1 cell-slot net; pass n_in/n_actions for
    any other encoder (same LSTM+head architecture, only the widths move)."""
    torch = _torch()
    n_in = n_in if n_in is not None else 2 * n_cells
    n_actions = n_actions if n_actions is not None else n_cells + 1

    class QNet(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.lstm = torch.nn.LSTM(n_in, HIDDEN, batch_first=True)
            self.head = torch.nn.Linear(HIDDEN, n_actions)  # 0=stay, else HO target slot

        def forward(self, x):                 # x: (batch, WINDOW, 2*n_cells)
            out, _ = self.lstm(x)
            return self.head(out[:, -1, :])   # Q from the last step's encoding

    return QNet()


class DQNController:
    """Greedy evaluation-mode controller over a trained checkpoint."""
    name = "dqn"

    def __init__(self, checkpoint):
        torch = _torch()
        self.torch = torch
        ckpt = torch.load(checkpoint, map_location="cpu", weights_only=True)
        self.version = ckpt["version"]
        self.cells = ckpt.get("cells")
        self.encoder = make_encoder(ckpt.get("encoder"), self.cells)
        self.net = build_net(n_in=self.encoder.n_in, n_actions=self.encoder.n_actions)
        self.net.load_state_dict(ckpt["state_dict"])
        self.net.eval()

    def reset(self):
        """Clear per-UE LSTM windows between episodes (part of the controller
        contract — harnesses must call this, never reach into the encoder)."""
        self.encoder.reset()

    @property
    def _windows(self):
        """v1 name for the per-UE window state (kept for existing tests)."""
        enc = self.encoder
        return enc._w if isinstance(enc, CellEncoder) else enc._h

    def decide(self, ue, rsrp, step):
        enc = self.encoder
        enc.push(ue.ue_id, rsrp, ue.serving)
        if not enc.ready(ue.ue_id):
            return None                        # warm-up: hold until the window fills
        x = self.torch.tensor([enc.window(ue.ue_id)], dtype=self.torch.float32)
        with self.torch.no_grad():
            q = self.net(x)[0]
        target = enc.target(ue.ue_id, int(q.argmax()))
        return None if target is None or target == ue.serving else target


def checkpoint_path(version, root=None):
    if not _VERSION_SAFE.match(version or ""):
        raise ValueError(f"unsafe version string: {version!r}")
    root = Path(root) if root else Path(__file__).resolve().parent.parent / "checkpoints"
    return root / f"dqn-{version}.pt"


def load_dqn(version, root=None):
    p = checkpoint_path(version, root)
    if not p.exists():
        raise FileNotFoundError(
            f"no checkpoint for version {version} at {p} — train one: "
            f"python -m twin.train_dqn --version {version}")
    return DQNController(p)
