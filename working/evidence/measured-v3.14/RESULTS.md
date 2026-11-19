# Real-data check: the frozen v3.14.24 on the measured Kumoh campus route

Pre-registered in `pipeline/finals_preregistration_measured_v3_14.json` (commit b31f947, 2026-11-18T14:03:42Z)
before any run on the evaluation lap; one run of all blocks (`final/`). Candidate `v3.14.24` exactly as frozen
(trained only on the synthetic twin; no retraining, tuning or rule change).

Route: the t4 G-NetTrack Pro walk (LG U+, LTE band 1, one handset, Oct 2026). Lap 1 built the calibrated mean
RSRP surface; lap 2 (reverse direction) is the evaluation route. 93% of lap 2 is represented by stable
multi-cell segments. Fading, load, interference, SINR, handover execution and throughput are modelled (declared
assumptions), not measured.

## Primary block (lap 2, neighbour-assumption surface, declared PHY, 60 Rician + 60 Rayleigh fading seeds)

| v3.14.24 minus | utility [95% CI] | HO rate | ping-pong rate | H2 (superiority) | non-inferiority (1%) |
|---|---|---|---|---|---|
| Network-wide tuned CHO (= ext-grid CHO = 3GPP mobility-state CHO) | −0.046 [−0.070, −0.021] | −0.157 | +0.012 (Rayleigh mode > 0.02 margin) | FAIL | FAIL (ping-pong guardrail; utility within −1%) |
| MRO-adaptive CHO | **+0.428 [+0.314, +0.542]** | −1.374 | −0.124 | PASS | PASS |
| Network-wide tuned A3 | **+2.688 [+2.241, +3.135]** | — | — | PASS | PASS |

Pre-registered verdicts: **H2 FAIL, non-inferiority FAIL** (both because of network-wide CHO).
Deterministic mean surface (no fading, one episode): v3.14.24 12.563 vs network-wide CHO 12.354 (+0.21), no
ping-pongs in either, slightly more handovers (0.48 vs 0.42 per minute).

## Sensitivity blocks (reported only, 20 + 20 seeds each)

| block | vs network-wide CHO | vs MRO CHO | vs A3 network-wide |
|---|---|---|---|
| serving-only surface | +0.021 [−0.051, +0.093]; ping-pong guardrail fails | +0.780 | +4.951 |
| load 0.25 | −0.043 [−0.088, +0.003] | +0.360 | +1.822 |
| load 0.75 | −0.064 [−0.112, −0.015] (all guardrails hold) | +0.392 | +3.694 |
| external interference −120 dBm/RE | −0.053 [−0.104, −0.001] | +0.391 | +2.499 |
| external interference −100 dBm/RE | −0.057 [−0.104, −0.010] | +0.391 | +2.981 |

## Reading

On real measured campus radio the twin-trained policy, unchanged, beats MRO-adaptive CHO and network-wide A3 by
wide margins in every block, and is within 0.5% of the network-wide tuned CHO with fewer handovers, but does not
beat it, and under the declared Rayleigh fading layer it produces slightly more ping-pongs than the guardrail
allows. The twin-scale advantage over network-wide CHO (+0.147 on twin held-out data) does not carry over to this
single-walker route. Development (lap 1, `dev/`) predicted the same.

Limits: one handset, one operator, one route; the surface is interpolated from lap 1 and partly relies on assumed
neighbour identities; RRC connected/idle state of the walk is not established (raw logs unavailable); single UE.
