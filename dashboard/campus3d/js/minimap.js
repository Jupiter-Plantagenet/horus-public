// 2D overview (north up). Static layer cached; dynamic overlay redrawn at ~8 Hz.
import { posAt, servingAt, armOf } from './sources.js';

export class MiniMap {
  constructor(canvas, onSeek) {
    this.c = canvas; this.g = canvas.getContext('2d'); this.onSeek = onSeek; this.last = 0;
    canvas.addEventListener('click', (e) => this._click(e));
  }
  setCampus(campus, route) {
    this.campus = campus; this.route = route;
    const p = route.sessions['t4-reverse'].points;
    let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
    p.x.forEach((x, i) => { x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, p.y[i]); y1 = Math.max(y1, p.y[i]); });
    const pad = 70; this.box = { x0: x0 - pad - 40, x1: x1 + pad + 40, y0: y0 - pad, y1: y1 + pad };
    this._layout(); this.staticLayer = null;
  }
  _layout() {
    const W = this.c.width, H = this.c.height, b = this.box;
    const s = Math.min((W - 16) / (b.x1 - b.x0), (H - 16) / (b.y1 - b.y0));
    this.s = s; this.ox = W / 2 - s * (b.x0 + b.x1) / 2; this.oy = H / 2 + s * (b.y0 + b.y1) / 2;
  }
  X(x) { return this.ox + x * this.s; } Y(y) { return this.oy - y * this.s; }
  _static() {
    const cv = document.createElement('canvas'); cv.width = this.c.width; cv.height = this.c.height;
    const g = cv.getContext('2d'), poly = (pts) => { g.beginPath(); pts.forEach(([x, y], i) => (i ? g.lineTo(this.X(x), this.Y(y)) : g.moveTo(this.X(x), this.Y(y)))); g.closePath(); };
    g.fillStyle = '#06132b'; g.fillRect(0, 0, cv.width, cv.height);
    if (this.campus.boundary) { poly(this.campus.boundary.poly); g.fillStyle = '#0b2148'; g.fill(); g.strokeStyle = 'rgba(255,213,79,.45)'; g.lineWidth = 1; g.stroke(); }
    g.strokeStyle = '#2b5487'; g.lineWidth = 1;
    for (const p of this.campus.paths) { g.beginPath(); p.pts.forEach(([x, y], i) => (i ? g.lineTo(this.X(x), this.Y(y)) : g.moveTo(this.X(x), this.Y(y)))); g.stroke(); }
    for (const b of this.campus.buildings) {
      poly(b.poly); const v = (b.name_ko || '').startsWith('산학협력관');
      g.fillStyle = v ? '#a3832b' : '#2a4f86'; g.fill();
      if (v) { g.strokeStyle = '#FFD54F'; g.lineWidth = 1.5; g.stroke(); }
    }
    const p = this.route.sessions['t4-reverse'].points;
    g.strokeStyle = 'rgba(120,150,190,.55)'; g.lineWidth = 2; g.beginPath();
    p.x.forEach((x, i) => (i ? g.lineTo(this.X(x), this.Y(p.y[i])) : g.moveTo(this.X(x), this.Y(p.y[i])))); g.stroke();
    g.fillStyle = 'rgba(159,179,209,.8)'; g.font = '600 10px Segoe UI, Malgun Gothic, sans-serif'; g.fillText('N ↑', 8, 14);
    // 100 m scale bar
    const L = 100 * this.s; g.fillStyle = 'rgba(159,179,209,.85)'; g.fillRect(8, cv.height - 10, L, 2); g.fillText('100 m', 10 + L, cv.height - 6);
    this.staticLayer = cv;
  }
  setScenario(sc) { this.sc = sc; this.scLayer = null; }
  _scLayer() {
    const sc = this.sc, cv = document.createElement('canvas'); cv.width = this.c.width; cv.height = this.c.height;
    const g = cv.getContext('2d'), P = sc.pos, prim = armOf(sc, sc.primary) || sc.arms[0];
    g.lineWidth = 3.2; g.lineCap = 'round';
    for (let i = 1; i < P.t.length; i++) {
      if (P.t[i] < sc.highlight[0] || P.t[i] > sc.highlight[1]) continue;
      const s = servingAt(prim, P.t[i]); g.strokeStyle = s >= 0 ? sc.cells[s].color : '#7d8ba0';
      g.beginPath(); g.moveTo(this.X(P.x[i - 1]), this.Y(P.y[i - 1])); g.lineTo(this.X(P.x[i]), this.Y(P.y[i])); g.stroke();
    }
    for (const c of sc.cells) {
      const x = this.X(c.anchor.x), y = this.Y(c.anchor.y);
      g.strokeStyle = c.color; g.lineWidth = 1.5; g.beginPath(); g.arc(x, y, 5, 0, Math.PI * 2); g.stroke();
      g.fillStyle = c.color; g.font = '700 10px Consolas, monospace'; g.fillText(c.letter, x + 6, y - 4);
    }
    this.scLayer = cv;
  }
  draw(t, force = false) {
    const now = performance.now(); if (!force && now - this.last < 120) return; this.last = now;
    if (!this.campus || !this.sc) return;
    if (!this.staticLayer) this._static(); if (!this.scLayer) this._scLayer();
    const g = this.g; g.drawImage(this.staticLayer, 0, 0); g.drawImage(this.scLayer, 0, 0);
    const sc = this.sc;
    for (const arm of sc.arms) for (const e of arm.events) {
      if (e.t > t) continue; const p = posAt(sc, e.t), x = this.X(p.x), y = this.Y(p.y);
      const completed = e.status === 'confirmed' && e.phases?.cu_confirmed != null && t >= e.phases.cu_confirmed;
      g.fillStyle = completed ? '#FFD54F' : e.status === 'failed' ? '#D72638' : e.status === 'observed' ? '#DDE6F3' : e.status === 'modelled' ? '#9FB3D1' : '#00D9FF';
      g.beginPath(); g.moveTo(x, y - 4); g.lineTo(x + 4, y); g.lineTo(x, y + 4); g.lineTo(x - 4, y); g.closePath(); g.fill();
    }
    if (!sc.pos.t.length) return;                       // no frames: no device dot
    const d = posAt(sc, t), x = this.X(d.x), y = this.Y(d.y);
    g.fillStyle = 'rgba(255,213,79,.25)'; g.beginPath(); g.arc(x, y, 9, 0, Math.PI * 2); g.fill();
    g.fillStyle = '#fff'; g.strokeStyle = '#FFD54F'; g.lineWidth = 2; g.beginPath(); g.arc(x, y, 4, 0, Math.PI * 2); g.fill(); g.stroke();
  }
  _click(e) {
    if (!this.sc || !this.onSeek) return;
    const r = this.c.getBoundingClientRect(), mx = (e.clientX - r.left) * this.c.width / r.width, my = (e.clientY - r.top) * this.c.height / r.height;
    const P = this.sc.pos; let best = -1, bd = 14 * 14;
    for (let i = 0; i < P.t.length; i++) {
      if (P.t[i] < this.sc.highlight[0] || P.t[i] > this.sc.highlight[1]) continue;
      const dx = this.X(P.x[i]) - mx, dy = this.Y(P.y[i]) - my, dd = dx * dx + dy * dy;
      if (dd < bd) { bd = dd; best = i; }
    }
    if (best >= 0) this.onSeek(P.t[best]);
  }
}
