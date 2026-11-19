// HORUS finals dashboard — small SVG chart kit (no dependencies).
// Marks follow the dataviz rules: one y-axis per chart, 2px lines, recessive grid,
// legend + end-of-line direct labels for <=4 series, crosshair tooltip on hover.
(function () {
  const NS = "http://www.w3.org/2000/svg";
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const fs = () => parseFloat(getComputedStyle(document.body).fontSize) || 14;
  const kstFmt = new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Seoul", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
  const hms = (t) => kstFmt.format(new Date(t * 1000));
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const fmt = (v, d = 1) => (v === null || v === undefined || Number.isNaN(v) ? "–" : Number(v).toFixed(d));

  function niceTicks(lo, hi, n = 4) {
    if (!(hi > lo)) { hi = lo + 1; }
    const raw = (hi - lo) / n, mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) || raw;
    const a = Math.floor(lo / step) * step, b = Math.ceil(hi / step) * step, out = [];
    for (let v = a; v <= b + step / 2; v += step) out.push(+v.toFixed(6));
    return out;
  }

  const tip = () => document.getElementById("tip");
  function showTip(x, y, html) {
    const el = tip(); el.innerHTML = html; el.hidden = false;
    const w = el.offsetWidth, h = el.offsetHeight;
    el.style.left = Math.min(x + 14, innerWidth - w - 8) + "px";
    el.style.top = Math.max(8, Math.min(y - h - 10, innerHeight - h - 8)) + "px";
  }
  function hideTip() { tip().hidden = true; }

  function svg(w, h) {
    const s = document.createElementNS(NS, "svg");
    s.setAttribute("width", w); s.setAttribute("height", h); s.setAttribute("viewBox", `0 0 ${w} ${h}`);
    return s;
  }
  function add(parent, tag, attrs, text) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (text !== undefined) e.textContent = text;
    parent.appendChild(e); return e;
  }

  // ---------------------------------------------------------------- line --
  // opts: {series:[{name,color,dash,area,pts:[[t,v]]}], t0,t1, h, unit, yZero, digits,
  //        marks:[{t,color,label}], bands:[{t0,t1,color}], empty}
  function line(el, o) {
    const F = fs(), w = Math.max(el.clientWidth || 600, 240), h = o.h || F * 14;
    const pl = F * 3.1, pr = F * 4.6, pt = F * 0.9, pb = F * 1.7;
    const all = o.series.flatMap((s) => s.pts.filter((p) => p[1] !== null).map((p) => p[1]));
    el.innerHTML = "";
    if (!all.length) { el.innerHTML = `<div class="empty" style="height:${h}px;display:grid;place-items:center">${esc(o.empty || "–")}</div>`; return; }
    let lo = Math.min(...all), hi = Math.max(...all);
    if (o.yZero) lo = Math.min(0, lo);
    const pad = (hi - lo) * 0.12 || 1; if (!o.yZero) lo -= pad; hi += pad;
    const ticks = niceTicks(lo, hi); lo = ticks[0]; hi = ticks[ticks.length - 1];
    const t0 = o.t0, t1 = Math.max(o.t1, o.t0 + 1);
    const X = (t) => pl + ((t - t0) / (t1 - t0)) * (w - pl - pr);
    const Y = (v) => h - pb - ((v - lo) / (hi - lo)) * (h - pt - pb);
    const s = svg(w, h), dim = css("--dim"), grid = css("--grid"), mute = css("--mute");
    ticks.forEach((v) => {
      add(s, "line", { x1: pl, x2: w - pr, y1: Y(v), y2: Y(v), stroke: grid, "stroke-width": 1 });
      add(s, "text", { x: pl - F * 0.4, y: Y(v) + F * 0.3, "text-anchor": "end", "font-size": F * 0.72, fill: mute }, +v.toFixed(2));
    });
    for (let i = 0; i <= 3; i++) {
      const t = t0 + (i / 3) * (t1 - t0);
      add(s, "text", { x: X(t), y: h - F * 0.35, "text-anchor": i === 0 ? "start" : i === 3 ? "end" : "middle", "font-size": F * 0.72, fill: mute }, hms(t));
    }
    (o.bands || []).forEach((b) => add(s, "rect", { x: X(Math.max(b.t0, t0)), y: pt, width: Math.max(0, X(Math.min(b.t1, t1)) - X(Math.max(b.t0, t0))), height: h - pt - pb, fill: b.color, opacity: 0.12, rx: 4 }));
    const defs = add(s, "defs", {});
    const ends = [];
    o.series.forEach((se, i) => {
      const pts = se.pts.filter((p) => p[0] >= t0 - 1 && p[0] <= t1 + 1);
      let d = "", pen = false, seg = [], segs = [];
      pts.forEach(([t, v]) => {
        if (v === null) { pen = false; if (seg.length) segs.push(seg); seg = []; return; }
        d += `${pen ? "L" : "M"}${X(t).toFixed(1)},${Y(v).toFixed(1)}`; pen = true; seg.push([X(t), Y(v)]);
      });
      if (seg.length) segs.push(seg);
      if (se.area) {
        const gid = `g${Math.random().toString(36).slice(2, 8)}`;
        const lg = add(defs, "linearGradient", { id: gid, x1: 0, y1: 0, x2: 0, y2: 1 });
        add(lg, "stop", { offset: 0, "stop-color": se.color, "stop-opacity": 0.32 });
        add(lg, "stop", { offset: 1, "stop-color": se.color, "stop-opacity": 0 });
        segs.forEach((sg) => {
          if (sg.length < 2) return;
          const a = `M${sg[0][0]},${h - pb}` + sg.map((p) => `L${p[0].toFixed(1)},${p[1].toFixed(1)}`).join("") + `L${sg[sg.length - 1][0]},${h - pb}Z`;
          add(s, "path", { d: a, fill: `url(#${gid})` });
        });
      }
      add(s, "path", { d, fill: "none", stroke: se.color, "stroke-width": se.width || 2, "stroke-linejoin": "round", "stroke-dasharray": se.dash ? "5 4" : "none" });
      const last = [...pts].reverse().find((p) => p[1] !== null);
      if (last) ends.push({ y: Y(last[1]), x: X(last[0]), v: last[1], se });
    });
    (o.marks || []).forEach((m) => {
      if (m.t < t0 || m.t > t1) return;
      add(s, "line", { x1: X(m.t), x2: X(m.t), y1: pt, y2: h - pb, stroke: m.color, "stroke-width": 2, "stroke-dasharray": "3 3" });
      if (m.label) add(s, "text", { x: X(m.t) + 4, y: pt + F * 0.8, "font-size": F * 0.72, fill: m.color, "font-weight": 700 }, m.label);
    });
    // end-of-line direct labels, nudged apart
    ends.sort((a, b) => a.y - b.y);
    for (let i = 1; i < ends.length; i++) if (ends[i].y - ends[i - 1].y < F * 1.0) ends[i].y = ends[i - 1].y + F * 1.0;
    if (ends.length <= 4) ends.forEach((e) => {
      add(s, "circle", { cx: e.x, cy: Y(e.v), r: 3.5, fill: e.se.color, stroke: css("--panel"), "stroke-width": 2 });
      add(s, "text", { x: w - pr + F * 0.45, y: e.y + F * 0.3, "font-size": F * 0.72, fill: dim, "font-weight": 600 }, `${fmt(e.v, o.digits ?? 1)} ${e.se.short || ""}`.trim());
    });
    // hover layer
    const cross = add(s, "line", { y1: pt, y2: h - pb, stroke: dim, "stroke-width": 1, opacity: 0 });
    const hot = add(s, "rect", { x: pl, y: 0, width: w - pl - pr, height: h, fill: "transparent" });
    const onMove = (ev) => {
      const r = s.getBoundingClientRect(), x = ev.clientX - r.left, t = t0 + ((x - pl) / (w - pl - pr)) * (t1 - t0);
      el._hx = x; cross.setAttribute("x1", x); cross.setAttribute("x2", x); cross.setAttribute("opacity", 0.6);
      const rows = o.series.map((se) => {
        let best = null; for (const p of se.pts) if (best === null || Math.abs(p[0] - t) < Math.abs(best[0] - t)) best = p;
        return `<div class="tr"><span><span class="sw${se.dash ? " dash" : ""}" style="background:${se.color};border-color:${se.color}"></span> ${esc(se.name)}</span><b>${best && best[1] !== null ? fmt(best[1], o.digits ?? 1) + " " + (o.unit || "") : "–"}</b></div>`;
      }).join("");
      showTip(ev.clientX, ev.clientY, `<div class="tt">${hms(t)} KST</div>${rows}`);
    };
    hot.addEventListener("mousemove", onMove);
    hot.addEventListener("mouseleave", () => { el._hx = null; cross.setAttribute("opacity", 0); hideTip(); });
    el.appendChild(s);
  }

  // ------------------------------------------------------------- CI dots --
  // arms:[{id,label,color}], values:{id:{mean,ci_low,ci_high,n}}
  function ci(el, arms, values, unit, digits) {
    const F = fs(), w = Math.max(el.clientWidth || 500, 200), rowH = F * 1.55, h = rowH * arms.length + F * 1.6;
    const pl = F * 0.5, pr = F * 0.5;
    const xs = arms.flatMap((a) => { const v = values[a.id]; return v ? [v.ci_low ?? v.mean, v.ci_high ?? v.mean, v.mean] : []; });
    el.innerHTML = "";
    if (!xs.length) return;
    const ticks = niceTicks(Math.min(...xs), Math.max(...xs), 4), lo = ticks[0], hi = ticks[ticks.length - 1];
    const X = (v) => pl + ((v - lo) / (hi - lo || 1)) * (w - pl - pr);
    const s = svg(w, h), grid = css("--grid"), mute = css("--mute");
    ticks.forEach((v) => {
      add(s, "line", { x1: X(v), x2: X(v), y1: 0, y2: h - F * 1.3, stroke: grid });
      add(s, "text", { x: X(v), y: h - F * 0.2, "text-anchor": "middle", "font-size": F * 0.7, fill: mute }, +v.toFixed(3));
    });
    arms.forEach((a, i) => {
      const v = values[a.id]; if (!v) return;
      const y = rowH * i + rowH / 2;
      const g = add(s, "g", {});
      if (v.ci_low !== null && v.ci_high !== null) {
        add(g, "line", { x1: X(v.ci_low), x2: X(v.ci_high), y1: y, y2: y, stroke: a.color, "stroke-width": 2.5, "stroke-linecap": "round" });
        [v.ci_low, v.ci_high].forEach((c) => add(g, "line", { x1: X(c), x2: X(c), y1: y - F * 0.35, y2: y + F * 0.35, stroke: a.color, "stroke-width": 2 }));
      }
      add(g, "circle", { cx: X(v.mean), cy: y, r: a.id === "policy" ? F * 0.48 : F * 0.38, fill: a.color, stroke: css("--panel"), "stroke-width": 2 });
      add(g, "rect", { x: 0, y: y - rowH / 2, width: w, height: rowH, fill: "transparent" });
      g.addEventListener("mousemove", (ev) => showTip(ev.clientX, ev.clientY,
        `<div class="tt">${esc(a.label)}</div><div class="tr"><span>mean</span><b>${fmt(v.mean, digits)} ${esc(unit)}</b></div>` +
        `<div class="tr"><span>95% CI</span><b>${fmt(v.ci_low, digits)} – ${fmt(v.ci_high, digits)}</b></div><div class="tr"><span>n</span><b>${v.n ?? "–"}</b></div>`));
      g.addEventListener("mouseleave", hideTip);
    });
    el.appendChild(s);
  }

  // ----------------------------------------------------------- histogram --
  function hist(el, bins, color, unit) {
    const F = fs(), w = Math.max(el.clientWidth || 300, 160), h = F * 7.5, pb = F * 1.4;
    el.innerHTML = "";
    if (!bins || !bins.length) { el.innerHTML = `<div class="empty">–</div>`; return; }
    const top = Math.max(...bins.map((b) => b[2])) || 1, slot = w / bins.length, s = svg(w, h), mute = css("--mute");
    bins.forEach((b, i) => {
      const bh = Math.max(2, (b[2] / top) * (h - pb - F * 0.4)), x = i * slot + 1;
      const r = add(s, "rect", { x, y: h - pb - bh, width: Math.max(1, slot - 2), height: bh, rx: 3, fill: color });
      r.addEventListener("mousemove", (ev) => showTip(ev.clientX, ev.clientY, `<div class="tt">${fmt(b[0])}–${fmt(b[1])} ${unit}</div><div class="tr"><span>count</span><b>${b[2]}</b></div>`));
      r.addEventListener("mouseleave", hideTip);
    });
    add(s, "text", { x: 0, y: h - F * 0.2, "font-size": F * 0.7, fill: mute }, `${fmt(bins[0][0])} ${unit}`);
    add(s, "text", { x: w, y: h - F * 0.2, "font-size": F * 0.7, fill: mute, "text-anchor": "end" }, `${fmt(bins[bins.length - 1][1])} ${unit}`);
    el.appendChild(s);
  }

  // ------------------------------------------------------- Korea (schematic) --
  // Simplified South Korea coastline (lon, lat), clockwise from Ganghwa; Jeju as an ellipse.
  const KOREA = [[126.10, 37.72], [126.65, 37.95], [127.10, 38.30], [127.80, 38.32], [128.35, 38.62], [128.60, 38.20],
    [128.90, 37.78], [129.17, 37.45], [129.42, 37.05], [129.40, 36.45], [129.57, 36.08], [129.45, 35.50], [129.20, 35.15],
    [128.95, 35.05], [128.60, 35.05], [128.43, 34.83], [127.95, 34.85], [127.70, 34.72], [127.35, 34.55], [126.95, 34.42],
    [126.52, 34.30], [126.30, 34.70], [126.42, 35.05], [126.42, 35.45], [126.60, 35.98], [126.50, 36.35], [126.13, 36.70],
    [126.55, 37.00], [126.62, 37.40]];
  function korea(el, campuses, opt) {
    const F = fs(), w = Math.max(el.clientWidth || 420, 240);
    const lon0 = 125.7, lon1 = 130.2, lat0 = 33.0, lat1 = 38.75, k = Math.cos((36 * Math.PI) / 180);
    const maxH = Math.max(F * 18, innerHeight - el.getBoundingClientRect().top - F * 2.5);
    const sx = Math.min((w - 20) / ((lon1 - lon0) * k), (maxH - 20) / (lat1 - lat0));
    const h = (lat1 - lat0) * sx + 20, ox = (w - (lon1 - lon0) * k * sx) / 2;
    const P = (lon, lat) => [ox + (lon - lon0) * k * sx, 10 + (lat1 - lat) * sx];
    const s = svg(w, h);
    const d = KOREA.map((p, i) => (i ? "L" : "M") + P(p[0], p[1]).map((v) => v.toFixed(1)).join(",")).join("") + "Z";
    add(s, "path", { d, fill: "#13213A", stroke: "#2A3B5A", "stroke-width": 1.5, "stroke-linejoin": "round" });
    const [jx, jy] = P(126.55, 33.38);
    add(s, "ellipse", { cx: jx, cy: jy, rx: 0.40 * k * sx, ry: 0.17 * sx, fill: "#13213A", stroke: "#2A3B5A", "stroke-width": 1.5 });
    add(s, "text", { x: w - 8, y: h - 6, "text-anchor": "end", "font-size": F * 0.7, fill: css("--mute") }, opt.note || "");
    const col = { promote: css("--ok"), reject: css("--bad"), pending: css("--warn") };
    const pts = campuses.filter((c) => c.lat !== null && c.lon !== null).map((c) => {
      const [x, y] = P(c.lon, c.lat), r = Math.max(F * 0.45, Math.min(F * 1.0, Math.sqrt(c.sites || 25) * F * 0.06));
      const text = opt.label(c), tw = text.length * F * 0.78 * (/[가-힣]/.test(text) ? 1.0 : 0.6);
      return { c, x, y, r, text, tw, lx: x + r + 5, ly: y };
    });
    // label collision avoidance: walk top->bottom, push a label down if it overlaps one above
    pts.sort((a, b) => a.ly - b.ly);
    pts.forEach((p, i) => { for (let j = 0; j < i; j++) { const q = pts[j];
      if (p.lx < q.lx + q.tw && q.lx < p.lx + p.tw && Math.abs(p.ly - q.ly) < F * 1.05) p.ly = q.ly + F * 1.05; } });
    pts.forEach((p) => {
      const g = add(s, "g", { style: "cursor:default" });
      add(g, "circle", { cx: p.x, cy: p.y, r: p.r + F * 0.45, fill: col[p.c.verdict], opacity: 0.18 });
      add(g, "circle", { cx: p.x, cy: p.y, r: p.r, fill: col[p.c.verdict], stroke: css("--bg"), "stroke-width": 2 });
      if (Math.abs(p.ly - p.y) > 2) add(g, "line", { x1: p.x + p.r, y1: p.y, x2: p.lx - 2, y2: p.ly, stroke: css("--mute"), "stroke-width": 1 });
      add(g, "text", { x: p.lx, y: p.ly + F * 0.3, "font-size": F * 0.78, fill: css("--text"), "font-weight": 600 }, p.text);
      g.addEventListener("mousemove", (ev) => showTip(ev.clientX, ev.clientY, opt.tip(p.c)));
      g.addEventListener("mouseleave", hideTip);
    });
    el.innerHTML = ""; el.appendChild(s);
  }

  window.Charts = { line, ci, hist, korea, hms, esc, fmt, showTip, hideTip };
})();
