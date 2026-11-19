"""Package and qualify the frozen v3.14.24 selector for the calibrated-twin -> emulated OAI F1 path.

The same checks as release/selector_integration.py (v3.39.0), bound to v3.14 evidence instead of
the laptop-only transfer bundle:

  * weights   = pipeline/checkpoints/dqn-v3.14.24.pt, sha256 equal to working/evidence/v3.14/FREEZE.md
  * artifact  = working/candidates/v3-clean-fedavg-v3.14.24.json (gate PROMOTE); only trained_on
                fields the approved schema does not know move to a provenance sidecar
  * gate      = the PRE-REGISTERED unchanged-gate rows (working/evidence/v3.14/gates/v3.14.24.gate-1100.rows.jsonl.gz),
                re-judged on this backend; a fresh recheck on this backend is recorded beside them
  * prior run = the frozen measured-route 'off' episode of v3.14.24 (working/evidence/measured-v3.14/final/primary.rows.jsonl.gz)

Qualification concerns faithful runtime inputs and execution. It is not AI superiority, field
deployment, native RRC CHO or a final GO. Nothing is overwritten; the output directory must be new.

    python release/selector_integration_v314.py --root .
"""
import argparse
import copy
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

VERSION = 'v3.14.24'
COUNTERS = ('ho_attempts', 'ho_success', 'hof_cmd', 'hof_target', 'rlf', 'too_late', 'too_early',
            'wrong_cell', 'rlf_coverage', 'ping_pongs', 'short_stays', 'ho_stationary')


