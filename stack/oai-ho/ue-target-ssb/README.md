# Sole authorized target CFRA beam (experimental)

The DU CFRA-retry probe recovered a natural Msg2-window miss, but later failed
on handover 33 when the UE asserted that RA resource selection set no SSB.
Pinned OAI only matches the current `mib_ssb` against the target's dedicated
resource list; a nonmatching index leaves no selected resource and exits.

This image retains the completion-after-target-RA correction and adds a narrow
selection rule for **four-step CFRA**. When the normal match fails, there must
be exactly one target RRC-authorized resource and exactly one active target
SSB, with that resource mapped to active index zero. Only then use its SSB,
reserved preamble and occasion mask. The previous MIB observation is preserved.
Multiple, empty, inactive, null or out-of-range resources do not get guessed.
CBRA and two-step RA retain upstream behavior. Actual target RA, new CU RRC
completion and post-control traffic are still required.

Build from this directory using
`docker build -t horus/oai-nr-ue:target-ssb-diagnostic .`.
The recipe pins upstream source/runtime, refuses unexpected original bytes and
compiles tests of the actual selection helper. `BUILD.json` binds the tested
incremental binary and records that the standalone full rebuild was not run.
OS package resolution is not a bit-reproducible promise.

Select this UE together with the finite CU timer and bounded DU retry:

```
--cu-image horus/oai-gnb:srb-reorder-diagnostic --cu-srb-reordering-ms 1000 \
--ue-image horus/oai-nr-ue:target-ssb-diagnostic \
--du-image horus/oai-gnb:cfra-retry-diagnostic
```

All stock Compose defaults, 106 PRB, response window, integrity, models, gate and
strict completion checks remain unchanged. This is an emulated-radio experiment;
compilation/helper tests alone are not operator, integrated or sustained PASS.
Prior failures remain archived. It is not field-network or native CHO evidence.
