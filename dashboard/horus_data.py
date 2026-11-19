#!/usr/bin/env python3
"""HORUS finals dashboard — data layer (pure parsers + state builder).

Everything the dashboard shows comes from files the system already produces
(or that a producing agent writes to a documented contract — see
dashboard/CONTRACTS.md). This module only READS; it never touches the stack.

Design rule that makes LIVE and REPLAY indistinguishable: every reader takes a
``now`` (epoch seconds). Live passes wall-clock time; replay passes a virtual
clock walking through a recorded bundle at real speed. Records stamped after
``now`` are invisible, so a recorded bundle "plays" exactly like the live feed,
through the very same code path.

Every reader degrades gracefully: a missing file, an empty file, a torn final
line (writer mid-append), or a malformed record yields an empty/partial result,
never an exception.

stdlib only (python3 >= 3.8).
"""

import glob
import json
import math
import os
import re
from datetime import datetime, timezone

VERSION_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")

# Windows (seconds) the panels summarise over. Kept here so tests and docs agree.
STATS_WINDOW_S = 60        # tiles: p50/p95/mean over the last minute
CHART_WINDOW_S = 180       # line charts: last three minutes
EFFECT_BEFORE_S = 10       # actuation effect: mean DL over [t-10, t)
EFFECT_SETTLE_S = 2        # ... skip the first 2 s after the action
EFFECT_AFTER_S = 10        # ... then mean DL over (t+2, t+12]
FRESH_FAST_S = 5           # rtt / tput are ~1 Hz: older than 5 s = stale
FRESH_KPM_S = 30           # KPM indications are ~10 s cadence
HEALTH_STALE_S = 30        # a health probe record older than this is ignored
MAX_POINTS = 240           # chart series are bucket-averaged down to this


# ------------------------------------------------------------------ basics --

def parse_version(v):
    m = VERSION_RE.match(v) if isinstance(v, str) else None
    return tuple(int(x) for x in m.groups()) if m else None


def parse_ts(v):
    """ISO-8601 string (Z or offset) or epoch seconds/millis -> epoch float, else None."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        if not math.isfinite(v):
            return None
        return v / 1000.0 if v > 1e11 else float(v)   # tolerate epoch-ms
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        try:
            if re.fullmatch(r"\d+(\.\d+)?", s):
                return parse_ts(float(s))
            return _iso(s)
        except ValueError:
            return None
    return None


def _iso(s):
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if d.tzinfo is None:                   # contract says UTC; naive = UTC
        d = d.replace(tzinfo=timezone.utc)
    return d.timestamp()


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if t else None


def num(v):
    """A finite float or None (rejects bools, strings, NaN)."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v) if math.isfinite(v) else None


def percentile(values, p):
    """Linear-interpolated percentile (p in 0..100); None for empty input."""
    xs = sorted(v for v in values if v is not None)
    if not xs:
        return None
    if len(xs) == 1:
        return xs[0]
    k = (len(xs) - 1) * p / 100.0
    lo, hi = math.floor(k), math.ceil(k)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def mean(values):
    xs = [v for v in values if v is not None]
    return sum(xs) / len(xs) if xs else None


def rnd(v, n=2):
    return None if v is None else round(v, n)


def downsample(points, max_points=MAX_POINTS):
    """[(t, v)] -> at most max_points by bucket-averaging (keeps shape, bounds payload)."""
    if len(points) <= max_points:
        return [[round(t, 3), rnd(v, 3)] for t, v in points]
    size = len(points) / max_points
    out = []
    for i in range(max_points):
        chunk = points[int(i * size):int((i + 1) * size)] or [points[-1]]
        vals = [v for _, v in chunk if v is not None]
        out.append([round(chunk[-1][0], 3), rnd(sum(vals) / len(vals), 3) if vals else None])
    return out


# --------------------------------------------------------------- file I/O --

def read_jsonl(path, now=None, ts_keys=("ts",), tail_bytes=None):
    """Parse a JSONL file into dicts carrying ``_t`` (epoch). Skips blank, torn
    and non-object lines and records without a parseable timestamp; drops records
    stamped after ``now`` (replay clock). ``tail_bytes`` bounds the read on large
    live files (the partial first line of the tail is discarded). Missing file -> []."""
    try:
        with open(path, "rb") as fh:
            if tail_bytes:
                fh.seek(0, os.SEEK_END)
                size = fh.tell()
                if size > tail_bytes:
                    fh.seek(size - tail_bytes)
                    fh.readline()          # discard the partial line we landed in
                else:
                    fh.seek(0)
            raw = fh.read()
    except OSError:
        return []
    out = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue                       # torn final line during an append
        if not isinstance(rec, dict):
            continue
        t = None
        for k in ts_keys:
            t = parse_ts(_dig(rec, k))
            if t is not None:
                break
        if t is None or (now is not None and t > now + 0.5):
            continue
        rec["_t"] = t
        out.append(rec)
    out.sort(key=lambda r: r["_t"])
    return out


