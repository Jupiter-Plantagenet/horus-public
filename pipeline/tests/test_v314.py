"""v3.14: 'trend' feature set (the v3 set must stay bit-identical), the
'penalized' cost rule, ensembles, fed/trainer width handling."""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from twin.cho_v3 import (FEATURE_NAMES, FEATURE_NAMES_TREND, N_FEATURES, SituationFeatures,  # noqa: E402
                         feature_set_of, parse_profile)
from twin.finals_common import single_thread, trace_for  # noqa: E402
from twin.sim import SimConfig, TwinSim  # noqa: E402

single_thread()
SHORT = SimConfig(duration_s=30.0)
PROFS = ["cho:prep=-6,off=3,hys=1,ttt=0,k=8", "cho:prep=-6,off=6,hys=2,ttt=0,k=4",
         "cho:prep=-6,off=0,hys=2,ttt=0,k=4"]


class _Tap:
    """Runs the default CHO profile and records both feature sets every 0.5 s."""

    def __init__(self):
        from twin.cho_v3 import ProfileCHO
        self.engine = ProfileCHO([parse_profile(PROFS[0])])
        self.a, self.b = SituationFeatures(), SituationFeatures(feature_set="trend")
        self.l3_k, self.k, self.out = 4, 0, []

    def reset(self):
        self.engine.reset()

    def decide_batch(self, obs):
        self.a.update(obs)
        self.b.update(obs)
        self.k += 1
        if self.k % 5 == 0:
            self.out.append((self.a.vector(), self.b.vector()))
        return self.engine.step(obs)


@pytest.mark.parametrize("scenario,fading", [("corner_turner", "rayleigh"), ("rush_hour", "off")])
def test_trend_set_extends_v3_set_bit_identically(scenario, fading):
    env = TwinSim(trace_for(scenario, fading, 3, cfg=SHORT), SHORT)
    tap = _Tap()
    env.reset()
    done = False
    while not done:
        _, _, done = env.step(tap)
    assert len(tap.out) > 10
    moved = 0.0
    for a, b in tap.out:
        assert a.shape[1] == N_FEATURES and b.shape[1] == len(FEATURE_NAMES_TREND)
        np.testing.assert_array_equal(a, b[:, :N_FEATURES])
        assert np.isfinite(b).all() and (np.abs(b) <= 3).all()
        moved += float(np.abs(b[:, N_FEATURES:]).sum())
    assert moved > 0                                   # the trend columns are not constant zeros


def test_feature_set_names():
    assert FEATURE_NAMES_TREND[:N_FEATURES] == FEATURE_NAMES
    assert feature_set_of(FEATURE_NAMES) == "v3" and feature_set_of(FEATURE_NAMES_TREND) == "trend"
    with pytest.raises(ValueError):
        feature_set_of(FEATURE_NAMES[:-1])
    with pytest.raises(ValueError):
        SituationFeatures(feature_set="nope")


def test_penalized_rule_scores_and_slack():
    from twin.selector_v3 import score_profiles
    heads = np.array([[[0.0, 1.0, 0.1], [2.0, 1.5, 0.1], [1.0, 3.0, 0.0], [0.5, 0.5, 0.3]]])
    P = lambda **k: {"ho_penalty": 0.0, "fail_penalty": 0.0, "ho_slack": None, "fail_slack": None, **k}
    q, f = score_profiles(heads, "penalized", P())
    np.testing.assert_allclose(q[0], [0.0, 2.0, 1.0, 0.5])          # no penalty, no slack = utility_only
    q, _ = score_profiles(heads, "penalized", P(ho_penalty=1.0))
    np.testing.assert_allclose(q[0], [0.0, 1.5, -1.0, 1.0])          # U - 1*(HO - HO_default)
    q, f = score_profiles(heads, "penalized", P(ho_slack=0.5))
    assert list(f[0]) == [True, True, False, True] and q[0, 2] == -np.inf
    q, f = score_profiles(heads, "penalized", P(fail_slack=0.1))
    assert list(f[0]) == [True, True, True, False]
    q, f = score_profiles(heads, "penalized", P(ho_slack=0.0, fail_slack=0.0))
    assert list(f[0]) == [True, False, False, False] and q[0, 0] == 0.0   # default always feasible


def test_cost_params_validated():
    from twin.selector_v3 import check_cost_params
    ok = {"ho_penalty": 0.0, "fail_penalty": 0.0, "ho_slack": 0.5, "fail_slack": None}
    assert check_cost_params("penalized", ok) == ok
    assert check_cost_params("utility_only", None) is None
    for bad in ({**ok, "ho_penalty": -1.0}, {**ok, "ho_slack": -0.1}, {k: v for k, v in ok.items() if k != "fail_slack"},
                {**ok, "extra": 1}):
        with pytest.raises(ValueError):
            check_cost_params("penalized", bad)
    with pytest.raises(ValueError):
        check_cost_params("utility_only", ok)


