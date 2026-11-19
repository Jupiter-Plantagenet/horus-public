#!/usr/bin/env bash
# Acceptance check for the handover profile: one RIC-commanded handover, verified
# at the CU independently of the xApp (serving DU before != after), UE still
# passes traffic afterwards. No twin/policy here — just the E2 control path.
set -u
cd "$(dirname "$0")"
fail=0
# the UE with an established PDU session (the CU may hold stale contexts from failed RA)
UEID=$(docker exec ho-cu cat nrRRC_stats.log | awk '/^UE [0-9]+ CU UE ID/{id=$6} /PDU session.*established/{best=id} END{print best}')
du() { python3 ./ci_cmd.py 192.168.71.150 9090 "ci fetch_du_by_ue_id $UEID" | grep -oE '\b358[45]\b' | tail -1; }

echo "=== 1. E2 nodes (CU + 2 DUs) at the RIC ==="
docker logs ho-flexric 2>&1 | grep -E "E2 SETUP-REQUEST rx" | sed 's/^/   /'
n=$(docker logs ho-flexric 2>&1 | grep -c "E2 SETUP-REQUEST rx")
[ "$n" -ge 3 ] || { echo "FAIL: expected >=3 E2 nodes (CU, DU0, DU1), saw $n"; fail=1; }

echo "=== 2. UE attached + serving DU (CU RRC) ==="
echo "   active UE (CU UE ID with PDU session): ${UEID:-none}"
b=$(du); echo "   serving DU before: ${b:-none}"; [ -n "$b" ] || { echo "FAIL: no UE at CU"; exit 1; }

echo "=== 3. E2SM-RC Style 3 / Action 1 Handover Control (xapp_horus_ho) ==="
control_output=$(docker exec -e HORUS_UE_ID="$UEID" ho-flexric timeout 60 /usr/local/flexric/xApp/c/rc_handover/xapp_horus_ho 2>&1)
control_rc=$?
printf '%s\n' "$control_output" | grep -E "UE currently on|Decoded F1|HORUS|rejected|CONTROL" | sed 's/^/   /'
if [ "$control_rc" -ne 0 ] || ! printf '%s\n' "$control_output" | grep -qE 'HORUS_HO .*result=acked'; then
  echo "FAIL: handover control did not complete with an acknowledgement"; fail=1
fi
a=""
for i in $(seq 1 60); do a=$(du); [ -n "$a" ] && [ "$a" != "$b" ] && break; sleep 1; done
echo "   serving DU after : ${a:-none}"
[ -n "$a" ] && [ "$a" != "$b" ] || { echo "FAIL: serving DU did not change"; fail=1; }

echo "=== 4. UE data plane after handover ==="
ping_output=$(docker exec ho-nr-ue ping -c 4 -W 3 -I oaitun_ue1 192.168.72.135 2>&1)
ping_rc=$?
printf '%s\n' "$ping_output" | tail -2 | sed 's/^/   /'
if [ "$ping_rc" -ne 0 ]; then
  echo "FAIL: UE data-plane ping failed after handover"; fail=1
fi

[ "$fail" = 0 ] && echo "RESULT: PASS — RIC-commanded F1 handover executed and confirmed at the CU" || echo "RESULT: FAIL"
exit "$fail"
