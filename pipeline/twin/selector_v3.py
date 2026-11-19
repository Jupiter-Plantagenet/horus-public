"""HORUS v3 policy: a learned per-UE conditional-handover profile selector.

Every `period_s` the policy estimates, for each UE, the operator utility of
each CHO profile over the next minute from that UE's online situation
features (cho_v3.SituationFeatures — measurement reports only), and applies
the best one through ProfileCHO. Every handover is still a 3GPP CHO
execution with standard parameters; the AI chooses which parameter set.

Safety structure (bounded blast radius):
  - cold start: the network-wide default profile until `warm_s` of
    measurements exist;
  - conservative switching: leave the default only if the predicted gain over
    the default exceeds `margin`; change the current profile only if the
    predicted gain over it exceeds `switch_margin` (hysteresis);
  - the profile table is fixed in the checkpoint and validated on load.

Checkpoint (pipeline/checkpoints/dqn-<version>.pt, so the frozen policy
artifact / gate tooling is unchanged): arch "ctx_cho_selector", profiles,
feature names, input normalisation, MLP state_dict, decision constants.
"""

import numpy as np

from .cho_v3 import FEATURE_NAMES, FEATURE_SETS, N_FEATURES, ProfileCHO, SituationFeatures, feature_set_of

ARCH = "ctx_cho_selector"
HIDDEN = 64
PREDICTION_HEADS = ("utility_delta", "ho_rate", "fail_rate")
COST_RULES = ("utility_only", "fail_constrained", "fail_ho_constrained", "penalized")
COST_PARAM_KEYS = ("ho_penalty", "fail_penalty", "ho_slack", "fail_slack")


def check_cost_params(rule, params):
    """v3.14 'penalized' rule parameters (finals_preregistration_v3_14.json):
    penalties >= 0 per unit of predicted rate above the default's, slacks
    None (no hard bound) or >= 0. Other rules take no parameters."""
    if rule != "penalized":
        if params:
            raise ValueError(f"cost rule {rule!r} takes no cost_params")
        return None
    params = dict(params or {})
    if set(params) != set(COST_PARAM_KEYS):
        raise ValueError(f"penalized rule needs exactly {COST_PARAM_KEYS}, got {sorted(params)}")
    for k in ("ho_penalty", "fail_penalty"):
        if not (isinstance(params[k], (int, float)) and np.isfinite(params[k]) and params[k] >= 0):
            raise ValueError(f"{k} must be a finite number >= 0")
    for k in ("ho_slack", "fail_slack"):
        if params[k] is not None and not (np.isfinite(params[k]) and params[k] >= 0):
            raise ValueError(f"{k} must be None or a finite number >= 0")
    return params


def score_profiles(heads, rule, params=None, default=0):
    """Decision scores (N, K) from multi-head predictions (N, K, 3) = (utility
    relative to the default, HO rate, failure rate per UE-minute), already
    divided by the head scales. Shared by the online policy and the offline
    regret so both apply the rule identically. Infeasible profiles are -inf;
    the default is always feasible and scores 0.

      utility_only         U
      fail_constrained     U, feasible iff F(j) <= F(default)
      fail_ho_constrained  U, feasible iff F(j) <= F(d) and HO(j) <= HO(d)
      penalized            U - ho_penalty*(HO(j)-HO(d)) - fail_penalty*(F(j)-F(d)),
                           feasible iff HO(j) <= HO(d)+ho_slack and F(j) <= F(d)+fail_slack
                           (a None slack is no bound)
    """
    q = heads[:, :, 0].copy()
    if rule == "utility_only":
        feasible = np.ones(q.shape, bool)
    else:
        rates = np.maximum(heads[:, :, 1:], 0.0)                 # (N, K, 2): ho, fail
        d = default
        rel = rates - rates[:, d:d + 1, :]
        if rule == "penalized":
            q = q - params["ho_penalty"] * rel[:, :, 0] - params["fail_penalty"] * rel[:, :, 1]
            feasible = np.ones(q.shape, bool)
            for i, k in ((0, "ho_slack"), (1, "fail_slack")):
                if params[k] is not None:
                    feasible &= rel[:, :, i] <= params[k]
        else:
            use = [1] if rule == "fail_constrained" else [0, 1]
            feasible = (rates[:, :, use] <= rates[:, d:d + 1, use]).all(2)
    feasible[:, default] = True
    q = np.where(feasible, q, -np.inf)
    q[:, default] = 0.0
    return q, feasible


def _torch():
    import torch
    torch.set_num_threads(1)
    return torch


def build_mlp(n_in, n_out, hidden=HIDDEN):
    torch = _torch()
    return torch.nn.Sequential(torch.nn.Linear(n_in, hidden), torch.nn.ReLU(),
                               torch.nn.Linear(hidden, hidden), torch.nn.ReLU(),
                               torch.nn.Linear(hidden, n_out))


class NumpyMLP:
    """Inference without torch overhead (weights copied from the state_dict)."""

    def __init__(self, sd):
        self.W = [np.asarray(sd[f"{i}.weight"], np.float64) for i in (0, 2, 4)]
        self.b = [np.asarray(sd[f"{i}.bias"], np.float64) for i in (0, 2, 4)]

    def __call__(self, x):
        h = x
        for j, (W, b) in enumerate(zip(self.W, self.b)):
            h = h @ W.T + b
            if j < 2:
                h = np.maximum(h, 0.0)
        return h


