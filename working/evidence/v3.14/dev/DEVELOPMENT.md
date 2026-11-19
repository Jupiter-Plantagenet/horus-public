# v3.14 development record (exploratory; development seeds only)

Everything here ran on **development seeds 1400..1439** (evaluation) and on training-data seeds
34000..34159, 35000..35279 and 36000..36599. No selection (1500..1539), gate-replicate (1300..1302) or held-out
(2200..2259) seed was touched. Each `rulesN/` holds the raw rows (`eval.jsonl.gz`, every pre-registered arm,
20 seeds × 12 cells = 240 paired episodes) and `variants-summary.json` (each variant scored with the unchanged
H1/H2 rules of `finals_preregistration_v3.json`); `variants-N.json` defines the variants; `tr*.log` and
`fed*.log` are the training and federation logs. The harness is `dev_variants.py`, `train_dev.py`,
`percell.py`, `profile_use.py` and `openloop_cell.py`.

Numbers below are utility differences per UE-minute, pooled over the 240 episodes, with the lower 95% CI bound
where it matters. "ext" = `cho_tuned_ext` (per-cell oracle over the extended grid, the same action space as
HORUS); "global" = `cho_global` (network-wide tuned CHO = profile 0).

| step | runs | finding |
|---|---|---|
| 1. Decision rules on v3.13.10 weights | rules1, rules2 | A per-UE **HO budget** relative to profile 0 (ho_slack 0.2–0.5) makes **H2 pass** every time (+0.12–0.13 over global; every guardrail holds). Utility-only + hysteresis 0.1 reaches ext +0.000 but fails the H2 HO guardrail vs global in 7 cells. HO penalties without a hard budget cause RLF and fail. |
| 2. Why H1 and H2 pull apart | rules2 per cell | The per-cell oracles themselves use +0.4–0.5 HO/UE-min more than global in every mobile cell: above the 0.285 H2 margin. |
| 3. Capacity | tr930–933, rules3 | Offline validation gain 0.141 (width 64) → 0.150 (256) → 0.155 (512); closed loop ext −0.018 → −0.007 / −0.009. |
| 4. More data, federation | tr932, fed931, rules4 | 4.5× data: ext +0.002 (central). Federation of width 256 on the v3.13 clients: small gain; median ≈ FedAvg. |
| 5. Ensembles | rules5 | 2–4 member ensembles: ext +0.000…+0.004. Not used. |
| 6. **Trend features** | tr980, rules6 | 6 short-term trend features (fast-EMA neighbour-gap and serving-level change over 2 s / 5 s, SINR change over 2 s, cell changes in 10 s). Training loss 0.802 → 0.762; offline gain 35.7% → 38.6% of the per-window oracle. **HO budget 0.5 is now almost free: H2 PASS with ext −0.001** (before: −0.015). |
| 7. Decision timing | rules7, rules8 | Period 1 s / 5 s, hysteresis 0.2, small HO penalty, minimum dwell 10–30 s: all within ±0.005 or worse. Not used. |
| 8. Where the oracle still wins | percell, profile_use, openloop_cell | corner_turner (−0.02…−0.06) and stationary/Rayleigh. Open-loop label utility shows it is **model error**, not counterfactual mismatch: in corner/Rician the model's choices score +0.169 vs +0.206 for the oracle's fixed profile p4; the policy cannot tell corner-turning from rush-hour walkers. |
| 9. Ranking loss, 6960 episodes | tr982, tr983 | ListNet term (weight 1, τ 0.1): offline gain collapses to 0.035 (shift-invariant softmax dominated the regression). 6960 episodes at 1 row per UE-snapshot: 0.177 (no gain). Not used. |
| 10. Federation with trend features, **fresh development seeds 1420..1439** | fed980, rules9 | FedAvg / median of the trend model on the new trend client data. Budget 0.5 **fails** H2 (corner_turner/Rayleigh HO +0.31 > 0.285); 0.4 passes (worst corner cell +0.26); 0.3 passes (+0.21). FedAvg, budget 0.4: global +0.156, MRO +0.193, cho_tuned +0.022 [+0.012], ext −0.004. |

Consequences for `pipeline/finals_preregistration_v3_14.json`: trend features, width 256, 40 epochs, Huber loss,
3 rows per UE-snapshot, switch_margin 0.1; budgets {0.4, 0.3, 0.2} chosen mechanically on the selection seeds
with a 20% guardrail safety buffer; utility-only (A) reported, never eligible; held-out set enlarged to 60
seeds per cell.

Operational lesson: with numpy/torch imported before `single_thread()` sets the thread variables, eval workers
spin-waited (load 60, 70% system time). All v3.14 steps export `OMP/OPENBLAS/MKL_NUM_THREADS=1` before Python
starts; the v3.1.1 regression is identical with and without it (`../REGRESSION-v3.1.1.json`).
