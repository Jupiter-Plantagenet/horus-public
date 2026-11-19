"""Allowlisted, non-destructive ZIP -> dataset/quality report for issue #6.

No raw archive extraction, raw telephony strings or subscriber identifiers are
written. Original bytes remain in the source ZIP; hashes make them traceable.
Run: python -m twin.walktest_ingest --archive PATH --session-config CONFIG --out DIR
"""
import argparse
import bisect
import csv
import hashlib
import io
import json
import math
import re
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath

from .walktest import _time, load_sites, parse_gnettrack
from .cellmatch import build_cells, load_catalog, match_ids, match_summary


def digest(data):
    return hashlib.sha256(data).hexdigest()


def source_digest(path):
    """Git checkout line-ending conversion must not change code identity."""
    return digest(Path(path).read_bytes().replace(b"\r\n", b"\n"))


def stats(values):
    v = sorted(x for x in values if x is not None and math.isfinite(x))
    def quantile(q):
        i = (len(v) - 1) * q
        j = int(i)
        return v[j] + (v[min(j + 1, len(v) - 1)] - v[j]) * (i - j)
    return {"n": len(v), "min": v[0], "median": quantile(.5), "p95": quantile(.95), "max": v[-1]} if v else {"n": 0}


def normalize_mark(label):
    """Return direction, stop, event; preserve source label separately."""
    s = label.upper().replace("ARIVE", "ARRIVE")
    m = re.fullmatch(r"(FWD|RW|RWD)_(?:S)?(P|\d+)_?(START|ARRIVE|DEPART|STOP)", s)
    if not m:
        raise ValueError("Unrecognized filemark; review label locally before exporting")
    return ("forward" if m[1] == "FWD" else "reverse", "P" if m[2] == "P" else str(int(m[2])), m[3].lower())


def parse_marks(data, offset):
    marks = []
    for p in ET.fromstring(data).findall(".//{*}Placemark"):
        fields = {e.attrib["name"]: e.findtext("{*}value") for e in p.findall(".//{*}Data")}
        label = p.findtext("{*}name")
        direction, stop, event = normalize_mark(label)
        coord = p.findtext(".//{*}coordinates").split(",")
        time = _time(fields.get("TIME"), None, offset)
        if time is None:
            raise ValueError("Filemark has invalid time")
        marks.append(dict(label=label, direction=direction, stop=stop, event=event,
                          timestamp=fields["TIME"], t=time, lon=float(coord[0]), lat=float(coord[1])))
    if any(b["t"] < a["t"] for a, b in zip(marks, marks[1:])):
        raise ValueError("Filemarks are not chronological")
    return marks


def hold_intervals(marks, end, final_hold):
    holds = []
    for a, b in zip(marks, marks[1:]):
        if a["event"] in {"start", "arrive"} and b["event"] == "depart":
            if a["stop"] != b["stop"] or a["direction"] != b["direction"]:
                raise ValueError("Mismatched filemark hold pair")
            holds.append(dict(stop=a["stop"], start=a["t"], end=b["t"], source="paired_filemarks"))
    if final_hold:
        last = marks[-1]
        if last["event"] not in {"arrive", "stop"} or last["t"] > end:
            raise ValueError("Final hold requires a valid arrival/stop mark")
        holds.append(dict(stop=last["stop"], start=last["t"], end=end,
                          source="user_declared_final_stop", declared_seconds=final_hold))
    return holds


def radio_frames(data, offset):
    """Extract registered LTE facts, never copy unstructured diagnostics.

    A logger-time join is approximate. Android elapsed-realtime timestamps are
    not converted to wall time; this is not independent modem ground truth.
    """
    frames = []
    for r in csv.DictReader(io.StringIO(data.decode("utf-8-sig")), delimiter="\t"):
        t = _time(r.get("Timestamp"), None, offset)
        if t is None:
            continue
        blocks = re.findall(r"CellInfoLte:(.*?)(?=CellInfo\w+:|$)", r.get("NewFunctions", ""))
        for block in blocks:
            if not re.search(r"mRegistered=YES\b", block):
                continue
            def number(pattern):
                m = re.search(pattern, block)
                return int(m[1]) if m else None
            frames.append(dict(t=t, registered=True,
                               modem_timestamp_ns=number(r"mTimeStamp=(\d+)ns"),
                               mcc=number(r"mMcc=(\d+)"), mnc=number(r"mMnc=(\d+)"),
                               rsrp=number(r"\brsrp=(-?\d+)"), rsrq=number(r"\brsrq=(-?\d+)"),
                               rssi=number(r"\brssi=(-?\d+)")))
    return frames


