"""Isolated qualified selector/OAI/dashboard rehearsal with preserved captures.

Run in native WSL. Explicit --live is required for RAN access. Existing OAI
containers are never taken over. Only the owned profile is stopped; volumes stay.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
from urllib.request import urlopen


def ue_image(value):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/@-]{0,254}',value):
        raise argparse.ArgumentTypeError('Expected a Docker image reference without whitespace')
    return value


def validate_radio_options(args):
    for name in ('ue_image','du_image','flexric_image'):
        if getattr(args,name,None):ue_image(getattr(args,name))
    cu=getattr(args,'cu_image',None)
    timer=getattr(args,'cu_srb_reordering_ms',None)
    if bool(cu) != (timer is not None):
        raise ValueError('CU image and CU SRB reorder timer must be explicitly selected together')
    if cu:
        ue_image(cu)
        if type(timer) is not int or timer != 1000:
            raise ValueError('Only the 1000 ms laboratory CU timer is supported')


def radio_environment(source,args):
    validate_radio_options(args)
    env=dict(os.environ,COMPOSE_ENV_FILES='/dev/null',COMPOSE_FILE=str(source/'docker-compose.yml'),
             OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1')
    for name in ('HORUS_NR_UE_IMAGE','HORUS_CU_IMAGE','HORUS_DU_IMAGE','HORUS_FLEXRIC_IMAGE','HORUS_LAB_SRB_REORDERING_MS'):
        env.pop(name,None)
    if getattr(args,'ue_image',None):env['HORUS_NR_UE_IMAGE']=ue_image(args.ue_image)
    if getattr(args,'du_image',None):env['HORUS_DU_IMAGE']=ue_image(args.du_image)
    if getattr(args,'flexric_image',None):env['HORUS_FLEXRIC_IMAGE']=ue_image(args.flexric_image)
    if getattr(args,'cu_image',None):
        env['HORUS_CU_IMAGE']=ue_image(args.cu_image)
        env['HORUS_LAB_SRB_REORDERING_MS']=str(args.cu_srb_reordering_ms)
    return env


def run(a):
    validate_radio_options(a)
    root, out = a.root.resolve(), a.out.resolve()
    if not a.live:
        raise ValueError('Actuating rehearsal requires explicit --live; use dashboard/horus_dash.py for recorded replay')
    # qualification directory under working/evidence: selector-integration (v3.39.0, default, unchanged)
    # or selector-integration-v3.14 (release/selector_integration_v314.py)
    qualification = getattr(a, 'qualification', 'selector-integration')
    if not re.fullmatch(r'selector-integration(-v[0-9.]+)?', qualification):
        raise ValueError('Unknown qualification directory')
    proof = root/'working/evidence'/qualification
    parity = json.loads((proof/'runtime-parity.json').read_text())
    if not parity['passed']:
        raise ValueError('Complete source-bound runtime qualification required')
    sys.path[:0] = [str(root/'stack'), str(root/'dashboard')]
    from selector_runtime import SelectorRuntime, read_json
    from selector_telemetry import append, save, utc
    from session_clock import SessionClock
    import horus_data as hd
    import horus_dash as dash
    from http.server import ThreadingHTTPServer
    context = read_json(proof/'context.json')
    runtime = SelectorRuntime(root, context)
    if not runtime.load(proof/'artifact.json')['live_eligible']:
        raise ValueError('Actual candidate refused by current runtime')
    version = runtime.version
    names = subprocess.check_output(['docker','ps','-a','--format','{{.Names}}'],text=True).splitlines()
    active = subprocess.check_output(['docker','ps','--format','{{.Names}}'],text=True).splitlines()
    if any(n.startswith('ho-') for n in names) or any(n in ('gnb','ue','flexric') for n in active):
        raise RuntimeError('Existing operator stack detected; no containers touched')
    source = root/'stack/oai-ho'
    if (source/'.env').exists():
        raise ValueError('Private dotenv is not an allowed release input')
    out.mkdir(parents=True,exist_ok=False)
    env = radio_environment(source,a)
    report = dict(started=utc(), passed=False, cycles=[], candidate_version=version, qualification_dir=qualification, qualification='calibrated replay -> emulated OAI ordinary F1; not field RAN or native CHO',
                  required_sustained_utc_seconds=a.soak_seconds, final_evaluation_verdict=None,
                  ue_image_override=getattr(a,'ue_image',None),cu_image_override=getattr(a,'cu_image',None),
                  du_image_override=getattr(a,'du_image',None),
                  flexric_image_override=getattr(a,'flexric_image',None),
                  cu_srb_reordering_ms=getattr(a,'cu_srb_reordering_ms',None))
    children, handles, readers = [], [], []
    server = None
    owned = False
    def record():
        save(out/'result.json',report)
    def command(label,cmd,timeout=120):
        with (out/(label+'.txt')).open('x') as log:
            result = subprocess.run(cmd,cwd=source,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=timeout)
        if result.returncode:
            raise RuntimeError(f'{label} failed ({result.returncode}); capture preserved')
    def child(label,cmd):
        stream=(out/(label+'.txt')).open('x');handles.append(stream)
        proc=subprocess.Popen(cmd,cwd=root,env=env,stdout=stream,stderr=subprocess.STDOUT)
        children.append(proc)
        return proc
    def stop(proc):
        if proc.poll() is None:
            proc.terminate()
            try: proc.wait(timeout=10)
            except subprocess.TimeoutExpired: proc.kill();proc.wait()
    try:
        owned=True
        command('startup',['bash','./ho-up.sh'],900)
        # Startup finishes when F1/E2 are connected. Allow the emulated target
        # radio to settle before traffic readiness checks and starting inputs.
        report['radio_startup_settle_seconds']=8
        time.sleep(report['radio_startup_settle_seconds'])
        report['ue_image_id']=subprocess.check_output(['docker','inspect','-f','{{.Image}}','ho-nr-ue'],text=True).strip()
        report['cu_image_id']=subprocess.check_output(['docker','inspect','-f','{{.Image}}','ho-cu'],text=True).strip()
        report['flexric_image_id']=subprocess.check_output(['docker','inspect','-f','{{.Image}}','ho-flexric'],text=True).strip()
        report['handover_xapp_sha256']=subprocess.check_output(['docker','exec','ho-flexric','sha256sum',
            '/usr/local/flexric/xApp/c/rc_handover/xapp_horus_ho'],text=True).split()[0]
        report['du_image_ids']={name:subprocess.check_output(['docker','inspect','-f','{{.Image}}',name],text=True).strip()
                                for name in ('ho-du-pci0','ho-du-pci1')}
        cores=sorted(os.sched_getaffinity(0))
        if len(cores)<3:
            raise RuntimeError('Integrated live rehearsal requires at least three available CPU cores')
        report['cpu_allocation']=dict(shared_available_cores=cores,
            note='Shared CPU allocation; RF simulation retains all available CPUs')
        command('traffic-before',['docker','exec','ho-nr-ue','ping','-c','4','-W','3','-I','oaitun_ue1','192.168.72.135'],30)
        app=dash.App(str(out/'not-yet-started'),None,prober=None)
        server=ThreadingHTTPServer(('127.0.0.1',a.port),dash.make_handler(app))
        threading.Thread(target=server.serve_forever,daemon=True).start()
        report['dashboard_url']=f'http://127.0.0.1:{a.port}'
        report['sustained_started']=utc()
        sustained,sustained_wall=time.monotonic(),time.time()
        # The soak must hold on BOTH clocks: WSL's CLOCK_MONOTONIC was measured running 3.7-5% fast
        # against UTC on the lab host, so a monotonic-only loop under-delivers real sustained time.
        elapsed=lambda:min(time.monotonic()-sustained,time.time()-sustained_wall)
        index=0
        while index < a.cycles or elapsed() < a.soak_seconds:
            cycle=out/f'cycle-{index:03d}'
            cycle.mkdir()
            capture=cycle/'dashboard'
            app.root=str(capture)
            ready,frames=cycle/'ready.json',cycle/'frames.jsonl'
            producer=child(f'producer-{index:03d}',[sys.executable,str(root/'stack/measured_selector_stream.py'),
                '--root',str(root),'--context',str(proof/'context.json'),'--out',str(frames),
                '--segment','0','--seconds','186.1','--wait-ready',str(ready),'--version',version])
            deadline=time.monotonic()+90
            while not frames.exists():
                if producer.poll() is not None or time.monotonic()>deadline:
                    raise RuntimeError('Producer initialization failed')
                time.sleep(.05)
            driver=child(f'driver-{index:03d}',[sys.executable,str(root/'stack/oai-ho/selector_driver.py'),
                '--root',str(root),'--artifact',str(proof/'artifact.json'),'--context',str(proof/'context.json'),
                '--frames',str(frames),'--out',str(cycle/'driver'),'--live','--follow','--learned-only',
                '--ready-file',str(ready),'--track','measured-walker','--max-hos','2','--min-gap-s','10',
                '--timeout-s','231.1','--dashboard-archive',str(capture)])
            deadline=time.monotonic()+65
            while not ready.exists():
                if driver.poll() is not None or time.monotonic()>deadline:
                    raise RuntimeError('Consumer clock/readiness initialization failed')
                time.sleep(.05)
            clock=SessionClock(read_json(ready)['clock'])
            traffic_log=(out/f'traffic-{index:03d}.txt').open('x');handles.append(traffic_log)
            traffic=subprocess.Popen(['docker','exec','ho-nr-ue','ping','-D','-i','1','-W','3',
                '-I','oaitun_ue1','192.168.72.135'],cwd=root,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1)
            children.append(traffic)
            replies=[]
            def read_traffic(proc=traffic,log=traffic_log,destination=capture,session_clock=clock,received=replies):
                for line in proc.stdout:
                    observed=time.monotonic()
                    log.write(line);log.flush()
                    match=re.search(r'\[([0-9.]+)\].*?time[=<]([0-9.]+) ms',line)
                    if match:
                        received.append(observed)
                        append(destination/'metrics/rtt.jsonl',dict(ts=datetime.fromtimestamp(session_clock.at_monotonic(observed),timezone.utc).isoformat(),
                            observed_mono_s=observed,raw_ping_wall_utc_s=float(match[1]),ue='measured-walker',rtt_ms=float(match[2]),
                            source='OAI RF-simulator ICMP; original wall stamp retained, observation clock is steady session UTC'))
                proc.stdout.close()
            reader=threading.Thread(target=read_traffic,daemon=True);readers.append(reader);reader.start()
            api_good=0; learned_good=0; copied_research=False
            deadline=time.monotonic()+300
            while driver.poll() is None:
                if producer.poll() not in (None,0) or time.monotonic()>deadline:
                    raise RuntimeError('Producer failure or bounded driver timeout')
                if capture.exists() and not copied_research:
                    research=root/'working/research'
                    (capture/'evidence').mkdir(exist_ok=True)
                    if (research/'dashboard-results.json').exists():
                        shutil.copyfile(research/'dashboard-results.json',capture/'evidence/finals-results.json')
                        shutil.copyfile(research/'finals-results-original.json',capture/'evidence/finals-results-original.json')
                    for candidate in (research/'packages').glob('*.artifact.json'):
                        art=read_json(candidate)
                        target=capture/'candidates'/f'{art["version"]}.json'
                        if not target.exists():shutil.copyfile(candidate,target)
                    for campus in (root/'working/evidence').glob('finals-campus-*.json'):
                        shutil.copyfile(campus,capture/'evidence'/campus.name)
                    copied_research=True
                with urlopen(report['dashboard_url']+'/api/state?src=live',timeout=10) as response:
                    state=json.load(response)
                if state.get('error'):
                    raise RuntimeError('Dashboard API error: '+state['error'])
                api_good+=1
                if state['runtime']['ai_active']:
                    learned_good+=1
                    save(cycle/'dashboard-learned-state.json',state)
                append(cycle/'api-monitor.jsonl',dict(ts=clock.iso(),ai_active=state['runtime']['ai_active'],
                    effective=state['runtime']['effective'],eligibility=state['runtime']['eligibility']))
                time.sleep(1)
            producer_rc=producer.wait(timeout=60)
            stop(traffic)
            reader.join(timeout=10)
            if reader.is_alive():raise RuntimeError('Traffic observer did not stop')
            if driver.returncode or producer_rc:
                raise RuntimeError(f'Driver {driver.returncode} / producer {producer_rc}; failed run preserved')
            summary=read_json(cycle/'driver/summary.json')
            decisions=[json.loads(s) for s in (cycle/'driver/decisions.jsonl').read_text().splitlines()]
            actions=[json.loads(s) for s in (cycle/'driver/timed-actions.jsonl').read_text().splitlines()]
            rt=summary['runtime']
            if not (summary['confirmed_handovers']==2 and summary['failed_controls']==0 and rt['inference_calls']>0
                    and rt['invalid_frames']==rt['model_faults']==rt['fallback_frames']==0 and learned_good>0):
                raise RuntimeError('Selector/control/dashboard acceptance failed')
            if not all(x['result']=='ok' and x['params']['ric_control_result']=='acked' and
                       x['params']['source_du']!=x['params']['target_du'] for x in actions):
                raise RuntimeError('Missing independent ACK/CU evidence')
            counts=[]
            for i,x in enumerate(actions):
                confirmed=x['confirmation_mono_s']
                until=actions[i+1]['decision_mono_s'] if i+1<len(actions) else float('inf')
                counts.append(sum(confirmed<t<until for t in replies))
            if min(counts)<2:
                raise RuntimeError('Insufficient post-handover traffic')
            # Final driver heartbeat must stop an active-AI claim immediately.
            state=hd.build_state(str(capture),clock.timestamp())
            if state['runtime']['ai_active']:
                raise RuntimeError('Stopped session still claims active AI')
            # External metrics are now finalized; bind the entire replay, not only writer-owned files.
            man=read_json(capture/'manifest.json')
            man['files']={p.relative_to(capture).as_posix():dict(bytes=p.stat().st_size,
                sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in capture.rglob('*')
                if p.is_file() and p.name!='manifest.json'}
            save(capture/'manifest.json',man)
            report['cycles'].append(dict(index=index,summary=summary,api_frames=api_good,learned_api_frames=learned_good,
                post_handover_replies=counts,max_input_age_s=max(d.get('input_age_s',0) for d in decisions),
                replay_manifest_sha256=hashlib.sha256((capture/'manifest.json').read_bytes()).hexdigest()))
            report['sustained_elapsed_seconds']=time.monotonic()-sustained
            report['sustained_elapsed_utc_seconds']=time.time()-sustained_wall
            record()
            print(json.dumps(dict(cycle=index,confirmed_handovers=2,learned_api_frames=learned_good,
                sustained_elapsed_seconds=report['sustained_elapsed_seconds'])),flush=True)
            index+=1
        command('traffic-after',['docker','exec','ho-nr-ue','ping','-c','6','-W','3','-I','oaitun_ue1','192.168.72.135'],40)
        report['passed']=True
    except Exception as exc:
        report['error']=f'{type(exc).__name__}: {exc}'
    finally:
        for proc in reversed(children):stop(proc)
        for reader in readers:reader.join(timeout=10)
        for stream in handles:stream.close()
        if server:server.shutdown();server.server_close()
        if owned:
            # Capture protocol diagnostics before removing owned containers.
            # Exclude authentication/security lines from reviewable logs.
            for name in ('ho-cu','ho-du-pci0','ho-du-pci1','ho-nr-ue','ho-flexric'):
                try:
                    log=subprocess.run(['docker','logs','--tail','12000',name],capture_output=True,text=True,timeout=15)
                    lines=[line for line in (log.stdout+log.stderr).splitlines()
                        if re.search(r'(?i)handover|\bF1\b|RRCReconfiguration|E1AP|\bPDCP\b|\bRLC\b|error|assert|fail|timed.?out|cell|synchron',line)
                        and not re.search(r'(?i)imsi|supi|suci|\bopc\b|password|token|\bkey\b|authentication|security|\bNAS\b',line)]
                    (out/(name+'-protocol.txt')).write_text('\n'.join(lines)+'\n')
                except (OSError,subprocess.TimeoutExpired) as exc:
                    report.setdefault('diagnostic_errors',[]).append(type(exc).__name__)
            try:
                command('shutdown',['docker','compose','--env-file','/dev/null','--profile','metrics','down'],180)
                report['cleanup_passed']=True
            except Exception as exc:report['cleanup_passed']=False;report['cleanup_error']=str(exc)
        report['finished']=utc()
        manifest=read_json(root.parent/'assembly-manifest.json')
        report['source_files_verified']=len(manifest['files'])
        report['source_hashes_match']=all(hashlib.sha256((root/n).read_bytes()).hexdigest()==v['sha256'] for n,v in manifest['files'].items())
        record()
    print(json.dumps({k:report.get(k) for k in ('passed','error','cleanup_passed','source_hashes_match')}),flush=True)
    return 0 if report['passed'] and report.get('cleanup_passed') and report['source_hashes_match'] else 1


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--live',action='store_true')
    p.add_argument('--cycles',type=int,default=1)
    p.add_argument('--soak-seconds',type=float,default=0)
    p.add_argument('--port',type=int,default=8027)
    p.add_argument('--qualification',default='selector-integration',help='working/evidence/<dir> holding the qualified candidate (default: v3.39.0)')
    p.add_argument('--ue-image',type=ue_image,help='Explicit emulated UE image override; identity recorded, original default preserved')
    p.add_argument('--du-image',type=ue_image,help='Explicit laboratory image for both DUs; identities recorded, original default preserved')
    p.add_argument('--flexric-image',type=ue_image,help='Explicit RIC/xApp image; image and handover binary identities recorded')
    p.add_argument('--cu-image',type=ue_image,help='Explicit laboratory CU image; requires --cu-srb-reordering-ms')
    p.add_argument('--cu-srb-reordering-ms',type=int,choices=[1000],help='Explicit CU-only laboratory PDCP receive timer; requires --cu-image')
    a=p.parse_args()
    if a.cycles<1 or not 0<=a.soak_seconds<=14400 or not 1024<=a.port<=65535:p.error('Invalid rehearsal limits')
    raise SystemExit(run(a))
