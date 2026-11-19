"""OpenStreetMap campus layout via the Overpass API (buildings + walkable paths).

Fetch is cached: the raw Overpass JSON lands in data/campuses/<id>/raw/
(git-ignored; ODbL data, attribution in data/campuses/README.md) and is only
re-requested with --refresh. Overpass mirrors are flaky, so the client walks a
list of public endpoints with backoff; it never hammers one server.

parse_layout() turns the raw response into the small committed layout.json the
twin consumes: building footprints (centroid, area, simplified ring) and a
pedestrian/vehicle path graph in the campus-local metre frame (same
equirectangular projection as data/opencellid/build_sites.py).
"""

import heapq
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request

ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)
USER_AGENT = "HORUS-campus/1.0 (Kumoh NIT research; handover digital twin)"

# highway=* values a person (or campus shuttle) actually moves along.
WALK = {"footway", "path", "pedestrian", "steps", "living_street", "service",
        "residential", "unclassified", "tertiary", "secondary", "cycleway",
        "track", "corridor", "primary", "tertiary_link", "secondary_link"}
DRIVE = {"service", "residential", "unclassified", "tertiary", "secondary",
         "primary", "living_street", "tertiary_link", "secondary_link"}


def overpass(query, log=print, rounds=3, timeout=180):
    """POST a query, rotating endpoints with backoff between full rounds."""
    last = None
    body = urllib.parse.urlencode({"data": query}).encode()
    for attempt in range(rounds):
        for ep in ENDPOINTS:
            req = urllib.request.Request(ep, data=body, headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return json.loads(r.read())
            except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
                last = e
                log(f"  overpass {ep.split('/')[2]}: {e} - trying next mirror")
        time.sleep(10.0 * (attempt + 1))
    raise RuntimeError(f"all Overpass mirrors failed: {last}")


def layout_query(bbox):
    s, w, n, e = bbox
    b = f"({s},{w},{n},{e})"
    return ("[out:json][timeout:150];"
            f'(way["building"]{b};way["highway"]{b};);out geom tags;'
            f'(way["amenity"="university"]{b};relation["amenity"="university"]{b};);out bb tags;')


def fetch_layout(bbox, cache_file, refresh=False, log=print):
    """-> (raw_json, fetched_now)."""
    if cache_file.exists() and not refresh:
        log(f"  osm: cached {cache_file.name}")
        return json.loads(cache_file.read_text(encoding="utf-8")), False
    log(f"  osm: querying Overpass for bbox {bbox}")
    raw = overpass(layout_query(bbox), log=log)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(raw), encoding="utf-8")
    return raw, True


# ---------------------------------------------------------------- geometry

def polygon_area_centroid(pts):
    """Shoelace area (m^2) + centroid of a ring of (x, y)."""
    a = cx = cy = 0.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
        cr = x0 * y1 - x1 * y0
        a += cr
        cx += (x0 + x1) * cr
        cy += (y0 + y1) * cr
    a *= 0.5
    if abs(a) < 1e-9:
        xs, ys = zip(*pts)
        return 0.0, (sum(xs) / len(xs), sum(ys) / len(ys))
    return abs(a), (cx / (6 * a), cy / (6 * a))


