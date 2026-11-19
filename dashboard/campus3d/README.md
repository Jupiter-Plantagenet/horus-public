# HORUS campus twin (`dashboard/campus3d/`)

A lightweight 3D twin of the Kumoh National Institute of Technology campus (금오공과대학교). It shows the
walk route, the moving device, the serving and target cells and each confirmed handover. Every view
is synchronised with the AI decision, the RAN execution stages and the interactive-service probes.
It runs offline: three.js r160 is vendored, there is no CDN and no build step, and the server uses only
the Python standard library.

## Run

```bash
python dashboard/campus3d/serve.py                    # http://127.0.0.1:8030/campus3d/   (REPLAY + SAMPLE)
python dashboard/campus3d/serve.py --capture OUT_DIR  # LIVE: tails release/run_demo.py's cycle-NNN/ captures, read-only
python dashboard/campus3d/serve.py --rehearse         # LIVE code path fed by recorded input; badge reads "LIVE · REHEARSAL"
```

In the demo, run `serve.py --capture` next to the release runner (native WSL) and point it at the
runner's output directory. Port 8030 is the default. On Windows the server refuses a port that is
already in use instead of silently double-binding it (the console uses 8020).

URL options: `scen=v314|seg0v314|seg0|walk|sample|live`, `lang=en|ko`, `view=hero|follow|overview|top`, `t=<s>`,
`speed=<n>`, `autoplay=0`, `quality=auto|high|low`, `embed=operator`, `minimap=0`.

| Key | Action |
|---|---|
| `Space` | play / pause |
| `←` `→` (`Shift` for 30 s) | seek ±5 s |
| `[` `]` | playback speed |
| `1`–`4` | camera: hero · follow · campus · top (dragging the scene switches to free orbit) |
| `V` | HORUS v3.14 (modelled, default) |
| `E` `W` `S` | executed handovers (v3.14.24 ⇄ v3.39.0) · full campus walk · sample |
| `R` | LIVE ⇄ REPLAY |
| `L` | 한국어 / English |
| `F` | full screen |
| `Home` | restart the scenario |

Clicking the minimap or the timeline seeks. Clicking a handover marker jumps to two seconds before it.

## Scenarios and what drives them

| Scenario | Mode | Inputs |
|---|---|---|
| **HORUS v3.14 (modelled)** (default) | REPLAY | The frozen v3.14.24 selector on the measured campus route (36-minute reverse lap), every arm on the same calibrated RSRP surface and time base: HORUS against network-wide CHO, MRO CHO and stock A3 (TwinSim, `build_v314.py`). The verdict panel shows the pre-registered results, including the failed ones: held-out H2 PASS (+0.147 vs network CHO), H1 not claimed (−0.016 vs the extended per-cell oracle), measured route H2 FAIL (−0.046 vs network CHO). |
| **Executed · v3.14.24** | REPLAY | Reverse-route segment 0 run live: the calibrated observation stream feeds the online v3.14.24 runtime, whose decisions become OAI F1 handovers between two DUs (emulated RF). The bounded acceptance cycle plus the 41 cycles of the two-hour acceptance (82/82 CU-confirmed, 2.05 h real), each selectable; decide → send → RIC ACK → CU RRC timings per handover (`working/evidence/live-v3.14/`). |
| **Executed · v3.39.0 (finals)** | REPLAY | The same live path with the central model that ran at the competition finals: bounded cycle plus 36 two-hour cycles (72 CU-confirmed handovers). |
| **Full campus walk** | REPLAY | The 36-minute reverse lap of the campus walk: the LG U+ network's own serving cell and its 38 observed cell changes, the calibrated per-cell RSRP, and the per-segment modelled comparison of HORUS v3.14.24 against network CHO, MRO CHO and stock A3. |
| **Sample** | SAMPLE | The real route geometry with synthetic radio, events and RTT. It exercises the paired HORUS/baseline lanes and the interruption display. Violet hatching and a SAMPLE DATA bar mark it; it is not a result. |
| **Live** | LIVE | `/api/campus3d/live`. Without frames the view shows WAITING. If the frame file stops growing for more than 2 s it shows STALE. It never falls back to recorded data. |
| **Console scene** | from the console | A `horus.twin-scene/1` sent by the operator console, which also drives the clock (see INTERFACE.md §0). |

Provenance appears as one chip that opens a per-value table with the tags `measured`, `calibrated`,
`modelled`, `emulated`, `recorded`, `approx`, `sample` and `pending`.