def _dig(d, dotted):
    for part in dotted.split("."):
        if not isinstance(d, dict):
            return None
        d = d.get(part)
    return d


def read_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            v = json.load(fh)
        return v if isinstance(v, dict) else None
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


_count_cache = {}


def count_lines(path):
    """Line count, cached on (size, mtime) so a 1 Hz poll over a big archive is cheap."""
    try:
        st = os.stat(path)
    except OSError:
        return 0
    key = (path, st.st_size, st.st_mtime)
    if key not in _count_cache:
        with open(path, "rb") as fh:
            _count_cache[key] = sum(1 for _ in fh)
    return _count_cache[key]


# ------------------------------------------------------- metric streams --

def rtt_state(rows, now, stats_window=STATS_WINDOW_S, chart_window=CHART_WINDOW_S):
    """rows: working/metrics/rtt.jsonl records {ts, ue, rtt_ms}. rtt_ms null/absent
    or ``lost: true`` counts as a lost probe (loss %), never as a latency value."""
    per_ue, series = {}, {}
    for r in rows:
        ue = str(r.get("ue") or "ue?")
        v = num(r.get("rtt_ms"))
        if r.get("lost") is True or (v is not None and v < 0):
            v = None
        if now - r["_t"] <= chart_window:
            series.setdefault(ue, []).append((r["_t"], v))
        if now - r["_t"] <= stats_window:
            per_ue.setdefault(ue, []).append(v)
    ues = {}
    for ue, vals in per_ue.items():
        ok = [v for v in vals if v is not None]
        jitter = mean([abs(a - b) for a, b in zip(ok, ok[1:])]) if len(ok) > 1 else None
        ues[ue] = {
            "n": len(vals), "last": rnd(ok[-1]) if ok else None,
            "p50": rnd(percentile(ok, 50)), "p95": rnd(percentile(ok, 95)),
            "max": rnd(max(ok)) if ok else None, "jitter": rnd(jitter),
            "loss_pct": rnd(100.0 * (len(vals) - len(ok)) / len(vals), 1) if vals else None,
        }
    allv = [v for vals in per_ue.values() for v in vals if v is not None]
    last_t = rows[-1]["_t"] if rows else None
    return {
        "ues": ues,
        "all": {"p50": rnd(percentile(allv, 50)), "p95": rnd(percentile(allv, 95)),
                "n": sum(len(v) for v in per_ue.values())},
        "series": {ue: downsample(p) for ue, p in series.items()},
        "last_t": last_t, "age_s": rnd(now - last_t, 1) if last_t else None,
    }


def tput_state(rows, now, stats_window=STATS_WINDOW_S, chart_window=CHART_WINDOW_S):
    """rows: working/metrics/tput.jsonl records {ts, ue, dl_mbps, ul_mbps}."""
    per_ue, series = {}, {}
    for r in rows:
        ue = str(r.get("ue") or "ue?")
        dl, ul = num(r.get("dl_mbps")), num(r.get("ul_mbps"))
        dl = dl if dl is None or dl >= 0 else None
        ul = ul if ul is None or ul >= 0 else None
        if now - r["_t"] <= chart_window:
            s = series.setdefault(ue, {"dl": [], "ul": []})
            s["dl"].append((r["_t"], dl))
            s["ul"].append((r["_t"], ul))
        if now - r["_t"] <= stats_window:
            per_ue.setdefault(ue, []).append((dl, ul))
    ues = {}
    for ue, vals in per_ue.items():
        dls = [d for d, _ in vals if d is not None]
        uls = [u for _, u in vals if u is not None]
        ues[ue] = {"n": len(vals),
                   "dl_last": rnd(dls[-1]) if dls else None, "dl_mean": rnd(mean(dls)),
                   "dl_peak": rnd(max(dls)) if dls else None,
                   "ul_last": rnd(uls[-1]) if uls else None, "ul_mean": rnd(mean(uls)),
                   "ul_peak": rnd(max(uls)) if uls else None}
    last_t = rows[-1]["_t"] if rows else None
    agg = lambda k: rnd(sum(u[k] for u in ues.values() if u[k] is not None)) \
        if any(u[k] is not None for u in ues.values()) else None
    return {
        "ues": ues,
        "total": {"dl_last": agg("dl_last"), "dl_mean": agg("dl_mean"),
                  "ul_last": agg("ul_last"), "ul_mean": agg("ul_mean")},
        "series": {ue: {"dl": downsample(s["dl"]), "ul": downsample(s["ul"])}
                   for ue, s in series.items()},
        "last_t": last_t, "age_s": rnd(now - last_t, 1) if last_t else None,
    }


