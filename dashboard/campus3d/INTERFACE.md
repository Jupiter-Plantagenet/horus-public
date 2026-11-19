# campus3d ⇄ operator interface (v1)

Owner: 3D agent (`dashboard/campus3d/`). Consumer: operator console (`dashboard/operator/`).
Status: **stable for integration**. Additive changes only; anything breaking bumps `/1` → `/2`.

The 3D campus twin is a self-contained page. The console embeds it with an iframe and
talks to it with `postMessage`. No build step, no shared JS module state, no CDN.

## 0. The console's protocol `horus.twin/1` is implemented as-is (preferred)

The twin implements `dashboard/operator/INTERFACE.md` (console = clock master) without
changes on the console side. Verified in a browser with the console's own
`operator/data/twin-scene.example.json` (see `tests/browser_check.py`, case `embed-operator`).

| console → twin | twin behaviour |
|---|---|
| `horus.twin.scene {scene}` | Builds the scene from `route.points` (`t_s,lat,lon,x_m,y_m`), `cells[].anchor` (x/y), `arms.{horus,baseline}`. Switches to the console clock. Non-catalogue anchors render as light pillars + ground rings, never as masts. |
| `horus.twin.tick {t, playing, rate, mode, arm, live?}` | Scene time = `t` (+ `rate`·elapsed while `playing`). `mode` drives the badge. `arm` selects which arm's serving link/route colour is primary; the other arm is drawn as a dim slate link and offset markers. In LIVE, `live.stale: true` freezes the last state immediately; missing ticks for more than 2 s also freezes it as STALE. `live.age_s` and `live.rehearsal` are preserved. |
| `horus.twin.focus {event_id}` | Pulses that event marker. |
| `horus.twin.view {preset}` | `overview` → campus, `follow` → chase camera, `cell` → hero. Also `top`, `hero`. |
| `horus.twin.lang {lang}` | `en` / `ko`. |

Twin → console: `horus.twin.ready {version:"campus3d/1", capabilities}` after load;
`horus.twin.pick {event_id? | cell_id? | t?}` on clicks (3D markers, cell beacons, minimap);
`horus.twin.status {fps, quality}` every 5 s and `{message}` on load errors.

Event `status` handling: `confirmed` gets the gold treatment **only once scene time passes
the CU completion time** (`t + (decision_to_send_ms + control_to_cu_ms)/1000`); before
that it is cyan "in flight". `acked`/`attempted` stay cyan, `failed` crimson, `modelled`
slate (dashed label), never gold.

The completion interval must be a finite, nonnegative number and cannot precede the ACK.
Missing completion times never default to the decision time. An unresolved action retains its
source/target relationship until a later event supersedes it.

Scene `traffic: {kind, label?}` supplies the device label: `icmp_probe`, `interactive_video`, or
`none`/`walk`. Missing traffic becomes "service not provided". Scene `artifact` identifies the
executed model; an absent identity is pending. A `setStatus` for a new candidate cannot overwrite
the built-in historical central replay identity. Geometry supplied from a recording remains
recorded geometry even when the control observations are LIVE.

Embed with `?embed=operator` (hides the twin's own chrome; keeps the mode badge,
provenance chip, minimap and a compact serving→target pill). Until a `horus.twin.scene`
arrives it shows its own recorded REPLAY so the frame is never blank.

Sections 1–6 below describe the twin's own commands/feed, used for standalone operation,
for LIVE (`serve.py --capture`), and by any client that prefers to push data.

## 1. Embed

```html
<!-- from dashboard/operator/index.html -->
<iframe id="twin" src="../campus3d/index.html?embed=1&lang=en&mode=replay"
        title="HORUS campus twin" allow="fullscreen"></iframe>
```

Both folders must be served from the same origin with `dashboard/` as the web root
(`python dashboard/campus3d/serve.py` does this, port 8030; any static server rooted at
`dashboard/` also works for REPLAY/SAMPLE). Opening `index.html` from `file://` is not
supported (browsers block module/JSON loads there).