def run(root, out_name='selector-integration-v3.14', recheck_gate=True):
    root = Path(root).resolve()
    sys.path.insert(0, str(root/'stack'))
    from selector_runtime import (SelectorRuntime, backend_hashes, canonical_hash, load_backend, read_json, sha256)
    from measured_selector_stream import context_for, inputs, replay, save, source_hashes, checkpoint
    import numpy as np
    directory = root/'working/evidence'/out_name
    directory.mkdir(parents=True, exist_ok=False)
    weights = root/f'pipeline/checkpoints/dqn-{VERSION}.pt'
    freeze = (root/'working/evidence/v3.14/FREEZE.md').read_text(encoding='utf-8')
    frozen_sha = re.search(r'Weights sha256: `([0-9a-f]{64})`', freeze).group(1)
    if sha256(weights) != frozen_sha or f'**{VERSION}**' not in freeze:
        raise ValueError('Weights are not the frozen v3.14 confirmatory candidate')
    backend = load_backend(root)
    ck = checkpoint(root, backend, VERSION)        # the runtime's multihead contract

    original_path = root/f'working/candidates/v3-clean-fedavg-{VERSION}.json'
    original = read_json(original_path)
    if original['gate']['verdict'] != 'promote' or original['weights_ref'] != f'pipeline/checkpoints/dqn-{VERSION}.pt':
        raise ValueError('Candidate artifact is not the promoted v3.14.24')
    artifact = copy.deepcopy(original)
    allowed = set(read_json(root/'schemas/policy_artifact.schema.json')['properties']['trained_on']['properties'])
    extra = {k: artifact['trained_on'].pop(k) for k in list(artifact['trained_on']) if k not in allowed}
    if not set(extra) <= {'radio_model', 'fading', 'obs_filter'}:
        raise ValueError('Unexpected artifact adaptation: ' + ','.join(sorted(extra)))
    from policy_store import _validate_schema
    if _validate_schema(artifact, root/'schemas/policy_artifact.schema.json'):
        raise ValueError('Adapted artifact invalid')
    save(directory/'artifact-original.json', original)
    save(directory/'artifact.json', artifact)
    freeze_decision = read_json(root/'working/evidence/v3.14/freeze-decision.json')
    save(directory/'provenance.json', dict(format='horus.selector-provenance/1',
         original_artifact_sha256=sha256(original_path), original_artifact=original,
         artifact_canonical_sha256=canonical_hash(artifact), weights_sha256=sha256(weights),
         moved_training_metadata=extra,
         transformation='Only unsupported trained_on fields moved to this sidecar; weights and training identity unchanged',
         preregistration='pipeline/finals_preregistration_v3_14.json',
         freeze_ref='working/evidence/v3.14/FREEZE.md', freeze_sha256=sha256(root/'working/evidence/v3.14/FREEZE.md'),
         final_evaluation_verdict='H2 (finals-results-v3.14.json, held-out 2200..2259)',
         separation_claim=freeze_decision['separation_claim'], federated=True))

    # Gate: the pre-registered unchanged-gate rows, judged again on this backend.
    cfg_path = root/'pipeline/gate_config_finals.json'
    cfg = read_json(cfg_path)
    rows_path = root/f'working/evidence/v3.14/gates/{VERSION}.gate-1100.rows.jsonl.gz'
    rows = [json.loads(l) for l in gzip.open(rows_path, 'rt', encoding='utf-8') if l.strip()]
    worst, failures = backend['gate_v3'].judge(rows, cfg)
    if failures or worst['score'] != artifact['gate']['worst_case_score']:
        raise ValueError('Research gate no longer agrees')
    for r in rows:
        if r['score'] != round(backend['gate_v3'].episode_score_v3(r, cfg['se_ref']), 4):
            raise ValueError('Gate row score not reproducible from its own fields')
    gate_receipt = dict(verdict='promote', weights_sha256=sha256(weights),
                        artifact_canonical_sha256=canonical_hash(artifact), config_sha256=sha256(cfg_path),
                        fixture_only=False, rows=rows, source_rows_sha256=sha256(rows_path),
                        provenance_ref=(directory/'provenance.json').relative_to(root).as_posix())
    if recheck_gate:
        gate_receipt['recheck'] = gate_recheck(root, directory, rows)
    save(weights.with_suffix('.gate.json'), gate_receipt)

    _, assumptions, traces, coverage = inputs(root)
    context = context_for(root, traces)
    save(directory/'context.json', context)
    prior_path = root/'working/evidence/measured-v3.14/final/primary.rows.jsonl.gz'
    prior = next(json.loads(l) for l in gzip.open(prior_path, 'rt', encoding='utf-8')
                 if json.loads(l)['arm'] == 'v3' and json.loads(l)['fading'] == 'off')
    save(directory/'plan-frozen.json', dict(created=datetime.now(timezone.utc).isoformat(),
         purpose='Engineering input/decision fidelity and bounded emulated actuation qualification only',
         candidate=VERSION,
         criteria=['Every supported reverse-route observation survives exact JSON round trip.',
                   'All targets, conditional flags and selected profiles match an independent selector.',
                   'Route totals match the frozen measured-route v3.14.24 off-episode (pre-registered run).',
                   'Actual runtime subsequently reproduces every frame with zero fallback, invalid input or model fault.',
                   'Live test uses the first chronological learned-stage natural handover; no forced target, tuning or held-out use.'],
         source_sha256=source_hashes(root), prior_run_sha256=sha256(prior_path),
         weights_sha256=sha256(weights), context_sha256=canonical_hash(context)))

    boundary = SelectorRuntime(root, context)
    independent, last_segment, frames, events = None, None, 0, []

    def check(frame, targets, conditional, policy):
        nonlocal independent, last_segment, frames
        wire = json.loads(json.dumps(frame, allow_nan=False))
        obs, _ = boundary._observation(wire, datetime.fromisoformat(frame['source_ts']))
        if frame['segment'] != last_segment:
            independent = backend['selector_v3'].CHOSelectorPolicy(copy.deepcopy(ck))
            last_segment = frame['segment']
        rt, rc = independent.decide_batch(obs)
        if (not np.array_equal(rt, targets) or not np.array_equal(rc, conditional) or
                not np.array_equal(independent.engine.current, policy.engine.current)):
            raise ValueError('Serialization changed selector decisions')
        for name in ('l1', 'l3', 'sinr_db', 'serving', 'connected', 'can_ho', 'time_since_ho', 'active'):
            if not np.array_equal(np.asarray(wire[name]), getattr(obs, name)):
                raise ValueError('Observation round trip differs')
        frames += 1
        if (targets >= 0).any():
            events.append(dict(segment=frame['segment'], t_s=frame['t_s'],
                               learned=frame['t_s']-policy._t0+1e-9 >= policy.warm_s, targets=targets.tolist(),
                               profiles=policy.engine.current.tolist()))
    result = replay(root, check, version=VERSION)

    # route totals vs the frozen pre-registered measured-route episode
    totals = {k: sum(s['metrics'][k] for s in result['segments']) for k in COUNTERS}
    duration = sum(s['metrics']['duration_s'] for s in result['segments'])
    se = sum(s['metrics']['mean_se'] * s['metrics']['duration_s'] for s in result['segments']) / duration
    comparison = {k: [totals[k], prior[k]] for k in COUNTERS}
    comparison['duration_s'] = [round(duration, 6), round(prior['duration_s'], 6)]
    comparison['mean_se'] = [round(se, 4), prior['mean_se']]
    diffs = {k: v for k, v in comparison.items() if v[0] != v[1]}
    if any(k not in ('ping_pongs', 'short_stays') for k in diffs):
        raise ValueError(f'Frozen measured-route run differs: {diffs}')
    evidence = directory/'input-fidelity.json'
    learned = [e for e in events if e['learned']]
    save(evidence, dict(passed=True, scope='Engineering fidelity for calibrated-twin to emulated OAI F1 only',
         candidate=VERSION, frames=frames, roundtrip_decision_mismatches=0, segments=result['segments'],
         coverage=coverage, natural_events=events, learned_event=learned[0] if learned else None,
         prior_run_comparison=comparison, prior_run_differences=diffs,
         prior_run_note=('Only ping-pong/short-stay accounting may differ: the frozen run predates the PR #49 '
                         'float-boundary fix that this release carries.'),
         source_sha256=source_hashes(root), weights_sha256=sha256(weights),
         artifact_canonical_sha256=canonical_hash(artifact), context_sha256=canonical_hash(context),
         provenance_sha256=sha256(directory/'provenance.json'),
         limits=['RSRP surface calibrated (lap 1); SINR, load, HO state and utility simulated.',
                 'Single UE and supported segments only; resets retained.',
                 'Does not establish general superiority, field safety, native CHO or a final GO.']))
    save(weights.with_suffix('.qualification.json'), dict(format='horus.selector-qualification/1',
         status='qualified', scope='twin-actuation', weights_sha256=sha256(weights),
         artifact_canonical_sha256=canonical_hash(artifact), context_sha256=canonical_hash(context),
         backend_sha256=backend_hashes(root), evidence_ref=evidence.relative_to(root).as_posix(),
         evidence_sha256=sha256(evidence)))

    runtime = SelectorRuntime(root, context)
    status = runtime.load(directory/'artifact.json')
    if not status['live_eligible']:
        raise ValueError('Actual candidate refused: ' + status['reason'])

    def runtime_check(frame, targets, conditional, policy):
        decision = runtime.step(json.loads(json.dumps(frame)), now=datetime.fromisoformat(frame['source_ts']))
        want = [None if v < 0 else frame['cell_ids'][v] for v in targets]
        if (decision['effective_controller'] != 'selector' or decision['targets'] != want or
                decision['conditional_in_twin'] != conditional.tolist() or
                [p['index'] for p in decision['selected_profiles']] != policy.engine.current.tolist()):
            raise ValueError('Actual runtime diverged from frozen selector')
    replay(root, runtime_check, version=VERSION)
    final = runtime.status()
    if final['invalid_frames'] or final['fallback_frames'] or final['model_faults']:
        raise ValueError('Runtime parity failed')
    save(directory/'runtime-parity.json', dict(passed=True, frames=frames, status=final,
         observation_clock='Offline exact-timestamp check; no live freshness claim', ran_calls=0))
    from policy_store import admit
    ok, version, reason = admit(directory/'artifact.json', root/'working/selector-session-store')
    if not ok:
        raise ValueError('Isolated metadata admission failed: ' + reason)
    summary = dict(passed=True, version=version, frames=frames, inference_calls=final['inference_calls'],
                   learned_event=learned[0] if learned else None, learned_events=len(learned),
                   prior_run_differences=diffs, qualified_scope='calibrated-twin to emulated OAI F1 only', ran_calls=0)
    print(json.dumps(summary))
    return summary


