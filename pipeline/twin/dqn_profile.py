"""HORUS v2 policy, profile form (finals): DQN+LSTM selects, per UE every
5 s, which 3GPP-standard A3 handover profile the RAN applies; a standard
per-neighbour-TTT A3 engine (controllers_v2.A3Batch) executes the HOs.

Why this form (finals finding, see working/evidence/finals-train/): the
direct form (dqn_v2.py — "hand over to cell j now?" every 200 ms) did not
learn: an HO is ~1% of decisions, so both Q-learning and distillation of the
tuned A3 collapse to "always stay" (distilled-only validation U 7.5 vs the
teacher's ~12, HO rate 0.1-0.3/UE-min vs ~5). Choosing the handover PROFILE
is a dense, well-posed decision; it is also the safer product: the AI can
only ever select standard-valid reportConfig parameters (offset, hysteresis,
TTT) — every HO is still a 3GPP A3 event — and its blast radius is bounded
by the profile table. It attacks exactly the gap the baseline sweep exposed:
the best A3 setting differs by mobility and fading (TTT 0 for movers, 1.28 s
for faded stationary users), and one network-wide setting loses ~1.1
utility/UE-min to per-situation tuning. The policy has to infer the
situation per UE from its measurements alone.

All profiles use L3 fc4 — the same filter as every v2 observation — so no
filter-switch idealization is needed.
"""

import numpy as np

from .controllers_v2 import A3Batch
from .dqn import checkpoint_path
from .dqn_v2 import WindowBank, _torch, features_v2, n_features

ARCH = "dqn_lstm_profile"
WINDOW = 4          # decisions of history in the LSTM (20 s at 5 s decisions)
HIDDEN = 48
PERIOD_S = 5.0      # a profile is held 5 s per decision (see train_profile.py:
                    # at 0.5 s a single-decision deviation is invisible — the TTT
                    # timers keep running — so Q-learning could not value the
                    # conservative mode; a committal hold makes the choice matter)
L3_K = 4
# name, offset_db, hys_db, ttt_s  (chosen from the k=4 slice of the sweep:
# the per-cell bests plus two speed-graded neighbours)
PROFILES = (
    ("fast-mobile",      -1.0, 2.0, 0.0),   # enter +1 dB, leave -3 dB
    ("mobile",            0.0, 2.0, 0.0),
    ("mobile-light-ttt",  1.0, 1.0, 0.08),
    ("faded-mobile",      2.0, 0.0, 0.16),
    ("slow",              4.0, 2.0, 0.64),
    ("static-faded",      6.0, 0.0, 1.28),
)


N_MOB = 3


class MobilityTracker:
    """Long-horizon mobility-state estimate per UE from its own L1 reports —
    the learned analogue of 3GPP mobility state estimation (which counts
    HOs/reselections over T_CRmax). A 4 s LSTM window cannot tell a 1.4 m/s
    walker from a faded stationary UE (5.6 m of motion is below the fading
    noise); 20 s of report history can:
        mobility = mean over the 4 strongest cells of |EMA_10s(now) - EMA_10s(20 s ago)|
        fading   = mean over the same cells of |L1 - EMA_10s|
    Updated at each decision (0.5 s). Inputs are ordinary measurement
    reports, so an xApp can compute this from KPM history."""

    TAU_S, LAG_S = 10.0, 20.0

    def __init__(self, period_s):
        self.a = 1.0 - np.exp(-period_s / self.TAU_S)
        self.lag = int(round(self.LAG_S / period_s))
        self.ema, self.hist, self.n = None, [], 0

    def update(self, l1):
        if self.ema is None or self.ema.shape != l1.shape:
            self.ema, self.hist, self.n = l1.copy(), [], 0
        else:
            self.ema = (1 - self.a) * self.ema + self.a * l1
        self.hist.append(self.ema.copy())
        if len(self.hist) > self.lag + 1:
            self.hist.pop(0)
        self.n += 1
        top = np.argsort(-self.ema, axis=1)[:, :4]
        rows = np.arange(l1.shape[0])[:, None]
        mob = np.abs(self.ema[rows, top] - self.hist[0][rows, top]).mean(1)
        fad = np.abs(l1[rows, top] - self.ema[rows, top]).mean(1)
        warm = min(1.0, (len(self.hist) - 1) / self.lag)
        return np.stack([np.clip(mob / 5.0, 0, 2), np.clip(fad / 5.0, 0, 2),
                         np.full(l1.shape[0], warm)], 1).astype(np.float32)


def n_features_p(n_cells):
    return n_features(n_cells) + len(PROFILES) + N_MOB


def features_p(obs, current, tracker):
    oh = np.zeros((len(current), len(PROFILES)), np.float32)
    oh[np.arange(len(current)), current] = 1.0
    return np.concatenate([features_v2(obs), oh, tracker.update(obs.l1)], 1)


