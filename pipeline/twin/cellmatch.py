"""Match walk-test cells to OpenCellID sites - by identity first (#5/#6).

Order of preference for every logged LTE cell (rat, mcc, mnc, ECI):

  1. 'eci'  - the exact cell is in the OpenCellID catalog (kumoh-cell-ids.json)
  2. 'enb'  - the sector is not, but its eNB (ECI >> 8) is: same mast
  3. 'inferred' - no ID in OpenCellID: the site is chosen afterwards by
     path-loss likelihood under the ID-matched fit (fit_radio.infer_sites),
     over candidate sites of the same operator near the cell's samples
  4. 'unmatched' - nothing plausible within reach: the cell's samples are
     dropped from the fit (and reported)

An emitter is what the fit models: a frozen v0 site (ocid-NN) when the eNB's
catalog cells snap to one, else an extra 'enb:MCC-MNC-ENB' emitter at the
eNB's OpenCellID position (real cell, just not among the 110 frozen sites).

The strongest-sample centroid (PR #33's matcher) is kept ONLY as a reported
baseline: on serving-cell-only data it pins ~1 in 5 samples to the wrong mast.
Neighbour rows carry a PCI, not an ECI; resolve_neighbours maps (operator,
PCI[, EARFCN]) to the nearest serving cell that used that PCI.
"""

import json
import math
from collections import Counter, defaultdict
from pathlib import Path

CATALOG_FILE = Path(__file__).resolve().parents[2] / "data" / "opencellid" / "kumoh-cell-ids.json"

INFER_RADIUS_M = 1500.0          # candidate sites for an ID-less cell
NEIGHBOUR_RADIUS_M = 2500.0      # a PCI heard further than this from its serving centroid is a reuse
NEIGHBOUR_AMBIGUITY = 0.6        # nearest candidate must be < 0.6 x second-nearest


def load_catalog(path=CATALOG_FILE):
    p = Path(path)
    if not p.exists():
        return {"cells": [], "enbs": []}
    return json.loads(p.read_text(encoding="utf-8"))


def _site_mncs(sites_doc, catalog):
    m = {s["site_id"]: set(s.get("mncs") or []) for s in sites_doc["sites"]}
    for c in catalog.get("cells", []):
        if c.get("site_id"):
            m.setdefault(c["site_id"], set()).add(c["mnc"])
    return m


