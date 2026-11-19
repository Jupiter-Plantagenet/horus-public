"""working/evidence/finals-results-current.json: the dashboards' results document for the CURRENT
pre-registered confirmatory claim, in the unchanged horus.finals-results/1 format plus three
additive blocks the dashboards render when present:

  paired               paired held-out differences (policy - ref) with 95% CIs and each pre-registered
                       H1/H2 check, from the confirmatory run's stats.json (the claim rests on these,
                       not on overlapping per-arm CIs)
  measured_route       the pre-registered measured-campus-route transfer test of the same candidate
  confirmatory_history every pre-registered confirmatory test so far, verdicts as they came out

The historical working/evidence/finals-results.json (v3.1.1 NO-GO) is never modified.

    python -m twin.results_current            # from pipeline/
"""
import json
import sys
from pathlib import Path

from .finals_common import EVIDENCE

REFS = ("cho_global", "cho_global_ext", "cho_mse", "cho_mro", "a3_global", "a3_tuned", "cho_tuned", "cho_tuned_ext")
METRICS = ("utility", "ho_rate", "fail_rate", "pp_rate")


def triple(p):
    return [round(p["diff"], 4), round(p["ci_low"], 4), round(p["ci_high"], 4)]


def build(evidence=EVIDENCE):
    doc = json.loads((evidence / "finals-results-v3.14.json").read_text(encoding="utf-8"))
    st = json.loads((evidence / "finals-v3.14/final/stats.json").read_text(encoding="utf-8"))
    v = st["verdict"]
    checks = {ref: r for hyp in ("H1_oracle", "H2_deployable") for ref, r in v[hyp]["refs"].items()}
    doc["provenance"]["evaluated_candidate_version"] = "v3.14.24"
    doc["provenance"]["headline_meaning"] = ("H2: beats every deployable baseline (network-wide A3/CHO, 3GPP mobility-state CHO, "
                                             "MRO CHO) with no guardrail regressed; H1 (per-cell oracles) is not claimed")
    doc["paired"] = {
        "source": "working/evidence/finals-v3.14/final/stats.json",
        "episodes": len(st["seeds"]) * 12,
        "refs": {ref: dict(group="oracle" if ref in v["H1_oracle"]["refs"] else "deployable",
                           passed=checks[ref]["pass"],
                           failed_checks=[c["check"].split(":")[0] for c in checks[ref]["checks"] if not c["pass"]],
                           **{m: triple(st["comparisons"][ref][m]["pooled"]) for m in METRICS})
                 for ref in REFS},
        "H1": v["H1_oracle"]["pass"], "H2": v["H2_deployable"]["pass"], "headline": v["headline"]}
    ms = json.loads((evidence / "measured-v3.14/final/summary.json").read_text(encoding="utf-8"))["primary"]["verdict"]
    doc["measured_route"] = {
        "source": "working/evidence/measured-v3.14/final/summary.json",
        "preregistration": "pipeline/finals_preregistration_measured_v3_14.json",
        "scope": "t4 reverse lap, calibrated lap-1 RSRP surface, modelled PHY and fading layer; frozen policy, no retraining",
        "episodes": ms["episodes"], "H2": ms["pass"], "non_inferiority": ms["non_inferiority_pass"],
        "refs": {ref: dict(utility=[round(r["checks"][0]["diff"], 4)] + [round(x, 4) for x in r["checks"][0]["ci"]],
                           passed=r["pass"], non_inferior=r["non_inferiority"]["pass"],
                           failed_checks=[c["check"].split(" (")[0] for c in r["checks"] if not c["pass"]])
                 for ref, r in ms["refs"].items()}}
    doc["confirmatory_history"] = [
        dict(candidate="v3.1.1", file="working/evidence/finals-results.json", seeds="2100-2119", verdict="NO-GO",
             note="federated v3.1.1 (finals): H1 and H2 fail"),
        dict(candidate="v3.14.24", file="working/evidence/finals-results-v3.14.json", seeds="2200-2259", verdict=v["headline"],
             note="federated, operator HO budget 0.3: H2 PASS; H1 fails only vs the extended per-cell CHO oracle"),
        dict(candidate="v3.14.32", file="working/evidence/finals-results-v3.15.json", seeds="2300-2359", verdict="NO-GO",
             note="utility-only rule: ties the extended oracle (+0.003, CI includes 0), RLF guardrail in stationary/Rayleigh"),
        dict(candidate="v3.14.24", file="working/evidence/measured-v3.14/final/summary.json", seeds="measured route, 120 faded episodes",
             verdict="H2 FAIL", note="beats MRO (+0.43) and A3 (+2.69); -0.046 vs network CHO, ping-pong guardrail (Rayleigh layer)")]
    return doc


def main():
    out = EVIDENCE / "finals-results-current.json"
    doc = build()
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
