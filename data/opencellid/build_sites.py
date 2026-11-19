#!/usr/bin/env python3
"""Trim raw OpenCellID tile pulls into the committed site extract (#6 v0).

Reads raw-tile*.json (getInArea responses; NOT committed — rerun the fetch
with your own token), dedupes cells, clusters them into physical sites
(~100 m grid — co-sited sectors/carriers collapse to one tower), and writes
kumoh-cells.json: the small, committable geometry file the twin's
`--radio-map opencellid` loader consumes.

The site set and its IDs are FROZEN (the DQN checkpoints, gate evidence and the
measured map key on ocid-NN). OpenCellID re-estimates cell positions as crowd
samples arrive, so re-clustering a fresh pull would renumber the sites. The
default mode therefore leaves kumoh-cells.json alone and writes the per-cell
identifier catalog kumoh-cell-ids.json instead: every LTE cell (MCC/MNC, ECI =
eNB*256 + sector, TAC) pinned to its nearest frozen site, plus an eNB -> site
consensus. The walk-test matcher (pipeline/twin/cellmatch.py) uses it to match
logged cells to sites by ID instead of by guessing from signal strength.

Usage (from this directory):
    python3 fetch_tiles.py && python3 build_sites.py     # catalog (default)
    python3 build_sites.py --rebuild-sites               # v0 behaviour: re-cluster
"""

import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Kumoh National Institute of Technology, Yangho-dong campus centre.
CAMPUS_LAT, CAMPUS_LON = 36.1446, 128.3936
CLUSTER_M = 100.0
SITE_SNAP_M = 150.0   # a cell further than this from every frozen site stays unsited


def local_xy(lat, lon, centre_lat=CAMPUS_LAT, centre_lon=CAMPUS_LON):
    x = (lon - centre_lon) * 111_320.0 * math.cos(math.radians(centre_lat))
    y = (lat - centre_lat) * 110_574.0
    return x, y


def dedupe_lte(raw_cells, mcc=450, radios=("LTE",)):
    """Unique (mcc, mnc, cellid) cells of the given radio types (LTE only by
    default: the site clustering), first occurrence wins."""
    cells, seen = [], set()
    for c in raw_cells:
        key = (c["mcc"], c["mnc"], c["cellid"])
        if c["mcc"] != mcc or c.get("radio") not in radios or key in seen:
            continue
        seen.add(key)
        cells.append(c)
    return cells


def cluster_sites(cells, centre_lat=CAMPUS_LAT, centre_lon=CAMPUS_LON,
                  cluster_m=CLUSTER_M):
    """Collapse co-sited sectors/carriers onto a cluster_m grid -> physical
    sites, ids ordered by distance from the centre (ocid-00 = nearest).
    Reused by pipeline/campus (any campus) — keep it the single copy."""
    clusters = {}
    for c in cells:
        x, y = local_xy(c["lat"], c["lon"], centre_lat, centre_lon)
        k = (round(x / cluster_m), round(y / cluster_m))
        clusters.setdefault(k, []).append((c, x, y))

    sites = []
    for i, (k, members) in enumerate(sorted(clusters.items(),
                                            key=lambda kv: math.hypot(*kv[0]))):
        xs = [m[1] for m in members]
        ys = [m[2] for m in members]
        sites.append({
            "site_id": f"ocid-{i:02d}",
            "lat": round(sum(m[0]["lat"] for m in members) / len(members), 6),
            "lon": round(sum(m[0]["lon"] for m in members) / len(members), 6),
            "x_m": round(sum(xs) / len(xs), 1),      # campus-local metres (centre = 0,0)
            "y_m": round(sum(ys) / len(ys), 1),
            "n_cells": len(members),
            "mncs": sorted({m[0]["mnc"] for m in members}),
            "tacs": sorted({m[0]["tac"] for m in members}),
        })
    return sites


def load_raw_tiles():
    raw = []
    for f in sorted(HERE.glob("raw-tile*.json")):
        raw.extend(json.loads(f.read_text(encoding="utf-8")).get("cells", []))
    return raw


def load_raw_lte():
    """LTE + NR cells (the ID catalog keeps NR too; site clustering is LTE only)."""
    return dedupe_lte(load_raw_tiles(), radios=("LTE", "NR"))