def kpm_state(kpm_dir, now, replay=False, chart_window=600):
    """Existing KPM archive (schemas/kpm_record.schema.json) in working/kpm/."""
    files = sorted(glob.glob(os.path.join(kpm_dir, "kpm*.jsonl")))
    current = os.path.join(kpm_dir, "kpm.jsonl")
    rows = read_jsonl(current, now=now, tail_bytes=None if replay else 400_000)
    total = len(rows) if replay else sum(count_lines(f) for f in files)
    recent = [r for r in rows if now - r["_t"] <= chart_window]
    last_t = rows[-1]["_t"] if rows else None
    in10 = [r for r in rows if now - r["_t"] <= 600]
    return {
        "total_rows": total, "files": len(files),
        "rows_per_min": rnd(len(in10) / 10.0, 1),
        "rsrp": downsample([(r["_t"], num(r.get("rsrp_dbm"))) for r in recent]),
        "thp": downsample([(r["_t"], num(r.get("throughput_mbps"))) for r in recent]),
        "last": {k: rows[-1].get(k) for k in ("ue_id", "serving_cell_id", "rsrp_dbm",
                                               "throughput_mbps", "source")} if rows else None,
        "last_t": last_t, "age_s": rnd(now - last_t, 1) if last_t else None,
    }


# ------------------------------------------------------------- actuation --

OK_RESULTS = {"ok", "success", "acked", "ack", "applied"}


def _window_mean(tput_rows, ue, t0, t1, closed_left=False):
    """Mean DL Mbps in (t0, t1] — or [t0, t1) with closed_left — for one UE
    ('*'/'cell'/None/'all' = cell level: sum over UEs per 1-s sample)."""
    inside = (lambda t: t0 <= t < t1) if closed_left else (lambda t: t0 < t <= t1)
    if ue in (None, "", "*", "cell", "all"):
        buckets = {}
        for r in tput_rows:
            if inside(r["_t"]) and num(r.get("dl_mbps")) is not None:
                buckets.setdefault(int(r["_t"]), 0.0)
                buckets[int(r["_t"])] += r["dl_mbps"]
        return mean(list(buckets.values()))
    return mean([num(r.get("dl_mbps")) for r in tput_rows
                 if str(r.get("ue")) == str(ue) and inside(r["_t"])])


def action_effect(action, tput_rows, now):
    """Throughput before/after an actuated action. An explicit ``effect`` object
    on the record (producer-measured) wins; otherwise it is derived from tput."""
    eff = action.get("effect")
    if isinstance(eff, dict) and num(eff.get("dl_before_mbps")) is not None \
            and num(eff.get("dl_after_mbps")) is not None:
        b, a = eff["dl_before_mbps"], eff["dl_after_mbps"]
        return {"status": "measured", "source": "producer", "dl_before": rnd(b), "dl_after": rnd(a),
                "delta_pct": rnd(100.0 * (a - b) / b, 1) if b else None}
    t = action["_t"]
    if now < t + EFFECT_SETTLE_S + EFFECT_AFTER_S:
        return {"status": "measuring", "source": "tput",
                "ready_in_s": rnd(t + EFFECT_SETTLE_S + EFFECT_AFTER_S - now, 0)}
    ue = action.get("ue")
    b = _window_mean(tput_rows, ue, t - EFFECT_BEFORE_S, t, closed_left=True)
    a = _window_mean(tput_rows, ue, t + EFFECT_SETTLE_S, t + EFFECT_SETTLE_S + EFFECT_AFTER_S)
    if b is None or a is None:
        return {"status": "no-data", "source": "tput"}
    return {"status": "measured", "source": "tput", "dl_before": rnd(b), "dl_after": rnd(a),
            "delta_pct": rnd(100.0 * (a - b) / b, 1) if b else None}


def actuation_state(action_rows, shadow_rows, tput_rows, now, limit=40):
    acts = []
    for r in action_rows:
        res = str(r.get("result", "")).lower()
        acts.append({
            "kind": "actuated", "t": r["_t"], "ts": iso(r["_t"]),
            "ue": r.get("ue"), "policy_version": r.get("policy_version"),
            "action": r.get("action"), "target": r.get("target"),
            "params": r.get("params") if isinstance(r.get("params"), dict) else {},
            "result": r.get("result"), "ok": res in OK_RESULTS,
            "latency_ms": rnd(num(r.get("latency_ms"))),
            "trigger": r.get("trigger") if isinstance(r.get("trigger"), (dict, str)) else None,
        })
    for a, r in zip(acts, action_rows):
        a["effect"] = action_effect(r, tput_rows, now) if a["ok"] else {"status": "not-applied"}
    shadows = []
    for r in shadow_rows:
        if r.get("issued") is True:
            continue                       # only would-issue records are shadow
        rc = r.get("ric_control") if isinstance(r.get("ric_control"), dict) else {}
        trig = r.get("trigger") if isinstance(r.get("trigger"), dict) else {}
        shadows.append({
            "kind": "shadow", "t": r["_t"], "ts": iso(r["_t"]),
            "ue": rc.get("ue_id"), "policy_version": r.get("policy_version"),
            "action": (r.get("decision") or "HANDOVER").lower(),
            "target": rc.get("target_cell"), "serving": rc.get("serving_cell"),
            "rsrp_dbm": num(trig.get("observed_rsrp_dbm")), "rule": trig.get("rule"),
            "not_sent_because": r.get("not_sent_because"),
            "ric": {"style": rc.get("control_style"), "action_id": rc.get("control_action_id"),
                    "ran_function": rc.get("ran_function")},
        })
    ok = [a for a in acts if a["ok"]]
    # decision latency = decision -> RIC control ack; a failed/timed-out control has
    # no ack, so its latency_ms (often the timeout) is excluded from the statistics.
    lats = [a["latency_ms"] for a in ok if a["latency_ms"] is not None]
    measured = [a["effect"]["delta_pct"] for a in ok
                if a["effect"].get("status") == "measured" and a["effect"].get("delta_pct") is not None]
    feed = sorted(acts + shadows, key=lambda x: x["t"], reverse=True)[:limit]
    last_act = acts[-1] if acts else None
    return {
        "feed": feed,
        "focus": next((a for a in reversed(acts) if a["ok"]), last_act),
        "counts": {"actuated": len(acts), "ok": len(ok), "failed": len(acts) - len(ok),
                   "shadow": len(shadows)},
        "latency": {"p50": rnd(percentile(lats, 50)), "p95": rnd(percentile(lats, 95)),
                    "max": rnd(max(lats)) if lats else None, "n": len(lats),
                    "hist": _hist(lats)},
        "success_pct": rnd(100.0 * len(ok) / len(acts), 1) if acts else None,
        "effect_median_pct": rnd(percentile(measured, 50), 1),
        "last_t": acts[-1]["t"] if acts else None,
        "last_shadow_t": shadows[-1]["t"] if shadows else None,
    }


