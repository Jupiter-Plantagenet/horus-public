"""Dashboard projection of a selector session; no RAN or policy writes."""
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import uuid


def utc():
    return datetime.now(timezone.utc).isoformat()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n', encoding='utf-8', newline='\n')
    temporary.replace(path)


def append(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(value, allow_nan=False) + '\n')


class SessionTelemetry:
    def __init__(self, out, context, artifact, session_id=None, now=None):
        self.out = Path(out)
        self.out.mkdir(parents=True, exist_ok=False)
        self.session_id = session_id or str(uuid.uuid4())
        self.context = copy.deepcopy(context)
        fixture = context.get('mode') == 'synthetic-fixture'
        self.scope = context.get('scope') or ('synthetic non-actuating fixture' if fixture else 'explicit twin context; no field qualification')
        self.started = now or utc()
        self.manifest = dict(schema='horus.replay-bundle/1', sample=fixture,
            label='SAMPLE · synthetic non-actuating fixture' if fixture else 'RECORDED · calibrated twin replay / emulated OAI F1',
            start_ts=self.started, end_ts=self.started, session_id=self.session_id,
            recorded_from='selector_driver / SessionTelemetry',
            provenance=dict(input='synthetic complete-observation fixture' if fixture else 'calibrated TwinSim observation replay; independent online inference',
                rsrp=context['feature_source']['rsrp'], sinr=context['feature_source']['sinr'],
                network=context['feature_source']['network'], control='none; non-actuating fixture' if fixture else 'emulated OAI ordinary F1 handover; not native CHO',
                scope=self.scope, final_performance_verdict=None), files={})
        save(self.out/'provenance.json', self.manifest['provenance'])
        save(self.out/'context.json', context)
        if artifact is not None:
            save(self.out/'candidates'/f'{artifact["version"]}.json', artifact)
        save(self.out/'manifest.json', self.manifest)

    def heartbeat(self, status, state='running', now=None):
        stamp = now or utc()
        row = dict(status, schema='horus.runtime-eligibility/1', ts=stamp,
            session_id=self.session_id, session_state=state,
            input_qualified=status.get('input_qualified', False), input_scope=self.scope)
        append(self.out/'evidence/runtime-eligibility.jsonl', row)
        self.manifest['end_ts'] = stamp
        save(self.out/'manifest.json', self.manifest)

    def decision(self, raw, now=None):
        if raw.get('effective_controller') != 'hold' and not raw.get('source_ts'):
            raise ValueError('A controlling decision requires its original source timestamp')
        row = copy.deepcopy(raw)
        row.update(session_id=self.session_id, observed_ts=now or utc())
        row['ts'] = raw.get('source_ts') or row['observed_ts']
        row['context_hash'] = raw.get('context_sha256')
        for i, ue in enumerate(raw.get('ue_ids') or [None]):
            single = dict(row, ue=ue)
            profiles = raw.get('selected_profiles') or []
            single['selector_profile'] = profiles[i]['parameters'] if i < len(profiles) else None
            append(self.out/'actuation/decisions.jsonl', single)

    def action(self, record):
        from release_adapter import project_action
        append(self.out/'evidence/control-attempts.jsonl', dict(record, session_id=self.session_id))
        projected = project_action(record)
        if projected is not None:
            append(self.out/'actuation/actions.jsonl', dict(projected, session_id=self.session_id))

    def close(self, status, state='stopped', now=None):
        self.heartbeat(status, state, now)
        self.manifest['files'] = {p.relative_to(self.out).as_posix():
            dict(bytes=p.stat().st_size, sha256=hashlib.sha256(p.read_bytes()).hexdigest())
            for p in self.out.rglob('*') if p.is_file() and p.name != 'manifest.json'}
        save(self.out/'manifest.json', self.manifest)
