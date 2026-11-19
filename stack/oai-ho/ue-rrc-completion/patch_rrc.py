"""Diagnostic hypothesis: queue handover completion only after target RA.

Refuse different upstream bytes. This is not a qualified radio image until
actual protocol/traffic checks pass; the original image stays unchanged.
"""
from pathlib import Path
import hashlib,json,re,sys
root=Path(sys.argv[1]);paths={'openair2/RRC/NR_UE/rrc_UE.c':'035e66ea10f30d03508720b68e24e14e2bd98042d6f1184921e790e7b090c89c',
    'openair2/RRC/NR_UE/rrc_defs.h':'77902bbae91484252d3bf723b9e5fdbc6e9a5179b2812ffbc048e36ed25ca139'}
for rel,digest in paths.items():assert hashlib.sha256((root/rel).read_bytes()).hexdigest()==digest,rel
p=root/'openair2/RRC/NR_UE/rrc_defs.h';s=p.read_text()
anchor='  bool sched_reconfsync_sib1;'
assert s.count(anchor)==1
s=s.replace(anchor,anchor+'\n  bool pending_handover_complete;\n  int pending_handover_srb;\n  uint8_t pending_handover_transaction;')
p.write_text(s)
p=root/'openair2/RRC/NR_UE/rrc_UE.c';s=p.read_text()
anchor='          nr_rrc_ue_generate_RRCReconfigurationComplete(rrc, Srb_id, c1->choice.rrcReconfiguration->rrc_TransactionIdentifier);'
assert s.count(anchor)==1
s=s.replace(anchor,'''          if (nr_timer_is_active(&rrc->timers_and_constants.T304)) {
            /* MAC applies reconfigurationWithSync asynchronously. Enqueuing
             * SRB1 now can expose the completion to the old cell or MAC reset.
             * Submit it after successful target random access instead. */
            rrc->pending_handover_complete = true;
            rrc->pending_handover_srb = Srb_id;
            rrc->pending_handover_transaction = c1->choice.rrcReconfiguration->rrc_TransactionIdentifier;
            RRCLOG_I("HORUS: defer handover completion until target random access\\n");
          } else {
            rrc->pending_handover_complete = false;
            nr_rrc_ue_generate_RRCReconfigurationComplete(rrc, Srb_id, c1->choice.rrcReconfiguration->rrc_TransactionIdentifier);
          }''')
anchor='    nr_timer_stop(&timers->T304);'
assert s.count(anchor)==1
s=s.replace(anchor,anchor+'''
    if (rrc->pending_handover_complete) {
      rrc->pending_handover_complete = false;
      RRCLOG_I("HORUS: target random access succeeded; submit handover completion\\n");
      nr_rrc_ue_generate_RRCReconfigurationComplete(rrc, rrc->pending_handover_srb,
                                                 rrc->pending_handover_transaction);
    }''')
for name in ('nr_rrc_process_reconfigurationWithSync','nr_rrc_going_to_IDLE'):
    pattern=r'((?:static )?void '+name+r'\([^;]*?\)\s*\{)'
    s,count=re.subn(pattern,lambda m:m[1]+'\n  rrc->pending_handover_complete = false;',s)
    assert count==1,(name,count)
p.write_text(s)
print(json.dumps(dict(upstream='cfee4c20b45ac1cf6d455d3f01bb3e00200438b0',diagnostic_only=True,
    patched_sha256={rel:hashlib.sha256((root/rel).read_bytes()).hexdigest() for rel in paths})))
