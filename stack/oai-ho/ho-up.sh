#!/usr/bin/env bash
# Bring up the OAI handover profile in the order OAI's handover tutorial/CI require:
#   core + RIC -> CU -> DU0 -> UE (must attach on DU0) -> DU1
# Refuses to run while the default srsRAN stack is up (CPU on the demo box).
set -u
cd "$(dirname "$0")"
DC="docker compose"
say() { echo "[$(date -u +%H:%M:%S)] $*"; }
wait_log() {  # wait_log <container> <regex> <timeout_s>
  local c=$1 re=$2 t=$3 i
  for i in $(seq 1 "$t"); do
    docker logs "$c" 2>&1 | grep -qE "$re" && return 0
    if [ "$(docker inspect -f '{{.State.Running}}' "$c" 2>/dev/null)" != true ]; then
      say "FAIL: $c exited:"; docker logs "$c" 2>&1 | grep -E "Assert|error|Error" | tail -5 | sed 's/^/   /'
      exit 1
    fi
    sleep 2
  done
  return 1
}

if docker ps --format '{{.Names}}' | grep -qx gnb; then
  say "REFUSED: the srsRAN stack (container 'gnb') is running. 'make down' first — both stacks"
  say "         do not fit on this machine's CPU at the same time."
  exit 2
fi

say "1/5 core network + near-RT RIC"
$DC up -d mysql oai-amf oai-smf oai-upf oai-ext-dn flexric 2>&1 | grep -vE "Pulling|Waiting|Downloading" | tail -3
wait_log ho-amf "NGAP|ngap|Starting|amf" 120 || say "warn: AMF not logging yet"
sleep 5

say "2/5 CU (E2 agent -> RIC 192.168.71.160)"
$DC up -d --no-deps oai-cu 2>&1 | tail -1
wait_log ho-cu "Received NGSetupResponse|NGSetupResponse" 180 && say "   CU: NG Setup with AMF done" || say "   warn: no NGSetupResponse yet"

say "3/5 DU pci0 (DU id 3584)"
$DC up -d --no-deps oai-du-pci0 2>&1 | tail -1
wait_log ho-cu "F1 Setup|DU.*3584|gNB-DU ID 3584|Received F1 Setup" 180 && say "   CU accepted DU0 over F1" || say "   warn: DU0 F1 setup not seen"

say "4/5 nrUE (rfsim server) — attach on DU0"
$DC up -d --no-deps oai-nr-ue 2>&1 | tail -1
ok=0
for i in $(seq 1 300); do
  ip=$(docker exec ho-nr-ue ip -4 -o addr show oaitun_ue1 2>/dev/null | awk '{print $4}')
  if [ -n "$ip" ]; then ok=1; break; fi
  sleep 1
done
[ $ok = 1 ] && say "   UE attached: oaitun_ue1 $ip" || { say "FAIL: UE did not get an IP within 300 s"; exit 1; }

say "5/5 DU pci1 (DU id 3585, second cell)"
$DC up -d --no-deps oai-du-pci1 2>&1 | tail -1
sleep 20
wait_log ho-cu "3585" 180 && say "   CU sees DU1 (3585)" || say "   warn: DU1 not seen at CU yet"

say "state: serving DU per CU RRC ->"
UEID=$(docker exec ho-cu cat nrRRC_stats.log | awk '/^UE [0-9]+ CU UE ID/{id=$6} /PDU session.*established/{best=id} END{print best}')
say "   UE contexts at CU: $(docker exec ho-cu grep -cE '^UE [0-9]' nrRRC_stats.log) (active with PDU session: CU UE ID ${UEID:-none})"
python3 ./ci_cmd.py 192.168.71.150 9090 "ci fetch_du_by_ue_id $UEID" | head -1 | sed 's/^/   /'
say "E2 nodes at the RIC:"
docker logs ho-flexric 2>&1 | grep -E "E2 SETUP|Accepting RAN function" | sed 's/^/   /' | tail -12
say "handover profile up. 'make ho-demo' to run the RIC-commanded handover."
