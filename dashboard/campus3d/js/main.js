// HORUS campus twin — boot, clock, modes, messaging.
import { CampusScene } from './scene.js';
import { MiniMap } from './minimap.js';
import { HUD, currentLink, serviceState } from './hud.js';
import { loadBase, buildSeg0, buildSeg0V314, buildV314, buildWalk, buildSample, buildFromConsoleScene, LiveSource, trafficLabel } from './sources.js';
import { setLang, getLang, t as tr, applyStatic } from './i18n.js';

const Q = new URLSearchParams(location.search);
const $ = (id) => document.getElementById(id);
const app = $('app');
const EMBED = Q.has('embed') && Q.get('embed') !== '0';
const PROTO_A = 'horus.campus3d', PROTO_B = 'horus.twin';
if (EMBED) app.classList.add('embed');
if (Q.get('minimap') === '0') app.classList.add('nominimap');
setLang(Q.get('lang') || 'en');

const SCENARIOS = [
  { id: 'v314', mode: 'replay', key: 'scen_v314', build: () => buildV314(), loopFrom: 0, speed: 8 },
  { id: 'seg0v314', mode: 'replay', key: 'scen_seg0v314', build: () => buildSeg0V314(state.cycle), loopFrom: 128, speed: 1 },
  { id: 'seg0', mode: 'replay', key: 'scen_seg0', build: () => buildSeg0(state.cycle), loopFrom: 128, speed: 1 },
  { id: 'walk', mode: 'replay', key: 'scen_walk', build: () => buildWalk(), loopFrom: 0, speed: 16 },
  { id: 'sample', mode: 'sample', key: 'scen_sample', build: () => buildSample(), loopFrom: 0, speed: 2 },
  { id: 'live', mode: 'live', key: 'scen_live' },
];
const state = { t: 0, playing: Q.get('autoplay') !== '0', speed: +(Q.get('speed') || 0) || null, scen: null, sc: null, cycle: 0,
  external: null, live: null, liveState: 'waiting', status: null, lastTick: 0, pinnedT: Q.has('t') ? +Q.get('t') : null };

const post = (msg) => { if (window.parent !== window) window.parent.postMessage(msg, location.origin === 'null' ? '*' : location.origin); };
const emit = (kind, body = {}) => post({ type: `${PROTO_A}.event`, v: 1, kind, ...body });
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }[c]));

function refreshLiveState(now = performance.now()) {
  if (state.sc?.mode !== 'live') return;
  let next;
  if (state.external) {
    const x = state.external;
    next = !x.hasTick ? 'waiting' : x.live?.stale === true || now - x.at > 2000 ? 'stale' : 'live';
  } else next = (state.live || state.pushed)?.freshness(now) || 'waiting';
  if (next !== state.liveState) { state.liveState = next; renderMode(); }
}

// ---------------------------------------------------------------- scene + widgets
const scene = new CampusScene($('scene'), $('labels'), {
  quality: Q.get('quality') || 'auto',
  onPick: (p) => { if (!p) return; post({ type: `${PROTO_B}.pick`, v: 1, ...p }); emit('pick', p);
    if (p.event_id) { const e = allEvents().find((x) => x.id === p.event_id); if (e && !state.external) seek(e.t - 2); scene.focusEvent(p.event_id); } },
  onViewChange: (v) => renderViews(v),
});
const mini = new MiniMap($('minimap'), (t) => { if (!state.external) seek(t); post({ type: `${PROTO_B}.pick`, v: 1, t }); });
const hud = new HUD({ onSeek: (t) => seek(t), onCycle: (i) => { state.cycle = i; selectScenario(state.scen === 'seg0v314' ? 'seg0v314' : 'seg0', { keepTime: true }); } });
const allEvents = () => (state.sc ? state.sc.arms.flatMap((a) => a.events) : []);
const pill = document.createElement('div'); pill.className = 'embed-pill'; app.appendChild(pill);

function toast(text, cls = '') {
  const el = $('toast'); el.textContent = text; el.className = `toast ${cls}`; el.hidden = false;
  clearTimeout(toast.h); toast.h = setTimeout(() => { el.hidden = true; }, 3800);
}
function seek(t) {
  if (!state.sc) return;
  state.t = Math.max(0, Math.min(state.sc.duration, t)); scene.prevT = null;
  emit('tick', tickBody());
}

