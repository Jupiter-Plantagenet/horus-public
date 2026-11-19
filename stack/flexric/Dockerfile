# FlexRIC (EURECOM near-RT RIC) built for interop with the srsRAN Project gNB.
#
# Version pinning is load-bearing: FlexRIC MUST be built to the same E2AP/KPM
# version the gNB emits, or E2 setup fails. The authority is the gNB binary's
# RAN-function OIDs, not the docs:
#   KPM OID 1.3.6.1.4.1.53148.1.2.2.2  -> E2SM-KPM v2.03  (version digit = 2)
#   RC  OID 1.3.6.1.4.1.53148.1.1.2.3  -> E2SM-RC v1
# So this srsRAN 24_04 image speaks KPM v2.03 (NOT v3.00). We pin the current
# br-flexric tip (7365081), whose CMake accepts KPM_V2_03; the older commit the
# srsRAN tutorial names (1a3903a7) uses different version tokens and rejects it.
# Default E2AP is v2.03 (E2AP_V2), which the gNB's E2AP-PDU matches, so we do NOT
# override -DE2AP_VERSION. gcc-10 forces the 22.04 base (not packaged on 24.04).
#
# Reproducibility: the load-bearing versions are pinned (FLEXRIC_COMMIT, KPM_V2_03,
# swig==4.2.1). The ubuntu:22.04 base tag and apt packages are intentionally NOT
# version-locked — locking apt versions breaks the build as the Ubuntu archive
# rotates, for no interop benefit here.
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive TZ=UTC

RUN apt-get update && apt-get install -y --no-install-recommends \
      git build-essential cmake cmake-curses-gui pkg-config \
      gcc-10 g++-10 \
      python3 python3-dev python3-pip \
      libsctp-dev lksctp-tools \
      libconfig-dev libconfig++-dev \
      ca-certificates \
      iproute2 iputils-ping bind9-host \
    && rm -rf /var/lib/apt/lists/*

# FlexRIC requires gcc-10 (not the distro default). Make it the default toolchain.
RUN update-alternatives --install /usr/bin/gcc gcc /usr/bin/gcc-10 100 \
 && update-alternatives --install /usr/bin/g++ g++ /usr/bin/g++-10 100

# FlexRIC's Python xApp SDK needs SWIG >= 4.1, but Ubuntu 22.04 ships 4.0.2.
# PyPI's `swig` package bundles a prebuilt SWIG 4.2 binary (installed to
# /usr/local/bin, which precedes /usr/bin on PATH -> FlexRIC's FindSWIG picks it).
RUN pip3 install --no-cache-dir "swig==4.2.1" \
 && swig -version

# br-flexric tip as of 2026-07-15; bump deliberately, never silently.
ARG FLEXRIC_COMMIT=7365081
WORKDIR /opt
RUN git clone https://gitlab.eurecom.fr/mosaic5g/flexric.git \
 && cd flexric \
 && git checkout "${FLEXRIC_COMMIT}" \
 && git submodule update --init --recursive

# --- HORUS resilience patch (2026-07-15) -------------------------------------
# srsRAN's gNB E2SM-KPM intermittently fails to ASN.1-encode a KPM indication yet
# transmits the malformed PDU anyway ("Encoding failure ... Sending E2 indication").
# Stock FlexRIC then ABORTS on a decode assertion in kpm_dec_ind_msg_asn()
# ("Are you sending data in ATS_ALIGNED_BASIC_PER syntax?"), crashing the near-RT
# RIC and permanently dropping the gNB's E2 (srsRAN never reconnects) — the live
# stack died ~every 13 min. A RIC must not die on one bad message: patch the KPM
# *indication-message* decoder to SKIP a malformed PDU (return an empty FORMAT_1
# message) instead of asserting.
# NB: the same assert text appears in three functions in this file (event-trigger
# decode ~L55, indication-message decode L184, func-def decode ~L229) but only the
# message decoder returns a kpm_ind_msg_t (with .type) — so we patch L184 ONLY.
# The other two run once at subscription time; a malformed PDU there should still
# fail loudly. Commit is pinned => L184 is stable; the sed-guard verifies it.
RUN F=/opt/flexric/src/sm/kpm_sm/kpm_sm_v02.03/dec/kpm_dec_asn.c \
 && sed -n '184p' "$F" | grep -q 'Are you sending data in ATS_ALIGNED_BASIC_PER' \
 && sed -i '184s|.*|  if (rval.code != RC_OK) { ASN_STRUCT_FREE_CONTENTS_ONLY(asn_DEF_E2SM_KPM_IndicationMessage, pdu); free(pdu); ret.type = FORMAT_1_INDICATION_MESSAGE; return ret; }|' "$F" \
 && grep -q 'rval.code != RC_OK' "$F" \
 && echo 'HORUS: patched kpm_dec_ind_msg_asn (L184) to skip malformed KPM indications'

# --- HORUS resilience patch 2 (2026-07-16) ------------------------------------
# When the KPM xApp restarts (e.g. its stall watchdog fired), the subscription
# teardown can make the gNB answer with RIC Subscription Delete FAILURE. FlexRIC
# fences its decoder for that message behind `assert(0!=0 && "Untested code")`
# (e2ap_msg_dec_asn.c:844) — so the near-RT RIC ABORTS on a valid E2AP reply,
# dropping the gNB's E2 permanently (srsRAN never reconnects). Observed live at
# the ~8.7h stall and the 07:31Z Jul-16 crash-loop. Remove the outer assert so
# the decode logic runs. NB: "Untested code" was accurate — patch 3 below fixes
# the actual bugs that assert was hiding.
RUN F=/opt/flexric/src/lib/e2ap/v2_03/dec/e2ap_msg_dec_asn.c \
 && sed -n '844p' "$F" | grep -q 'Untested code' \
 && sed -i '844s|.*|  /* HORUS: removed upstream untested-code assert - see patch 3 for the field-level fixes it was hiding. */|' "$F" \
 && sed -n '844p' "$F" | grep -q 'HORUS' \
 && echo 'HORUS: patched e2ap_dec_subscription_delete_failure (L844) to decode instead of abort'

