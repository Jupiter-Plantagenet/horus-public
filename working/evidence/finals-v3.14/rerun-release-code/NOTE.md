# Held-out rerun on the release code (2026-11-19)

The command recorded in `../../v3.14/FREEZE.md` was run again from the curated public tree (built from
`live/v3.14` 87685d2; its commit was e228d84) with `--out` set to this folder:

    cd pipeline && python -m twin.evaluate_v3 --v3 v3.14.24 --seed0 2200 --seeds 60 --workers 15 --final \
        --prereg finals_preregistration_v3_14.json --out <this folder>

Comparison with the confirmatory run (`../final/`, produced on 2026-11-18 by the code of that day):

- 7,120 of 7,200 rows are identical.
- The other 80 differ only in `short_stays` (71 rows) and `ping_pongs` (9 rows, all baseline arms). The cause is the
  ping-pong float-boundary fix merged afterwards (`stay < pingpong_s - 1e-9`, baseline-harness PR #49). The 9
  ping-pong rows change their `utility`.
- Pooled utility differences change only against MRO CHO (+0.158388 → +0.158360) and network-wide A3 (+1.43343 →
  +1.43317). Every other reference is identical.
- Every verdict is identical: H2 PASS (all five deployable references), and H1 fails only against `cho_tuned_ext`.

`python verify.py` (repository root) checks these statements against both row files.
