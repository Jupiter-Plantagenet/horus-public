#!/usr/bin/env python3
"""HORUS resilience patch 4 (2026-10-30): a RIC Control FAILURE must not kill the RIC.

Finals actuation sends real E2SM-RC controls to the srsRAN gNB. srsRAN answers a
control it cannot apply (e.g. unknown UE id) with RIC Control FAILURE. Stock
FlexRIC (br-flexric 7365081) aborts the near-RT RIC on that valid E2AP reply in
two places, which would drop the gNB's E2 for good (srsRAN never reconnects):

  1. e2ap_msg_dec_asn.c  e2ap_dec_control_failure(): `assert(0!=0 && "Untested
     code")` + strict criticality asserts (srsRAN's IE criticalities differ).
  2. msg_handler_ric.c   e2ap_handle_control_failure_ric(): `assert(0!=0 &&
     "not implemented")`.
  (+) msg_handler_ric.c  e2ap_handle_error_indication_ric(): same "Not
     Implemented" abort for an E2 Error Indication.

Fix: decode the failure without the untested/criticality asserts; in the RIC,
log it, stop the pending control timer and carry on. The failure is NOT
forwarded to the xApp (FlexRIC's iApp has no path for it); the xApp SDK times
out on the missing ACK and the HORUS actuator logs result "failed". Only error
paths are touched — E2 setup / KPM subscription / indication / control-ACK code
is unchanged. Each edit is guarded: the build fails if the anchor text moved.
"""
import re
import sys

ROOT = sys.argv[1] if len(sys.argv) > 1 else "/opt/flexric"


def span(src, sig):
    i = src.index(sig)
    j = src.index("\n}\n", i)
    return i, j


def patch_file(path, fn):
    with open(path) as f:
        src = f.read()
    new = fn(src)
    assert new != src, f"patch4: no change in {path}"
    with open(path, "w") as f:
        f.write(new)


def dec(src):
    i, j = span(src, "e2ap_msg_t e2ap_dec_control_failure(const E2AP_PDU_t* pdu)")
    body = src[i:j]
    assert 'assert(0!=0 && "Untested code");' in body
    body = body.replace('assert(0!=0 && "Untested code");',
                        '/* HORUS patch4: untested-code assert removed (srsRAN sends valid Control Failures) */')
    body, n = re.subn(r"\n\s*assert\([^;\n]*criticality[^;\n]*\);", "", body)
    assert n >= 1, "patch4: no criticality asserts found in e2ap_dec_control_failure"
    return src[:i] + body + src[j:]


def ric(src):
    i, j = span(src, "e2ap_msg_t e2ap_handle_control_failure_ric(near_ric_t* ric, const e2ap_msg_t* msg)")
    body = src[i:j]
    old = 'assert(0!=0 && "not implemented" );'
    assert old in body
    body = body.replace(old,
        "/* HORUS patch4: log + stop the pending control timer instead of aborting the RIC */\n"
        "  ric_control_failure_t const* cf = &msg->u_msgs.ric_ctrl_fail;\n"
        "  pending_event_ric_t ev = {.ev = CONTROL_REQUEST_PENDING_EVENT, .id = cf->ric_id };\n"
        "  stop_pending_event(ric, &ev);\n"
        "  printf(\"[NEAR-RIC]: CONTROL FAILURE rx (ran_func %d ric_req_id %d) - RIC continues\\n\",\n"
        "         cf->ric_id.ran_func_id, cf->ric_id.ric_req_id);\n"
        "  fflush(stdout);")
    src = src[:i] + body + src[j:]

    i, j = span(src, "e2ap_msg_t e2ap_handle_error_indication_ric(near_ric_t* ric, const e2ap_msg_t* msg)")
    body = src[i:j]
    old = 'assert(0 != 0 && "Not Implemented");'
    assert old in body
    body = body.replace(old, 'printf("[NEAR-RIC]: E2 ERROR INDICATION rx - ignored (HORUS patch4)\\n"); fflush(stdout);')
    return src[:i] + body + src[j:]


patch_file(f"{ROOT}/src/lib/e2ap/v2_03/dec/e2ap_msg_dec_asn.c", dec)
patch_file(f"{ROOT}/src/ric/msg_handler_ric.c", ric)
print("HORUS: patch4 applied - RIC survives RIC Control Failure / Error Indication")
