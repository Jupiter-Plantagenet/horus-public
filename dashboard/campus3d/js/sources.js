// Scenario model + loaders. Every scenario normalizes to one shape so the scene,
// minimap, HUD and timeline never care where the data came from.
//
// Scenario = {
//   id, kind, mode: 'replay'|'sample'|'live', label, labelKo, provenance: [{k, tag, v}],
//   duration, pos: {t[], x[], y[]}, cells: [{id, letter, pci, color, anchor:{x,y}, anchorKind}],
//   arms: [{key, label, tag, serving: [[t, cellIdx]], events: [Event]}], primary: armKey,
//   rsrp: {t[], v[][]} | null, sinr[], profile[], stage[], rtt: {pts, window} | null,
//   acceptance, cycles, cycleIndex, comparison, artifact, highlight: [t0, t1]
// }
// Event = {id, arm, t, phases:{decision, sent, ack, cu_confirmed}, from, to, status, evidence, profile}
// status: confirmed | acked | attempted | failed | modelled | observed

export const CELL_COLORS = ['#6EA8FF', '#C792EA', '#FF9E80', '#5EEAD4', '#F78FB3', '#B8E986', '#A0AEC0', '#FFE082', '#80DEEA'];

const cache = {};
async function getJSON(url) {
  if (!cache[url]) cache[url] = fetch(url, { cache: 'no-cache' }).then((r) => {
    if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
    return r.json();
  });
  return cache[url];
}
export const loadBase = async () => ({ campus: await getJSON('data/campus.json'), route: await getJSON('data/route.json') });

// ---------- helpers
export function bsearch(arr, v) { // last index with arr[i] <= v (or 0)
  let lo = 0, hi = arr.length - 1;
  if (!arr.length || v < arr[0]) return 0;
  while (lo < hi) { const m = (lo + hi + 1) >> 1; if (arr[m] <= v) lo = m; else hi = m - 1; }
  return lo;
}
export function posAt(sc, t) {
  const p = sc.pos, n = p.t.length;
  if (!n) return { x: 0, y: 0, heading: 0 };
  const i = bsearch(p.t, t), j = Math.min(i + 1, n - 1);
  const span = p.t[j] - p.t[i], f = span > 0 ? Math.min(1, Math.max(0, (t - p.t[i]) / span)) : 0;
  const x = p.x[i] + (p.x[j] - p.x[i]) * f, y = p.y[i] + (p.y[j] - p.y[i]) * f;
  // heading from a short look-ahead so a stationary walker keeps its last direction
  let k = j; while (k < n - 1 && Math.hypot(p.x[k] - x, p.y[k] - y) < 2) k++;
  let b = i; while (b > 0 && Math.hypot(p.x[b] - x, p.y[b] - y) < 2) b--;
  const hx = (p.x[k] - p.x[b]) || 0, hy = (p.y[k] - p.y[b]) || 1;
  return { x, y, heading: Math.atan2(hx, hy) };
}
export function servingAt(arm, t) {
  if (!arm || !arm.serving.length) return -1;
  const ts = arm._ts || (arm._ts = arm.serving.map((s) => s[0]));
  return t < ts[0] ? arm.serving[0][1] : arm.serving[bsearch(ts, t)][1];
}

export function trafficLabel(sc, ko = false) {
  const kind = sc.traffic?.kind;
  if (sc.mode === 'sample') return ko ? '단말 · 샘플' : 'UE · sample';
  if (kind === 'icmp_probe') return ko ? '단말 · ICMP 프로브' : 'UE · ICMP probes';
  if (kind === 'interactive_video') return ko ? '단말 · 대화형 영상' : 'UE · interactive video';
  if (sc.kind === 'walk' || kind === 'none') return ko ? '단말 · 기록된 보행' : 'UE · recorded walk';
  return ko ? '단말 · 서비스 미제공' : 'UE · service not provided';
}
export function frameAt(sc, t) { return sc.rsrp ? bsearch(sc.rsrp.t, t) : -1; }
export function armOf(sc, key) { return sc.arms.find((a) => a.key === key) || null; }

