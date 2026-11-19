
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
e2ap_msg_t e2ap_handle_e42_setup_request_xapp(struct e42_xapp_s* xapp, const struct e2ap_msg_s* msg)
{
  assert(xapp != NULL);
  assert(msg == NULL && "Not accepting any msg");

  e42_setup_request_t sr = generate_e42_setup_request(xapp); 
  defer({ e2ap_free_e42_setup_request(&sr);  } );

  assert(sr.len_rf > 0);
  assert(sr.ran_func_item != NULL);

  byte_array_t ba = e2ap_enc_e42_setup_request_xapp(&xapp->ap, &sr); 
  defer({free_byte_array(ba); } ); 

  e2ap_send_bytes_xapp(&xapp->ep, ba);

  printf("[xApp]: E42 SETUP-REQUEST tx\n");

  // A pending event is created along with a timer of 1000 ms,
  // after which an event will be triggered
  pending_event_xapp_t x_ev = {.ev = E42_SETUP_REQUEST_PENDING_EVENT,
                                .wait_ms = 1000,
                               .id = {0} }; 
  add_pending_event_xapp(xapp, &x_ev);

  e2ap_msg_t ans = {.type = NONE_E2_MSG_TYPE };
  return ans;
}
e2ap_msg_t e2ap_handle_e42_subscription_delete_request_xapp(e42_xapp_t* xapp, const e2ap_msg_t* msg)
{
  assert(xapp != NULL);
  assert(msg != NULL);
  assert(msg->type == E42_RIC_SUBSCRIPTION_DELETE_REQUEST);

  const e42_ric_subscription_delete_request_t* e42_sdr = &msg->u_msgs.e42_ric_sub_del_req;
  printf("[xApp]: E42 RIC_SUBSCRIPTION_DELETE_REQUEST tx RAN_FUNC_ID %d RIC_REQ_ID %d \n", e42_sdr->sdr.ric_id.ran_func_id, e42_sdr->sdr.ric_id.ric_req_id);

  byte_array_t ba_msg = e2ap_enc_e42_ric_subscription_delete_xapp(&xapp->ap,( e42_ric_subscription_delete_request_t* ) e42_sdr);
  defer({ free_byte_array(ba_msg) ;}; );

  e2ap_send_bytes_xapp(&xapp->ep, ba_msg);

  // A pending event is created along with a timer of 10000 ms,
  // after which an event will be generated
  pending_event_xapp_t ev = {.ev = E42_RIC_SUBSCRIPTION_DELETE_REQUEST_PENDING_EVENT, 
                              .id = e42_sdr->sdr.ric_id,
                              .wait_ms = 10000};
  add_pending_event_xapp(xapp, &ev);


  e2ap_msg_t ans = {.type = NONE_E2_MSG_TYPE};
  return ans; 
}
e2ap_msg_t e2ap_handle_e42_ric_control_request_xapp(e42_xapp_t* xapp, const e2ap_msg_t* msg)
{
  assert(xapp != NULL);
  assert(msg != NULL);
  assert(msg->type == E42_RIC_CONTROL_REQUEST);

  const e42_ric_control_request_t* cr = &msg->u_msgs.e42_ric_ctrl_req;

  byte_array_t ba_msg = e2ap_enc_e42_control_request_xapp(&xapp->ap,(  e42_ric_control_request_t* ) cr);
  defer({ free_byte_array(ba_msg) ;}; );

  e2ap_send_bytes_xapp(&xapp->ep, ba_msg);

  printf("[xApp]: CONTROL-REQUEST tx \n");

  pending_event_xapp_t ev = {.ev = E42_RIC_CONTROL_REQUEST_PENDING_EVENT,
    .id = cr->ctrl_req.ric_id,
    .wait_ms = 10000};
  add_pending_event_xapp(xapp, &ev);


  e2ap_msg_t ans = {.type = NONE_E2_MSG_TYPE};
  return ans;
}
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
