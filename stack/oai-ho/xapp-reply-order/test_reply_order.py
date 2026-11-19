"""Compile actual handlers with immediate-reply transport, and actual pthread wait code."""
from pathlib import Path
import hashlib,json,re,subprocess,sys

root=Path(sys.argv[1]);out=Path(sys.argv[2]);out.mkdir(exist_ok=False)
src=root/'src/xApp';patched=(src/'msg_handler_xapp.c').read_text()
original=subprocess.check_output(['git','-C',str(root),'show','HEAD:src/xApp/msg_handler_xapp.c'],text=True)
assert hashlib.sha256(original.encode()).hexdigest()=='5f236fc06af04bc515bac8fc76b3aaa40665888521cb4f886c64d501fd2aa3a3'
names=['e2ap_handle_e42_setup_request_xapp','e2ap_handle_e42_subscription_delete_request_xapp','e2ap_handle_e42_ric_control_request_xapp']
def extract(text,name):
    mark=text.index(name+'(');start=text.rfind('\n',0,mark)+1
    assert re.fullmatch(r'\s*e2ap_msg_t\s+',text[start:mark])
    begin=text.index('{',mark);depth=0
    for end in range(begin,len(text)):
        if text[end]=='{':depth+=1
        elif text[end]=='}':
            depth-=1
            if depth==0:return text[start:end+1]
    raise ValueError(name)
for call in ('send_subscription_request(xapp, id, ric_id, data);','send_ric_subscription_delete(xapp, ans.val.id);','send_control_request(xapp, id, ric_id, ctrl_msg);'):
    e42=(src/'e42_xapp.c').read_text();pos=e42.index(call)
    assert 'prepare_sync_ui(&xapp->sync);' in e42[max(0,pos-65):pos]
failure=extract(patched,'e2ap_handle_control_failure_xapp')
assert 'signal_failure_sync_ui(&xapp->sync);' in failure and 'signal_sync_ui(&xapp->sync);' not in failure

prefix=r'''
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#define assert(x) ((void)0)
#define defer(...) ((void)0)
#define CHECK(x) do { if (!(x)) exit(86); } while(0)
enum {E42_SETUP_REQUEST_PENDING_EVENT=1,E42_RIC_SUBSCRIPTION_DELETE_REQUEST_PENDING_EVENT,
 E42_RIC_CONTROL_REQUEST_PENDING_EVENT,E42_RIC_SUBSCRIPTION_DELETE_REQUEST,E42_RIC_CONTROL_REQUEST,NONE_E2_MSG_TYPE};
typedef struct {int ric_req_id,ran_func_id;} ric_gen_id_t;
typedef struct {int ev;ric_gen_id_t id;int wait_ms;} pending_event_xapp_t;
typedef struct {ric_gen_id_t ric_id;} request_t;
typedef struct {request_t sdr;} e42_ric_subscription_delete_request_t;
typedef struct {request_t ctrl_req;} e42_ric_control_request_t;
typedef struct {int len_rf;void *ran_func_item;} e42_setup_request_t;
typedef struct e42_xapp_s {int ap,ep;} e42_xapp_t;
typedef struct e2ap_msg_s {int type;union {e42_ric_subscription_delete_request_t e42_ric_sub_del_req;e42_ric_control_request_t e42_ric_ctrl_req;} u_msgs;} e2ap_msg_t;
typedef struct {size_t len;void *buf;} byte_array_t;
static int active,registered,sent,removed,mode,expected_ev,expected_wait;
static pending_event_xapp_t pending;
void add_pending_event_xapp(e42_xapp_t *x,pending_event_xapp_t *ev) {
 (void)x; CHECK(!active);CHECK(ev->ev==expected_ev && ev->wait_ms==expected_wait);
 pending=*ev;active=1;registered++;
}
void remove_reply(void) {CHECK(active);active=0;removed++;}
void e2ap_send_bytes_xapp(int *ep,byte_array_t ba) {
 (void)ep;CHECK(ba.len==8);CHECK(active && registered==1);sent++;
 if(mode==0) remove_reply();
}
e42_setup_request_t generate_e42_setup_request(e42_xapp_t *x) {(void)x;return (e42_setup_request_t){1,&active};}
byte_array_t e2ap_enc_e42_setup_request_xapp(int *a,e42_setup_request_t *r) {(void)a;(void)r;return (byte_array_t){8,0};}
byte_array_t e2ap_enc_e42_ric_subscription_delete_xapp(int *a,e42_ric_subscription_delete_request_t *r) {(void)a;CHECK(r->sdr.ric_id.ric_req_id==41);return (byte_array_t){8,0};}
byte_array_t e2ap_enc_e42_control_request_xapp(int *a,e42_ric_control_request_t *r) {(void)a;CHECK(r->ctrl_req.ric_id.ric_req_id==41);return (byte_array_t){8,0};}
'''
suffix=r'''
static void run_case(int which,int delivery) {
 active=registered=sent=removed=0;mode=delivery;
 expected_ev=which+1;expected_wait=which==0?1000:10000;
 e42_xapp_t x={0};e2ap_msg_t msg={0},answer;
 if(which==0) answer=e2ap_handle_e42_setup_request_xapp(&x,NULL);
 else if(which==1) {msg.type=E42_RIC_SUBSCRIPTION_DELETE_REQUEST;msg.u_msgs.e42_ric_sub_del_req.sdr.ric_id=(ric_gen_id_t){41,3};answer=e2ap_handle_e42_subscription_delete_request_xapp(&x,&msg);}
 else {msg.type=E42_RIC_CONTROL_REQUEST;msg.u_msgs.e42_ric_ctrl_req.ctrl_req.ric_id=(ric_gen_id_t){41,3};answer=e2ap_handle_e42_ric_control_request_xapp(&x,&msg);}
 CHECK(answer.type==NONE_E2_MSG_TYPE && registered==1 && sent==1);
 CHECK(pending.id.ric_req_id==(which==0?0:41));
 if(delivery==0) CHECK(!active && removed==1);
 else {CHECK(active && !removed); remove_reply();CHECK(!active && removed==1);}
}
int main(int argc,char **argv) {
 if(argc==2) {run_case(atoi(argv[1]),0);return 0;}
 for(int which=0;which<3;which++) for(int delivery=0;delivery<3;delivery++) run_case(which,delivery);
 return 0;
}
'''
for label,text in [('original',original),('patched',patched)]:
    p=out/(label+'-handlers.c');p.write_text(prefix+'\n'.join(extract(text,n) for n in names)+suffix)
    exe=out/(label+'-handlers')
    subprocess.run(['cc','-std=gnu11','-O2','-DNDEBUG','-Wall','-Wextra','-Werror','-Wno-unused-parameter',str(p),'-o',str(exe)],check=True)
    if label=='original':
        for which in range(3):assert subprocess.run([str(exe),str(which)],capture_output=True).returncode==86
    else:subprocess.run([str(exe)],check=True)