function statusOf(ph) { return ph.cu_confirmed != null ? 'confirmed' : ph.ack != null ? 'acked' : 'attempted'; }
function cellsFromRoute(route) {
  return route.cells.map((c, i) => ({ id: c.key, letter: c.letter, pci: c.pci, eci: c.eci, color: CELL_COLORS[i % CELL_COLORS.length],
    anchor: { x: c.anchor.x, y: c.anchor.y }, anchorKind: 'strongest_measured', rsrpPeak: c.anchor.rsrp_dbm }));
}
function stepServing(times, idx) {
  const out = [];
  for (let i = 0; i < times.length; i++) if (!out.length || out[out.length - 1][1] !== idx[i]) out.push([times[i], idx[i]]);
  return out;
}
function routePoints(route, session = 't4-reverse', shift = 0, from = -Infinity, to = Infinity) {
  const p = route.sessions[session].points, t = [], x = [], y = [];
  for (let i = 0; i < p.t.length; i++) {
    const tt = p.t[i] + shift;
    if (tt < from - 2 || tt > to + 2) continue;
    t.push(tt); x.push(p.x[i]); y.push(p.y[i]);
  }
  return { t, x, y };
}
const ARTIFACT_RELEASED = { version: 'v3.39.0', kind: 'central', label: 'Released actor · central MLP CHO-profile selector',
  labelKo: '릴리스 액터 · 중앙 학습 MLP CHO 프로파일 선택기', federation: { state: 'pending' }, gate: { state: 'pending' }, source: 'evidence' };

export const ARTIFACT_V314 = { version: 'v3.14.24', kind: 'federated',
  label: 'Federated MLP CHO-profile selector with an operator handover budget (FedAvg, 3 non-IID campus clients) · pre-registered held-out: H2 PASS',
  labelKo: '연합 학습 MLP CHO 프로파일 선택기 · 운영자 핸드오버 예산 (FedAvg, 비IID 캠퍼스 클라이언트 3개) · 사전 등록 홀드아웃: H2 통과',
  federation: { state: 'pass' }, gate: { state: 'pass' }, source: 'evidence' };

