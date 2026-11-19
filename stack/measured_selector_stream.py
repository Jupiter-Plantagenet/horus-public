"""Original calibrated TwinSim observations, optionally paced at 100 ms.

The reference selector evolves the simulated UE; an independent runtime consumes
the serialized observations. Qualification requires exact decision/profile parity.
OAI's two-DU projection does not feed back into this seven-cell simulation.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import time

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from selector_runtime import (backend_hashes, canonical_hash, frame_from_observation,
                              load_backend, read_json, sha256, validate_checkpoint)
from session_clock import SessionClock


def save(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False)+'\n', encoding='utf-8', newline='\n')


def inputs(root):
    root = Path(root).resolve()
    backend = load_backend(root)
    from twin.measured_twin import load_inputs, make_traces
    assumptions = read_json(root/'data/walktest/t4-phy-assumptions.json')
    model = root/'working/evidence/t4-replay/neighbor-assumption-model.json'
    mapping = root/'working/evidence/t4-replay/cell-mapping.json'
    rm, cells, epochs = load_inputs(root/'data/walktest/t4', model, mapping, 't4-reverse')
    traces, coverage = make_traces(rm, cells, epochs, assumptions)
    return backend, assumptions, traces, coverage


def source_hashes(root):
    root = Path(root)
    names = ['stack/measured_selector_stream.py', 'pipeline/twin/measured_twin.py',
             'stack/session_clock.py', 'stack/oai-ho/selector_driver.py',
             'pipeline/twin/measured_scenario.py', 'pipeline/twin/route_radio.py',
             'data/walktest/t4-phy-assumptions.json', 'data/walktest/t4/manifest.json',
             'data/walktest/t4/epochs.jsonl', 'working/evidence/t4-replay/cell-mapping.json',
             'working/evidence/t4-replay/neighbor-assumption-model.json']
    return {n: sha256(root/n) for n in names} | backend_hashes(root)


def context_for(root, traces):
    return dict(format='horus.selector-context/1', mode='twin-stream', dt_s=.1, l3_k=4,
                source_clock='Shared steady session UTC: one UTC anchor plus same-boot monotonic elapsed time; raw wall drift recorded',
                ue_count=1, min_cells=2, max_cells=max(len(t.cell_ids) for _, _, t in traces),
                max_frame_age_s=2., delivery_processing_margin_s=.2,
                cell_ids=sorted({c for _, _, t in traces for c in t.cell_ids}),
                ue_ids=['measured-walker'], source_sha256=source_hashes(root),
                feature_source=dict(rsrp='lap-1 calibrated mean RSRP on t4 reverse route; conditional neighbour identities',
                    sinr='TwinSim PHY with declared load, noise and interference assumptions',
                    network='single simulated walker; controller-dependent simulated connection/HO state'),
                scope='Bounded calibrated-twin to emulated OAI F1 actuation; no field-performance or native CHO qualification')


DEFAULT_VERSION = 'v3.39.0'


def checkpoint(root, backend, version=DEFAULT_VERSION):
    import torch
    torch.set_num_threads(1)
    ck = validate_checkpoint(torch.load(Path(root)/'pipeline/checkpoints'/f'dqn-{version}.pt',
                                        map_location='cpu', weights_only=True), backend)
    if ck.get('version') != version:
        raise ValueError('checkpoint_version_mismatch')
    return ck


def pace_utc(deadline, maximum_lateness, now=None, sleep=None):
    now, sleep = now or time.time, sleep or time.sleep
    delay = deadline-now()
    if delay > 0:
        sleep(delay)
    lateness = now()-deadline
    if lateness > maximum_lateness:
        raise RuntimeError(f'Producer cannot sustain declared 100 ms cadence; no frames fabricated; lateness_s={lateness:.6f}')


def delivery_budget(context):
    margin = context['delivery_processing_margin_s']
    if not isinstance(margin, (int, float)) or not np.isfinite(margin) or not 0 < margin < context['max_frame_age_s']:
        raise ValueError('Invalid delivery processing margin')
    return context['max_frame_age_s']-margin


class ReferenceStream:
    l3_k = 4

    def __init__(self, backend, ck, context, segment, callback, clock):
        self.policy = backend['selector_v3'].CHOSelectorPolicy(ck)
        self.context, self.segment, self.callback, self.clock = context, segment, callback, clock
        self.calls = 0
        predict = self.policy.predict

        def counted(x):
            self.calls += 1
            return predict(x)
        self.policy.predict = counted

    def decide_batch(self, obs):
        frame = frame_from_observation(obs, self.context, self.clock['sequence'], self.segment,
                    (self.clock['start']+timedelta(seconds=.1*self.clock['sequence'])).isoformat())
        targets, conditional = self.policy.decide_batch(obs)
        self.callback(frame, targets, conditional, self.policy)
        self.clock['sequence'] += 1
        return targets, conditional


def replay(root, callback, segment_index=None, paced=False, max_seconds=None, version=DEFAULT_VERSION):
    backend, assumptions, traces, coverage = inputs(root)
    context = context_for(root, traces)
    ck = checkpoint(root, backend, version)
    clock = dict(sequence=0, start=datetime.now(timezone.utc), mono=time.monotonic())
    results = []
    for index, (start, end, trace) in enumerate(traces):
        if segment_index is not None and index != segment_index:
            continue

        def emit(frame, targets, conditional, policy):
            if paced:
                # The source timestamp and freshness judge use CLOCK_REALTIME.
                # WSL's monotonic clock can progress at a different rate; pacing
                # against it accumulated several seconds of false source age.
                # Use the same absolute UTC schedule; no age limit is relaxed.
                deadline = clock['start'].timestamp()+frame['sequence']*.1
                pace_utc(deadline, delivery_budget(context))
            callback(frame, targets, conditional, policy)

        ctl = ReferenceStream(backend, ck, context, f'reverse-supported-{index}', emit, clock)
        env = backend['sim'].TwinSim(trace, backend['sim'].SimConfig(dt=.1), l3_k=4,
                        bandwidth_mhz=assumptions['n_prb']*12*assumptions['scs_khz']/1000)
        env.reset()
        done = False
        while not done:
            _, _, done = env.step(ctl)
            if max_seconds is not None and env.t >= max_seconds:
                break
        results.append(dict(index=index, start_s=start*.1, end_s=(end-1)*.1,
                            inference_calls=ctl.calls, metrics=env.metrics()))
    return dict(context=context, coverage=coverage, segments=results, frames=clock['sequence'])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', required=True, type=Path)
    p.add_argument('--context', required=True, type=Path)
    p.add_argument('--out', required=True, type=Path)
    p.add_argument('--segment', required=True, type=int)
    p.add_argument('--seconds', required=True, type=float)
    p.add_argument('--version', default=DEFAULT_VERSION, help='qualified selector version (checkpoint dqn-<version>.pt)')
    p.add_argument('--wait-ready', type=Path, help='Wait for initialized consumer after creating the fresh empty stream')
    a = p.parse_args()
    if a.out.exists() or not np.isfinite(a.seconds) or a.seconds <= 0:
        p.error('Choose a fresh output and positive finite duration')
    _, _, traces, _ = inputs(a.root)
    if not 0 <= a.segment < len(traces):
        p.error('Unknown supported segment')
    expected = read_json(a.context)
    if context_for(a.root, traces) != expected:
        p.error('Producer source/context differs from qualified inputs')
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with a.out.open('x', encoding='utf-8', newline='\n') as f:
        # This is replay of recorded-route model inputs, not fresh field KPM.
        # Generate the exact reference-dependent observation sequence before
        # the live clock starts. Actual inference still happens independently
        # in the consumer; no observations or missing cells are fabricated.
        buffered = []
        result = replay(a.root, lambda frame, *_: buffered.append(frame),
                        a.segment, paced=False, max_seconds=a.seconds, version=a.version)
        if a.wait_ready:
            deadline = time.monotonic()+60
            while not a.wait_ready.exists():
                if time.monotonic() >= deadline:
                    raise TimeoutError('Consumer did not become ready; no observations emitted')
                time.sleep(.05)
        clock=SessionClock(read_json(a.wait_ready)['clock']) if a.wait_ready else SessionClock()
        start = clock.now()
        for frame in buffered:
            deadline = start+timedelta(seconds=frame['sequence']*.1)
            frame['source_ts'] = deadline.isoformat()
            pace_utc(deadline.timestamp(), delivery_budget(expected),now=clock.timestamp)
            f.write(json.dumps(frame, allow_nan=False)+'\n')
            f.flush()
        result['delivery'] = 'Precomputed calibrated TwinSim observation replay; independent online consumer inference'
    save(a.out.with_suffix('.summary.json'), result)


if __name__ == '__main__':
    main()