| Query param | Values | Default | Meaning |
|---|---|---|---|
| `embed` | `1` | off | Hide the standalone header/side HUD; keep the scene, minimap, mode badge, provenance chip and serving/target chip. The console owns model/gate/timeline chrome. |
| `mode` | `live` `replay` `sample` | `replay` | Initial data mode (see §3). |
| `lang` | `en` `ko` | `en` | Labels. Key terms are always bilingual. |
| `view` | `hero` `follow` `overview` `top` | `hero` | Initial camera. |
| `speed` | `1` `2` `4` `8` `16` | `1` | REPLAY/SAMPLE playback rate. |
| `t` | seconds | start | REPLAY/SAMPLE start time in scenario seconds. |
| `quality` | `auto` `high` `low` | `auto` | `auto` measures frame time and steps down for Intel HD 620-class GPUs. |
| `feed` | URL | — | LIVE feed URL (default `/api/campus3d/live`). |
| `autoplay` | `0`/`1` | `1` | Start playing immediately. |

## 2. Messages

All messages are plain objects with `type` and a protocol tag `v: 1`. The frame only
accepts messages from `window.parent` and from the same origin.

### Console → twin (`type: "horus.campus3d.command"`)

```json
{"type":"horus.campus3d.command","v":1,"cmd":"setMode","mode":"replay"}
{"type":"horus.campus3d.command","v":1,"cmd":"setLang","lang":"ko"}
{"type":"horus.campus3d.command","v":1,"cmd":"play"}
{"type":"horus.campus3d.command","v":1,"cmd":"pause"}
{"type":"horus.campus3d.command","v":1,"cmd":"seek","t_s":150.0}
{"type":"horus.campus3d.command","v":1,"cmd":"setSpeed","speed":4}
{"type":"horus.campus3d.command","v":1,"cmd":"setView","view":"follow"}
{"type":"horus.campus3d.command","v":1,"cmd":"setQuality","quality":"low"}
{"type":"horus.campus3d.command","v":1,"cmd":"focusEvent","id":"rec-ho-1"}
{"type":"horus.campus3d.command","v":1,"cmd":"pushFeed","feed":{ "...": "horus.campus3d.feed/1, §4" }}
{"type":"horus.campus3d.command","v":1,"cmd":"setStatus","status":{ "...": "§5" }}
```

`pushFeed` lets the console become the data source (for example when it already polls
`/api/state`). A pushed feed replaces the built-in source until `setMode` is sent again.

### Twin → console (`type: "horus.campus3d.event"`)

```json
{"type":"horus.campus3d.event","v":1,"kind":"ready","modes":["live","replay","sample"],"scenario":{"id":"t4-reverse-seg0","duration_s":186.1}}
{"type":"horus.campus3d.event","v":1,"kind":"tick","mode":"replay","t_s":153.7,"duration_s":186.1,"playing":true,"speed":1,
 "segment":"reverse-supported-0","step":1536,"serving":"LTE/450/6/36154379/100","target":null,
 "position":{"x_m":12.4,"y_m":288.1},"service":{"rtt_ms":131,"state":"ok"}}
{"type":"horus.campus3d.event","v":1,"kind":"event","id":"rec-ho-1","phase":"cu_confirmed","t_s":158.5,
 "from":"LTE/450/6/36153880/100","to":"LTE/450/6/36154379/100"}
{"type":"horus.campus3d.event","v":1,"kind":"modeChanged","mode":"sample"}
{"type":"horus.campus3d.event","v":1,"kind":"feedStatus","mode":"live","state":"waiting","detail":"no frames yet"}
```

`tick` is sent at ≤ 4 Hz. Use `t_s` as the shared scenario clock: the console's
service/command timeline should render the same `t_s` so the scene and the timeline
never disagree. Event `phase` is one of `decision`, `ack`, `cu_confirmed`, `failed`.

## 3. Modes (distinct meanings, distinct colours)