// ---------- REPLAY (modelled): HORUS v3.14.24 and network CHO on the calibrated reverse route
export async function buildV314() {
  const { route } = await loadBase();
  const d = await getJSON('data/v314-route.json');
  const cmp = await getJSON('data/comparison-v314.json');
  const cells = cellsFromRoute(route);
  const gidx = d.cells.map((k) => cells.findIndex((c) => c.id === k));
  const prof = (i) => (i == null || !d.profiles[i] ? null : { index: i, ...d.profiles[i] });
  const mk = (key, armKey, label) => {
    const a = d.arms[armKey];
    return { key, label, tag: 'modelled', serving: a.serving.map(([t, s]) => [t, gidx[s]]),
      events: a.events.map((e, i) => ({ id: `${key}-${i}`, arm: key, n: i + 1, t: e.t, phases: { decision: e.t },
        from: gidx[e.from], to: gidx[e.to], status: 'modelled', profile: prof(e.profile),
        stage: key === 'horus' ? 'learned_profiles' : undefined, evidence: { kind: 'TwinSim modelled handover' } })) };
  };
  const v = d.frames.rsrp.map((row) => { const out = new Array(cells.length).fill(null); row.forEach((val, j) => { if (gidx[j] >= 0) out[gidx[j]] = val; }); return out; });
  const dur = route.sessions['t4-reverse'].duration_s, V = d.verdicts;
  return {
    id: 'v314', kind: 'v314', mode: 'replay', duration: dur,
    label: `HORUS ${d.candidate} on the measured campus route · modelled decisions vs network CHO`,
    labelKo: `HORUS ${d.candidate} · 실측 캠퍼스 경로 · 모델 결정 vs 네트워크 CHO`,
    provenance: [
      { k: 'Route & positions', tag: 'measured', v: 'Phone GNSS, T4 reverse lap, Oct 2026 (allowlisted export)' },
      { k: 'Cell RSRP', tag: 'calibrated', v: 'Lap-1 calibrated radio surface (reverse lap is the evaluation route)' },
      { k: 'AI decisions', tag: 'modelled', v: `${d.candidate} (frozen, federated) in TwinSim; runtime parity verified on all 20,169 frames` },
      { k: 'Baseline', tag: 'modelled', v: 'Network-wide tuned CHO, identical route, time base and assumptions' },
      { k: 'Handover execution', tag: 'modelled', v: 'Twin only in this view; live OAI execution is the Executed handovers view' },
      { k: 'Twin held-out', tag: 'recorded', v: `${V.twin.headline} PASS on ${V.twin.episodes} paired episodes (seeds ${V.twin.seeds})` },
      { k: 'Cell anchors', tag: 'approx', v: 'Strongest measured point; mast locations are not known' },
      { k: 'Buildings', tag: 'measured', v: 'OpenStreetMap footprints (ODbL); heights approximate' },
    ],
    pos: routePoints(route, 't4-reverse', 0.1), cells, primary: 'horus',
    arms: [mk('horus', `selector_${d.candidate}`, `HORUS ${d.candidate}`), mk('baseline', 'cho_global', 'Network CHO')],
    rsrp: { t: d.frames.t, v }, sinr: null, profile: d.frames.profile, stage: d.frames.stage,
    profileTable: d.profiles, verdicts: V,
    rtt: null, acceptance: null, cycles: null, comparison: cmp, artifact: ARTIFACT_V314,
    traffic: { kind: 'none' }, highlight: [0, dur],
  };
}

// ---------- REPLAY: executed handovers on reverse segment 0
export async function buildSeg0(cycleIndex = 0, opt = {}) {
  const { feed = 'data/replay-seg0.json', version = 'v3.39.0', artifact = ARTIFACT_RELEASED, id = 'seg0' } = opt;
  const { route } = await loadBase();
  const rp = await getJSON(feed);
  const cells = cellsFromRoute(route);
  const gidx = rp.cells.map((k) => cells.findIndex((c) => c.id === k));
  const f = rp.frames;
  const v = f.rsrp.map((row) => { const out = new Array(cells.length).fill(null); row.forEach((val, j) => { out[gidx[j]] = val; }); return out; });
  const cyc = rp.cycles[Math.max(0, Math.min(cycleIndex, rp.cycles.length - 1))];
  const key = (k) => cells.findIndex((c) => c.id === k);
  const events = cyc.events.map((e, i) => ({ id: e.id, arm: 'horus', n: i + 1, t: e.phases.decision, phases: e.phases,
    from: key(e.from), to: key(e.to), status: statusOf(e.phases), profile: e.profile, stage: e.stage, evidence: e.evidence }));
  const dur = rp.scenario.duration_s;
  return {
    id, kind: 'seg0', mode: 'replay', duration: dur,
    label: `${rp.label} · ${cyc.kind === 'bounded' ? 'bounded acceptance' : 'two-hour run'} ${cyc.id.split('/')[1]}`,
    labelKo: `녹화된 검증 실행 · ${version} · 역방향 구간 0 · ${cyc.kind === 'bounded' ? '제한 검증' : '2시간 실행'} ${cyc.id.split('/')[1]}`,
    provenance: [
      { k: 'Route & positions', tag: 'measured', v: 'Phone GNSS, T4 reverse lap, Oct 2026 (allowlisted export)' },
      { k: 'Cell RSRP', tag: 'calibrated', v: 'Lap-1 calibrated radio surface, recorded stream frames (0.1 s)' },
      { k: 'AI decisions', tag: 'recorded', v: `${version} online inference, ${cyc.runtime.inference_calls} calls this cycle, ${cyc.runtime.model_faults} faults` },
      { k: 'Handover execution', tag: 'emulated', v: 'OAI F1 handover between two DUs (RF simulator); RIC ACK + new CU RRC completion' },
      { k: 'RTT', tag: 'emulated', v: 'ICMP probes through the UE tunnel during the cycle' },
      { k: 'Cell anchors', tag: 'approx', v: 'Strongest measured point; mast locations are not known' },
      { k: 'Buildings', tag: 'measured', v: 'OpenStreetMap footprints (ODbL); heights approximate' },
      { k: 'Receipts', tag: 'recorded', v: rp.provenance.execution },
    ],
    pos: routePoints(route, 't4-reverse', 0.1, 0, dur),
    cells, primary: 'horus',
    arms: [{ key: 'horus', label: `HORUS ${version}`, tag: 'recorded', serving: stepServing(f.t_s, f.serving.map((s) => gidx[s])), events }],
    rsrp: { t: f.t_s, v }, sinr: f.sinr_db, profile: f.profile, stage: f.stage,
    rtt: cyc.rtt.length ? { pts: cyc.rtt, window: cyc.rtt_window } : null,
    acceptance: rp.acceptance, cycles: rp.cycles.map((c) => c.id), cycleIndex, cycle: cyc,
    artifact, traffic: { kind: 'icmp_probe' }, highlight: [0, dur], comparison: null,
  };
}
export const buildSeg0V314 = (cycleIndex = 0) => buildSeg0(cycleIndex, { feed: 'data/replay-seg0-v314.json', version: 'v3.14.24', artifact: ARTIFACT_V314, id: 'seg0v314' });

