"""A registered campus as a twin world: frame, radio map, OSM-path scenarios.

Everything here plugs into the existing twin through two name hooks, so the
env/controllers/gate never learn they are on a different campus:

    radio map  "campus:<id>"        -> campus_radio_map(id, seed)
    scenario   "<kind>@<id>"        -> campus_scenario(name)
               kinds: commute | shuttle | dwell   (+ cell_outage@<id> in the gate)

Frame: campus-local metres, origin at the bbox centre, x east / y north —
exactly data/opencellid/build_sites.py's projection (local_xy), so site
x_m/y_m from cluster_sites() are already in the twin frame.

Physics is the twin's: same Cell / RadioMap path loss + seeded shadowing.
CampusRadioMap only memoizes the per-(seed, cell, tile) shadow draw (the
value is bit-identical to RadioMap._shadow_db; it just stops re-seeding a
Random per cell per report, which dominates runtime on 20-30-site maps).
"""

import functools
import importlib.util
import json
import math
from pathlib import Path

from twin.radio import TX_POWER_DBM, Cell, RadioMap
from twin.scenarios import UE, Scenario

from .osm import PathGraph

REPO = Path(__file__).resolve().parents[2]
CAMPUS_DATA = REPO / "data" / "campuses"
SITE_MARGIN_M = 300.0     # towers this far outside the fence still enter the twin
# RSRP: cells carry TOTAL carrier power (radio.TX_POWER_DBM, 43 dBm) like every
# other twin map; twin v2 (phy.py) converts to per-RE RSRP (-10*log10(12*N_PRB),
# n78 100 MHz) and computes SINR with interference. (The old-twin campus code
# used a hand-rolled CAMPUS_RS_POWER_DBM ~12 dBm on the v1 RadioMap; removed
# with the twin-v2 port — see working/evidence/campus-v1-superseded/.)
SHADOW_MARGIN_M = 150.0   # shadowing field covers the walk/drive graph + this
MAX_SITES = 24            # cap (spatially thinned); the rank encoder needs no fixed count