| Mode | Badge | Meaning | Source |
|---|---|---|---|
| `LIVE` | emerald, pulsing | Frames arriving now from a running session. Staleness > 2 s turns the badge grey `STALE`; no frames ⇒ `WAITING`. Never falls back to recorded data silently. | `serve.py --capture DIR` → `/api/campus3d/live`, or `pushFeed` |
| `REPLAY` | amber | A recorded, hash-referenced session replayed on a virtual clock. Labelled with the recording date and session. | `data/replay-*.json` (built from `working/evidence/`) |
| `SAMPLE` | violet, hatched | Synthetic data that exercises the UI (federated artifact slot, interruptions, gate states). Never a result. | generated in-browser, seeded |

## 4. Feed: `horus.campus3d.feed/1`

Compact, columnar. See `interface/feed.example.json` for a complete small example.

```jsonc
{
  "format": "horus.campus3d.feed/1",
  "mode": "replay",                       // live | replay | sample
  "label": "Recorded 2026-11-02 live acceptance · v3.39.0",
  "provenance": {"kind":"recorded","source":"working/evidence/...","sha256":"..."},
  "scenario": {"id":"t4-reverse-seg0","route":"t4-reverse","segment":"reverse-supported-0",
               "step0":0,"dt_s":0.1,"duration_s":186.1},
  "cells": ["LTE/450/6/36153880/100", "..."],      // index space for serving/rsrp below
  "frames": {                                      // one entry per 0.1 s (or sparser)
    "t_s":   [0.1, 0.2],
    "step":  [0, 1],                               // route step → position (route.json)
    "serving":[0, 0],                              // index into cells, -1 = none
    "rsrp":  [[-91.4,-93.9,-99.7,-101.5,-100.5], [...]],   // dBm, null = unsupported
    "sinr_db":[3.27, 3.27]
  },
  "events": [ {"id":"rec-ho-1","t_s":153.6,"from":0,"to":2,
               "phases":{"decision":153.6,"ack":153.65,"cu_confirmed":158.4},
               "profile":{"index":31,"prep_offset_db":-6,"exec_offset_db":0,"hys_db":2,"ttt_s":0},
               "evidence":{"ric_ack_ms":45.9,"decision_to_cu_ms":3807.6,"source_du":"3584","target_du":"3585"}} ],
  "service": {"rtt": [[t_s, ms], ...], "interruptions": [[t0_s, t1_s], ...], "throughput_mbps": [[t_s, v], ...]},
  "comparison": null | {"reference":"a3_stock","events":[...same shape...],"service":{...},
                        "provenance":{...}}      // paired baseline on identical t_s/workload
}
```

Rules the twin enforces: missing `service`/`comparison` is shown as *pending*, never as
zero or as a pass; events without `cu_confirmed` render as unconfirmed (open ring, no gold).

## 5. Status block (optional, `setStatus`)

The console owns the model / federation / gate story. If it sends this block the twin
shows a compact chip; if it never does, the chip says `artifact status: not provided`.

```json
{"artifact":{"version":"v3.39.0","kind":"central","label":"Released actor (central MLP CHO-profile selector)"},
 "federation":{"state":"pending","rounds":null,"clients":null},
 "gate":{"state":"pending","receipt":null}}
```

`kind`: `central` | `federated`. `state`: `pending` | `running` | `pass` | `fail` | `n/a`.
The twin never derives `pass` itself.

## 6. LIVE endpoint (`serve.py`)

`GET /api/campus3d/live?after=<seq>` → `horus.campus3d.feed/1` with `frames` after
`seq`, all `events` of the current cycle, recent `service.rtt`, plus
`"live":{"cycle":"cycle-007","newest_source_ts":"...","age_s":0.4,"stale":false}`.
It tails the release runner's capture layout read-only:
`<capture>/cycle-NNN/frames.jsonl`, `driver/decisions.jsonl`, `driver/timed-actions.jsonl`,
`dashboard/metrics/rtt.jsonl`.

An initial archived file is stale until a subsequent valid frame is appended. Malformed growth
does not prove freshness. Clients also require distinct advancing frame sequence/time values;
repeated snapshots cannot keep a stopped source LIVE. Stopping or replacing a source aborts its
poll and prevents a late response from restarting it. The last received state stays visible under
a STALE overlay, with service unknown. The endpoint reports ICMP traffic and treats a driver model
identity as reported metadata; it never infers federation or operator acceptance.
