"""`--radio-map measured` (#6 v1): the OpenCellID twin, calibrated by the walk-test.

Same cell set as `opencellid_map` - the K frozen sites nearest the campus
centre, same IDs, same order - so a policy trained on `opencellid` evaluates on
`measured` without KeyErrors. Only the radio parameters change:

  * a site fitted from the walk-test gets its own RSRP-at-1-km and slope
  * every other site gets the CAMPUS-level fit (never the raw v0 constants:
    v0 is ~30 dB too hot vs per-RE RSRP, so a v0 site would win every attach)
  * shadowing sigma = the large-scale (25 m tile) part of the fitted residual,
    excluding within-tile fading (the #16 fading layer adds that separately)

The fit file stores RSRP at 1 km (dBm, a real per-RE quantity: what a UE
reports) + slope, not pl_a. pl_a is derived here for TWIN V2's radio:
phy.py reports per-RE RSRP = tx_power_dbm - 10*log10(12*N_PRB) - PL + shadow,
so pl_a = tx_power_dbm - per_re_offset_db - rsrp_1km and v2 reproduces the
measured level exactly. (The legacy v1 RadioMap.rsrp_dbm, which has no per-RE
term, then reads per_re_offset_db (~35 dB) hotter on this map — the same
"total-power" units as on every other v1 map, i.e. what the v1.x checkpoints
were trained on. Before the twin-v2 port the measured map was the one v1 map
in per-RE units, a ~35 dB input shift for v1.3.1.)

Shadowing: twin v2 draws a continuous field with PhyConfig.shadow_sigma_db;
the map publishes the fitted sigma as phy_overrides, which sim.make_trace
applies. The v1 path keeps scaling the base map's 25 m tile draw.

No silent fallback: without data/walktest/radio-fit.json this raises. A fit
marked synthetic is refused unless explicitly requested (HORUS_RADIO_FIT=<file>
or fit_file=...), so a rehearsal can never pose as the campus map.
"""

import json
import os
from dataclasses import replace
from pathlib import Path

from .radio import SHADOW_SIGMA_DB, RadioMap, opencellid_map


def _per_re_offset_db():
    from .phy import PhyConfig
    return PhyConfig().per_re_offset_db

MEASURED_FIT_FILE = Path(__file__).resolve().parents[2] / "data" / "walktest" / "radio-fit.json"
FIT_SCHEMA = "horus-radio-fit/2"


class MeasuredRadioMap(RadioMap):
    """RadioMap with a fitted shadowing sigma (scales the base map's N(0, 6 dB)
    tile draw, so the spatial structure/determinism is the base map's)."""

    def __init__(self, cells, seed, shadow_sigma_db, fading="off"):
        super().__init__(cells, seed, fading=fading)
        self.shadow_sigma_db = float(shadow_sigma_db)
        # twin v2 (sim.make_trace) applies these to the episode's PhyConfig
        self.phy_overrides = {"shadow_sigma_db": self.shadow_sigma_db}

    def _shadow_db(self, cell, x, y):
        return super()._shadow_db(cell, x, y) * (self.shadow_sigma_db / SHADOW_SIGMA_DB)


def load_fit(fit_file=None):
    explicit = fit_file or os.environ.get("HORUS_RADIO_FIT")
    path = Path(explicit) if explicit else MEASURED_FIT_FILE
    if not path.exists():
        raise FileNotFoundError(
            f"--radio-map measured needs {path}: produce it from the campus walk-test (#5) with "
            "`python -m twin.walktest_pipeline ../data/walktest/<logs>.txt` "
            "(or use --radio-map opencellid)")
    fit = json.loads(path.read_text(encoding="utf-8"))
    if fit.get("schema") != FIT_SCHEMA:
        raise ValueError(f"{path}: schema {fit.get('schema')!r}, expected {FIT_SCHEMA!r} - rerun the pipeline")
    if fit.get("synthetic") and not explicit:
        raise ValueError(f"{path} is a SYNTHETIC rehearsal fit; refusing to use it as the campus map")
    return fit


def measured_map(seed, k=9, fit_file=None, fading="off"):
    fit = load_fit(fit_file)
    base = opencellid_map(seed, k=k)
    campus = fit["campus"]
    off = _per_re_offset_db()
    cells = []
    for c in base.cells:
        p = fit["sites"].get(c.cell_id, campus)
        cells.append(replace(c, pl_a=c.tx_power_dbm - off - p["rsrp_1km_dbm"], pl_b=p["slope_db_per_decade"]))
    return MeasuredRadioMap(cells, seed, fit["shadow_sigma_db"], fading=fading)