def build_cells(epochs):
    """Logged serving cells -> {key: summary}. Centroids are over the cell's own
    serving samples; `top_centroid` is PR #33's strongest-quartile centroid."""
    groups = defaultdict(list)
    for e in epochs:
        groups[e["cell"]].append(e)
    cells = {}
    for key, grp in groups.items():
        top = sorted(grp, key=lambda e: -e["rsrp"])[:max(1, len(grp) // 4)]
        pcis = Counter(e["pci"] for e in grp if e["pci"] is not None)
        earfcns = Counter(e["earfcn"] for e in grp if e["earfcn"] is not None)
        cells[key] = {
            "key": key, "rat": key[0], "mcc": key[1], "mnc": key[2], "eci": key[3],
            "enb": grp[0]["enb"], "sector": grp[0]["sector"],
            "pci": pcis.most_common(1)[0][0] if pcis else None,
            "earfcn": earfcns.most_common(1)[0][0] if earfcns else None,
            "n_serving": len(grp),
            "cx": sum(e["x"] for e in grp) / len(grp), "cy": sum(e["y"] for e in grp) / len(grp),
            "top_cx": sum(e["x"] for e in top) / len(top), "top_cy": sum(e["y"] for e in top) / len(top),
            "match": None, "emitter": None,
        }
    return cells


def match_ids(cells, sites_doc, catalog):
    """Fill cell['match'] / cell['emitter'] by identity; returns the emitter table
    {emitter_id: {x, y, site_id, kind, mncs}} (all frozen sites + any extra
    catalog eNBs the log touched)."""
    emitters = {s["site_id"]: {"x": s["x_m"], "y": s["y_m"], "site_id": s["site_id"],
                               "kind": "v0-site", "mncs": set()}
                for s in sites_doc["sites"]}
    for sid, m in _site_mncs(sites_doc, catalog).items():
        if sid in emitters:
            emitters[sid]["mncs"] |= m
    by_cell, by_cellid, by_enb = {}, defaultdict(list), {}
    for c in catalog.get("cells", []):
        by_cell[(c["radio"], c["mcc"], c["mnc"], c["cellid"])] = c
        by_cellid[(c["radio"], c["cellid"])].append(c)
    for e in catalog.get("enbs", []):
        by_enb[(e["mcc"], e["mnc"], e["enb"])] = e

    def emitter_for_enb(mcc, mnc, enb):
        e = by_enb.get((mcc, mnc, enb))
        if e is None:
            return None
        if e.get("site_id"):
            return e["site_id"]
        eid = f"enb:{mcc}-{mnc:02d}-{enb}"
        emitters.setdefault(eid, {"x": e["x_m"], "y": e["y_m"], "site_id": None,
                                  "kind": "ocid-enb", "mncs": {mnc}})
        return eid

    for key, cell in cells.items():
        rat, mcc, mnc, eci = key
        hit = by_cell.get(key)
        if hit is None and mcc is None and len(by_cellid[(rat, eci)]) == 1:
            hit = by_cellid[(rat, eci)][0]          # log without an Operator column
        if hit is not None:
            cell["match"] = "eci"
            cell["mcc"], cell["mnc"] = hit["mcc"], hit["mnc"]
            if rat == "LTE":
                cell["emitter"] = emitter_for_enb(hit["mcc"], hit["mnc"], hit["enb"])
            if cell["emitter"] is None and hit.get("site_id"):
                cell["emitter"] = hit["site_id"]
            if cell["emitter"] is None:
                eid = f"cell:{hit['mcc']}-{hit['mnc']:02d}-{hit['cellid']}"
                emitters.setdefault(eid, {"x": hit["x_m"], "y": hit["y_m"], "site_id": None,
                                          "kind": "ocid-cell", "mncs": {hit["mnc"]}})
                cell["emitter"] = eid
            continue
        if rat == "LTE" and mcc is not None:
            eid = emitter_for_enb(mcc, mnc, cell["enb"])
            if eid is not None:
                cell["match"], cell["emitter"] = "enb", eid
                continue
        cell["match"] = "none"
    return emitters


def centroid_site(cell, emitters, max_dist_m=500.0):
    """PR #33's matcher (baseline only): nearest operator-compatible frozen
    site to the strongest-quartile centroid."""
    cands = [(eid, em) for eid, em in emitters.items() if em["kind"] == "v0-site"
             and (cell["mnc"] is None or not em["mncs"] or cell["mnc"] in em["mncs"])]
    if not cands:
        return None
    eid, em = min(cands, key=lambda kv: math.hypot(kv[1]["x"] - cell["top_cx"], kv[1]["y"] - cell["top_cy"]))
    return eid if math.hypot(em["x"] - cell["top_cx"], em["y"] - cell["top_cy"]) <= max_dist_m else None


def candidate_emitters(cell, emitters, radius_m=INFER_RADIUS_M):
    return [eid for eid, em in emitters.items()
            if (cell["mnc"] is None or not em["mncs"] or cell["mnc"] in em["mncs"])
            and math.hypot(em["x"] - cell["cx"], em["y"] - cell["cy"]) <= radius_m]


def resolve_neighbours(epochs, cells):
    """Neighbour rows -> cell keys. -> (list of (epoch_idx, key, rsrp)), stats.
    A neighbour's ECI is used when the log has one (NCellid >= 256); otherwise
    its PCI (+EARFCN when logged) is resolved to the nearest serving cell of the
    same operator/RAT that used that PCI, and dropped if that is ambiguous
    (PCI reuse) or too far."""
    by_pci = defaultdict(list)
    for key, c in cells.items():
        if c["pci"] is not None:
            by_pci[(c["rat"], c["mcc"], c["mnc"], c["pci"])].append(c)
    out, stats = [], Counter()
    for i, e in enumerate(epochs):
        for n in e["neighbours"]:
            stats["seen"] += 1
            if n.get("cellid") is not None and n["cellid"] >= 256:
                key = (e["rat"], e["mcc"], e["mnc"], n["cellid"])
                if key in cells:
                    out.append((i, key, n["rsrp"]))
                    stats["by ECI"] += 1
                    continue
            cands = by_pci.get((e["rat"], e["mcc"], e["mnc"], n["pci"]), [])
            if n.get("earfcn") is not None:
                same = [c for c in cands if c["earfcn"] in (None, n["earfcn"])]
                cands = same  # explicit channel mismatch is not PCI evidence
            cands = [c for c in cands if c["key"] != e["cell"]]
            if not cands:
                stats["PCI never seen as serving"] += 1
                continue
            ds = sorted((math.hypot(c["cx"] - e["x"], c["cy"] - e["y"]), j) for j, c in enumerate(cands))
            d0 = ds[0][0]
            if d0 > NEIGHBOUR_RADIUS_M:
                stats["PCI's serving cell too far"] += 1
                continue
            if len(ds) > 1 and d0 > NEIGHBOUR_AMBIGUITY * ds[1][0]:
                stats["PCI ambiguous (reuse)"] += 1
                continue
            out.append((i, cands[ds[0][1]]["key"], n["rsrp"]))
            stats["by PCI"] += 1
    return out, dict(stats)


def match_summary(cells):
    """Judge-facing match rate: share of observed cells (and of samples) whose
    identity is in OpenCellID."""
    n_cells = len(cells)
    n_samp = sum(c["n_serving"] for c in cells.values()) or 1
    by = Counter(c["match"] for c in cells.values())
    by_s = Counter()
    for c in cells.values():
        by_s[c["match"]] += c["n_serving"]
    return {
        "cells_observed": n_cells,
        "cells_by_match": dict(by),
        "samples_by_match": dict(by_s),
        "pct_cells_eci": round(100.0 * by["eci"] / n_cells, 1) if n_cells else 0.0,
        "pct_cells_id_any": round(100.0 * (by["eci"] + by["enb"]) / n_cells, 1) if n_cells else 0.0,
        "pct_samples_id_any": round(100.0 * (by_s["eci"] + by_s["enb"]) / n_samp, 1),
    }