// ---------------------------------------------------------------- chrome
function renderScenarioNav() {
  const nav = $('scenarios');
  const items = SCENARIOS.map((s) => `<button data-id="${s.id}" class="${state.scen === s.id ? 'on' : ''}"><span class="m ${s.mode}">${tr(`mode_${s.mode}`)}</span>${tr(s.key)}</button>`);
  if (state.external) items.push(`<button data-id="console" class="on"><span class="m ${state.sc?.mode}">${tr(`mode_${state.sc?.mode || 'replay'}`)}</span>${tr('scen_console')}</button>`);
  nav.innerHTML = items.join('');
  nav.querySelectorAll('button').forEach((b) => b.addEventListener('click', () => { if (b.dataset.id !== 'console') selectScenario(b.dataset.id); }));
  $('speeds').innerHTML = [1, 2, 4, 8, 16, 32].map((s) => `<button data-s="${s}" class="${s === state.speed ? 'on' : ''}">${s}×</button>`).join('');
  $('speeds').querySelectorAll('button').forEach((b) => b.addEventListener('click', () => { state.speed = +b.dataset.s; renderScenarioNav(); }));
}
function renderViews(v) {
  $('views').innerHTML = ['hero', 'follow', 'overview', 'top'].map((k, i) => `<button data-v="${k}" class="${v === k ? 'on' : ''}" title="${i + 1}">${tr(`view_${k}`)}</button>`).join('')
    + (v === 'free' ? `<button class="on" disabled>${tr('view_free')}</button>` : '');
  $('views').querySelectorAll('button[data-v]').forEach((b) => b.addEventListener('click', () => scene.setView(b.dataset.v)));
}
function renderMode() {
  const sc = state.sc, b = $('mode-badge'); if (!sc) return;
  let cls = sc.mode, txt = tr(`mode_${sc.mode}`);
  if (sc.mode === 'live') {
    if (state.liveState === 'waiting') { cls = 'waiting'; txt = tr('mode_waiting'); }
    else if (state.liveState === 'stale') { cls = 'stale'; txt = tr('mode_stale'); }
    if (sc.live?.rehearsal) txt += ' · REHEARSAL';
  }
  b.className = `mode-badge ${cls}`; $('mode-text').textContent = txt;
  $('scen-label').textContent = getLang() === 'ko' ? (sc.labelKo || sc.label) : sc.label;
  const sb = $('sample-bar'); sb.hidden = sc.mode !== 'sample'; sb.textContent = tr('sample_bar');
  const w = $('waiting');
  w.hidden = !(sc.mode === 'live' && state.liveState !== 'live');
  if (!w.hidden) w.innerHTML = `<b>${state.liveState === 'stale' ? tr('stale_d') : tr('waiting_t')}</b>${tr(state.liveState === 'stale' ? 'stale_note' : 'waiting_d')}${sc.live?.error ? `<div class="note">${esc(sc.live.error)}</div>` : ''}`;
  $('prov-pop').innerHTML = `<h4>${tr('provenance')} · ${esc(getLang() === 'ko' ? (sc.labelKo || sc.label) : sc.label)}</h4><dl>${sc.provenance.map((p) => `<dt>${esc(p.k)}</dt><dd><span class="tag ${esc(p.tag)}">${esc(p.tag)}</span>${esc(p.v)}</dd>`).join('')}</dl>
    <div class="note">${esc(state.base?.campus.attribution || '')}</div>`;
}
$('prov-chip').addEventListener('click', () => { const p = $('prov-pop'); p.hidden = !p.hidden; $('prov-chip').setAttribute('aria-expanded', String(!p.hidden)); });
$('btn-play').addEventListener('click', () => { state.playing = !state.playing; });
$('btn-lang').addEventListener('click', () => changeLang(getLang() === 'en' ? 'ko' : 'en'));
$('btn-full').addEventListener('click', () => (document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen?.()));
function changeLang(l) {
  setLang(l); applyStatic(); scene.setLang(l); $('btn-lang').textContent = l === 'en' ? '한국어' : 'English';
  renderScenarioNav(); renderViews(scene.view); renderMode(); hud.scStatic = null; hud._evKey = undefined; hud.redrawTimeline(); hud.update(state.t, { force: true });
  if (scene._updMarkerLabels) scene._updMarkerLabels();
}

