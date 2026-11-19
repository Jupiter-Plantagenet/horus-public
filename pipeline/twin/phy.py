"""PHY v2: per-RE RSRP, correlated shadowing, Doppler-correlated fading, SINR.

The legacy twin (radio.py RadioMap.rsrp_dbm) computes RSRP from TOTAL carrier
TX power (43 dBm), which puts every RSRP ~31-35 dB too hot (serving peaks near
-3 dBm, means around -45 dBm) — no real UE reports that. RSRP is defined per
resource element (TS 38.215 §5.1.1), so this module subtracts 10*log10(N_RE)
with N_RE = 12 * N_PRB from the configured numerology. Measured maps (#5/#6
walk-test, real per-RE dBm) are therefore directly comparable to this output.

What is modelled (all vectorized over UEs x cells, deterministic per seed):

- path loss: the map's per-cell log-distance law (radio.Cell.pl_a / pl_b),
  unchanged — the map owns geometry and path loss, this module owns the PHY.
- shadowing: a spatially CONTINUOUS log-normal field per cell (iid grid at the
  decorrelation distance, bilinear-interpolated, variance-renormalized) — the
  legacy 25 m tiles had 6 dB step discontinuities that triggered handovers.
- small-scale fading (off | rayleigh | rician): complex Gaussian AR(1) per
  (UE, cell) whose correlation follows Jakes, rho = J0(2*pi*f_D*tau), with
  f_D = max(v/lambda, min_doppler_hz). A stationary UE therefore sees SLOW,
  correlated fading (environment motion only); a cyclist sees fast fading
  that the L1 measurement averages down. Each env step averages `l1_samples`
  sub-samples — the L1 RSRP averaging a real UE performs inside a measurement
  period. (The PR #34 layer drew i.i.d. per 1 s step per 2 m tile; that is
  inert for stationary UEs' time correlation and wrong for moving ones.)
- interference & noise: RS-SINR of the serving cell = S / (load * sum_j I_j + N),
  thermal noise per RE = -174 + 10log10(SCS) + NF. `load` is the interferer
  RE activity factor (fraction of neighbour REs carrying energy).

Not modelled (say so on slides): ray tracing, cross-cell shadowing correlation,
sectorization/beamforming, UL. Numbers are a calibrated parametric model.
"""

import math
from dataclasses import dataclass, field, replace

import numpy as np

FADING_MODES = ("off", "rayleigh", "rician")
SE_CAP = 7.4                 # bps/Hz, 256-QAM ceiling
SHANNON_ALPHA = 0.6          # TR 36.942 A.1 attenuated Shannon
SINR_MIN_DB = -10.0          # below this: zero throughput (TR 36.942)


@dataclass(frozen=True)
class PhyConfig:
    fc_ghz: float = 3.5              # n78, the Korean 5G campus band
    scs_khz: float = 30.0
    n_prb: int = 273                 # 100 MHz @ 30 kHz SCS
    noise_figure_db: float = 7.0
    load: float = 0.5                # interferer RE activity factor
    shadow_sigma_db: float = 6.0
    shadow_decorr_m: float = 25.0
    min_dist_m: float = 10.0
    fading: str = "off"
    rician_k_db: float = 6.0
    min_doppler_hz: float = 2.0      # scatterer motion: a static UE still fades slowly
    l1_samples: int = 5              # L1 sub-samples averaged per env step
    diversity: int = 2               # independent fading branches combined (Rx antennas x
                                     # coherence bands inside the SSB measurement bandwidth)
    meas_err_db: float = 0.0         # optional L1 measurement error (std, dB)

    def __post_init__(self):
        if self.fading not in FADING_MODES:
            raise ValueError(f"unknown fading mode {self.fading!r}; expected one of {FADING_MODES}")

    @property
    def n_re(self):
        return 12 * self.n_prb

    @property
    def per_re_offset_db(self):
        """Total carrier power -> per-RE power: 10*log10(12*N_PRB)."""
        return 10.0 * math.log10(self.n_re)

    @property
    def noise_per_re_dbm(self):
        return -174.0 + 10.0 * math.log10(self.scs_khz * 1e3) + self.noise_figure_db

    @property
    def bandwidth_mhz(self):
        return self.n_prb * 12 * self.scs_khz / 1e3

    @property
    def wavelength_m(self):
        return 0.299792458 / self.fc_ghz


