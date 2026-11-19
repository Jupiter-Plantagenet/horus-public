"""Measured RSRP -> finals TwinSim execution, with explicit assumed PHY.

Full execution is conditional on stable map-supported cell sets. Unknown
support is censored, never replaced by weak signal or counted as a real RLF.
This module adds no training, gate tuning, or automatic policy promotion.
"""
import json
import math
from dataclasses import replace
from pathlib import Path

import numpy as np

from .controllers_v2 import A3Batch,CHOBatch,STOCK_A3,LEGACY_PARAMS_A3
from .measured_scenario import (hash_file,predict_matrix,position_trace,fixture_preflight,cell_name)
from .route_radio import RouteRadioMap
from .sim import RadioTrace,SimConfig,TwinSim,summarize,utility_per_ue_min
from .walktest_ingest import source_digest


def load_inputs(dataset,model,mapping,session):
    dataset,model,mapping=map(Path,(dataset,model,mapping))
    manifest=json.loads((dataset/'manifest.json').read_text(encoding='utf-8'))
    if hash_file(dataset/'epochs.jsonl')!=manifest['output_sha256']['epochs.jsonl']:
        raise ValueError('Dataset hash mismatch')
    rm=RouteRadioMap.load(model)
    if rm.model['metadata']['dataset_manifest_sha256']!=hash_file(dataset/'manifest.json'):
        raise ValueError('Model dataset provenance mismatch')
    mapping_doc=json.loads(mapping.read_text(encoding='utf-8'))
    keys=[tuple(c['key']) for c in mapping_doc['cells']]
    ids=[c['id'] for c in mapping_doc['cells']]
    if len(set(ids))!=len(ids) or any(c['index']!=i or c['id']!=cell_name(c['key']) for i,c in enumerate(mapping_doc['cells'])):
        raise ValueError('Invalid measured-cell mapping')
    if set(rm.points)-set(keys):raise ValueError('Model contains cells outside the declared mapping')
    epochs=[json.loads(line) for line in (dataset/'epochs.jsonl').read_text(encoding='utf-8').splitlines()]
    training_keys={tuple(e['cell'])+(e['earfcn'],) for e in epochs if e['split']=='development'}
    if (mapping_doc.get('format')!='horus-measured-cell-mapping-v1' or mapping_doc.get('source_split')!='development only'
            or set(keys)!=training_keys):
        raise ValueError('Mapping must match development-split serving identities')
    group=[e for e in epochs if e['session']==session]
    if not group:raise ValueError('Unknown measured session')
    return rm,mapping_doc,group


def validate_assumptions(a):
    if a.get('format')!='horus-measured-twin-assumptions-v1':raise ValueError('Assumptions format required')
    for key in ('dt_s','minimum_stable_support_s','nominal_bandwidth_mhz','n_prb','scs_khz','noise_figure_db'):
        if not isinstance(a[key],(int,float)) or not math.isfinite(a[key]) or a[key]<=0:
            raise ValueError(f'Invalid assumption: {key}')
    if not isinstance(a['n_prb'],int):raise ValueError('n_prb must be an integer')
    if not 0<=a['load']<=1 or not math.isfinite(a['external_interference_dbm_per_re']):
        raise ValueError('Invalid load or external interference assumption')
    if a['fading']!='off':raise ValueError('Measured surface must not silently add uncalibrated fading')


def stable_segments(values,dt,minimum_s):
    """Constant support masks isolate unknown geometry from radio execution.

    Return indices [start,end), represented duration and excluded intervals.
    The boundary clock step is excluded; it cannot imply a network event.
    """
    masks=np.isfinite(values);starts=[0]+list(np.flatnonzero(np.any(masks[1:]!=masks[:-1],axis=1))+1)
    segments=[];discarded=[]
    for start,end in zip(starts,starts[1:]+[len(values)]):
        duration=max(0,end-start-1)*dt
        cells=np.flatnonzero(masks[start])
        if len(cells)<2 or duration+1e-9<minimum_s:
            discarded.append(dict(start=int(start),end=int(end),seconds=duration,cells=int(len(cells))))
        else:segments.append((int(start),int(end),cells))
    return segments,dict(route_duration_s=max(0,len(values)-1)*dt,
                         represented_duration_s=sum((e-s-1)*dt for s,e,_ in segments),
                         segment_count=len(segments),support_change_boundaries=len(starts)-1,
                         boundary_duration_s=(len(starts)-1)*dt,excluded_intervals=discarded)


