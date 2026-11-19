"""Compile and exercise the actual patched C helper and idle-expiry block."""
from pathlib import Path
import subprocess,tempfile,json
import sys
root=Path(sys.argv[1])
out=Path(sys.argv[2]) if len(sys.argv)>2 else Path(tempfile.mkdtemp(prefix='horus-cfra-unit-'))
if len(sys.argv)>2:out.mkdir(exist_ok=False)
src=(root/'openair2/LAYER2/NR_MAC_gNB/gNB_scheduler_RA.c').read_text()
start=src.index('static bool horus_rearm_cfra_after_expired_msg2(');end=src.index('\n}\n',start)+3
helper=src[start:end]
start=src.index('    if (ra->cfra && ra->ra_state == nrRA_gNB_IDLE && ra->horus_cfra_retry_slots > 0')
end=src.index('    // Check RA Contention Resolution timer',start)
idle=src[start:end]
c='''#include <stdbool.h>
#include <assert.h>
#include <stdio.h>
#define LOG_W(...) ((void)0)
enum {nrRA_gNB_IDLE, nrRA_Msg2};
typedef struct {bool cfra; unsigned int horus_cfra_window_misses; int horus_cfra_retry_slots; int ra_state;} NR_RA_t;
typedef struct {NR_RA_t *ra; int rnti;} UE_t;
'''+helper+'''
static int schedule_idle(UE_t *UE) {
  int to_release[1]={0}; int num_release=0; NR_RA_t *ra=UE->ra;
  for(int once=0;once<1;once++) {
'''+idle+'''
  }
  return num_release ? to_release[0] : 0;
}
int main(void) {
  NR_RA_t cb={.cfra=false,.ra_state=nrRA_Msg2};
  assert(!horus_rearm_cfra_after_expired_msg2(&cb,20));
  assert(cb.ra_state==nrRA_Msg2 && cb.horus_cfra_window_misses==0 && cb.horus_cfra_retry_slots==0);
  for(int mu=0;mu<4;mu++) {
    int spf=10<<mu;
    NR_RA_t ra={.cfra=true,.ra_state=nrRA_Msg2};
    for(unsigned int retry=1;retry<=3;retry++) {
      assert(horus_rearm_cfra_after_expired_msg2(&ra,spf));
      assert(ra.horus_cfra_window_misses==retry && ra.ra_state==nrRA_gNB_IDLE);
      assert(ra.horus_cfra_retry_slots==100*spf);
      ra.ra_state=nrRA_Msg2; // a NEW preamble restores Msg2 in upstream initiation
    }
    assert(!horus_rearm_cfra_after_expired_msg2(&ra,spf));
    assert(ra.ra_state==nrRA_Msg2 && ra.horus_cfra_window_misses==3);
    ra=(NR_RA_t){.cfra=true,.ra_state=nrRA_Msg2};
    assert(horus_rearm_cfra_after_expired_msg2(&ra,spf));
    UE_t ue={.ra=&ra,.rnti=42};
    for(int slot=1;slot<100*spf;slot++) assert(schedule_idle(&ue)==0);
    assert(schedule_idle(&ue)==42); // finite no-preamble lifetime
    assert(schedule_idle(&ue)==0); // cannot queue release twice
    ra=(NR_RA_t){.cfra=true,.ra_state=nrRA_Msg2,.horus_cfra_retry_slots=1};
    assert(schedule_idle(&ue)==0 && ra.horus_cfra_retry_slots==1); // active RA retains timer rules
  }
  puts("PASS actual CFRA recovery helper: CBRA unchanged, three rearms, fourth releases, finite idle lifetime, active RA unchanged, four numerologies");
}
'''
(out/'actual-helper-test.c').write_text(c)
r=subprocess.run(['cc','-Wall','-Wextra','-Werror','-std=c11',str(out/'actual-helper-test.c'),'-o',str(out/'actual-helper-test')],capture_output=True,text=True)
(out/'compile.txt').write_text(r.stdout+r.stderr);assert r.returncode==0,r.stderr
r=subprocess.run([str(out/'actual-helper-test')],capture_output=True,text=True)
(out/'result.txt').write_text(r.stdout+r.stderr);assert r.returncode==0,r.stderr
(out/'receipt.json').write_text(json.dumps(dict(passed=True,actual_patched_c_compiled=True,new_training_or_evaluation=False))+'\n')
print(r.stdout)
