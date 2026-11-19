#!/usr/bin/env python3
"""Recompute every headline number HORUS claims from the raw evidence in this repository.

    python verify.py            # standard library only; exits non-zero if any check fails

1. Frozen model     the weights and pre-registration hash to the values recorded in FREEZE.md before the run
2. Held-out claim   paired differences recomputed from the 7,200 raw episode rows (not read from stats.json),
                    and the rerun of the same command on this release's code compared row by row
3. Measured route   the transfer test on the calibrated campus walk, recomputed from its raw rows
4. Live OAI run     the two-hour acceptance re-aggregated from the 41 per-cycle driver summaries
5. 3D console       the numbers the console shows are the numbers above
"""
import gzip
import hashlib
import json
import re
import statistics
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EV = ROOT / "working/evidence"
FAILED = []


def check(ok, what):
    print(f"  {'PASS' if ok else 'FAIL'}  {what}")
    if not ok:
        FAILED.append(what)


def sha256(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def jload(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def jrows(p):
    with gzip.open(p, "rt", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def t975(df):
    """Two-sided 95% Student-t quantile (Cornish-Fisher expansion; error < 1e-6 for df >= 30)."""
    z = statistics.NormalDist().inv_cdf(0.975)
    g1 = (z ** 3 + z) / 4
    g2 = (5 * z ** 5 + 16 * z ** 3 + 3 * z) / 96
    g3 = (3 * z ** 7 + 19 * z ** 5 + 17 * z ** 3 - 15 * z) / 384
    return z + g1 / df + g2 / df ** 2 + g3 / df ** 3


def paired(rows, arm, ref, key, metric):
    a = {key(r): r[metric] for r in rows if r["arm"] == arm}
    b = {key(r): r[metric] for r in rows if r["arm"] == ref}
    d = [a[k] - b[k] for k in sorted(a) if k in b]
    m, s = statistics.fmean(d), statistics.stdev(d)
    h = t975(len(d) - 1) * s / len(d) ** 0.5
    return m, m - h, m + h, len(d)


def frozen_model():
    print("1. Frozen model (working/evidence/v3.14/FREEZE.md)")
    freeze = (EV / "v3.14/FREEZE.md").read_text(encoding="utf-8")
    want_w = re.search(r"Weights sha256: `([0-9a-f]{64})`", freeze).group(1)
    want_p = re.search(r"finals_preregistration_v3_14\.json`, sha256 `([0-9a-f]{64})`", freeze).group(1)
    art = jload(ROOT / "working/candidates/v3-clean-fedavg-v3.14.24.json")
    check(sha256(ROOT / "pipeline/checkpoints/dqn-v3.14.24.pt") == want_w, "dqn-v3.14.24.pt sha256 = weights frozen before the held-out run")
    check(sha256(ROOT / "pipeline/finals_preregistration_v3_14.json") == want_p, "pre-registration file unchanged since the freeze")
    check(art.get("version") == "v3.14.24", "candidate artifact names v3.14.24")


def heldout():
    print("2. Pre-registered held-out test (seeds 2200..2259, 12 cells, 720 paired episodes per baseline)")
    rows = jrows(EV / "finals-v3.14/final/eval.jsonl.gz")
    st = jload(EV / "finals-v3.14/final/stats.json")
    key = lambda r: (r["scenario"], r["fading"], r["seed"])
    seeds = sorted({r["seed"] for r in rows})
    check(seeds == list(range(2200, 2260)) and len(rows) == 7200, f"{len(rows)} rows, seeds {seeds[0]}..{seeds[-1]}")
    print(f"     {'HORUS v3.14.24 minus':<16}{'utility [95% CI]':>28}{'HO/UE-min':>11}{'failures':>10}  verdict")
    verdict = st["verdict"]
    groups = {**{r: "H1_oracle" for r in verdict["H1_oracle"]["refs"]}, **{r: "H2_deployable" for r in verdict["H2_deployable"]["refs"]}}
    for ref in ("cho_global", "cho_mse", "cho_mro", "a3_global", "a3_tuned", "cho_tuned", "cho_tuned_ext"):
        m, lo, hi, n = paired(rows, "v3", ref, key, "utility")
        ho = paired(rows, "v3", ref, key, "ho_rate")[0]
        fail = paired(rows, "v3", ref, key, "fail_rate")[0]
        p = st["comparisons"][ref]["utility"]["pooled"]
        same = abs(m - p["diff"]) < 1e-9 and abs(lo - p["ci_low"]) < 1e-5 and abs(hi - p["ci_high"]) < 1e-5 and n == 720
        g = groups[ref]
        ok = verdict[g]["refs"][ref]["pass"]
        print(f"     {ref:<16}{m:>+10.3f} [{lo:+.3f}, {hi:+.3f}]{ho:>+11.3f}{fail:>+10.3f}  {'pass' if ok else 'FAIL'}"
              f"{'' if same else '   <- differs from stats.json'}")
        if not same:
            FAILED.append(f"recomputed {ref} differs from stats.json")
    check(verdict["H2_deployable"]["pass"] is True, "H2 (beats every deployable baseline, no guardrail regressed): PASS")
    check(verdict["H1_oracle"]["pass"] is False, "H1 (per-cell oracles) is reported as failed (extended CHO oracle), not claimed")
    rerun = EV / "finals-v3.14/rerun-release-code"
    new = {key(r) + (r["arm"],): r for r in jrows(rerun / "eval.jsonl.gz")}
    old = {key(r) + (r["arm"],): r for r in rows}
    diff = [k for k in old if old[k] != new.get(k)]
    fields = {f for k in diff for f in old[k] if old[k][f] != new[k][f]}
    check(set(new) == set(old) and len(diff) <= 80 and fields <= {"short_stays", "short_stay_rate", "ping_pongs", "pp_rate", "utility"},
          f"rerun on this release's code: {len(old) - len(diff)}/{len(old)} rows identical; the {len(diff)} others differ only in "
          f"{sorted(fields)} (ping-pong boundary fix, see rerun-release-code/NOTE.md)")
    worst = 0.0
    for ref in groups:
        m_new = paired(list(new.values()), "v3", ref, key, "utility")[0]
        worst = max(worst, abs(m_new - paired(rows, "v3", ref, key, "utility")[0]))
    st2 = jload(rerun / "stats.json")["verdict"]
    same_verdicts = all(st2[g]["refs"][r]["pass"] == verdict[g]["refs"][r]["pass"] for r, g in groups.items())
    check(same_verdicts and st2["headline"] == verdict["headline"] and worst < 0.001,
          f"rerun: every verdict identical (headline {st2['headline']}), largest utility change {worst:.5f}")


def measured():
    print("3. Measured campus route (frozen v3.14.24, no retraining; pre-registered)")
    s = jload(EV / "measured-v3.14/final/summary.json")["primary"]["verdict"]
    rows = [r for r in jrows(EV / "measured-v3.14/final/primary.rows.jsonl.gz") if r["fading"] != "off"]
    key = lambda r: (r["fading"], r["seed"])
    for ref in ("cho_global", "cho_mro", "a3_global"):
        m, lo, hi, n = paired(rows, "v3", ref, key, "utility")
        c = s["refs"][ref]["checks"][0]
        same = abs(m - c["diff"]) < 1e-9 and abs(lo - c["ci"][0]) < 1e-5
        print(f"     v3.14.24 - {ref:<12}{m:>+8.3f} [{lo:+.3f}, {hi:+.3f}] n={n}  {'pass' if s['refs'][ref]['pass'] else 'FAIL'}"
              f"{'' if same else '   <- differs from summary.json'}")
        if not same:
            FAILED.append(f"recomputed measured {ref} differs from summary.json")
    check(s["pass"] is False, "measured-route H2 is reported as FAILED vs network CHO (ping-pong guardrail, Rayleigh layer)")


def live():
    print("4. Live two-hour acceptance: calibrated route -> online selector -> emulated OAI F1 handovers")
    run = EV / "live-v3.14/sustained-run2-20261118T192432Z"
    res, ver = jload(run / "result.json"), jload(run / "VERIFICATION.json")
    cyc = [jload(d / "driver/summary.json") for d in sorted(run.glob("cycle-*"))]
    tot = lambda k: sum(c[k] for c in cyc)
    rt = lambda k: sum(c["runtime"][k] for c in cyc)
    conf, att = tot("confirmed_handovers"), tot("control_attempts")
    faults = rt("model_faults") + rt("fallback_frames") + rt("invalid_frames") + sum(c["runtime"]["runtime_fault"] is not None for c in cyc)
    started = datetime.fromisoformat(res["sustained_started"])
    finished = datetime.fromisoformat(res["finished"])
    utc = (finished - started).total_seconds()
    check(res["passed"] and res["cleanup_passed"] and res["source_hashes_match"], f"runner verdict PASS, cleanup PASS, {res['source_files_verified']} source hashes match")
    check({c["runtime"]["candidate_version"] for c in cyc} == {"v3.14.24"}, f"{len(cyc)} cycles, every one served by v3.14.24")
    check(conf == att == 82 and tot("failed_controls") == 0, f"{conf}/{att} AI handovers ACKed and CU-confirmed, 0 failed")
    check(faults == 0, f"{rt('inference_calls')} online inferences, 0 model faults / fallback / invalid frames")
    check(utc >= 7200, f"{utc:,.0f} s between the soak start and the runner's finish on the UTC clock (>= 7,200 s); "
                       f"verified sustained {ver['timing']['real_sustained_s']:,.1f} s")


def console():
    print("5. 3D console data (dashboard/campus3d/data)")
    d = ROOT / "dashboard/campus3d/data"
    acc = jload(d / "replay-seg0-v314.json")["acceptance"]
    ver = jload(EV / "live-v3.14/sustained-run2-20261118T192432Z/VERIFICATION.json")
    check(acc["kind"] == "soak" and acc["cycles"] == ver["cycles"] and acc["confirmed_handovers"] == ver["confirmed_handovers"]
          and acc["inference_calls"] == ver["inference_calls"] and acc["host_seconds"] == ver["timing"]["real_sustained_s"],
          f"'Executed · v3.14.24' shows the two-hour run: {acc['cycles']} cycles, {acc['confirmed_handovers']} CU-confirmed, "
          f"{acc['host_seconds'] / 3600:.2f} h")
    vr = jload(d / "v314-route.json")
    blob = json.dumps(vr)
    st = jload(EV / "finals-v3.14/final/stats.json")["comparisons"]["cho_global"]["utility"]["pooled"]["diff"]
    check(f"{st:+.3f}" in blob or f"{round(st, 3)}" in blob, f"'HORUS v3.14 (modelled)' verdict panel carries the held-out +{st:.3f} vs network CHO")
    check("-0.046" in blob, "and the measured-route failure (-0.046 vs network CHO)")
    man = jload(d / "manifest.json")
    bad = [n for n, m in man["outputs"].items() if (d / n).exists() and sha256(d / n) != m["sha256"]]
    check(not bad, "console data files match the console's own manifest" + (f" (mismatch: {bad})" if bad else ""))


def main():
    for step in (frozen_model, heldout, measured, live, console):
        try:
            step()
        except Exception as exc:          # a missing or malformed file is a failed check, not a crash
            check(False, f"{step.__name__}: {type(exc).__name__}: {exc}")
        print()
    print("ALL CHECKS PASS" if not FAILED else f"{len(FAILED)} CHECK(S) FAILED: " + "; ".join(FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
