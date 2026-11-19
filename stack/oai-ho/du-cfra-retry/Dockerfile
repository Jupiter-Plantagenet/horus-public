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
COPY patch_cfra.py /tmp/patch_cfra.py
COPY test_cfra.py /tmp/test_cfra.py
RUN python3 /tmp/patch_cfra.py /oai-ran
RUN python3 /tmp/test_cfra.py /oai-ran /cfra-unit-checks
COPY patch_cfra_repeat.py test_cfra_repeat.py /tmp/
RUN python3 /tmp/patch_cfra_repeat.py /oai-ran
RUN python3 /tmp/test_cfra_repeat.py /oai-ran /cfra-repeat-unit-checks
RUN git -C /oai-ran submodule update --init --depth 1 openair2/E2AP/flexric
RUN cd /oai-ran/cmake_targets && ./build_oai --gNB -w SIMU --ninja --noavx512 \
    --build-e2 --build-lib telnetsrv --build-tool-opt -j2 \
    --cmake-opt -DE2AP_VERSION=E2AP_V3 --cmake-opt -DKPM_VERSION=KPM_V3_00 \
    --cmake-opt -DAUTO_DOWNLOAD_ASN1C=ON --cmake-opt -DENABLE_TESTS=OFF \
    --cmake-opt -DCMAKE_BUILD_TYPE=Release
RUN dpkg-query -W > /oai-build-packages.txt
FROM oaisoftwarealliance/oai-gnb@sha256:b7554483225068fa9c6a03032507b00fc2c663786c436fe61ea89b956fdb4850
LABEL org.horus.scope="Experimental finite CFRA retries until valid UL; not runtime qualified"
LABEL org.horus.oai.source="cfee4c20b45ac1cf6d455d3f01bb3e00200438b0"
COPY --from=build /oai-ran/cmake_targets/ran_build/build/nr-softmodem /opt/oai-gnb/bin/nr-softmodem
COPY --from=build /oai-ran/horus-cfra-patch.json /oai-ran/horus-cfra-repeat-patch.json /oai-build-packages.txt /opt/horus/
RUN ldd /opt/oai-gnb/bin/nr-softmodem