def _ck(width, hidden, seed, feature_names=None, rule="utility_only", **extra):
    import torch
    from twin.selector_v3 import PREDICTION_HEADS, build_mlp
    from twin.train_v3 import HEAD_SCALES
    torch.manual_seed(seed)
    net = build_mlp(width, 9, hidden)
    ck = {"arch": "ctx_cho_selector", "profiles": [parse_profile(p) for p in PROFS], "default": 0,
          "x_mean": [0.0] * width, "x_std": [1.0] * width,
          "state_dict": {k: v.detach().numpy() for k, v in net.state_dict().items()},
          "prediction_heads": list(PREDICTION_HEADS), "head_scales": list(HEAD_SCALES), "cost_rule": rule,
          **extra}
    if feature_names is not None:
        ck["feature_names"] = list(feature_names)
    return ck


def test_ensemble_is_the_mean_of_member_outputs_and_any_width_loads():
    from twin.selector_v3 import CHOSelectorPolicy
    a, b = _ck(N_FEATURES, 256, 1), _ck(N_FEATURES, 32, 2)
    b["x_mean"] = [0.5] * N_FEATURES
    ens = dict(a, ensemble=[{"x_mean": b["x_mean"], "x_std": b["x_std"], "state_dict": b["state_dict"]}])
    x = np.random.default_rng(0).standard_normal((7, N_FEATURES))
    pa, pb, pe = (CHOSelectorPolicy(c) for c in (a, b, ens))
    pa.predict(x); ha = pa.last_heads
    pb.predict(x); hb = pb.last_heads
    pe.predict(x)
    np.testing.assert_allclose(pe.last_heads, (ha + hb) / 2, rtol=1e-12, atol=1e-12)


def test_trend_checkpoint_drives_trend_features_in_closed_loop():
    from twin.selector_v3 import CHOSelectorPolicy
    w = len(FEATURE_NAMES_TREND)
    p = CHOSelectorPolicy(_ck(w, 64, 3, FEATURE_NAMES_TREND, warm_s=2.0, period_s=2.0))
    assert p.feature_set == "trend" and p.feat.feature_set == "trend"
    env = TwinSim(trace_for("corner_turner", "rician", 5, cfg=SHORT), SHORT)
    env.reset()
    done = False
    while not done:
        _, _, done = env.step(p)
    assert p.feat.vector().shape[1] == w
    with pytest.raises(ValueError):                    # v3-width weights under trend names
        CHOSelectorPolicy(_ck(N_FEATURES, 64, 3, FEATURE_NAMES_TREND)).predict(np.zeros((1, w)))


def test_trainer_saves_matching_feature_names():
    import tempfile
    import torch
    from twin.train_v3 import fit, save_checkpoint
    from twin.selector_v3 import load_selector
    rng = np.random.default_rng(0)
    for width, names in ((N_FEATURES, FEATURE_NAMES), (len(FEATURE_NAMES_TREND), FEATURE_NAMES_TREND)):
        X = rng.standard_normal((64, width)).astype(np.float32)
        Y = rng.standard_normal((64, 3, 3)).astype(np.float32)
        state, norm = fit(X, Y, np.ones(64, np.float32), epochs=1, hidden=16)
        with tempfile.TemporaryDirectory() as d:
            p = save_checkpoint("v0.0.1", state, norm, [parse_profile(x) for x in PROFS],
                                {"prediction_heads": ["utility_delta", "ho_rate", "fail_rate"],
                                 "head_scales": [1.0, 1.0, 5.0], "cost_rule": "utility_only", "hidden": 16}, root=d)
            ck = torch.load(p, map_location="cpu", weights_only=True)
            assert list(ck["feature_names"]) == list(names)
            assert load_selector(p).feature_set == ("v3" if width == N_FEATURES else "trend")


def test_float32_targets_bit_identical_to_the_v313_float64_path():
    from twin.train_v3 import HEAD_SCALES, Y_CLIP, prepare_targets
    rng = np.random.default_rng(5)
    Y = (rng.standard_normal((500, 7, 3)) * np.array([6.0, 3.0, 0.4])).astype(np.float32)
    for sign in (1.0, -1.0):
        ref = Y.astype(np.float64).copy()
        ref[:, :, 0] = np.clip(ref[:, :, 0], -Y_CLIP, Y_CLIP)
        ref *= np.asarray(HEAD_SCALES, float)[None, None, :]
        ref = (sign * ref.reshape(len(ref), -1)).astype(np.float32)
        got = prepare_targets(Y, sign)
        assert got.dtype == np.float32
        np.testing.assert_array_equal(got, ref)