def _build_sites_module():
    """data/opencellid/build_sites.py is a standalone script, not a package —
    load it by path so there is exactly one copy of the projection/cluster logic."""
    path = REPO / "data" / "opencellid" / "build_sites.py"
    spec = importlib.util.spec_from_file_location("horus_build_sites", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


build_sites = _build_sites_module()


class Frame:
    def __init__(self, bbox):
        s, w, n, e = bbox
        self.bbox = tuple(bbox)
        self.lat0, self.lon0 = (s + n) / 2.0, (w + e) / 2.0
        x0, y0 = self.xy(s, w)
        x1, y1 = self.xy(n, e)
        self.extent = (x0, y0, x1, y1)          # campus fence in local metres

    def xy(self, lat, lon):
        return build_sites.local_xy(lat, lon, self.lat0, self.lon0)

    def size_m(self):
        x0, y0, x1, y1 = self.extent
        return x1 - x0, y1 - y0

    def inside(self, x, y, margin=0.0):
        x0, y0, x1, y1 = self.extent
        return x0 - margin <= x <= x1 + margin and y0 - margin <= y <= y1 + margin


def campus_dir(cid):
    return CAMPUS_DATA / cid


class CampusRadioMap(RadioMap):
    _SHADOW = {}                      # (seed, cell_id, tx, ty) -> dB, shared across resets

    def _shadow_db(self, cell, x, y):
        key = (self._seed, cell.cell_id, int(x // self.SHADOW_TILE_M), int(y // self.SHADOW_TILE_M))
        v = self._SHADOW.get(key)
        if v is None:
            if len(self._SHADOW) > 3_000_000:
                self._SHADOW.clear()
            v = self._SHADOW[key] = RadioMap._shadow_db(self, cell, x, y)
        return v


class CampusWorld:
    def __init__(self, cid):
        d = campus_dir(cid)
        self.id = cid
        self.sites_doc = json.loads((d / "sites.json").read_text(encoding="utf-8"))
        self.layout = json.loads((d / "layout.json").read_text(encoding="utf-8"))
        self.frame = Frame(self.sites_doc["bbox"])
        self.twin_sites = self.sites_doc["twin_sites"]
        self.walk = PathGraph(self.layout["nodes"], self.layout["edges"])
        drive = PathGraph(self.layout["nodes"], self.layout["drive_edges"])
        self.drive = drive if len(drive.active) >= 50 else self.walk
        bl = self.layout["buildings"][:60]
        self.buildings = [(b, self.walk.nearest(b["x"], b["y"])) for b in bl]
        self.halls = self.layout["buildings"][: self.sites_doc.get("hints", {}).get("dwell_buildings", 3)]

    def cells(self):
        return [Cell(s["site_id"], s["x_m"], s["y_m"], tx_power_dbm=TX_POWER_DBM)
                for s in self.twin_sites]

    def shadow_extent(self):
        """(lo, hi) square for twin v2's continuous shadowing field: every
        place a UE can be (walk + drive graph nodes, building centroids)."""
        xs = [n[0] for n in self.layout["nodes"]] + [b["x"] for b in self.layout["buildings"]]
        ys = [n[1] for n in self.layout["nodes"]] + [b["y"] for b in self.layout["buildings"]]
        return (min(min(xs), min(ys)) - SHADOW_MARGIN_M, max(max(xs), max(ys)) + SHADOW_MARGIN_M)


@functools.lru_cache(maxsize=None)
def load_world(cid):
    return CampusWorld(cid)


def campus_radio_map(cid, seed, fading="off"):
    w = load_world(cid)
    m = CampusRadioMap(w.cells(), seed, fading=fading)
    m.shadow_extent = w.shadow_extent()      # read by twin.sim.make_trace (PHY v2)
    return m


def select_twin_sites(sites, frame, margin_m=SITE_MARGIN_M, max_sites=MAX_SITES):
    """Sites inside the fence (+margin), thinned to max_sites by farthest-point
    sampling seeded at the site nearest the centre — even spatial coverage on
    a 2.5 km campus, where "K nearest the centre" (the Kumoh-only v0 rule)
    would leave the far ends without a tower. Ids keep build_sites' order."""
    keep = [s for s in sites if frame.inside(s["x_m"], s["y_m"], margin_m)]
    if len(keep) <= max_sites:
        return keep
    chosen = [min(keep, key=lambda s: math.hypot(s["x_m"], s["y_m"]))]
    d = {id(s): math.hypot(s["x_m"] - chosen[0]["x_m"], s["y_m"] - chosen[0]["y_m"]) for s in keep}
    while len(chosen) < max_sites:
        nxt = max(keep, key=lambda s: (d[id(s)], s["site_id"]))
        chosen.append(nxt)
        for s in keep:
            d[id(s)] = min(d[id(s)], math.hypot(s["x_m"] - nxt["x_m"], s["y_m"] - nxt["y_m"]))
    order = {s["site_id"]: i for i, s in enumerate(sites)}
    return sorted(chosen, key=lambda s: order[s["site_id"]])


# ---------------------------------------------------------------- mobility

class _RouteFollower(Scenario):
    """UEs walk shortest paths on the OSM graph between campus buildings; on
    arrival they pick a new destination. Deterministic in the env RNG."""
    graph_attr = "walk"
    episode_steps = 300

    def __init__(self, cid, kind):
        self.cid, self.kind = cid, kind
        self.name = f"{kind}@{cid}"

    @property
    def world(self):
        return load_world(self.cid)

    def _graph(self):
        return getattr(self.world, self.graph_attr)

    def _pick_node(self, rng):
        g, w = self._graph(), self.world
        if g is w.walk and w.buildings:
            # area-weighted building entrances: big halls draw more people
            tot = sum(b["area_m2"] for b, _ in w.buildings)
            r = rng.uniform(0, tot)
            for b, node in w.buildings:
                r -= b["area_m2"]
                if r <= 0:
                    return node
            return w.buildings[-1][1]
        return g.active[rng.randrange(len(g.active))]

    def _speed(self, rng):
        raise NotImplementedError

    def _new_route(self, ue, rng, src):
        g = self._graph()
        for _ in range(6):
            dst = self._pick_node(rng)
            path = g.route(src, dst)
            if len(path) > 1:
                break
        ue.route = [g.nodes[i] for i in path]
        ue.route_end = path[-1]
        ue.leg = 0

    def spawn(self, rng):
        g = self._graph()
        ues = []
        for i in range(self.n_ues):
            src = self._pick_node(rng)
            ue = UE(f"ue-{i:02d}", *g.nodes[src])
            ue.speed = self._speed(rng)
            self._new_route(ue, rng, src)
            # start somewhere along the first route, not all at doorways
            ue.x, ue.y = ue.route[rng.randrange(len(ue.route))]
            ue.leg = 0
            ues.append(ue)
        return ues

    def move(self, ue, step, rng, dt=1.0):
        left = ue.speed * dt
        while left > 0:
            if ue.leg >= len(ue.route) - 1:
                self._new_route(ue, rng, ue.route_end)
                if len(ue.route) < 2:
                    return
            tx, ty = ue.route[ue.leg + 1]
            d = math.hypot(tx - ue.x, ty - ue.y)
            if d <= left:
                ue.x, ue.y = tx, ty
                ue.leg += 1
                left -= d
            else:
                ue.x += (tx - ue.x) * left / d
                ue.y += (ty - ue.y) * left / d
                left = 0.0


class Commute(_RouteFollower):
    """rush_hour analogue: 20 pedestrians/cyclists between buildings."""
    n_ues = 20

    def _speed(self, rng):
        return rng.uniform(3.0, 6.0) if rng.random() < 0.25 else rng.uniform(1.0, 1.8)


class Shuttle(_RouteFollower):
    """Campus roads at 6-12 m/s (shuttle bus, cars): fast serial HOs."""
    n_ues = 8
    graph_attr = "drive"

    def _speed(self, rng):
        return rng.uniform(6.0, 12.0)


class Dwell(Scenario):
    """stationary_clusters analogue: crowds inside the largest buildings
    (lecture halls from the OSM footprints). Any HO churn is controller error."""
    n_ues = 15
    episode_steps = 300

    def __init__(self, cid):
        self.cid = cid
        self.name = f"dwell@{cid}"

    def spawn(self, rng):
        halls = load_world(self.cid).halls
        ues = []
        for i in range(self.n_ues):
            h = halls[i % len(halls)]
            r = min(30.0, 0.4 * math.sqrt(h["area_m2"]))
            ues.append(UE(f"ue-{i:02d}", h["x"] + rng.uniform(-r, r), h["y"] + rng.uniform(-r, r)))
        return ues

    def move(self, ue, step, rng, dt=1.0):
        pass


KINDS = ("commute", "shuttle", "dwell")


@functools.lru_cache(maxsize=None)
def campus_scenario(name):
    kind, cid = name.split("@", 1)
    if kind == "commute":
        return Commute(cid, kind)
    if kind == "shuttle":
        return Shuttle(cid, kind)
    if kind == "dwell":
        return Dwell(cid)
    raise ValueError(f"unknown campus scenario kind {kind!r} (have: {', '.join(KINDS)})")


def scenario_names(cid):
    return [f"{k}@{cid}" for k in KINDS]