// ---------------------------------------------------------------- scenarios
async function applyScenario(sc, def = {}) {
  state.sc = sc; scene.setScenario(sc); mini.setScenario(sc); hud.setScenario(sc); hud.setStatus(state.status);
  if (state.speed == null || def.resetSpeed) state.speed = def.speed || 1;
  renderScenarioNav(); renderMode(); hud.redrawTimeline(); hud.update(state.t, { force: true });
  emit('ready', { modes: ['live', 'replay', 'sample'], scenario: { id: sc.id, duration_s: sc.duration, mode: sc.mode } });
}
async function selectScenario(id, { keepTime = false } = {}) {
  const selection = state.selection = (state.selection || 0) + 1;
  if (state.live) { state.live.stop(); state.live = null; }
  if (state.pushed) { state.pushed.stop(); state.pushed = null; }
  state.external = null; state.status = null; state.scen = id;
  const def = SCENARIOS.find((s) => s.id === id) || SCENARIOS[0];
  if (id === 'live') {
    state.liveState = 'waiting';
    const src = new LiveSource(Q.get('feed') || '/api/campus3d/live', (sc, st) => {
      const was = state.liveState; state.liveState = st;
      if (state.sc === sc) {
        if (sc.duration !== hud._lastDur) { hud._lastDur = sc.duration; mini.scLayer = null; hud.redrawTimeline(); }
        // route ribbon + framing follow the growing live track (throttled to every 2 s of scenario time)
        if (Math.abs(sc.duration - (state._routeAt ?? -99)) >= 2 || sc.duration < (state._routeAt ?? 0)) { state._routeAt = sc.duration; scene.refreshRoute(); }
        if (was !== st) renderMode();
      }
      const events = JSON.stringify(sc.arms[0].events.map((e) => [e.id, e.status, e.phases]));
      if (events !== state._liveEv) { state._liveEv = events; scene.setScenario(sc); hud.setScenario(sc); hud.redrawTimeline(); }
      const artifact = JSON.stringify(sc.artifact); if (artifact !== state._artifact) { state._artifact = artifact; hud.scStatic = null; }
    });
    state.live = src; const sc = await src.init(); state.t = 0;
    if (selection !== state.selection) { src.stop(); return; }
    await applyScenario(sc, { speed: 1, resetSpeed: true });
  } else {
    const sc = await def.build(); sc.loopFrom = def.loopFrom;
    if (selection !== state.selection) return;
    if (!keepTime) state.t = state.pinnedT ?? def.loopFrom; state.pinnedT = null;
    await applyScenario(sc, { speed: def.speed, resetSpeed: !keepTime && !Q.get('speed') });
  }
  emit('modeChanged', { mode: state.sc.mode, scenario: id });
  history.replaceState(null, '', `?${new URLSearchParams({ ...Object.fromEntries(Q), scen: id, lang: getLang() })}`);
}

