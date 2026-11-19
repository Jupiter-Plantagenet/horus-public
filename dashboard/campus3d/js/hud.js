// DOM HUD + timeline. Pure presentation of the scenario at time t.
import { t as tr, getLang } from './i18n.js';
import { servingAt, frameAt, armOf } from './sources.js';

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const fmt = (v, d = 1) => (v == null || Number.isNaN(v) ? '—' : Number(v).toFixed(d));
const pct = (a, q) => (a.length ? a.slice().sort((x, y) => x - y)[Math.min(a.length - 1, Math.round(q * (a.length - 1)))] : null);

/** The event "in flight" at t (decision <= t < confirmation or a short hold after). */
export function activeEvent(sc, t) {
  let best = null;
  for (const arm of sc.arms) {
    if (arm.key !== sc.primary) continue;
    for (const e of arm.events) {
      const ph = e.phases || {}, end = ph.cu_confirmed ?? (e.t + 1.5);
      if (t >= e.t && t < end + 2.5) best = e;
    }
  }
  return best;
}
/** Serving/target as the RAN sees it: a handover is in flight from decision until
 *  CU RRC completion (or 1.5 s for events without RAN execution). */
export function currentLink(sc, t) {
  const prim = armOf(sc, sc.primary) || sc.arms[0];
  const twin = servingAt(prim, t);
  for (const e of prim ? prim.events.slice().reverse() : []) {
    if (t < e.t) continue;
    if (['acked', 'attempted'].includes(e.status) && e.phases?.cu_confirmed == null)
      return { serving: e.from, target: e.to, inflight: e, twin };
    if (e.status === 'failed') return { serving: e.from, target: -1, inflight: null, twin };
    const end = e.phases?.cu_confirmed ?? (e.status === 'confirmed' ? e.t : e.t + 1.5);
    if (t >= e.t && t < end) return { serving: e.from, target: e.to, inflight: e, twin };
    break; // a later completed event supersedes an older unresolved attempt
  }
  return { serving: twin, target: -1, inflight: null, twin };
}
export function lastEvent(sc, t) {
  const arm = armOf(sc, sc.primary); if (!arm) return null;
  let last = null; for (const e of arm.events) if (e.t <= t) last = e; return last;
}
export function serviceState(sc, t) {
  const arm = armOf(sc, sc.primary);
  if (arm?.interruptions) return arm.interruptions.some(([a, b]) => t >= a && t <= b) ? 'interrupted' : 'ok';
  if (!sc.rtt || !sc.rtt.window) return 'unknown';
  const [a, b] = sc.rtt.window; if (t < a || t > b + 3) return 'unknown';
  // a probe reply within the last 3 s means the session is answering
  const pts = sc.rtt.pts; let lo = 0, hi = pts.length - 1;
  while (lo < hi) { const m = (lo + hi + 1) >> 1; if (pts[m][0] <= t) lo = m; else hi = m - 1; }
  return pts[lo] && t - pts[lo][0] <= 3 && pts[lo][0] <= t ? 'ok' : 'unknown';
}

export class HUD {
  constructor({ onSeek, onCycle }) {
    this.onSeek = onSeek; this.onCycle = onCycle; this.tl = $('tl-canvas'); this.g = this.tl.getContext('2d');
    this.status = null; this.lastPanel = 0;
    let drag = false;
    const seek = (e) => { const r = this.tl.getBoundingClientRect(), x = e.clientX - r.left; if (x < this.lx) return; this.onSeek(this._t(x)); };
    this.tl.addEventListener('pointerdown', (e) => { drag = true; this.tl.setPointerCapture(e.pointerId); seek(e); });
    this.tl.addEventListener('pointermove', (e) => { if (drag) seek(e); });
    this.tl.addEventListener('pointerup', () => { drag = false; });
  }
  setStatus(s) { this.status = s; this.scStatic = null; }
  setScenario(sc) { this.sc = sc; this.tlStatic = null; this.scStatic = null; this.ticks = null; }
  _t(x) { const sc = this.sc; return Math.max(0, Math.min(sc.duration, (x - this.lx) / (this.tw) * sc.duration)); }
  _x(t) { return this.lx + (t / Math.max(1e-6, this.sc.duration)) * this.tw; }

