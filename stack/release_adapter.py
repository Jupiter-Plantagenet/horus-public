"""Project OAI evidence into the frozen dashboard contract without changing sources.

OAI's latency_ms measures decision -> CU confirmation. The dashboard contract
defines decision -> ACK, which this producer does not measure. Leave it null;
retain both measured intervals with their actual meaning under params.
"""
import argparse
import json
from pathlib import Path


def project_action(record):
    if not isinstance(record, dict) or record.get('action') != 'handover':
        raise ValueError('Expected an OAI handover action')
    params = record.get('params')
    if not isinstance(params, dict):
        raise ValueError('Missing control evidence')
    before, after = params.get('source_du'), params.get('target_du')
    confirmed = (record.get('result') == 'ok' and params.get('ric_control_result') == 'acked'
                 and before is not None and after is not None and before != after
                 and params.get('rrc_handover_complete') is not False)
    # A failure before transmission is an attempt, not a sent control. Keep the
    # complete input separately; only confirmed executions enter actions.jsonl.
    if not confirmed:
        return None
    output = {key: record.get(key) for key in ('ts','ue','policy_version','action','target','result','trigger')}
    output['params'] = dict(params, decision_to_cu_confirmed_ms=record.get('latency_ms'),
                            dashboard_latency_note='decision-to-ACK unavailable; latency_ms intentionally null',
                            completion_basis='ACK, DU transition and new CU RRC completion' if params.get('rrc_handover_complete') is True
                                else 'Historical ACK and CU DU transition; RRC completion not independently checked')
    output['latency_ms'] = None
    return output


def export(source, destination):
    source, destination = Path(source), Path(destination)
    if destination.exists():
        raise FileExistsError('Choose a new evidence directory; existing captures are never overwritten')
    records = [json.loads(line) for line in source.read_text(encoding='utf-8').splitlines() if line.strip()]
    actions = [action for r in records if (action := project_action(r)) is not None]
    destination.mkdir(parents=True)
    (destination/'actuation').mkdir()
    (destination/'evidence').mkdir()
    (destination/'actuation/actions.jsonl').write_text(''.join(json.dumps(a)+'\n' for a in actions), encoding='utf-8')
    (destination/'evidence/control-attempts.jsonl').write_bytes(source.read_bytes())
    report = dict(format='horus.runtime-provenance/1', source=str(source),
                  attempts=len(records), confirmed_controls=len(actions), omitted_attempts=len(records)-len(actions),
                  rf='OAI rfsim protocol execution; no campus RF measurements',
                  decision_input='Legacy twin RSRP; campus decisions mapped onto two emulated live DUs',
                  timings=dict(latency_ms='null: decision-to-ACK not measured',
                               ric_control_ack_ms='RIC control exchange interval reported by xApp',
                               decision_to_cu_confirmed_ms='Policy decision through independent CU confirmation'),
                  throughput_effect='Not established by a handover alone; do not manufacture an effect')
    (destination/'provenance.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--actions', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(export(args.actions,args.out), indent=2))


if __name__ == '__main__':
    main()