def _hist(values, bins=12):
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi == lo:
        lo, hi = lo - 1.0, hi + 1.0
    w = (hi - lo) / bins
    counts = [0] * bins
    for v in values:
        counts[min(int((v - lo) / w), bins - 1)] += 1
    return [[rnd(lo + i * w), rnd(lo + (i + 1) * w), c] for i, c in enumerate(counts)]


def tput_window(tput_rows, ue, t0, t1):
    """DL series for one UE (or all, summed) between t0 and t1 — for the effect chart."""
    if ue in (None, "", "*", "cell", "all"):
        b = {}
        for r in tput_rows:
            if t0 <= r["_t"] <= t1 and num(r.get("dl_mbps")) is not None:
                b[int(r["_t"])] = b.get(int(r["_t"]), 0.0) + r["dl_mbps"]
        return downsample(sorted((float(k), v) for k, v in b.items()))
    return downsample([(r["_t"], num(r.get("dl_mbps"))) for r in tput_rows
                       if str(r.get("ue")) == str(ue) and t0 <= r["_t"] <= t1])


# -------------------------------------------------------------- pipeline --

GATE_RE = re.compile(
    r"^(?P<ts>\S+)\s+GATE\s+(?P<verdict>PROMOTE|REJECT|PENDING)\s+(?P<version>v\d+\.\d+\.\d+)\s+"
    r"worst=(?P<worst>[\d.]+)\s+\(threshold\s+(?P<thr>[\d.]+)(?:,\s*worst case:\s*(?P<wc>[^)]*))?\)"
    r"(?:.*?suite=(?P<suite>\S+))?(?:.*?aggregation=(?P<agg>\S+))?(?:.*?artifact=(?P<art>\S+))?")


