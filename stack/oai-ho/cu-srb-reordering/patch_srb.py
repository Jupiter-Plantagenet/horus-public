from pathlib import Path
import hashlib,json,subprocess
root=Path('/oai-ran')
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()=='cfee4c20b45ac1cf6d455d3f01bb3e00200438b0'
# Discard the previous, unsuccessful UE timing experiment in this owned build layer.
subprocess.run(['git','restore','openair2/RRC/NR_UE/rrc_UE.c','openair2/RRC/NR_UE/rrc_defs.h'],cwd=root,check=True)
p=root/'openair2/LAYER2/nr_pdcp/nr_pdcp_oai_api.c'
before=p.read_bytes(); assert hashlib.sha256(before).hexdigest()=='92cb9880cf6641414188e49bd31d1871ebe0494ae8d51ffe4ef690c0adfacfba'; text=before.decode()
old = '''  int t_Reordering = -1; // infinity as per default SRB configuration in 9.2.1 of 38.331
  if (s->pdcp_Config != NULL && s->pdcp_Config->t_Reordering != NULL)
    t_Reordering = decode_t_reordering(*s->pdcp_Config->t_Reordering);'''
new = old + r'''

  /* Explicit local CU laboratory experiment. Keep the upstream default unless
   * opted in; do not change integrity validation, SN ordering, or UE settings.
   * The existing PDCP expiry path delivers authenticated buffered SDUs after
   * a missing source-DU PDU, instead of waiting forever across an F1 handover. */
  const char *lab_timer = getenv("HORUS_LAB_SRB_REORDERING_MS");
  if (is_gnb && NODE_IS_CU(node_type) && lab_timer != NULL) {
    AssertFatal(strcmp(lab_timer, "1000") == 0,
                "HORUS_LAB_SRB_REORDERING_MS only supports 1000 in this diagnostic image\n");
    t_Reordering = 1000;
    LOG_W(PDCP, "HORUS LAB: CU SRB %d t-Reordering explicitly set to %d ms\n", srb_id, t_Reordering);
  }
'''
assert text.count(old)==1
p.write_text(text.replace(old,new))
changed=subprocess.check_output(['git','diff','--name-only'],cwd=root,text=True).splitlines()
assert changed==['openair2/LAYER2/nr_pdcp/nr_pdcp_oai_api.c'],changed
receipt=dict(source_commit='cfee4c20b45ac1cf6d455d3f01bb3e00200438b0',file=changed[0],before_sha256=hashlib.sha256(before).hexdigest(),after_sha256=hashlib.sha256(p.read_bytes()).hexdigest(),experimental=True,qualified=False,t_reordering_ms=1000,explicit_opt_in='HORUS_LAB_SRB_REORDERING_MS=1000',ue_patch_removed=True)
Path('/oai-srb-patch.json').write_text(json.dumps(receipt,indent=2)+'\n')
