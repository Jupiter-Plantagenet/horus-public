/*
 * HORUS RC actuation xApp — E2SM-RC Control Service Style 2 ("Radio Resource
 * Allocation Control"), Control Action 6 ("Slice-level PRB quota"), sent through
 * FlexRIC to the srsRAN gNB over E2.
 *
 * Long-lived: connects to the near-RT RIC once (E42), then reads one command per
 * line on stdin and answers one line on stdout, so the Python controller
 * (stack/actuation/horus_actuator.py) can issue controls with no per-control
 * connection setup:
 *
 *   in : CTRL <req_id> <f1ap_ue_id> <max_prb> <sst> <sd>
 *   out: ACK  <req_id> <latency_us>          (RIC Control Acknowledge received)
 *        ERR  <req_id> <reason>              (not sent: bad command / no node)
 *   out: READY <n_e2_nodes>                  (once, after E42 setup)
 *
 * A RIC Control FAILURE from the gNB is not forwarded to xApps by FlexRIC (the
 * xApp SDK aborts on the missing ACK after ~5 s); the controller treats a dead
 * xApp / no ACK as result "failed" and restarts this process. The near-RT RIC
 * itself is patched (flexric/patches/patch4_rc_ctrl_failure.py) so a Control
 * Failure never takes the RIC — and the gNB's E2 — down.
 *
 * Message layout (O-RAN E2SM-RC v1 §8.4.3.6), as srsRAN 24_04 parses it
 * (lib/e2/e2sm/e2sm_rc/e2sm_rc_control_action_du_executor.cpp):
 *   RRM Policy Ratio List (1)            LIST
 *   > [group]                            STRUCTURE
 *   >> RRM Policy (3)                    STRUCTURE
 *   >>> RRM Policy Member List (5)       LIST
 *   >>>> [member]                        STRUCTURE
 *   >>>>> PLMN Identity (7)              ELEMENT
 *   >>>>> S-NSSAI (8)                    STRUCTURE { SST (9), SD (10) }
 *   >> Max PRB Policy Ratio (12)         ELEMENT
 * Min PRB Policy Ratio (11) is deliberately NOT sent: srsRAN 24_04 pushes 11 and
 * 12 as separate param-list entries and applies only param_list[0]
 * (du_ue_ric_configuration_procedure.cpp), so sending Min first would silently
 * drop the Max cap. 24_04 applies the value to the addressed UE as its PDSCH
 * grant-size limit {0, max} in PRBs (cell = 106 PRB).
 */
#include "../../../../src/xApp/e42_xapp_api.h"
#include "../../../../src/sm/rc_sm/ie/ir/ran_param_struct.h"
#include "../../../../src/sm/rc_sm/ie/ir/ran_param_list.h"
#include "../../../../src/util/time_now_us.h"
#include "../../../../src/sm/rc_sm/rc_sm_id.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static const char* PLMN = "99970";   /* MCC 999 / MNC 70 — matches core + gNB */

static void elem_str(seq_ran_param_t* p, uint32_t id, const char* s)
{
  p->ran_param_id = id;
  p->ran_param_val.type = ELEMENT_KEY_FLAG_FALSE_RAN_PARAMETER_VAL_TYPE;
  p->ran_param_val.flag_false = calloc(1, sizeof(ran_parameter_value_t));
  assert(p->ran_param_val.flag_false != NULL);
  p->ran_param_val.flag_false->type = OCTET_STRING_RAN_PARAMETER_VALUE;
  byte_array_t ba = cp_str_to_ba(s);
  p->ran_param_val.flag_false->octet_str_ran.len = ba.len;
  p->ran_param_val.flag_false->octet_str_ran.buf = ba.buf;
}

static void elem_int(seq_ran_param_t* p, uint32_t id, int64_t v)
{
  p->ran_param_id = id;
  p->ran_param_val.type = ELEMENT_KEY_FLAG_FALSE_RAN_PARAMETER_VAL_TYPE;
  p->ran_param_val.flag_false = calloc(1, sizeof(ran_parameter_value_t));
  assert(p->ran_param_val.flag_false != NULL);
  p->ran_param_val.flag_false->type = INTEGER_RAN_PARAMETER_VALUE;
  p->ran_param_val.flag_false->int_ran = v;
}

static seq_ran_param_t* strct(seq_ran_param_t* p, uint32_t id, size_t n)
{
  p->ran_param_id = id;
  p->ran_param_val.type = STRUCTURE_RAN_PARAMETER_VAL_TYPE;
  p->ran_param_val.strct = calloc(1, sizeof(ran_param_struct_t));
  assert(p->ran_param_val.strct != NULL);
  p->ran_param_val.strct->sz_ran_param_struct = n;
  p->ran_param_val.strct->ran_param_struct = calloc(n, sizeof(seq_ran_param_t));
  assert(p->ran_param_val.strct->ran_param_struct != NULL);
  return p->ran_param_val.strct->ran_param_struct;
}

static lst_ran_param_t* lst(seq_ran_param_t* p, uint32_t id, size_t n)
{
  p->ran_param_id = id;
  p->ran_param_val.type = LIST_RAN_PARAMETER_VAL_TYPE;
  p->ran_param_val.lst = calloc(1, sizeof(ran_param_list_t));
  assert(p->ran_param_val.lst != NULL);
  p->ran_param_val.lst->sz_lst_ran_param = n;
  p->ran_param_val.lst->lst_ran_param = calloc(n, sizeof(lst_ran_param_t));
  assert(p->ran_param_val.lst->lst_ran_param != NULL);
  return p->ran_param_val.lst->lst_ran_param;
}