def parse_gate_log(path, now=None):
    """stack gate log lines -> [{t, version, verdict, worst, threshold, worst_case, suite, ...}]."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        m = GATE_RE.match(line.strip())
        if not m:
            continue
        t = parse_ts(m["ts"])
        if t is None or (now is not None and t > now + 0.5):
            continue
        out.append({"t": t, "version": m["version"], "verdict": m["verdict"].lower(),
                    "worst": float(m["worst"]), "threshold": float(m["thr"]),
                    "worst_case": (m["wc"] or "").strip() or None, "suite": m["suite"],
                    "aggregation": m["agg"], "artifact": m["art"]})
    return out


def read_artifacts(dirs, now=None):
    """Policy artifacts (schemas/policy_artifact.schema.json) from the store and the
    candidates dir. Replay: an artifact not yet created at ``now`` is hidden; one
    created but not yet gated shows as awaiting the gate."""
    seen, arts = {}, []
    for d in dirs:
        if not d or not os.path.isdir(d):
            continue
        in_store = os.path.basename(os.path.normpath(d)) == "policies"
        for f in sorted(glob.glob(os.path.join(d, "*.json"))):
            a = read_json(f)
            if not a or not parse_version(a.get("version")):
                continue
            created = parse_ts(a.get("created_ts"))
            if now is not None and created is not None and created > now + 0.5:
                continue
            gate = a.get("gate") if isinstance(a.get("gate"), dict) else {}
            ev_t = parse_ts(gate.get("evaluated_ts"))
            v = a["version"]
            if v in seen:                  # same version in store + candidates: merge
                seen[v]["in_store"] = seen[v]["in_store"] or in_store
                continue
            rec = {"version": v, "algo": a.get("algo"), "file": os.path.basename(f),
                   "in_store": in_store, "created_t": created,
                   "provenance": a.get("provenance") if isinstance(a.get("provenance"), dict) else None,
                   "trained_on": a.get("trained_on") if isinstance(a.get("trained_on"), dict) else None,
                   "gate": dict(gate), "gate_t": ev_t}
            if now is not None and ev_t is not None and ev_t > now + 0.5:
                rec["gate"] = {"verdict": "pending", "threshold": gate.get("threshold")}
                rec["gate_t"] = None
                rec["in_store"] = False    # cannot be in the store before it is promoted
            seen[v] = rec
            arts.append(rec)
    return arts


def stage_of(a):
    v = (a.get("gate") or {}).get("verdict")
    if v == "promote":
        return "promoted"
    if v == "reject":
        return "rejected"
    if v == "pending":
        return "gating"
    return "federated" if a.get("provenance") else "trained"


def pipeline_state(store_dir, cand_dir, gate_log_paths, now, xapp_active=None):
    arts = read_artifacts([store_dir, cand_dir], now=now)
    events = []
    for p in gate_log_paths:
        events.extend(parse_gate_log(p, now=now))
    by_v = {}
    for e in events:
        by_v.setdefault(e["version"], e)  # earliest line per version
        if e["t"] >= by_v[e["version"]]["t"]:
            by_v[e["version"]] = e
    known = {a["version"] for a in arts}
    # gate-log versions with no artifact file still deserve a card (log is evidence)
    for v, e in by_v.items():
        if v not in known:
            arts.append({"version": v, "algo": None, "file": e.get("artifact"), "in_store": False,
                         "created_t": None, "provenance": {"aggregation": e.get("aggregation")},
                         "trained_on": None, "gate_t": e["t"],
                         "gate": {"verdict": e["verdict"], "worst_case_score": e["worst"],
                                  "threshold": e["threshold"], "scenario_suite": e.get("suite")}})
    cards = []
    for a in arts:
        g = a.get("gate") or {}
        e = by_v.get(a["version"]) or {}
        prov = a.get("provenance") or {}
        clients = prov.get("client_ids") if isinstance(prov.get("client_ids"), list) else []
        worst = num(g.get("worst_case_score"))
        thr = num(g.get("threshold"))
        cards.append({
            "version": a["version"], "algo": a.get("algo"), "file": a.get("file"),
            "stage": stage_of(a), "in_store": a["in_store"],
            "aggregation": prov.get("aggregation"), "round": prov.get("round"),
            "clients": [str(c) for c in clients],
            "poisoned": any("poison" in str(c).lower() for c in clients) or
                        "poison" in str(a.get("file") or "").lower(),
            "worst": worst if worst is not None else e.get("worst"),
            "threshold": thr if thr is not None else e.get("threshold"),
            "worst_case": e.get("worst_case"), "suite": g.get("scenario_suite") or e.get("suite"),
            "gate_t": a.get("gate_t") or e.get("t"), "gate_ts": iso(a.get("gate_t") or e.get("t")),
        })
    cards.sort(key=lambda c: parse_version(c["version"]) or (0, 0, 0), reverse=True)
    promoted_in_store = [c for c in cards if c["in_store"] and c["stage"] == "promoted"]
    active_store = promoted_in_store[0]["version"] if promoted_in_store else None
    for c in cards:
        c["active"] = c["version"] == (xapp_active or active_store)
    timeline = sorted(
        [{"t": c["gate_t"], "version": c["version"], "verdict": c["stage"],
          "worst": c["worst"], "threshold": c["threshold"], "aggregation": c["aggregation"],
          "poisoned": c["poisoned"], "worst_case": c["worst_case"]}
         for c in cards if c["gate_t"] and c["stage"] in ("promoted", "rejected")],
        key=lambda e: e["t"])
    counts = {s: sum(1 for c in cards if c["stage"] == s)
              for s in ("trained", "federated", "gating", "promoted", "rejected")}
    return {"cards": cards, "events": timeline, "counts": counts,
            "active_store": active_store, "active_xapp": xapp_active,
            "active": xapp_active or active_store}


# --------------------------------------------------------------- runtime --

ELIGIBILITY_SCHEMA = "horus.runtime-eligibility/1"
ELIG_STALE_S = 30.0          # a runtime-eligibility record older than this is "stale", never "current"
DECISION_STALE_S = 15.0      # no per-decision row for this long -> the effective controller is unknown
CONTROLLERS = ("selector", "a3", "hold")


def _bool(v):
    return v if isinstance(v, bool) else None


def _count(v):
    """A non-negative integral counter, else None. Rejects bool, NaN/Infinity (json decodes 1e309 as inf),
    fractions and negatives; never raises."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v if v >= 0 else None
    if isinstance(v, float) and math.isfinite(v) and v.is_integer() and v >= 0:
        return int(v)
    return None


def _ident(v):
    return v if isinstance(v, str) and v.strip() else None


BIND_KEYS = ("candidate_version", "session_id", "context_sha256")


