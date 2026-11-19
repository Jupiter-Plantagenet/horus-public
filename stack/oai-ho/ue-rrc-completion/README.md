# Explicit target-RA completion ordering in the emulated UE

This pinned-source experimental image queues handover RRC completion only after
target random access succeeds. It preserves integrity, T304 handling and the
original radio bandwidth/configuration. The original UE image is unchanged.

The UE change alone FAILED on the ninth operator control: a missing SRB1 count
still blocked the stock CU's infinite reorder queue. The finite CU timer alone
passed 36 operator controls, including two observed gap recoveries, but its first
AI-integrated bounded attempt failed target random access. Both original failures
remain archived. The COMBINATION then passed bounded AI integration: 1,802 frames,
86 actual calls, two new CU RRC proofs, post-control traffic, source hashes and
cleanup. This is bounded engineering evidence, not yet a two-hour PASS, a proven
general root-cause fix or field-radio qualification.

Build from this directory with Docker:

```sh
docker build -t horus/oai-nr-ue:rrc-complete-diagnostic .
```

Both the official build/runtime base and upstream commit are pinned. The patch
refuses different original source hashes. BUILD.json binds the tested binary
and image. Select the combination explicitly in the release runner:

```sh
--cu-image horus/oai-gnb:srb-reorder-diagnostic --cu-srb-reordering-ms 1000 \
--ue-image horus/oai-nr-ue:rrc-complete-diagnostic
```

Every handover still requires a new target-specific CU trigger/completion proof
and post-control traffic. A control failure stops the session. No AI checkpoint,
gate threshold, measured-radio calibration or final federated NO-GO changes.
