FROM oaisoftwarealliance/oai-nr-ue@sha256:d7ac8b9566488d6c4e5f04ae9a7a64a2693b3d6947f1045add7b44075176e119 AS build
USER root
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake ninja-build git ca-certificates pkg-config python3-dev \
    bison flex autoconf automake libtool libconfig-dev libsctp-dev libssl-dev \
    libyaml-cpp-dev libfftw3-dev libcap-dev libpcre2-dev libzstd-dev zlib1g-dev \
    libsimde-dev libboost-dev libboost-system-dev libboost-thread-dev libboost-program-options-dev \
    libreadline-dev wget curl xxd && rm -rf /var/lib/apt/lists/*
WORKDIR /oai-ran
RUN git init && git remote add origin https://github.com/OPENAIRINTERFACE/openairinterface5g.git \
    && git fetch --depth 1 origin cfee4c20b45ac1cf6d455d3f01bb3e00200438b0 \
    && git checkout --detach FETCH_HEAD \
    && test "$(git rev-parse HEAD)" = cfee4c20b45ac1cf6d455d3f01bb3e00200438b0
COPY patch_rrc.py /tmp/patch_rrc.py
RUN python3 /tmp/patch_rrc.py /oai-ran > /oai-rrc-patch.json
COPY patch_target_ssb.py test_target_ssb.py /tmp/
RUN python3 /tmp/patch_target_ssb.py /oai-ran
RUN python3 /tmp/test_target_ssb.py /oai-ran /target-ssb-unit-checks
RUN cd cmake_targets && ./build_oai --nrUE -w SIMU --ninja --noavx512 \
    --build-lib telnetsrv --build-tool-opt -j2 \
    --cmake-opt -DAUTO_DOWNLOAD_ASN1C=ON --cmake-opt -DENABLE_TESTS=OFF \
    --cmake-opt -DCMAKE_BUILD_TYPE=Release
RUN dpkg-query -W > /oai-build-packages.txt

FROM oaisoftwarealliance/oai-nr-ue@sha256:d7ac8b9566488d6c4e5f04ae9a7a64a2693b3d6947f1045add7b44075176e119
LABEL org.horus.scope="Diagnostic completion order and sole active target CFRA SSB selection; requires independent live qualification"
LABEL org.horus.oai.source="cfee4c20b45ac1cf6d455d3f01bb3e00200438b0"
COPY --from=build /oai-ran/cmake_targets/ran_build/build/nr-uesoftmodem /opt/oai-nr-ue/bin/nr-uesoftmodem
COPY --from=build /oai-ran/cmake_targets/ran_build/build/*.so /usr/local/lib/
COPY --from=build /oai-rrc-patch.json /oai-build-packages.txt /oai-ran/horus-target-ssb-patch.json /opt/horus/
RUN ldconfig && ldd /opt/oai-nr-ue/bin/nr-uesoftmodem
