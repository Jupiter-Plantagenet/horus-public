"""v3.14 steps 2-6 (pipeline/finals_preregistration_v3_14.json), applied mechanically.

    python -m twin.run_v314 federate --fed-data D --log-data L
    python -m twin.run_v314 derive
    python -m twin.run_v314 gates
    python -m twin.run_v314 select
    python -m twin.run_v314 freeze

Every rule (configs, version numbers, seeds, eligibility, buffer, tie-breaks)
comes from the pre-registration file; nothing here takes a threshold from the
command line. The confirmatory held-out run is the plain twin.evaluate_v3
--final command the file names; `freeze` prints it when it is authorised.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

from .finals_common import EVIDENCE, REPO

PLAN = REPO / "pipeline" / "finals_preregistration_v3_14.json"
OUT = EVIDENCE / "v3.14"
CAND = REPO / "working" / "candidates"
WEIGHTS = ("clean-fedavg", "clean-median", "poisoned-fedavg", "poisoned-median")
GATES = (("1100", "gate_config_finals.json"), ("1300", "gate_config_finals_replicate_1300.json"))
BUFFER = 0.8


def sha256(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def plan():
    return json.loads(PLAN.read_text(encoding="utf-8"))


def candidates(p=None):
    """[(version, config_name, weights_index)] in pre-registered order."""
    p = p or plan()
    out = []
    for k, name in enumerate(p["candidate_family"]["decision_configs"]):
        for n in range(4):
            out.append((f"v3.14.{20 + 4 * k + n}", name, n))
    return out


def artifact_path(version, n):
    return CAND / f"v3-{WEIGHTS[n]}-{version}.json"


def seeds_of(s):
    lo, hi = map(int, s.split(".."))
    return lo, hi


def cmd_federate(a):
    from . import fed_v3
    base = ["--init-version", "v3.14.0", "--round", "14", "--version-base", "v3.14", "--version-offset", "10",
            "--fed-data", str(a.fed_data), "--val-data", str(a.log_data), "--out-dir", str(CAND)]
    (OUT / "fed").mkdir(parents=True, exist_ok=True)
    fed_v3.main(base)
    fed_v3.main(base + ["--poison"])


def cmd_derive(a):
    import torch
    from .dqn import checkpoint_path
    from .selector_v3 import check_cost_params
    p = plan()
    cfgs = p["candidate_family"]["decision_configs"]
    rows = []
    for version, name, n in candidates(p):
        src = f"v3.14.{10 + n}"
        ck = torch.load(checkpoint_path(src), map_location="cpu", weights_only=True)
        cfg = cfgs[name]
        check_cost_params(cfg["cost_rule"], cfg["cost_params"])
        ck = dict(ck)
        ck.update({"version": version, "cost_rule": cfg["cost_rule"], "switch_margin": cfg["switch_margin"],
                   "decision_config": name, "derived_from": src, "experiment_plan_sha256": sha256(PLAN)})
        if cfg["cost_params"] is None:
            ck.pop("cost_params", None)
        else:
            ck["cost_params"] = cfg["cost_params"]
        out = checkpoint_path(version)
        if out.exists():
            raise SystemExit(f"{out} exists")
        torch.save(ck, out)
        src_art = json.loads(artifact_path(src, n).read_text(encoding="utf-8"))
        art = dict(src_art, version=version, weights_ref=f"pipeline/checkpoints/dqn-{version}.pt")
        art["gate"] = {"verdict": "pending", "worst_case_score": None, "threshold": None,
                       "scenario_suite": None, "evaluated_ts": None}
        artifact_path(version, n).write_text(json.dumps(art, indent=2) + "\n", encoding="utf-8")
        rows.append({"version": version, "config": name, "weights": src, "sha256": sha256(out)})
        print(f"{version} = {src} + {name}", file=sys.stderr)
    (OUT / "derived.json").write_text(json.dumps(rows, indent=1) + "\n", encoding="utf-8")


def cmd_gates(a):
    from . import gate_v3
    (OUT / "gates").mkdir(parents=True, exist_ok=True)
    for version, name, n in candidates():
        art = artifact_path(version, n)
        for tag, cfg in GATES:
            path = art if tag == "1100" else art.with_name(art.stem + f".replicate-{tag}.json")
            if tag != "1100" and not path.exists():
                # the replicate gates a PENDING copy: never inherit the unchanged gate's verdict
                d = json.loads(art.read_text(encoding="utf-8"))
                d["gate"] = {"verdict": "pending", "worst_case_score": None, "threshold": None,
                             "scenario_suite": None, "evaluated_ts": None}
                path.write_text(json.dumps(d, indent=2) + "\n", encoding="utf-8")
            if json.loads(path.read_text(encoding="utf-8"))["gate"]["verdict"] != "pending":
                continue
            gate_v3.main(["--artifact", str(path), "--config", str(REPO / "pipeline" / cfg), "--workers", "15",
                          "--rows", str(OUT / "gates" / f"{version}.gate-{tag}.rows.jsonl"),
                          "--log", str(OUT / "gates" / "gate_log.txt")])


def gate_verdicts(version, n):
    """Both verdicts; each must come from its own gate run (its rows file exists and the
    replicate's evaluation is not the unchanged gate's)."""
    art = artifact_path(version, n)
    g = {"1100": json.loads(art.read_text(encoding="utf-8"))["gate"]}
    g["1300"] = json.loads(art.with_name(art.stem + ".replicate-1300.json").read_text(encoding="utf-8"))["gate"]
    for tag in ("1100", "1300"):
        rows = OUT / "gates" / f"{version}.gate-{tag}.rows.jsonl"
        if not (rows.exists() or rows.with_name(rows.name + ".gz").exists()) or g[tag]["verdict"] == "pending":
            raise SystemExit(f"{version}: gate {tag} has not run")
    if g["1300"]["evaluated_ts"] == g["1100"]["evaluated_ts"]:
        raise SystemExit(f"{version}: replicate verdict is a copy of the unchanged gate's")
    return g


def cmd_select(a):
    from . import evaluate_v3
    p = plan()
    lo, hi = seeds_of(p["seeds"]["selection"].split(" ")[0])
    clean = [(v, name, n) for v, name, n in candidates(p) if n in (0, 1)]
    args = ["--seed0", str(lo), "--seeds", str(hi - lo + 1), "--workers", "15", "--out", str(OUT / "selection")]
    for v, _, _ in clean:
        args += ["--extra-arm", f"{v}=dqn2:{v}"]
    evaluate_v3.main(args)


def selection_stats(version, rows, prereg):
    from .evaluate_v3 import analyse
    names = {v for v, _, n in candidates() if n in (0, 1)}
    sub = [dict(r, arm="v3") if r["arm"] == version else r for r in rows
           if r["arm"] == version or r["arm"] not in names]
    return analyse(sub, prereg, "v3")


def buffer_check(st, rule):
    """Every deployable ref x guardrail: pooled upper CI and every per-cell mean increase <= BUFFER x margin."""
    from .evaluate_v3 import DEPLOYABLE
    worst, ok = [], True
    for ref in DEPLOYABLE:
        for g in rule["guardrails"]:
            m = g["metric"]
            margin = max(g["rel_margin"] * abs(st["pooled"][m][ref][0]), g["abs_margin"])
            comp = st["comparisons"][ref][m]
            vals = [("pooled_ci_high", comp["pooled"]["ci_high"])] + [(c, v["diff"]) for c, v in comp["cells"].items()]
            for where, x in vals:
                if x > BUFFER * margin:
                    ok = False
                    worst.append({"ref": ref, "metric": m, "where": where, "increase": round(x, 4),
                                  "buffer_limit": round(BUFFER * margin, 4)})
    return ok, worst


def cmd_freeze(a):
    from .evaluate_v3 import DEPLOYABLE, ORACLES
    p = plan()
    prereg = json.loads((REPO / p["rules_from"]).read_text(encoding="utf-8"))
    rows = [json.loads(l) for l in (OUT / "selection" / "eval.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    cfgs = p["candidate_family"]["decision_configs"]
    out = {"prereg_sha256": sha256(PLAN), "buffer": BUFFER, "candidates": {}}
    from .dqn import checkpoint_path
    for version, name, n in candidates(p):
        g = gate_verdicts(version, n)
        rec = {"config": name, "weights": WEIGHTS[n], "weights_sha256": sha256(checkpoint_path(version)),
               "gate_1100": g["1100"]["verdict"], "gate_1100_worst": g["1100"]["worst_case_score"],
               "gate_1300": g["1300"]["verdict"], "gate_1300_worst": g["1300"]["worst_case_score"]}
        if n in (0, 1):
            st = selection_stats(version, rows, prereg)
            vd = st["verdict"]
            ok, worst = buffer_check(st, prereg["go_no_go"])
            rec.update({
                "pooled_utility_selection": st["pooled"]["utility"]["v3"][0],
                "utility_vs": {r: [round(st["comparisons"][r]["utility"]["pooled"][k], 4) for k in ("diff", "ci_low", "ci_high")]
                               for r in ORACLES + DEPLOYABLE},
                "H1_selection": vd["H1_oracle"]["pass"], "H2_selection": vd["H2_deployable"]["pass"],
                "failed_checks": [f"{hyp}/{ref}: {c['check']} (diff {c.get('diff', float('nan')):+.4f}"
                                  + (f", cells {c['cells_regressed']}" if c.get("cells_regressed") else "") + ")"
                                  for hyp in ("H1_oracle", "H2_deployable") for ref, r in vd[hyp]["refs"].items()
                                  for c in r["checks"] if not c["pass"]],
                "buffer_ok": ok, "buffer_violations": worst[:20]})
            rec["eligible"] = (name != "A" and rec["gate_1100"] == "promote" and rec["gate_1300"] == "promote"
                               and rec["H2_selection"] and ok)
        else:
            rec["eligible"] = False
        out["candidates"][version] = rec
    el = {v: r for v, r in out["candidates"].items() if r["eligible"]}
    slack = lambda v: cfgs[out["candidates"][v]["config"]]["cost_params"]["ho_slack"]
    frozen = max(el, key=lambda v: (slack(v), el[v]["pooled_utility_selection"], v)) if el else None
    out["frozen_candidate"] = frozen
    if frozen:
        fc = out["candidates"][frozen]
        same = [v for v, r in out["candidates"].items() if r["config"] == fc["config"]]
        clean = [v for v in same if out["candidates"][v]["weights"].startswith("clean")]
        pfa = [v for v in same if out["candidates"][v]["weights"] == "poisoned-fedavg"][0]
        out["separation_claim"] = (all(out["candidates"][v]["gate_1100"] == "promote" and out["candidates"][v]["gate_1300"] == "promote"
                                       for v in clean) and out["candidates"][pfa]["gate_1100"] == "reject")
        lo, hi = p["held_out_seeds"]
        out["held_out_run"] = "AUTHORISED"
        out["confirmatory_command"] = (f"python -m twin.evaluate_v3 --v3 {frozen} --seed0 {lo} --seeds {hi - lo + 1} "
                                       "--workers 15 --final --prereg pipeline/finals_preregistration_v3_14.json")
    else:
        out["separation_claim"] = None
        out["held_out_run"] = "WITHHELD: no eligible candidate (development NO-GO); 2200..2259 stay unused"
    (OUT / "freeze-decision.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "candidates"}, indent=1))
    for v, r in out["candidates"].items():
        print(v, r["config"], r["weights"], r["gate_1100"], r["gate_1300"],
              r.get("H1_selection"), r.get("H2_selection"), r.get("buffer_ok"), r.get("eligible"),
              round(r.get("pooled_utility_selection", float("nan")), 4))


def main(argv=None):
    from .finals_common import single_thread
    single_thread()
    ap = argparse.ArgumentParser(prog="python -m twin.run_v314")
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("federate")
    f.add_argument("--fed-data", type=Path, required=True)
    f.add_argument("--log-data", type=Path, required=True)
    for c in ("derive", "gates", "select", "freeze"):
        sub.add_parser(c)
    a = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    {"federate": cmd_federate, "derive": cmd_derive, "gates": cmd_gates, "select": cmd_select,
     "freeze": cmd_freeze}[a.cmd](a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
