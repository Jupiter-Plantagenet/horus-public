#!/usr/bin/env bash
# HORUS finals — RIC-commanded HANDOVER demo (needs `make ho-up` first).
#
#   twin + promoted DQN policy decides -> E2SM-RC Style 3/Action 1 Handover Control
#   (FlexRIC v3 xapp_rc_handover) -> OAI CU runs a real F1 handover of the nrUE
#   between DU 3584 and DU 3585 -> verified at the CU -> actions.jsonl
#
#   env: MAX_HOS (default 3)  MIN_GAP_S (default 40)  PY (python with torch;
#        default ~/horus-ml/bin/python, falls back to A3 without torch)
set -u
cd "$(dirname "$0")"
REPO="$(cd ../.. && pwd)"
W="$REPO/working"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
EVID="$W/evidence/finals-act-ho-$STAMP.txt"
PY="${PY:-$(ls /home/*/horus-ml/bin/python 2>/dev/null | head -1)}"; PY="${PY:-python3}"
mkdir -p "$W/evidence" "$W/actuation"
exec > >(tee "$EVID") 2>&1
say() { echo "[$(date -u +%H:%M:%S)] $*"; }

say "=== HORUS RIC-commanded handover demo ($STAMP) ==="
for c in ho-cu ho-du-pci0 ho-du-pci1 ho-nr-ue ho-flexric ho-amf; do
  docker ps --format '{{.Names}}' | grep -qx "$c" || { say "FAIL: $c not running — 'make ho-up' first"; exit 1; }
done
say "E2 nodes registered at the near-RT RIC (FlexRIC v3.0.0):"
docker logs ho-flexric 2>&1 | grep -E "E2 SETUP-REQUEST rx|Accepting RAN function" | sed 's/^/   /' | head -12
if ! ls "$W"/policies/*.json >/dev/null 2>&1; then
  say "A1 store empty -> admitting the gate-promoted candidate"
  "$PY" "$REPO/stack/policy_store.py" submit "$W/candidates/clean-median-r3.json" --store "$W/policies" | sed 's/^/   /'
fi
say "UE data plane before: $(docker exec ho-nr-ue ip -4 -o addr show oaitun_ue1 2>/dev/null | awk '{print $4}')"
before_ping=$(docker exec ho-nr-ue ping -c 3 -W 3 -I oaitun_ue1 192.168.72.135 2>&1)
before_ping_rc=$?
printf '%s\n' "$before_ping" | tail -2 | sed 's/^/   /'

n0=$(wc -l < "$W/actuation/actions.jsonl" 2>/dev/null || echo 0)
say "running the twin-in-the-loop driver (policy -> real handovers), MAX_HOS=${MAX_HOS:-3}"
"$PY" ./ho_driver.py --max-hos "${MAX_HOS:-3}" --min-gap-s "${MIN_GAP_S:-40}" ${HO_ARGS:-}
rc=$?

say "UE data plane after: ping through the 5G core from the UE on its NEW cell"
after_ping=$(docker exec ho-nr-ue ping -c 3 -W 3 -I oaitun_ue1 192.168.72.135 2>&1)
after_ping_rc=$?
printf '%s\n' "$after_ping" | tail -2 | sed 's/^/   /'
say "CU RRC evidence (handover procedure lines):"
docker logs ho-cu 2>&1 | grep -iE "handover|trigger_f1_ho|RC.*control|Reconfiguration.*sync|UE context release|E2 .*CONTROL" | tail -15 | sed 's/^/   /'
say "target-DU evidence (UE random access on the new cell):"
for d in ho-du-pci0 ho-du-pci1; do
  docker logs "$d" 2>&1 | grep -iE "RA procedure|Msg4|CFRA|handover" | tail -3 | sed "s/^/   [$d] /"
done
say "executed handovers (working/actuation/actions.jsonl):"
tail -n +$((n0 + 1)) "$W/actuation/actions.jsonl" | python3 -c 'import sys,json
for l in sys.stdin:
    r=json.loads(l)
    if r.get("action")!="handover": continue
    p=r["params"]
    print("   %s RC %s/%s DU %s -> %s (cell %s) policy=%s result=%s latency=%sms twin %s->%s" % (r["ts"], p["ric_style"], p["ric_action"],
          p["source_du"], p["target_du"], p["target_nr_cell_id"], r["policy_version"], r["result"], r["latency_ms"], p["twin_from_cell"], p["twin_to_cell"]))'
ok=$(tail -n +$((n0 + 1)) "$W/actuation/actions.jsonl" | grep -c '"action": "handover".*"result": "ok"')
result=1
if [ "$rc" = 0 ] && [ "$ok" -ge 1 ] && [ "$before_ping_rc" = 0 ] && [ "$after_ping_rc" = 0 ]; then
  say "=== PASS: $ok RIC-commanded handover(s) executed by the RAN and confirmed at the CU ==="
  result=0
else
  say "=== FAIL: handover demo incomplete (driver rc=$rc, confirmed=$ok, traffic before=$before_ping_rc after=$after_ping_rc) ==="
fi
say "transcript: $EVID"
exit "$result"
