#!/usr/bin/env python3
"""HORUS finals dashboard (issue #14, finals edition) — server + CLI.

    python3 dashboard/horus_dash.py                 # LIVE over working/  -> http://127.0.0.1:8014
    python3 dashboard/horus_dash.py --replay DIR    # arm a specific REPLAY bundle (key R in the UI)
    python3 dashboard/horus_dash.py record --minutes 10 --out working/replay/latest
    python3 dashboard/horus_dash.py --once [--src replay]   # one state frame as JSON (debug)

The page is a single-screen app (static/) polling /api/state once a second.
LIVE reads working/ with the wall clock; REPLAY reads a recorded bundle (same
directory layout as working/) with a virtual clock that walks it at real speed
and loops. Same parsers, same layout — the only difference on screen is the
amber REPLAY label. See dashboard/README.md and dashboard/CONTRACTS.md.

Read-only towards the system. The one optional write is the demo-health probe:
when docker is reachable it appends one line every 5 s to working/health/stack.jsonl
(so recordings carry stack health too); --no-probe disables it. The probe only
runs `docker ps` / `docker logs` — it never starts or stops containers.

stdlib only (python3 >= 3.8). The previous (interim, July) one-screen page is
kept as dashboard/horus_dash_interim.py.
"""

import argparse
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
import horus_data as hd  # noqa: E402
sys.path.insert(0, str(REPO / "stack"))
from session_clock import SessionClock

STATIC = HERE / "static"
SAMPLE_BUNDLE = HERE / "sample"


# ------------------------------------------------------------ replay clock --

