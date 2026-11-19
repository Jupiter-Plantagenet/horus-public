"""Finals evaluation: every arm x every (scenario x fading) cell x N held-out
seeds, on IDENTICAL radio traces per (cell, seed) — a paired design.

Arms (resolved per cell where tuned):
    v2          the v2 learned policy (dqn2:<version>)
    a3_tuned    best A3 for THIS cell (oracle per-cell tuning, finals_baselines.json)
    a3_global   the single best A3 over all cells (what an operator deploys)
    cho_tuned   best conditional-HO config for this cell
    a3_stock    vendor-default A3 (Off 3 dB, Hys 1 dB, TTT 320 ms, fc4)
    a3_legacy   the v1.x baseline's knobs (margin 3 dB, TTT 3 s, no L3)
    v1.3.1      the promoted v1 policy (live loop), fed in its training units

Statistics (per metric): per-arm mean with a 95% t-CI over episodes; paired
difference vs a3_tuned with 95% t-CI, paired t-test and Wilcoxon signed-rank;
Holm correction over the per-cell tests. The go/no-go rule is pre-registered
in pipeline/finals_preregistration.json (committed before this ran) and
applied mechanically here.

Outputs (working/evidence/):
    finals-eval/eval.jsonl        one row per (cell, seed, arm)
    finals-eval/report.md         judge-facing tables + verdict
    finals-eval/stats.json        every number in report.md
    finals-results.json           dashboard contract horus.finals-results/1

    python -m twin.evaluate --v2 v2.1.0 --seeds 20 --workers 3
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from multiprocessing import Pool
from pathlib import Path

import numpy as np

from .finals_common import (BASELINES_JSON, EVAL_SEED0, EVIDENCE, FADINGS, RADIO_MAP,
                            SCENARIOS, REPO, single_thread, trace_for)

PREREG = REPO / "pipeline" / "finals_preregistration.json"
METRICS = [  # id, label, label_ko, unit, better, scale
    ("utility", "Operator utility (objective)", "운영자 효용 (목적함수)", "per UE-min", "higher", 1.0),
    ("pp_rate", "Ping-pong HOs (<1 s stay)", "핑퐁 핸드오버 (<1초 체류)", "per UE-min", "lower", 1.0),
    ("ho_rate", "Handover rate", "핸드오버 빈도", "per UE-min", "lower", 1.0),
    ("fail_rate", "Failures (RLF + HO failure)", "실패 (RLF + HO 실패)", "per UE-min", "lower", 1.0),
    ("rlf_rate", "Radio-link failures", "무선 링크 실패", "per UE-min", "lower", 1.0),
    ("mro_rate", "MRO events (late/early/wrong-cell)", "MRO 이벤트 (늦은/이른/잘못된 셀)", "per UE-min", "lower", 1.0),
    ("ho_success_rate", "HO success rate", "핸드오버 성공률", "%", "higher", 100.0),
    ("outage_frac", "Time in outage", "서비스 중단 시간", "%", "lower", 100.0),
    ("mean_thr_mbps", "Mean throughput (Shannon proxy)", "평균 처리량 (Shannon 근사)", "Mbps", "higher", 1.0),
    ("p5_thr_mbps", "5th-pct UE throughput", "하위 5% UE 처리량", "Mbps", "higher", 1.0),
    ("short_stay_rate", "Short-stay returns (<5 s)", "단기 복귀 (<5초)", "per UE-min", "lower", 1.0),
]


def arm_specs(v2_version, baselines):
    def tuned(fam):
        return lambda s, f: baselines["per_cell"][s][f][fam]["spec"]
    arms = {
        "a3_tuned": tuned("a3"),
        "a3_global": lambda s, f: baselines["global"]["a3"]["spec"],
        "cho_tuned": tuned("cho"),
        "a3_stock": lambda s, f: "a3",
        "a3_legacy": lambda s, f: "a3-legacy",
        "v1.3.1": lambda s, f: "dqn:v1.3.1",
        "mse_rule": lambda s, f: "mse-rule:thr=2.0",
    }
    if v2_version:
        arms = {"v2": lambda s, f: f"dqn2:{v2_version}", **arms}
    return arms


def _task(args):
    single_thread()
    scenario, fading, seed, specs = args
    from .controllers_v2 import parse_controller
    from .sim import SimConfig, run_on_trace, utility_per_ue_min
    t0 = time.time()
    tr = trace_for(scenario, fading, seed)
    rows = []
    for arm, spec in specs.items():
        m = run_on_trace(parse_controller(spec), tr, SimConfig())[0]
        m["utility"] = round(utility_per_ue_min(m), 4)
        rows.append({"scenario": scenario, "fading": fading, "seed": seed, "arm": arm,
                     "spec": spec, **m})
    return rows, time.time() - t0


# ------------------------------------------------------------------ stats
def tci(x):
    from scipy import stats
    x = np.asarray(x, float)
    n = len(x)
    mu = float(x.mean())
    if n < 2:
        return mu, mu, mu
    h = float(stats.t.ppf(0.975, n - 1) * x.std(ddof=1) / np.sqrt(n))
    return mu, mu - h, mu + h


def paired(a, b):
    """a - b paired: mean, 95% t-CI, t-test p, Wilcoxon p."""
    from scipy import stats
    d = np.asarray(a, float) - np.asarray(b, float)
    mu, lo, hi = tci(d)
    if np.allclose(d, 0):
        return {"diff": 0.0, "ci_low": 0.0, "ci_high": 0.0, "p_t": 1.0, "p_wilcoxon": 1.0, "n": len(d)}
    p_t = float(stats.ttest_1samp(d, 0.0).pvalue)
    try:
        p_w = float(stats.wilcoxon(d).pvalue)
    except ValueError:
        p_w = 1.0
    return {"diff": mu, "ci_low": lo, "ci_high": hi, "p_t": p_t, "p_wilcoxon": p_w, "n": len(d)}


def holm(ps):
    order = np.argsort(ps)
    adj = np.empty(len(ps))
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (len(ps) - rank) * ps[i]))
        adj[i] = running
    return adj.tolist()


def analyse(rows, prereg, policy="v2", ref="a3_tuned"):
    cells = [(s, f) for s in SCENARIOS for f in FADINGS]
    arms = sorted({r["arm"] for r in rows})
    val = {}
    for r in rows:
        val.setdefault((r["arm"], r["scenario"], r["fading"]), {})[r["seed"]] = r
    seeds = sorted({r["seed"] for r in rows})
    out = {"cells": {}, "pooled": {}, "per_scenario": {}}

    def series(arm, metric, cell_list):
        xs = []
        for s, f in cell_list:
            d = val.get((arm, s, f), {})
            xs += [d[sd][metric] if d[sd][metric] is not None else np.nan for sd in seeds if sd in d]
        return np.asarray(xs, float)

    for mid, *_ in METRICS:
        out["pooled"][mid] = {a: tci(series(a, mid, cells)) for a in arms}
        for s in SCENARIOS:
            out["per_scenario"].setdefault(s, {})[mid] = {
                a: tci(series(a, mid, [(s, f) for f in FADINGS])) for a in arms}
        for s, f in cells:
            out["cells"].setdefault(f"{s}/{f}", {})[mid] = {a: tci(series(a, mid, [(s, f)])) for a in arms}

    comp = {}
    if policy in arms:
        for mid, *_ in METRICS:
            pooled = paired(series(policy, mid, cells), series(ref, mid, cells))
            per = {f"{s}/{f}": paired(series(policy, mid, [(s, f)]), series(ref, mid, [(s, f)]))
                   for s, f in cells}
            adj = holm([v["p_t"] for v in per.values()])
            for (k, v), pa in zip(per.items(), adj):
                v["p_holm"] = pa
            comp[mid] = {"pooled": pooled, "cells": per}
    out["comparison"] = {"policy": policy, "ref": ref, "metrics": comp}
    # pre-registered SECONDARY comparisons (reported, not part of the go/no-go)
    sec = {}
    for pol in [x for x in arms if x == "v2" or x.startswith("v2.")]:
        for other in ("a3_tuned", "a3_global", "a3_stock", "cho_tuned", "mse_rule", "v1.3.1"):
            if other in arms and other != pol:
                sec[f"{pol} - {other}"] = {mid: paired(series(pol, mid, cells), series(other, mid, cells))
                                           for mid, *_ in METRICS}
    out["secondary"] = sec
    out["verdict"] = verdict(comp, out["pooled"], prereg, policy, ref) if comp else None
    out["seeds"] = seeds
    return out


def verdict(comp, pooled, prereg, policy, ref):
    rule = prereg["go_no_go"]
    checks = []
    better = {m[0]: m[4] for m in METRICS}
    for mid in rule["primary"]:
        p = comp[mid]["pooled"]
        ok = p["ci_low"] > 0 if better[mid] == "higher" else p["ci_high"] < 0
        checks.append({"check": f"primary {mid}: pooled 95% CI of ({policy} - {ref}) excludes 0 in {policy}'s favour",
                       "pass": bool(ok), "diff": p["diff"], "ci": [p["ci_low"], p["ci_high"]]})
    for g in rule["guardrails"]:
        mid, rel, abs_m = g["metric"], g["rel_margin"], g["abs_margin"]
        refmean = pooled[mid][ref][0]
        margin = max(rel * abs(refmean), abs_m)
        p = comp[mid]["pooled"]
        ok = p["ci_high"] <= margin
        bad_cells = [k for k, v in comp[mid]["cells"].items()
                     if v["p_holm"] < 0.05 and v["diff"] > max(rel * abs(
                         pooled[mid][ref][0]), abs_m)]
        checks.append({"check": f"guardrail {mid}: pooled upper 95% CI of increase <= {margin:.4f} "
                                f"(max({rel:.0%} of {ref} mean, {abs_m})) and no cell with a "
                                "Holm-significant increase beyond that margin",
                       "pass": bool(ok and not bad_cells), "diff": p["diff"],
                       "ci": [p["ci_low"], p["ci_high"]], "cells_regressed": bad_cells})
    go = all(c["pass"] for c in checks)
    return {"go": go, "checks": checks,
            "rule": rule["statement"]}


# ------------------------------------------------------------------ outputs
def fmt(t, scale=1.0, nd=3):
    mu, lo, hi = (v * scale for v in t)
    return f"{mu:.{nd}f} [{lo:.{nd}f}, {hi:.{nd}f}]"


def write_report(st, meta, out_dir):
    known = ("v2", "a3_tuned", "a3_global", "cho_tuned", "mse_rule", "a3_stock", "a3_legacy", "v1.3.1")
    arms_order = [a for a in known if a in st["pooled"]["utility"]]
    arms_order += sorted(a for a in st["pooled"]["utility"] if a not in known)
    L = [f"# HORUS finals evaluation — twin v2, {RADIO_MAP} map, held-out seeds "
         f"{st['seeds'][0]}..{st['seeds'][-1]} (n={len(st['seeds'])} per cell)", "",
         f"Generated {meta['generated_ts']} at commit {meta['commit']}. Every arm ran on identical "
         "radio traces per (cell, seed) — paired design. Means with 95% t-CIs over episodes.", ""]
    v = st.get("verdict")
    if v:
        L += [f"## Go/no-go (pre-registered): **{'GO — v2 is the headline' if v['go'] else 'NO-GO — v2 does not clear the bar'}**",
              "", f"Rule: {v['rule']}", ""]
        for c in v["checks"]:
            L.append(f"- {'PASS' if c['pass'] else 'FAIL'} — {c['check']}: diff {c['diff']:.4f}, "
                     f"95% CI [{c['ci'][0]:.4f}, {c['ci'][1]:.4f}]"
                     + (f"; regressed cells: {c['cells_regressed']}" if c.get("cells_regressed") else ""))
        L.append("")
    L += ["## Pooled over all 12 cells (4 scenarios x 3 fading modes)", "",
          "| metric | " + " | ".join(arms_order) + " |", "|---|" + "---|" * len(arms_order)]
    for mid, label, _, unit, better, scale in METRICS:
        L.append(f"| {label} ({unit}, {better} better) | " +
                 " | ".join(fmt(st["pooled"][mid][a], scale, 2 if scale > 1 or 'thr' in mid else 3)
                            for a in arms_order) + " |")
    comp = st["comparison"]["metrics"]
    if comp:
        L += ["", f"## {st['comparison']['policy']} minus {st['comparison']['ref']} (paired), per cell", "",
              "| cell | utility diff [95% CI] (p_holm) | ping-pong diff | HO-rate diff | fail-rate diff | thr diff (Mbps) |",
              "|---|---|---|---|---|---|"]
        for cell in comp["utility"]["cells"]:
            def c(mid):
                x = comp[mid]["cells"][cell]
                return f"{x['diff']:+.3f} [{x['ci_low']:+.3f}, {x['ci_high']:+.3f}] (p={x['p_holm']:.3g})"
            L.append(f"| {cell} | {c('utility')} | {c('pp_rate')} | {c('ho_rate')} | {c('fail_rate')} | {c('mean_thr_mbps')} |")
        L += ["", "Pooled paired differences (all cells):", ""]
        for mid, label, *_ in METRICS:
            x = comp[mid]["pooled"]
            L.append(f"- {label}: {x['diff']:+.4f} [{x['ci_low']:+.4f}, {x['ci_high']:+.4f}], "
                     f"paired t p={x['p_t']:.3g}, Wilcoxon p={x['p_wilcoxon']:.3g}, n={x['n']}")
    if st.get("secondary"):
        L += ["", "## Secondary paired comparisons, pooled over all cells (reported, NOT part of the go/no-go)", "",
              "| comparison | utility | ping-pong | HO rate | failures | mean thr (Mbps) |", "|---|---|---|---|---|---|"]
        for k, d in st["secondary"].items():
            c = lambda mid: f"{d[mid]['diff']:+.3f} [{d[mid]['ci_low']:+.3f}, {d[mid]['ci_high']:+.3f}]"
            L.append(f"| {k} | {c('utility')} | {c('pp_rate')} | {c('ho_rate')} | {c('fail_rate')} | {c('mean_thr_mbps')} |")
    L += ["", "## Per cell, all arms", ""]
    for cell, d in st["cells"].items():
        L += [f"### {cell}", "", "| metric | " + " | ".join(arms_order) + " |",
              "|---|" + "---|" * len(arms_order)]
        for mid, label, _, unit, better, scale in METRICS[:10]:
            L.append(f"| {label} | " + " | ".join(fmt(d[mid][a], scale, 2 if scale > 1 or 'thr' in mid else 3)
                                                  for a in arms_order) + " |")
        L.append("")
    L += ["## Arms", ""] + [f"- `{a}`: {meta['arm_desc'].get(a, '')}" for a in arms_order]
    (out_dir / "report.md").write_text("\n".join(L) + "\n", encoding="utf-8")


def dashboard_json(st, meta, policy_arm, path):
    arm_ids = {policy_arm: "policy", "a3_tuned": "a3_tuned", "a3_stock": "a3_stock"}
    extra = [a for a in ("v2", "v2.0.2-central", "v1.3.1", "a3_global", "cho_tuned", "mse_rule", "a3_legacy")
             if a in st["pooled"]["utility"] and a not in arm_ids]
    arms = [{"id": "policy", "label": meta["arm_label"][policy_arm], "label_ko": meta["arm_label_ko"][policy_arm]},
            {"id": "a3_tuned", "label": meta["arm_label"]["a3_tuned"], "label_ko": meta["arm_label_ko"]["a3_tuned"]},
            {"id": "a3_stock", "label": meta["arm_label"]["a3_stock"], "label_ko": meta["arm_label_ko"]["a3_stock"]}]
    arms += [{"id": a, "label": meta["arm_label"][a], "label_ko": meta["arm_label_ko"][a]} for a in extra]
    src = {**arm_ids, **{a: a for a in extra}}
    n_pool = len(st["seeds"]) * len(SCENARIOS) * len(FADINGS)
    n_scen = len(st["seeds"]) * len(FADINGS)
    metrics = []

    def vals(table, n, scale):
        out = {}
        for a, dash in src.items():
            mu, lo, hi = table[a]
            if not np.isfinite(mu):
                continue
            out[dash] = {"mean": round(mu * scale, 4), "ci_low": round(lo * scale, 4),
                         "ci_high": round(hi * scale, 4), "n": n}
        return out

    for mid, label, label_ko, unit, better, scale in METRICS:
        metrics.append({"id": mid, "label": label, "label_ko": label_ko, "unit": unit,
                        "better": better, "scenario": None,
                        "values": vals(st["pooled"][mid], n_pool, scale)})
    for s in SCENARIOS:
        for mid, label, label_ko, unit, better, scale in METRICS:
            if mid not in ("utility", "pp_rate", "ho_rate", "fail_rate", "mean_thr_mbps"):
                continue
            metrics.append({"id": f"{mid}@{s}", "label": label, "label_ko": label_ko, "unit": unit,
                            "better": better, "scenario": s,
                            "values": vals(st["per_scenario"][s][mid], n_scen, scale)})
    v = st.get("verdict")
    doc = {
        "schema": "horus.finals-results/1",
        "generated_ts": meta["generated_ts"],
        "title": f"{meta['arm_label'][policy_arm]} vs A3 baselines — Kumoh twin v2, held-out seeds",
        "title_ko": f"{meta['arm_label_ko'][policy_arm]} vs A3 기준선 — 금오공대 디지털 트윈 v2, 미사용 시드",
        "arms": arms, "metrics": metrics,
        "provenance": {
            "twin": "twin v2: 100 ms step, per-RE RSRP (n78 100 MHz, 273 PRB), RS-SINR with 50% interferer load, "
                    "Doppler-correlated fading (2-branch diversity), 3GPP RLF (Qout -8 dB / Qin -6 dB, N310=2, T310=1 s), "
                    "HO failure on source-command loss or target SINR < Qout, 1 s re-establishment",
            "radio_map": f"{RADIO_MAP} (9 nearest real Kumoh sites)",
            "cells": f"{len(SCENARIOS)} scenarios ({', '.join(SCENARIOS)}) x {len(FADINGS)} fading ({', '.join(FADINGS)})",
            "eval_seeds": f"{st['seeds'][0]}-{st['seeds'][-1]} (held out: training 0-499, sweep 500-599, federation 600-999, gate 1100+)",
            "episodes_per_arm": n_pool, "episode_length": "300 s",
            "pairing": "all arms run on identical radio traces per (cell, seed)",
            "ci_method": "95% Student-t CI of the mean over episodes; paired-difference tests in report.md",
            "a3_tuning": "a3_tuned = best of 504 A3 configs (offset x hys x TTT x L3 k) per (scenario, fading) cell "
                         "on sweep seeds 500-504, objective = operator utility; a3_stock = Off 3 dB / Hys 1 dB / TTT 320 ms / fc4",
            "objective": "utility = 60*meanSE/7.4 - 0.3*HO - 2*ping-pong - 5*(RLF+HOF), per UE-minute",
            "policy_arm": (f"{policy_arm} — v2 {'PASSED' if v['go'] else 'did NOT pass'} the pre-registered "
                           f"go/no-go vs a3_tuned" + ("" if (v['go'] or policy_arm != 'v2') else
                                                      "; v2 shown as policy by explicit choice, not as the GO headline"))
                          if v else policy_arm,
            "go_no_go": ("GO" if v["go"] else "NO-GO") if v else "n/a",
            "commit": meta["commit"],
        },
    }
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def git_commit():
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, timeout=10, cwd=REPO).stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m twin.evaluate")
    ap.add_argument("--v2", default=None, help="v2 policy version (dqn2:<v>)")
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--seed0", type=int, default=EVAL_SEED0)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--arms", default=None, help="comma list to restrict arms")
    ap.add_argument("--extra-arm", action="append", default=[],
                    help="name=spec, e.g. v2.0.2-central=dqn2:v2.0.2 (reported, not compared)")
    ap.add_argument("--out", type=Path, default=EVIDENCE / "finals-eval")
    ap.add_argument("--reuse", action="store_true", help="re-analyse existing eval.jsonl only")
    ap.add_argument("--also-v2-dashboard", action="store_true",
                    help="additionally write finals-results-v2-as-policy.json (policy arm = v2 "
                         "regardless of the go/no-go; provenance says so)")
    ap.add_argument("--append", action="store_true",
                    help="add the selected arms to an existing eval.jsonl (same seeds/cells)")
    a = ap.parse_args(argv)
    if a.seed0 < 2000:
        raise SystemExit("evaluation seeds start at 2000 (lower ranges are training/sweep/gate)")
    baselines = json.loads(BASELINES_JSON.read_text(encoding="utf-8"))
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    specs_fn = arm_specs(a.v2, baselines)
    if a.arms:
        keep = a.arms.split(",")
        specs_fn = {k: v for k, v in specs_fn.items() if k in keep}
    for ea in a.extra_arm:
        name, spec = ea.split("=", 1)
        specs_fn[name] = (lambda sp: (lambda s, f: sp))(spec)
    a.out.mkdir(parents=True, exist_ok=True)
    jl = a.out / "eval.jsonl"
    if not a.reuse:
        tasks = [(s, f, a.seed0 + i, {arm: fn(s, f) for arm, fn in specs_fn.items()})
                 for i in range(a.seeds) for s in SCENARIOS for f in FADINGS]
        print(f"evaluate: {len(specs_fn)} arms x {len(tasks)} traces", file=sys.stderr)
        with Pool(a.workers) as pool, jl.open("a" if a.append else "w", encoding="utf-8") as fh:
            for i, (rs, dt) in enumerate(pool.imap_unordered(_task, tasks)):
                for r in rs:
                    fh.write(json.dumps(r) + "\n")
                fh.flush()
                print(f"  [{i + 1}/{len(tasks)}] {rs[0]['scenario']}/{rs[0]['fading']}/{rs[0]['seed']} {dt:.0f}s",
                      file=sys.stderr, flush=True)
    rows = [json.loads(l) for l in jl.read_text(encoding="utf-8").splitlines() if l.strip()]
    if a.v2 is None:
        a.v2 = next((r["spec"].split(":", 1)[1] for r in rows if r["arm"] == "v2"), None)
    st = analyse(rows, prereg, policy="v2" if a.v2 else "v1.3.1")
    v = st["verdict"]
    policy_arm = "v2" if (v and v["go"]) else "v1.3.1"
    g = baselines["global"]["a3"]["spec"]
    meta = {
        "generated_ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit": git_commit(),
        "arm_label": {"v2": f"HORUS policy {a.v2}", "v1.3.1": "HORUS policy v1.3.1 (live-loop promoted)",
                      "a3_tuned": "Best-tuned A3 (per scenario x fading)", "a3_global": f"Tuned A3, one config ({g})",
                      "cho_tuned": "Best-tuned conditional HO", "a3_stock": "Stock A3 (Off 3 dB, Hys 1 dB, TTT 320 ms)",
                      "a3_legacy": "A3 with v1.x knobs (3 dB, TTT 3 s, no L3)",
                      "mse_rule": "Mobility-rule A3 (ablation)",
                      "v2.0.2-central": "HORUS v2.0.2 (central, pre-federation; not gated)"},
        "arm_label_ko": {"v2": f"HORUS 정책 {a.v2}", "v1.3.1": "HORUS 정책 v1.3.1 (라이브 루프 승격)",
                         "a3_tuned": "최적 튜닝 A3 (시나리오 x 페이딩별)", "a3_global": "튜닝 A3 (단일 설정)",
                         "cho_tuned": "최적 튜닝 조건부 핸드오버", "a3_stock": "기본 A3 (Off 3 dB, Hys 1 dB, TTT 320 ms)",
                         "a3_legacy": "v1.x 설정 A3 (3 dB, TTT 3초, L3 없음)",
                         "mse_rule": "이동성 규칙 A3 (절제 실험)",
                         "v2.0.2-central": "HORUS v2.0.2 (중앙 학습, 연합 전; 게이트 미적용)"},
        "arm_desc": {"v2": f"v2 DQN+LSTM checkpoint {a.v2} (L3 fc4 observations, 200 ms decisions)",
                     "a3_tuned": "per-cell oracle: best of the 504-config A3 sweep for that (scenario, fading)",
                     "a3_global": f"single best A3 over all cells: `{g}`",
                     "cho_tuned": "per-cell best of the 450-config CHO sweep",
                     "a3_stock": "Off 3 dB, Hys 1 dB, TTT 320 ms, fc4", "a3_legacy": "margin 3 dB, TTT 3 s, k=0",
                     "v1.3.1": "promoted v1 policy (legacy twin), 1 s decisions on L3 RSRP in its training units",
                     "v2.0.2-central": "central v2 checkpoint before federation (best validation pick); never gated — reported for diagnosis",
                     "mse_rule": "ABLATION added after pre-registration: same profile engine + mobility index as v2, hand rule (index < 2 dB -> static-faded, else mobile)"},
    }
    (a.out / "stats.json").write_text(json.dumps(st, indent=1, default=float) + "\n", encoding="utf-8")
    write_report(st, meta, a.out)
    dashboard_json(st, meta, policy_arm, EVIDENCE / "finals-results.json")
    if a.also_v2_dashboard and "v2" in st["pooled"]["utility"] and policy_arm != "v2":
        dashboard_json(st, meta, "v2", EVIDENCE / "finals-results-v2-as-policy.json")
    print((a.out / "report.md").read_text(encoding="utf-8")[:6000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
