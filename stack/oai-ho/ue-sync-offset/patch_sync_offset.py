"""Backport OAI a646baaa negative synchronization-offset correction, with a diagnostic log."""
from pathlib import Path
import hashlib,json,sys

root=Path(sys.argv[1]);p=root/'executables/nr-ue.c'
before=hashlib.sha256(p.read_bytes()).hexdigest()
assert before=='9a05fae2a97586eed2aaf0983808b0ec1adb77700de67c786a52206b3be185b7',before
text=p.read_text()
old='static void syncInFrame(PHY_VARS_NR_UE *UE, openair0_timestamp_t *timestamp, int duration_rx_to_tx, openair0_timestamp_t rx_offset)'
helper='''static int sync_frame_start(int decoded_frame, int skipped_frames, int samples_per_frame, int *rx_offset)
{
  // Sometimes offset is negative meaning we need to skip ahead to next frame
  if (*rx_offset < 0) {
    *rx_offset += samples_per_frame;
    decoded_frame++;
  }
  return (decoded_frame + skipped_frames) % MAX_FRAME_NUMBER;
}

'''
assert text.count(old)==1
text=text.replace(old,helper+old)
old='          decoded_frame_rx = (decoded_frame_rx + skipped_frames) % MAX_FRAME_NUMBER;'
new='''          if (syncMsg->rx_offset < 0)
            LOG_W(PHY, "HORUS LAB: negative synchronization offset %d samples; advance to next frame\\n", syncMsg->rx_offset);
          decoded_frame_rx = sync_frame_start(decoded_frame_rx, skipped_frames, fp->samples_per_frame, &syncMsg->rx_offset);'''
assert text.count(old)==1
text=text.replace(old,new)
p.write_text(text)
receipt=dict(source_commit='cfee4c20b45ac1cf6d455d3f01bb3e00200438b0',
    upstream_fix='a646baaa62d6950e77edebd188e80422d4bf5bc3',
    upstream_url='https://github.com/OPENAIRINTERFACE/openairinterface5g/commit/a646baaa62d6950e77edebd188e80422d4bf5bc3',
    scope='Advance a negative synchronization offset by one radio frame and advance decoded SFN; positive offsets unchanged; additional warning only',
    file='executables/nr-ue.c',before_sha256=before,after_sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
    experimental=True,qualified=False,model_gate_security_bandwidth_response_window_unchanged=True)
(root/'horus-sync-offset-patch.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt))
