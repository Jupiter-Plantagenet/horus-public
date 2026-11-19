"""Radio maps: cell sites + RSRP(x, y) per cell.

v0 ships the `placeholder` map: 7 sites on a deterministic layout over a
1 km x 1 km campus, log-distance path loss (3GPP UMa-flavoured constants)
plus seeded log-normal shadowing. #6 swaps in `opencellid` (real Kumoh/Gumi
site geometry) and `measured` (walk-test calibrated) behind the same
interface; the twin env and controllers never know which map they run on.
"""

import math
import random
from dataclasses import dataclass
from pathlib import Path

# Log-distance path loss: PL(d) = A + B*log10(d_km). UMa-ish defaults; per-cell
# overrides land with the measured map (#6 v1 fits these to the walk-test).
PL_A = 128.1
PL_B = 37.6
TX_POWER_DBM = 43.0          # TOTAL carrier TX power (all REs), macro ballpark
# NOTE (finals, twin v2): RadioMap.rsrp_dbm below is the LEGACY quantity —
# tx_power_dbm - PL, i.e. computed from TOTAL power, ~35 dB hotter than a real
# per-RE RSRP (TS 38.215). It stays as-is so the v1.x evidence reproduces.
# Twin v2 (phy.py) consumes the same Cell objects and reports per-RE RSRP =
# tx_power_dbm - 10*log10(12*N_PRB) - PL + shadow; a measured map whose cells
# are fitted to real walk-test RSRP should keep tx_power_dbm as TOTAL power
# (or set it = fitted_rsrp_ref + per_re_offset_db) so v2 output is real dBm.
SHADOW_SIGMA_DB = 6.0        # log-normal shadowing
NOISE_FLOOR_DBM = -120.0     # clamp: below this a cell is effectively unhearable
FADING_MODES = ("off", "rayleigh", "rician")
FADING_TILE_M = 2.0          # spatial bin of the legacy i.i.d. fading key. NOT a
                             # decorrelation distance: the draw also keys on the
                             # step t, so every 1 s step is independent regardless
                             # of motion (a stationary UE gets a fresh fade each
                             # step). Time-correlated (Jakes/Doppler) fading lives
                             # in phy.py (twin v2).
RICIAN_K_DB = 6.0            # LoS/NLoS power ratio for the rician mode
MIN_DIST_M = 10.0            # avoid log(0) at the mast foot

# Single source of truth for RSRP normalization — the DQN features, the
# training reward, and the gate's coverage term must all scale identically,
# and must all move together when #6 changes the realistic range.
RSRP_NORM_LO, RSRP_NORM_HI = -120.0, -40.0


def normalize_rsrp(dbm):
    """RSRP -> [0, 1] over the map's realistic range."""
    return (min(max(dbm, RSRP_NORM_LO), RSRP_NORM_HI) - RSRP_NORM_LO) / (RSRP_NORM_HI - RSRP_NORM_LO)


@dataclass(frozen=True)
class Cell:
    cell_id: str
    x: float
    y: float
    tx_power_dbm: float = TX_POWER_DBM
    pl_a: float = PL_A
    pl_b: float = PL_B


