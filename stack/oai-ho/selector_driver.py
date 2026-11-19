#!/usr/bin/env python3
"""Explicit selector-to-OAI bridge. Default is a dry run with zero RAN calls.

The twin executes ProfileCHO; the live testbed receives ordinary F1 handover
commands to its other DU. This does not configure native CHO in the live RAN.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import importlib.util
import json
import math
from pathlib import Path
import sys
import time
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from selector_runtime import SelectorRuntime, read_json
from selector_telemetry import SessionTelemetry
from session_clock import SessionClock


def append(path, record):
    with Path(path).open('a', encoding='utf-8', newline='\n') as f:
        f.write(json.dumps(record, allow_nan=False) + '\n')


class ControlDispatcher:
    """One outstanding RC call; observation processing continues at 100 ms."""
    def __init__(self, perform, out, track, min_gap_s=40, max_hos=3, live=False, learned_only=False):
        self.perform, self.out, self.track = perform, Path(out), track
        self.min_gap_s, self.max_hos, self.live = min_gap_s, max_hos, live
        self.learned_only = learned_only
        self.pool = ThreadPoolExecutor(max_workers=1) if live else None
        self.pending = None
        self.last_send = -float('inf')
        self.attempted = self.completed = self.failed = self.would_request = 0

    def poll(self):
        if self.pending is not None and self.pending.done():
            try:
                record = self.pending.result()
                ok = record.get('result') == 'ok'
                self.completed += int(ok)
                self.failed += int(not ok)
            except Exception:
                self.failed += 1
            self.pending = None

    def submit(self, decision):
        self.poll()
        if self.failed:
            return 'refused-control-path-fault'
        if decision.get('effective_controller') == 'hold' or self.track not in decision.get('ue_ids', []):
            return 'hold'
        i = decision['ue_ids'].index(self.track)
        target = decision['targets'][i]
        if target is None or target == decision['from_cells'][i]:
            return 'stay'
        if self.learned_only and (decision.get('effective_controller') != 'selector' or
                                  decision.get('selector_stage') != 'learned_profiles'):
            return 'waiting-for-learned-profile-event'
        if not self.live:
            self.would_request += 1
            return 'dry-run-only'
        # Defence in depth: even a caller that requested --live cannot send
        # fixture/unqualified/held-input decisions to the shared RC executor.
        if decision.get('fixture_only') or not decision.get('control_eligible'):
            return 'refused-unqualified-control'
        if self.pending is not None or self.attempted >= self.max_hos:
            return 'control-in-flight-or-budget'
        if time.monotonic() - self.last_send < self.min_gap_s:
            return 'minimum-wall-gap'
        version = decision['candidate_version'] if decision['effective_controller'] == 'selector' else 'a3'
        request = dict(decided_mono=time.monotonic(), twin_ue=self.track,
                       step=round(decision['t_s']/.1), controller=decision['effective_controller'],
                       serving_rsrp=decision['rsrp_serving'][i], target_rsrp=decision['rsrp_target'][i],
                       selector_metadata=dict(candidate_version=decision['candidate_version'],
                         effective_controller=decision['effective_controller'], context_sha256=decision['context_sha256'],
                         source_ts=decision['source_ts'], input_age_s=decision['input_age_s'],
                         selected_profile=decision['selected_profiles'][i] if decision['selected_profiles'] else None,
                         selector_stage=decision.get('selector_stage'), native_cho_configured=False,
                         conditional_in_twin=decision['conditional_in_twin'][i],
                         mapping='Twin target maps to OTHER emulated live DU; profile parameters are applied only in twin'),
                       **{'from': decision['from_cells'][i], 'to': target})
        self.pending = self.pool.submit(self.perform, version, request)
        self.attempted += 1
        self.last_send = time.monotonic()
        return 'control-submitted'

    def close(self):
        if self.pool:
            self.pool.shutdown(wait=True)
            self.poll()

    def summary(self):
        return dict(control_attempts=self.attempted, confirmed_handovers=self.completed,
                    failed_controls=self.failed, dry_run_target_proposals=self.would_request)


def run(args):
    if args.live and (args.fixture or not args.follow):
        raise ValueError('Live execution requires --follow and never accepts --fixture')
    root = args.root.resolve()
    context = read_json(args.context)
    runtime = SelectorRuntime(root, context, allow_fixtures=args.fixture)
    if args.track not in context['ue_ids']:
        raise ValueError('Tracked UE is not part of the qualified context')
    status = runtime.load(args.artifact)
    clock=SessionClock()
    if args.out.exists():
        raise FileExistsError('Choose a new output directory; captures are preserved')
    args.out.mkdir(parents=True)
    (args.out/'eligibility.json').write_text(json.dumps(status, indent=2)+'\n', encoding='utf-8', newline='\n')
    telemetry = SessionTelemetry(args.dashboard_archive, context, read_json(args.artifact),now=clock.iso()) if getattr(args, 'dashboard_archive', None) else None
    if telemetry:
        telemetry.manifest['clock']=clock.record
        telemetry.heartbeat(dict(status,clock_diagnostics=clock.diagnostics()), 'starting',now=clock.iso())
    perform = None
    if args.live:
        if not status['live_eligible']:
            if telemetry:
                telemetry.close(status, 'refused',now=clock.iso())
            print(json.dumps(dict(status='refused-before-RAN-access', **status)))
            return 2
        spec = importlib.util.spec_from_file_location('oai_control', HERE/'ho_driver.py')
        legacy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(legacy)
        du, _ = legacy.serving_du()
        if du is None:
            raise RuntimeError('No confirmed OAI serving DU')
        control_args = SimpleNamespace(verify_s=args.verify_s, ue_label=args.ue_label,
                                      scenario='qualified-twin-stream', radio_map=context['feature_source']['rsrp'],
                                      out=args.out/'actions.jsonl')
        def perform(version, decision):
            result = legacy.execute_handover(version, decision, control_args)
            result=dict(result,ts=datetime.fromtimestamp(clock.at_monotonic(decision['decided_mono']),timezone.utc).isoformat(),
                raw_wall_ts=result['ts'],decision_mono_s=decision['decided_mono'],
                confirmation_mono_s=decision['decided_mono']+result['latency_ms']/1000 if result.get('latency_ms') is not None else None)
            append(args.out/'timed-actions.jsonl',result)
            if telemetry:
                telemetry.action(result)
            return result
    dispatcher = ControlDispatcher(perform, args.out, args.track, args.min_gap_s, args.max_hos, args.live,
                                   args.learned_only)
    if args.ready_file:
        if args.ready_file.exists():
            raise FileExistsError('Readiness receipt must be fresh')
        temporary=args.ready_file.with_suffix(args.ready_file.suffix+'.tmp')
        with temporary.open('x', encoding='utf-8') as ready:
            ready.write(json.dumps(dict(ready=True, status=status,clock=clock.record))+'\n')
        temporary.replace(args.ready_file)
    started, frames, heartbeat_at = time.monotonic(), 0, 0.
    completed_normally = False
    try:
        with args.frames.open(encoding='utf-8') as source:
            while time.monotonic()-started < args.timeout_s:
                line = source.readline()
                dispatcher.poll()
                if dispatcher.failed:
                    break  # retain the failed attempt; never send another RC command
                if telemetry and time.monotonic() - heartbeat_at >= 1.:
                    telemetry.heartbeat(dict(runtime.status(),clock_diagnostics=clock.diagnostics()),now=clock.iso())
                    heartbeat_at = time.monotonic()
                if args.live and dispatcher.attempted >= args.max_hos and dispatcher.pending is None:
                    break
                if not line:
                    if not args.follow:
                        break
                    time.sleep(.01)
                    continue
                # A live append may expose an unfinished final line. Wait for
                # its remainder rather than interpreting a partial JSON frame.
                while args.follow and not line.endswith('\n') and time.monotonic()-started < args.timeout_s:
                    tail = source.readline()
                    if tail:
                        line += tail
                    else:
                        time.sleep(.01)
                try:
                    frame = json.loads(line)
                except ValueError:
                    frame = {}
                fixture_now = None
                if args.fixture and context['mode'] == 'synthetic-fixture':
                    try:
                        fixture_now = datetime.fromisoformat(frame['source_ts'].replace('Z', '+00:00'))
                    except (KeyError, TypeError, ValueError):
                        pass
                decision = runtime.step(frame, now=fixture_now or clock.now())
                frames += 1
                decision['dispatch'] = dispatcher.submit(decision)
                append(args.out/'decisions.jsonl', decision)
                if telemetry:
                    telemetry.decision(decision,now=clock.iso())
                if args.live and dispatcher.completed >= args.max_hos:
                    break
        completed_normally = dispatcher.failed == 0
    finally:
        dispatcher.close()
        if telemetry:
            status=dict(runtime.status(),clock_diagnostics=clock.diagnostics())
            if dispatcher.failed:
                status.update(live_eligible=False,reason='control_path_failure',control_path_fault='unconfirmed_handover')
            telemetry.close(status, 'stopped' if completed_normally and not dispatcher.failed else 'failed',now=clock.iso())
    summary = dict(mode='live-twin-to-OAI' if args.live else 'dry-run-no-RAN-access', frames=frames,
                   runtime=runtime.status(), **dispatcher.summary(), native_cho_configured=False,
                   session_state='failed' if dispatcher.failed or not completed_normally else 'stopped',
                   control_path_fault='unconfirmed_handover' if dispatcher.failed else None)
    (args.out/'summary.json').write_text(json.dumps(summary, indent=2)+'\n', encoding='utf-8', newline='\n')
    print(json.dumps(summary))
    if args.live:
        return 0 if dispatcher.completed >= args.max_hos and dispatcher.failed == 0 else 1
    return 0 if frames and runtime.stats['invalid_frames'] == 0 else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=HERE.parents[1])
    parser.add_argument('--artifact', type=Path, required=True)
    parser.add_argument('--context', type=Path, required=True)
    parser.add_argument('--frames', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--dashboard-archive', type=Path, help='Fresh dashboard capture directory; original source timestamps and scope are preserved')
    parser.add_argument('--fixture', action='store_true', help='Enable fixture-only inference; never real control')
    parser.add_argument('--live', action='store_true', help='Explicit qualified twin-stream to OAI RC bridge')
    parser.add_argument('--follow', action='store_true')
    parser.add_argument('--learned-only', action='store_true', help='Dispatch only natural events after actual model inference')
    parser.add_argument('--ready-file', type=Path, help='Create a fresh readiness receipt after model and RAN initialization')
    parser.add_argument('--track', default='walker')
    parser.add_argument('--ue-label', default='ue-0')
    parser.add_argument('--min-gap-s', type=float, default=40)
    parser.add_argument('--max-hos', type=int, default=3)
    parser.add_argument('--verify-s', type=float, default=40)
    parser.add_argument('--timeout-s', type=float, default=120)
    args = parser.parse_args()
    if (not all(math.isfinite(x) for x in (args.min_gap_s,args.verify_s,args.timeout_s)) or
            args.min_gap_s < 0 or args.max_hos < 1 or args.verify_s <= 0 or args.timeout_s <= 0):
        parser.error('Invalid control limit')
    try:
        return run(args)
    except (OSError, ValueError, ImportError, RuntimeError, KeyError, TypeError, AttributeError) as exc:
        print(json.dumps(dict(status='refused', reason=str(exc))), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
