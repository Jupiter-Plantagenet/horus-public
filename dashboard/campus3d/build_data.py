#!/usr/bin/env python3
"""Build the campus3d data bundle from committed, sanitized repo sources.

Standard library only. Read-only on every input; writes only into
dashboard/campus3d/data/. Every output records the SHA-256 of each input.

Inputs (all committed or derived from committed data):
  * OSM campus geometry   data/sources/osm-kumoh-20261104.json  (Overpass response, ODbL)
  * OpenCelliD sites      data/opencellid/kumoh-cells.json
  * T4 walk epochs        data/walktest/t4/epochs.jsonl, or the committed blob on
                          branch finals-measured-map (allowlisted structured facts only)
  * Calibrated trace      release/reference/measured-trace.{json,npz}
  * Recorded stream       working/evidence/selector-live-20261102/live/frames.jsonl
  * Qualified execution   working/evidence/qualified-release-20261104/{bounded,soak}/cycle-*/
  * Modelled comparison   working/evidence/measured-policy-20261102/results.json

    python dashboard/campus3d/build_data.py            # rebuild data/*.json
    python dashboard/campus3d/build_data.py --check    # verify outputs are up to date
"""
import argparse, ast, glob, hashlib, io, json, math, os, struct, subprocess, sys, zipfile
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OUT = HERE / "data"
CENTRE = {"lat": 36.1446, "lon": 128.3936}          # data/opencellid/build_sites.py centre
EPOCHS_BRANCH = "finals-measured-map"
EPOCHS_PATH = "data/walktest/t4/epochs.jsonl"
OSM_FILE = OUT / "sources" / "osm-kumoh-20261104.json"
LIVE = ROOT / "working/evidence/selector-live-20261102/live"
QUAL = ROOT / "working/evidence/qualified-release-20261104"
POLICY = ROOT / "working/evidence/measured-policy-20261102/results.json"
TRACE = ROOT / "release/reference/measured-trace"

inputs = {}


def sha(b):
    return hashlib.sha256(b).hexdigest()


def read(path):
    b = Path(path).read_bytes()
    inputs[Path(path).resolve().relative_to(ROOT).as_posix()] = sha(b)
    return b


def jload(path):
    return json.loads(read(path).decode("utf-8"))


def jlines(path):
    return [json.loads(l) for l in read(path).decode("utf-8").splitlines() if l.strip()]


def local_xy(lat, lon):
    """Same projection as data/opencellid/build_sites.py and pipeline/twin/walktest.py."""
    return ((lon - CENTRE["lon"]) * 111_320.0 * math.cos(math.radians(CENTRE["lat"])),
            (lat - CENTRE["lat"]) * 110_574.0)


def r1(v):
    return None if v is None or (isinstance(v, float) and not math.isfinite(v)) else round(v, 1)