def build_net_p(n_cells, hidden=HIDDEN):
    torch = _torch()

    class QNetProfile(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.inp = torch.nn.Linear(n_features_p(n_cells), hidden)
            self.lstm = torch.nn.LSTM(hidden, hidden, batch_first=True)
            self.val = torch.nn.Linear(hidden, 1)
            self.adv = torch.nn.Linear(hidden, len(PROFILES))

        def forward(self, x):
            h, _ = self.lstm(torch.relu(self.inp(x)))
            z = h[:, -1, :]
            a = self.adv(z)
            return self.val(z) + a - a.mean(1, keepdim=True)

    return QNetProfile()


class ProfileEngine:
    """Per-row A3 with a switchable profile. Switching keeps the per-neighbour
    TTT timers (same measurements, new thresholds next report)."""

    def __init__(self, n_rows, default=1):
        self.current = np.full(n_rows, default)
        self.a3 = A3Batch(*self._cols(), l3_k=L3_K, name="a3-profile")

    def _cols(self):
        t = np.array([p[1:] for p in PROFILES])[self.current]
        return t[:, 0:1].copy(), t[:, 1:2].copy(), t[:, 2:3].copy()

    def set(self, profiles):
        self.current = np.asarray(profiles)
        self.a3.offset_db, self.a3.hys_db, self.a3.ttt_s = self._cols()

    def step(self, obs):
        return self.a3.decide_batch(obs)


class GreedyProfilePolicy:
    """Controller (sim contract) around a profile Q-net."""

    def __init__(self, net, cells, period_s=PERIOD_S, name="dqn-profile"):
        self.torch = _torch()
        self.net, self.cells, self.period_s, self.name = net, list(cells), period_s, name
        self.l3_k = L3_K
        self.reset()

    def reset(self):
        self.bank, self.engine, self._next_t = WindowBank(), None, 0.0
        self.tracker = MobilityTracker(self.period_s)
        self.trace = []

    def decide_batch(self, obs):
        n = len(obs.serving)
        if self.engine is None:
            self.engine = ProfileEngine(n)
        if obs.t + 1e-9 >= self._next_t:
            self._next_t = obs.t + self.period_s
            w = self.bank.push(features_p(obs, self.engine.current, self.tracker))
            with self.torch.no_grad():
                q = self.net(self.torch.from_numpy(w)).numpy()
            self.engine.set(q.argmax(1))
            self.trace.append(np.bincount(self.engine.current, minlength=len(PROFILES)))
        return self.engine.step(obs)


class DQNProfileController(GreedyProfilePolicy):
    def __init__(self, checkpoint):
        torch = _torch()
        ck = torch.load(checkpoint, map_location="cpu", weights_only=True)
        if ck.get("arch") != ARCH:
            raise ValueError(f"{checkpoint}: not a {ARCH} checkpoint")
        if [tuple(p) for p in ck["profiles"]] != [tuple(p) for p in PROFILES]:
            raise ValueError(f"{checkpoint}: profile table differs from this code's")
        net = build_net_p(len(ck["cells"]), ck.get("hidden", HIDDEN))
        net.load_state_dict(ck["state_dict"])
        net.eval()
        self.version = ck["version"]
        self.meta = {k: v for k, v in ck.items() if k != "state_dict"}
        super().__init__(net, ck["cells"], ck.get("decision_period_s", PERIOD_S),
                         name=f"dqn2:{ck['version']}")

    def decide_batch(self, obs):
        if list(obs.cell_ids) != self.cells:
            raise ValueError("cell list differs from the checkpoint's")
        return super().decide_batch(obs)


def load_any_v2(version, root=None):
    """dqn2:<version> resolves either v2 architecture by the checkpoint's arch."""
    torch = _torch()
    p = checkpoint_path(version, root)
    if not p.exists():
        raise FileNotFoundError(f"no v2 checkpoint {p}")
    arch = torch.load(p, map_location="cpu", weights_only=True).get("arch")
    if arch == ARCH:
        return DQNProfileController(p)
    if arch == "ctx_cho_selector":
        from .selector_v3 import load_selector
        return load_selector(p)
    from .dqn_v2 import DQNv2Controller
    return DQNv2Controller(p)


class MobilityRuleController:
    """ABLATION (added after pre-registration, reported, not part of the
    go/no-go): the hand-written rule the DQN's mobility feature makes
    possible — mobility index < `thr_db` -> static-faded profile, else the
    mobile profile; the first 20 s (no history yet) use mobile. If the DQN
    cannot beat this, the learning adds nothing beyond the feature."""

    def __init__(self, thr_db=2.0, period_s=PERIOD_S):
        self.thr, self.period_s, self.l3_k = thr_db / 5.0, period_s, L3_K
        self.name = f"mse-rule(thr={thr_db}dB)"
        self.reset()

    def reset(self):
        self.engine, self._next_t = None, 0.0
        self.tracker = MobilityTracker(self.period_s)

    def decide_batch(self, obs):
        n = len(obs.serving)
        if self.engine is None:
            self.engine = ProfileEngine(n)
        if obs.t + 1e-9 >= self._next_t:
            self._next_t = obs.t + self.period_s
            mob = self.tracker.update(obs.l1)
            static = (mob[:, 2] >= 1.0) & (mob[:, 0] < self.thr)
            self.engine.set(np.where(static, len(PROFILES) - 1, 1))
        return self.engine.step(obs)