def bessel_j0(x):
    """J0 via its integral form (vectorized, |err| < 1e-9 for |x| < 60)."""
    x = np.asarray(x, dtype=float)
    theta = (np.arange(64) + 0.5) * (math.pi / 64)
    return np.cos(np.multiply.outer(x, np.sin(theta))).mean(axis=-1)


def shannon_se(sinr_db):
    """Attenuated-Shannon spectral efficiency (bps/Hz), TR 36.942 A.1 style."""
    sinr_db = np.asarray(sinr_db, dtype=float)
    se = SHANNON_ALPHA * np.log2(1.0 + 10.0 ** (sinr_db / 10.0))
    se = np.minimum(se, SE_CAP)
    return np.where(sinr_db < SINR_MIN_DB, 0.0, se)


class ShadowField:
    """Continuous log-normal shadowing per cell: iid N(0, sigma^2) on a grid
    with spacing = decorrelation distance, bilinear interpolation, divided by
    sqrt(sum w^2) so the marginal std is sigma everywhere (not just at nodes)."""

    def __init__(self, n_cells, rng, sigma_db, spacing_m, lo=-300.0, hi=1300.0):
        self.spacing = spacing_m
        self.lo = lo
        n = int(math.ceil((hi - lo) / spacing_m)) + 2
        self.n = n
        self.grid = rng.standard_normal((n_cells, n, n)) * sigma_db

    def __call__(self, xy):
        g = (np.clip(xy, self.lo, self.lo + (self.n - 2) * self.spacing) - self.lo) / self.spacing
        i0 = np.minimum(np.floor(g).astype(int), self.n - 2)
        f = g - i0
        fx, fy = f[:, 0], f[:, 1]
        ix, iy = i0[:, 0], i0[:, 1]
        w = np.stack([(1 - fx) * (1 - fy), fx * (1 - fy), (1 - fx) * fy, fx * fy], 1)   # (N,4)
        vals = np.stack([self.grid[:, ix, iy], self.grid[:, ix + 1, iy],
                         self.grid[:, ix, iy + 1], self.grid[:, ix + 1, iy + 1]], -1)  # (C,N,4)
        out = (vals * w[None]).sum(-1) / np.sqrt((w ** 2).sum(1))[None]
        return out.T                                                                   # (N,C)