def make_traces(rm,mapping,epochs,a):
    validate_assumptions(a);dt=a['dt_s']
    t,x,y,source,gps=position_trace(epochs,dt)
    keys=[tuple(c['key']) for c in mapping['cells']]
    values=predict_matrix(rm,keys,x,y);values[~gps]=np.nan
    segments,coverage=stable_segments(values,dt,a['minimum_stable_support_s'])
    # Speed serves only stationary-HO accounting here (fading is off). Marked
    # holds override delayed phone speed; position derivatives are smoothed.
    lag=max(1,round(1/dt));left=np.maximum(np.arange(len(t))-lag,0);right=np.minimum(np.arange(len(t))+lag,len(t)-1)
    speeds=np.hypot(x[right]-x[left],y[right]-y[left])/np.maximum(t[right]-t[left],dt)
    speeds[[epochs[int(i)]['phase']=='marked_hold' for i in source]]=0
    thermal=-174+10*math.log10(a['scs_khz']*1000)+a['noise_figure_db']
    noise=10**(thermal/10)+10**(a['external_interference_dbm_per_re']/10)
    traces=[]
    for start,end,cells in segments:
        l1=values[start:end][:,cells][:,None,:]
        rx=10**(l1/10)   # measured-calibrated per-RE RSRP, not total TX power
        trace=RadioTrace(l1,rx,speeds[start:end,None],np.ones(len(cells),dtype=bool),
                         [mapping['cells'][i]['id'] for i in cells],['measured-walker'],load=a['load'],noise_mw=noise)
        traces.append((start,end,trace))
    coverage['represented_fraction']=coverage['represented_duration_s']/coverage['route_duration_s'] if coverage['route_duration_s'] else 0
    coverage['interpretation']='Only stable intervals with >=2 supported cells. Segment starts reset UE/controller; boundaries are not RLF/HO events.'
    return traces,coverage


def controller_for(spec):
    if spec=='a3':return A3Batch(**STOCK_A3,name='a3-stock')
    if spec=='a3-legacy':return A3Batch(**LEGACY_PARAMS_A3,name='a3-legacy-params')
    if spec=='cho':return CHOBatch(name='cho-default')
    raise ValueError('Measured execution supports a3, a3-legacy, cho or an explicitly checked policy artifact')


def execute(controller_spec,traces,assumptions):
    total=None;duration=0;segment_results=[]
    cfg=SimConfig(dt=assumptions['dt_s'])
    occupied=assumptions['n_prb']*12*assumptions['scs_khz']/1000
    for start,end,trace in traces:
        ctl=controller_for(controller_spec)
        env=TwinSim(trace,cfg,l3_k=ctl.l3_k,bandwidth_mhz=occupied)
        env.reset();ctl.reset();done=False
        while not done:_,_,done=env.step(ctl)
        if total is None:total={k:np.zeros_like(v) for k,v in env.c.items()}
        for k,v in env.c.items():total[k]+=v
        duration+=env.n_steps*cfg.dt
        segment_results.append(dict(start_s=start*cfg.dt,end_s=(end-1)*cfg.dt,cells=trace.cell_ids,
                                    metrics=env.metrics()))
    if total is None:raise ValueError('No sufficiently long supported multi-cell segments')
    metrics=summarize(total,1,duration,occupied)
    metrics['utility_modelled']=utility_per_ue_min(metrics)
    return dict(controller=controller_spec,metrics=metrics,segments=segment_results,
                conditional_supported_segments=True,whole_route_ho_rate_valid=False,
                provenance='Finals TwinSim execution over calibrated mean RSRP; interference/load, failures, throughput and utility are conditional simulated outcomes, not measured ground truth.')


