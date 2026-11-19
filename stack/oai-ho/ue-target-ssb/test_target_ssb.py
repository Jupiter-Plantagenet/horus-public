from pathlib import Path
import subprocess,re,json
import sys,tempfile
root=Path(sys.argv[1]);out=Path(sys.argv[2]) if len(sys.argv)>2 else Path(tempfile.mkdtemp(prefix='horus-target-ssb-test-'))
if len(sys.argv)>2:out.mkdir(exist_ok=False)
src=(root/'openair2/LAYER2/NR_MAC_UE/nr_ra_procedures.c').read_text()
start=src.index('static bool horus_select_single_cfra_target(');end=src.index('\n}\n',start)+3;helper=src[start:end]
c='''#include <stdbool.h>
#include <assert.h>
#include <stddef.h>
#include <stdio.h>
#define MAX_NB_SSB 64
#define LOG_W(...) ((void)0)
typedef struct {long ssb; long ra_PreambleIndex;} NR_CFRA_SSB_Resource_t;
struct NR_CFRA__resources__ssb {struct {struct {int count; NR_CFRA_SSB_Resource_t **array;} list;} ssb_ResourceList; long ra_ssb_OccasionMaskIndex;};
typedef struct {struct {int nb_tx_ssb; int nb_ssb_per_index[64];} ssb_list; struct {int ra_PreambleIndex; int ro_mask_index;} ra; int mib_ssb;} NR_UE_MAC_INST_t;
'''+helper+'''
int main(void) {
 NR_UE_MAC_INST_t mac={.ssb_list.nb_tx_ssb=1,.mib_ssb=2,.ra.ra_PreambleIndex=7,.ra.ro_mask_index=-1};
 for(int i=0;i<64;i++)mac.ssb_list.nb_ssb_per_index[i]=-1;
 mac.ssb_list.nb_ssb_per_index[1]=0;
 NR_CFRA_SSB_Resource_t res={.ssb=1,.ra_PreambleIndex=63};
 NR_CFRA_SSB_Resource_t *array[1]={&res};
 struct NR_CFRA__resources__ssb list={.ssb_ResourceList.list.count=1,.ssb_ResourceList.list.array=array,.ra_ssb_OccasionMaskIndex=0};
 int ssb=-1; assert(horus_select_single_cfra_target(&mac,&list,&ssb));
 assert(ssb==1 && mac.ra.ra_PreambleIndex==63 && mac.ra.ro_mask_index==0 && mac.mib_ssb==2);
 mac.ra.ra_PreambleIndex=7; ssb=1;
 assert(!horus_select_single_cfra_target(&mac,&list,&ssb));assert(mac.ra.ra_PreambleIndex==7);
 ssb=-1; mac.ssb_list.nb_tx_ssb=2; assert(!horus_select_single_cfra_target(&mac,&list,&ssb)); mac.ssb_list.nb_tx_ssb=1;
 list.ssb_ResourceList.list.count=2; assert(!horus_select_single_cfra_target(&mac,&list,&ssb));list.ssb_ResourceList.list.count=1;
 list.ssb_ResourceList.list.count=0; assert(!horus_select_single_cfra_target(&mac,&list,&ssb));list.ssb_ResourceList.list.count=1;
 array[0]=NULL;assert(!horus_select_single_cfra_target(&mac,&list,&ssb));array[0]=&res;
 res.ssb=-1;assert(!horus_select_single_cfra_target(&mac,&list,&ssb));
 res.ssb=64;assert(!horus_select_single_cfra_target(&mac,&list,&ssb));
 res.ssb=2;assert(!horus_select_single_cfra_target(&mac,&list,&ssb)); // inactive target
 res.ssb=1;mac.ssb_list.nb_ssb_per_index[1]=1;assert(!horus_select_single_cfra_target(&mac,&list,&ssb));
 assert(ssb==-1 && mac.ra.ra_PreambleIndex==7 && mac.mib_ssb==2);
 puts("PASS actual target-SSB C helper: sole active authorized target, preserve MIB, existing match, multiple/empty/null/invalid/inactive refusal");
}
'''
(out/'actual-helper-test.c').write_text(c)
r=subprocess.run(['cc','-Wall','-Wextra','-Werror','-std=c11',str(out/'actual-helper-test.c'),'-o',str(out/'actual-helper-test')],capture_output=True,text=True)
(out/'compile.txt').write_text(r.stdout+r.stderr);assert r.returncode==0,r.stderr
r=subprocess.run([str(out/'actual-helper-test')],capture_output=True,text=True)
(out/'result.txt').write_text(r.stdout+r.stderr);assert r.returncode==0,r.stderr
(out/'receipt.json').write_text(json.dumps(dict(passed=True,actual_patched_c_compiled=True,new_training_or_evaluation=False))+'\n')
print(r.stdout)
