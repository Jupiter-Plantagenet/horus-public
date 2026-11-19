# CHO-profile selector runtime

`stack/selector_runtime.py` runs a frozen, gated, qualified selector checkpoint online. It reads a stream of
observation frames and returns one decision per frame. Any failure makes it fall back to stock A3; it never
invents an input. `stack/oai-ho/selector_driver.py` turns the selected target events into OAI handovers.
The default mode is a dry run, which makes zero RAN calls.

## Checkpoint contract

The runtime loads a checkpoint only if it matches one of two explicit contracts. `validate_checkpoint`
refuses everything else with a named reason.

| Contract | Accepted |
|---|---|
| **multihead** (v3.14, `finals_preregistration_v3_14.json`) | A feature set the backend defines (`v3`, 16 features, or `trend`, 22). Any MLP width from 16 to 1024. Exactly the backend's three prediction heads (utility, HO rate, failures) with finite positive scales. A backend cost rule (`penalized`: HO/failure penalties plus the operator HO budget relative to profile 0) whose parameters pass `selector_v3.check_cost_params`. An optional minimum dwell. |
| **plain** (v3.39.0, the finals model) | The 16 v3 features, width 64, one utility head, no cost rule. |

Ensembles, input clipping, unknown heads or rules, and any shape, normalisation, profile-table or
decision-constant mismatch are refused. Weights are decoded with `weights_only=True`.

Loading a real candidate also needs its two sibling receipts next to `pipeline/checkpoints/dqn-vX.Y.Z.pt`:

- `.gate.json` holds the gate verdict `promote`, the weights, artifact and config hashes, and every
  candidate/reference row of the unchanged gate. The runtime recomputes suite coverage, episode scores and
  guardrails, and they must agree with the artifact.
- `.qualification.json` (`horus.selector-qualification/1`, status `qualified`, scope `twin-actuation`) holds
  the same weight and artifact hashes, the exact `context_sha256`, the backend source hashes
  (`backend_hashes(root)`) and a repository-local evidence file with its hash. The runtime never creates this
  receipt for a real candidate. For v3.14.24 it was written by `release/selector_integration_v314.py`, and only
  after full frame-by-frame parity on the measured route: `working/evidence/selector-integration-v3.14/`.

Hashes of JSON values are canonical: sorted keys, compact separators, no nonfinite numbers. Bound files are
re-checked during execution; a changed or removed file revokes live eligibility.

## Observation input

`horus.selector-context/1` declares:

- the 100 ms clock and the fc4 L3 filtering;
- the UE list, the allowed cell IDs and the cell-count range;
- the maximum input age;
- the provenance of each feature;
- the producer, model and input hashes.

`horus.selector-frame/1` binds the context hash, sequence number, segment ID, UTC source time and simulation time
to every `TwinSim.Obs` field: the L1/L3 matrices, serving cells, serving SINR, eligibility, time since the last
HO, the active-cell mask, and the cell and UE IDs. Missing fields are never synthesised.

Missing, duplicate, stale, future, nonfinite, unknown-ID or malformed input produces HOLD, clears baseline timers
and latches the AI off for the rest of the segment. Later valid input runs stock A3, and a new segment resets the
history.

## Decisions and faults

With a cost rule, an infeasible profile gets the value −inf. This is the operator HO budget at work, not a
fault. NaN, +inf or a nonfinite default-profile value is a model fault and latches A3 with the reason recorded.
Reloading resets the feature, profile and baseline history, and a rejected reload uses A3.

## OAI bridge

```bash
python stack/oai-ho/selector_driver.py --root <assembly> --artifact <artifact.json> --context <context.json> \
    --frames <frames.jsonl> --out <new-capture-directory>          # dry run: no RAN access
```

Actuation additionally requires `--live --follow`, a qualified `twin-stream` context and the full candidate
bundle. Fixture inputs are refused before any CU access or Docker call.

The driver behaves as follows:

- It follows the append-only producer stream and checks freshness at read time.
- It keeps at most one RC control in flight.
- It paces controls with a minimum wall-time gap and a bounded attempt count.
- The selected profile executes in the twin.
- The resulting target maps to the other live DU through the FlexRIC E2SM-RC Style 3 / Action 1 xApp.
- It does **not** program native RRC CHO in OAI, and each record says `native_cho_configured=false`.
- A handover counts as completed only on an ACK plus an independently confirmed CU serving-DU change.

## Live acceptance

```bash
python release/make_assembly.py --out /var/tmp/horus-assembly
cd /var/tmp/horus-assembly/assembly
python release/run_demo.py --root "$PWD" --out /var/tmp/horus-run --live --soak-seconds 7200 \
    --qualification selector-integration-v3.14 \
    --cu-image horus/oai-gnb:srb-reorder-diagnostic --cu-srb-reordering-ms 1000 \
    --du-image horus/oai-gnb:cfra-retry-v2-diagnostic --ue-image horus/oai-nr-ue:sync-offset-diagnostic \
    --flexric-image horus/oai-flexric:reply-order-diagnostic
```

The four images are built from `stack/oai-ho/{cu-srb-reordering,du-cfra-retry,ue-sync-offset,xapp-reply-order}/`.

Each cycle replays reverse-route segment 0 (the producer is `stack/measured_selector_stream.py`) and must end with
two ACKed, CU-confirmed handovers. At the end the runner re-hashes every source file against the assembly
manifest. The soak ends only when both the monotonic and the UTC clock reach `--soak-seconds`.

The producer reads the walk trace (`data/walktest/t4/`), which the public release does not include. The recorded
runs are in `working/evidence/live-v3.14/`.