def run(dataset,model,mapping,assumptions,session,controllers,out,policy_artifact=None):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    a=json.loads(Path(assumptions).read_text(encoding='utf-8'))
    rm,mapping_doc,epochs=load_inputs(dataset,model,mapping,session)
    traces,coverage=make_traces(rm,mapping_doc,epochs,a)
    guard=None
    if policy_artifact:
        guard=fixture_preflight(policy_artifact,mapping_doc)
        # No implicit conversion of nine-site weights or unqualified units.
        if guard['eligible']:raise ValueError('Qualified AI execution adapter required')
        guard.update(effective_controller='a3',ai_inference_calls=0)
        controllers=['a3']
    fingerprint=hashlib_trace(traces)
    result=dict(format='horus-measured-twin-run-v1',session=session,
                session_role='held-out model evaluation route' if epochs[0]['split']=='evaluation' else 'development/in-sample route',
                assumptions=a,occupied_resource_bandwidth_mhz=a['n_prb']*12*a['scs_khz']/1000,
                coverage=coverage,trace_sha256=fingerprint,
                model_sha256=hash_file(model),mapping_sha256=hash_file(mapping),dataset_manifest_sha256=hash_file(Path(dataset)/'manifest.json'),
                source_sha256={n:source_digest(Path(__file__).with_name(n)) for n in ('measured_twin.py','sim.py','phy.py','controllers_v2.py')},
                policy_guard=guard,runs=[execute(c,traces,a) for c in controllers],
                limits=['Neighbour identities/PLMN are conditional when using augmented model.',
                        'Missing cells are not proven absent; external interference floor is an assumption.',
                        'No measurement validates simulated SINR/load/HO outcomes/throughput.',
                        'No policy promotion or campus AI-performance improvement is claimed.'])
    (out/'results.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8',newline='\n')
    lines=['# Measured-radio integration into finals TwinSim','',f'Session: {session}. Trace SHA-256: `{fingerprint}`.',
           '',f"Represented {coverage['represented_duration_s']:.1f} / {coverage['route_duration_s']:.1f} seconds ({coverage['represented_fraction']*100:.1f}%), {coverage['segment_count']} stable multi-cell segments.",
           '',coverage['interpretation'],'','## Conditional simulation results','',
           '| Controller | HO attempts | HO success | RLF | Ping-pongs | Mean RSRP | Throughput proxy Mbps |',
           '|---|---:|---:|---:|---:|---:|---:|']
    for r in result['runs']:
        m=r['metrics'];lines.append(f"| {r['controller']} | {m['ho_attempts']} | {m['ho_success_rate']:.4f} | {m['rlf']} | {m['ping_pongs']} | {m['mean_rsrp_dbm']:.2f} | {m['mean_thr_mbps']:.2f} |")
    lines+=['','These are simulated outcomes under the attached assumptions, not field-measured network performance.','',*result['limits'],'','Assumptions: `'+json.dumps(a)+'`']
    if guard:lines+=['','Policy guard: `'+json.dumps(guard)+'`']
    (out/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8',newline='\n')
    return result


def integration_suite(dataset,serving_model,neighbor_model,mapping,assumptions,out):
    """Paired reference runs plus predeclared one-factor PHY sensitivities."""
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    primary=json.loads(Path(assumptions).read_text(encoding='utf-8'))
    cases=[('primary',{}),('load_025',{'load':.25}),('load_075',{'load':.75}),
           ('external_minus120',{'external_interference_dbm_per_re':-120}),
           ('external_minus100',{'external_interference_dbm_per_re':-100})]
    plan=dict(purpose='Execution integration and assumption sensitivity; no training, policy selection, gate tuning or promotion',
              primary_assumptions=primary,cases=[dict(name=n,override=v) for n,v in cases],
              cells_sha256=hash_file(mapping),model_sha256={'serving':hash_file(serving_model),'neighbor':hash_file(neighbor_model)})
    (out/'suite-plan-frozen.json').write_text(json.dumps(plan,indent=2)+'\n',encoding='utf-8',newline='\n')
    results=[]
    for variant,model in [('serving_only',serving_model),('neighbor_assumption',neighbor_model)]:
        for session in ['t4-forward','t4-reverse']:
            rm,mapping_doc,epochs=load_inputs(dataset,model,mapping,session)
            original,coverage=make_traces(rm,mapping_doc,epochs,primary)
            for case,override in (cases if variant=='neighbor_assumption' and session=='t4-reverse' else cases[:1]):
                a=dict(primary,**override)
                thermal=-174+10*math.log10(a['scs_khz']*1000)+a['noise_figure_db']
                noise=10**(thermal/10)+10**(a['external_interference_dbm_per_re']/10)
                traces=[(start,end,replace(trace,load=a['load'],noise_mw=noise)) for start,end,trace in original]
                for controller in ('a3','a3-legacy','cho'):
                    r=execute(controller,traces,a)
                    results.append(dict(session=session,variant=variant,case=case,assumptions=a,coverage=coverage,
                                        trace_sha256=hashlib_trace(traces),**r))
                print(f"completed {session} / {variant} / {case}",flush=True)
    suite=dict(plan=plan,runs=results,
               interpretation='All metrics conditional on represented intervals and assumed PHY. Different surfaces/coverage are not paired directly. Same case/variant/session uses identical trace for each controller. No real network or AI-superiority claim.')
    (out/'suite-results.json').write_text(json.dumps(suite,indent=2)+'\n',encoding='utf-8',newline='\n')
    lines=['# Measured TwinSim integration suite','',suite['interpretation'],'',
           '| Session | Surface | Case | Controller | Represented % | Attempts | Failures | RLF | Utility (modelled) |',
           '|---|---|---|---|---:|---:|---:|---:|---:|']
    for r in results:
        m=r['metrics'];lines.append(f"| {r['session']} | {r['variant']} | {r['case']} | {r['controller']} | {r['coverage']['represented_fraction']*100:.1f} | {m['ho_attempts']} | {m['hof']} | {m['rlf']} | {m['utility_modelled']:.3f} |")
    lines+=['','Segment boundaries censor events and reset UE/controller state. Whole-route handover rates cannot be inferred from segment aggregates.',
            'Interference/load and channel bandwidth remain declared assumptions. RSRP calibration does not validate those mechanisms.',
            'Serving-only and neighbour-augmented surfaces are separate support/identity-assumption cases; report them separately.',
            'Current nine-site DQN compatibility and original policy gate criteria are not changed by these runs.']
    (out/'SUITE.md').write_text('\n'.join(lines)+'\n',encoding='utf-8',newline='\n')
    return suite


def hashlib_trace(traces):
    import hashlib
    h=hashlib.sha256()
    for start,end,tr in traces:
        h.update(json.dumps([start,end,tr.cell_ids,tr.load,tr.noise_mw]).encode())
        for a in (tr.l1,tr.rx,tr.speeds):h.update(np.asarray(a,dtype='<f8').tobytes())
    return h.hexdigest()