def compatible_frame(epoch, frames, times, maximum_age_s=3):
    """Last causal logger record matching PLMN AND available signal facts.

    Without a full cell identity in Android's dump this is still a proxy, not
    a proof of acquisition identity. Mismatching records must not merge samples.
    """
    j=bisect.bisect_right(times,epoch["t"])-1
    while j>=0 and epoch["t"]-times[j]<=maximum_age_s:
        f=frames[j]
        if ((f["mcc"],f["mnc"])==(epoch["mcc"],epoch["mnc"])
                and f["modem_timestamp_ns"] is not None
                and all(epoch.get(k) is None or f.get(k)==epoch[k] for k in ("rsrp","rsrq","rssi"))):
            return dict(f,logger_join_age_s=epoch["t"]-f["t"],observation_matches=True)
        j-=1
    return None


def ingest(archive, config, out):
    archive, out = Path(archive), Path(out)
    if any(out.resolve() == p or p in out.resolve().parents for p in [archive.resolve()]):
        raise ValueError("Output must differ from source archive")
    out.mkdir(parents=True, exist_ok=True)
    doc = load_sites()
    manifest = {"format": "horus-walk-dataset-v1", "source_zip_sha256": digest(archive.read_bytes()),
                "timezone": config["timezone"], "utc_offset_hours": config["utc_offset_hours"],
                "session_context": config, "members": [],
                "privacy": "Allowlisted structured fields only; no raw diagnostic strings or subscriber identifiers.",
                "split": "lap 1 development; lap 2 evaluation only (already descriptively audited)",
                "rsrp_reference": "https://developer.android.com/reference/android/telephony/CellSignalStrengthLte#getRsrp()"}
    manifest["source_code_sha256"] = {p.name:source_digest(p) for p in
                                     [Path(__file__),Path(__file__).with_name("walktest.py"),Path(__file__).with_name("cellmatch.py")]}
    catalog_path=Path(__file__).resolve().parents[2]/"data"/"opencellid"/"kumoh-cell-ids.json"
    manifest["catalogue_sha256"]=digest(catalog_path.read_bytes()) if catalog_path.exists() else None
    try:
        manifest["base_commit"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parents[2], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        manifest["base_commit"] = "unknown"
    all_epochs, all_marks, all_holds, summaries = [], [], [], []
    with zipfile.ZipFile(archive) as z:
        for session in config["sessions"]:
            main = [n for n in z.namelist() if PurePosixPath(n).name == session["stem"] + ".txt"]
            if len(main) != 1:
                raise ValueError("Session selection must match exactly one main log")
            name = main[0]
            members = {}
            for kind, suffix in [("main", ".txt"), ("marks", "_filemarks.kml"), ("verbose", "_verboselog.txt")]:
                member = name[:-4] + suffix
                raw = z.read(member)
                members[kind] = raw
                manifest["members"].append(dict(session=session["id"], kind=kind, member=member,
                                                 bytes=len(raw), sha256=digest(raw)))
            epochs, report = parse_gnettrack(name, doc["campus_centre"], text=members["main"].decode("utf-8-sig"),
                                             utc_offset_hours=config["utc_offset_hours"])
            if not epochs or any("timestamp_fallback" in e["flags"] for e in epochs):
                raise ValueError("Session has no accepted epochs or invalid timestamps")
            times = [e["t"] for e in epochs]
            if any(b < a for a, b in zip(times, times[1:])):
                raise ValueError("Backwards logger timestamps need explicit review")
            marks = parse_marks(members["marks"], config["utc_offset_hours"])
            if any(m["direction"] != session["direction"] for m in marks):
                raise ValueError("Filemark direction disagrees with session configuration")
            if any(not times[0] <= m["t"] <= times[-1] for m in marks):
                raise ValueError("Filemark lies outside recorded session")
            holds = hold_intervals(marks, times[-1], session.get("final_hold_seconds"))
            frames = radio_frames(members["verbose"], config["utc_offset_hours"])
            if any(b["t"] < a["t"] for a, b in zip(frames, frames[1:])):
                raise ValueError("Backwards verbose timestamps need review")
            frame_times = [r["t"] for r in frames]
            last_fingerprint = None
            for i, e in enumerate(epochs):
                e.update(session=session["id"], lap=session["lap"], split=session["split"], phase="between_marks", stop=None, settled=False)
                for h in holds:
                    if h["start"] <= e["t"] <= h["end"]:
                        e.update(phase="marked_hold", stop=h["stop"], settled=e["t"]-h["start"] >= config["settling_seconds"])
                        break
                if (e["mcc"], e["mnc"]) != tuple(config["expected_plmn"]):
                    e["flags"].append("unexpected_operator")
                frame = compatible_frame(e,frames,frame_times)
                e["source_link"] = frame
                if frame is None:
                    e["flags"].append("radio_source_unlinked")
                modem = frame["modem_timestamp_ns"] if frame else None
                # This is an approximate cache grouping, not a globally unique
                # physical acquisition ID. Full identity prevents cross-cell merging.
                fp = (e["cell"], e["earfcn"], modem) if modem else None
                if fp is not None and fp == last_fingerprint:
                    e["flags"].append("cached_radio_timestamp")
                last_fingerprint = fp
                if i and e["t"] > epochs[i-1]["t"]:
                    speed = math.hypot(e["x"]-epochs[i-1]["x"], e["y"]-epochs[i-1]["y"])/(e["t"]-epochs[i-1]["t"])
                    if speed > 12:
                        e["flags"].append("adjacent_position_speed_review")
            for h in holds:
                group = [e for e in epochs if h["start"] <= e["t"] <= h["end"]]
                zeros = [e for e in group if e["speed_kmh"] == 0]
                h.update(session=session["id"], duration_s=h["end"]-h["start"], rows=len(group),
                         first_zero_delay_s=zeros[0]["t"]-h["start"] if zeros else None,
                         all_rsrp=stats(e["rsrp"] for e in group),
                         settled_rsrp=stats(e["rsrp"] for e in group if e["settled"]),
                         settled_review_filtered_rsrp=stats(e["rsrp"] for e in group if e["settled"] and "joint_signal_tuple_review" not in e["flags"]))
            dt = [b-a for a, b in zip(times, times[1:])]
            cells = build_cells(epochs)
            match_ids(cells, doc, load_catalog())  # identities only: no centroid substitution
            inventory = [dict(cell=list(k), earfcn=v["earfcn"], pci=v["pci"], samples=v["n_serving"], match=v["match"], emitter=v["emitter"]) for k,v in sorted(cells.items())]
            summary = dict(session=session["id"], parse=report, first=epochs[0]["timestamp"], last=epochs[-1]["timestamp"],
                           duration_s=times[-1]-times[0], intervals_s=stats(dt), exact_time_duplicates=sum(d==0 for d in dt),
                           flags=dict(Counter(f for e in epochs for f in e["flags"])),
                           identities=inventory, catalog_identity_match=match_summary(cells), filemarks=len(marks),
                           rows=len(epochs), raw_gps_path_m=sum(math.hypot(b["x"]-a["x"],b["y"]-a["y"]) for a,b in zip(epochs,epochs[1:])),
                           registered_lte_frames=len(frames), unique_registered_modem_timestamps=len({r["modem_timestamp_ns"] for r in frames if r["modem_timestamp_ns"] is not None}),
                           radio_new_age_s=stats(e["new_age_s"] for e in epochs), radio_old_age_s=stats(e["old_age_s"] for e in epochs))
            summaries.append(summary)
            all_epochs.extend(epochs)
            all_marks.extend(dict(m,session=session["id"]) for m in marks)
            all_holds.extend(holds)
    def write(name, value):
        (out/name).write_text(json.dumps(value, indent=2, allow_nan=False)+"\n", encoding="utf-8",newline="\n")
    with (out/"epochs.jsonl").open("w", encoding="utf-8",newline="\n") as f:
        for e in all_epochs:
            f.write(json.dumps(e, separators=(",",":"), allow_nan=False)+"\n")
    write("filemarks.json", all_marks)
    write("holds.json", all_holds)
    write("quality.json", {"sessions":summaries, "dropped_by_track_cleaning":0,
                           "note":"No speed-based sample deletion; reported speed is not stop ground truth."})
    manifest["output_sha256"] = {p.name:digest(p.read_bytes()) for p in sorted(out.iterdir()) if p.name in {"epochs.jsonl","filemarks.json","holds.json","quality.json"}}
    write("manifest.json", manifest)
    lines = ["# T4 dataset quality report", "", "Generated without extracting or modifying the original ZIP.",
             "", "| Session | Rows | Duration (s) | Tuple flags | Catalog identity matches |", "|---|---:|---:|---:|---:|"]
    for s in summaries:
        lines.append(f"| {s['session']} | {s['rows']} | {s['duration_s']:.3f} | {s['flags'].get('joint_signal_tuple_review',0)} | {s['catalog_identity_match']['pct_cells_id_any']}% |")
    lines += ["", "## Interpretation", "", "Lap 1 is development; lap 2 is evaluation-only and has already received descriptive QA.",
              "Repeated modem timestamps are flagged, not counted as independent acquisitions or discarded.",
              "The verbose-to-main timestamp join is approximate; a registered flag is reported Android state, not independent network verification.",
              "Stationary periods come from filemarks/user context. Both all-sample and 15-second-settled summaries are retained.",
              "The joint -44/-3/-113 tuple is retained. Its cause and whether it represents clipping are not established.",
              "Catalog matches use identity only. Unmatched cells are not assigned to arbitrary nearby sites.",
              "No SNR, throughput or network-side handover validation is inferred from these logs.",
              "", "See manifest.json for source/member/output hashes and the supplied device/session context."]
    (out/"QUALITY.md").write_text("\n".join(lines)+"\n",encoding="utf-8",newline="\n")
    return summaries


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--archive",required=True,type=Path)
    p.add_argument("--session-config",required=True,type=Path)
    p.add_argument("--out",required=True,type=Path)
    a=p.parse_args()
    summaries=ingest(a.archive,json.loads(a.session_config.read_text(encoding="utf-8")),a.out)
    print(json.dumps([dict(session=s["session"],rows=s["rows"],flags=s["flags"],catalog_match=s["catalog_identity_match"]) for s in summaries],indent=2))


if __name__=="__main__":
    main()
