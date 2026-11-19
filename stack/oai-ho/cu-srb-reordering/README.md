# Explicit CU signalling reorder timer for the emulated laboratory

Status: the 36-control operator probe passed, including two natural sequence-gap
recoveries; integrated acceptance is pending. Evidence:
`working/evidence/signalling-recovery-20261104/RECOVERY.json`.
This directory does not enable a radio override or qualify an image by itself.

The stock 2026.w43 profile stalled after an uplink SRB1 sequence gap: the CU
received RRCReconfigurationComplete SN 63, but SN 62 was absent and its last
in-order delivery cursor remained 62. Default SRB PDCP reordering waits forever.
This patch opts the local CU's SRB receive entities into the existing 1,000 ms
PDCP reorder timer. It leaves integrity checks, PDCP sequence accounting,
security algorithms and completion verification intact. It does not establish
why the source-DU PDU was lost or implement source-DU signalling forwarding.

The stock UE and both DUs stay unchanged. No AI, gate, RF bandwidth or twin
parameter changes are part of this patch. The unsuccessful prior UE completion
timing experiment is explicitly absent. This is an emulated-lab workaround;
there is no field-network or native RRC CHO qualification.

## Build

From the repository root, with Docker:

```sh
docker build -t horus/oai-gnb:srb-reorder-diagnostic stack/oai-ho/cu-srb-reordering
```

Both base images and OAI source are pinned by digest/commit. The UE image is
used only as a build environment; the output is the pinned gNB runtime image
with its rebuilt CU-capable nr-softmodem binary. The patch checks the source
file hash and permits only its one source-file diff. The source-pinned FlexRIC
submodule and upstream E2AP v3/KPM v3 settings are retained. Build package
versions and before/after patch hashes are stored under /opt/horus/. OS package
repositories remain external build dependencies; bit-identical fresh builds
are not claimed. Runtime acceptance binds the actual image ID and source hashes.

## Explicit selection

The normal Compose profile keeps the upstream image. The release runner clears
inherited radio overrides and requires both options together:

```sh
python release/spooled_demo.py --root /path/to/assembly --out /new/durable/capture \
  --live --cu-image horus/oai-gnb:srb-reorder-diagnostic --cu-srb-reordering-ms 1000
```

The diagnostic binary accepts only the exact opt-in environment value
HORUS_LAB_SRB_REORDERING_MS=1000. Its absence keeps the upstream infinite default;
an unsupported value refuses. The release Compose mapping supplies an empty
value unless explicitly selected, so selecting this diagnostic image alone
is intentionally refused by the runner. Both flags are recorded, along with
the actual CU and UE image IDs. No flag constitutes a passing qualification.
Keep all prior failed captures and require fresh CU RRC proof for every control.

Upstream:
https://github.com/OPENAIRINTERFACE/openairinterface5g/tree/cfee4c20b45ac1cf6d455d3f01bb3e00200438b0/openair2/LAYER2/nr_pdcp
