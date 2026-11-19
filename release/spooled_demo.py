"""Keep active capture I/O in Linux tmpfs; persist each completed, verified cycle.

The original runner owns model, freshness, radio control and acceptance. This
observer changes only capture storage. Original files and timestamps are copied
unchanged. An archive is fresh-only; failed/incomplete cycles stay distinguishable.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tree_hashes(root):
    root = Path(root)
    if root.is_symlink() or (hasattr(root, 'is_junction') and root.is_junction()):
        raise ValueError('Archive source root is a link')
    if not root.is_dir():
        raise ValueError('Archive source must be an existing directory')
    root = root.resolve()
    found = {}
    for path in root.rglob('*'):
        if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()) or not path.resolve().is_relative_to(root):
            raise ValueError('Archive source contains a link or escaped path')
        if path.is_file():
            found[path.relative_to(root).as_posix()] = sha(path)
        elif not path.is_dir():
            raise ValueError('Archive source contains a special file')
    return found


def tree_dirs(root):
    return sorted(p.relative_to(root).as_posix() for p in Path(root).rglob('*') if p.is_dir())


def verify_capture(root, expected):
    root = Path(root).resolve()
    manifest = root/'dashboard/manifest.json'
    if sha(manifest) != expected:
        raise ValueError('Completed replay manifest changed')
    data = json.loads(manifest.read_text())
    for name, record in data['files'].items():
        rel = PurePosixPath(name)
        if rel.is_absolute() or '..' in rel.parts or '\\' in name or ':' in name:
            raise ValueError('Unsafe replay member')
        path = (manifest.parent/name).resolve()
        if not path.is_relative_to(manifest.parent) or sha(path) != record['sha256']:
            raise ValueError('Completed replay file changed')


def publish_tree(source, destination, *, expected_manifest=None, accepted=False):
    """Publish an immutable actual tree, refusing replacement or changed evidence."""
    source, destination = Path(source), Path(destination)
    if destination.exists():
        raise FileExistsError('An archived cycle may not be replaced')
    if destination.resolve().is_relative_to(source.resolve()):
        raise ValueError('Archive destination must be outside its source')
    before = tree_hashes(source)
    directories = tree_dirs(source)
    if 'SPOOL-SNAPSHOT.json' in before:
        raise ValueError('Reserved snapshot name already exists')
    if accepted:
        if not expected_manifest:
            raise ValueError('Accepted cycles require their original manifest hash')
        verify_capture(source, expected_manifest)
    temporary = destination.parent/('.'+destination.name+'-'+uuid.uuid4().hex+'.partial')
    temporary.mkdir(parents=True, exist_ok=False)
    for name in directories:
        (temporary/name).mkdir(parents=True, exist_ok=True)
    for name, digest in before.items():
        target = temporary/name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source/name, target)
        if sha(target) != digest:
            raise ValueError('Source changed while archiving; partial copy retained')
    if tree_hashes(source) != before or tree_dirs(source) != directories:
        raise ValueError('Source changed while archiving; partial copy retained')
    receipt = dict(schema='horus.capture-spool/1', accepted_cycle=accepted,
                   original_manifest_sha256=expected_manifest, original_files_sha256=before,
                   original_directories=directories,
                   original_bytes_unchanged=True)
    (temporary/'SPOOL-SNAPSHOT.json').write_text(json.dumps(receipt, indent=2)+'\n')
    if destination.exists():
        raise FileExistsError('Archive appeared while copying; partial copy retained')
    temporary.rename(destination)
    return receipt


def save(path, value):
    temporary = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n')
    temporary.replace(path)


def filesystem_type(path):
    path = Path(path).resolve()
    matches = []
    for line in Path('/proc/mounts').read_text().splitlines():
        fields = line.split()
        mount = Path(fields[1].replace('\\040', ' ').replace('\\011', '\t')).resolve()
        if path.is_relative_to(mount):
            matches.append((len(str(mount)), fields[2]))
    if not matches:
        raise ValueError('Cannot establish archive filesystem')
    return max(matches)[1]


def release_ram(parent, capture, expected_files, expected_dirs):
    parent, capture = Path(parent), Path(capture)
    if parent.is_symlink() or parent.resolve().parent != Path('/dev/shm').resolve() or not parent.name.startswith('horus-demo-'):
        raise ValueError('Unexpected RAM capture owner')
    if capture.parent != parent or capture.name != 'capture':
        raise ValueError('Unexpected RAM capture path')
    allowed = {capture} if capture.exists() else set()
    if set(parent.iterdir()) != allowed:
        raise ValueError('Foreign RAM-parent entries preserved; nothing deleted')
    if capture.exists():
        if tree_hashes(capture) != expected_files or tree_dirs(capture) != expected_dirs:
            raise ValueError('RAM capture changed after archival; nothing deleted')
        shutil.rmtree(capture)
    parent.rmdir()  # never recursively delete unarchived siblings


def cleanup_owned(root, capture):
    """Backstop after a runner crash; never take over a pre-existing profile."""
    if not (capture/'startup.txt').exists():
        return False
    profile = (root/'stack/oai-ho').resolve()
    names = subprocess.check_output(['docker','ps','-a','--filter','name=^/ho-',
                                     '--format','{{.Names}}'], text=True).splitlines()
    for name in names:
        owner = subprocess.check_output(['docker','inspect','-f',
            '{{index .Config.Labels "com.docker.compose.project.working_dir"}}', name], text=True).strip()
        if Path(owner).resolve() != profile:
            raise RuntimeError('Unexpected container owner; no cleanup attempted')
    if names:
        from run_demo import radio_environment
        subprocess.run(['docker','compose','--env-file','/dev/null','--profile','metrics','down'],
                       cwd=profile, check=True, timeout=180,
                       env=radio_environment(profile,argparse.Namespace()))
    return True


def run(args):
    from run_demo import validate_radio_options
    validate_radio_options(args)
    if not args.live or sys.platform != 'linux':
        raise ValueError('Explicit --live on native Linux is required')
    if filesystem_type('/dev/shm') != 'tmpfs':
        raise ValueError('/dev/shm must be an actual tmpfs mount')
    if shutil.disk_usage('/dev/shm').free < 512*1024**2:
        raise ValueError('At least 512 MiB of free tmpfs capture capacity is required')
    archive, root = args.out.resolve(), args.root.resolve()
    archive_type = filesystem_type(archive)
    if archive_type in ('tmpfs', 'ramfs'):
        raise ValueError('The durable archive must be on a non-RAM filesystem')
    archive.mkdir(parents=True, exist_ok=False)
    ram_parent = Path(tempfile.mkdtemp(prefix='horus-demo-', dir='/dev/shm'))
    capture = ram_parent/'capture'
    status = dict(schema='horus.spooled-demo/1', passed=False, capture_storage='Linux tmpfs',
        durable_archive=str(archive), archive_filesystem=archive_type, active_capture=str(capture), completed_cycles=[],
        runner_source_sha256=sha(root/'release/run_demo.py'), spooler_source_sha256=sha(__file__),
        source_manifest_sha256=sha(root.parent/'assembly-manifest.json'), source_code_root=str(root),
        python=sys.version, python_executable=sys.executable,
        source_and_acceptance_unchanged=True,ue_image_override=getattr(args,'ue_image',None),
        du_image_override=getattr(args,'du_image',None),
        flexric_image_override=getattr(args,'flexric_image',None),
        cu_image_override=getattr(args,'cu_image',None),cu_srb_reordering_ms=getattr(args,'cu_srb_reordering_ms',None))
    save(archive/'SPOOL-STATUS.json', status)
    command = [sys.executable, str(root/'release/run_demo.py'), '--root', str(root), '--out', str(capture),
               '--live', '--soak-seconds', str(args.soak_seconds), '--port', str(args.port),
               '--qualification', getattr(args, 'qualification', 'selector-integration')]
    if getattr(args,'ue_image',None):command.extend(['--ue-image',args.ue_image])
    if getattr(args,'du_image',None):command.extend(['--du-image',args.du_image])
    if getattr(args,'flexric_image',None):command.extend(['--flexric-image',args.flexric_image])
    if getattr(args,'cu_image',None):
        command.extend(['--cu-image',args.cu_image,'--cu-srb-reordering-ms',str(args.cu_srb_reordering_ms)])
    process = None
    original_start = None
    published = set()
    def publish_completed(report):
        for cycle in report.get('cycles', []):
            index = cycle['index']
            if type(index) is not int or not 0 <= index < 10000:
                raise ValueError('Invalid completed cycle identity')
            if index not in published:
                name = f'cycle-{index:03d}'
                publish_tree(capture/name, archive/name,
                    expected_manifest=cycle['replay_manifest_sha256'], accepted=True)
                published.add(index)
                status['completed_cycles'] = sorted(published)
                save(archive/'SPOOL-STATUS.json', status)
                print(json.dumps(dict(event='cycle_archived', cycle=index, original_bytes_verified=True)), flush=True)
    try:
        with (archive/'runner-console.txt').open('x') as console:
            process = subprocess.Popen(command, stdout=console, stderr=subprocess.STDOUT, start_new_session=True,
                                       env=dict(os.environ, PYTHONFAULTHANDLER='1'))
            try: original_start = Path(f'/proc/{process.pid}/stat').read_text().rsplit(')', 1)[1].split()[19]
            except FileNotFoundError: pass
            last_progress = -float('inf')
            while process.poll() is None:
                if (capture/'result.json').exists():
                    try: report = json.loads((capture/'result.json').read_text())
                    except json.JSONDecodeError: report = None  # writer may be replacing a progress report
                    if report: publish_completed(report)
                if shutil.disk_usage('/dev/shm').free < 128*1024**2:
                    raise RuntimeError('Capture capacity floor reached; no timestamps or criteria changed')
                if time.monotonic()-last_progress >= 60:
                    progress = dict(event='spool_progress', archived_cycles=len(published))
                    heartbeats = sorted(capture.glob('cycle-*/dashboard/evidence/runtime-eligibility.jsonl'))
                    if heartbeats:
                        try:
                            with heartbeats[-1].open('rb') as stream:
                                stream.seek(max(0, heartbeats[-1].stat().st_size-8192))
                                row = json.loads(stream.read().splitlines()[-1])
                            progress['last_recorded_status'] = {k:row.get(k) for k in
                                ('ts','session_id','session_state','inference_calls','invalid_frames','fallback_frames','model_faults')}
                        except (OSError, ValueError, IndexError): pass
                    print(json.dumps(progress), flush=True)
                    last_progress = time.monotonic()
                time.sleep(1)
        status['runner_exit_code'] = process.returncode
        report = json.loads((capture/'result.json').read_text()) if (capture/'result.json').exists() else {}
        publish_completed(report)
        status['passed'] = bool(process.returncode == 0 and report.get('passed') and
                                report.get('cleanup_passed') and report.get('source_hashes_match'))
    except Exception as exc:
        status['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        if process and process.poll() is None:
            process.send_signal(signal.SIGINT)
            try: process.wait(timeout=240)
            except subprocess.TimeoutExpired: process.kill(); process.wait()
        if process and process.returncode != 0 and original_start is not None:
            # Only the fresh child session's process group, including orphaned
            # producer/driver/traffic clients. Container cleanup is guarded separately.
            try:
                current_start = Path(f'/proc/{process.pid}/stat').read_text().rsplit(')', 1)[1].split()[19]
            except FileNotFoundError: current_start = None
            if current_start in (None, original_start):
                try: os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError: pass
        try:
            result = json.loads((capture/'result.json').read_text()) if (capture/'result.json').exists() else {}
            if not result.get('cleanup_passed') and (capture/'startup.txt').exists():
                status['backstop_cleanup_passed'] = cleanup_owned(root, capture)
            original_files = tree_hashes(capture) if capture.exists() else {}
            original_dirs = tree_dirs(capture) if capture.exists() else []
            cycle_dirs = {p.name for p in capture.glob('cycle-*') if p.is_dir()}
            for source in (capture/name for name in sorted(cycle_dirs)):
                if source.name not in {f'cycle-{i:03d}' for i in published}:
                    publish_tree(source, archive/('incomplete-'+source.name), accepted=False)
            # Root files are written only after all child writers have stopped.
            other = archive/'run-files';other.mkdir()
            for source in capture.iterdir() if capture.exists() else []:
                if source.name in cycle_dirs: continue
                if source.is_file():
                    if source.is_symlink(): raise ValueError('Unexpected root capture link')
                    shutil.copyfile(source, other/source.name)
                    if sha(source) != sha(other/source.name): raise ValueError('Archive copy mismatch')
                elif source.is_dir():
                    publish_tree(source, other/source.name, accepted=False)
            def archived_path(name):
                head, *tail = PurePosixPath(name).parts
                if head in {f'cycle-{i:03d}' for i in published}:
                    return archive.joinpath(head, *tail)
                if head in cycle_dirs:
                    return archive.joinpath('incomplete-'+head, *tail)
                return other/name
            if any(sha(archived_path(name)) != digest for name,digest in original_files.items()):
                raise ValueError('Not all original capture files were archived')
            if any(not archived_path(name).is_dir() for name in original_dirs):
                raise ValueError('Not all original capture directories were archived')
            if capture.exists() and (tree_hashes(capture) != original_files or tree_dirs(capture) != original_dirs):
                raise ValueError('Capture changed during final archive')
            status['all_available_evidence_archived'] = True
        except Exception as exc:
            status['passed'] = False
            status['archive_error'] = f'{type(exc).__name__}: {exc}'
        if status.get('all_available_evidence_archived'):
            try:
                release_ram(ram_parent, capture, original_files, original_dirs)
                status['ram_capture_released'] = True
            except (OSError, ValueError) as exc:
                status['passed'] = False
                status['ram_release_error'] = str(exc)
        save(archive/'SPOOL-STATUS.json', status)
    print(json.dumps(status), flush=True)
    return 0 if status['passed'] else 1


if __name__ == '__main__':
    from run_demo import ue_image
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path, help='Fresh durable archive directory')
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--soak-seconds', type=float, default=0)
    parser.add_argument('--port', type=int, default=8027)
    parser.add_argument('--qualification', default='selector-integration', help='working/evidence/<dir> of the qualified candidate (default: v3.39.0)')
    parser.add_argument('--ue-image',type=ue_image,help='Explicit emulated UE image; passed unchanged to the recorded runner')
    parser.add_argument('--du-image',type=ue_image,help='Explicit laboratory image for both DUs; passed unchanged to the recorded runner')
    parser.add_argument('--flexric-image',type=ue_image,help='Explicit RIC/xApp image; passed unchanged to the recorded runner')
    parser.add_argument('--cu-image',type=ue_image,help='Explicit laboratory CU image; requires --cu-srb-reordering-ms')
    parser.add_argument('--cu-srb-reordering-ms',type=int,choices=[1000],help='Explicit CU-only laboratory timer; requires --cu-image')
    args = parser.parse_args()
    if not 0 <= args.soak_seconds <= 14400 or not 1024 <= args.port <= 65535:
        parser.error('Invalid rehearsal limits')
    try: raise SystemExit(run(args))
    except (OSError, ValueError) as exc: parser.exit(2, f'Refused: {exc}\n')