def build_catalog():
    """Per-cell identifiers -> frozen site IDs (kumoh-cell-ids.json)."""
    sites = json.loads((HERE / "kumoh-cells.json").read_text(encoding="utf-8"))["sites"]
    raw = load_raw_lte()
    if not raw:
        sys.exit("no raw-tile*.json here: run fetch_tiles.py first")
    out_cells = []
    for c in sorted(raw, key=lambda c: (c["mnc"], c["cellid"])):
        x, y = local_xy(c["lat"], c["lon"])
        near = min(sites, key=lambda s: math.hypot(s["x_m"] - x, s["y_m"] - y))
        dist = math.hypot(near["x_m"] - x, near["y_m"] - y)
        lte = c["radio"] == "LTE"
        out_cells.append({
            "radio": c["radio"], "mcc": c["mcc"], "mnc": c["mnc"],
            "cellid": c["cellid"],                       # LTE: ECI (28 bit); NR: NCI
            "enb": c["cellid"] >> 8 if lte else None,
            "sector": c["cellid"] & 0xFF if lte else None,
            "tac": c.get("tac"), "lat": c["lat"], "lon": c["lon"],
            "x_m": round(x, 1), "y_m": round(y, 1),
            "range_m": c.get("range"), "samples": c.get("samples"),
            "site_id": near["site_id"] if dist <= SITE_SNAP_M else None,
            "site_dist_m": round(dist, 1),
        })
    # eNB -> site consensus: sectors of one eNB share a mast, but OpenCellID
    # places each sector at the centroid of ITS crowd samples (pulled toward the
    # sector's boresight), so the per-cell snap can disagree across sectors.
    by_enb = defaultdict(list)
    for c in out_cells:
        if c["enb"] is not None:
            by_enb[(c["mcc"], c["mnc"], c["enb"])].append(c)
    enbs = []
    for (mcc, mnc, enb), members in sorted(by_enb.items()):
        votes = Counter(m["site_id"] for m in members if m["site_id"])
        mx = sum(m["x_m"] for m in members) / len(members)
        my = sum(m["y_m"] for m in members) / len(members)
        enbs.append({"mcc": mcc, "mnc": mnc, "enb": enb, "n_cells": len(members),
                     "x_m": round(mx, 1), "y_m": round(my, 1),
                     "spread_m": round(max(math.hypot(m["x_m"] - mx, m["y_m"] - my) for m in members), 1),
                     "site_id": votes.most_common(1)[0][0] if votes else None})
    doc = {
        "source": "opencellid.org getInArea (4 tiles, 2x2 km each), MCC 450, LTE/NR",
        "note": "positions are OpenCellID crowd estimates (3-decimal degrees, ~100 m "
                "quantisation), not surveyed masts; site_id = nearest frozen v0 site "
                f"within {SITE_SNAP_M:.0f} m, else null",
        "campus_centre": {"lat": CAMPUS_LAT, "lon": CAMPUS_LON},
        "fetched_utc": max(json.loads(f.read_text(encoding="utf-8")).get("fetched_utc", "")
                           for f in HERE.glob("raw-tile*.json")) or None,
        "n_cells": len(out_cells),
        "n_sited": sum(1 for c in out_cells if c["site_id"]),
        "cells": out_cells,
        "enbs": enbs,
    }
    (HERE / "kumoh-cell-ids.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    per_site = Counter(c["site_id"] for c in out_cells if c["site_id"])
    print(f"{len(out_cells)} cells ({doc['n_sited']} within {SITE_SNAP_M:.0f} m of a frozen site), "
          f"{len(enbs)} eNBs -> kumoh-cell-ids.json")
    print(f"frozen sites with >=1 catalogued cell: {len(per_site)}/{len(sites)}")


def rebuild_sites():
    cells = dedupe_lte(load_raw_tiles())
    sites = cluster_sites(cells)

    out = {
        "source": "opencellid.org getInArea, MCC 450, radio=LTE only",
        "campus_centre": {"lat": CAMPUS_LAT, "lon": CAMPUS_LON},
        "cluster_metres": CLUSTER_M,
        "n_raw_cells": len(cells),
        "n_sites": len(sites),
        "sites": sites,
    }
    (HERE / "kumoh-cells.json").write_text(json.dumps(out, indent=1) + "\n",
                                           encoding="utf-8")
    print(f"{len(cells)} LTE cells -> {len(sites)} sites -> kumoh-cells.json")
    for s in sites[:10]:
        print(f"  {s['site_id']}: ({s['x_m']:7.1f},{s['y_m']:7.1f}) m  "
              f"{s['n_cells']:2d} cells  mnc={s['mncs']}")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if "--rebuild-sites" in argv:
        rebuild_sites()       # renumbers sites: invalidates checkpoints/evidence
    else:
        build_catalog()


if __name__ == "__main__":
    main()