def test_min_dwell_holds_a_new_profile_but_never_an_infeasible_one():
    from twin.selector_v3 import CHOSelectorPolicy
    U0 = np.array([0.0, 2.0, 1.0]); HO0 = np.array([1.0, 0.5, 3.0]); F0 = np.array([0.1, 0.5, 0.05])
    ck = _ck(N_FEATURES, 8, 0, warm_s=2.0, period_s=2.0, min_dwell_s=10.0)
    from twin.train_v3 import HEAD_SCALES
    ck["state_dict"]["4.weight"][:] = 0.0
    ck["state_dict"]["4.bias"][:] = (np.stack([U0, HO0, F0], 1) * np.asarray(HEAD_SCALES)).reshape(-1)
    SH = SimConfig(duration_s=40.0)
    c = CHOSelectorPolicy(ck)
    env = TwinSim(trace_for("rush_hour", "rayleigh", 7, cfg=SH), SH)
    env.reset()
    for _ in range(30):                                # past warm-up: profile 1 adopted at t ~ 2-3 s
        env.step(c)
    assert (c.engine.current == 1).all()
    b = c.net.b[2].copy()
    c.net.b[2][:] = (np.stack([[0.0, 1.0, 2.0], HO0, F0], 1) * np.asarray(HEAD_SCALES)).reshape(-1)
    for _ in range(40):                                # 4 s later: profile 2 now best, but dwell holds 1
        env.step(c)
    assert (c.engine.current == 1).all()
    for _ in range(80):                                # after 10 s the switch happens
        env.step(c)
    assert (c.engine.current == 2).all()
    c.net.b[2][:] = b                                  # back to the first predictions: 1 best again
    c.cost_rule, c.cost_params = "penalized", {"ho_penalty": 0.0, "fail_penalty": 0.0,
                                               "ho_slack": None, "fail_slack": 0.0}
    for _ in range(25):                                # profile 2 is held by dwell but not infeasible...
        env.step(c)
    assert (c.engine.current == 2).all()
    c.cost_params = {"ho_penalty": 0.0, "fail_penalty": 0.0, "ho_slack": 0.0, "fail_slack": None}
    for _ in range(25):                                # ...now it is infeasible (HO 3 > 1): left at once
        env.step(c)
    assert (c.engine.current != 2).all()


# ---------------------------------------------------------------- v3.14 pre-registration plumbing
PIPE = Path(__file__).resolve().parents[1]


def test_v314_plan_is_consistent():
    import json
    from twin.selector_v3 import check_cost_params
    from twin.train_v314 import load_plan, seed_range
    p = load_plan(PIPE / "finals_preregistration_v3_14.json")
    assert p["held_out_seeds"] == [2200, 2259] and (PIPE.parent / p["rules_from"]).exists()
    for name, cfg in p["candidate_family"]["decision_configs"].items():
        check_cost_params(cfg["cost_rule"], cfg["cost_params"])
    assert list(p["candidate_family"]["decision_configs"]) == ["B04", "B03", "B02", "A"]
    assert len(seed_range(p["central"]["fit_seeds"])) == 200
    a = json.loads((PIPE / "gate_config_finals.json").read_text(encoding="utf-8"))
    b = json.loads((PIPE / "gate_config_finals_replicate_1300.json").read_text(encoding="utf-8"))
    assert sorted(k for k in a if a[k] != b.get(k)) == ["_comment", "seeds"] and b["seeds"] == [1300, 1301, 1302]


def test_v314_candidate_numbering():
    from twin.run_v314 import candidates
    c = candidates()
    assert len(c) == 16 and len({v for v, _, _ in c}) == 16
    assert c[0] == ("v3.14.20", "B04", 0) and c[5] == ("v3.14.25", "B03", 1) and c[-1] == ("v3.14.35", "A", 3)


def test_v314_buffer_check():
    from twin.evaluate_v3 import DEPLOYABLE
    from twin.run_v314 import buffer_check
    rule = {"guardrails": [{"metric": "ho_rate", "rel_margin": 0.1, "abs_margin": 0.05}]}

    def st(cell_diff, ci_high):
        return {"pooled": {"ho_rate": {r: (3.0, 0, 0) for r in DEPLOYABLE}},
                "comparisons": {r: {"ho_rate": {"pooled": {"ci_high": ci_high},
                                                "cells": {"a/off": {"diff": cell_diff}, "b/off": {"diff": 0.0}}}}
                                for r in DEPLOYABLE}}
    assert buffer_check(st(0.24, 0.1), rule)[0]                 # 0.24 <= 0.8 * 0.3
    ok, worst = buffer_check(st(0.25, 0.1), rule)
    assert not ok and worst[0]["where"] == "a/off"
    assert not buffer_check(st(0.0, 0.241), rule)[0]


def test_final_run_bound_to_v314_held_out_seeds():
    from twin.evaluate_v3 import main
    plan = PIPE / "finals_preregistration_v3_14.json"
    with pytest.raises(SystemExit, match="2200..2259"):
        main(["--v3", "v0.0.0", "--seed0", "2200", "--seeds", "20", "--final", "--prereg", str(plan)])


def test_v315_plan_binds_the_frozen_a_candidate_and_its_seeds():
    import hashlib
    import json
    from twin.evaluate_v3 import main
    plan = PIPE / "finals_preregistration_v3_15.json"
    p = json.loads(plan.read_text(encoding="utf-8"))
    assert p["held_out_seeds"] == [2300, 2359] and p["candidate"]["version"] == "v3.14.32"
    w = PIPE.parent / p["candidate"]["weights"]
    assert hashlib.sha256(w.read_bytes()).hexdigest() == p["candidate"]["weights_sha256"]
    with pytest.raises(SystemExit, match="2300..2359"):
        main(["--v3", "v3.14.32", "--seed0", "2200", "--seeds", "60", "--final", "--prereg", str(plan)])
