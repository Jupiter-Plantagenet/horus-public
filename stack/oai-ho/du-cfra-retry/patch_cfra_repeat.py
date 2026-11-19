"""Keep a bounded CFRA retry context until valid UL confirms RAR reception."""
from pathlib import Path
import hashlib,json,sys
root=Path(sys.argv[1]);base=root/'openair2/LAYER2/NR_MAC_gNB'
expected={'gNB_scheduler_primitives.c':'b91f8b37e1ecd997067175926f06a3e5cceb60c1b934ab1589473640dd2a9caf',
 'gNB_scheduler_ulsch.c':'16c1f0bb50a0594953bc1287ae7073b092ac33cc89e7b2f001c8522ab5b98590',
 'gNB_scheduler_RA.c':'889436c9939610e0a0f4d8b14804b178c0ee8b144ca89795d7a2b3c6a226b0f3',
 'nr_mac_gNB.h':'2818f3749588a8fd5b1ee95b9af2b2b9ca794b0a081529892c5a164f0a0a5516'}
for name,digest in expected.items():assert hashlib.sha256((base/name).read_bytes()).hexdigest()==digest,name
def edit(name,old,new):
    p=base/name;s=p.read_text();assert s.count(old)==1,(name,old[:100]);p.write_text(s.replace(old,new))
edit('nr_mac_gNB.h','  NR_RA_t *ra;\n','  NR_RA_t *ra;\n  NR_RA_t *horus_cfra_replay; // bounded, unconfirmed-RAR retry context; exclusive ownership\n')
edit('gNB_scheduler_primitives.c','''  free_and_zero(UE->ra);
  free(UE);''','''  free_and_zero(UE->ra);
  free_and_zero(UE->horus_cfra_replay);
  free(UE);''')
edit('gNB_scheduler_primitives.c','''  free_and_zero(UE->ra);

  return add_connected_nr_ue(nr_mac, UE);''','''  /* CFRA Msg3 callback may be a NACK: it is not proof the UE received RAR.
   * Preserve only its reserved retry context until valid UL or finite expiry.
   * The connected UE can still obtain SR/UL grants as required by CFRA. */
  if (UE->ra->cfra && UE->ra->horus_cfra_window_misses < 3) {
    DevAssert(UE->horus_cfra_replay == NULL);
    UE->horus_cfra_replay = UE->ra;
    UE->ra = NULL;
    UE->horus_cfra_replay->horus_cfra_retry_slots = 100 * UE->pcell->frame_structure.numb_slots_frame;
    LOG_W(NR_MAC, "HORUS LAB: CFRA %04x retain bounded RAR retry context pending valid UL\\n", UE->rnti);
  } else {
    free_and_zero(UE->ra);
  }

  return add_connected_nr_ue(nr_mac, UE);''')
old='''  return NULL;
}

/** @brief add UE to list of UEs doing RA.'''
new='''  /* The expected CFRA Msg3 callback may have moved this UE to connected
   * even though RAR was lost. A matching NEW reserved preamble can restart
   * access, but only before first valid UL, within its lifetime/retry budget. */
  UE_iterator(nr_mac->UE_info.connected_ue_list, UE) {
    NR_RA_t *retry = UE->horus_cfra_replay;
    if (UE->pcell != cell || retry == NULL || !retry->cfra
        || retry->horus_cfra_retry_slots <= 0 || retry->horus_cfra_window_misses >= 3)
      continue;
    for (int i = 0; i < retry->preambles.num_preambles; ++i) {
      if (retry->preambles.preamble_list[i] != preamble_index)
        continue;
      DevAssert(UE->ra == NULL);
      UE->ra = retry;
      UE->horus_cfra_replay = NULL;
      if (!add_new_UE_RA(nr_mac, UE)) {
        UE->ra = NULL;
        UE->horus_cfra_replay = retry;
        LOG_W(NR_MAC, "HORUS LAB: CFRA %04x retry refused: access list full\\n", UE->rnti);
        return NULL;
      }
      NR_UE_info_t *removed = remove_UE_from_list(MAX_MOBILES_PER_GNB + 1, nr_mac->UE_info.connected_ue_list, UE->rnti);
      DevAssert(removed == UE);
      retry->horus_cfra_window_misses++;
      retry->horus_cfra_retry_slots = 0;
      LOG_W(NR_MAC, "HORUS LAB: CFRA %04x NEW reserved preamble after lost RAR, retry %u/3\\n",
            UE->rnti, retry->horus_cfra_window_misses);
      return UE;
    }
  }
  return NULL;
}

/** @brief add UE to list of UEs doing RA.'''
edit('gNB_scheduler_RA.c',old,new)
edit('gNB_scheduler_RA.c','''  start_meas(&cell->schedule_ra);
  // releasing a UE modifies access_ue_list''','''  start_meas(&cell->schedule_ra);
  UE_iterator(mac->UE_info.connected_ue_list, UE) {
    NR_RA_t *retry = UE->horus_cfra_replay;
    if (UE->pcell == cell && retry != NULL && --retry->horus_cfra_retry_slots <= 0) {
      LOG_W(NR_MAC, "HORUS LAB: CFRA %04x unconfirmed-RAR retry context expired\\n", UE->rnti);
      free_and_zero(UE->horus_cfra_replay);
    }
  }
  // releasing a UE modifies access_ue_list''')
edit('gNB_scheduler_ulsch.c','''    // if not missed detection (10dB threshold for now)''','''    if (sduP != NULL && sdu_lenP > 0 && UE->horus_cfra_replay != NULL) {
      LOG_W(NR_MAC, "HORUS LAB: CFRA %04x valid UL received; retire RAR retry context\\n", UE->rnti);
      free_and_zero(UE->horus_cfra_replay);
    }

    // if not missed detection (10dB threshold for now)''')
receipt=dict(source_commit='cfee4c20b45ac1cf6d455d3f01bb3e00200438b0',experimental=True,qualified=False,
    scope='CFRA only; finite reserved-preamble retry after missed RAR; exclusive RA ownership; first valid UL, UE deletion, or 1000 ms radio-time expiry frees retained context; aggregate retry budget three',
    response_window_security_bandwidth_model_gate_unchanged=True,
    files={name:dict(before_sha256=digest,after_sha256=hashlib.sha256((base/name).read_bytes()).hexdigest()) for name,digest in expected.items()})
(root/'horus-cfra-repeat-patch.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
