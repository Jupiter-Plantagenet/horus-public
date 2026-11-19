# v3.14 execution log of deviations from the intended mechanics

## D1 (2026-11-18, during step 4): replicate gate skipped by an orchestrator bug, fixed and re-run

- **What happened.** `twin.run_v314 gates` (commit 7d27305) created each replicate artifact
  (`*.replicate-1300.json`) by copying the candidate artifact *after* the unchanged gate (1100..1102) had
  written its verdict into it. Its own guard ("gate only pending artifacts") then skipped every replicate run.
  The 16 replicate files therefore held byte copies of the unchanged-gate verdicts (identical
  `evaluated_ts`), and no `*.gate-1300.rows.jsonl` exists. The replicate gate on seeds 1300..1302 never ran.
- **When found.** Reading `gates/gate_log.txt` after step 4: 16 lines instead of 32. At that moment the
  unchanged-gate verdicts were known (clean PROMOTE, poisoned-FedAvg REJECT, poisoned-median PROMOTE);
  no replicate verdict and no selection result existed. Step 5 (selection eval) was running; the runner was
  stopped before step 6 (freeze) so no freeze decision could read the copied verdicts.
- **Fix.** Replicate artifacts are now created with `gate` reset to pending; `gate_verdicts` refuses a
  verdict without its own rows file or a replicate verdict whose `evaluated_ts` equals the unchanged gate's.
  The 16 copied replicate files were deleted and the replicate gate run on all 16 candidates as the
  pre-registration requires. No rule, threshold, seed, candidate or config changed.