  // ---------------------------------------------------------------- panels
  update(t, info = {}) {
    const sc = this.sc; if (!sc) return;
    $('t-now').textContent = fmt(t, 1); $('t-dur').textContent = fmt(sc.duration, 1);
    this._head(t);
    const now = performance.now(); if (now - this.lastPanel < 100 && !info.force) return; this.lastPanel = now;
    const link = currentLink(sc, t), act = activeEvent(sc, t);
    const s = link.serving, tgt = link.target;
    const cell = (i) => sc.cells[i];
    const chip = (el, i, label) => {
      const c = cell(i);
      el.classList.toggle('none', !c); el.style.color = c ? c.color : '';
      el.innerHTML = c ? `<div class="sm">${label}</div><div class="big">${esc(c.letter)}</div><div class="sm">${c.pci != null ? `PCI ${c.pci} · ` : ''}${esc((c.id || '').split('/')[3] || c.id)}</div>`
        : `<div class="sm">${label}</div><div class="big">—</div><div class="sm">${tr('none')}</div>`;
    };
    chip($('serving'), s, tr('serving')); chip($('target'), tgt, tr('target'));
    $('target-arrow').classList.toggle('on', tgt >= 0);
    // RSRP bars
    const fi = frameAt(sc, t), row = fi >= 0 ? sc.rsrp.v[fi] : null;
    $('rsrp-bars').innerHTML = sc.cells.map((c, i) => {
      const v = row ? row[i] : null, w = v == null ? 0 : Math.max(2, Math.min(100, (v + 125) / 65 * 100));
      return `<div class="bar ${i === s ? 'srv' : ''} ${v == null ? 'na' : ''}"><span class="l" style="color:${c.color}">${esc(c.letter)}</span>
        <span class="track"><span class="fill" style="display:block;width:${w}%;background:${c.color};opacity:${i === s ? 1 : 0.55}"></span></span>
        <span class="v">${v == null ? '—' : fmt(v, 1)}</span></div>`;
    }).join('');
    const sinr = sc.sinr && fi >= 0 ? sc.sinr[fi] : null;
    $('radio-kv').innerHTML = `<span class="k">RSRP dBm</span><span class="v">${sc.rsrp ? (sc.kind === 'sample' ? 'sample' : 'calibrated') : '—'}</span>`
      + (sinr != null ? `<span class="k">${tr('sinr')} (modelled)</span><span class="v">${fmt(sinr, 1)} dB</span>` : '')
      + (sc.kind === 'seg0' || sc.kind === 'live' ? `<span class="k">${tr('step')}</span><span class="v">${Math.max(0, Math.round(t * 10) - 1)}</span>` : '');
    this._ai(t, fi, act); this._ran(t, act); this._artifact(); this._evidence(t); this._service(t);
  }
  _ai(t, fi, act) {
    const sc = this.sc, el = $('ai-body');
    if (sc.kind === 'walk') {
      el.innerHTML = `<div class="kv"><span class="k">${getLang() === 'ko' ? '이 화면' : 'This view'}</span><span class="v"><span class="pill na">${getLang() === 'ko' ? '네트워크 자체 결정' : 'network’s own decisions'}</span></span></div>
        <div class="note">${tr('walk_note')}</div>`; return;
    }
    const pi = sc.profile && fi >= 0 ? sc.profile[fi] : (act?.profile?.index ?? null);
    const stg = sc.stage && fi >= 0 ? sc.stage[fi] : act?.stage;
    const tbl = sc.profileTable && pi != null && sc.profileTable[pi] ? { index: pi, ...sc.profileTable[pi] } : null;
    const p = act?.profile && (pi == null || act.profile.index === pi) ? act.profile : (tbl || this._profiles?.[pi] || act?.profile || null);
    if (act?.profile) { this._profiles = this._profiles || {}; this._profiles[act.profile.index] = act.profile; }
    const learned = stg === 'learned_profiles';
    el.innerHTML = `<div class="kv">
      <span class="k">${tr('profile')}</span><span class="v">${pi != null ? `#${pi}` : '—'}</span>
      <span class="k">${tr('stage')}</span><span class="v">${stg ? `<span class="pill ${learned ? 'ai' : 'na'}">${learned ? (getLang() === 'ko' ? '학습 프로파일' : 'learned profile') : (getLang() === 'ko' ? '웜업 기본값' : 'warm-up default')}</span>` : (sc.kind === 'sample' ? '<span class="pill na">sample</span>' : '—')}</span>
      ${p ? `<span class="k">${tr('prep')} / ${tr('exec')}</span><span class="v">${fmt(p.prep_offset_db, 0)} / ${fmt(p.exec_offset_db, 0)} dB</span>
      <span class="k">${tr('hys')} · ${tr('ttt')}</span><span class="v">${fmt(p.hys_db, 0)} dB · ${fmt((p.ttt_s ?? 0) * 1000, 0)} ms</span>` : ''}
    </div>`;
  }
  _ran(t, act) {
    const sc = this.sc, el = $('ran-body'), e = act || lastEvent(sc, t);
    if (!e || sc.kind === 'walk') {
      el.innerHTML = sc.kind === 'walk' ? `<div class="note">${getLang() === 'ko' ? '휴대폰 로그의 실제 셀 변경 (금색 아님 = HORUS 제어 아님)' : 'Cell changes from the phone log (not HORUS controls)'}</div>` : `<div class="note">${tr('ran_idle')}</div>`; return;
    }
    const ph = e.phases || {}, st = (k, lbl, gold) => {
      const at = ph[k], done = at != null && t >= at, active = at != null && !done && (k === 'cu_confirmed' ? t >= (ph.ack ?? e.t) : false);
      const dtx = at != null ? `+${fmt(at - e.t, 2)} s` : (e.status === 'modelled' ? tr('modelled') : '—');
      return `<div class="stage ${done ? 'done' : ''} ${done && gold ? 'gold' : ''} ${active ? 'active' : ''}"><b>${lbl}${done && gold ? ' ✓' : ''}</b>${dtx}</div>`;
    };
    const f = sc.cells[e.from], to = sc.cells[e.to], ev = e.evidence || {};
    el.innerHTML = `<div class="kv"><span class="k">${act ? tr('ho') : tr('ran_last')} ${e.n ?? ''}</span><span class="v">${f ? f.letter : '?'} → ${to ? to.letter : '?'}
      ${ev.source_du ? ` · ${tr('du')} ${esc(ev.source_du)} → ${esc(ev.target_du)}` : ev.ran ? ` · ${esc(ev.ran)}` : ''}</span></div>
      <div class="stages">${st('decision', tr('st_decision'))}${st('sent', tr('st_sent'))}${st('ack', tr('st_ack'))}${st('cu_confirmed', tr('st_cu'), true)}</div>
      <div class="note">${e.status === 'confirmed' ? esc(ev.completion_basis || ev.text || 'RIC ACK + new CU RRC completion') : e.status === 'modelled' ? (getLang() === 'ko' ? '트윈 모델 결정, RAN 실행 없음' : 'Twin decision only; no RAN execution') : esc(e.status)}
      ${ev.ric_ack_ms != null ? ` · ACK ${fmt(ev.ric_ack_ms, 1)} ms` : ''}${ev.decision_to_cu_ms != null ? ` · ${getLang() === 'ko' ? '결정→CU' : 'decision→CU'} ${fmt(ev.decision_to_cu_ms / 1000, 2)} s` : ''}${ev.interruption_ms != null ? ` · interruption ${ev.interruption_ms} ms (sample)` : ''}</div>`;
  }
  _artifact() {
    if (this.scStatic === 'done') return;
    const sc = this.sc, st = sc.artifact?.source === 'evidence' ? {} : this.status || {}, a = st.artifact || sc.artifact;
    const el = $('artifact-body');
    if (!a) { el.innerHTML = `<div class="note">artifact status: ${tr('status_np')}</div>`; return; }
    const stPill = (s) => { const v = (s && s.state) || 'pending'; return `<span class="pill ${v === 'pass' ? 'ok' : v === 'fail' ? 'bad' : v === 'running' ? 'ai' : 'na'}">${esc(v === 'pending' ? tr('pending') : v)}</span>`; };
    const fed = st.federation || a.federation, gate = st.gate || a.gate;
    el.innerHTML = `<div class="kv">
      <span class="k">${getLang() === 'ko' ? '버전' : 'Version'}</span><span class="v"><b style="color:var(--gold)">${esc(a.version)}</b> <span class="pill ${a.kind === 'federated' ? 'ai' : 'na'}">${a.kind === 'federated' ? tr('artifact_fed') : a.kind === 'central' ? tr('artifact_central') : tr('status_np')}</span></span>
      <span class="k">${tr('fed_pending')}</span><span class="v">${stPill(fed)}${fed?.rounds ? ` ${fed.rounds} rounds · ${fed.clients} clients` : ''}</span>
      <span class="k">${tr('gate')}</span><span class="v">${stPill(gate)}</span></div>
      <div class="note">${esc(getLang() === 'ko' ? (a.labelKo || a.label) : a.label)}${st.artifact ? ' · console' : ''}</div>`;
    this.scStatic = 'done';
  }
  _evidence(t) {
    const sc = this.sc, el = $('accept-body'), ko = getLang() === 'ko';
    if (sc.acceptance) {
      const A = sc.acceptance;
      if (this._evKey !== sc.cycleIndex) {
        this._evKey = sc.cycleIndex;
        el.innerHTML = `<div class="big-stat"><div><b>${A.cycles}/${A.cycles}</b><span>${tr('cycles')}</span></div>
          <div><b>${A.confirmed_handovers}/${A.confirmed_handovers + A.failed_controls}</b><span>${tr('confirmed')}</span></div>
          <div><b>${A.kind === 'bounded' ? `${(A.native_seconds / 60).toFixed(1)} min` : `${((A.host_seconds ?? A.native_seconds) / 3600).toFixed(2)} h`}</b><span>${A.kind === 'bounded' ? (ko ? '제한 검증' : 'bounded run') : tr('two_hour')}</span></div></div>
          <div class="kv"><span class="k">${tr('dec_cu')}</span><span class="v">${fmt(A.decision_to_cu_ms.p50 / 1000, 2)} s (p95 ${fmt(A.decision_to_cu_ms.p95 / 1000, 2)})</span>
          <span class="k">${tr('ack')}</span><span class="v">${fmt(A.ric_ack_ms.p50, 1)} ms (p95 ${fmt(A.ric_ack_ms.p95, 1)})</span>
          <span class="k">${tr('faults')}</span><span class="v">${sc.cycle?.runtime ? `${sc.cycle.runtime.model_faults} / ${sc.cycle.runtime.fallback_frames}` : '0 / 0'} · ${A.inference_calls.toLocaleString()} ${ko ? '추론' : 'calls'}</span></div>
          <div class="cycle-pick"><span>${tr('cycle')}</span><select id="cycle-sel">${sc.cycles.map((c, i) => `<option value="${i}" ${i === sc.cycleIndex ? 'selected' : ''}>${esc(c)}</option>`).join('')}</select></div>`;
        $('cycle-sel').addEventListener('change', (e) => this.onCycle(+e.target.value));
      }
      return;
    }
    this._evKey = null;
    if (sc.comparison) {
      const a = sc.comparison.arms, sel = Object.keys(a).find((k) => k.startsWith('selector_'));
      const row = (k, lbl) => a[k] ? `<tr><th>${lbl}</th><td>${a[k].totals.ho_attempts}</td><td>${a[k].totals.ping_pongs}</td><td>${a[k].totals.rlf}</td><td>${fmt(a[k].totals.mean_thr_mbps, 1)}</td></tr>` : '';
      const V = sc.verdicts, d3 = (x) => `${x >= 0 ? '+' : ''}${fmt(x, 3)}`, ci = (u) => `${d3(u[0])} [${d3(u[1])}, ${d3(u[2])}]`;
      const verdict = V ? `<div class="kv">
          <span class="k">${ko ? '트윈 홀드아웃' : 'Twin held-out'}</span><span class="v"><span class="pill ${V.twin.H2 ? 'ok' : 'bad'}">${V.twin.headline}</span> ${V.twin.episodes} ${ko ? '쌍' : 'paired'}</span>
          <span class="k">${ko ? '· vs 네트워크 CHO' : '· vs network CHO'}</span><span class="v">${ci(V.twin.vs.cho_global.utility)}</span>
          <span class="k">· vs MRO CHO</span><span class="v">${ci(V.twin.vs.cho_mro.utility)}</span>
          <span class="k">${ko ? '· vs 셀별 오라클' : '· vs ext. oracle'}</span><span class="v">${ci(V.twin.vs.cho_tuned_ext.utility)}</span>
          <span class="k"></span><span class="v"><span class="pill na">${ko ? 'H1 미주장' : 'H1 not claimed'}</span></span>
          <span class="k">${ko ? '실측 경로' : 'Measured route'}</span><span class="v"><span class="pill ${V.measured.H2 ? 'ok' : 'bad'}">H2 ${V.measured.H2 ? 'PASS' : 'FAIL'}</span> ${V.measured.episodes} ${ko ? '에피소드' : 'faded'}</span>
          <span class="k">${ko ? '· vs 네트워크 CHO' : '· vs network CHO'}</span><span class="v">${ci(V.measured.vs.cho_global)}</span>
          <span class="k">· vs MRO CHO</span><span class="v">${ci(V.measured.vs.cho_mro)}</span></div>
          <div class="note">${ko ? '실측 경로: 핑퐁 가드레일 실패 (레일리 페이딩 층)' : 'Measured route: ping-pong guardrail fails under the Rayleigh fading layer'}</div>` : '';
      el.innerHTML = `${verdict}<table class="cmp"><thead><tr><th></th><th>HO</th><th>PP</th><th>RLF</th><th>Mb/s</th></tr></thead>
        <tbody>${row(sel, sel ? `HORUS ${sel.slice(9)}` : tr('cmp_horus'))}${row('cho_global', tr('cmp_cho'))}${row('cho_mro', tr('cmp_mro'))}${row('a3_stock', tr('cmp_a3'))}${row('cho_default', 'CHO default')}</tbody></table>
        <div class="note"><span class="tag modelled">modelled</span> ${ko ? '동일 경로·동일 시간축·동일 가정의 TwinSim 재생. 현장 측정 아님.' : 'TwinSim replay, same route, time base and assumptions. Not a field measurement.'}</div>`;
      return;
    }
    if (sc.kind === 'sample') {
      const s = (k) => { const a = armOf(sc, k); return a ? a.interruptions.reduce((x, [p, q]) => x + (q - p), 0) * 1000 : 0; };
      el.innerHTML = `<div class="kv"><span class="k">HORUS interruption</span><span class="v">${fmt(s('horus'), 0)} ms</span>
        <span class="k">Baseline interruption</span><span class="v">${fmt(s('baseline'), 0)} ms</span></div>
        <div class="note"><span class="tag sample">sample</span> ${ko ? '합성 데이터 — 결과 아님' : 'Synthetic — exercises the paired view, not a result'}</div>`;
      return;
    }
    el.innerHTML = sc.kind === 'live' ? `<div class="note">${ko ? '사이클' : 'Cycle'} ${esc(sc.live?.cycle || '—')} · ${sc.arms[0].events.filter((e) => e.status === 'confirmed').length} ${tr('confirmed')}</div>`
      : `<div class="note">${ko ? '콘솔이 제공한 장면' : 'Scene supplied by the operator console'}</div>`;
  }
  _service(t) {
    const sc = this.sc, el = $('service-body'), ko = getLang() === 'ko';
    if (!sc.rtt || !sc.rtt.pts.length) {
      el.innerHTML = `<div class="kv"><span class="k">RTT</span><span class="v"><span class="pill na">${tr('pending')}</span></span></div>
        <div class="note">${sc.kind === 'walk' ? (ko ? '보행 로그에는 서비스 프로브가 없음' : 'The phone walk log carries no service probes') : (ko ? '서비스 측정 미수신' : 'No service measurements received')}</div>`; return;
    }
    const pts = sc.rtt.pts, upto = pts.filter((p) => p[0] <= t).map((p) => p[1]);
    const arm = armOf(sc, sc.primary), after = (arm?.events || []).filter((e) => e.phases?.cu_confirmed != null && e.phases.cu_confirmed <= t).map((e, i, all) => {
      const next = (arm.events[arm.events.indexOf(e) + 1] || {}).t ?? Infinity; return pts.filter((p) => p[0] > e.phases.cu_confirmed && p[0] < next && p[0] <= t).length;
    });
    el.innerHTML = `<canvas class="spark" id="spark" width="300" height="44"></canvas>
      <div class="kv"><span class="k">${tr('rtt_p50')} / ${tr('rtt_p95')}</span><span class="v">${upto.length ? `${fmt(pct(upto, 0.5), 0)} / ${fmt(pct(upto, 0.95), 0)} ms` : '—'}</span>
      ${after.length ? `<span class="k">${tr('replies_after')}</span><span class="v">${after.join(' · ')}</span>` : ''}</div>
      <div class="note">${sc.kind === 'sample' ? '<span class="tag sample">sample</span> synthetic' : tr('probes')}</div>`;
    const c = $('spark'), g = c.getContext('2d'), W = c.width, H = c.height, [a, b] = [0, sc.duration], max = Math.max(250, ...pts.map((p) => p[1]));
    const X = (tt) => (tt - a) / (b - a) * W, Y = (v) => H - 3 - v / max * (H - 6);
    if (sc.rtt.window) { g.fillStyle = 'rgba(125,139,160,.12)'; g.fillRect(0, 0, X(sc.rtt.window[0]), H); g.fillRect(X(sc.rtt.window[1]), 0, W, H); }
    g.strokeStyle = 'rgba(46,204,113,.35)'; g.setLineDash([3, 3]); g.beginPath(); g.moveTo(0, Y(100)); g.lineTo(W, Y(100)); g.stroke(); g.setLineDash([]);
    g.strokeStyle = '#2ECC71'; g.lineWidth = 1.4; g.beginPath(); let first = true;
    for (const [tt, v] of pts) { if (tt > t) break; first ? g.moveTo(X(tt), Y(v)) : g.lineTo(X(tt), Y(v)); first = false; } g.stroke();
    for (const e of arm?.events || []) if (e.phases?.cu_confirmed != null && e.phases.cu_confirmed <= t) { g.fillStyle = '#FFD54F'; g.fillRect(X(e.phases.cu_confirmed) - 1, 0, 2, H); }
    g.fillStyle = '#FFD54F'; g.fillRect(X(t) - 0.5, 0, 1, H);
  }

  // ---------------------------------------------------------------- timeline
  _head(t) {
    if (!this.tw) this._tlStatic();
    $('tl-head').style.left = `${this._x(t)}px`;
  }
  redrawTimeline() { this.tlStatic = null; this._tlStatic(); }
  _tlStatic() {
    const sc = this.sc, c = this.tl, r = c.getBoundingClientRect(); if (!sc || !r.width) return;
    const dpr = Math.min(2, window.devicePixelRatio || 1); c.width = r.width * dpr; c.height = r.height * dpr;
    const g = this.g; g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, r.width, r.height);
    const ko = getLang() === 'ko', fs = Math.max(10, Math.min(14, r.height / 10));
    this.lx = Math.max(78, fs * 7); this.tw = r.width - this.lx - 12;
    const lanes = [];
    const prim = armOf(sc, sc.primary) || sc.arms[0];
    lanes.push({ k: tr('lane_cells'), draw: (y, h) => this._laneServing(g, prim, y, h) });
    for (const arm of sc.arms) lanes.push({ k: arm.key === 'horus' ? tr('lane_horus') : arm.key === 'network' ? tr('lane_net') : tr('lane_base'), draw: (y, h) => this._laneEvents(g, arm, y, h) });
    if (sc.comparison) lanes.push({ k: ko ? 'HO 비교' : 'HO / seg.', draw: (y, h) => this._laneCompare(g, y, h) });
    else if (!armOf(sc, 'baseline') && sc.kind !== 'walk') lanes.push({ k: tr('lane_base'), draw: (y, h) => this._lanePending(g, y, h, ko ? '동일 시간·부하의 기준 실행: 백엔드 수신 대기' : 'Paired baseline on identical time & workload: pending backend receipt') });
    lanes.push({ k: tr('lane_rtt'), draw: (y, h) => this._laneRtt(g, y, h) });
    const top = 6, H = (r.height - top - 16) / lanes.length;
    g.font = `600 ${fs}px Segoe UI, Malgun Gothic, sans-serif`; g.textBaseline = 'middle';
    lanes.forEach((L, i) => {
      const y = top + i * H; g.fillStyle = 'rgba(143,163,192,.06)'; g.fillRect(this.lx, y + 1, this.tw, H - 2);
      g.fillStyle = '#9FB3D1'; g.fillText(L.k, 8, y + H / 2); L.draw(y + 2, H - 4);
    });
    // axis
    g.fillStyle = '#5E7697'; g.font = `${fs * 0.85}px Consolas, monospace`; g.textBaseline = 'alphabetic';
    const step = [5, 10, 20, 30, 60, 120, 300, 600].find((s) => sc.duration / s <= 10) || 600;
    for (let s = 0; s <= sc.duration; s += step) { const x = this._x(s); g.fillRect(x, r.height - 13, 1, 4); g.fillText(`${s}s`, x + 2, r.height - 3); }
    this.tlStatic = true;
  }
  _laneServing(g, arm, y, h) {
    const sc = this.sc; if (!arm) return;
    arm.serving.forEach(([t0, s], i) => {
      const t1 = i + 1 < arm.serving.length ? arm.serving[i + 1][0] : sc.duration, x0 = this._x(Math.max(0, t0)), x1 = this._x(Math.min(sc.duration, t1));
      g.fillStyle = s >= 0 ? sc.cells[s].color : '#3a4a60'; g.globalAlpha = 0.85; g.fillRect(x0, y + h * 0.15, Math.max(1, x1 - x0), h * 0.7); g.globalAlpha = 1;
      if (x1 - x0 > 16 && s >= 0) { g.fillStyle = '#081C3A'; g.fillText(sc.cells[s].letter, x0 + 4, y + h / 2); }
    });
  }
  _laneEvents(g, arm, y, h) {
    const sc = this.sc, cy = y + h / 2;
    for (const e of arm.events) {
      const ph = e.phases || {}, x = this._x(e.t);
      if (ph.cu_confirmed != null) { g.strokeStyle = 'rgba(255,213,79,.6)'; g.lineWidth = 2; g.beginPath(); g.moveTo(x, cy); g.lineTo(this._x(ph.cu_confirmed), cy); g.stroke(); }
      const col = e.status === 'confirmed' ? '#00D9FF' : e.status === 'failed' ? '#D72638' : e.status === 'observed' ? '#DDE6F3' : e.status === 'modelled' ? '#9FB3D1' : '#00D9FF';
      const r = Math.min(6, h * 0.35);
      g.fillStyle = col; g.beginPath(); g.moveTo(x, cy - r); g.lineTo(x + r, cy); g.lineTo(x, cy + r); g.lineTo(x - r, cy); g.closePath(); g.fill();
      if (ph.cu_confirmed != null) { const xc = this._x(ph.cu_confirmed); g.fillStyle = '#FFD54F'; g.beginPath(); g.arc(xc, cy, r * 0.8, 0, Math.PI * 2); g.fill(); }
      if (arm.interruptions) for (const [a, b] of arm.interruptions) { g.fillStyle = '#D72638'; g.fillRect(this._x(a), y + h - 4, Math.max(2, this._x(b) - this._x(a)), 4); }
    }
  }
  _laneCompare(g, y, h) {
    const A = this.sc.comparison.arms, H = A[Object.keys(A).find((k) => k.startsWith('selector_'))], B = A.cho_global || A.a3_stock; if (!H || !B) return;
    const max = Math.max(1, ...H.segments.map((s) => s.ho), ...B.segments.map((s) => s.ho));
    H.segments.forEach((s, i) => {
      const b = B.segments[i]; const x0 = this._x(s.start_s), w = Math.max(2, this._x(s.end_s) - x0);
      g.fillStyle = 'rgba(0,217,255,.75)'; const hh = s.ho / max * (h / 2 - 1); g.fillRect(x0, y + h / 2 - hh, w * 0.98, hh);
      g.fillStyle = 'rgba(159,179,209,.75)'; const hb = (b ? b.ho : 0) / max * (h / 2 - 1); g.fillRect(x0, y + h / 2 + 1, w * 0.98, hb);
    });
  }
  _lanePending(g, y, h, text) {
    g.save(); g.beginPath(); g.rect(this.lx, y, this.tw, h); g.clip();
    g.strokeStyle = 'rgba(125,139,160,.25)'; for (let x = this.lx - h; x < this.lx + this.tw; x += 8) { g.beginPath(); g.moveTo(x, y + h); g.lineTo(x + h, y); g.stroke(); }
    g.restore(); g.fillStyle = '#9FB3D1'; g.fillText(text, this.lx + 8, y + h / 2);
  }
  _laneRtt(g, y, h) {
    const sc = this.sc;
    if (!sc.rtt || !sc.rtt.pts.length) { this._lanePending(g, y, h, sc.kind === 'walk' ? (getLang() === 'ko' ? '보행 로그에 서비스 프로브 없음' : 'no service probes in the walk log') : tr('pending')); return; }
    const pts = sc.rtt.pts, max = Math.max(250, ...pts.map((p) => p[1])), Y = (v) => y + h - v / max * h;
    if (sc.rtt.window) { g.fillStyle = 'rgba(125,139,160,.14)'; g.fillRect(this.lx, y, this._x(sc.rtt.window[0]) - this.lx, h); g.fillRect(this._x(sc.rtt.window[1]), y, this.lx + this.tw - this._x(sc.rtt.window[1]), h); }
    g.strokeStyle = 'rgba(46,204,113,.3)'; g.setLineDash([3, 3]); g.beginPath(); g.moveTo(this.lx, Y(100)); g.lineTo(this.lx + this.tw, Y(100)); g.stroke(); g.setLineDash([]);
    g.strokeStyle = '#2ECC71'; g.lineWidth = 1.3; g.beginPath(); pts.forEach(([t, v], i) => (i ? g.lineTo(this._x(t), Y(v)) : g.moveTo(this._x(t), Y(v)))); g.stroke();
    const arm = armOf(sc, sc.primary);
    if (arm?.interruptions) for (const [a, b] of arm.interruptions) { g.fillStyle = 'rgba(215,38,56,.8)'; g.fillRect(this._x(a), y, Math.max(2, this._x(b) - this._x(a)), h); }
  }
}
