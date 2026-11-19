"""Fix observed early-ACK registration race and fail closed on lost/rejected replies."""
from pathlib import Path
import hashlib,json,re,sys

root=Path(sys.argv[1]);base=root/'src/xApp'
expected={'msg_handler_xapp.c':'5f236fc06af04bc515bac8fc76b3aaa40665888521cb4f886c64d501fd2aa3a3',
 'e42_xapp.c':'b76d0d6f05ba63ef3aed7e9bd98e067f383c506bf1751794f98dab8fe1fe9526',
 'sync_ui.c':'8b7e52dc932318384ecd534f99d6dfc301026623e66ca62ea7b09731398317a4',
 'sync_ui.h':'2c298f05a6e19340cc9c1f97193742c561f8542b1f5a189094a09ca2b2268d2b'}
for name,digest in expected.items():assert hashlib.sha256((base/name).read_bytes()).hexdigest()==digest,name

def function_span(text,name):
    marker=text.index(name+'(');start=text.rfind('\n',0,marker)+1
    assert re.fullmatch(r'\s*e2ap_msg_t\s+',text[start:marker]),name
    begin=text.index('{',marker);level=0
    for end in range(begin,len(text)):
        if text[end]=='{':level+=1
        elif text[end]=='}':
            level-=1
            if level==0:return start,end+1
    raise ValueError(name)

p=base/'msg_handler_xapp.c';s=p.read_text()
for name,wire,event in (
 ('e2ap_handle_e42_setup_request_xapp','  e2ap_send_bytes_xapp(&xapp->ep, ba);','  add_pending_event_xapp(xapp, &x_ev);'),
 ('e2ap_handle_e42_subscription_delete_request_xapp','  e2ap_send_bytes_xapp(&xapp->ep, ba_msg);','  add_pending_event_xapp(xapp, &ev);'),
 ('e2ap_handle_e42_ric_control_request_xapp','  e2ap_send_bytes_xapp(&xapp->ep, ba_msg);','  add_pending_event_xapp(xapp, &ev);')):
    start,end=function_span(s,name);body=s[start:end]
    assert body.count(wire)==body.count(event)==1 and body.index(wire)<body.index(event)
    body=body.replace(wire+'\n','',1)
    body=body.replace(event,event+'\n\n  /* Publish the request before a fast peer can reply. */\n'+wire,1)
    s=s[:start]+body+s[end:]
start,end=function_span(s,'e2ap_handle_control_failure_xapp');body=s[start:end]
assert body.count('signal_sync_ui(&xapp->sync);')==1
body=body.replace('signal_sync_ui(&xapp->sync);','signal_failure_sync_ui(&xapp->sync);')
s=s[:start]+body+s[end:];p.write_text(s)

p=base/'e42_xapp.c';s=p.read_text()
for call in ('send_subscription_request(xapp, id, ric_id, data);',
             'send_ric_subscription_delete(xapp, ans.val.id);',
             'send_control_request(xapp, id, ric_id, ctrl_msg);'):
    assert s.count(call)==1
    s=s.replace(call,'prepare_sync_ui(&xapp->sync);\n  '+call,1)
p.write_text(s)

p=base/'sync_ui.c';s=p.read_text()
s=s.replace('#include <pthread.h>','#include <pthread.h>\n#include <stdio.h>\n#include <stdlib.h>')
reset='''  s->flag_sync = false;
  s->msg_ack = false;
'''
wait_start=s.index('void cond_wait_sync_ui(')
reset_at=s.index(reset,wait_start)
s=s[:reset_at]+s[reset_at:].replace(reset,'',1)
old='''  assert(rc != ETIMEDOUT && "Timeout. No response from the E2 Node received, and neither from epoll. Unforeseen path");
  assert(rc == 0);

  pthread_mutex_unlock(&s->mtx_sync);

  assert(s->msg_ack == true && "No response to subscription from the RIC received\\n" );'''
new='''  const bool acknowledged = rc == 0 && s->flag_sync && s->msg_ack;
  pthread_mutex_unlock(&s->mtx_sync);
  if (!acknowledged) {
    fprintf(stderr, "HORUS: response absent, rejected or wait failed (%d); no acknowledgement claimed\\n", rc);
    exit(EXIT_FAILURE);
  }'''
assert s.count(old)==1
s=s.replace(old,new)
marker='void cond_wait_sync_ui(sync_ui_t* s, uint32_t wait_ms)'
assert s.count(marker)==1
s=s.replace(marker,'''void prepare_sync_ui(sync_ui_t* s)
{
  assert(s != NULL);
  lock_guard(&s->mtx_sync);
  s->flag_sync = false;
  s->msg_ack = false;
}

'''+marker)
s+='''
void signal_failure_sync_ui(sync_ui_t* s)
{
  assert(s != NULL);
  lock_guard(&s->mtx_sync);
  s->flag_sync = true;
  s->msg_ack = false;
  pthread_cond_signal(&s->cv_sync);
}
'''
p.write_text(s)
p=base/'sync_ui.h';s=p.read_text();assert s.count('void cond_wait_sync_ui(')==1
s=s.replace('void cond_wait_sync_ui(','void prepare_sync_ui(sync_ui_t* s);\n\nvoid signal_failure_sync_ui(sync_ui_t* s);\n\nvoid cond_wait_sync_ui(',1);p.write_text(s)
receipt=dict(flexric_tag='v3.0.0',experimental=True,qualified=False,
    observed_crash='CONTROL ACK removes pending event before sender registers it; assoc_rb_tree minimum(NULL)',
    scope='Register setup/delete/control pending events before TX; arm synchronous reply state before each request; preserve early ACKs; reject CONTROL FAILURE and missing replies',
    original_timeouts_preserved=True,model_gate_radio_security_bandwidth_cu_proof_unchanged=True,
    files={name:dict(before_sha256=digest,after_sha256=hashlib.sha256((base/name).read_bytes()).hexdigest()) for name,digest in expected.items()})
(root/'horus-xapp-reply-order-patch.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