def _binding(el, dec):
    """AI-active status must be about ONE model session. The admitted heartbeat and the decision must carry
    the same candidate_version, session_id and context_sha256. A missing identity on either side is
    'unverified' (never a match); a different value is a mismatch (another session's inference, a reload,
    or another candidate). Returns (ok, reason)."""
    if not el or not dec:
        return False, "no_record"
    for k in BIND_KEYS:
        a, b = _ident(el.get(k)), _ident(dec.get(k))
        if a is None or b is None:
            return False, f"{k}_missing"
        if a != b:
            return False, f"{k}_mismatch"
    return True, None


def runtime_state(path, decision_rows, pipe, results, now):
    """runtime-eligibility.jsonl is a heartbeat: the runtime appends one row at least every few seconds.
    Keep four things apart that a viewer would otherwise merge into 'the AI is running':

    1. research_gate      the safety-gate verdict of the candidate (admission check)
    2. final_evaluation   the pre-registered held-out verdict: GO / NO-GO / pending
    3. admission          whether the runtime admitted that candidate (eligibility record)
    4. effective          which controller actually made the latest decisions
                          (selector / a3 fallback / hold) and how many inference calls

    ``ai_active`` is True only when all of: the runtime says the candidate is eligible,
    inference_calls > 0, and a selector decision arrived within DECISION_STALE_S. The highest
    version in the A1 store (pipeline.active) is NOT evidence of any of this."""
    erows = read_jsonl(path, now=now) if path else []      # rows stamped after `now` are already hidden
    d = max(enumerate(erows), key=lambda item: (item[1]["_t"], item[0]))[1] if erows else {}      # latest by timestamp, not by file position
    el = None
    if d and d.get("schema") in (ELIGIBILITY_SCHEMA, None):
        age = now - d["_t"]
        el = {"candidate_version": d.get("candidate_version"),
              "eligible": _bool(d.get("eligible")), "live_eligible": _bool(d.get("live_eligible")),
              "fixture_only": _bool(d.get("fixture_only")), "reason": d.get("reason"),
              "inference_calls": _count(d.get("inference_calls")),
              "session_state": d.get("session_state"), "runtime_fault": d.get("runtime_fault"),
              "clock_diagnostics": d.get("clock_diagnostics"),
              "session_id": _ident(d.get("session_id")), "context_sha256": _ident(d.get("context_sha256")),
              "input_qualified": _bool(d.get("input_qualified")), "input_scope": d.get("input_scope"),
              "ts": iso(d["_t"]), "age_s": rnd(age, 1), "stale": age > ELIG_STALE_S}
    # effective controller from the per-decision stream (actuation/decisions.jsonl, NOT actions.jsonl:
    # that file means 'a control was sent to the RAN')
    rows = [r for r in decision_rows if r.get("effective_controller") in CONTROLLERS]
    last = max(rows, key=lambda r: r["_t"]) if rows else None
    recent = [r for r in rows if now - r["_t"] <= 60.0]
    counts = {c: sum(1 for r in recent if r["effective_controller"] == c) for c in CONTROLLERS}
    eff = {"controller": None, "stage": None, "age_s": None, "stale": True, "counts_60s": counts,
           "profile": None, "input_age_s": None, "candidate_version": None, "session_id": None,
           "context_sha256": None, "learned": False}
    if last:
        age = now - last["_t"]
        eff.update(controller=last["effective_controller"], stage=last.get("selector_stage"),
                   age_s=rnd(age, 1), stale=age > DECISION_STALE_S, ts=iso(last["_t"]),
                   profile=last.get("selector_profile") if isinstance(last.get("selector_profile"), dict) else None,
                   input_age_s=num(last.get("input_age_s")),
                   candidate_version=_ident(last.get("candidate_version")), session_id=_ident(last.get("session_id")),
                   context_sha256=_ident(last.get("context_sha256")),
                   learned=(last["effective_controller"] == "selector" and last.get("selector_stage") == "learned_profiles"))
    cand = (el or {}).get("candidate_version")
    card = next((c for c in pipe.get("cards", []) if c["version"] == cand), None) if cand else None
    gate = {"candidate_version": cand,
            "verdict": card["stage"] if card else None,
            "worst": card["worst"] if card else None, "threshold": card["threshold"] if card else None}
    fe = results.get("go_no_go") if results else None
    evaluated = re.search(r"v3\s+(v\d+\.\d+\.\d+)", str((results or {}).get("provenance", {}).get("policy_arm", "")))
    explicit_version = (results or {}).get('provenance', {}).get('evaluated_candidate_version')
    final = {"candidate_version": explicit_version if parse_version(explicit_version) else evaluated.group(1) if evaluated else None, "verdict": fe or "pending", "decided": fe is not None,
             "note": None if fe else "pre-registered held-out evaluation not run / not recorded"}
    bound, why = _binding(el, eff if last else None)
    ai_active = bool(el and not el["stale"] and el["eligible"] is True and (el["inference_calls"] or 0) > 0
                     and eff["controller"] == "selector" and not eff["stale"]
                     and eff["learned"]                      # warm_default is the default profile, not learned-AI control
                     and bound and el["session_state"] == "running" and not el["runtime_fault"])
    if el and el['session_state'] in ('stopped','failed','refused'):
        eff.update(controller=None, stage=None, stale=True, learned=False)
    store_active = pipe.get("active")
    return {"eligibility": el, "effective": eff, "research_gate": gate, "final_evaluation": final,
            "ai_active": ai_active, "binding": {"ok": bound, "reason": why},
            "store_only": bool(store_active) and not ai_active,   # A1 store names a version but no AI inference is proven
            "store_active": store_active}


