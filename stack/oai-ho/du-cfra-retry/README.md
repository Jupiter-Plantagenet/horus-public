# Bounded target CFRA recovery, including missed RAR (experimental)

The 481-file combined radio soak failed in its sixth cycle. The target DU tried
to schedule Msg2 21 slots after the preamble, beyond the configured 20-slot
window. Upstream then deleted the prepared CFRA UE. The UE's repeated reserved
preamble no longer matched its target context and did not recover.

This diagnostic changes only that expiration path in pinned OAI source
`cfee4c20b45ac1cf6d455d3f01bb3e00200438b0`. For a prepared CFRA UE, it retains
the context in IDLE for a **new** preamble, with at most three rearms and a
1,000 ms radio-time idle lifetime. A fourth expiration or idle timeout releases
the context. It does not send a late RAR. CBRA keeps upstream behavior.

The first image recovered one natural expired window, but later probes exposed
another interval: upstream marks CFRA complete on its expected Msg3 callback
even when no packet was received, then frees its RA context. Version 2 retains
that context separately while the UE can receive normal uplink grants. A NEW
matching reserved preamble can move the same UE back to access. The total retry
budget is three; valid uplink data, a 1,000 ms radio-time timeout, or UE deletion
retires the retained context. Access-list capacity failure restores ownership
without removing the connected UE. No RAR-reception or CU-completion claim is
created by this retention. Prior images/results remain in the evidence index.

The image is selected explicitly for both DUs:

```
python release/spooled_demo.py --root /absolute/path/to/assembly \
  --out /absolute/path/to/fresh-capture --live --soak-seconds 7200 \
  --cu-image horus/oai-gnb:srb-reorder-diagnostic --cu-srb-reordering-ms 1000 \
  --ue-image horus/oai-nr-ue:target-ssb-diagnostic \
  --du-image horus/oai-gnb:cfra-retry-v2-diagnostic
```

The default Compose DUs remain the stock image. The release command clears
inherited overrides and records both actual DU image IDs. The 106 PRB profile,
20-slot response window, integrity, AI weights, gate and strict CU completion
requirements stay unchanged. This is an emulated-radio recovery experiment,
not field-network qualification, native CHO or an AI performance improvement.

Build with `docker build -t horus/oai-gnb:cfra-retry-v2-diagnostic
stack/oai-ho/du-cfra-retry`. The standalone recipe pins source and runtime image;
its OS package versions are not a bit-reproducible build promise. `BUILD.json`
records the actually tested incremental build, exact binary/source hashes and
qualification limits. Compilation and isolated C checks do not establish
operator, integrated or two-hour acceptance. Retain prior failed captures.

The recipe compiles and executes `test_cfra.py` against the actual patched
helper and idle-expiry C block. It covers CBRA refusal, the three-rearm limit,
finite idle expiry, no repeated release, active-RA preservation and four
numerologies. For an already patched source checkout, run
`python3 test_cfra.py /absolute/path/to/oai-source /fresh/check-output`.

`test_cfra_repeat.py` compiles the actual lookup, retention, valid-UL retirement
and timeout blocks. It covers cell/preamble matching, exclusive pointer/list
ownership, access-list rollback, limits, expiry, unchanged CBRA and double-free
refusal. AddressSanitizer and UndefinedBehaviorSanitizer also pass on those
isolated blocks. Full-stack qualification remains separately required.