class PhyModel:
    """Per-episode PHY state over a fixed cell list (radio.Cell objects)."""

    def __init__(self, cells, seed, cfg=None, shadow_extent=None):
        """shadow_extent=(lo, hi) metres: the square the shadowing field spans
        (default -300..1300, the 1 km opencellid frame + margin — unchanged so
        the finals traces reproduce). Campus maps (centred frames up to ~3 km)
        pass their own; outside the extent the field is clamped (constant)."""
        self.cfg = cfg or PhyConfig()
        self.cells = list(cells)
        self.cell_ids = [c.cell_id for c in self.cells]
        c = self.cfg
        ss = np.random.SeedSequence([int(seed) & 0xFFFFFFFF, 0x5AD0])
        lo, hi = shadow_extent or (-300.0, 1300.0)
        self.shadow = ShadowField(len(self.cells), np.random.default_rng(ss),
                                  c.shadow_sigma_db, c.shadow_decorr_m, lo, hi)
        self._fade_rng = np.random.default_rng(np.random.SeedSequence([int(seed) & 0xFFFFFFFF, 0xFADE]))
        self._err_rng = np.random.default_rng(np.random.SeedSequence([int(seed) & 0xFFFFFFFF, 0xE44]))
        self._cxy = np.array([[cl.x, cl.y] for cl in self.cells], dtype=float)
        self._pl_a = np.array([cl.pl_a for cl in self.cells], dtype=float)
        self._pl_b = np.array([cl.pl_b for cl in self.cells], dtype=float)
        self._tx = np.array([cl.tx_power_dbm for cl in self.cells], dtype=float)
        self.active = np.ones(len(self.cells), dtype=bool)
        self._h = None          # (N,C,D) complex scattered component
        self._los_phase = None
        self._rho_key = None

    # -- map surgery (cell_outage) -------------------------------------------------
    def silence(self, cell_idx):
        self.active[cell_idx] = False

    # -- large scale -----------------------------------------------------------------
    def mean_rsrp_dbm(self, xy):
        """Per-RE RSRP without small-scale fading, (N,C) dBm."""
        d = np.maximum(np.hypot(xy[:, None, 0] - self._cxy[None, :, 0],
                                xy[:, None, 1] - self._cxy[None, :, 1]), self.cfg.min_dist_m)
        pl = self._pl_a[None] + self._pl_b[None] * np.log10(d / 1000.0)
        return self._tx[None] - self.cfg.per_re_offset_db - pl + self.shadow(xy)

    # -- small scale ------------------------------------------------------------------
    def fading_gain(self, speeds, dt):
        """Linear power gain (N,C), unit mean, averaged over l1_samples
        sub-samples of an AR(1) Jakes-correlated complex channel."""
        c = self.cfg
        n, m = len(speeds), len(self.cells)
        if c.fading == "off":
            return np.ones((n, m))
        rng = self._fade_rng
        shape = (n, m, c.diversity)
        if self._h is None:
            self._h = (rng.standard_normal(shape) + 1j * rng.standard_normal(shape)) / math.sqrt(2)
            self._los_phase = rng.uniform(0, 2 * math.pi, shape)
        speeds = np.asarray(speeds, float)
        key = (speeds.tobytes(), dt)
        if self._rho_key != key:                      # speeds rarely change: cache J0
            fd = np.maximum(speeds / c.wavelength_m, c.min_doppler_hz)                  # (N,)
            rho = np.clip(bessel_j0(2 * math.pi * fd * dt / c.l1_samples), 0.0, 1.0)
            self._rho = rho[:, None, None]                                              # (N,1,1)
            self._innov = np.sqrt(1.0 - self._rho ** 2) / math.sqrt(2)
            self._rho_key = key
        rho, innov = self._rho, self._innov
        acc = np.zeros(shape)
        if c.fading == "rician":
            k = 10.0 ** (c.rician_k_db / 10.0)
            los = math.sqrt(k / (k + 1.0)) * np.exp(1j * self._los_phase)
            nlos_w = math.sqrt(1.0 / (k + 1.0))
        z = rng.standard_normal((c.l1_samples, 2) + shape)
        for s in range(c.l1_samples):
            self._h = rho * self._h + innov * (z[s, 0] + 1j * z[s, 1])
            hh = self._h if c.fading == "rayleigh" else los + nlos_w * self._h
            acc += np.abs(hh) ** 2
        return acc.mean(-1) / c.l1_samples

    # -- one step ---------------------------------------------------------------------
    def step(self, xy, speeds, dt):
        """Returns (rsrp_l1_dbm (N,C), rx_mw (N,C)). rx_mw is the true per-RE
        received power used for SINR; rsrp_l1 is what the UE reports (adds the
        optional measurement error). Silenced cells read at the RSRP floor."""
        mean_db = self.mean_rsrp_dbm(xy)
        rx_db = mean_db + 10.0 * np.log10(np.maximum(self.fading_gain(speeds, dt), 1e-6))
        rx_mw = np.where(self.active[None], 10.0 ** (rx_db / 10.0), 0.0)
        meas = rx_db
        if self.cfg.meas_err_db > 0:
            meas = meas + self._err_rng.standard_normal(meas.shape) * self.cfg.meas_err_db
        meas = np.where(self.active[None], np.maximum(meas, RSRP_FLOOR_DBM), RSRP_FLOOR_DBM)
        return meas, rx_mw

    def sinr_db(self, rx_mw, serving):
        """RS-SINR (dB) of cell `serving[i]` for each UE i; serving may be any
        candidate column (used for HO target checks too)."""
        idx = np.arange(rx_mw.shape[0])
        s = rx_mw[idx, serving]
        i = self.cfg.load * (rx_mw.sum(1) - s)
        n = 10.0 ** (self.cfg.noise_per_re_dbm / 10.0)
        return 10.0 * np.log10(np.maximum(s, 1e-30) / (i + n))


RSRP_FLOOR_DBM = -156.0      # bottom of the TS 38.133 RSRP report range
# Normalization range for v2 features (per-RE RSRP actually seen on campus).
RSRP_V2_LO, RSRP_V2_HI = -130.0, -50.0


def normalize_rsrp_v2(dbm):
    return (np.clip(dbm, RSRP_V2_LO, RSRP_V2_HI) - RSRP_V2_LO) / (RSRP_V2_HI - RSRP_V2_LO)


def config_with(**overrides):
    return replace(PhyConfig(), **overrides)
