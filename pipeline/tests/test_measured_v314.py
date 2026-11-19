"""Measured-route transfer harness (twin.measured_v314)."""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from twin.measured_v314 import faded, verdict  # noqa: E402
from twin.sim import RadioTrace  # noqa: E402

PIPE = Path(__file__).resolve().parents[1]


def _trace(T=400, C=3):
    l1 = np.tile(np.array([-80.0, -85.0, -90.0])[:C], (T, 1, 1)).reshape(T, 1, C)
    return RadioTrace(l1, 10 ** (l1 / 10), np.full((T, 1), 1.4), np.ones(C, bool), list("abc")[:C], ["w"], None, 0.5, 1e-12)


def test_off_is_the_mean_surface_and_fading_is_seeded_unit_mean():
    tr = _trace()
    assert faded(tr, "off", 1, 0.1) is tr
    a, b, c = faded(tr, "rayleigh", 1, 0.1), faded(tr, "rayleigh", 1, 0.1), faded(tr, "rayleigh", 2, 0.1)
    np.testing.assert_array_equal(a.l1, b.l1)
    assert not np.array_equal(a.l1, c.l1)
    g = 10 ** ((a.l1 - tr.l1) / 10)
    assert 0.7 < g.mean() < 1.3 and a.l1.shape == tr.l1.shape
    np.testing.assert_allclose(a.rx, 10 ** (a.l1 / 10))


def _rows(diff_u, diff_ho=0.0, n=30):
    rng = np.random.default_rng(0)
    rows = []
    for md in ("rician", "rayleigh"):
        for s in range(n):
            base = 12.0 + rng.normal(0, 0.2)
            for arm, u, ho in (("v3", base + diff_u + rng.normal(0, 0.01), 1.0 + diff_ho), ("cho_global", base, 1.0)):
                rows.append({"arm": arm, "fading": md, "seed": s, "utility": u, "ho_rate": ho,
                             "fail_rate": 0.0, "rlf_rate": 0.0, "pp_rate": 0.0})
    return rows


def test_superiority_and_non_inferiority_rules():
    pr = json.loads((PIPE / "finals_preregistration_v3.json").read_text(encoding="utf-8"))
    v = verdict(_rows(+0.05), pr, refs=("cho_global",), ni_rel=0.01)
    assert v["pass"] and v["non_inferiority_pass"]
    v = verdict(_rows(-0.05), pr, refs=("cho_global",), ni_rel=0.01)      # -0.05 > -0.12: NI only
    assert not v["pass"] and v["non_inferiority_pass"]
    v = verdict(_rows(-0.30), pr, refs=("cho_global",), ni_rel=0.01)
    assert not v["non_inferiority_pass"]
    v = verdict(_rows(+0.05, diff_ho=0.2), pr, refs=("cho_global",), ni_rel=0.01)   # HO guardrail breaks both
    assert not v["pass"] and not v["non_inferiority_pass"]