- **Real:** the OpenStreetMap footprints and names, the phone GNSS route, the serving cells and the recorded execution evidence.
- **Approximate:** building heights, because OSM has no levels for these buildings.
- **Cell anchors:** placed at the strongest measured point. The mast positions are unknown. The anchors are drawn as light pillars and never as towers.
- **Pending (shown as hatched lanes, never as zero or a pass):** the paired baseline execution and the service metrics that have not been delivered.
- **Gold handover state:** a handover turns gold only after scene time passes its CU RRC completion. Before that it shows cyan, as "in flight".

## Files

| Path | Role |
|---|---|
| `index.html`, `style.css` | Shell and theme: navy/gold/cyan from `submission/theme/theme.md`, tuned for projectors and 1280×720–1920×1080 |
| `js/main.js` | Boot, clocks (internal, LIVE, console-driven), both message protocols, keys |
| `js/scene.js` | three.js scene: merged OSM buildings, shader route ribbon, cell pillars, device, links, handover markers and effects, cameras, adaptive pixel ratio |
| `js/sources.js` | Normalises every source (REPLAY, walk, SAMPLE, LIVE, console scene, pushed feed) into one scenario model |
| `js/hud.js`, `js/minimap.js`, `js/i18n.js` | Panels, multi-lane timeline, 2D overview, EN/KO strings |
| `build_data.py` | Derives `data/*.json` from committed sources and records the input/output SHA-256 in `data/manifest.json`. `--check` verifies the bundle is up to date |
| `data/sources/osm-kumoh-20261104.json` | Overpass snapshot of the campus (ODbL), kept so the build stays offline and reproducible |
| `serve.py` | Static server rooted at `dashboard/`, plus the LIVE tail and rehearsal |
| `INTERFACE.md` | Integration contract with `dashboard/operator/` |
| `tests/test_campus3d.py` | 13 stdlib tests: bundle reproducibility and hashes, provenance invariants, replay consistency against VERIFICATION.json, live tailing (partial lines, freshness, malformed growth, static archives, cycle roll-over, failed or unconfirmed controls) |
| `tests/browser_check.py` | Playwright + installed Chrome. Runs every scenario at 1280×720 / 1920×1080 in EN/KO, embed mode with the console's own scene, and LIVE through rehearsal. Checks page/console errors, real WebGL output, overflow and protocol behaviour, and saves screenshots to `evidence/` |
| `vendor/` | three.js r160 `three.module.min.js` and `OrbitControls.js` (MIT, `LICENSE-three.txt`) |

Rebuild the data after committed inputs change: `python dashboard/campus3d/build_data.py`. The script
reads the walk epochs from `data/walktest/t4/epochs.jsonl` if that file exists, and otherwise from the
committed blob on `finals-measured-map`.

## Performance on the demo laptop (Intel HD 620)

- The scene is drawn with about 60 draw calls: all buildings are one merged mesh, the OCID sites are instanced, and there are no shadows or post-processing.
- Labels are DOM elements, and the timeline's static layer is cached.
- Pixel ratio starts at ≤ 1.5 and adapts: it steps down to 0.75 when the average frame time exceeds 26 ms. `quality=low` forces ratio 1 without antialiasing.
- The browser harness records the actual renderer. The November 4 verification used installed Chrome on Intel HD 620 via D3D11, rather than software WebGL.

## Verification and data boundaries

```bash
python -m unittest discover -s dashboard/campus3d/tests -p test_campus3d.py -q
python dashboard/campus3d/build_data.py --check          # needs the walk trace (not in the public release)
python -u dashboard/campus3d/tests/browser_check.py --self-serve --out /tmp/campus3d-check
```

The v3.14 views were verified in headless Chromium (EN/KO, 1280×720 and 1920×1080, no page errors, no
overflow): `working/evidence/console-v3.14/` (screenshots, `browser_check.mjs`, `results.json`).

The browser command starts two temporary local servers and a single Chrome instance, then cleans
them up. It checks EN/KO and both screen sizes, offline assets, the console protocol, LIVE rehearsal,
stopped external/pushed LIVE clocks, duplicate frames, detached polling and missing CU timestamps.
Screenshots from rehearsal and fabricated protocol fixtures remain UI checks, never runtime receipts.

Historical execution uses ICMP probes and is labelled accordingly. The full walk has no application
traffic measurement. Neither view establishes video-call performance or a new federated benefit.
The historical central artifact identity cannot be replaced by a status update for an experimental
federated checkpoint. Missing artifact identity stays pending. LIVE keeps its last received state
after a stall, freezes its clock and marks service unknown; it cannot turn an archived capture fresh
merely by loading it.