static seq_ran_param_t* item(lst_ran_param_t* it, size_t n)
{
  it->ran_param_struct.sz_ran_param_struct = n;
  it->ran_param_struct.ran_param_struct = calloc(n, sizeof(seq_ran_param_t));
  assert(it->ran_param_struct.ran_param_struct != NULL);
  return it->ran_param_struct.ran_param_struct;
}

static rc_ctrl_req_data_t build_ctrl(uint64_t f1ap_ue_id, int max_prb, const char* sst, const char* sd)
{
  rc_ctrl_req_data_t rc = {0};

  /* Header format 1: UE id + style 2 + action 6 */
  rc.hdr.format = FORMAT_1_E2SM_RC_CTRL_HDR;
  ue_id_e2sm_t ue = {0};
  ue.type = GNB_DU_UE_ID_E2SM;
  ue.gnb_du.gnb_cu_ue_f1ap = f1ap_ue_id;
  rc.hdr.frmt_1.ue_id = cp_ue_id_e2sm(&ue);
  rc.hdr.frmt_1.ric_style_type = 2;
  rc.hdr.frmt_1.ctrl_act_id = Slice_level_PRB_quotal_7_6_3_1;

  /* Message format 1 */
  rc.msg.format = FORMAT_1_E2SM_RC_CTRL_MSG;
  rc.msg.frmt_1.sz_ran_param = 1;
  rc.msg.frmt_1.ran_param = calloc(1, sizeof(seq_ran_param_t));
  assert(rc.msg.frmt_1.ran_param != NULL);

  lst_ran_param_t* groups = lst(&rc.msg.frmt_1.ran_param[0], RRM_Policy_Ratio_List_8_4_3_6, 1);
  seq_ran_param_t* g = item(&groups[0], 2);
  seq_ran_param_t* pol = strct(&g[0], RRM_Policy_8_4_3_6, 1);
  lst_ran_param_t* members = lst(&pol[0], RRM_Policy_Member_List_8_4_3_6, 1);
  seq_ran_param_t* m = item(&members[0], 2);
  elem_str(&m[0], PLMN_Identity_8_4_3_6, PLMN);
  seq_ran_param_t* nssai = strct(&m[1], S_NSSAI_8_4_3_6, 2);
  elem_str(&nssai[0], SST_8_4_3_6, sst);
  elem_str(&nssai[1], SD_8_4_3_6, sd);
  elem_int(&g[1], Max_PRB_Policy_Ratio_8_4_3_6, max_prb);
  return rc;
}

static int rc_node(e2_node_arr_xapp_t* nodes)
{
  for (size_t i = 0; i < nodes->len; ++i)
    for (size_t j = 0; j < nodes->n[i].len_rf; ++j)
      if (nodes->n[i].rf[j].id == SM_RC_ID)
        return (int)i;
  return -1;
}

int main(int argc, char* argv[])
{
  setvbuf(stdout, NULL, _IOLBF, 0);
  fr_args_t args = init_fr_args(argc, argv);
  init_xapp_api(&args);
  sleep(1);

  e2_node_arr_xapp_t nodes = e2_nodes_xapp_api();
  for (int w = 0; w < 60 && nodes.len == 0; ++w) {
    free_e2_node_arr_xapp(&nodes);
    sleep(1);
    nodes = e2_nodes_xapp_api();
  }
  printf("READY %d\n", nodes.len);

  char line[512];
  while (fgets(line, sizeof line, stdin) != NULL) {
    char cmd[16] = {0}, req[64] = {0}, sst[16] = {0}, sd[16] = {0};
    unsigned long long ue_id = 0;
    int max_prb = -1;
    int n = sscanf(line, "%15s %63s %llu %d %15s %15s", cmd, req, &ue_id, &max_prb, sst, sd);
    if (n < 1 || strcmp(cmd, "QUIT") == 0) break;
    if (strcmp(cmd, "NODES") == 0) {
      free_e2_node_arr_xapp(&nodes);
      nodes = e2_nodes_xapp_api();
      printf("NODES %d\n", nodes.len);
      continue;
    }
    if (strcmp(cmd, "CTRL") != 0 || n < 6 || max_prb < 0) {
      printf("ERR %s bad-command\n", n >= 2 ? req : "-");
      continue;
    }
    free_e2_node_arr_xapp(&nodes);
    nodes = e2_nodes_xapp_api();
    int idx = rc_node(&nodes);
    if (idx < 0) {
      printf("ERR %s no-e2-node-with-rc\n", req);
      continue;
    }
    rc_ctrl_req_data_t rc = build_ctrl(ue_id, max_prb, sst, sd);
    int64_t t0 = time_now_us();
    sm_ans_xapp_t ans = control_sm_xapp_api(&nodes.n[idx].id, SM_RC_ID, &rc);
    int64_t dt = time_now_us() - t0;
    free_rc_ctrl_req_data(&rc);
    if (ans.success)
      printf("ACK %s %ld\n", req, (long)dt);
    else
      printf("ERR %s control-not-acked\n", req);
  }

  free_e2_node_arr_xapp(&nodes);
  while (try_stop_xapp_api() == false)
    usleep(1000);
  return 0;
}
