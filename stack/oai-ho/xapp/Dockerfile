# HORUS handover xApp on top of the upstream OAI FlexRIC v3.0.0 image.
#
# Builds ONE extra binary (xapp_horus_ho, see xapp_horus_ho.c) from the same
# FlexRIC tag the image was built from, with the same E2AP/KPM versions and
# compiler as docker/Dockerfile.flexric.ubuntu in that tag, and adds it next to
# the stock xApps. The near-RT RIC binary and service models are untouched.
#   docker build -t horus/oai-flexric:v3.0.0-horus stack/oai-ho/xapp
ARG FLEXRIC_TAG=v3.0.0

FROM ubuntu:jammy AS build
ARG FLEXRIC_TAG
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install --yes --no-install-recommends \
      build-essential libsctp-dev git ca-certificates m4 automake autoconf libtool \
      python3 cmake bison flex libpcre2-dev gcc-12 g++-12 ninja-build \
    && rm -rf /var/lib/apt/lists/*
# asn1c fork + commit pinned by FlexRIC's own Dockerfile (F1AP codec for the xApp)
RUN git clone https://github.com/mouse07410/asn1c /tmp/asn1c \
 && cd /tmp/asn1c && git checkout 940dd5fa9f3917913fd487b13dfddfacd0ded06e \
 && autoreconf -iv && ./configure --prefix /opt/asn1c/ && make -j"$(nproc)" && make install
RUN git clone --depth 1 --branch ${FLEXRIC_TAG} https://github.com/duranta-project/flexric.git /flexric
COPY xapp_horus_ho.c /flexric/examples/xApp/c/rc_handover/xapp_horus_ho.c
RUN printf '\nadd_executable(xapp_horus_ho xapp_horus_ho.c ../../../../src/util/alg_ds/alg/defer.c)\ntarget_link_libraries(xapp_horus_ho PUBLIC e42_xapp asn1_f1ap -pthread -lsctp -ldl)\n' \
      >> /flexric/examples/xApp/c/rc_handover/CMakeLists.txt \
 && mkdir /flexric/build && cd /flexric/build \
 && cmake -GNinja -DCMAKE_BUILD_TYPE=Release -DE2AP_VERSION=E2AP_V3 -DKPM_VERSION=KPM_V3_00 \
          -DCMAKE_C_COMPILER=gcc-12 -DCMAKE_CXX_COMPILER=g++-12 .. \
 && ninja xapp_horus_ho \
 && ls -la examples/xApp/c/rc_handover/xapp_horus_ho

FROM oaisoftwarealliance/oai-flexric:${FLEXRIC_TAG}
COPY --from=build /flexric/build/examples/xApp/c/rc_handover/xapp_horus_ho /usr/local/flexric/xApp/c/rc_handover/xapp_horus_ho