def gate_recheck(root, directory, rows):
    """Run the unchanged gate on this backend; record how its rows compare with the pre-registered ones."""
    art = json.loads((root/f'working/candidates/v3-clean-fedavg-{VERSION}.json').read_text())
    art['gate'] = dict(verdict='pending', worst_case_score=None, threshold=None, scenario_suite=None, evaluated_ts=None)
    tmp = directory/'gate-recheck-artifact.json'
    tmp.write_text(json.dumps(art, indent=2) + '\n', encoding='utf-8')
    out_rows = directory/'gate-recheck.rows.jsonl'
    subprocess.run([sys.executable, '-m', 'twin.gate_v3', '--artifact', str(tmp), '--rows', str(out_rows),
                    '--log', str(directory/'gate-recheck-log.txt'), '--workers', '15'],
                   cwd=root/'pipeline', check=True, stdout=subprocess.DEVNULL)
    new = [json.loads(l) for l in out_rows.read_text().splitlines() if l.strip()]
    key = lambda r: (r['role'], r['scenario'], r['fading'], r['seed'])
    old = {key(r): r for r in rows}
    diff = sorted({f for r in new for f in r if r[f] != old[key(r)].get(f)})
    verdict = json.loads(tmp.read_text())['gate']
    return dict(verdict=verdict['verdict'], worst_case_score=verdict['worst_case_score'],
                rows_sha256=hashlib.sha256(out_rows.read_bytes()).hexdigest(), fields_differing=diff,
                note='Recheck on this release backend (with the PR #49 accounting fix); the receipt keeps the pre-registered rows.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--out-name', default='selector-integration-v3.14')
    a = parser.parse_args()
    run(a.root, a.out_name)
