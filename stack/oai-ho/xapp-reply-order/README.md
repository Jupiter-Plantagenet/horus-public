# xApp request/reply ordering correction

The debugger probe failed after 55 strict completions. Its receiver was removing
a pending control event in the red-black tree while the sender was still adding
that event. The resulting minimum(NULL) crashed the xApp after CONTROL ACK rx.
Original failed probes and the backtrace remain in
working/evidence/xapp-reply-order-20261104/.

This opt-in image rebuilds only the handover xApp from pinned FlexRIC v3.0.0
commit 18c3325091ad6890a706ebb2bba38d3c0fb741e5. Setup, subscription-delete and
control pending events register before transmission. Synchronous reply state
arms before each request, so a fast ACK is preserved. Missing/rejected replies
terminate the xApp without claiming acknowledgement, including Release builds
where upstream assertions are disabled. Original timeouts are preserved.
The near-RT RIC executable, shared service models and RAN images are unchanged.

Tests compile the three actual changed handlers with a transport that can reply
inside send(), and the actual pthread wait implementation. All three original
handlers fail that immediate-ACK test. Nine delivery cases and five reply-state
cases pass normally and with ASan/UBSan. This is not sanitizer qualification of
the complete RIC or ASN.1 codecs. Actual operator/integrated/sustained results
must be recorded separately; no PASS follows from compilation alone.

Select explicitly with --flexric-image horus/oai-flexric:reply-order-diagnostic.
The release runner clears inherited overrides and records the actual RIC image
ID and handover binary SHA-256. Models, gate, integrity, 106 PRB, response window,
retry limits, freshness and matching-CU completion checks remain unchanged.
No model training or final/audit evaluation is performed.

Build context: stack/oai-ho. The default runtime parent is the exact local
original HORUS image ID recorded in BUILD.json; load the archived base images
first. A different parent/rebuild needs its own identity and qualification.

    docker build -f stack/oai-ho/xapp-reply-order/Dockerfile \
      -t horus/oai-flexric:reply-order-diagnostic stack/oai-ho

The actual build used a fresh pinned-source/toolchain bootstrap followed by the
candidate build. The combined single-build recipe was not separately reexecuted.
Dependencies are inventoried in the image; only source/compiler major versions
are pinned. Restore the archived image for the tested bytes.