class CHOSelectorPolicy:
    def __init__(self, ck, name=None):
        self.profiles = ck["profiles"]
        self.default = int(ck["default"])
        # checkpoints without feature_names (tests) are the v3 set
        self.feature_set = feature_set_of(ck.get("feature_names", FEATURE_NAMES))
        self.mu = np.asarray(ck["x_mean"], float)
        self.sd = np.asarray(ck["x_std"], float)
        self.period_s = float(ck.get("period_s", 2.0))
        self.warm_s = float(ck.get("warm_s", 10.0))
        self.margin = float(ck.get("margin", 0.0))
        self.switch_margin = float(ck.get("switch_margin", 0.0))
        # v3.14: a UE keeps a newly chosen profile for at least min_dwell_s (0 = v3.1.x/v3.13 behaviour);
        # an infeasible held profile is still left at once
        self.min_dwell_s = float(ck.get("min_dwell_s", 0.0))
        if not (np.isfinite(self.min_dwell_s) and self.min_dwell_s >= 0):
            raise ValueError("min_dwell_s must be a finite number >= 0")
        self.allowed = np.asarray(ck.get("allowed", [True] * len(self.profiles)), bool)
        # v3.13 multi-head checkpoints (finals_preregistration_v3_13.json); absent -> v3.1.x behaviour
        self.prediction_heads = ck.get("prediction_heads")
        self.head_scales = np.asarray(ck.get("head_scales", [1.0, 1.0, 1.0]), float)
        self.cost_rule = ck.get("cost_rule", "utility_only")
        self.cost_params = ck.get("cost_params")
        if self.prediction_heads is not None:
            if list(self.prediction_heads) != list(PREDICTION_HEADS):
                raise ValueError(f"unknown prediction heads {self.prediction_heads!r}")
            if self.cost_rule not in COST_RULES:
                raise ValueError(f"unknown cost rule {self.cost_rule!r}")
            self.cost_params = check_cost_params(self.cost_rule, self.cost_params)
        elif self.cost_rule != "utility_only" or self.cost_params:
            raise ValueError("cost rules need a multi-head checkpoint")
        self.cost_blocked = 0
        self.net = NumpyMLP(ck["state_dict"])
        # optional ensemble (v3.14): extra members with their own input normalisation and
        # weights; the policy uses the mean of all members' raw outputs
        self.members = [(self.mu, self.sd, self.net)] + [
            (np.asarray(m["x_mean"], float), np.asarray(m["x_std"], float), NumpyMLP(m["state_dict"]))
            for m in ck.get("ensemble", [])]
        self.version = ck.get("version", "unversioned")
        self.name = name or f"dqn2:{self.version}"
        self.l3_k = 4
        self.meta = {k: v for k, v in ck.items() if k != "state_dict"}
        self.reset()

    def reset(self):
        self.engine = ProfileCHO(self.profiles, default=self.default)
        self.feat = SituationFeatures(feature_set=self.feature_set)
        self._next_t = None
        self._last_switch = None
        self.switches = 0
        self.trace = []

    def predict(self, X):
        """Predicted window utility of every profile RELATIVE to the default.

        Multi-head checkpoints also predict absolute HO and failure rates per
        UE-minute; under a cost rule a profile whose predicted rate exceeds the
        default profile's is infeasible (-inf). The default is always feasible."""
        if len(self.members) == 1:
            q = self.net((X - self.mu) / self.sd)
        else:
            q = np.mean([net((X - mu) / sd) for mu, sd, net in self.members], axis=0)
        if self.prediction_heads is not None:
            heads = q.reshape(len(X), len(self.profiles), len(PREDICTION_HEADS)) / self.head_scales
            if not np.isfinite(heads).all():
                raise ValueError("nonfinite_cost_predictions")
            self.last_heads = heads
            q, feasible = score_profiles(heads, self.cost_rule, self.cost_params, self.default)
            self.cost_blocked += int((~feasible).sum())
        q[:, self.default] = 0.0
        return np.where(self.allowed[None], q, -np.inf)

    def decide_batch(self, obs):
        self.feat.update(obs)
        if self.engine.current is None:
            self.engine.set(np.full(len(obs.serving), self.default), obs)
            self._next_t = obs.t + self.period_s
            self._t0 = obs.t
        if obs.t + 1e-9 >= self._next_t:
            self._next_t = obs.t + self.period_s
            if obs.t - self._t0 + 1e-9 >= self.warm_s:
                q = self.predict(self.feat.vector())
                cur = self.engine.current
                best = q.argmax(1)
                rows = np.arange(len(cur))
                gain_cur = q[rows, best] - q[rows, cur]
                choice = np.where(gain_cur > self.switch_margin, best, cur)
                # never leave the default unless clearly better than it
                choice = np.where(q[rows, choice] > self.margin, choice, self.default)
                if self.min_dwell_s > 0:
                    if self._last_switch is None:
                        self._last_switch = np.full(len(cur), -np.inf)
                    choice = np.where(obs.t - self._last_switch + 1e-9 < self.min_dwell_s, cur, choice)
                # a held profile can become infeasible under a cost rule; hysteresis and dwell
                # must never keep it (no-op for single-head checkpoints: q is finite)
                choice = np.where(np.isfinite(q[rows, choice]), choice, best)
                changed = choice != cur
                self.switches += int(changed.sum())
                if self._last_switch is not None:
                    self._last_switch[changed] = obs.t
                self.engine.set(choice)
            self.trace.append(np.bincount(self.engine.current, minlength=len(self.profiles)))
        return self.engine.step(obs)


def load_selector(path):
    torch = _torch()
    ck = torch.load(path, map_location="cpu", weights_only=True)
    if ck.get("arch") != ARCH:
        raise ValueError(f"{path}: not a {ARCH} checkpoint")
    if list(ck["feature_names"]) not in [list(v) for v in FEATURE_SETS.values()]:
        raise ValueError(f"{path}: feature set differs from this code's")
    if ck["x_mean"].__len__() != len(ck["feature_names"]):
        raise ValueError(f"{path}: input width mismatch")
    return CHOSelectorPolicy(ck)
