"""Compile the actual patched OAI helper and check synchronization/SFN boundaries."""
from pathlib import Path
import hashlib,json,re,subprocess,sys

root=Path(sys.argv[1]);out=Path(sys.argv[2]);out.mkdir(exist_ok=False)
source=(root/'executables/nr-ue.c').read_text()
function=re.search(r'static int sync_frame_start\([^\n]+\)\n\{.*?\n\}',source,re.S).group()
assert source.count('decoded_frame_rx = sync_frame_start(')==1
assert 'fp->samples_per_frame, &syncMsg->rx_offset)' in source
cases=[(0,0,0,0,0),(10,2,0,12,0),(10,2,1,12,1),
       (1023,2,614399,1,614399),(10,2,-176,13,614224),
       (1023,0,-1,0,614399),(1023,2,-176,2,614224),
       (0,1024,-176,1,614224),(10,2,-614399,13,1),
       (10,2,1228799,12,1228799),(523,2,-2224,526,612176)]
harness='#include <assert.h>\n#define MAX_FRAME_NUMBER 1024\n'+function+'\nint main(void) {\n'
for frame,skip,offset,expected_frame,expected_offset in cases:
    harness+=f'{{ int offset={offset}; assert(sync_frame_start({frame},{skip},614400,&offset)=={expected_frame}); assert(offset=={expected_offset}); }}\n'
harness+='return 0; }\n'
harness=harness.replace('return 0; }','{ int offset=-2224; assert(sync_frame_start(523,2,1228800,&offset)==526); assert(offset==1226576); } return 0; }')
p=out/'actual-helper.c';p.write_text(harness)
for name,flags in [('normal',[]),('sanitized',['-fsanitize=address,undefined','-fno-omit-frame-pointer'])]:
    exe=out/name
    subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',*flags,str(p),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
receipt=dict(passed=True,actual_patched_c_compiled=True,cases=len(cases)+1,asan_ubsan_passed=True,
    helper_sha256=hashlib.sha256(function.encode()).hexdigest(),source_sha256=hashlib.sha256((root/'executables/nr-ue.c').read_bytes()).hexdigest(),
    observed_failure_offset_samples=-2224,frame_sizes_checked=[614400,1228800],
    scope='Helper/SFN arithmetic and caller wiring; no PHY/radio outcome qualification',new_training_or_evaluation=False)
(out/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