def _simplify(pts, keep=12):
    return pts if len(pts) <= keep else pts[::max(1, len(pts) // keep)]


def parse_layout(raw, frame, densify_m=20.0, clip=None):
    """raw Overpass JSON -> {buildings, nodes, edges, drive_edges, university}.

    frame: campus.world.Frame (lat/lon -> local metres). Path ways are
    densified to <= densify_m segments (a UE walking an edge never skips a
    shadowing tile); nodes shared between ways become junctions. clip:
    (xmin, ymin, xmax, ymax) — path nodes outside are dropped. Only the
    largest connected component is kept (islands would strand UEs).
    """
    buildings, node_xy, node_ids = [], [], {}
    edges, drive = set(), set()
    university = []

    def inside(x, y):
        return clip is None or (clip[0] <= x <= clip[2] and clip[1] <= y <= clip[3])

    def nid(lat, lon):
        key = (round(lat, 7), round(lon, 7))
        if key not in node_ids:
            node_ids[key] = len(node_xy)
            node_xy.append(frame.xy(lat, lon))
        return node_ids[key]

    def extra_node(x, y):
        node_xy.append((x, y))
        return len(node_xy) - 1

    for el in raw.get("elements", []):
        tags = el.get("tags", {})
        if tags.get("amenity") == "university" and "bounds" in el:
            b = el["bounds"]
            university.append({"name": tags.get("name:en") or tags.get("name"),
                               "osm": f"{el['type']}/{el['id']}",
                               "bbox": [b["minlat"], b["minlon"], b["maxlat"], b["maxlon"]]})
            continue
        geom = el.get("geometry")
        if el.get("type") != "way" or not geom:
            continue
        if "building" in tags:
            ring = [frame.xy(p["lat"], p["lon"]) for p in geom]
            if len(ring) > 1 and ring[0] == ring[-1]:
                ring = ring[:-1]
            if len(ring) < 3:
                continue
            area, (cx, cy) = polygon_area_centroid(ring)
            if area < 30.0 or not inside(cx, cy):      # sheds, kiosks, off-campus
                continue
            try:
                levels = float(str(tags.get("building:levels", "0")).split(";")[0])
            except ValueError:
                levels = 0.0
            buildings.append({"x": round(cx, 1), "y": round(cy, 1), "area_m2": round(area),
                              "levels": levels,
                              "name": tags.get("name:en") or tags.get("name") or "",
                              "ring": [[round(x, 1), round(y, 1)] for x, y in _simplify(ring)]})
            continue
        hw = tags.get("highway")
        if hw in WALK:
            ids = [nid(p["lat"], p["lon"]) for p in geom]
            for a, b in zip(ids, ids[1:]):
                if a == b:
                    continue
                (xa, ya), (xb, yb) = node_xy[a], node_xy[b]
                if not (inside(xa, ya) and inside(xb, yb)):
                    continue
                d = math.hypot(xb - xa, yb - ya)
                n_seg = max(1, int(math.ceil(d / densify_m)))
                chain = ([a] + [extra_node(xa + (xb - xa) * k / n_seg, ya + (yb - ya) * k / n_seg)
                                for k in range(1, n_seg)] + [b])
                for u, v in zip(chain, chain[1:]):
                    e = (min(u, v), max(u, v))
                    edges.add(e)
                    if hw in DRIVE:
                        drive.add(e)

    adj = {}
    for u, v in edges:
        adj.setdefault(u, set()).add(v)
        adj.setdefault(v, set()).add(u)
    seen, best = set(), set()
    for s in adj:
        if s in seen:
            continue
        comp, stack = {s}, [s]
        while stack:
            u = stack.pop()
            for v in adj[u]:
                if v not in comp:
                    comp.add(v)
                    stack.append(v)
        seen |= comp
        if len(comp) > len(best):
            best = comp
    order = sorted(best)
    remap = {old: i for i, old in enumerate(order)}
    nodes = [[round(node_xy[o][0], 1), round(node_xy[o][1], 1)] for o in order]
    e_out = sorted((remap[u], remap[v]) for u, v in edges if u in remap and v in remap)
    d_out = sorted((remap[u], remap[v]) for u, v in drive if u in remap and v in remap)
    buildings.sort(key=lambda b: -b["area_m2"])
    return {"buildings": buildings, "nodes": nodes, "edges": e_out,
            "drive_edges": d_out, "university": university}


# ---------------------------------------------------------------- routing

class PathGraph:
    """Undirected metric graph with Dijkstra routing (stdlib heapq)."""

    def __init__(self, nodes, edges):
        self.nodes = [tuple(n) for n in nodes]
        self.adj = {i: [] for i in range(len(self.nodes))}
        for u, v in edges:
            d = math.dist(self.nodes[u], self.nodes[v])
            self.adj[u].append((v, d))
            self.adj[v].append((u, d))
        self.active = [i for i, nb in self.adj.items() if nb]
        self._routes = {}

    def nearest(self, x, y):
        return min(self.active,
                   key=lambda i: (self.nodes[i][0] - x) ** 2 + (self.nodes[i][1] - y) ** 2)

    def route(self, src, dst):
        key = (src, dst)
        if key in self._routes:
            return self._routes[key]
        dist, prev, pq = {src: 0.0}, {}, [(0.0, src)]
        while pq:
            d, u = heapq.heappop(pq)
            if u == dst:
                break
            if d > dist.get(u, math.inf):
                continue
            for v, w in self.adj[u]:
                nd = d + w
                if nd < dist.get(v, math.inf):
                    dist[v], prev[v] = nd, u
                    heapq.heappush(pq, (nd, v))
        if dst not in dist:
            path = [src]
        else:
            path, u = [dst], dst
            while u != src:
                u = prev[u]
                path.append(u)
            path = path[::-1]
        self._routes[key] = path
        return path

    def length_m(self):
        return sum(d for u, nb in self.adj.items() for v, d in nb if u < v)
