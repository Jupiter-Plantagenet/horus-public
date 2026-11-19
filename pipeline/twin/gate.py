"""Safety gate v1 (#10): no candidate reaches the live stack without passing
a worst-case check against the pre-registered SLA threshold.

The gate is deterministic in (artifact, scenario suite, threshold) — same
inputs, same verdict, rerunnable — given the same torch/BLAS build (float
reductions can differ across builds; a verdict within ~1e-6 of the
threshold is a coin you shouldn't be flipping anyway). Its side effects are
exactly two, both intended: the verdict written into the artifact and one
append to the evidence log. The threshold and suite are pre-registered in
pipeline/gate_config.json — committed before candidates existed — so a
verdict cannot be bargained with after seeing a score.

Scoring: for every (scenario, seed) in the suite, run the candidate in the
twin and compute a composite in [0, 1]:

    score = 0.4 * HO_success_rate
          + 0.3 * (1 - ping_pong_ratio)        # churn, the A3 pathology
          + 0.3 * coverage_norm                # mean serving RSRP, normalized

worst_case_score = MIN over the whole suite — a candidate is judged on its
single worst episode, not its average (an SLA is a floor, not a vibe). The
suite includes `cell_outage`: the strongest site is removed at eval time
(map surgery), the coverage-hole case a policy trained on a healthy map has
never seen.

Verdict (promote iff worst_case_score >= threshold) is written INTO the
artifact's frozen-schema gate block, in place. The promoted-policy store
(#11) refuses anything that isn't a promote — this gate is the only thing
that can produce one.

Run inside the ML venv:
    ~/horus-ml/bin/python -m twin.gate --artifact ../working/candidates/clean-median-r1.json
"""

import argparse
import dataclasses
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from .dqn import DQNController
from .env import TwinEnv
from .radio import normalize_rsrp

PIPELINE = Path(__file__).resolve().parent.parent
CONFIG = PIPELINE / "gate_config.json"
CHECKPOINTS = PIPELINE / "checkpoints"
SCHEMA = PIPELINE.parent / "schemas" / "policy_artifact.schema.json"


def episode_score(m):
    """Composite in [0,1]. Zero-attempt episodes get a COVERAGE-CONDITIONED
    success term: staying put is judged by the quality of what you stayed on.
    (Suite v1 used a flat neutral 0.5 here; it punished *correct* restraint —
    a good policy's justified inaction in stationary_clusters scored 0.7456
    and lost to the 0.75 threshold. v2 re-registered 2026-07-18 with this fix;
    an always-stay policy still can't coast: with mediocre coverage the term
    is mediocre, and a stranded-UE episode scores far below threshold.)"""
    cov = normalize_rsrp(m["mean_rsrp_dbm"])
    success = m["ho_success_rate"] if m["handovers_attempted"] else cov
    pp_ratio = min(m["ping_pongs"] / max(m["handovers_attempted"], 1), 1.0)
    return (0.4 * success
            + 0.3 * (1.0 - pp_ratio)
            + 0.3 * cov)


def run_scenario(controller, scenario, seed, radio_map):
    # "cell_outage@<campus>" = the same surgery on that campus's commute flow
    outage = scenario == "cell_outage" or scenario.startswith("cell_outage@")
    base = scenario
    if outage:
        base = "rush_hour" if "@" not in scenario else "commute@" + scenario.split("@", 1)[1]
    env = TwinEnv(scenario=base, radio_map=radio_map, seed=seed)
    env.reset()
    if outage:
        # Coverage-hole surgery: SILENCE the busiest site (don't remove it —
        # the controller's feature vector is sized to the trained cell list,
        # so the map must keep every cell). Victim = the cell serving the
        # most UEs at reset, picked programmatically so this survives #6's
        # real geometry. tx -> -inf clamps its RSRP to NOISE_FLOOR everywhere.
        serving_counts = {}
        for ue in env.ues:
            serving_counts[ue.serving] = serving_counts.get(ue.serving, 0) + 1
        if not serving_counts:
            raise RuntimeError("cell_outage: no UEs attached — nothing to silence")
        victim = max(serving_counts, key=serving_counts.get)
        env.radio.cells = [dataclasses.replace(c, tx_power_dbm=-1e9)
                           if c.cell_id == victim else c for c in env.radio.cells]
        for ue in env.ues:   # victims re-attach to the strongest survivor
            if ue.serving == victim:
                rsrp = {c: v for c, v in env.radio.measure(ue.x, ue.y, env.step_i).items()
                        if c != victim}
                ue.serving = max(rsrp, key=rsrp.get)
    if hasattr(controller, "reset"):
        controller.reset()
    done = False
    while not done:
        _, done = env.step(controller)
    return env.metrics.as_dict()