# --- HORUS resilience patch 3 (2026-07-18) ------------------------------------
# With patch 2's outer guard gone, the delete-failure decoder ran on into two
# genuine upstream bugs and crashed the RIC anyway (e2ap_msg_dec_asn.c:875) —
# hit live ~13:33Z Jul-18 when the xApp crash-looped under CPU pressure, wedging
# a ~52h run until the watchdog recovered it.
#   L875: `assert(array[2]->id == RICactions_NotAdmitted)` is a copy-paste from
#         the *subscription*-failure decoder. In a Delete Failure array[2] is the
#         Cause IE (the very next line does df->cause = copy_cause(...) on it),
#         so a spec-correct srsRAN reply trips it. Drop the wrong id-assert; the
#         `value.present == _PR_Cause` assert right below is the correct guard.
#   L886: `assert(0 && "Not implemented")` in the OPTIONAL CriticalityDiagnostics
#         branch (only entered when the gNB sends a 4th IE) — make it a no-op so
#         the optional IE is skipped, not fatal.
# Both are on the rare teardown error path; the E2-setup/subscribe/indication
# decoders that carry live KPM are untouched. Pinned commit => lines stable.
RUN F=/opt/flexric/src/lib/e2ap/v2_03/dec/e2ap_msg_dec_asn.c \
 && sed -n '875p' "$F" | grep -q 'act_not_adm->id == ProtocolIE_ID_id_RICactions_NotAdmitted' \
 && sed -i '875s|.*|  /* HORUS: FlexRIC copy-paste bug - array[2] here is the Cause IE (decoded next line), NOT RICactions_NotAdmitted; the value.present == _PR_Cause assert below is the correct check. */|' "$F" \
 && sed -n '886p' "$F" | grep -q 'Not implemented' \
 && sed -i '886s|.*|  /* HORUS: optional CriticalityDiagnostics not decoded - skip, do not abort the RIC on the teardown path. */|' "$F" \
 && sed -n '875p' "$F" | grep -q 'HORUS' && sed -n '886p' "$F" | grep -q 'HORUS' \
 && echo 'HORUS: patched e2ap_dec_subscription_delete_failure field bugs (L875 id, L886 crit-diag)'

WORKDIR /opt/flexric/build
RUN cmake -DKPM_VERSION=KPM_V2_03 -DXAPP_DB=NONE_XAPP .. \
 && make -j"$(nproc)" \
 && make install \
 && ldconfig

# --- HORUS finals actuation (2026-10-30) -------------------------------------
# Layered AFTER the validated KPM build so the docker cache keeps those layers
# and this is an incremental rebuild (only the touched objects recompile).
#  * patch 4: a RIC Control FAILURE / E2 Error Indication from the gNB must not
#    abort the near-RT RIC (see patches/patch4_rc_ctrl_failure.py for the why).
#  * xapp_horus_rc: long-lived E2SM-RC Style 2 / Action 6 (slice-level PRB quota)
#    control xApp driven over stdin by stack/actuation/horus_actuator.py.
COPY patches/patch4_rc_ctrl_failure.py /tmp/patch4_rc_ctrl_failure.py
COPY xapp_horus_rc.c /opt/flexric/examples/xApp/c/control/xapp_horus_rc.c
COPY xapp_horus_rc.cmake /tmp/xapp_horus_rc.cmake
RUN python3 /tmp/patch4_rc_ctrl_failure.py /opt/flexric \
 && cat /tmp/xapp_horus_rc.cmake >> /opt/flexric/examples/xApp/c/control/CMakeLists.txt \
 && cd /opt/flexric/build \
 && cmake .. \
 && make -j"$(nproc)" \
 && make install \
 && ldconfig \
 && test -x /opt/flexric/build/examples/xApp/c/control/xapp_horus_rc \
 && echo 'HORUS: built xapp_horus_rc + patched RIC'

# The service models FlexRIC dlopen()s at runtime live here after `make install`.
# Both the RIC and the xApps read them; keep the path stable.
ENV FLEXRIC_SM_DIR=/usr/local/lib/flexric

# SIGSTOP/SIGCONT and ordinary signals can interrupt epoll_wait. Retry EINTR,
# retaining the assertion for genuine wait errors (runtime fault acceptance).
COPY patches/patch5_epoll_eintr.py /tmp/patch5_epoll_eintr.py
COPY tests/epoll_eintr.c /tmp/epoll_eintr.c
RUN python3 /tmp/patch5_epoll_eintr.py /opt/flexric \
 && cc -Wall -Wextra -I/opt/flexric/src/xApp /tmp/epoll_eintr.c /opt/flexric/src/xApp/asio_xapp.c -o /tmp/test_epoll_eintr \
 && /tmp/test_epoll_eintr \
 && cmake --build /opt/flexric/build -j2 \
 && cmake --install /opt/flexric/build \
 && ldconfig

# Default command runs the near-RT RIC; compose overrides this for the xApp.
CMD ["/opt/flexric/build/examples/ric/nearRT-RIC"]