// ---------- REPLAY: whole recorded walk (network's own serving cells)
export async function buildWalk() {
  const { route } = await loadBase();
  // the current candidate's modelled comparison; the v3.39.0 one stays in data/comparison.json as history
  const cmp = await getJSON('data/comparison-v314.json').catch(() => getJSON('data/comparison.json'));
  const cells = cellsFromRoute(route);
  const s = route.sessions['t4-reverse'];
  const byEci = (e) => cells.findIndex((c) => c.eci === e);
  const times = s.x.map((_, i) => i);
  const events = s.observed_cell_changes.map((c, i) => ({ id: `net-${i}`, arm: 'network', n: i + 1, t: c.t_s, phases: { decision: c.t_s },
    from: byEci(c.from), to: byEci(c.to), status: 'observed', evidence: { kind: 'phone log serving-cell change' } }));
  const tr = route.trace;
  return {
    id: 'walk', kind: 'walk', mode: 'replay', duration: s.duration_s,
    label: `Recorded campus walk · reverse lap${s.t0_kst ? ` · ${s.t0_kst.slice(0, 10).replace(/\./g, '-')}` : ''} · LG U+ serving cells`,
    labelKo: '녹화된 캠퍼스 보행 · 역방향 랩 · 2026-10 · LG U+ 서빙 셀',
    provenance: [
      { k: 'Route & positions', tag: 'measured', v: `Phone GNSS, ${s.rows} rows, 36 min walk` },
      { k: 'Serving cell', tag: 'measured', v: 'The LG U+ network’s own serving cell, recorded by the phone' },
      { k: 'Cell changes', tag: 'measured', v: `${events.length} serving-cell changes observed in the log` },
      { k: 'Per-cell RSRP', tag: 'calibrated', v: 'Lap-1 calibrated surface (1 s means); gaps = outside stable support' },
      { k: 'HO comparison', tag: 'modelled', v: cmp.label },
      { k: 'Cell anchors', tag: 'approx', v: 'Strongest measured point; mast locations are not known' },
      { k: 'Buildings', tag: 'measured', v: 'OpenStreetMap footprints (ODbL); heights approximate' },
    ],
    pos: routePoints(route, 't4-reverse'), cells, primary: 'network',
    arms: [{ key: 'network', label: 'LG U+ network', tag: 'measured', serving: stepServing(times, s.serving_eci.map(byEci)), events }],
    rsrp: { t: tr.rsrp_1s.map((_, i) => i), v: tr.rsrp_1s }, sinr: null, profile: null, stage: null,
    rtt: null, acceptance: null, cycles: null, comparison: cmp, artifact: null, traffic: { kind: 'none' }, highlight: [0, s.duration_s],
  };
}

