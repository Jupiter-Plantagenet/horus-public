#!/usr/bin/env python3
"""Serve the campus twin (and the rest of dashboard/) plus a read-only LIVE feed.

    python dashboard/campus3d/serve.py                       # REPLAY/SAMPLE: http://127.0.0.1:8030/campus3d/
    python dashboard/campus3d/serve.py --capture OUT_DIR     # LIVE: tail release/run_demo.py captures (read-only)
    python dashboard/campus3d/serve.py --rehearse            # exercise the LIVE path with recorded input (labelled REHEARSAL)

The web root is dashboard/, so dashboard/operator/ and dashboard/campus3d/ share an origin
and can embed each other with relative paths. Standard library only.

GET /api/campus3d/live?after=SEQ  ->  horus.campus3d.feed/1 (see campus3d/INTERFACE.md §6)
"""
import argparse, json, os, re, shutil, sys, tempfile, threading, time
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
WEB = HERE.parent
REPO = WEB.parent
STALE_S = 2.0


def iso(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


class Tail:
    """Incremental JSONL reader: only complete lines, never modifies the file."""
    def __init__(self):
        self.files = {}

    def read(self, path):
        st = self.files.setdefault(str(path), {"off": 0, "rows": [], "grew": None, "buf": b"", "seen": False, "errors": 0})
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            return st
        if size < st["off"]:                      # truncated/replaced: start over
            st.update(off=0, rows=[], buf=b"", grew=None, seen=False, errors=0)
        if size > st["off"]:
            with open(path, "rb") as f:
                f.seek(st["off"]); data = st["buf"] + f.read(size - st["off"])
            st["off"] = size
            *lines, st["buf"] = data.split(b"\n")
            appended = 0
            for l in lines:
                if l.strip():
                    try:
                        value = json.loads(l)
                        if not isinstance(value, dict): raise ValueError('record must be an object')
                        st["rows"].append(value); appended += 1
                    except (json.JSONDecodeError, ValueError): st["errors"] += 1
            # Initial contents can be an old stopped archive. Only growth
            # observed after attachment proves that a producer is advancing.
            if appended and st["seen"]: st["grew"] = time.monotonic()
        st["seen"] = True
        return st


def event_from_action(i, a):
    p, lb = a.get("params", {}), a.get("latency_breakdown") or {}
    t = round((p.get("twin_step", 0) + 1) * 0.1, 2)
    send = lb.get("decision_to_send_ms")
    ack = t + (send + p["ric_control_ack_ms"]) / 1000 if send is not None and p.get("ric_control_ack_ms") is not None else None
    cu = t + a["latency_ms"] / 1000 if a.get("latency_ms") and p.get("rrc_handover_complete") else None
    status = "failed" if a.get("result") not in (None, "ok") else "confirmed" if cu else "acked" if ack else "attempted"
    prof = (p.get("selector") or {}).get("selected_profile") or {}
    return {"id": f"live-{i}", "from": p.get("twin_from_cell"), "to": p.get("twin_to_cell"), "status": status,
            "phases": {"decision": t, "sent": round(t + send / 1000, 2) if send is not None else None,
                       "ack": round(ack, 2) if ack else None, "cu_confirmed": round(cu, 2) if cu else None},
            "profile": {"index": prof.get("index"), **(prof.get("parameters") or {})} if prof else None,
            "evidence": {"ric_ack_ms": p.get("ric_control_ack_ms"), "decision_to_cu_ms": a.get("latency_ms"),
                         "source_du": p.get("source_du"), "target_du": p.get("target_du"),
                         "completion_basis": p.get("completion_basis")}}


class LiveFeed:
    def __init__(self, capture, rehearsal=False):
        self.capture = Path(capture); self.tail = Tail(); self.rehearsal = rehearsal; self.lock = threading.Lock()

    def cycle(self):
        cycles = sorted(p for p in self.capture.glob("cycle-*") if (p / "frames.jsonl").exists())
        return cycles[-1] if cycles else None

    def feed(self, after):
        with self.lock:
            c = self.cycle()
            base = {"format": "horus.campus3d.feed/1", "mode": "live",
                    "label": ("LIVE PATH REHEARSAL · recorded input" if self.rehearsal else "Live session"),
                    "live": {"cycle": None, "stale": True, "age_s": None, "rehearsal": self.rehearsal}}
            if not c:
                return dict(base, frames={"t_s": [], "step": [], "serving": [], "rsrp": [], "sinr_db": []}, events=[], cells=[])
            fr = self.tail.read(c / "frames.jsonl")
            dec = self.tail.read(c / "driver/decisions.jsonl")
            acts_path = c / "driver/timed-actions.jsonl"
            acts = self.tail.read(acts_path if acts_path.exists() else c / "driver/actions.jsonl")
            rtt = self.tail.read(c / "dashboard/metrics/rtt.jsonl")
            rows = fr["rows"]
            cells = rows[0]["cell_ids"] if rows else []
            dmap = {d.get("sequence"): d for d in dec["rows"][-4000:]}
            sel = [f for f in rows if f.get("sequence", -1) > after][-2000:]
            frames = {"t_s": [], "step": [], "serving": [], "rsrp": [], "sinr_db": [], "profile": [], "stage": []}
            for f in sel:
                d = dmap.get(f["sequence"]) or {}
                frames["t_s"].append(round(f["t_s"], 2)); frames["step"].append(f["sequence"])
                frames["serving"].append(f["serving"][0]); frames["rsrp"].append([round(v, 1) for v in f["l1"][0]])
                frames["sinr_db"].append(round(f["sinr_db"][0], 2))
                frames["profile"].append(((d.get("selected_profiles") or [{}])[0]).get("index"))
                frames["stage"].append(d.get("selector_stage"))
            service = {"rtt": []}
            if rows:
                anchor_t, anchor_ts = rows[-1]["t_s"], iso(rows[-1]["source_ts"])
                for r in rtt["rows"][-600:]:
                    try: service["rtt"].append([round(anchor_t + iso(r["ts"]) - anchor_ts, 2), r["rtt_ms"]])
                    except (KeyError, ValueError): pass
            # Freshness is observer-side (time since the frame file last grew); it does not rely on
            # cross-clock comparisons between the producer's session UTC and this host's wall clock.
            age = None if fr["grew"] is None else round(time.monotonic() - fr["grew"], 2)
            base["live"] = {"cycle": c.name, "stale": age is None or age > STALE_S or bool(fr["errors"]), "age_s": age, "rehearsal": self.rehearsal,
                            "newest_source_ts": rows[-1]["source_ts"] if rows else None, "frames_total": len(rows)}
            if fr["errors"]: base["error"] = "malformed live input; waiting for a new clean cycle"
            identity = next((d for d in reversed(dec["rows"]) if d.get('candidate_version')), {})
            return dict(base, cells=cells,
                        scenario={"id": "live", "route": "t4-reverse", "segment": rows[0].get("segment") if rows else None, "dt_s": 0.1},
                        frames=frames, events=[event_from_action(i, a) for i, a in enumerate(acts["rows"])],
                        service=service, comparison=None, traffic={"kind":"icmp_probe","label":"ICMP probes · emulated RF"},
                        artifact={"version":identity.get('candidate_version','not provided'),"kind":identity.get('model_kind','unknown'),
                                  "label":"Driver-reported artifact; operator acceptance not provided",
                                  "federation":{"state":"pending"},"gate":{"state":"pending"}})


def rehearse(out, stop):
    """Write recorded evidence into a private capture dir at real-time pace (LIVE code-path test only)."""
    live = REPO / "working/evidence/selector-live-20261102/live"
    qual = REPO / "working/evidence/qualified-release-20261104/bounded/cycle-000/driver/timed-actions.jsonl"
    frames = (live / "frames.jsonl").read_text(encoding="utf-8").splitlines()
    decisions = {json.loads(l)["sequence"]: l for l in (live / "driver/decisions.jsonl").read_text(encoding="utf-8").splitlines()}
    actions = [json.loads(l) for l in qual.read_text(encoding="utf-8").splitlines()]
    n = 0
    while not stop.is_set():
        c = out / f"cycle-{n:03d}"; (c / "driver").mkdir(parents=True); (c / "dashboard/metrics").mkdir(parents=True)
        start = time.time(); t_first = None
        with open(c / "frames.jsonl", "w", encoding="utf-8") as ff, open(c / "driver/decisions.jsonl", "w", encoding="utf-8") as fd, \
             open(c / "driver/timed-actions.jsonl", "w", encoding="utf-8") as fa, open(c / "dashboard/metrics/rtt.jsonl", "w", encoding="utf-8") as fr:
            done = set(); next_ping = 0.0
            for line in frames:
                if stop.is_set(): return
                f = json.loads(line)
                if t_first is None: t_first = f["t_s"]
                wait = start + (f["t_s"] - t_first) - time.time()
                if wait > 0: time.sleep(wait)
                f["source_ts"] = datetime.now(timezone.utc).isoformat()
                ff.write(json.dumps(f) + "\n"); ff.flush()
                if f["sequence"] in decisions: fd.write(decisions[f["sequence"]] + "\n"); fd.flush()
                for i, a in enumerate(actions):
                    if i not in done and a["latency_ms"] and f["sequence"] >= a["params"]["twin_step"] + a["latency_ms"] / 100:
                        fa.write(json.dumps(a) + "\n"); fa.flush(); done.add(i)
                # No RTT is written: rehearsal never fabricates service measurements.
        n += 1


def make_handler(feed):
    class H(SimpleHTTPRequestHandler):
        def __init__(self, *a, **k): super().__init__(*a, directory=str(WEB), **k)
        def log_message(self, fmt, *args): pass
        def end_headers(self):
            if self.path.endswith((".json", ".js", ".html", ".css")): self.send_header("Cache-Control", "no-cache")
            super().end_headers()
        def do_GET(self):
            u = urlparse(self.path)
            if u.path in ("/", "/campus3d"):
                self.send_response(302); self.send_header("Location", "/campus3d/"); self.end_headers(); return
            if u.path == "/api/campus3d/live":
                if feed is None:
                    body = {"format": "horus.campus3d.feed/1", "mode": "live", "live": {"stale": True, "age_s": None, "cycle": None},
                            "error": "no capture configured (start serve.py with --capture DIR)", "frames": {"t_s": []}, "events": []}
                    code = 200
                else:
                    try: after = int(parse_qs(u.query).get("after", ["-1"])[0])
                    except ValueError: after = -1
                    body, code = feed.feed(after), 200
                b = json.dumps(body, separators=(",", ":")).encode()
                self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b); return
            return super().do_GET()
    return H


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--host", default="127.0.0.1"); ap.add_argument("--port", type=int, default=8030)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--capture", help="release runner output directory containing cycle-NNN/ (read-only)")
    g.add_argument("--rehearse", action="store_true", help="stream recorded evidence through the LIVE path (labelled REHEARSAL)")
    a = ap.parse_args()
    feed, stop, tmp = None, threading.Event(), None
    if a.capture:
        if not Path(a.capture).is_dir(): sys.exit(f"--capture {a.capture}: not a directory")
        feed = LiveFeed(a.capture)
    elif a.rehearse:
        tmp = Path(tempfile.mkdtemp(prefix="horus-campus3d-rehearsal-"))
        threading.Thread(target=rehearse, args=(tmp, stop), daemon=True).start()
        feed = LiveFeed(tmp, rehearsal=True)
    class Server(ThreadingHTTPServer):
        allow_reuse_address = os.name != "nt"   # Windows would silently double-bind a busy port
        daemon_threads = True
    srv = Server((a.host, a.port), make_handler(feed))
    print(f"HORUS campus twin: http://{a.host}:{a.port}/campus3d/"
          + (f"  (LIVE from {a.capture})" if a.capture else "  (LIVE path REHEARSAL)" if a.rehearse else ""), flush=True)
    try: srv.serve_forever()
    except KeyboardInterrupt: pass
    finally:
        stop.set(); srv.server_close()
        if tmp: shutil.rmtree(tmp, ignore_errors=True)   # only the directory this process created


if __name__ == "__main__":
    main()