# --------------------------------------------------------------- results --

RESULTS_SCHEMA = "horus.finals-results/1"
CAMPUS_SCHEMA = "horus.finals-campus/1"
ARM_ORDER = ("policy", "a3_tuned", "a3_stock")


def _go_no_go(d):
    """The pre-registered verdict. Real producers (twin.evaluate / evaluate_v3) write it as
    ``provenance.go_no_go``; a top-level ``go_no_go`` is also accepted. Anything but GO / NO-GO is None."""
    for v in (d.get("go_no_go"), (d.get("provenance") or {}).get("go_no_go") if isinstance(d.get("provenance"), dict) else None):
        if v in ("GO", "NO-GO", "H1", "H2"):     # H1/H2 = the v3 rule's pass headlines (finals_preregistration_v3.json)
            return v
    return None


def results_state(path):
    """working/evidence/finals-results.json (contract: dashboard/CONTRACTS.md)."""
    d = read_json(path)
    if not d:
        return None
    arms = [a for a in d.get("arms", []) if isinstance(a, dict) and a.get("id")]
    arm_ids = [a["id"] for a in arms]
    metrics = []
    for m in d.get("metrics", []):
        if not isinstance(m, dict) or not isinstance(m.get("values"), dict):
            continue
        vals = {}
        for aid in arm_ids:
            v = m["values"].get(aid)
            if not isinstance(v, dict) or num(v.get("mean")) is None:
                continue
            lo, hi = num(v.get("ci_low")), num(v.get("ci_high"))
            vals[aid] = {"mean": v["mean"], "ci_low": lo, "ci_high": hi, "n": v.get("n")}
        if not vals:
            continue
        better = "higher" if m.get("better") == "higher" else "lower"
        cmp = None
        p, t = vals.get("policy"), vals.get("a3_tuned")
        if p and t:
            delta = p["mean"] - t["mean"]
            rel = 100.0 * delta / abs(t["mean"]) if t["mean"] else None
            improves = delta > 0 if better == "higher" else delta < 0
            sep = None
            if None not in (p["ci_low"], p["ci_high"], t["ci_low"], t["ci_high"]):
                sep = p["ci_high"] < t["ci_low"] or t["ci_high"] < p["ci_low"]
            cmp = {"delta": rnd(delta, 4), "rel_pct": rnd(rel, 1), "improves": improves,
                   "ci_separated": sep}
        metrics.append({"id": m.get("id"), "label": m.get("label") or m.get("id"),
                        "label_ko": m.get("label_ko"), "unit": m.get("unit", ""),
                        "better": better, "scenario": m.get("scenario"),
                        "values": vals, "vs_tuned": cmp})
    return {"title": d.get("title"), "title_ko": d.get("title_ko"),
            "sample": bool(d.get("sample")), "generated_ts": d.get("generated_ts"),
            "go_no_go": _go_no_go(d),
            "arms": arms, "metrics": metrics,
            "provenance": d.get("provenance") if isinstance(d.get("provenance"), dict) else {},
            # additive blocks written by twin.results_current (absent in older documents)
            "paired": d.get("paired") if isinstance(d.get("paired"), dict) else None,
            "measured_route": d.get("measured_route") if isinstance(d.get("measured_route"), dict) else None,
            "confirmatory_history": d.get("confirmatory_history") if isinstance(d.get("confirmatory_history"), list) else None,
            "schema_ok": d.get("schema") == RESULTS_SCHEMA}


def campus_state(evidence_dir):
    """working/evidence/finals-campus-*.json, one file per campus."""
    out = []
    for f in sorted(glob.glob(os.path.join(evidence_dir, "finals-campus-*.json"))):
        d = read_json(f)
        if not d:
            continue
        g = d.get("gate") if isinstance(d.get("gate"), dict) else {}
        verdict = g.get("verdict") if g.get("verdict") in ("promote", "reject", "pending") else "pending"
        out.append({
            "id": d.get("campus_id") or os.path.basename(f)[len("finals-campus-"):-5],
            "name": d.get("name"), "name_ko": d.get("name_ko"), "city": d.get("city"),
            "city_ko": d.get("city_ko"),
            "lat": num(d.get("lat")), "lon": num(d.get("lon")),
            "sites": d.get("sites"), "ues": d.get("ues"), "radio_map": d.get("radio_map"),
            "policy_version": d.get("policy_version"), "verdict": verdict,
            "worst": num(g.get("worst_case_score")), "threshold": num(g.get("threshold")),
            "worst_case": g.get("worst_scenario"), "suite": g.get("suite"),
            "vs_tuned": d.get("vs_a3_tuned") if isinstance(d.get("vs_a3_tuned"), dict) else None,
            "sample": bool(d.get("sample")), "file": os.path.basename(f),
        })
    return {"campuses": out,
            "promoted": sum(1 for c in out if c["verdict"] == "promote"),
            "rejected": sum(1 for c in out if c["verdict"] == "reject"),
            "sample": any(c["sample"] for c in out)}