// ---------- SAMPLE: synthetic, exercises paired comparison + interruptions. Never a result.
function rng(seed) { let s = seed >>> 0; return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296); }
export async function buildSample(seed = 7) {
  const { route } = await loadBase();
  const cells = cellsFromRoute(route);
  const T0 = 380, DUR = 240;                    // a walking stretch of the real route
  const pos = routePoints(route, 't4-reverse', -T0, 0, DUR);
  const R = rng(seed), dt = 0.5, t = [], v = [];
  const at = (tt) => posAt({ pos }, tt);
  for (let tt = 0; tt <= DUR; tt += dt) {
    const p = at(tt);
    t.push(+tt.toFixed(1));
    v.push(cells.map((c, j) => {
      const d = Math.hypot(p.x - c.anchor.x, p.y - c.anchor.y) + 15;
      return +(-58 - 30 * Math.log10(d) + 4 * Math.sin(tt / (9 + j) + j) + (R() - 0.5) * 2).toFixed(1);
    }));
  }
  const run = (hys, tttS, slow) => {
    let s = v[0].indexOf(Math.max(...v[0])), cand = -1, since = 0;
    const serving = [[0, s]], events = [], interruptions = [];
    for (let i = 1; i < t.length; i++) {
      const best = v[i].indexOf(Math.max(...v[i]));
      if (best !== s && v[i][best] > v[i][s] + hys) {
        if (cand !== best) { cand = best; since = t[i]; }
        if (t[i] - since >= tttS) {
          const gap = slow ? 0.18 + R() * 0.42 : 0.03 + R() * 0.07;
          events.push({ id: `${slow ? 'b' : 'h'}${events.length + 1}`, arm: slow ? 'baseline' : 'horus', n: events.length + 1, t: t[i],
            phases: slow ? { decision: t[i] } : { decision: t[i], sent: t[i] + 0.2, ack: t[i] + 0.21, cu_confirmed: t[i] + 2.4 },
            from: s, to: best, status: slow ? 'modelled' : 'confirmed', evidence: { interruption_ms: Math.round(gap * 1000), sample: true } });
          interruptions.push([t[i], t[i] + gap]);
          s = best; cand = -1; serving.push([t[i], s]);
        }
      } else cand = -1;
    }
    return { serving, events, interruptions };
  };
  const h = run(2.0, 0.0, false), b = run(1.0, 0.32, true);
  const rtt = [];
  for (let tt = 0; tt <= DUR; tt += 1) {
    const inGap = (iv) => iv.some(([a, z]) => tt >= a - 0.5 && tt <= z + 0.8);
    rtt.push([tt, Math.round(38 + R() * 30 + (inGap(h.interruptions) ? 60 : 0))]);
  }
  return {
    id: 'sample', kind: 'sample', mode: 'sample', duration: DUR,
    label: 'SAMPLE · synthetic paired run on the real campus route', labelKo: '샘플 · 실제 캠퍼스 경로 위 합성 비교 실행',
    provenance: [
      { k: 'Route geometry', tag: 'measured', v: 'Real T4 reverse route positions (380–620 s)' },
      { k: 'Radio, events, RTT', tag: 'sample', v: 'Synthetic, seeded generator in js/sources.js — not a measurement or result' },
      { k: 'Artifact / gate', tag: 'pending', v: 'Federated artifact and operator gate are pending real receipts' },
    ],
    pos, cells, primary: 'horus',
    arms: [{ key: 'horus', label: 'HORUS (sample)', tag: 'sample', serving: h.serving, events: h.events, interruptions: h.interruptions },
           { key: 'baseline', label: 'Baseline A3 (sample)', tag: 'sample', serving: b.serving, events: b.events, interruptions: b.interruptions }],
    rsrp: { t, v }, sinr: null, profile: null, stage: null, rtt: { pts: rtt, window: [0, DUR] },
    acceptance: null, cycles: null, comparison: null, highlight: [0, DUR],
    artifact: { version: 'sample', kind: 'federated', label: 'SAMPLE federated artifact slot', labelKo: '샘플 연합 학습 모델 슬롯',
      federation: { state: 'pending', rounds: null, clients: null }, gate: { state: 'pending' }, source: 'sample' },
  };
}

