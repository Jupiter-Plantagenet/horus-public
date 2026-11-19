# UE negative synchronization offset backport

This opt-in image retains the target-random-access completion and authorized
target-SSB corrections and backports OAI commit
`a646baaa62d6950e77edebd188e80422d4bf5bc3` onto pinned source
`cfee4c20b45ac1cf6d455d3f01bb3e00200438b0`.

The failed 494-file sustained run logged `Resynchronizing RX by -2224 samples`
immediately before repeated PBCH decoding and RAR reception failures. The pinned
`syncInFrame()` consumes samples only while its signed size is positive. The
upstream correction advances negative offsets by one frame and advances the
decoded frame number. The backport adds a warning when that correction is used.
Positive offsets retain their original behavior.

`UPSTREAM.json` preserves the upstream change and attribution. `BUILD.json`
records actual image/binary IDs, the pinned source hashes, and verification scope.
Twelve checks compile the actual patched C helper, including the observed offset,
both frame sizes, positive offsets and SFN wraparound; ASan/UBSan pass. The image
also retains its initial ten-case receipt. The expanded twelve-case receipt uses
the same compiled source helper. These checks do not qualify radio recovery.

Select explicitly alongside the unchanged CU and DU overrides:

```
--cu-image horus/oai-gnb:srb-reorder-diagnostic --cu-srb-reordering-ms 1000 \
--ue-image horus/oai-nr-ue:sync-offset-diagnostic \
--du-image horus/oai-gnb:cfra-retry-v2-diagnostic
```

Stock defaults, 106 PRB, the 20-slot response window, integrity, retry limits,
model, gate and strict CU-completion criteria remain unchanged. Operator and
source-bound bounded/two-hour qualification must be recorded separately. The
earlier failed run and the operator-interrupted timing diagnostic remain in the
evidence history. No new training or held-out/audit evaluation is involved.

The standalone recipe uses `stack/oai-ho` as its build context:

```
docker build -f stack/oai-ho/ue-sync-offset/Dockerfile \
  -t horus/oai-nr-ue:sync-offset-diagnostic stack/oai-ho
```

The actual build was incremental from the exact recorded local builder/runtime
images. A full standalone rebuild has not been tested. Do not infer image-byte
identity from a future rebuild; record and qualify its actual image IDs.
