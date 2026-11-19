"""Safety gate v3 (finals suite `finals-v3`): the gate for twin-v2 policies.

Same contract as gate.py (v1/v2 suites, kept for the v1.x verdicts): the
suite, thresholds and reference baseline are PRE-REGISTERED in
pipeline/gate_config_finals.json, committed before any v2 candidate exists;
the verdict is written into the artifact's frozen-schema gate block and one
line is appended to working/evidence/gate_log-finals.txt in the format the
dashboard parses.

A candidate is PROMOTED only if all three hold over every (scenario x fading)
cell of the suite (4 scenarios incl. the never-trained cell_outage x 3
fading modes x 3 seeds):

1. worst-case composite >= threshold, where per episode
       score = 0.4 * (1 - min(1, failures per UE-min))
             + 0.3 * (1 - min(1, ping-pongs per UE-min))
             + 0.3 * min(1, mean SE / SE_REF)
   Rates, not ratios: the v2-suite "HO success" term is undefined/noisy for
   a policy that (correctly) barely hands over — one failure out of three
   attempts swung it by 0.13 — while failures per UE-minute is what an
   SLA actually bounds. Delivered SE replaces RSRP "coverage";
2. HO-rate guardrail: per cell, mean HO rate <= ho_rel * reference + ho_abs;
3. failure guardrail: per cell, mean (RLF + HOF) rate <= fail_rel * reference + fail_abs.

The reference is the per-cell best-tuned A3 (frozen in the config) on the
same traces. Threshold = ~90% of that reference's own worst-case composite
on this suite (calibrated on baselines only, before any v2 candidate).
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .gate import CHECKPOINTS, PIPELINE, _validate_artifact

CONFIG = PIPELINE / "gate_config_finals.json"


def episode_score_v3(m, se_ref):
    return (0.4 * (1.0 - min(1.0, m["fail_rate"])) + 0.3 * (1.0 - min(1.0, m["pp_rate"]))
            + 0.3 * min(1.0, m["mean_se"] / se_ref))


def _suite_task(args):
    from .controllers_v2 import parse_controller
    from .finals_common import single_thread, trace_for
    from .sim import SimConfig, run_on_trace
    single_thread()
    scenario, fading, seed, pairs, se_ref = args
    tr = trace_for(scenario, fading, seed)
    out = []
    # candidate and reference share one sim pass (composite.run_arms: rows are
    # independent, identical to separate runs — tests/test_v3.py); a speed-up
    # only, no change to what is measured or how it is judged
    from .composite import run_arms
    ms = run_arms(tr, [parse_controller(spec) for _, spec in pairs], SimConfig())
    for (role, spec), m in zip(pairs, ms):
        out.append({"role": role, "scenario": scenario, "fading": fading, "seed": seed,
                    "score": round(episode_score_v3(m, se_ref), 4), **m})
    return out


def run_suite(controller_spec, cfg, workers=1):
    """Deterministic regardless of `workers` (each episode is a pure function
    of its (scenario, fading, seed) trace); rows are returned in suite order."""
    tasks = [(s, f, sd, (("candidate", controller_spec),
                         ("reference", cfg["reference_specs"][s][f])), cfg["se_ref"])
             for s in cfg["scenarios"] for f in cfg["fadings"] for sd in cfg["seeds"]]
    if workers > 1:
        from multiprocessing import Pool
        with Pool(workers) as p:
            res = p.map(_suite_task, tasks)
    else:
        res = [_suite_task(t) for t in tasks]
    return [r for rs in res for r in rs]


def judge(rows, cfg):
    cand = [r for r in rows if r["role"] == "candidate"]
    worst = min(cand, key=lambda r: r["score"])
    fails = []
    if worst["score"] < cfg["threshold"]:
        fails.append(f"composite {worst['score']:.4f} < {cfg['threshold']} "
                     f"({worst['scenario']}/{worst['fading']} seed {worst['seed']})")
    for s in cfg["scenarios"]:
        for f in cfg["fadings"]:
            c = [r for r in cand if r["scenario"] == s and r["fading"] == f]
            ref = [r for r in rows if r["role"] == "reference" and r["scenario"] == s and r["fading"] == f]
            for key, rel, ab, what in (("ho_rate", cfg["ho_rel"], cfg["ho_abs"], "HO rate"),
                                       ("fail_rate", cfg["fail_rel"], cfg["fail_abs"], "RLF+HOF rate")):
                cm, rm = np.mean([r[key] for r in c]), np.mean([r[key] for r in ref])
                if cm > rel * rm + ab:
                    fails.append(f"{what} {cm:.3f} > {rel}x{rm:.3f}+{ab} ({s}/{f})")
    return worst, fails


def gate_v3(artifact_path, cfg=None, workers=1):
    cfg = cfg or json.loads(CONFIG.read_text(encoding="utf-8"))
    art = json.loads(Path(artifact_path).read_text(encoding="utf-8"))
    ckpt = _validate_artifact(art, artifact_path)
    from .dqn_profile import load_any_v2
    ctl = load_any_v2(ckpt.stem[len("dqn-"):], root=ckpt.parent)
    if f"dqn-{ctl.version}.pt" != ckpt.name or ctl.version != art["version"]:
        raise SystemExit(f"checkpoint {ckpt.name} embeds version {ctl.version!r}, artifact says "
                         f"{art['version']!r} — refusing")
    rows = run_suite(f"dqn2:{ctl.version}", cfg, workers)
    worst, fails = judge(rows, cfg)
    verdict = "reject" if fails else "promote"
    art["gate"] = {"verdict": verdict, "worst_case_score": worst["score"],
                   "threshold": cfg["threshold"], "scenario_suite": cfg["scenario_suite"],
                   "evaluated_ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    tmp = Path(str(artifact_path) + ".tmp")
    tmp.write_text(json.dumps(art, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, artifact_path)
    return art, worst, fails, rows


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m twin.gate_v3")
    ap.add_argument("--artifact", required=True, type=Path)
    ap.add_argument("--log", type=Path,
                    default=PIPELINE.parent / "working" / "evidence" / "gate_log-finals.txt")
    ap.add_argument("--rows", type=Path, default=None, help="optional JSONL dump of suite episodes")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--config", type=Path, default=CONFIG,
                    help="gate config (default: the frozen gate_config_finals.json)")
    a = ap.parse_args(argv)
    cfg = json.loads(a.config.read_text(encoding="utf-8"))
    art, worst, fails, rows = gate_v3(a.artifact, cfg=cfg, workers=a.workers)
    g = art["gate"]
    why = "; ".join(fails) if fails else "all guardrails held"
    line = (f"{g['evaluated_ts']} GATE {g['verdict'].upper():7s} {art['version']:8s} "
            f"worst={g['worst_case_score']:.4f} (threshold {g['threshold']}, worst case: "
            f"{worst['scenario']}/{worst['fading']} seed {worst['seed']}; {why}) "
            f"suite={g['scenario_suite']} aggregation="
            f"{art['provenance']['aggregation'] if art.get('provenance') else 'single'} "
            f"artifact={a.artifact.name}")
    print(line)
    a.log.parent.mkdir(parents=True, exist_ok=True)
    with a.log.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    if a.rows:
        with a.rows.open("w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
