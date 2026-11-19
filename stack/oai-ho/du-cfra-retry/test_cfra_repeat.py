"""Compile actual retry lookup/retain/retire/expiry C code with list stubs."""
from pathlib import Path
import json,subprocess,sys,tempfile
root=Path(sys.argv[1]);out=Path(sys.argv[2]) if len(sys.argv)>2 else Path(tempfile.mkdtemp(prefix='horus-cfra-repeat-test-'))
if len(sys.argv)>2:out.mkdir(exist_ok=False)
base=root/'openair2/LAYER2/NR_MAC_gNB'
ra=(base/'gNB_scheduler_RA.c').read_text();pr=(base/'gNB_scheduler_primitives.c').read_text();ul=(base/'gNB_scheduler_ulsch.c').read_text()
def function(s,anchor):
    start=s.index(anchor);return s[start:s.index('\n}\n',start)+3]
lookup=function(ra,'static NR_UE_info_t *get_existing_ra(')
start=pr.index('  /* CFRA Msg3 callback may be a NACK:');retain=pr[start:pr.index('\n  return add_connected_nr_ue',start)]
start=ul.index('    if (sduP != NULL && sdu_lenP > 0 && UE->horus_cfra_replay != NULL)');retire=ul[start:ul.index('    // if not missed detection',start)]
start=ra.index('  UE_iterator(mac->UE_info.connected_ue_list, UE)',ra.index('void nr_schedule_RA('));expiry=ra[start:ra.index('  // releasing a UE modifies access_ue_list',start)]
c='''#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#define NR_NB_RA_PROC_MAX 4
#define MAX_MOBILES_PER_GNB 4
#define DevAssert(x) assert(x)
#define LOG_W(...) ((void)0)
static int frees;
#define free_and_zero(p) do {if(p){free(p);p=NULL;frees++;}} while(0)
typedef struct {struct {int num_preambles;int preamble_list[2];} preambles;bool cfra;unsigned int horus_cfra_window_misses;int horus_cfra_retry_slots;} NR_RA_t;
typedef struct {struct {int numb_slots_frame;} frame_structure;} nr_cell_sched_t;
typedef struct {NR_RA_t *ra;NR_RA_t *horus_cfra_replay;nr_cell_sched_t *pcell;int rnti;} NR_UE_info_t;
typedef struct {struct {NR_UE_info_t *access_ue_list[5];NR_UE_info_t *connected_ue_list[5];} UE_info;} gNB_MAC_INST;
#define UE_iterator(list,UE) for(int _i=0;_i<4 && (list)[_i];_i++) for(NR_UE_info_t *UE=(list)[_i];UE;UE=NULL)
static bool force_full;
static bool add_new_UE_RA(gNB_MAC_INST *mac,NR_UE_info_t *UE){assert(UE->ra);if(force_full)return false;for(int i=0;i<4;i++)if(!mac->UE_info.access_ue_list[i]){mac->UE_info.access_ue_list[i]=UE;return true;}return false;}
static NR_UE_info_t *remove_UE_from_list(int size,NR_UE_info_t **list,int rnti){for(int i=0;i<size && list[i];i++)if(list[i]->rnti==rnti){NR_UE_info_t *u=list[i];for(int j=i;j<size-1;j++)list[j]=list[j+1];list[size-1]=NULL;return u;}return NULL;}
'''+lookup+'''
static void retain_context(NR_UE_info_t *UE){
'''+retain+'''
}
static void retire_context(NR_UE_info_t *UE,void *sduP,unsigned int sdu_lenP){
'''+retire+'''
}
static void expire_context(gNB_MAC_INST *mac,nr_cell_sched_t *cell){
'''+expiry+'''
}
static NR_RA_t *make_ra(void){NR_RA_t *p=calloc(1,sizeof(*p));assert(p);p->cfra=true;p->preambles.num_preambles=1;p->preambles.preamble_list[0]=63;return p;}
int main(void){
 nr_cell_sched_t cell={.frame_structure.numb_slots_frame=20},other={.frame_structure.numb_slots_frame=20};
 gNB_MAC_INST mac={0};NR_UE_info_t ue={.pcell=&cell,.rnti=42};
 ue.ra=make_ra();NR_RA_t *p=ue.ra;
 retain_context(&ue);assert(!ue.ra && ue.horus_cfra_replay==p && p->horus_cfra_retry_slots==2000);
 mac.UE_info.connected_ue_list[0]=&ue;
 assert(!get_existing_ra(&mac,&other,63));assert(!get_existing_ra(&mac,&cell,62));
 assert(ue.horus_cfra_replay==p && !ue.ra && mac.UE_info.connected_ue_list[0]==&ue);
 force_full=true;assert(!get_existing_ra(&mac,&cell,63));force_full=false;
 assert(!ue.ra && ue.horus_cfra_replay==p && p->horus_cfra_window_misses==0 && mac.UE_info.connected_ue_list[0]==&ue);
 assert(get_existing_ra(&mac,&cell,63)==&ue);
 assert(ue.ra==p && !ue.horus_cfra_replay && p->horus_cfra_window_misses==1 && p->horus_cfra_retry_slots==0);
 assert(mac.UE_info.access_ue_list[0]==&ue && !mac.UE_info.connected_ue_list[0]);
 assert(get_existing_ra(&mac,&cell,63)==&ue && p->horus_cfra_window_misses==1); // active RA takes precedence
 mac=(gNB_MAC_INST){0};retain_context(&ue);mac.UE_info.connected_ue_list[0]=&ue;
 retire_context(&ue,NULL,1);retire_context(&ue,&mac,0);assert(ue.horus_cfra_replay==p);
 int old_frees=frees;retire_context(&ue,&mac,1);assert(!ue.horus_cfra_replay && frees==old_frees+1);
 retire_context(&ue,&mac,1);assert(frees==old_frees+1);
 ue.ra=make_ra();p=ue.ra;retain_context(&ue);
 for(int i=0;i<1999;i++){expire_context(&mac,&other);assert(p->horus_cfra_retry_slots==2000);}
 for(int i=0;i<1999;i++)expire_context(&mac,&cell);
 assert(ue.horus_cfra_replay==p && p->horus_cfra_retry_slots==1);
 old_frees=frees;expire_context(&mac,&cell);assert(!ue.horus_cfra_replay && frees==old_frees+1);
 expire_context(&mac,&cell);assert(frees==old_frees+1);
 ue.ra=make_ra();ue.ra->horus_cfra_window_misses=3;old_frees=frees;retain_context(&ue);assert(!ue.ra && !ue.horus_cfra_replay && frees==old_frees+1);
 ue.ra=make_ra();ue.ra->cfra=false;old_frees=frees;retain_context(&ue);assert(!ue.ra && !ue.horus_cfra_replay && frees==old_frees+1);
 ue.horus_cfra_replay=make_ra();p=ue.horus_cfra_replay;p->horus_cfra_retry_slots=20;p->horus_cfra_window_misses=3;
 assert(!get_existing_ra(&mac,&cell,63));p->horus_cfra_window_misses=0;p->horus_cfra_retry_slots=0;
 assert(!get_existing_ra(&mac,&cell,63));p->horus_cfra_retry_slots=20;p->cfra=false;
 assert(!get_existing_ra(&mac,&cell,63));free_and_zero(ue.horus_cfra_replay);
 puts("PASS actual CFRA lifecycle C: exclusive list/pointer ownership, matching cell/preamble, full-list rollback, retry budget, valid-UL retirement, finite expiry, CBRA unchanged, no double free");
}
'''
(out/'actual-lifecycle-test.c').write_text(c)
r=subprocess.run(['cc','-Wall','-Wextra','-Werror','-std=c11',str(out/'actual-lifecycle-test.c'),'-o',str(out/'actual-lifecycle-test')],capture_output=True,text=True)
(out/'compile.txt').write_text(r.stdout+r.stderr);assert r.returncode==0,r.stderr
r=subprocess.run([str(out/'actual-lifecycle-test')],capture_output=True,text=True)
(out/'result.txt').write_text(r.stdout+r.stderr);assert r.returncode==0,r.stderr
san=subprocess.run(['cc','-Wall','-Wextra','-Werror','-std=c11','-fsanitize=address,undefined','-fno-omit-frame-pointer',str(out/'actual-lifecycle-test.c'),'-o',str(out/'actual-lifecycle-test-sanitized')],capture_output=True,text=True)
assert san.returncode==0,san.stderr
san=subprocess.run([str(out/'actual-lifecycle-test-sanitized')],capture_output=True,text=True)
(out/'sanitizer.txt').write_text(san.stdout+san.stderr);assert san.returncode==0,san.stderr
(out/'receipt.json').write_text(json.dumps(dict(passed=True,actual_patched_c_compiled=True,address_and_undefined_sanitizers_passed=True,new_training_or_evaluation=False))+'\n')
print(r.stdout)
