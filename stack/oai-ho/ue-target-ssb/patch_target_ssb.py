"""Pinned single-active-target CFRA selection; preserves all other paths."""
from pathlib import Path
import hashlib,json,sys
root=Path(sys.argv[1]);p=root/'openair2/LAYER2/NR_MAC_UE/nr_ra_procedures.c'
before=p.read_bytes();assert hashlib.sha256(before).hexdigest()=='604dab87cdb22db171cbd8c8eb99f66c25cd176fc6c014ca705191453b4561ee'
s=before.decode()
helper='''/* CFRA handover can retain the previous cell's MIB SSB index. In the
 * unambiguous one-active-SSB target case, use only the target resource explicitly
 * authorized by RRC. Never guess for multi-beam or inactive/malformed resources. */
static bool horus_select_single_cfra_target(NR_UE_MAC_INST_t *mac,
                                           struct NR_CFRA__resources__ssb *list,
                                           int *ssb)
{
  if (*ssb >= 0 || mac->ssb_list.nb_tx_ssb != 1 || list->ssb_ResourceList.list.count != 1)
    return false;
  NR_CFRA_SSB_Resource_t *res = list->ssb_ResourceList.list.array[0];
  if (res == NULL || res->ssb < 0 || res->ssb >= MAX_NB_SSB || mac->ssb_list.nb_ssb_per_index[res->ssb] != 0)
    return false;
  *ssb = res->ssb;
  mac->ra.ra_PreambleIndex = res->ra_PreambleIndex;
  mac->ra.ro_mask_index = list->ra_ssb_OccasionMaskIndex;
  LOG_W(NR_MAC, "HORUS LAB: sole authorized active target CFRA SSB %d selected; previous MIB SSB %d\\n", *ssb, mac->mib_ssb);
  return true;
}

'''
old='static void configure_ra_preamble(NR_UE_MAC_INST_t *mac)';assert s.count(old)==1;s=s.replace(old,helper+old)
old='''      }
    } else { // for the contention-based Random Access preamble selection'''
new='''      }
      (void)horus_select_single_cfra_target(mac, ssb_list, &ssb);
    } else { // for the contention-based Random Access preamble selection'''
assert s.count(old)==1;s=s.replace(old,new);p.write_text(s)
receipt=dict(source_commit='cfee4c20b45ac1cf6d455d3f01bb3e00200438b0',experimental=True,qualified=False,
    file=str(p.relative_to(root)),before_sha256=hashlib.sha256(before).hexdigest(),after_sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
    scope='4-step CFRA only; one RRC-authorized resource and one active target SSB; matching map required; previous MIB index unchanged',
    model_gate_security_bandwidth_unchanged=True)
(root/'horus-target-ssb-patch.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt))