class RadioMap:
    """RSRP per cell at a position. Shadowing is deterministic per (cell, grid
    tile, seed): the same UE spot always sees the same shadow — spatially
    consistent enough for A3/TTT dynamics without a correlated-fading model
    (that fidelity is the #16 stretch)."""

    SHADOW_TILE_M = 25.0  # shadowing decorrelation distance

    def __init__(self, cells, seed, shadow_sigma_db=SHADOW_SIGMA_DB, fading="off"):
        if fading not in FADING_MODES:
            raise ValueError(f"unknown fading mode {fading!r}; expected one of {FADING_MODES}")
        self.cells = list(cells)
        self._seed = seed
        self._sigma = shadow_sigma_db
        self.fading = fading

    def _shadow_db(self, cell, x, y):
        tile = f"{self._seed}|{cell.cell_id}|{int(x // self.SHADOW_TILE_M)}|{int(y // self.SHADOW_TILE_M)}"
        rng = random.Random(tile)
        return rng.gauss(0.0, self._sigma)

    def _fading_db(self, cell, x, y, t):
        """Small-scale fading on top of shadowing (#16). Parametric, NOT ray-traced:
        Rayleigh (no line of sight) or Rician (K = RICIAN_K_DB) power gain with unit
        mean power, drawn independently per (cell, FADING_TILE_M tile, step t) —
        i.i.d. in time at the 1 s step, unfiltered (legacy; see phy.py for the
        Doppler-correlated v2 model).
        Deterministic in (seed, cell, tile, t), so same seed -> same episode. With
        t=None (callers that don't track time) the draw is spatial only."""
        if self.fading == "off":
            return 0.0
        key = f"{self._seed}|fade|{cell.cell_id}|{int(x // FADING_TILE_M)}|{int(y // FADING_TILE_M)}|{t}"
        rng = random.Random(key)
        if self.fading == "rayleigh":
            power = -math.log(1.0 - rng.random())          # |h|^2 ~ Exp(1)
        else:
            k = 10.0 ** (RICIAN_K_DB / 10.0)
            sd = math.sqrt(1.0 / (2.0 * (k + 1.0)))
            re = math.sqrt(k / (k + 1.0)) + rng.gauss(0.0, sd)
            power = re * re + rng.gauss(0.0, sd) ** 2
        return 10.0 * math.log10(max(power, 1e-6))

    def rsrp_dbm(self, cell, x, y, t=None):
        d_m = max(math.hypot(x - cell.x, y - cell.y), MIN_DIST_M)
        pl = cell.pl_a + cell.pl_b * math.log10(d_m / 1000.0)
        rsrp = cell.tx_power_dbm - pl + self._shadow_db(cell, x, y) + self._fading_db(cell, x, y, t)
        return max(rsrp, NOISE_FLOOR_DBM)

    def measure(self, x, y, t=None):
        """{cell_id: rsrp_dbm} at (x, y) — one 'measurement report'. `t` is the
        env step; it only matters when fading is on."""
        return {c.cell_id: self.rsrp_dbm(c, x, y, t) for c in self.cells}


def placeholder_map(seed, fading="off"):
    """7 cells: hex-ish ring + centre over a 1 km campus square. Fixed layout
    (not seeded) so scenario geometry is stable across seeds; the seed drives
    shadowing only."""
    ring = [
        ("cell-1", 500.0, 500.0),
        ("cell-2", 200.0, 250.0),
        ("cell-3", 800.0, 250.0),
        ("cell-4", 950.0, 500.0),
        ("cell-5", 800.0, 750.0),
        ("cell-6", 200.0, 750.0),
        ("cell-7", 50.0, 500.0),
    ]
    return RadioMap([Cell(cid, x, y) for cid, x, y in ring], seed, fading=fading)


def opencellid_map(seed, k=9, fading="off"):
    """#6 v0: real Kumoh/Gumi cell-site geometry from OpenCellID (MCC 450,
    LTE, clustered to physical towers — see data/opencellid/build_sites.py).
    The K sites nearest the campus centre are placed in the scenario frame
    (campus centre -> (500, 500)); path-loss/shadowing constants stay the
    calibrated-urban defaults until the walk-test fit lands (#6 v1,
    `measured`). K=9 keeps the DQN action space tractable (stay + 9)."""
    import json
    data_file = Path(__file__).resolve().parents[2] / "data" / "opencellid" / "kumoh-cells.json"
    data = json.loads(data_file.read_text(encoding="utf-8"))
    sites = sorted(data["sites"], key=lambda s: math.hypot(s["x_m"], s["y_m"]))[:k]
    cells = [Cell(s["site_id"], s["x_m"] + 500.0, s["y_m"] + 500.0) for s in sites]
    return RadioMap(cells, seed, fading=fading)


MEASURED_FIT_FILE = Path(__file__).resolve().parents[2] / "data" / "walktest" / "radio-fit.json"


def measured_map(seed, k=9, fit_file=None, fading="off"):
    """Compatibility entry point for the provenance-checked fitted map."""
    from .measured_map import measured_map as load_measured
    return load_measured(seed, k=k, fit_file=fit_file, fading=fading)


def load_radio_map(name, seed, fading="off"):
    if name == "placeholder":
        return placeholder_map(seed, fading)
    if name == "opencellid":
        return opencellid_map(seed, fading=fading)
    if name.startswith("campus:"):
        # any-campus twin (pipeline/campus): OpenCellID sites of a registered
        # campus, same Cell/RadioMap physics — layered on top, not forked.
        from campus.world import campus_radio_map
        return campus_radio_map(name.split(":", 1)[1], seed, fading=fading)
    if name == "measured":
        return measured_map(seed, fading=fading)
    raise ValueError(f"unknown radio map: {name}")