def _validate_artifact(art, artifact_path):
    try:
        import jsonschema
    except ImportError as e:
        raise SystemExit("gate requires jsonschema in the ML venv: "
                         "~/horus-ml/bin/pip install jsonschema") from e
    jsonschema.validate(art, json.loads(SCHEMA.read_text(encoding="utf-8")))
    if art["gate"]["verdict"] != "pending":
        raise SystemExit(f"{artifact_path}: gate.verdict is "
                         f"{art['gate']['verdict']!r}, not 'pending' — refusing to re-gate "
                         "a decided artifact (delete/reset the gate block deliberately if "
                         "you really mean to)")
    ckpt = (PIPELINE.parent / art["weights_ref"]).resolve()
    if not ckpt.is_relative_to(CHECKPOINTS.resolve()):
        raise SystemExit(f"{artifact_path}: weights_ref escapes pipeline/checkpoints/ "
                         f"({art['weights_ref']!r}) — refusing")
    return ckpt


def gate(artifact_path, cfg=None, radio_map_for=None, guard=None):
    """cfg: a pre-registered suite dict (default: gate_config.json).
    radio_map_for(scenario) -> twin radio-map name, for suites that span
    several maps (the any-campus suite runs each campus's scenarios on that
    campus's map); default = the artifact's trained_on.radio_map.
    guard(results) -> (ok, reason): an extra pre-registered veto (e.g. the
    campus suite's churn guard); it can only turn promote into reject."""
    cfg = cfg if cfg is not None else json.loads(CONFIG.read_text(encoding="utf-8"))
    art = json.loads(Path(artifact_path).read_text(encoding="utf-8"))
    ckpt = _validate_artifact(art, artifact_path)
    controller = DQNController(ckpt)
    if f"dqn-{controller.version}.pt" != ckpt.name:
        raise SystemExit(f"checkpoint {ckpt.name} embeds version "
                         f"{controller.version!r} — mismatch; refusing")
    radio_map = art["trained_on"]["radio_map"]

    results, worst = [], None
    for scenario in cfg["scenarios"]:
        for seed in cfg["seeds"]:
            m = run_scenario(controller, scenario, seed,
                             radio_map_for(scenario) if radio_map_for else radio_map)
            s = episode_score(m)   # raw score decides; rounding is display-only
            results.append({"scenario": scenario, "seed": seed, "score": round(s, 4), **m})
            if worst is None or s < worst["raw"]:
                worst = {"scenario": scenario, "seed": seed, "raw": s, "score": round(s, 4)}

    verdict = "promote" if worst["raw"] >= cfg["threshold"] else "reject"
    if guard is not None:
        ok, reason = guard(results)
        worst["guard"] = reason
        if not ok:
            verdict = "reject"
    art["gate"] = {
        "verdict": verdict,
        "worst_case_score": worst["score"],
        "threshold": cfg["threshold"],
        "scenario_suite": cfg["scenario_suite"],
        "evaluated_ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    tmp = Path(str(artifact_path) + ".tmp")
    tmp.write_text(json.dumps(art, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, artifact_path)
    return art, worst, results


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m twin.gate")
    ap.add_argument("--artifact", required=True, type=Path)
    ap.add_argument("--log", type=Path,
                    default=PIPELINE.parent / "working" / "evidence" / "gate_log.txt")
    args = ap.parse_args(argv)

    art, worst, results = gate(args.artifact)
    g = art["gate"]
    line = (f"{g['evaluated_ts']} GATE {g['verdict'].upper():7s} {art['version']:8s} "
            f"worst={g['worst_case_score']:.4f} (threshold {g['threshold']}, "
            f"worst case: {worst['scenario']} seed {worst['seed']}) "
            f"suite={g['scenario_suite']} aggregation={art['provenance']['aggregation'] if art.get('provenance') else 'single'} "
            f"artifact={Path(args.artifact).name}")
    print(line)
    for r in results:
        print(f"    {r['scenario']:<20} seed {r['seed']}  score {r['score']:.4f}  "
              f"pp={r['ping_pongs']:<3d} ho_ok={r['handovers_ok']}/{r['handovers_attempted']}  "
              f"rsrp={r['mean_rsrp_dbm']}")
    args.log.parent.mkdir(parents=True, exist_ok=True)
    with args.log.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