// ---------- Console scene: horus.twin-scene/1 (console is clock master)
export async function buildFromConsoleScene(scene) {
  const { route } = await loadBase();
  const known = cellsFromRoute(route);
  const cells = (scene.cells || []).map((c, i) => {
    const k = known.find((x) => x.id === c.id);
    const a = c.anchor || {};
    return { id: c.id, short: c.short || `C${i}`, letter: k ? k.letter : (c.short || `C${i}`), pci: k ? k.pci : null,
      color: k ? k.color : CELL_COLORS[i % CELL_COLORS.length], anchorKind: c.anchor_kind || 'unknown',
      anchor: { x: a.x ?? (k ? k.anchor.x : 0), y: a.y ?? (k ? k.anchor.y : 0) }, label: c.label, labelKo: c.label_ko };
  });
  const ix = (s) => { const i = cells.findIndex((c) => c.short === s || c.id === s); return i; };
  const cols = scene.route?.columns || ['t_s', 'lat', 'lon', 'x_m', 'y_m'];
  const ci = (n) => cols.indexOf(n);
  const pts = (scene.route?.points || []).filter((p) => Array.isArray(p) && typeof p[0] === 'number');
  const pos = { t: pts.map((p) => p[ci('t_s')]), x: pts.map((p) => p[ci('x_m')]), y: pts.map((p) => p[ci('y_m')]) };
  const arms = Object.entries(scene.arms || {}).map(([key, a]) => ({
    key, label: a.label, labelKo: a.label_ko, tag: a.provenance || 'recorded',
    serving: (a.serving || []).map(([tt, s]) => [tt, ix(s)]),
    events: (a.events || []).map((e, n) => {
      const valid = (v) => Number.isFinite(v) && v >= 0;
      const sent = valid(e.decision_to_send_ms) ? e.t + e.decision_to_send_ms / 1000 : null;
      const ack = sent != null && valid(e.ack_ms) ? sent + e.ack_ms / 1000 : null;
      const cu = e.status === 'confirmed' && ack != null && valid(e.control_to_cu_ms) && e.control_to_cu_ms >= e.ack_ms
        ? sent + e.control_to_cu_ms / 1000 : null;
      return { id: e.id, arm: key, n: n + 1, t: e.t, from: ix(e.from), to: ix(e.to),
        status: e.status === 'confirmed' && cu == null ? (ack == null ? 'attempted' : 'acked') : e.status || 'attempted',
        profile: e.profile ? { index: e.profile_index, ...e.profile } : null,
        phases: { decision: e.t, sent, ack, cu_confirmed: cu },
        evidence: { text: e.evidence, ran: e.ran, ric_ack_ms: e.ack_ms,
          decision_to_cu_ms: cu == null ? null : e.decision_to_send_ms + e.control_to_cu_ms } };
    }),
  }));
  const mode = String(scene.mode || 'REPLAY').toLowerCase();
  const rp = scene.route?.provenance || {};
  return {
    id: `console:${scene.id}`, kind: 'console', mode: ['live', 'replay', 'sample'].includes(mode) ? mode : 'replay',
    duration: scene.clock?.duration_s ?? (pos.t.length ? pos.t[pos.t.length - 1] : 0),
    label: scene.label || scene.route?.label || scene.id, labelKo: scene.label_ko || scene.route?.label_ko,
    provenance: [{ k: 'Scene', tag: mode === 'sample' ? 'sample' : 'recorded', v: `${scene.schema} ${scene.id} from the operator console` },
      { k: 'Route', tag: rp.kind === 'measured_gps' ? 'measured' : 'recorded', v: rp.note || '' },
      ...arms.map((a) => ({ k: a.label, tag: a.tag, v: `${a.events.length} events` })),
      { k: 'Buildings', tag: 'measured', v: 'OpenStreetMap footprints (ODbL); heights approximate' }],
    pos, cells, primary: arms.find((a) => a.key === 'horus') ? 'horus' : (arms[0]?.key || 'horus'), arms,
    rsrp: null, sinr: null, profile: null, stage: null, rtt: null, acceptance: null, cycles: null, comparison: null,
    artifact: scene.artifact || null, traffic: scene.traffic || { kind: 'unknown' }, highlight: [0, scene.clock?.duration_s ?? 0], external: true,
  };
}

