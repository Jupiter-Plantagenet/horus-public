"""Pinned, diagnostic-only recovery of CFRA after an expired Msg2 window."""
from pathlib import Path
import hashlib,json,subprocess,sys
root=Path(sys.argv[1])
paths={
 'openair2/LAYER2/NR_MAC_gNB/gNB_scheduler_RA.c':'d10e79c59dfc0202701f9abd57f9a87ca5a8a09d546178f312fd2e4c29ac3d88',
 'openair2/LAYER2/NR_MAC_gNB/nr_mac_gNB.h':'de2f59ab9d2099c70abfb96e936e205497a49a33a6c10a1edfedc50f6578a27c'}
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()=='cfee4c20b45ac1cf6d455d3f01bb3e00200438b0'
for rel,digest in paths.items():assert hashlib.sha256((root/rel).read_bytes()).hexdigest()==digest,rel
p=root/'openair2/LAYER2/NR_MAC_gNB/nr_mac_gNB.h';s=p.read_text()
old='  /// CFRA flag\n  bool cfra;\n} NR_RA_t;'
new='''  /// CFRA flag
  bool cfra;
  /// Explicit HORUS diagnostic image: bounded Msg2-window recovery only.
  unsigned int horus_cfra_window_misses;
  int horus_cfra_retry_slots;
} NR_RA_t;'''
assert s.count(old)==1;s=s.replace(old,new);p.write_text(s)
p=root/'openair2/LAYER2/NR_MAC_gNB/gNB_scheduler_RA.c';s=p.read_text()
old='// returns true if the UE must be released by the caller\nstatic bool nr_generate_Msg2('
helper='''/* A prepared CFRA context owns its reserved preamble. Deleting it on one
 * missed response window makes subsequent UE retries look like invalid CBRA.
 * Do not transmit a late RAR. Wait for a NEW preamble, with finite retry count
 * and finite idle lifetime. CBRA retains the upstream release behavior. */
static bool horus_rearm_cfra_after_expired_msg2(NR_RA_t *ra, int slots_per_frame)
{
  if (!ra->cfra || ra->horus_cfra_window_misses >= 3)
    return false;
  ra->horus_cfra_window_misses++;
  ra->horus_cfra_retry_slots = 100 * slots_per_frame; // 1,000 ms radio time
  ra->ra_state = nrRA_gNB_IDLE;
  return true;
}

'''
assert s.count(old)==1;s=s.replace(old,helper+old)
old='''          ra->RA_rnti,
          UE->rnti);
    return true;
  }

  NR_UE_sched_ctrl_t *sched_ctrl = &UE->UE_sched_ctrl;'''
new='''          ra->RA_rnti,
          UE->rnti);
    if (horus_rearm_cfra_after_expired_msg2(ra, n_slots_frame)) {
      LOG_W(NR_MAC, "HORUS LAB: CFRA %04x missed Msg2 window; await NEW preamble, retry %u/3, idle limit 1000 ms\\n",
            UE->rnti, ra->horus_cfra_window_misses);
      return false;
    }
    return true;
  }

  NR_UE_sched_ctrl_t *sched_ctrl = &UE->UE_sched_ctrl;'''
assert s.count(old)==1;s=s.replace(old,new)
old='''    // Check RA Contention Resolution timer (TODO check this procedure)'''
new='''    if (ra->cfra && ra->ra_state == nrRA_gNB_IDLE && ra->horus_cfra_retry_slots > 0
        && --ra->horus_cfra_retry_slots == 0) {
      LOG_W(NR_MAC, "HORUS LAB: CFRA %04x retry idle lifetime expired; release context\\n", UE->rnti);
      to_release[num_release++] = UE->rnti;
      continue;
    }

'''+old
assert s.count(old)==1;s=s.replace(old,new);p.write_text(s)
receipt=dict(source_commit='cfee4c20b45ac1cf6d455d3f01bb3e00200438b0',experimental=True,qualified=False,
    behavior='CFRA only: at most three rearms after expired Msg2; wait for a new preamble; idle limit 1000 ms radio time',
    response_window_changed=False,security_changed=False,
    files={rel:dict(before_sha256=digest,after_sha256=hashlib.sha256((root/rel).read_bytes()).hexdigest()) for rel,digest in paths.items()})
(root/'horus-cfra-patch.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt))