ui=r'''
#include "sync_ui.h"
#include <stdlib.h>
#include <unistd.h>
#include <sys/wait.h>
#include <time.h>
#define CHECK(x) do{if(!(x)) _exit(90);}while(0)
static double now(void) {struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec+t.tv_nsec/1e9;}
static void *later(void *s) {usleep(20000);signal_sync_ui(s);return NULL;}
int main(void) {
 sync_ui_t s;init_sync_ui(&s);
 for(int i=0;i<8;i++) {prepare_sync_ui(&s);CHECK(!s.flag_sync && !s.msg_ack);signal_sync_ui(&s);double t=now();cond_wait_sync_ui(&s,1000);CHECK(now()-t<0.5 && s.msg_ack);}
 prepare_sync_ui(&s);CHECK(!s.flag_sync && !s.msg_ack);pthread_t th;CHECK(!pthread_create(&th,NULL,later,&s));cond_wait_sync_ui(&s,1000);CHECK(!pthread_join(th,NULL));CHECK(s.msg_ack);
 for(int rejected=0;rejected<2;rejected++) {
  pid_t pid=fork();CHECK(pid>=0);
  if(pid==0) {prepare_sync_ui(&s);if(rejected)signal_failure_sync_ui(&s);cond_wait_sync_ui(&s,1);_exit(0);}
  int status;CHECK(waitpid(pid,&status,0)==pid);CHECK(WIFEXITED(status) && WEXITSTATUS(status)==EXIT_FAILURE);
 }
 free_sync_ui(&s);return 0;
}
'''
ui_file=out/'actual-ui.c';ui_file.write_text(ui)
for label,flags in [('normal',[]),('sanitized',['-fsanitize=address,undefined','-fno-omit-frame-pointer'])]:
    for kind,p,extra in [('handlers',out/'patched-handlers.c',[]),('ui',ui_file,[str(src/'sync_ui.c'),str(root/'src/util/alg_ds/alg/defer.c'),'-pthread','-I'+str(src)])]:
        exe=out/(kind+'-'+label)
        subprocess.run(['cc','-std=gnu11','-D_GNU_SOURCE','-O2','-DNDEBUG','-Wall','-Wextra','-Werror','-Wno-unused-parameter','-Wno-unused-variable','-Wno-unused-but-set-variable',*flags,str(p),*extra,'-o',str(exe)],check=True)
        subprocess.run([str(exe)],check=True)
receipt=dict(passed=True,actual_c_handlers_and_pthread_wait_compiled=True,
    immediate_delayed_and_absent_transport_cases=9,old_handlers_fail_immediate_ack_cases=3,
    early_delayed_missing_rejected_and_stale_reply_cases=5,asan_ubsan_passed=True,
    scope='Actual three modified handlers with stub transport/pending map; actual pthread wait implementation; not full RIC/ASN.1 sanitizer qualification',
    source_sha256={n:hashlib.sha256((src/n).read_bytes()).hexdigest() for n in ('msg_handler_xapp.c','e42_xapp.c','sync_ui.c','sync_ui.h')},
    new_training_or_evaluation=False)
(out/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