// ---------- LIVE: tails /api/campus3d/live (serve.py). Never substitutes recorded data.
export class LiveSource {
  constructor(url, onUpdate) { this.url = url; this.onUpdate = onUpdate; this.after = -1; this.sc = null; this.timer = null; this.state = 'waiting'; this.stopped = false; this.lastProgressAt = null; }
  async init(poll = true) {
    const { route } = await loadBase();
    this.route = route;
    const cells = cellsFromRoute(route);
    this.sc = { id: 'live', kind: 'live', mode: 'live', duration: 0, label: 'Live session', labelKo: '실시간 세션',
      provenance: [{ k: 'Frames', tag: 'calibrated', v: 'Live calibrated TwinSim observation stream (release runner capture)' },
        { k: 'Decisions', tag: 'pending', v: 'Artifact identity must be supplied by the running session' },
        { k: 'Execution', tag: 'emulated', v: 'OAI F1 handovers; confirmation requires RIC ACK + new CU RRC completion' }],
      pos: { t: [], x: [], y: [] }, cells, primary: 'horus',
      arms: [{ key: 'horus', label: 'HORUS (live)', tag: 'recorded', serving: [], events: [] }],
      rsrp: { t: [], v: [] }, sinr: [], profile: [], stage: [], rtt: { pts: [], window: null },
      acceptance: null, cycles: null, comparison: null, artifact: null, traffic: { kind: 'unknown' }, highlight: [0, 0], live: { age_s: null, stale: true } };
    if (poll) this.poll();
    return this.sc;
  }
  stop() { this.stopped = true; clearTimeout(this.timer); this.timer = null; this.abort?.abort(); }
  freshness(now = performance.now()) {
    if (!this.sc?.pos.t.length) return (this.state = 'waiting');
    const age = this.lastProgressAt == null ? Infinity : (now - this.lastProgressAt) / 1000;
    return (this.state = this.sc.live.stale || age > 2 ? 'stale' : 'live');
  }
  async poll() {
    if (this.stopped) return;
    this.abort = new AbortController();
    try {
      const r = await fetch(`${this.url}?after=${this.after}`, { cache: 'no-store', signal: this.abort.signal });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const feed = await r.json(); if (this.stopped) return; this.ingest(feed);
    } catch (e) {
      if (this.stopped) return;
      this.state = this.sc.pos.t.length ? 'stale' : 'waiting'; this.sc.live = { ...this.sc.live, age_s: null, stale: true, error: String(e.message || e) };
    }
    if (this.stopped) return;
    this.onUpdate && this.onUpdate(this.sc, this.state);
    this.timer = setTimeout(() => this.poll(), 500);
  }
  ingest(feed) {
    const sc = this.sc, live = feed.live || {};
    if (live.cycle && live.cycle !== this.cycle) { // new cycle: restart the scenario clock
      this.cycle = live.cycle; this.after = -1;
      sc.pos = { t: [], x: [], y: [] }; sc.rsrp = { t: [], v: [] }; sc.sinr = []; sc.profile = []; sc.stage = [];
      sc.arms[0].serving = []; sc.arms[0]._ts = null;
      sc.rtt = { pts: [], window: null }; sc.artifact = null; sc.traffic = { kind: 'unknown' };
      this.lastProgressAt = null;
    }
    const seg = this.route.trace.segments.find((s, i) => `reverse-supported-${i}` === feed.scenario?.segment) || this.route.trace.segments[0];
    const fr = feed.frames || { t_s: [] };
    const gidx = (feed.cells || []).map((k) => sc.cells.findIndex((c) => c.id === k));
    const rp = this.route.sessions['t4-reverse'].points;
    for (let i = 0; i < fr.t_s.length; i++) {
      if (!Number.isInteger(fr.step[i]) || fr.step[i] <= this.after || !Number.isFinite(fr.t_s[i]) ||
          (sc.pos.t.length && fr.t_s[i] <= sc.pos.t.at(-1))) continue;
      const t = fr.t_s[i], step = seg.start + fr.step[i];
      const el = step * 0.1, k = bsearch(rp.t, el), j = Math.min(k + 1, rp.t.length - 1);
      const f = rp.t[j] > rp.t[k] ? (el - rp.t[k]) / (rp.t[j] - rp.t[k]) : 0;
      sc.pos.t.push(t); sc.pos.x.push(rp.x[k] + (rp.x[j] - rp.x[k]) * f); sc.pos.y.push(rp.y[k] + (rp.y[j] - rp.y[k]) * f);
      const row = new Array(sc.cells.length).fill(null); (fr.rsrp[i] || []).forEach((v, c) => { row[gidx[c]] = v; });
      sc.rsrp.t.push(t); sc.rsrp.v.push(row); sc.sinr.push(fr.sinr_db?.[i] ?? null);
      sc.profile.push(fr.profile?.[i] ?? null); sc.stage.push(fr.stage?.[i] ?? null);
      const s = gidx[fr.serving[i]] ?? -1, arm = sc.arms[0];
      if (!arm.serving.length || arm.serving[arm.serving.length - 1][1] !== s) { arm.serving.push([t, s]); arm._ts = null; }
      this.after = Math.max(this.after, fr.step[i]);
      this.lastProgressAt = performance.now();
    }
    const key = (k) => sc.cells.findIndex((c) => c.id === k);
    sc.arms[0].events = (feed.events || []).map((e, n) => ({ id: e.id, arm: 'horus', n: n + 1, t: e.phases.decision, phases: e.phases,
      from: key(e.from), to: key(e.to), status: e.status || statusOf(e.phases), profile: e.profile, evidence: e.evidence }));
    if (feed.service?.rtt) sc.rtt = { pts: feed.service.rtt, window: feed.service.rtt.length ? [feed.service.rtt[0][0], feed.service.rtt.at(-1)[0]] : null };
    sc.duration = sc.pos.t.length ? sc.pos.t[sc.pos.t.length - 1] : 0;
    sc.highlight = [0, sc.duration];
    sc.live = { age_s: live.age_s, stale: !!live.stale, cycle: live.cycle, rehearsal: !!live.rehearsal, error: feed.error || null };
    if (feed.label) sc.label = feed.label;
    if (feed.artifact) sc.artifact = { ...feed.artifact, source: 'feed' };
    if (feed.traffic) sc.traffic = feed.traffic;
    this.freshness();
  }
}
