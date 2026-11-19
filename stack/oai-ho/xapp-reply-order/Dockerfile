ARG RUNTIME_BASE=12a652edf98631a1b0d2e1cf7f3077f4f9e2ae55c6088a3a0bb1fd00549910e8
FROM ubuntu:jammy AS build
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends build-essential libsctp-dev git ca-certificates m4 automake autoconf libtool python3 cmake bison flex libpcre2-dev gcc-12 g++-12 ninja-build && rm -rf /var/lib/apt/lists/*
RUN git init /tmp/asn1c && cd /tmp/asn1c && git remote add origin https://github.com/mouse07410/asn1c && git fetch --depth 1 origin 940dd5fa9f3917913fd487b13dfddfacd0ded06e && git checkout --detach FETCH_HEAD && autoreconf -iv && ./configure --prefix /opt/asn1c/ && make -j2 && make install
RUN git init /flexric && cd /flexric && git remote add origin https://github.com/duranta-project/flexric.git && git fetch --depth 1 origin 18c3325091ad6890a706ebb2bba38d3c0fb741e5 && git checkout --detach FETCH_HEAD && test "$(git rev-parse HEAD)" = 18c3325091ad6890a706ebb2bba38d3c0fb741e5
COPY xapp-reply-order/patch_reply_order.py xapp-reply-order/test_reply_order.py /tmp/
RUN python3 /tmp/patch_reply_order.py /flexric
RUN python3 /tmp/test_reply_order.py /flexric /reply-order-unit-checks
COPY xapp/xapp_horus_ho.c /flexric/examples/xApp/c/rc_handover/xapp_horus_ho.c
RUN printf '\nadd_executable(xapp_horus_ho xapp_horus_ho.c ../../../../src/util/alg_ds/alg/defer.c)\ntarget_link_libraries(xapp_horus_ho PUBLIC e42_xapp asn1_f1ap -pthread -lsctp -ldl)\n' >> /flexric/examples/xApp/c/rc_handover/CMakeLists.txt && cmake -S /flexric -B /flexric/build -GNinja -DCMAKE_BUILD_TYPE=Release -DE2AP_VERSION=E2AP_V3 -DKPM_VERSION=KPM_V3_00 -DCMAKE_C_COMPILER=gcc-12 -DCMAKE_CXX_COMPILER=g++-12 && ninja -C /flexric/build -j2 xapp_horus_ho
RUN dpkg-query -W > /build-packages.txt
FROM ${RUNTIME_BASE}
LABEL org.horus.scope="Opt-in xApp pending-before-TX and early-reply/fail-closed correction; independent qualification required"
COPY --from=build /flexric/build/examples/xApp/c/rc_handover/xapp_horus_ho /usr/local/flexric/xApp/c/rc_handover/xapp_horus_ho
COPY --from=build /flexric/horus-xapp-reply-order-patch.json /build-packages.txt /opt/horus/
COPY --from=build /reply-order-unit-checks/receipt.json /opt/horus/reply-order-unit-checks.json
RUN ldd /usr/local/flexric/xApp/c/rc_handover/xapp_horus_ho
