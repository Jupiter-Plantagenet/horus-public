"""Explicitly synthetic contract fixtures. Never a trained/promoted candidate.

The gate rows below exercise receipt validation; no real gate experiment is
claimed. Both receipt scope and checkpoint mark these as non-actuating fixtures.
"""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import numpy as np

from selector_runtime import (ARCH, backend_hashes, canonical_hash, frame_from_observation,
                              load_backend, read_json, sha256)


def save(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False)+'\n', encoding='utf-8', newline='\n')


def make_fixture(root, version='v0.0.900', multihead=False):
    """multihead=True builds a v3.14-contract fixture (trend features, width 32, three heads,
    'penalized' HO-budget rule); still marked fixture-only and never actuating."""
    import torch
    root = Path(root).resolve()
    backend = load_backend(root)
    directory = root / 'working/evidence' / ('selector-fixture-'+version)
    if directory.exists():
        raise FileExistsError('Fixture already exists; preserve it or use another version')
    directory.mkdir(parents=True)
    weights = root / 'pipeline/checkpoints' / ('dqn-'+version+'.pt')
    if weights.exists():
        raise FileExistsError('Never overwrite a checkpoint')
    weights.parent.mkdir(parents=True, exist_ok=True)
    profiles = [dict(prep_offset_db=-3., exec_offset_db=6., hys_db=1., ttt_s=1.28, l3_k=8),
                dict(prep_offset_db=-6., exec_offset_db=0., hys_db=0., ttt_s=.16, l3_k=4)]
    if not multihead:
        state = {}
        for layer, nin, nout in [(0, 16, 64), (2, 64, 64), (4, 64, 2)]:
            state[f'{layer}.weight'] = torch.zeros((nout, nin))
            state[f'{layer}.bias'] = torch.zeros(nout)
        state['4.bias'][1] = 1.
        ck = dict(arch=ARCH, version=version, feature_names=list(backend['cho_v3'].FEATURE_NAMES),
                  x_mean=[0.]*16, x_std=[1.]*16, profiles=profiles, default=0, period_s=.2, warm_s=.2,
                  margin=0., switch_margin=0., fixture_only=True, state_dict=state)
    else:
        sel, names = backend['selector_v3'], list(backend['cho_v3'].FEATURE_NAMES_TREND)
        n, width, heads = len(names), 32, len(sel.PREDICTION_HEADS)
        state = {}
        for layer, nin, nout in [(0, n, width), (2, width, width), (4, width, 2 * heads)]:
            state[f'{layer}.weight'] = torch.zeros((nout, nin))
            state[f'{layer}.bias'] = torch.zeros(nout)
        # profile 1: utility +1 relative to the default, HO rate 1.2 vs 1.0 (inside a 0.3 budget),
        # failure rate equal; head scales [1, 1, 5] as v3.14
        state['4.bias'][:] = torch.tensor([0., 1.0, 0.5, 1.0, 1.2, 0.5])
        ck = dict(arch=ARCH, version=version, feature_names=names, x_mean=[0.]*n, x_std=[1.]*n,
                  profiles=profiles, default=0, period_s=.2, warm_s=.2, margin=0., switch_margin=0.1,
                  min_dwell_s=0., hidden=width, prediction_heads=list(sel.PREDICTION_HEADS),
                  head_scales=[1., 1., 5.], cost_rule='penalized',
                  cost_params=dict(ho_penalty=0., fail_penalty=0., ho_slack=0.3, fail_slack=None),
                  fixture_only=True, state_dict=state)
    torch.save(ck, weights)
    context = dict(format='horus.selector-context/1', mode='synthetic-fixture', dt_s=.1, l3_k=4,
                   ue_count=1, min_cells=2, max_cells=3, max_frame_age_s=.5,
                   cell_ids=['fixture-a', 'fixture-b', 'fixture-c'], ue_ids=['walker'],
                   feature_source=dict(rsrp='synthetic contract fixture', sinr='synthetic contract fixture',
                                       network='one synthetic UE'),
                   source_sha256=dict(fixture_generator=sha256(__file__)))
    save(directory/'context.json', context)
    cfg = read_json(root/'pipeline/gate_config_finals.json')
    artifact = dict(version=version, weights_ref=weights.relative_to(root).as_posix(), algo=ARCH,
                    created_ts='2026-01-01T00:00:00Z', trained_on=dict(radio_map='placeholder', twin_commit='synthetic-fixture'),
                    provenance=None, gate=dict(verdict='promote', worst_case_score=1., threshold=cfg['threshold'],
                                               scenario_suite=cfg['scenario_suite'], evaluated_ts='2026-01-01T00:00:00Z'))
    path = directory/'artifact.json'
    save(path, artifact)
    evidence = directory/'FIXTURE-ONLY.json'
    save(evidence, dict(fixture_only=True, trained=False, actual_gate_run=False,
                        purpose='Receipt, inference, refusal and transport-contract testing only'))
    gate_rows = [dict(scenario=s, fading=f, seed=seed, role=role, score=1., mean_se=cfg['se_ref'],
                      fail_rate=0., pp_rate=0., ho_rate=0.)
                 for s in cfg['scenarios'] for f in cfg['fadings'] for seed in cfg['seeds']
                 for role in ('candidate', 'reference')]
    save(weights.with_suffix('.gate.json'), dict(verdict='promote', weights_sha256=sha256(weights),
         artifact_canonical_sha256=canonical_hash(artifact), config_sha256=sha256(root/'pipeline/gate_config_finals.json'),
         fixture_only=True, rows=gate_rows))
    save(weights.with_suffix('.qualification.json'), dict(format='horus.selector-qualification/1', status='qualified',
         scope='fixture-only', weights_sha256=sha256(weights), artifact_canonical_sha256=canonical_hash(artifact),
         context_sha256=canonical_hash(context), backend_sha256=backend_hashes(root),
         evidence_ref=evidence.relative_to(root).as_posix(), evidence_sha256=sha256(evidence)))
    return dict(root=root, directory=directory, artifact=path, weights=weights, context=context, checkpoint=ck)


def observations(fixture, count=80, columns=3):
    backend = load_backend(fixture['root'])
    for i in range(count):
        values = np.array([[-70., -90., -100.] if i < 20 else [-90., -70., -100.]])[:, :columns]
        yield backend['sim'].Obs(t=(i+1)*.1, dt=.1, l1=values.copy(), l3=values.copy(),
            serving=np.array([0]), sinr_db=np.array([10.]), connected=np.array([True]), can_ho=np.array([True]),
            time_since_ho=np.array([i*.1]), active=np.ones(columns, bool),
            cell_ids=fixture['context']['cell_ids'][:columns], ue_ids=['walker'])


def frames(fixture, count=80, columns=3):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [frame_from_observation(obs, fixture['context'], i, 'supported-0',
             (start+timedelta(seconds=obs.t)).isoformat().replace('+00:00','Z'))
            for i, obs in enumerate(observations(fixture, count, columns))]
