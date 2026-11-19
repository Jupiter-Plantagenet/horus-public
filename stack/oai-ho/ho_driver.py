#!/usr/bin/env python3
"""HORUS twin-in-the-loop HANDOVER driver: the promoted policy decides, the real RAN hands over.

    HORUS digital twin (campus radio map, a UE walking the corner_turner route)
      -> gate-promoted DQN policy from the A1 store decides "hand over now"
      -> E2SM-RC CONTROL Style 3 / Action 1 (Handover Control) via FlexRIC
         (upstream xapp_rc_handover, run inside the RIC container)
      -> OAI CU executes a real 3GPP F1 handover of the OAI nrUE to the other DU
      -> verified independently at the CU (telnet `ci fetch_du_by_ue_id`)
      -> one line per executed handover in working/actuation/actions.jsonl

Honest scope (also written into every record):
  * RSRP that drives the decision comes from the twin (rfsim has no path loss,
    so the live UE measures nothing that could motivate a handover). The live
    testbed has 2 cells (DU 3584 / DU 3585); the twin has the campus sites.
    Each twin decision is executed as a real F1 handover to the OTHER live DU.
  * latency_ms = policy decision -> handover confirmed at the CU (serving DU
    changed). The xApp's own E42 setup + RC On-Demand report are inside it.

Run on the WSL host (needs docker CLI); the DQN needs the ML venv:
    ~/horus-ml/bin/python stack/oai-ho/ho_driver.py --max-hos 3
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO / "pipeline"))
sys.path.insert(0, str(REPO / "stack"))

CU = ("192.168.71.150", 9090)
XAPP = "/usr/local/flexric/xApp/c/rc_handover/xapp_horus_ho"
DU_CELL = {"3584": "12345678", "3585": "11111111"}   # gNB-DU id -> nr_cellid (compose)


def iso(t=None):
    t = time.time() if t is None else t
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def log(msg):
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] [ho-driver] {msg}", flush=True)


def ci(cmd):
    out = subprocess.run([sys.executable, str(HERE / "ci_cmd.py"), CU[0], str(CU[1]), cmd],
                         capture_output=True, text=True, timeout=20)
    return out.stdout


def active_ue():
    """CU UE ID of the UE that has an established PDU session (CU RRC stats).
    The CU can hold stale contexts from failed RA attempts on a slow box; those
    have no PDU session and are never the handover subject."""
    try:
        txt = subprocess.run(["docker", "exec", "ho-cu", "cat", "nrRRC_stats.log"],
                             capture_output=True, text=True, timeout=20).stdout
    except subprocess.TimeoutExpired:
        return None
    cur, best = None, None
    for ln in txt.splitlines():
        m = re.match(r"UE \d+ CU UE ID (\d+)", ln)
        if m:
            cur = int(m.group(1))
        elif cur is not None and "PDU session" in ln and "established" in ln:
            best = cur
    return best


_UE = {"id": None}


def serving_du():
    if _UE["id"] is None:
        _UE["id"] = active_ue()
    txt = ci(f"ci fetch_du_by_ue_id {_UE['id']}" if _UE["id"] else "ci fetch_du_by_ue_id")
    m = re.findall(r"\b(3584|3585)\b", txt)
    return (m[-1] if m else None), txt.strip()


def active_policy(store):
    try:
        import policy_store
        v, art = policy_store.select_active(str(store))
        return v, art
    except Exception:
        return None, None


def append(path, rec):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
        f.flush()


def rrc_snapshot():
    """Protocol events from this CU instance, independently of its early DU map.

    OAI changes the DU association before RRCReconfigurationComplete arrives.
    A locator change alone must therefore never certify a completed handover.
    Event times are CU log order markers, not acquisition/receipt timestamps.
    """
    try:
        identity = subprocess.run(['docker','inspect','-f','{{.Id}}','ho-cu'],
                                  capture_output=True,text=True,timeout=5)
        logs = subprocess.run(['docker','logs','--tail','1000','ho-cu'],
                              capture_output=True,text=True,timeout=5)
        if identity.returncode or logs.returncode or not identity.stdout.strip():
            return None
    except (OSError,subprocess.TimeoutExpired):
        return None
    events=[]
    for line in (logs.stdout+'\n'+logs.stderr).splitlines():
        start=re.search(r'(\d+\.\d+)\s+\[NR_RRC\].*Handover triggered for UE (\d+)/RNTI [0-9a-f]+ towards cell (\d+)',line,re.I)
        done=re.search(r'(\d+\.\d+)\s+\[NR_RRC\].*handover for UE (\d+)/RNTI [0-9a-f]+ complete!',line,re.I)
        if start:events.append(dict(t=float(start[1]),ue=int(start[2]),kind='trigger',cell=start[3]))
        elif done:events.append(dict(t=float(done[1]),ue=int(done[2]),kind='complete'))
    return dict(container_id=identity.stdout.strip(),events=events)


def completed_rrc_handover(before, after, ue, target_cell):
    """Require a new matching trigger and later completion in the same CU."""
    if not before or not after or before['container_id']!=after['container_id'] or ue is None:
        return None
    # Use the appended log sequence, not increasing numeric timestamps: WSL UTC
    # can step backwards. Losing the prior cursor is unverified, never success.
    offset=0
    if before['events']:
        positions=[i for i,e in enumerate(after['events']) if e==before['events'][-1]]
        if not positions:return None
        offset=positions[-1]+1
    trigger=None
    for event in after['events'][offset:]:
        if event['ue']!=ue:continue
        if event['kind']=='trigger':
            trigger=event if event['cell']==target_cell else None
        elif trigger is not None:
            return dict(cu_container_id=after['container_id'],cu_ue_id=ue,
                        trigger_marker=trigger['t'],completion_marker=event['t'],
                        target_nr_cell_id=target_cell,
                        meaning='CU reports completed RRC handover after this target-specific trigger')
    return None


def execute_handover(policy, decision, args):
    """Send the RC handover control and verify it at the CU. Returns the action record."""
    before, before_txt = serving_du()
    other = {"3584": "3585", "3585": "3584"}.get(before)
    want_cell = DU_CELL.get(other) if other else None
    t_dec = decision["decided_mono"]
    if want_cell is None:
        _UE['id'] = None
        rec = dict(ts=iso(), ue=args.ue_label, policy_version=policy, action='handover',
                   target='unknown', result='failed', latency_ms=None,
                   params=dict(source_du=before, target_du=None, ric_control_result='not-sent-unknown-source-du',
                               target_nr_cell_id=None, xapp_rc=None,
                               **({'selector':decision['selector_metadata']} if 'selector_metadata' in decision else {})),
                   verify=dict(cu_before=before_txt[-200:], cu_after=''))
        append(args.out, rec)
        log('REFUSED: current serving DU is unknown; no RC command sent')
        return rec
    cu_ue_id=_UE['id']
    rrc_before=rrc_snapshot()
    if rrc_before is None:
        rec=dict(ts=iso(),ue=args.ue_label,policy_version=policy,action='handover',target='unknown',
                 result='failed',latency_ms=None,
                 params=dict(source_du=before,target_du=None,ric_control_result='not-sent-unverified-rrc-baseline',
                             cu_ue_id=cu_ue_id,rrc_handover_complete=False,
                             **({'selector':decision['selector_metadata']} if 'selector_metadata' in decision else {})),
                 verify=dict(cu_before=before_txt[-200:],cu_after=''))
        append(args.out,rec)
        log('REFUSED: CU protocol baseline unavailable; no RC command sent')
        return rec
    sent_ts = time.time()
    t_send = time.monotonic()
    env = ["-e", f"HORUS_UE_ID={_UE['id']}"] if _UE["id"] else []
    if want_cell:
        env += ["-e", f"HORUS_TARGET_CELL={want_cell}"]
    try:
        p = subprocess.run(["docker", "exec", *env, "ho-flexric", "timeout", "60", XAPP],
                           capture_output=True, text=True, timeout=90)
        xout, xrc = p.stdout + p.stderr, p.returncode
    except subprocess.TimeoutExpired as e:
        xout, xrc = f"timeout: {e}", 124
    t_xapp = time.monotonic()
    m = re.search(r"HORUS_HO ue=(\S+) from=(\S+) to=(\S+) result=(\S+) ctrl_us=(\d+)", xout)
    target_cell = m.group(3) if m else None
    ric_result = m.group(4) if m else "no-result-line"
    ctrl_ms = round(int(m.group(5)) / 1000.0, 1) if m else None
    reported_ue=int(m.group(1)) if m and m.group(1).isdigit() else None
    expected_ue=cu_ue_id if cu_ue_id is not None else reported_ue
    after, after_txt = before, ""
    t_done = None
    rrc_proof=None
    checks=range(int(args.verify_s / 0.5)) if ric_result=='acked' and target_cell==want_cell and reported_ue==expected_ue else ()
    for _ in checks:
        after, after_txt = serving_du()
        if after and before and after != before:
            rrc_proof=completed_rrc_handover(rrc_before,rrc_snapshot(),expected_ue,want_cell)
            if rrc_proof is not None:
                t_done = time.monotonic()
                break
        time.sleep(0.5)
    ok = t_done is not None and ric_result == "acked" and target_cell == want_cell
    if not ok:
        _UE["id"] = None          # re-resolve the active UE next time (it may have re-attached)
    rec = {
        "ts": iso(sent_ts), "ue": args.ue_label, "policy_version": policy,
        "action": "handover",
        "target": f"du-{after if ok else '?'}/nr-cell-{target_cell or '?'}",
        "params": {
            "ric_style": 3, "ric_action": 1, "ran_function": "ORAN-E2SM-RC",
            "ric_control": "Connected Mode Mobility / Handover Control (F1, intra-gNB inter-DU)",
            "xapp": "xapp_horus_ho (FlexRIC v3.0.0 xapp_rc_handover + UE/target selection)",
            "e2_node": "OAI gNB-CU", "cu_ue_id": expected_ue,
            "ric_control_result": ric_result, "ric_control_ack_ms": ctrl_ms,
            "rrc_handover_complete": rrc_proof is not None,
            "rrc_completion_evidence": rrc_proof,
            "source_du": before, "target_du": after if ok else None,
            "target_nr_cell_id": target_cell,
            "twin_ue": decision["twin_ue"], "twin_step": decision["step"],
            "twin_from_cell": decision["from"], "twin_to_cell": decision["to"],
            "decision_source": f"twin-in-the-loop ({args.scenario}, radio_map={args.radio_map}, "
                               f"controller={decision['controller']})",
            "mapping": "each twin HO decision executes as a real F1 HO to the other live DU (2-cell testbed)",
            "xapp_rc": xrc,
            **({"selector": decision['selector_metadata']} if 'selector_metadata' in decision else {}),
        },
        "result": "ok" if ok else "failed",
        "latency_ms": round((t_done - t_dec) * 1000.0, 1) if ok else None,
        "latency_breakdown": {
            "decision_to_send_ms": round((t_send - t_dec) * 1000.0, 1),
            "xapp_run_ms": round((t_xapp - t_send) * 1000.0, 1),
            "control_to_cu_confirmed_ms": round((t_done - t_send) * 1000.0, 1) if ok else None,
        },
        "trigger": {"kpi": "twin_rsrp_dbm", "observed": decision["serving_rsrp"],
                    "slo": decision["target_rsrp"],
                    "note": "serving vs target RSRP in the twin at the decision step"},
        "verify": {"cu_before": before_txt[-200:], "cu_after": after_txt[-200:]},
    }
    append(args.out, rec)
    log(f"HANDOVER {'OK' if ok else 'FAILED'}: DU {before} -> {after} (cell {target_cell}) "
        f"policy={policy} latency={rec['latency_ms']} ms xapp_rc={xrc}")
    if not ok or xrc != 0:
        # xrc 139 seen once: the xApp segfaulted AFTER the control (HO still
        # executed and was confirmed at the CU) — keep its tail for diagnosis.
        log("xApp output tail:\n" + "\n".join(xout.strip().splitlines()[-12:]))
    return rec


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--store", type=Path, default=REPO / "working" / "policies")
    ap.add_argument("--out", type=Path, default=REPO / "working" / "actuation" / "actions.jsonl")
    ap.add_argument("--decisions", type=Path, default=REPO / "working" / "evidence" / "finals-act-ho-decisions.jsonl")
    ap.add_argument("--scenario", default="corner_turner")
    ap.add_argument("--radio-map", default="opencellid")
    ap.add_argument("--seed", type=int, default=1000)
    ap.add_argument("--controller", default=None, help="default: dqn:<active A1 version>, else a3")
    ap.add_argument("--track", default="ue-00", help="twin UE whose decisions drive the live UE")
    ap.add_argument("--ue-label", default="ue-0")
    ap.add_argument("--step-s", type=float, default=0.5, help="wall seconds per twin second")
    ap.add_argument("--min-gap-s", type=float, default=40.0, help="min wall time between real HOs")
    ap.add_argument("--max-hos", type=int, default=3)
    ap.add_argument("--verify-s", type=float, default=40.0)
    ap.add_argument("--force-first", action="store_true",
                    help="execute one handover immediately (demo warm-start), marked origin=operator")
    args = ap.parse_args()

    policy, art = active_policy(args.store)
    if policy is None:
        log("REFUSED: no gate-promoted policy in the A1 store — not actuating")
        return 2
    if not isinstance(art, dict) or art.get('algo') != 'dqn_lstm':
        log("REFUSED: legacy driver supports dqn_lstm only; use selector_driver.py "
            "with a qualified 100 ms input contract for ctx_cho_selector")
        return 2
    from twin.env import TwinEnv
    from twin.controllers import load_controller
    name = args.controller or f"dqn:{policy}"
    try:
        ctrl = load_controller(name)
    except Exception as e:
        log(f"controller {name} unavailable ({e.__class__.__name__}: {e}); falling back to a3")
        name, ctrl = "a3", load_controller("a3")
    log(f"policy gate: {policy} (A1 store) | controller {name} | twin {args.scenario}/{args.radio_map} "
        f"seed {args.seed} | live UE {args.ue_label} <- twin {args.track}")
    du, txt = serving_du()
    log(f"live UE currently served by DU {du}")
    if du is None:
        log("FAIL: CU reports no UE/DU — is the handover profile up (make ho-up)?")
        return 1

    env = TwinEnv(scenario=args.scenario, radio_map=args.radio_map, seed=args.seed)
    env.reset()
    tracked = next(u for u in env.ues if u.ue_id == args.track)
    done_hos, attempted_hos, last_ho = 0, 0, -1e9

    if args.force_first:
        d = {"decided_mono": time.monotonic(), "twin_ue": args.track, "step": 0, "from": tracked.serving,
             "to": None, "serving_rsrp": None, "target_rsrp": None, "controller": "operator (warm-start)"}
        result = execute_handover(policy, d, args)
        attempted_hos += 1
        if result["result"] != "ok":
            log("FAIL: operator warm-start handover did not complete")
            return 1
        done_hos += 1
        last_ho = time.monotonic()

    class Recorder:
        def __init__(self, inner):
            self.inner, self.pending = inner, None

        def decide(self, ue, rsrp, step):
            tgt = self.inner.decide(ue, rsrp, step)
            if ue.ue_id == args.track and tgt is not None and tgt != ue.serving:
                self.pending = {"decided_mono": time.monotonic(), "twin_ue": ue.ue_id, "step": step,
                                "from": ue.serving, "to": tgt,
                                "serving_rsrp": round(rsrp[ue.serving], 1),
                                "target_rsrp": round(rsrp[tgt], 1), "controller": name}
            return tgt

    rec = Recorder(ctrl)
    finished = False
    while not finished and done_hos < args.max_hos:
        t_step = time.monotonic()
        _, finished = env.step(rec)
        if rec.pending:
            d, rec.pending = rec.pending, None
            gap_ok = time.monotonic() - last_ho >= args.min_gap_s
            append(args.decisions, {"decided_ts": iso(), "policy_version": policy,
                                    "executed": gap_ok, **{k: v for k, v in d.items() if k != "decided_mono"}})
            if gap_ok:
                log(f"policy decision @twin step {d['step']}: {d['from']} -> {d['to']} "
                    f"(rsrp {d['serving_rsrp']} -> {d['target_rsrp']} dBm) => real F1 handover")
                result = execute_handover(policy, d, args)
                attempted_hos += 1
                if result["result"] == "ok":
                    done_hos += 1
                last_ho = time.monotonic()
            else:
                log(f"policy decision @twin step {d['step']} deferred (min gap {args.min_gap_s}s since last real HO)")
        time.sleep(max(0.0, args.step_s - (time.monotonic() - t_step)))
    log(f"done: {done_hos}/{args.max_hos} real handovers completed from {attempted_hos} attempts; "
        f"twin metrics {env.metrics.as_dict()}")
    return 0 if done_hos >= args.max_hos else 1


if __name__ == "__main__":
    sys.exit(main())