// ---------------------------------------------------------------- messaging (console)
function tickBody() {
  const sc = state.sc, L = currentLink(sc, state.t), cell = (i) => (i >= 0 ? sc.cells[i].id : null);
  const p = scene.lastDev || { x: 0, y: 0 };
  return { mode: sc.mode, t_s: +state.t.toFixed(2), duration_s: sc.duration, playing: state.playing, speed: state.speed,
    serving: cell(L.serving), target: cell(L.target), position: { x_m: +p.x.toFixed(1), y_m: +p.y.toFixed(1) },
    service: { state: sc.mode === 'live' && state.liveState !== 'live' ? 'unknown' : serviceState(sc, state.t) }, scenario: sc.id };
}
window.addEventListener('message', async (e) => {
  if (e.source !== window.parent && e.source !== window) return;
  if (e.origin !== location.origin && !(location.origin === 'null')) return;
  const m = e.data; if (!m || typeof m !== 'object' || typeof m.type !== 'string') return;
  try {
    if (m.type === `${PROTO_B}.scene` && m.scene) {
      const selection = state.selection = (state.selection || 0) + 1;
      if (state.live) { state.live.stop(); state.live = null; }
      if (state.pushed) { state.pushed.stop(); state.pushed = null; }
      const sc = await buildFromConsoleScene(m.scene); if (selection !== state.selection) return;
      state.external = { t: 0, at: performance.now(), rate: 1, playing: false, hasTick: false }; state.liveState = 'waiting';
      state.scen = 'console'; await applyScenario(sc, { speed: 1 });
    } else if (m.type === `${PROTO_B}.tick`) {
      if (!state.external) state.external = {};
      const x = state.external, stale = m.live?.stale === true;
      Object.assign(x, { t: stale && x.hasTick ? x.t : Math.max(0, +m.t || 0), at: performance.now(), rate: m.rate ?? 1, playing: !!m.playing, live: m.live || null, hasTick: true });
      const mode = String(m.mode || '').toLowerCase();
      if (['live', 'replay', 'sample'].includes(mode) && state.sc && state.sc.mode !== mode) { state.sc.mode = mode; renderMode(); }
      if (state.sc?.mode === 'live' && m.live) state.sc.live = { ...state.sc.live, rehearsal: !!m.live.rehearsal };
      refreshLiveState();
      if (m.arm && state.sc && state.sc.arms.some((a) => a.key === m.arm) && state.sc.primary !== m.arm) { state.sc.primary = m.arm; scene.setScenario(state.sc); mini.setScenario(state.sc); hud.redrawTimeline(); }
    } else if (m.type === `${PROTO_B}.focus`) {
      if (m.event_id) scene.focusEvent(m.event_id);
    } else if (m.type === `${PROTO_B}.view`) {
      scene.setView({ overview: 'overview', follow: 'follow', cell: 'hero', top: 'top', hero: 'hero' }[m.preset] || 'hero');
    } else if (m.type === `${PROTO_B}.lang`) {
      changeLang(m.lang);
    } else if (m.type === `${PROTO_A}.command`) {
      const c = m.cmd;
      if (c === 'setMode') selectScenario({ live: 'live', replay: 'seg0', sample: 'sample', walk: 'walk' }[m.mode] || m.mode);
      else if (c === 'setLang') changeLang(m.lang);
      else if (c === 'play') state.playing = true;
      else if (c === 'pause') state.playing = false;
      else if (c === 'seek') seek(+m.t_s);
      else if (c === 'setSpeed') state.speed = +m.speed || 1;
      else if (c === 'setView') scene.setView(m.view);
      else if (c === 'setQuality') scene.setQuality(m.quality);
      else if (c === 'focusEvent') scene.focusEvent(m.id);
      else if (c === 'setStatus') { state.status = m.status; hud.setStatus(m.status); }
      else if (c === 'pushFeed' && m.feed) {
        if (!state.pushed) { if (state.live) state.live.stop(); state.pushed = new LiveSource(null, null); state.live = null; const sc = await state.pushed.init(false); state.scen = 'live'; state.external = null; await applyScenario(sc, { speed: 1 }); }
        state.pushed.ingest(m.feed); state.liveState = state.pushed.state; mini.scLayer = null; hud.redrawTimeline(); renderMode();
      }
    }
  } catch (err) { console.error(err); post({ type: `${PROTO_B}.status`, v: 1, message: `twin error: ${err.message}` }); }
});

// ---------------------------------------------------------------- keys
window.addEventListener('keydown', (e) => {
  if (e.target.tagName === 'SELECT' || e.target.tagName === 'INPUT') return;
  const k = e.key;
  if (k === ' ') { state.playing = !state.playing; e.preventDefault(); }
  else if (k === 'ArrowRight') seek(state.t + (e.shiftKey ? 30 : 5));
  else if (k === 'ArrowLeft') seek(state.t - (e.shiftKey ? 30 : 5));
  else if (k >= '1' && k <= '4') scene.setView(['hero', 'follow', 'overview', 'top'][+k - 1]);
  else if (k === 'l' || k === 'L') changeLang(getLang() === 'en' ? 'ko' : 'en');
  else if (k === 'f' || k === 'F') $('btn-full').click();
  else if (k === 'r' || k === 'R') selectScenario(state.scen === 'live' ? 'seg0' : 'live');
  else if (k === 'w' || k === 'W') selectScenario('walk');
  else if (k === 'e' || k === 'E') selectScenario(state.scen === 'seg0v314' ? 'seg0' : 'seg0v314');
  else if (k === 'v' || k === 'V') selectScenario('v314');
  else if (k === 's' || k === 'S') selectScenario('sample');
  else if (k === ']') { state.speed = Math.min(32, state.speed * 2); renderScenarioNav(); }
  else if (k === '[') { state.speed = Math.max(1, state.speed / 2); renderScenarioNav(); }
  else if (k === 'Home') seek(state.sc?.loopFrom || 0);
});
window.addEventListener('resize', () => { hud.redrawTimeline(); });

