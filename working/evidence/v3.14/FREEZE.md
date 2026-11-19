# v3.14 FREEZE (recorded before the held-out run)

- Pre-registration: `pipeline/finals_preregistration_v3_14.json`, sha256 `4cff86b07946b9b9f0bcb5bb2e58ede2149a9e40fa732ed3e0da3693c80e90ab` (commit 7d27305; deviation D1 in DEVIATIONS.md).
- Frozen confirmatory candidate: **v3.14.24** = config B03 (per-UE HO budget 0.3/UE-min vs profile 0, switch_margin 0.1) on weights clean-fedavg (`v3.14.10`).
- Weights sha256: `b6002c7aabadec8b5135c7494b83834207d0882eb5a1116cdf734a490f1dfa28`.
- Gates: unchanged (1100..1102) PROMOTE 0.7998; replicate (1300..1302) PROMOTE 0.8154.
- Why this one (mechanical, step 6): B04 candidates fail the 20% guardrail buffer (corner_turner/off HO +0.245 vs cho_global, limit 0.218); B03 and B02 are eligible; the largest eligible ho_slack is 0.3; between B03 FedAvg (12.1053) and B03 median (12.1017) the higher pooled selection utility wins.
- Separation claim (frozen config): clean FedAvg and median PROMOTED by both gates, poisoned FedAvg REJECTED by the unchanged gate -> **True**.
- Confirmatory command (exactly one run): `python -m twin.evaluate_v3 --v3 v3.14.24 --seed0 2200 --seeds 60 --workers 15 --final --prereg pipeline/finals_preregistration_v3_14.json`