# ---------------------------------------------------------------- health --

def health_state(health_rows, now, rtt, tput, kpm, probe=None):
    """Demo-health: stack up, E2 nodes registered, data fresh. ``probe`` is an
    in-process docker probe result (live, when docker is reachable); otherwise the
    newest health/stack.jsonl record not older than HEALTH_STALE_S is used."""
    src, rec = None, None
    if probe:
        src, rec = "docker", probe
    elif health_rows:
        last = health_rows[-1]
        if now - last["_t"] <= HEALTH_STALE_S:
            src, rec = "probe-file", last
    stack_up = rec.get("stack_up") if rec else None
    e2 = rec.get("e2_nodes") if rec else None
    containers = rec.get("containers") if rec and isinstance(rec.get("containers"), dict) else {}
    down = sorted(k for k, v in containers.items() if str(v).lower() not in ("running", "up", "healthy"))
    ages = {"rtt": rtt.get("age_s"), "tput": tput.get("age_s"), "kpm": kpm.get("age_s")}
    limits = {"rtt": FRESH_FAST_S, "tput": FRESH_FAST_S, "kpm": FRESH_KPM_S}
    fresh = {k: (a is not None and a <= limits[k]) for k, a in ages.items()}
    have_any = any(a is not None for a in ages.values())
    data_ok = have_any and all(fresh[k] for k, a in ages.items() if a is not None)
    checks = {
        "stack": "ok" if stack_up is True and not down else ("bad" if stack_up is False or down else "unknown"),
        "e2": "ok" if isinstance(e2, int) and e2 >= 1 else ("bad" if e2 == 0 else "unknown"),
        "data": "ok" if data_ok else ("bad" if have_any else "unknown"),
    }
    overall = "bad" if "bad" in checks.values() else ("ok" if all(v == "ok" for v in checks.values()) else "warn")
    return {"overall": overall, "checks": checks, "source": src, "e2_nodes": e2,
            "containers_down": down, "containers_n": len(containers),
            "ran_functions": rec.get("ran_functions") if rec else None,
            "ages": ages, "fresh": fresh}


# --------------------------------------------------------- state builder --

def build_state(root, now, mode="live", probe=None, xapp_active=None, meta=None):
    """Everything the UI needs for one frame, as JSON-able dict. ``root`` is
    working/ (live) or a replay bundle with the same layout."""
    replay = mode == "replay"
    tail = None if replay else 3_000_000
    j = lambda *p: os.path.join(root, *p)
    rtt_rows = read_jsonl(j("metrics", "rtt.jsonl"), now=now, tail_bytes=tail)
    tput_rows = read_jsonl(j("metrics", "tput.jsonl"), now=now, tail_bytes=tail)
    action_rows = read_jsonl(j("actuation", "actions.jsonl"), now=now, tail_bytes=tail)
    decision_rows = read_jsonl(j("actuation", "decisions.jsonl"), now=now, tail_bytes=tail)
    shadow_rows = []
    for f in sorted(glob.glob(j("evidence", "*ho*.jsonl"))):
        shadow_rows.extend(read_jsonl(f, now=now, ts_keys=("decided_ts", "ts", "kpm_row_ts")))
    shadow_rows.sort(key=lambda r: r["_t"])
    health_rows = read_jsonl(j("health", "stack.jsonl"), now=now, tail_bytes=None if replay else 200_000)

    rtt = rtt_state(rtt_rows, now)
    tput = tput_state(tput_rows, now)
    kpm = kpm_state(j("kpm"), now, replay=replay)
    act = actuation_state(action_rows, shadow_rows, tput_rows, now)
    focus = act.get("focus")
    if focus:
        focus["series"] = tput_window(tput_rows, focus.get("ue"), focus["t"] - 30, focus["t"] + 30)
    gate_logs = sorted(glob.glob(j("evidence", "gate_log*.txt")))
    pipe = pipeline_state(j("policies"), j("candidates"), gate_logs, now, xapp_active=xapp_active)
    # the current pre-registered claim (twin.results_current) if present, else the historical finals file
    results = results_state(j("evidence", "finals-results-current.json")) or results_state(j("evidence", "finals-results.json"))
    runtime = runtime_state(j("evidence", "runtime-eligibility.jsonl"), decision_rows, pipe, results, now)
    campus = campus_state(j("evidence"))
    health = health_state(health_rows, now, rtt, tput, kpm, probe=probe)
    return {
        "mode": mode, "now": now, "now_iso": iso(now), "meta": meta or {},
        "health": health, "rtt": rtt, "tput": tput, "kpm": kpm,
        "actuation": act, "pipeline": pipe, "runtime": runtime, "results": results, "campus": campus,
    }