class ReplayClock:
    """Virtual 'now' walking a recorded bundle at ``speed``x real time, looping.
    Playback starts ``lead`` seconds into the recording so charts open already
    filled, exactly as they would on a live stack that has been running a while."""

    def __init__(self, start, end, speed=1.0, lead_s=None):
        self.start, self.end, self.speed = start, end, max(speed, 0.01)
        dur = max(end - start, 1.0)
        self.lead = min(hd.CHART_WINDOW_S, dur / 3) if lead_s is None else max(0.0, min(lead_s, dur - 1))
        self.restart()

    def restart(self, wall=None):
        self.w0 = time.time() if wall is None else wall

    def _span(self):
        return max(self.end - (self.start + self.lead), 1.0)

    def now(self, wall=None):
        wall = time.time() if wall is None else wall
        return self.start + self.lead + ((wall - self.w0) * self.speed) % self._span()

    def loop_index(self, wall=None):
        wall = time.time() if wall is None else wall
        return int(((wall - self.w0) * self.speed) // self._span())


def bundle_span(bundle):
    """(start, end, manifest) of a replay bundle: manifest first, else scan its streams."""
    man = hd.read_json(os.path.join(bundle, "manifest.json")) or {}
    s, e = hd.parse_ts(man.get("start_ts")), hd.parse_ts(man.get("end_ts"))
    if s and e and e > s:
        return s, e, man
    ts = []
    for rel in ("metrics/rtt.jsonl", "metrics/tput.jsonl", "kpm/kpm.jsonl", "actuation/actions.jsonl"):
        rows = hd.read_jsonl(os.path.join(bundle, rel))
        if rows:
            ts += [rows[0]["_t"], rows[-1]["_t"]]
    if len(ts) < 2 or max(ts) <= min(ts):
        return None, None, man
    return min(ts), max(ts), man


# ------------------------------------------------------------ health probe --

E2_NODE_RE = re.compile(r"E2 SETUP-REQUEST rx from PLMN\s+\S+\s+Node ID\s+(\d+)")
RAN_FN_RE = re.compile(r"Accepting RAN function ID\s+(\d+)\s+with def\s*=\s*(\S+)")
XAPP_POLICY_RE = re.compile(r"active_policy_version\D*?(v\d+\.\d+\.\d+)")
EXPECTED = ("amf", "smf", "upf", "nrf", "gnb", "ue", "flexric", "kpm-xapp")


def _run(cmd, timeout=4):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def parse_probe(ps_out, flexric_log, xapp_log):
    """Pure part of the probe (unit-tested): docker ps + logs text -> health record."""
    states = dict(l.split("\t", 1) for l in ps_out.splitlines() if "\t" in l)
    containers = {n: states.get(n, "missing") for n in EXPECTED}
    e2 = fns = None
    if flexric_log is not None:
        e2 = len(set(E2_NODE_RE.findall(flexric_log)))
        fns = sorted({f"{i}:{d}" for i, d in RAN_FN_RE.findall(flexric_log)})
    hits = XAPP_POLICY_RE.findall(xapp_log or "")
    return {"ts": hd.iso(time.time()), "stack_up": all(v == "running" for v in containers.values()),
            "containers": containers, "e2_nodes": e2, "ran_functions": fns,
            "xapp_policy": hits[-1] if hits else None}


def docker_probe():
    """One read-only look at the stack. None when docker is unreachable (e.g. the
    dashboard runs on Windows while the stack is in WSL)."""
    try:
        ps = _run(["docker", "ps", "-a", "--format", "{{.Names}}\t{{.State}}"])
        if ps.returncode != 0:
            return None
        names = ps.stdout
        fl = xa = None
        if "flexric\trunning" in names:
            r = _run(["docker", "logs", "--tail", "5000", "flexric"])
            fl = r.stdout + r.stderr
        if "kpm-xapp\trunning" in names:
            r = _run(["docker", "logs", "--tail", "2000", "kpm-xapp"])
            xa = r.stdout + r.stderr
        return parse_probe(names, fl, xa)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


class Prober(threading.Thread):
    def __init__(self, out_path, every=5.0):
        super().__init__(daemon=True)
        self.out_path, self.every, self.latest, self.available = out_path, every, None, None

    def run(self):
        while True:
            rec = docker_probe()
            self.available = rec is not None
            self.latest = rec
            if rec and self.out_path:
                try:
                    os.makedirs(os.path.dirname(self.out_path), exist_ok=True)
                    with open(self.out_path, "a", encoding="utf-8") as fh:
                        fh.write(json.dumps(rec) + "\n")
                except OSError:
                    pass
            time.sleep(self.every)


# ------------------------------------------------------------------ record --

JSONL_STREAMS = ("metrics/rtt.jsonl", "metrics/tput.jsonl", "actuation/actions.jsonl",
                 "kpm/kpm.jsonl", "health/stack.jsonl")


def record(root, out, minutes, label=None, now=None):
    """Snapshot the last ``minutes`` of every stream (+ policy store, candidates,
    gate logs, results, campus files) into a replay bundle with root's layout."""
    now = time.time() if now is None else now
    t0 = now - minutes * 60
    os.makedirs(out, exist_ok=True)
    written = {}
    shadow = [os.path.relpath(p, root).replace(os.sep, "/") for p in Path(root, "evidence").glob("*ho*.jsonl")]
    for rel in list(JSONL_STREAMS) + shadow:
        src = os.path.join(root, rel)
        if not os.path.exists(src):
            continue
        keys = ("decided_ts", "ts", "kpm_row_ts") if rel.startswith("evidence") else ("ts",)
        rows = [r for r in hd.read_jsonl(src, ts_keys=keys, tail_bytes=50_000_000) if r["_t"] >= t0]
        dst = os.path.join(out, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "w", encoding="utf-8") as fh:
            for r in rows:
                r.pop("_t", None)
                fh.write(json.dumps(r) + "\n")
        written[rel] = len(rows)
    for rel_dir in ("policies", "candidates"):
        for f in Path(root, rel_dir).glob("*.json"):
            os.makedirs(os.path.join(out, rel_dir), exist_ok=True)
            shutil.copy2(f, os.path.join(out, rel_dir, f.name))
            written[f"{rel_dir}/{f.name}"] = 1
    for pat in ("gate_log*.txt", "finals-results.json", "finals-campus-*.json"):
        for f in Path(root, "evidence").glob(pat):
            os.makedirs(os.path.join(out, "evidence"), exist_ok=True)
            shutil.copy2(f, os.path.join(out, "evidence", f.name))
            written[f"evidence/{f.name}"] = 1
    man = {"schema": "horus.replay-bundle/1", "label": label or os.path.basename(os.path.normpath(out)),
           "recorded_from": os.path.abspath(root), "recorded_at": hd.iso(now),
           "start_ts": hd.iso(t0), "end_ts": hd.iso(now), "sample": False, "files": written}
    with open(os.path.join(out, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(man, fh, indent=2)
    return man


# ------------------------------------------------------------------ server --

class App:
    def __init__(self, root, replay_dir, speed=1.0, prober=None):
        self.root, self.replay_dir, self.speed, self.prober = root, replay_dir, speed, prober
        self._live_lock = threading.Lock()
        self._live_cached = None
        self._live_cached_key = None
        self._live_cached_at = -float('inf')
        self.clock, self.man = None, {}
        if replay_dir and os.path.isdir(replay_dir):
            s, e, man = bundle_span(replay_dir)
            if s:
                self.clock, self.man = ReplayClock(s, e, speed), man

    def state(self, src="live", restart=False):
        if src == 'replay':
            return self._state(src, restart)
        with self._live_lock:
            key = self.root
            if self._live_cached is None or key != self._live_cached_key or time.monotonic()-self._live_cached_at >= .5:
                self._live_cached = self._state(src, restart)
                self._live_cached_key = key
                self._live_cached_at = time.monotonic()
            return self._live_cached

    def _state(self, src="live", restart=False):
        if src == "replay":
            if not self.clock:
                return {"mode": "replay", "error": "no replay bundle", "replay_dir": self.replay_dir}
            if restart:
                self.clock.restart()
            meta = {"label": self.man.get("label") or os.path.basename(self.replay_dir),
                    "recorded_at": self.man.get("recorded_at"), "speed": self.speed,
                    "bundle_start": hd.iso(self.clock.start), "bundle_end": hd.iso(self.clock.end),
                    "loop": self.clock.loop_index(), "sample": bool(self.man.get("sample"))}
            return hd.build_state(self.replay_dir, self.clock.now(), mode="replay", meta=meta)
        probe = self.prober.latest if self.prober else None
        meta = {"root": self.root, "replay_available": bool(self.clock),
                "probe": None if not self.prober else self.prober.available}
        manifest = hd.read_json(os.path.join(self.root, "manifest.json")) or {}
        meta.update(sample=bool(manifest.get('sample')),label=manifest.get('label'))
        clock_record = manifest.get("clock")
        now = time.time()
        clock_error = None
        if clock_record:
            try:
                now = SessionClock(clock_record).timestamp()
                meta["clock"] = clock_record
            except ValueError as exc:
                clock_error = str(exc)
                meta["clock_error"] = clock_error
        state = hd.build_state(self.root, now, mode="live", probe=probe,
                               xapp_active=(probe or {}).get("xapp_policy"), meta=meta)
        if clock_error:
            state["runtime"]["ai_active"] = False
            state["runtime"]["effective"].update(controller=None, stale=True)
        return state


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, body, ctype):
            try:
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                self.close_connection = True

        def do_GET(self):
            u = urlparse(self.path)
            if u.path == "/api/state":
                q = parse_qs(u.query)
                try:
                    st = app.state(src=q.get("src", ["live"])[0], restart="restart" in q)
                    self._send(200, json.dumps(st).encode(), "application/json")
                except Exception as e:  # never take the demo screen down
                    self._send(200, json.dumps({"error": f"{type(e).__name__}: {e}"}).encode(),
                               "application/json")
                return
            rel = "index.html" if u.path in ("/", "/index.html") else u.path.lstrip("/")
            if rel.startswith("static/"):
                rel = rel[len("static/"):]
            path = (STATIC / rel).resolve()
            if STATIC.resolve() not in path.parents or not path.is_file():
                self._send(404, b"not found", "text/plain")
                return
            ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype.endswith("javascript"):
                ctype += "; charset=utf-8"
            self._send(200, path.read_bytes(), ctype)

        def log_message(self, *_):
            pass
    return Handler


def default_replay():
    latest = REPO / "working" / "replay" / "latest"
    return str(latest) if latest.is_dir() else str(SAMPLE_BUNDLE)


def main(argv=None):
    ap = argparse.ArgumentParser(description="HORUS finals dashboard")
    sub = ap.add_subparsers(dest="cmd")
    rec = sub.add_parser("record", help="snapshot the last N minutes into a replay bundle")
    rec.add_argument("--root", default=str(REPO / "working"))
    rec.add_argument("--minutes", type=float, default=10)
    rec.add_argument("--out", default=str(REPO / "working" / "replay" / "latest"))
    rec.add_argument("--label")
    ap.add_argument("--root", default=str(REPO / "working"), help="live data root (working/)")
    ap.add_argument("--replay", default=None,
                    help="replay bundle dir (default: working/replay/latest, else dashboard/sample)")
    ap.add_argument("--speed", type=float, default=1.0, help="replay speed (1.0 = real time)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8014)
    ap.add_argument("--no-probe", action="store_true", help="disable the docker health probe")
    ap.add_argument("--health-out", default=None,
                    help="where the probe appends health records (default <root>/health/stack.jsonl)")
    ap.add_argument("--once", action="store_true", help="print one state frame as JSON and exit")
    ap.add_argument("--src", default="live", choices=("live", "replay"), help="with --once")
    args = ap.parse_args(argv)

    if args.cmd == "record":
        man = record(args.root, args.out, args.minutes, args.label)
        print(f"recorded {man['start_ts']} .. {man['end_ts']} -> {args.out}")
        for k, v in man["files"].items():
            print(f"  {k}: {v}")
        return 0

    replay_dir = args.replay or default_replay()
    prober = None
    if not args.no_probe and not args.once and shutil.which("docker"):
        prober = Prober(args.health_out or os.path.join(args.root, "health", "stack.jsonl"))
        prober.start()
    app = App(args.root, replay_dir, args.speed, prober)

    if args.once:
        print(json.dumps(app.state(src=args.src), indent=1))
        return 0

    print(f"HORUS finals dashboard -> http://{args.host}:{args.port}")
    print(f"  live root : {args.root}")
    print(f"  replay    : {replay_dir if app.clock else '(none)'}   [key R toggles LIVE/REPLAY]")
    print(f"  probe     : {'docker (read-only)' if prober else 'off -> reading <root>/health/stack.jsonl if present'}")
    ThreadingHTTPServer((args.host, args.port), make_handler(app)).serve_forever()


if __name__ == "__main__":
    sys.exit(main())