def iso(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


# ---------------------------------------------------------------- epochs
def load_epochs():
    local = ROOT / EPOCHS_PATH
    if local.exists():
        return [json.loads(l) for l in read(local).decode("utf-8").splitlines() if l.strip()], EPOCHS_PATH
    git = ["git", "-c", "safe.directory=*", "-C", str(ROOT)]
    blob = subprocess.check_output(git + ["rev-parse", f"{EPOCHS_BRANCH}:{EPOCHS_PATH}"], text=True).strip()
    b = subprocess.check_output(git + ["cat-file", "blob", blob])
    inputs[f"git:{EPOCHS_BRANCH}:{EPOCHS_PATH}"] = sha(b)
    return [json.loads(l) for l in b.decode("utf-8").splitlines() if l.strip()], f"git blob {blob} ({EPOCHS_BRANCH}:{EPOCHS_PATH})"


# ---------------------------------------------------------------- npz (stdlib)
def load_npz(path):
    arrays = {}
    with zipfile.ZipFile(io.BytesIO(read(path))) as z:
        for name in z.namelist():
            b = z.read(name)
            assert b[:6] == b"\x93NUMPY", name
            major = b[6]
            hlen = struct.unpack("<H", b[8:10])[0] if major == 1 else struct.unpack("<I", b[8:12])[0]
            off = 10 if major == 1 else 12
            hdr = ast.literal_eval(b[off:off + hlen].decode("latin1"))
            data = b[off + hlen:]
            shape = hdr["shape"]
            if hdr["descr"] == "<f8":
                n = 1
                for s in shape: n *= s
                arrays[name[:-4]] = (shape, struct.unpack(f"<{n}d", data[:8 * n]))
            elif hdr["descr"].startswith("<U"):
                width = int(hdr["descr"][2:])
                arrays[name[:-4]] = (shape, data[:4 * width].decode("utf-32-le").rstrip("\x00"))
            else:
                raise ValueError(f"unsupported dtype {hdr['descr']} in {name}")
    return arrays


# ---------------------------------------------------------------- campus (OSM)
NAME_EN = {
    "벤처창업관": "Venture Startup Hall", "테크노관": "Techno Hall", "도서관": "Library",
    "학생회관": "Student Union", "글로벌관": "Global Hall", "디지털관": "Digital Hall",
    "야외음악당": "Outdoor Amphitheatre", "체육관": "Gymnasium", "학군단": "ROTC",
    "골프장": "Golf Range", "사열대": "Reviewing Stand", "관리동": "Dormitory Office",
    "푸름관": "Pureum Hall", "오름관": "Oreum Hall", "공동실험실습관": "Joint Laboratory Hall",
    "두레관": "Dure Hall", "쓰레기집하장": "Waste Depot", "풍동실험장": "Wind Tunnel",
    "경비실": "Guard Post", "정문": "Main Gate", "청운대": "Cheongun Hall",
    "국제교육관": "International Education Hall", "에디슨관": "Edison Hall",
    "산학협력관": "Industry-Academia Cooperation Hall", "라운지": "KIT Lounge", "좌석": "Stand",
}
LANDMARK = {"산학협력관", "도서관", "테크노관", "디지털관", "글로벌관", "학생회관", "체육관",
            "정문", "벤처창업관", "국제교육관", "에디슨관", "푸름관 1동", "오름관 1동", "두레관"}


def short_ko(name):
    for p in ("금오공과대학교 ", "금오공대 "):
        if name.startswith(p): name = name[len(p):]
    return name


def name_en(ko):
    for k, v in NAME_EN.items():
        if k in ko:
            suffix = ko.split(k, 1)[1].strip()
            return (v + (" " + suffix.replace("동", "") if suffix else "")).strip()
    return None


def poly_area(pts):
    return abs(sum(pts[i][0] * pts[i - 1][1] - pts[i - 1][0] * pts[i][1] for i in range(len(pts)))) / 2


def build_campus():
    osm = jload(OSM_FILE)
    buildings, paths, areas, boundary = [], [], [], None
    for e in osm["elements"]:
        if e.get("type") != "way" or "geometry" not in e:
            continue
        t = e.get("tags", {})
        pts = [[round(v, 2) for v in local_xy(g["lat"], g["lon"])] for g in e["geometry"]]
        if t.get("amenity") == "university":
            boundary = {"name_ko": t.get("name"), "name_en": t.get("name:en") or "Kumoh National Institute of Technology",
                        "poly": pts}
        elif "building" in t:
            ko = short_ko(t["name"]) if t.get("name") else None
            area = poly_area(pts)
            kind = t["building"]
            # OSM carries no height/levels here: heights are a declared approximation.
            if area < 120: h = 4.0
            elif kind == "dormitory": h = 30.0
            elif kind in ("university", "school") and area > 900: h = 18.0
            elif kind in ("university", "school"): h = 10.0
            else: h = 7.0
            if ko and ("골프장" in ko or "사열대" in ko or "좌석" in ko or "음악당" in ko): h = 5.0
            buildings.append({"osm": e["id"], "name_ko": ko, "name_en": name_en(ko) if ko else None,
                              "landmark": bool(ko and any(ko.startswith(l) or l == ko for l in LANDMARK)),
                              "kind": kind, "height_m": h, "area_m2": round(area), "poly": pts})
        elif "highway" in t:
            paths.append({"kind": t["highway"], "name": t.get("name"), "pts": pts})
        else:
            kind = t.get("leisure") or t.get("natural") or t.get("landuse")
            if pts[0] == pts[-1] and kind:
                areas.append({"kind": kind, "name": t.get("name"), "poly": pts})
    ocid = jload(ROOT / "data/opencellid/kumoh-cells.json")
    sites = [{"id": s["site_id"], "x": s["x_m"], "y": s["y_m"], "n_cells": s["n_cells"]} for s in ocid["sites"]]
    return {
        "format": "horus.campus3d.campus/1",
        "projection": {"centre": CENTRE, "x": "(lon-lon0)*111320*cos(lat0) m east", "y": "(lat-lat0)*110574 m north",
                       "same_as": "data/opencellid/build_sites.py, pipeline/twin/walktest.py local_xy"},
        "attribution": "Building footprints, paths and campus boundary © OpenStreetMap contributors, ODbL 1.0 "
                       "(Overpass snapshot " + osm["osm3s"]["timestamp_osm_base"] + ")",
        "provenance": {
            "footprints": "OpenStreetMap (real geometry)",
            "heights": "approximate: OSM has no height or building:levels for these ways; class-based estimate",
            "ocid_sites": "OpenCelliD crowd-sourced site estimates (110 sites); not identity-matched to the walk cells",
        },
        "boundary": boundary, "buildings": buildings, "paths": paths, "areas": areas, "ocid_sites": sites,
    }


# ---------------------------------------------------------------- route
def build_route(epochs, epochs_src):
    trace_meta = jload(str(TRACE) + ".json")
    npz = load_npz(str(TRACE) + ".npz")
    segments = json.loads(npz["header"][1])
    sessions = {}
    eci_pci, serving_rows = {}, {}
    for e in epochs:
        if e.get("eci") is not None and e.get("pci") is not None:
            eci_pci.setdefault(e["eci"], e["pci"])
    for sid in ("t4-reverse", "t4-forward"):
        rows = [e for e in epochs if e["session"] == sid]
        t0 = rows[0]["t"]
        # 1 s resampling of the recorded positions (the twin interpolates linearly, as
        # pipeline/twin/measured_scenario.position_trace does at dt=0.1 s).
        el = [e["t"] - t0 for e in rows]
        n = int(el[-1]) + 1
        xs, ys, sv, rs, sp = [], [], [], [], []
        j = 0
        for k in range(n):
            while j + 1 < len(el) and el[j + 1] <= k: j += 1
            if j + 1 < len(el) and el[j + 1] > el[j]:
                f = (k - el[j]) / (el[j + 1] - el[j])
            else:
                f = 0.0
            a, b = rows[j], rows[min(j + 1, len(rows) - 1)]
            xs.append(round(a["x"] + (b["x"] - a["x"]) * f, 2)); ys.append(round(a["y"] + (b["y"] - a["y"]) * f, 2))
            sv.append(a["eci"]); rs.append(a["rsrp"]); sp.append(r1(a.get("speed_kmh")))
        # Observed serving-cell changes in the phone log (the operator network's own handovers).
        changes = []
        for p, q in zip(rows, rows[1:]):
            if p.get("eci") and q.get("eci") and p["eci"] != q["eci"]:
                changes.append({"t_s": round(q["t"] - t0, 2), "from": p["eci"], "to": q["eci"],
                                "x": round(q["x"], 1), "y": round(q["y"], 1)})
        for e in rows:
            # The joint (-44,-3,-113) tuple is flagged for review (data/walktest/T4.md); it is
            # preserved in the source but excluded from anchor estimation.
            if e.get("eci") and e.get("rsrp") is not None and "joint_signal_tuple_review" not in e.get("flags", ()):
                serving_rows.setdefault(e["eci"], []).append((e["rsrp"], e["x"], e["y"]))
        sessions[sid] = {"t0_epoch_s": t0, "t0_kst": rows[0]["timestamp"], "duration_s": round(el[-1], 3),
                         "rows": len(rows), "lap": rows[0]["lap"], "split": rows[0]["split"],
                         "sample_dt_s": 1.0, "x": xs, "y": ys, "serving_eci": sv, "serving_rsrp": rs,
                         "speed_kmh": sp, "observed_cell_changes": changes,
                         # exact recorded points, for the twin's 0.1 s step interpolation
                         "points": {"t": [round(v, 3) for v in el], "x": [round(e["x"], 2) for e in rows],
                                    "y": [round(e["y"], 2) for e in rows]}}
    # Cells: identity from the phone log. Mast coordinates are NOT known (no catalogue match).
    keys = sorted({c for s in segments for c in s["cell_ids"]})
    cells = []
    for i, key in enumerate(keys):
        eci = int(key.split("/")[3])
        pts = sorted(serving_rows.get(eci, []), reverse=True)
        top = pts[:max(3, len(pts) // 20)]
        ax = sorted(p[1] for p in top)[len(top) // 2] if top else None
        ay = sorted(p[2] for p in top)[len(top) // 2] if top else None
        cells.append({"key": key, "letter": "ABCDEFG"[i], "eci": eci, "enb": eci >> 8, "sector": eci & 255,
                      "pci": eci_pci.get(eci), "serving_rows": len(pts),
                      "anchor": {"x": r1(ax), "y": r1(ay), "rsrp_dbm": top[0][0] if top else None,
                                 "meaning": "strongest measured serving RSRP location; mast position unknown"}})
    # Calibrated per-cell RSRP on the reverse route (release/reference/measured-trace), 1 s means.
    dt = trace_meta["assumptions"]["dt_s"]
    total = segments[-1]["end"]
    nsec = int(total * dt) + 1
    rsrp = [[None] * len(keys) for _ in range(nsec)]
    acc = {}
    for si, seg in enumerate(segments):
        shape, vals = npz[f"s{si:03d}_l1"]
        steps, _, nc = shape
        idx = [keys.index(c) for c in seg["cell_ids"]]
        for k in range(steps):
            sec = int((seg["start"] + k) * dt)
            for c in range(nc):
                a = acc.setdefault((sec, idx[c]), [0.0, 0])
                a[0] += vals[k * nc + c]; a[1] += 1
    for (sec, c), (s, n) in acc.items():
        rsrp[sec][c] = round(s / n, 1)
    return {
        "format": "horus.campus3d.route/1",
        "epochs_source": epochs_src,
        "provenance": {
            "positions": "Recorded phone GNSS positions (G-NetTrack, allowlisted structured export), 31 Oct 2026",
            "serving_eci": "Recorded serving cell of the LG U+ network during the walk",
            "calibrated_rsrp": "Lap-1 calibrated radio surface on the reverse route (release/reference/measured-trace); "
                               "supported segments only, null = outside stable support",
            "cell_anchor": "Median location of the top 5% measured serving RSRP rows (rows flagged "
                           "joint_signal_tuple_review excluded); no mast coordinates are known for these cells",
        },
        "cells": cells, "sessions": sessions,
        "trace": {"dt_s": dt, "trace_sha256": trace_meta["trace_sha256"], "segments": segments,
                  "assumptions": trace_meta["assumptions"], "rsrp_1s": rsrp},
    }


# ---------------------------------------------------------------- comparison (modelled)
def build_comparison():
    d = jload(POLICY)
    arms = ["selector_v3.39.0", "a3_stock", "cho_default", "a3_global"]
    out = {"format": "horus.campus3d.comparison/1", "kind": "modelled",
           "label": "TwinSim modelled replay on the calibrated reverse route (neighbour-assumption primary case)",
           "notes": "SINR, failures, load and throughput are modelled; RSRP is calibrated. Same route, same time "
                    "base, same assumptions for every arm. Not a field measurement and not the operator gate.",
           "plan_sha256": d["plan_sha256"], "arms": {}}
    for r in d["runs"]:
        if (r["session"], r["surface"], r["case"]) == ("t4-reverse", "neighbor_assumption", "primary") and r["arm"] in arms:
            m = r["metrics"]
            out["arms"][r["arm"]] = {
                "totals": {k: m[k] for k in ("ho_attempts", "ho_success", "ping_pongs", "rlf", "hof",
                                             "mean_thr_mbps", "utility_modelled", "duration_s")},
                "segments": [{"start_s": s["start_s"], "end_s": s["end_s"],
                              "ho": s["metrics"]["ho_attempts"], "pp": s["metrics"]["ping_pongs"],
                              "rlf": s["metrics"]["rlf"], "thr": s["metrics"]["mean_thr_mbps"]}
                             for s in r["segments"]]}
    return out


# ---------------------------------------------------------------- replay (recorded)
def cycle_record(cdir, kind):
    acts = jlines(cdir / "driver/timed-actions.jsonl")
    summ = jload(cdir / "driver/summary.json")
    state = jload(cdir / "dashboard-learned-state.json")
    if not acts:
        return None
    a0 = acts[0]
    anchor_ts, anchor_t = iso(a0["ts"]), round((a0["params"]["twin_step"] + 1) * 0.1, 1)
    to_t = lambda ts: round(anchor_t + (ts - anchor_ts), 2)
    events = []
    for i, a in enumerate(acts):
        p, lb = a["params"], a.get("latency_breakdown") or {}
        t = to_t(iso(a["ts"]))
        send = lb.get("decision_to_send_ms")
        ack = None if send is None or p.get("ric_control_ack_ms") is None else t + (send + p["ric_control_ack_ms"]) / 1000
        cu = t + a["latency_ms"] / 1000 if a.get("latency_ms") and p.get("rrc_handover_complete") else None
        prof = p["selector"]["selected_profile"]
        events.append({"id": f"{kind}-{cdir.name}-{i}", "step": p["twin_step"], "from": p["twin_from_cell"],
                       "to": p["twin_to_cell"],
                       "phases": {"decision": round(t, 2), "sent": round(t + send / 1000, 2) if send is not None else None,
                                  "ack": round(ack, 2) if ack else None, "cu_confirmed": round(cu, 2) if cu else None},
                       "profile": {"index": prof["index"], **prof["parameters"]},
                       "stage": p["selector"].get("selector_stage"),
                       "evidence": {"ric_ack_ms": p.get("ric_control_ack_ms"), "decision_to_cu_ms": a.get("latency_ms"),
                                    "source_du": p["source_du"], "target_du": p["target_du"],
                                    "completion_basis": p.get("completion_basis") or "ACK, DU transition and new CU RRC completion",
                                    "rrc_complete": p.get("rrc_handover_complete")}})
    rtt = []
    for ue, series in (state.get("rtt", {}).get("series") or {}).items():
        rtt += [[to_t(ts), v] for ts, v in series]
    rtt.sort()
    rt = summ["runtime"]
    return {"id": f"{kind}/{cdir.name}", "kind": kind, "events": events, "rtt": rtt,
            "rtt_window": [rtt[0][0], rtt[-1][0]] if rtt else None,
            "runtime": {k: rt[k] for k in ("candidate_version", "inference_calls", "fallback_frames", "invalid_frames", "model_faults")},
            "frames": summ["frames"], "confirmed_handovers": summ["confirmed_handovers"],
            "failed_controls": summ["failed_controls"], "native_cho_configured": summ["native_cho_configured"]}


def build_replay(route):
    frames = jlines(LIVE / "frames.jsonl")
    decisions = jlines(LIVE / "driver/decisions.jsonl")
    cells = frames[0]["cell_ids"]
    assert all(f["cell_ids"] == cells for f in frames)
    seg0 = route["trace"]["segments"][0]
    assert frames[0]["segment"] == "reverse-supported-0" and seg0["start"] == 0
    dec = {d["sequence"]: d for d in decisions}
    profile, stage, infer = [], [], []
    for f in frames:
        d = dec.get(f["sequence"])
        profile.append(d["selected_profiles"][0]["index"] if d else None)
        stage.append(d["selector_stage"] if d else None)
    cycles = []
    for cdir in [QUAL / "bounded/cycle-000"] + sorted((QUAL / "soak").glob("cycle-*")):
        c = cycle_record(cdir, "bounded" if "bounded" in cdir.parts else "soak")
        if c: cycles.append(c)
    soak = jload(QUAL / "soak/VERIFICATION.json")
    ev = [e for c in cycles if c["kind"] == "soak" for e in c["events"]]
    cu_ms = sorted(e["evidence"]["decision_to_cu_ms"] for e in ev if e["evidence"]["decision_to_cu_ms"])
    ack_ms = sorted(e["evidence"]["ric_ack_ms"] for e in ev if e["evidence"]["ric_ack_ms"] is not None)
    pct = lambda a, q: a[min(len(a) - 1, int(q * (len(a) - 1) + 0.5))] if a else None
    decision_steps = sorted({(e["step"], e["profile"]["index"]) for c in cycles for e in c["events"]})
    return {
        "format": "horus.campus3d.feed/1", "mode": "replay",
        "label": "Recorded qualified execution · v3.39.0 · reverse route segment 0",
        "provenance": {
            "kind": "recorded",
            "inputs": "Calibrated TwinSim observation stream for reverse segment 0, recorded 2 Nov 2026 "
                      "(working/evidence/selector-live-20261102/live/frames.jsonl); deterministic, replayed in every cycle",
            "execution": "Released actor d57229c, 4 Nov 2026: bounded acceptance cycle and 36 two-hour cycles "
                         "(working/evidence/qualified-release-20261104/)",
            "scope": "Emulated OAI RF (rfsim), ordinary F1 handovers between two DUs; CHO profiles execute in the twin. "
                     "Not field RAN actuation and not native RRC CHO.",
        },
        "scenario": {"id": "t4-reverse-seg0", "route": "t4-reverse", "segment": frames[0]["segment"],
                     "step0": 0, "dt_s": 0.1, "duration_s": round(frames[-1]["t_s"], 1)},
        "cells": cells,
        "frames": {"t_s": [round(f["t_s"], 1) for f in frames], "step": [f["sequence"] for f in frames],
                   "serving": [f["serving"][0] for f in frames],
                   "rsrp": [[r1(v) for v in f["l1"][0]] for f in frames],
                   "sinr_db": [r1(f["sinr_db"][0]) for f in frames],
                   "profile": profile, "stage": stage},
        "decision_steps_all_cycles": decision_steps,
        "cycles": cycles,
        "acceptance": {"passed": soak["passed"], "cycles": soak["cycles"], "frames": soak["frames"],
                       "inference_calls": soak["inference_calls"],
                       "confirmed_handovers": sum(c["confirmed_handovers"] for c in cycles if c["kind"] == "soak"),
                       "failed_controls": sum(c["failed_controls"] for c in cycles if c["kind"] == "soak"),
                       "decision_to_cu_ms": {"p50": pct(cu_ms, .5), "p95": pct(cu_ms, .95), "max": cu_ms[-1] if cu_ms else None},
                       "ric_ack_ms": {"p50": pct(ack_ms, .5), "p95": pct(ack_ms, .95), "max": ack_ms[-1] if ack_ms else None},
                       "native_seconds": 7290.291, "host_seconds": 8092.589,
                       "receipt": "working/evidence/qualified-release-20261104/soak/VERIFICATION.json"},
        "service": None,      # per-cycle RTT lives in cycles[].rtt; interruption metrics are pending (backend)
        "comparison": None,   # paired baseline execution on identical time/workload: pending (backend)
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="verify committed outputs match a fresh build")
    a = ap.parse_args()
    epochs, src = load_epochs()
    route = build_route(epochs, src)
    outputs = {"campus.json": build_campus(), "route.json": route,
               "comparison.json": build_comparison(), "replay-seg0.json": build_replay(route)}
    manifest = {"format": "horus.campus3d.manifest/1", "builder": "dashboard/campus3d/build_data.py",
                "inputs": dict(sorted(inputs.items())), "outputs": {}}
    blobs = {}
    for name, obj in outputs.items():
        b = (json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        blobs[name] = b
        manifest["outputs"][name] = {"bytes": len(b), "sha256": sha(b)}
    blobs["manifest.json"] = (json.dumps(manifest, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    if a.check:
        bad = [n for n, b in blobs.items() if not (OUT / n).exists() or (OUT / n).read_bytes() != b]
        print("up to date" if not bad else "STALE: " + ", ".join(bad))
        return 1 if bad else 0
    OUT.mkdir(exist_ok=True)
    for n, b in blobs.items():
        (OUT / n).write_bytes(b)
        print(f"{n:20s} {len(b):>9,d} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
