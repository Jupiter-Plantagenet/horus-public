# v3.14.24 live: calibrated campus route → online selector runtime → OAI F1 handovers

Lab host: WSL Ubuntu 24.04, 16 threads, native Docker. RAN: OAI CU + two DUs + NR-UE over the RF simulator,
FlexRIC with the HORUS handover xApp (`stack/oai-ho/`). Image IDs: CU `dc53f0fd` (SRB reordering timer 1000 ms),
DU `9a0a1a25` (CFRA retry), UE `995d8773` (sync offset), FlexRIC/xApp `67dc41ae` (xApp binary `76ca14af`); the
Dockerfiles and patches that build them are in `stack/oai-ho/*/`.
Candidate `v3.14.24` (frozen, weights `b6002c7a…`), runtime qualification `../selector-integration-v3.14/`.
Every run executes from a manifest-verified source assembly (`assembly-3faca81/assembly-manifest.json`); the
runner re-hashes all 5,040 source files at the end and fails the run on any mismatch.

| run | result |
|---|---|
| `bounded-PASS-20261118T171712Z` | **PASS**: 1,817 frames, 86 online inferences, 2 control attempts / **2 ACKed + CU-confirmed handovers** / 0 failed, 0 fallback / invalid / model faults, post-handover replies 21 / 5, final ping 6/6, max input age 22.8 ms |
| `sustained-run2-20261118T192432Z` | **TWO-HOUR PASS**: 41 cycles, 74,502 frames, 3,527 online inferences, **82 control attempts / 82 ACKed + CU-confirmed handovers / 0 failed**, 0 fallback / invalid / model / runtime faults, every cycle 2/2, max input age 37.7 ms, decision→CU RRC p50 3.23 s, RIC ACK p50 0.6 ms, cleanup passed; **7,380.8 s real sustained** (UTC; an independent NTP clock agrees to 2 s) — `VERIFICATION.json` |

The runner's own soak timer uses CLOCK_MONOTONIC, which ran 3.7–5% fast against UTC on this WSL host, so the
run was given `--soak-seconds 7600` and its duration is certified on the UTC clock (`VERIFICATION.json`).
`release/run_demo.py` now ends a soak only when both clocks have reached `--soak-seconds`.

Each run folder holds the per-cycle driver and state files (`cycle-NNN/driver/{summary,actions,timed-actions,eligibility}.json*`,
`dashboard-learned-state.json`, `frames.summary.json`), the OAI protocol logs and ICMP traffic logs.
`FULL-CAPTURE.sha256` binds every file of the full 227 MB capture (frames, per-decision logs, dashboard
captures). `python verify.py` (repository root) re-aggregates the 41 cycle summaries.

Scope: calibrated-twin observations replayed at 100 ms into an independent online runtime; the selected
target events become ordinary OAI F1 handovers between two DUs over the RF simulator. This is not a field RAN
and not native RRC CHO; CHO profiles execute in the twin.
