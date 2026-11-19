# HORUS v3.14 / v3.15 — pre-registered held-out results (2026-11-18)

Twin v2 (Kumoh OpenCelliD map, 12 cells = 4 scenarios × 3 fading modes), every arm on identical radio traces,
paired 95% t-CIs pooled over 720 held-out episodes (60 seeds per cell), Holm over 12 cells for guardrails.
Rules: `pipeline/finals_preregistration_v3.json` (unchanged since 2026-10-30), applied mechanically by
`twin.evaluate_v3`. Utility = 60·SE/7.4 − 0.3·HO − 2·PP − 5·(RLF+HOF) per UE-minute.

## Confirmatory claim (v3.14): **H2 PASS — federated HORUS beats every deployable baseline, no guardrail regressed**

Candidate `v3.14.24`: federated (FedAvg, 3 non-IID campus clients, FedProx) per-UE CHO-profile selector with an
operator **handover budget** (a UE may only use a profile whose predicted HO rate is ≤ the network default's
+ 0.3/min). Frozen before the run (`v3.14/FREEZE.md`, weights sha256 `b6002c7a…`); one run on seeds 2200..2259.

| HORUS v3.14.24 minus | utility [95% CI] | HO rate | failures | verdict |
|---|---|---|---|---|
| Network-wide tuned CHO (`cho_global`; = `cho_global_ext`, = 3GPP mobility-state CHO `cho_mse`) | **+0.147 [+0.137, +0.157]** | −0.141 | +0.002 | PASS |
| MRO-adaptive CHO (`cho_mro`) | **+0.158 [+0.138, +0.179]** | −0.535 | −0.001 | PASS |
| Network-wide tuned A3 (`a3_global`) | **+1.433 [+1.158, +1.709]** | −2.156 | −0.152 | PASS |
| *Oracle:* per-cell best-tuned A3 (`a3_tuned`) | +0.226 [+0.197, +0.255] | −0.925 | −0.033 | pass |
| *Oracle:* per-cell best-tuned CHO (`cho_tuned`) | +0.009 [+0.003, +0.016] | −0.351 | +0.002 | pass |
| *Oracle:* per-cell best CHO, extended grid (`cho_tuned_ext`) | −0.016 [−0.020, −0.011] | −0.203 | +0.001 | **fail** (H1 not claimed) |

- Fewer handovers than every baseline, 0 regressed guardrail cells for H2; H2 utility CIs stay above 0 at
  97.5% (Bonferroni over the two confirmatory files: `finals-v3.14/bonferroni-97.5.json`).
- **Safety gate and poisoning** (both gates, seeds 1100..1102 unchanged and replicate 1300..1302): every clean
  federated candidate PROMOTED (0.80 / 0.82); the poisoned-FedAvg candidate REJECTED by both (0.50 / 0.51; HO
  rate 8.4/min); coordinate-median aggregation absorbs the poisoned client (PROMOTED). Separation claim: true.
- Known limit (within the pre-registered margin): stationary_clusters/Rayleigh RLF +0.014/UE-min vs `cho_tuned`
  (margin 0.02).

## Second confirmatory test (v3.15): NO-GO, reported as observed

Candidate `v3.14.32` = the same federated weights with the **utility-only** rule (config A; pre-specified in v3.14
as "reported, never eligible"; it passed H1 on selection seeds 1500..1539: +0.0135 [+0.0091, +0.0178] vs
`cho_tuned_ext`). Registered in `finals_preregistration_v3_15.json` before either held-out run; one run on
2300..2359.

| v3.14.32 minus | utility [95% CI] | failing checks |
|---|---|---|
| `cho_tuned_ext` | +0.003 [−0.001, +0.008] | utility CI includes 0 |
| `cho_tuned` | +0.027 [+0.021, +0.033] | failure / RLF guardrail: stationary_clusters/Rayleigh +0.024/UE-min > 0.02 |
| `a3_tuned` | +0.266 [+0.234, +0.297] | — |
| deployables | +0.165 (CHO) / +0.175 (MRO) / +1.596 (A3) | HO-rate guardrail (by design: no budget), stationary/Rayleigh RLF |

The utility-only rule ties the extended per-cell oracle on held-out data but does not beat it with confidence, and
it regresses RLF in stationary/Rayleigh. No oracle claim is made.

## Audit trail

`finals_preregistration_v3_14.json` (7d27305, 2026-11-18T12:38:50Z) → steps 1–6 (`v3.14/`, deviation D1 in
`v3.14/DEVIATIONS.md`: replicate gate initially skipped by an orchestrator bug, fixed and run before any freeze)
→ `v3.14/FREEZE.md` (2c6e1cc) → `finals_preregistration_v3_15.json` (d1bd28d, 13:13:58Z) → held-out v3.14
(13:18:08Z) → held-out v3.15. Development (seeds 1400..1439 only): `v3.14/dev/DEVELOPMENT.md`. Code regression:
v3.1.1 gate 72/72 rows identical (`v3.14/REGRESSION-v3.1.1.json`). Raw rows: `finals-v3.14/final/eval.jsonl.gz`,
`finals-v3.15/final/eval.jsonl.gz`; dashboards `finals-results-v3.14.json`, `finals-results-v3.15.json`.
