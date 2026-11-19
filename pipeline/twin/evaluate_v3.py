"""v3 finals evaluation: all arms x 12 cells x N seeds on identical traces
(paired), every arm of a trace run in ONE sim pass (composite.MultiArm; rows
are independent, so this equals separate runs — tests/test_v3.py).

The go/no-go of pipeline/finals_preregistration_v3.json is applied
mechanically: H1 (v3 vs every per-cell oracle) and H2 (v3 vs every deployable
baseline), each an intersection-union of pooled paired 95% t-CIs on utility
plus guardrails (pooled upper CI of the increase within margin, no
Holm-significant per-cell increase beyond margin).

    # tuning seeds (model selection; no verdict written to the dashboard)
    python -m twin.evaluate_v3 --v3 v3.0.0 --seed0 1000 --seeds 20 --out working/evidence/finals-v3/tune-v3.0.0
    # held-out confirmatory run (pre-registered: 2100..2119)
    python -m twin.evaluate_v3 --v3 v3.x.y --seed0 2100 --seeds 20 --final
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from multiprocessing import Pool
from pathlib import Path

import numpy as np

from .evaluate import METRICS, fmt, git_commit, holm, paired, tci
from .finals_common import (BASELINES_JSON, EVIDENCE, FADINGS, RADIO_MAP, REPO, SCENARIOS,
                            single_thread, trace_for)

PREREG = REPO / "pipeline" / "finals_preregistration_v3.json"
BASELINES_V3 = REPO / "pipeline" / "finals_baselines_v3.json"
ORACLES = ("a3_tuned", "cho_tuned", "cho_tuned_ext")
DEPLOYABLE = ("a3_global", "cho_global", "cho_global_ext", "cho_mse", "cho_mro")
HELD_OUT = range(2100, 2120)


def arm_table(b2, b3, v3=None, extra=()):
    """name -> fn(scenario, fading) -> spec (str) or ('mse'|'mro', params)."""
    t = {
        "a3_tuned": lambda s, f: b2["per_cell"][s][f]["a3"]["spec"],
        "cho_tuned": lambda s, f: b2["per_cell"][s][f]["cho"]["spec"],
        "cho_tuned_ext": lambda s, f: b3["per_cell"][s][f]["cho_ext"]["spec"],
        "a3_global": lambda s, f: b2["global"]["a3"]["spec"],
        "cho_global": lambda s, f: b2["global"]["cho"]["spec"],
        "cho_global_ext": lambda s, f: b3["global"]["cho_ext"]["spec"],
        "cho_mse": lambda s, f: "mse:" + b3["global"]["cho_mse"]["spec"],
        "cho_mro": lambda s, f: "mro:" + b3["global"]["cho_mro"]["spec"],
        "a3_stock": lambda s, f: "a3",
    }
    if v3:
        t = {"v3": lambda s, f: f"dqn2:{v3}", **t}
    for name, spec in extra:
        t[name] = (lambda sp: (lambda s, f: sp))(spec)
    return t


def make_controller(spec):
    from .cho_v3 import CHOMRO, CHOSpeedScaled, ProfileCHO, parse_profile
    from .controllers_v2 import parse_controller
    if spec.startswith("mse:") or spec.startswith("mro:"):
        p = json.loads(spec[4:])
        base = p.pop("base")
        return (CHOSpeedScaled if spec[:3] == "mse" else CHOMRO)(base, **p)
    if spec.startswith("cho:") and ",k=" in spec and "prep=" in spec:
        # every CHO arm runs on ProfileCHO (own per-arm L3 filter); identical to
        # CHOBatch with the sim filter at the same k (tests/test_v3.py)
        return ProfileCHO([parse_profile(spec)])
    return parse_controller(spec)


def _task(args):
    single_thread()
    from .composite import run_arms
    from .sim import SimConfig, utility_per_ue_min
    scenario, fading, seed, specs = args
    t0 = time.time()
    tr = trace_for(scenario, fading, seed)
    names = list(specs)
    ms = run_arms(tr, [make_controller(specs[a]) for a in names], SimConfig())
    rows = []
    for arm, m in zip(names, ms):
        m["utility"] = round(utility_per_ue_min(m), 4)
        rows.append({"scenario": scenario, "fading": fading, "seed": seed, "arm": arm,
                     "spec": specs[arm], **m})
    return rows, time.time() - t0


def analyse(rows, prereg=None, policy="v3"):
    cells = [(s, f) for s in SCENARIOS for f in FADINGS]
    arms = sorted({r["arm"] for r in rows})
    val = {}
    for r in rows:
        val.setdefault((r["arm"], r["scenario"], r["fading"]), {})[r["seed"]] = r
    seeds = sorted({r["seed"] for r in rows})

    def series(arm, metric, cl):
        xs = []
        for s, f in cl:
            d = val.get((arm, s, f), {})
            xs += [d[sd][metric] if d[sd][metric] is not None else np.nan for sd in seeds if sd in d]
        return np.asarray(xs, float)

    out = {"seeds": seeds, "pooled": {}, "per_scenario": {}, "cells": {}, "comparisons": {}}
    for mid, *_ in METRICS:
        out["pooled"][mid] = {a: tci(series(a, mid, cells)) for a in arms}
        for s in SCENARIOS:
            out["per_scenario"].setdefault(s, {})[mid] = {a: tci(series(a, mid, [(s, f) for f in FADINGS])) for a in arms}
        for s, f in cells:
            out["cells"].setdefault(f"{s}/{f}", {})[mid] = {a: tci(series(a, mid, [(s, f)])) for a in arms}
    if policy in arms:
        for ref in [a for a in arms if a != policy]:
            comp = {}
            for mid, *_ in METRICS:
                pooled = paired(series(policy, mid, cells), series(ref, mid, cells))
                per = {f"{s}/{f}": paired(series(policy, mid, [(s, f)]), series(ref, mid, [(s, f)])) for s, f in cells}
                for (k, v), pa in zip(per.items(), holm([v["p_t"] for v in per.values()])):
                    v["p_holm"] = pa
                comp[mid] = {"pooled": pooled, "cells": per}
            out["comparisons"][ref] = comp
    if prereg and policy in arms:
        out["verdict"] = verdict(out, prereg, policy)
    return out


def _check(comp, pooled, ref, rule, policy):
    checks = []
    p = comp["utility"]["pooled"]
    checks.append({"check": f"utility: pooled 95% CI of ({policy} - {ref}) > 0", "pass": bool(p["ci_low"] > 0),
                   "diff": p["diff"], "ci": [p["ci_low"], p["ci_high"]]})
    for g in rule["guardrails"]:
        mid = g["metric"]
        margin = max(g["rel_margin"] * abs(pooled[mid][ref][0]), g["abs_margin"])
        q = comp[mid]["pooled"]
        bad = [k for k, v in comp[mid]["cells"].items() if v["p_holm"] < 0.05 and v["diff"] > margin]
        checks.append({"check": f"guardrail {mid}: pooled upper CI of increase <= {margin:.4f} and no "
                                f"Holm-significant cell increase beyond it",
                       "pass": bool(q["ci_high"] <= margin and not bad), "diff": q["diff"],
                       "ci": [q["ci_low"], q["ci_high"]], "cells_regressed": bad})
    return checks


def verdict(st, prereg, policy):
    rule = prereg["go_no_go"]
    res = {}
    for hyp, refs in (("H1_oracle", ORACLES), ("H2_deployable", DEPLOYABLE)):
        per = {}
        for ref in refs:
            if ref not in st["comparisons"]:
                per[ref] = {"pass": False, "checks": [{"check": f"{ref} missing", "pass": False}]}
                continue
            ch = _check(st["comparisons"][ref], st["pooled"], ref, rule, policy)
            per[ref] = {"pass": all(c["pass"] for c in ch), "checks": ch}
        res[hyp] = {"pass": all(v["pass"] for v in per.values()), "refs": per}
    res["headline"] = ("H1" if res["H1_oracle"]["pass"] else "H2" if res["H2_deployable"]["pass"] else "NO-GO")
    return res


ARM_LABEL = {
    "v3": ("HORUS v3 (learned per-UE CHO profile selector)", "HORUS v3 (학습형 UE별 CHO 프로파일 선택기)"),
    "a3_tuned": ("Best-tuned A3 per scenario x fading (oracle)", "최적 튜닝 A3 (시나리오 x 페이딩별, 오라클)"),
    "cho_tuned": ("Best-tuned CHO per scenario x fading (oracle)", "최적 튜닝 CHO (시나리오 x 페이딩별, 오라클)"),
    "cho_tuned_ext": ("Best-tuned CHO per cell, extended grid (oracle)", "최적 튜닝 CHO, 확장 그리드 (오라클)"),
    "a3_global": ("Tuned A3, one network-wide config", "튜닝 A3 (네트워크 단일 설정)"),
    "cho_global": ("Tuned CHO, one network-wide config", "튜닝 CHO (네트워크 단일 설정)"),
    "cho_global_ext": ("Tuned CHO, one config (extended grid)", "튜닝 CHO (단일 설정, 확장 그리드)"),
    "cho_mse": ("CHO + 3GPP mobility-state scaling (tuned)", "CHO + 3GPP 이동성 상태 스케일링 (튜닝)"),
    "cho_mro": ("CHO + MRO online offset tuning (tuned)", "CHO + MRO 온라인 오프셋 조정 (튜닝)"),
    "a3_stock": ("Stock A3 (Off 3 dB, Hys 1 dB, TTT 320 ms)", "기본 A3 (Off 3 dB, Hys 1 dB, TTT 320 ms)"),
    "v1.3.1": ("HORUS policy v1.3.1 (live-loop promoted)", "HORUS 정책 v1.3.1 (라이브 루프 승격)"),
    "v2.0.2-central": ("HORUS v2.0.2 (DQN profile policy, central)", "HORUS v2.0.2 (DQN 프로파일 정책, 중앙)"),
    "mse_rule": ("Mobility-rule A3 (v2 ablation)", "이동성 규칙 A3 (v2 절제 실험)"),
}


def write_report(st, meta, out_dir, policy="v3"):
    order = [a for a in ("v3",) + ORACLES + DEPLOYABLE + ("a3_stock", "v2.0.2-central", "mse_rule", "v1.3.1")
             if a in st["pooled"]["utility"]]
    order += sorted(a for a in st["pooled"]["utility"] if a not in order)
    L = [f"# HORUS v3 evaluation — twin v2, {RADIO_MAP} map, seeds {st['seeds'][0]}..{st['seeds'][-1]} "
         f"(n={len(st['seeds'])} per cell, {meta['kind']})", "",
         f"Generated {meta['generated_ts']} at commit {meta['commit']}. All arms on identical radio traces per "
         "(cell, seed), run in one sim pass per trace. Means with 95% t-CIs over episodes.", ""]
    v = st.get("verdict")
    if v:
        L += [f"## Pre-registered go/no-go (finals_preregistration_v3.json): **{v['headline']}**", ""]
        for hyp in ("H1_oracle", "H2_deployable"):
            L.append(f"### {hyp}: {'PASS' if v[hyp]['pass'] else 'FAIL'}")
            for ref, r in v[hyp]["refs"].items():
                L.append(f"- vs `{ref}`: {'PASS' if r['pass'] else 'FAIL'}")
                for c in r["checks"]:
                    ci = c.get("ci")
                    L.append(f"  - {'PASS' if c['pass'] else 'FAIL'} {c['check']}" +
                             (f": diff {c['diff']:+.4f} [{ci[0]:+.4f}, {ci[1]:+.4f}]" if ci else "") +
                             (f"; regressed cells {c['cells_regressed']}" if c.get("cells_regressed") else ""))
            L.append("")
    L += ["## Pooled over all 12 cells", "", "| metric | " + " | ".join(order) + " |",
          "|---|" + "---|" * len(order)]
    for mid, label, _, unit, better, scale in METRICS:
        L.append(f"| {label} ({unit}, {better} better) | " + " | ".join(
            fmt(st["pooled"][mid][a], scale, 2 if scale > 1 or "thr" in mid else 3) for a in order) + " |")
    if st["comparisons"]:
        L += ["", f"## {policy} minus each arm (paired, pooled over 240 episodes unless fewer seeds)", "",
              "| reference | utility | HO rate | failures | ping-pong | mean thr (Mbps) | cells v3 better / worse (Holm p<0.05) |",
              "|---|---|---|---|---|---|---|"]
        for ref in order:
            if ref not in st["comparisons"]:
                continue
            d = st["comparisons"][ref]
            c = lambda mid: f"{d[mid]['pooled']['diff']:+.3f} [{d[mid]['pooled']['ci_low']:+.3f}, {d[mid]['pooled']['ci_high']:+.3f}]"
            cu = d["utility"]["cells"]
            nb = sum(1 for x in cu.values() if x["p_holm"] < 0.05 and x["diff"] > 0)
            nw = sum(1 for x in cu.values() if x["p_holm"] < 0.05 and x["diff"] < 0)
            L.append(f"| {ref} | {c('utility')} | {c('ho_rate')} | {c('fail_rate')} | {c('pp_rate')} | {c('mean_thr_mbps')} | {nb} / {nw} |")
        for ref in [r for r in ORACLES + DEPLOYABLE if r in st["comparisons"]]:
            d = st["comparisons"][ref]["utility"]["cells"]
            L += ["", f"### {policy} - {ref}, utility per cell", "", "| cell | diff [95% CI] | p_holm |", "|---|---|---|"]
            for cell, x in d.items():
                L.append(f"| {cell} | {x['diff']:+.3f} [{x['ci_low']:+.3f}, {x['ci_high']:+.3f}] | {x['p_holm']:.3g} |")
    L += ["", "## Per cell, utility (all arms)", "", "| cell | " + " | ".join(order) + " |", "|---|" + "---|" * len(order)]
    for cell, d in st["cells"].items():
        L.append(f"| {cell} | " + " | ".join(fmt(d["utility"][a]) for a in order) + " |")
    L += ["", "## Arms", ""] + [f"- `{a}`: {meta['specs'].get(a, '')}" for a in order]
    (out_dir / "report.md").write_text("\n".join(L) + "\n", encoding="utf-8")


def dashboard_json(st, meta, policy_arm, path):
    """horus.finals-results/1 — fixed ids policy / a3_tuned / a3_stock + extra arms."""
    order = [a for a in (policy_arm, "a3_tuned", "a3_stock") if a in st["pooled"]["utility"]]
    extra = [a for a in ("v3",) + ORACLES + DEPLOYABLE + ("v2.0.2-central", "v1.3.1", "mse_rule")
             if a in st["pooled"]["utility"] and a not in order]
    ids = {policy_arm: "policy", "a3_tuned": "a3_tuned", "a3_stock": "a3_stock", **{a: a for a in extra}}
    lab = lambda a: ARM_LABEL.get(a, (a, a))
    arms = [{"id": ids[a], "label": lab(a)[0], "label_ko": lab(a)[1]} for a in order + extra]
    n_pool = len(st["seeds"]) * len(SCENARIOS) * len(FADINGS)
    n_scen = len(st["seeds"]) * len(FADINGS)

    def vals(table, n, scale):
        out = {}
        for a, dash in ids.items():
            if a not in table:
                continue
            mu, lo, hi = table[a]
            if np.isfinite(mu):
                out[dash] = {"mean": round(mu * scale, 4), "ci_low": round(lo * scale, 4),
                             "ci_high": round(hi * scale, 4), "n": n}
        return out

    metrics = []
    for mid, label, label_ko, unit, better, scale in METRICS:
        metrics.append({"id": mid, "label": label, "label_ko": label_ko, "unit": unit, "better": better,
                        "scenario": None, "values": vals(st["pooled"][mid], n_pool, scale)})
    for s in SCENARIOS:
        for mid, label, label_ko, unit, better, scale in METRICS:
            if mid in ("utility", "pp_rate", "ho_rate", "fail_rate", "mean_thr_mbps"):
                metrics.append({"id": f"{mid}@{s}", "label": label, "label_ko": label_ko, "unit": unit,
                                "better": better, "scenario": s,
                                "values": vals(st["per_scenario"][s][mid], n_scen, scale)})
    v = st.get("verdict") or {}
    head = v.get("headline", "n/a")
    doc = {
        "schema": "horus.finals-results/1",
        "generated_ts": meta["generated_ts"],
        "title": f"{lab(policy_arm)[0]} vs A3/CHO baselines — Kumoh twin v2, held-out seeds",
        "title_ko": f"{lab(policy_arm)[1]} vs A3/CHO 기준선 — 금오공대 디지털 트윈 v2, 미사용 시드",
        "arms": arms, "metrics": metrics,
        "provenance": {
            "twin": "twin v2: 100 ms step, per-RE RSRP (n78 100 MHz, 273 PRB), RS-SINR with 50% interferer load, "
                    "Doppler-correlated fading (2-branch diversity), 3GPP RLF (Qout -8 dB / Qin -6 dB, N310=2, T310=1 s), "
                    "HO failure on source-command loss or target SINR < Qout, 1 s re-establishment; CHO executions skip command loss",
            "radio_map": f"{RADIO_MAP} (9 nearest real Kumoh sites)",
            "cells": f"{len(SCENARIOS)} scenarios x {len(FADINGS)} fading modes",
            "eval_seeds": f"{st['seeds'][0]}-{st['seeds'][-1]} (pre-registered held-out; v3 training 0-399, sweep 500-509, "
                          "federation 620-899, tuning 1000-1099, gate 1100-1102)",
            "episodes_per_arm": n_pool, "episode_length": "300 s",
            "pairing": "all arms run on identical radio traces per (cell, seed), one sim pass per trace",
            "ci_method": "95% Student-t CI of the mean over episodes; paired-difference tests in working/evidence/finals-v3/report.md",
            "baselines": "oracle (knows the scenario x fading cell): a3_tuned, cho_tuned (sweep 500-504), cho_tuned_ext "
                         "(extended grid, sweep 500-509); deployable (one network-wide setting): a3_global, cho_global, "
                         "cho_global_ext, cho_mse (3GPP mobility-state scaling), cho_mro (MRO online offsets)",
            "objective": "utility = 60*meanSE/7.4 - 0.3*HO - 2*ping-pong - 5*(RLF+HOF), per UE-minute",
            "preregistration": "pipeline/finals_preregistration_v3.json",
            "go_no_go": head,
            "policy_arm": meta["policy_desc"],
            "commit": meta["commit"],
        },
    }
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m twin.evaluate_v3")
    ap.add_argument("--v3", default=None)
    ap.add_argument("--seed0", type=int, required=True)
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--arms", default=None, help="comma list to restrict arms")
    ap.add_argument("--extra-arm", action="append", default=[], help="name=spec")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--reuse", action="store_true")
    ap.add_argument("--final", action="store_true", help="the pre-registered held-out run: writes the verdict "
                    "and working/evidence/finals-results.json")
    ap.add_argument("--prereg", type=Path, default=None,
                    help="a later pre-registration (e.g. finals_preregistration_v3_13.json) that names its own "
                         "held_out_seeds [lo, hi] and takes its go/no-go rules from rules_from")
    a = ap.parse_args(argv)
    seeds = list(range(a.seed0, a.seed0 + a.seeds))
    held_out, results_json, final_dir = list(HELD_OUT), EVIDENCE / "finals-results.json", "finals-v3"
    prereg_path = PREREG
    if a.prereg:
        later = json.loads(a.prereg.read_text(encoding="utf-8"))
        lo, hi = later["held_out_seeds"]
        held_out = list(range(lo, hi + 1))
        prereg_path = REPO / later["rules_from"]
        tag = a.prereg.stem.replace("finals_preregistration_", "")   # e.g. v3_13
        results_json = EVIDENCE / f"finals-results-{tag.replace('_', '.')}.json"
        final_dir = f"finals-{tag.replace('_', '.')}"
    if a.final:
        if seeds != held_out:
            raise SystemExit(f"--final must be exactly the pre-registered held-out seeds {held_out[0]}..{held_out[-1]}")
    elif any(s >= 2000 for s in seeds):
        raise SystemExit("non-final runs must not touch evaluation seeds (>= 2000)")
    out = a.out or (EVIDENCE / final_dir / ("final" if a.final else f"tune-{a.v3 or 'baselines'}"))
    out.mkdir(parents=True, exist_ok=True)
    b2 = json.loads(BASELINES_JSON.read_text(encoding="utf-8"))
    b3 = json.loads(BASELINES_V3.read_text(encoding="utf-8"))
    prereg = json.loads(prereg_path.read_text(encoding="utf-8"))
    extra = [tuple(e.split("=", 1)) for e in a.extra_arm]
    table = arm_table(b2, b3, a.v3, extra)
    if a.arms:
        keep = a.arms.split(",")
        table = {k: v for k, v in table.items() if k in keep}
    jl = out / "eval.jsonl"
    if not a.reuse:
        done = set()
        if jl.exists():
            for l in jl.read_text(encoding="utf-8").splitlines():
                if l.strip():
                    r = json.loads(l)
                    done.add((r["scenario"], r["fading"], r["seed"]))
        tasks = [(s, f, sd, {arm: fn(s, f) for arm, fn in table.items()})
                 for sd in seeds for s in SCENARIOS for f in FADINGS if (s, f, sd) not in done]
        print(f"evaluate_v3: {len(table)} arms x {len(tasks)} traces -> {out}", file=sys.stderr)
        with Pool(a.workers) as pool, jl.open("a", encoding="utf-8") as fh:
            for i, (rs, dt) in enumerate(pool.imap_unordered(_task, tasks)):
                for r in rs:
                    fh.write(json.dumps(r) + "\n")
                fh.flush()
                print(f"  [{i + 1}/{len(tasks)}] {rs[0]['scenario']}/{rs[0]['fading']}/{rs[0]['seed']} {dt:.0f}s",
                      file=sys.stderr, flush=True)
    rows = [json.loads(l) for l in jl.read_text(encoding="utf-8").splitlines() if l.strip()]
    rows = [r for r in rows if r["seed"] in seeds]
    policy = "v3" if any(r["arm"] == "v3" for r in rows) else None
    st = analyse(rows, prereg if a.final else None, policy or "v3")
    specs = {}
    for r in rows:
        specs.setdefault(r["arm"], set()).add(r["spec"])
    meta = {"generated_ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "commit": git_commit(),
            "kind": "PRE-REGISTERED HELD-OUT" if a.final else "tuning / exploratory",
            "specs": {k: "; ".join(sorted(v))[:600] for k, v in specs.items()}}
    (out / "stats.json").write_text(json.dumps(st, indent=1, default=float) + "\n", encoding="utf-8")
    write_report(st, meta, out)
    if a.final:
        v = st["verdict"]
        policy_arm = "v3" if v["headline"] in ("H1", "H2") else "v1.3.1"
        if policy_arm not in st["pooled"]["utility"]:
            policy_arm = "v3"
            meta["policy_desc"] = f"v3 {a.v3} shown as policy although the verdict is {v['headline']} (v1.3.1 not in this run)"
        else:
            meta["policy_desc"] = f"{policy_arm} ({'v3 ' + a.v3 + ' passed ' + v['headline'] if policy_arm == 'v3' else 'v3 NO-GO'})"
        dashboard_json(st, meta, policy_arm, results_json)
    print((out / "report.md").read_text(encoding="utf-8")[:5000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