// ---------------------------------------------------------------- loop
let lastFrame = performance.now(), lastEmit = 0, lastStatus = 0;
function frame(now) {
  requestAnimationFrame(frame);
  const dt = Math.min(0.25, (now - lastFrame) / 1000); lastFrame = now;
  const sc = state.sc; if (!sc) return;
  refreshLiveState(now);
  if (state.external) {
    const x = state.external; state.t = Math.max(0, Math.min(sc.duration, (x.t || 0) + (x.playing && (sc.mode !== 'live' || state.liveState === 'live') ? ((now - x.at) / 1000) * (x.rate || 1) : 0)));
  } else if (sc.mode === 'live' && state.scen === 'live') {
    if (state.liveState === 'live') { const goal = Math.max(0, sc.duration - 0.3); state.t += (goal - state.t) * Math.min(1, dt * 4); if (Math.abs(goal - state.t) > 5) state.t = goal; }
  } else if (state.playing) {
    state.t += dt * state.speed;
    if (state.t > sc.duration) { state.t = sc.loopFrom || 0; scene.prevT = null; }
  }
  $('btn-play').textContent = (state.external ? state.external.playing : state.playing) ? '❚❚' : '▶';
  const L = currentLink(sc, state.t), stale = sc.mode === 'live' && state.liveState !== 'live', svc = stale ? 'unknown' : serviceState(sc, state.t);
  const devLabel = trafficLabel(sc, getLang() === 'ko');
  const out = scene.update(state.t, { serving: L.serving, target: L.target, service: svc, stale, devLabel });
  if (out) {
    scene.lastDev = out.dev;
    for (const f of out.fired) {
      const e = f.ev, a = sc.cells[e.from], b = sc.cells[e.to], ko = getLang() === 'ko';
      if (f.kind === 'decision' && e.status !== 'observed') toast(`${ko ? 'AI 결정' : 'AI decision'} · HO ${e.n} · ${a?.letter}→${b?.letter}${e.profile ? ` · CHO profile #${e.profile.index}` : ''}`, 'cyan');
      if (f.kind === 'cu_confirmed') toast(`${ko ? '핸드오버 확인' : 'Handover confirmed'} · CU RRC ✓ · ${a?.letter}→${b?.letter}${e.evidence?.decision_to_cu_ms ? ` · ${ko ? '결정→CU' : 'decision→CU'} ${(e.evidence.decision_to_cu_ms / 1000).toFixed(2)} s` : ''}`);
      emit('event', { id: e.id, phase: f.kind, t_s: state.t, from: a?.id, to: b?.id });
    }
  }
  mini.draw(state.t);
  hud.update(state.t);
  const cs = sc.cells[L.serving], ct = sc.cells[L.target];
  pill.innerHTML = `<span style="color:${cs?.color || '#888'}">${cs?.letter || '—'}</span>${ct ? `<span style="color:var(--gold)">→</span><span style="color:${ct.color}">${ct.letter}</span>` : ''}<span style="color:var(--faint)">${state.t.toFixed(1)} s</span>`;
  if (now - lastEmit > 250) { lastEmit = now; emit('tick', tickBody()); }
  if (now - lastStatus > 5000) { lastStatus = now; post({ type: `${PROTO_B}.status`, v: 1, fps: scene.fps ?? null, quality: scene.pixelRatio }); }
  if (sc.mode === 'live' && now - (state._modeAt || 0) > 1000) { state._modeAt = now; renderMode(); }
}

// ---------------------------------------------------------------- boot
(async () => {
  applyStatic(); $('btn-lang').textContent = getLang() === 'en' ? '한국어' : 'English';
  try {
    state.base = await loadBase();
    scene.setCampus(state.base.campus, state.base.route, getLang()); mini.setCampus(state.base.campus, state.base.route);
    const v = Q.get('view'); if (v) scene.setView(v); else renderViews('hero');
    const want = Q.get('scen') || { live: 'live', sample: 'sample', replay: 'v314', walk: 'walk' }[Q.get('mode') || 'replay'] || 'v314';
    if (EMBED && Q.get('embed') === 'operator' && !Q.get('scen') && !Q.get('mode')) {
      // Console is clock master: show the recorded scene until it sends its own.
      await selectScenario('seg0');
    } else await selectScenario(want);
    post({ type: `${PROTO_B}.ready`, v: 1, version: 'campus3d/1', capabilities: ['scene', 'tick', 'focus', 'view', 'lang'] });
    requestAnimationFrame(frame);
  } catch (err) {
    console.error(err);
    $('waiting').hidden = false; $('waiting').innerHTML = `<b>Campus twin failed to load</b>${esc(err.message || err)}`;
    post({ type: `${PROTO_B}.status`, v: 1, message: `twin load failed: ${err.message}` });
  }
})();
