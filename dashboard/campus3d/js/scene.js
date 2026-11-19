// 3D campus scene. World frame: X = east (m), Z = -north (m), Y = up (m).
import * as THREE from 'three';
import { OrbitControls } from '../vendor/OrbitControls.js';
import { posAt, servingAt, armOf } from './sources.js';

THREE.ColorManagement.enabled = false;            // hex in = hex out; predictable on projectors
const W = (x, y, h = 0) => new THREE.Vector3(x, h, -y);
const STATUS_COLOR = { confirmed: '#FFD54F', acked: '#00D9FF', attempted: '#00D9FF', failed: '#D72638', modelled: '#9FB3D1', observed: '#DDE6F3' };
const ROUTE_VS = `attribute vec3 color; attribute float along; varying vec3 vC; varying float vA;
  void main(){ vC=color; vA=along; gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0); }`;
const ROUTE_FS = `uniform float uProgress; uniform float uTime; uniform float uFuture; varying vec3 vC; varying float vA;
  void main(){ float past=step(vA,uProgress); vec3 c=vC*mix(uFuture,1.0,past);
    float dash=step(0.55,fract((vA-uTime*9.0)/14.0))*past; c+=vec3(0.22)*dash; gl_FragColor=vec4(c,mix(0.55,0.95,past)); }`;
const BEAM_VS = `varying float vY; void main(){ vY=uv.y; gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0); }`;
const BEAM_FS = `uniform vec3 uColor; uniform float uTime; uniform float uOpacity; uniform float uFlow; varying float vY;
  void main(){ float a=uOpacity*(0.35+0.65*smoothstep(0.0,0.25,vY)*smoothstep(1.0,0.75,vY));
    float d=mix(1.0,0.45+0.55*step(0.5,fract(vY*10.0+uTime*uFlow)),step(0.001,abs(uFlow))); gl_FragColor=vec4(uColor,a*d); }`;
const PILLAR_FS = `uniform vec3 uColor; uniform float uOpacity; varying float vY;
  void main(){ gl_FragColor=vec4(uColor,uOpacity*pow(1.0-vY,1.6)); }`;

function radialTexture(stops) {
  const c = document.createElement('canvas'); c.width = c.height = 64;
  const g = c.getContext('2d'), gr = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  stops.forEach(([o, col]) => gr.addColorStop(o, col)); g.fillStyle = gr; g.fillRect(0, 0, 64, 64);
  const t = new THREE.CanvasTexture(c); return t;
}
function mergeGeoms(list) {
  let n = 0; list.forEach((g) => { n += g.attributes.position.count; });
  const pos = new Float32Array(n * 3), nor = new Float32Array(n * 3), col = list[0].attributes.color ? new Float32Array(n * 3) : null;
  let o = 0;
  for (const g of list) {
    pos.set(g.attributes.position.array, o * 3); nor.set(g.attributes.normal.array, o * 3);
    if (col) col.set(g.attributes.color.array, o * 3);
    o += g.attributes.position.count; g.dispose();
  }
  const m = new THREE.BufferGeometry();
  m.setAttribute('position', new THREE.BufferAttribute(pos, 3)); m.setAttribute('normal', new THREE.BufferAttribute(nor, 3));
  if (col) m.setAttribute('color', new THREE.BufferAttribute(col, 3));
  return m;
}
function ribbon(xs, ys, width, colorAt, h = 0.35) {
  const n = xs.length; if (n < 2) return null;
  const pos = new Float32Array(n * 6), col = new Float32Array(n * 6), along = new Float32Array(n * 2), idx = [];
  let acc = 0; const c = new THREE.Color();
  for (let i = 0; i < n; i++) {
    const a = Math.max(0, i - 1), b = Math.min(n - 1, i + 1);
    let dx = xs[b] - xs[a], dy = ys[b] - ys[a]; const L = Math.hypot(dx, dy) || 1; dx /= L; dy /= L;
    const nx = -dy * width / 2, ny = dx * width / 2;
    if (i) acc += Math.hypot(xs[i] - xs[i - 1], ys[i] - ys[i - 1]);
    pos.set([xs[i] + nx, h, -(ys[i] + ny), xs[i] - nx, h, -(ys[i] - ny)], i * 6);
    c.set(colorAt(i)); col.set([c.r, c.g, c.b, c.r, c.g, c.b], i * 6);
    along[i * 2] = along[i * 2 + 1] = acc;
    if (i < n - 1) { const k = i * 2; idx.push(k, k + 1, k + 2, k + 1, k + 3, k + 2); }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3)); g.setAttribute('color', new THREE.BufferAttribute(col, 3));
  g.setAttribute('along', new THREE.BufferAttribute(along, 1)); g.setIndex(idx);
  return { geom: g, total: acc };
}

export class CampusScene {
  constructor(canvas, labelsEl, { quality = 'auto', onPick = null, onViewChange = null } = {}) {
    this.canvas = canvas; this.labelsEl = labelsEl; this.onPick = onPick; this.onViewChange = onViewChange;
    this.quality = quality; this.lowPower = quality === 'low';
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: quality !== 'low', powerPreference: 'high-performance' });
    this.renderer.outputColorSpace = THREE.LinearSRGBColorSpace;
    this.pixelRatio = quality === 'low' ? 1 : Math.min(window.devicePixelRatio || 1, 1.5);
    this.renderer.setPixelRatio(this.pixelRatio);
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color('#050f22');
    this.scene.fog = new THREE.Fog('#050f22', 900, 2600);
    this.camera = new THREE.PerspectiveCamera(42, 1, 1, 6000);
    this.camera.position.set(-300, 400, 400);
    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.enableDamping = true; this.controls.maxPolarAngle = Math.PI * 0.495; this.controls.minDistance = 25; this.controls.maxDistance = 2600;
    this.controls.addEventListener('start', () => { if (this.view !== 'free') { this.view = 'free'; this.onViewChange && this.onViewChange('free'); } });
    this.scene.add(new THREE.HemisphereLight('#9fc3ff', '#0a1630', 0.95));
    const sun = new THREE.DirectionalLight('#ffe7b8', 0.85); sun.position.set(-300, 500, 200); this.scene.add(sun);
    this.static = new THREE.Group(); this.dynamic = new THREE.Group(); this.scene.add(this.static, this.dynamic);
    this.labels = []; this.view = 'hero'; this.camGoal = null; this.clock = new THREE.Clock(); this.time = 0;
    this.fx = []; this.frameMs = []; this.lastQualityCheck = 0; this.size = [0, 0];
    this.haloTex = radialTexture([[0, 'rgba(255,255,255,1)'], [0.25, 'rgba(255,255,255,0.55)'], [1, 'rgba(255,255,255,0)']]);
    this.ray = new THREE.Raycaster(); this.pickables = [];
    canvas.addEventListener('click', (e) => this._click(e));
  }

  // ---------------------------------------------------------------- labels
  addLabel(cls, html, v3, opts = {}) {
    const el = document.createElement('div'); el.className = `wl ${cls}`; el.innerHTML = html;
    this.labelsEl.appendChild(el);
    const L = { el, v: v3.clone(), maxDist: opts.maxDist ?? Infinity, group: opts.group || 'static', visible: true, color: opts.color };
    if (opts.color) el.style.color = opts.color;
    this.labels.push(L); return L;
  }
  clearLabels(group) { this.labels = this.labels.filter((L) => { if (L.group === group) { L.el.remove(); return false; } return true; }); }

  // ---------------------------------------------------------------- static campus
  setCampus(campus, route, lang = 'en') {
    this.campus = campus; this.route = route; this.lang = lang;
    const g = this.static; g.clear(); this.clearLabels('static');
    const ground = new THREE.Mesh(new THREE.PlaneGeometry(8000, 8000), new THREE.MeshBasicMaterial({ color: '#06132b' }));
    ground.rotation.x = -Math.PI / 2; ground.position.y = -0.2; g.add(ground);
    const grid = new THREE.GridHelper(4000, 80, '#0f2a52', '#0b2246'); grid.position.y = -0.1; g.add(grid);
    if (campus.boundary) {
      const sh = new THREE.Shape(campus.boundary.poly.map(([x, y]) => new THREE.Vector2(x, y)));
      const m = new THREE.Mesh(new THREE.ShapeGeometry(sh), new THREE.MeshBasicMaterial({ color: '#0b2148' }));
      m.rotation.x = -Math.PI / 2; m.position.y = 0; g.add(m);
      const pts = campus.boundary.poly.map(([x, y]) => W(x, y, 0.4));
      g.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineBasicMaterial({ color: '#FFD54F', transparent: true, opacity: 0.45 })));
    }
    const AREA = { pitch: '#0d3b44', track: '#183a55', park: '#0e3527', wood: '#0d3323', water: '#0c3d6e', farmland: '#0f2d22', residential: '#0c1f40', retail: '#0c1f40' };
    for (const a of campus.areas) {
      const col = AREA[a.kind]; if (!col) continue;
      const m = new THREE.Mesh(new THREE.ShapeGeometry(new THREE.Shape(a.poly.map(([x, y]) => new THREE.Vector2(x, y)))), new THREE.MeshBasicMaterial({ color: col }));
      m.rotation.x = -Math.PI / 2; m.position.y = a.kind === 'water' ? 0.12 : 0.08; g.add(m);
    }
    const seg = { minor: [], major: [] };
    for (const p of campus.paths) {
      const arr = ['service', 'tertiary', 'residential', 'secondary', 'primary'].includes(p.kind) ? seg.major : seg.minor;
      for (let i = 1; i < p.pts.length; i++) arr.push(W(p.pts[i - 1][0], p.pts[i - 1][1], 0.18), W(p.pts[i][0], p.pts[i][1], 0.18));
    }
    g.add(new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(seg.minor), new THREE.LineBasicMaterial({ color: '#2b5487', transparent: true, opacity: 0.8 })));
    g.add(new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(seg.major), new THREE.LineBasicMaterial({ color: '#4a78b5' })));
    // buildings: one merged mesh, vertex-coloured walls/roofs; venue tinted gold
    const geoms = [], edgesN = [], edgesV = [];
    const wall = new THREE.Color('#1d3d6e'), wallTop = new THREE.Color('#2f5b97'), roof = new THREE.Color('#3a6cab');
    const vWall = new THREE.Color('#2c2f3a'), vTop = new THREE.Color('#5c5232'), vRoof = new THREE.Color('#6e6236');
    for (const b of campus.buildings) {
      const pts = b.poly.slice(0, b.poly[0][0] === b.poly.at(-1)[0] && b.poly[0][1] === b.poly.at(-1)[1] ? -1 : undefined);
      if (pts.length < 3) continue;
      const geo = new THREE.ExtrudeGeometry(new THREE.Shape(pts.map(([x, y]) => new THREE.Vector2(x, y))), { depth: b.height_m, bevelEnabled: false });
      geo.rotateX(-Math.PI / 2);
      const ng = geo.index ? geo.toNonIndexed() : geo; if (ng !== geo) geo.dispose();
      ng.computeVertexNormals();
      const venue = (b.name_ko || '').startsWith('산학협력관');
      const P = ng.attributes.position, N = ng.attributes.normal, C = new Float32Array(P.count * 3), c = new THREE.Color();
      for (let i = 0; i < P.count; i++) {
        if (N.getY(i) > 0.5) c.copy(venue ? vRoof : roof);
        else c.copy(venue ? vWall : wall).lerp(venue ? vTop : wallTop, Math.min(1, P.getY(i) / Math.max(4, b.height_m)));
        C.set([c.r, c.g, c.b], i * 3);
      }
      ng.setAttribute('color', new THREE.BufferAttribute(C, 3)); geoms.push(ng);
      const e = new THREE.EdgesGeometry(ng, 30), arr = e.attributes.position.array;
      (venue ? edgesV : edgesN).push(arr); e.dispose();
      if (b.landmark && b.name_ko) {
        const cx = pts.reduce((s, p) => s + p[0], 0) / pts.length, cy = pts.reduce((s, p) => s + p[1], 0) / pts.length;
        const L = this.addLabel(venue ? 'bld venue' : 'bld', '', W(cx, cy, b.height_m + 3), { maxDist: venue ? Infinity : 1500 });
        L.ko = b.name_ko; L.en = b.name_en; L.venue = venue; this._bldLabel(L);
      }
    }
    if (geoms.length) {
      this.buildings = new THREE.Mesh(mergeGeoms(geoms), new THREE.MeshLambertMaterial({ vertexColors: true }));
      g.add(this.buildings);
    }
    const lineSet = (arrs, color, opacity) => {
      let n = 0; arrs.forEach((a) => { n += a.length; }); const all = new Float32Array(n); let o = 0; arrs.forEach((a) => { all.set(a, o); o += a.length; });
      const geo = new THREE.BufferGeometry(); geo.setAttribute('position', new THREE.BufferAttribute(all, 3));
      return new THREE.LineSegments(geo, new THREE.LineBasicMaterial({ color, transparent: true, opacity }));
    };
    if (edgesN.length) g.add(lineSet(edgesN, '#00D9FF', 0.32));
    if (edgesV.length) g.add(lineSet(edgesV, '#FFD54F', 0.9));
    // OpenCelliD catalogue sites (crowd-sourced, not identity-matched): small, dim
    const cone = new THREE.ConeGeometry(2.2, 9, 6); cone.translate(0, 4.5, 0);
    this.ocid = new THREE.InstancedMesh(cone, new THREE.MeshBasicMaterial({ color: '#5c6f8c', transparent: true, opacity: 0.55 }), campus.ocid_sites.length);
    const m4 = new THREE.Matrix4();
    campus.ocid_sites.forEach((s, i) => { m4.makeTranslation(s.x, 0, -s.y); this.ocid.setMatrixAt(i, m4); });
    g.add(this.ocid);
    // full walk loop as faint context
    for (const [sid, col] of [['t4-reverse', '#33507a']]) {
      const p = route.sessions[sid].points, r = ribbon(p.x, p.y, 1.6, () => col, 0.25);
      if (r) g.add(new THREE.Mesh(r.geom, new THREE.MeshBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.75, depthWrite: false })));
    }
    this.bounds = this._bounds(campus, route);
  }
  _bldLabel(L) {
    const ko = this.lang === 'ko';
    const main = ko ? L.ko : (L.en || L.ko), sub = ko ? (L.en || '') : L.ko;
    const venue = L.venue ? `<small>${ko ? '결선 장소 · Finals venue' : 'Finals venue · 결선 장소'}</small>` : '';
    L.el.innerHTML = `${main}${sub && main !== sub ? `<small>${sub}</small>` : ''}${venue}`;
  }
  setLang(lang) { this.lang = lang; this.labels.forEach((L) => { if (L.ko) this._bldLabel(L); }); if (this.sc) this._cellLabels(); }
  _bounds(campus, route) {
    const p = route.sessions['t4-reverse'].points; let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
    p.x.forEach((x, i) => { x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, p.y[i]); y1 = Math.max(y1, p.y[i]); });
    return { x0: x0 - 120, x1: x1 + 120, y0: y0 - 80, y1: y1 + 60 };
  }

  // ---------------------------------------------------------------- scenario
  setScenario(sc) {
    this.sc = sc; const g = this.dynamic; g.clear(); this.clearLabels('dyn'); this.pickables = []; this.fx = [];
    this.routeMesh = null; this.refreshRoute();
    // cell anchors: light pillars, never a tower mesh (mast positions are unknown)
    this.beacons = sc.cells.map((c, i) => {
      const grp = new THREE.Group(); grp.position.copy(W(c.anchor.x, c.anchor.y));
      const col = new THREE.Color(c.color);
      const pillar = new THREE.Mesh(new THREE.CylinderGeometry(1.1, 1.1, 34, 12, 1, true).translate(0, 17, 0),
        new THREE.ShaderMaterial({ vertexShader: BEAM_VS, fragmentShader: PILLAR_FS, transparent: true, depthWrite: false, side: THREE.DoubleSide,
          blending: THREE.AdditiveBlending, uniforms: { uColor: { value: col }, uOpacity: { value: 0.55 } } }));
      const ring = new THREE.Mesh(new THREE.RingGeometry(5, 6.2, 40), new THREE.MeshBasicMaterial({ color: col, transparent: true, opacity: 0.55, side: THREE.DoubleSide, depthWrite: false }));
      ring.rotation.x = -Math.PI / 2; ring.position.y = 0.6;
      const top = new THREE.Mesh(new THREE.OctahedronGeometry(2.4), new THREE.MeshBasicMaterial({ color: col }));
      top.position.y = 30; top.userData = { pick: { cell_id: c.id } };
      grp.add(pillar, ring, top); g.add(grp); this.pickables.push(top);
      return { grp, pillar, ring, top, color: col, cell: c };
    });
    this._cellLabels();
    // device
    const dev = new THREE.Group();
    const core = new THREE.Mesh(new THREE.SphereGeometry(1.5, 20, 14), new THREE.MeshBasicMaterial({ color: '#ffffff' })); core.position.y = 2.4;
    const halo = new THREE.Sprite(new THREE.SpriteMaterial({ map: this.haloTex, color: '#FFD54F', transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }));
    halo.scale.set(16, 16, 1); halo.position.y = 2.4;
    const svc = new THREE.Mesh(new THREE.RingGeometry(3.6, 4.6, 48), new THREE.MeshBasicMaterial({ color: '#2ECC71', transparent: true, opacity: 0.9, side: THREE.DoubleSide, depthWrite: false }));
    svc.rotation.x = -Math.PI / 2; svc.position.y = 0.7;
    const stem = new THREE.Mesh(new THREE.CylinderGeometry(0.18, 0.18, 2.4, 6).translate(0, 1.2, 0), new THREE.MeshBasicMaterial({ color: '#ffffff', transparent: true, opacity: 0.7 }));
    const arrow = new THREE.Mesh(new THREE.ConeGeometry(1.4, 3.4, 3).rotateX(Math.PI / 2).translate(0, 0.8, -6.2), new THREE.MeshBasicMaterial({ color: '#FFD54F', transparent: true, opacity: 0.85 }));
    dev.add(core, halo, svc, stem, arrow); g.add(dev);
    this.device = { grp: dev, core, halo, svc, arrow };
    this.devLabel = this.addLabel('dev', '', new THREE.Vector3(), { group: 'dyn' });
    // links: serving (flowing), target (gold, dashed), baseline (dim)
    const mkBeam = (r) => {
      const m = new THREE.Mesh(new THREE.CylinderGeometry(r, r, 1, 8, 1, true).translate(0, 0.5, 0),
        new THREE.ShaderMaterial({ vertexShader: BEAM_VS, fragmentShader: BEAM_FS, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
          uniforms: { uColor: { value: new THREE.Color('#ffffff') }, uTime: { value: 0 }, uOpacity: { value: 0.9 }, uFlow: { value: 0 } } }));
      m.visible = false; g.add(m); return m;
    };
    this.links = { serving: mkBeam(0.55), target: mkBeam(0.75), baseline: mkBeam(0.35) };
    // event markers (revealed as scenario time passes them)
    this.markers = [];
    const pinGeo = new THREE.CylinderGeometry(0.25, 0.25, 12, 6).translate(0, 6, 0), gemGeo = new THREE.OctahedronGeometry(2.0);
    const smallGem = new THREE.OctahedronGeometry(1.1);
    for (const arm of sc.arms) {
      for (const ev of arm.events) {
        const p = posAt(sc, ev.t), grp = new THREE.Group(); grp.position.copy(W(p.x, p.y));
        const mat = new THREE.MeshBasicMaterial({ color: STATUS_COLOR[ev.status] || '#ffffff', transparent: true, opacity: 0.95 });
        const small = ev.status === 'observed' || arm.key === 'baseline';
        const pin = new THREE.Mesh(pinGeo, mat); const gem = new THREE.Mesh(small ? smallGem : gemGeo, mat);
        pin.scale.y = small ? 0.55 : 1; gem.position.y = small ? 7 : 13.2;
        if (arm.key === 'baseline') { grp.position.x += 2.5; }
        gem.userData = { pick: { event_id: ev.id } };
        grp.add(pin, gem); grp.visible = false; g.add(grp); this.pickables.push(gem);
        let label = null;
        if (!small) label = this.addLabel(`ho ${ev.status === 'confirmed' ? '' : ev.status === 'failed' ? 'failed' : ev.status === 'modelled' ? 'modelled' : 'pending'}`,
          '', W(p.x, p.y, 17), { group: 'dyn', maxDist: 1400 });
        this.markers.push({ ev, arm: arm.key, grp, gem, mat, label, shown: false, confirmedShown: false, p });
      }
    }
    this._updMarkerLabels();
    this.prevT = null;
    this.setView(this.view === 'free' ? 'hero' : this.view, true);
  }
  /** (Re)build the active route ribbon and camera framing; LIVE calls this as frames arrive. */
  refreshRoute() {
    const sc = this.sc; if (!sc) return;
    const prim = armOf(sc, sc.primary) || sc.arms[0], P = sc.pos;
    if (this.routeMesh) { this.dynamic.remove(this.routeMesh); this.routeMesh.geometry.dispose(); this.routeMesh = null; }
    this.routeAlong = null;
    if (P.t.length > 1) {
      const xs = [], ys = [], ts = [];
      for (let i = 0; i < P.t.length; i++) if (P.t[i] >= sc.highlight[0] - 1 && P.t[i] <= sc.highlight[1] + 1) { xs.push(P.x[i]); ys.push(P.y[i]); ts.push(P.t[i]); }
      const r = ribbon(xs, ys, 3.2, (i) => { const s = servingAt(prim, ts[i]); return s >= 0 ? sc.cells[s].color : '#7d8ba0'; }, 0.45);
      if (r) {
        this.routeMat = this.routeMat || new THREE.ShaderMaterial({ vertexShader: ROUTE_VS, fragmentShader: ROUTE_FS, transparent: true, depthWrite: false,
          uniforms: { uProgress: { value: 0 }, uTime: { value: 0 }, uFuture: { value: 0.38 } } });
        this.routeMesh = new THREE.Mesh(r.geom, this.routeMat); this.dynamic.add(this.routeMesh);
        const al = r.geom.attributes.along.array; this.routeAlong = { t: ts, a: Array.from({ length: ts.length }, (_, i) => al[i * 2]) };
      }
    }
    this.scBox = P.t.length ? this._scBounds() : null;
  }
  _cellLabels() {
    this.clearLabels('cell');
    if (!this.beacons) return;
    for (const b of this.beacons) {
      const c = b.cell;
      b.label = this.addLabel('cell', `${c.letter}${c.pci != null ? `<span class="k">PCI ${c.pci}</span>` : ''}`, b.grp.position.clone().setY(36), { group: 'cell', color: c.color });
      b.label.el.title = `${c.id} — ${this.lang === 'ko' ? '최강 측정 지점 · 기지국 위치 미상' : 'strongest measured point · mast position unknown'}`;
    }
  }
  _updMarkerLabels() {
    const ko = this.lang === 'ko';
    for (const m of this.markers || []) {
      if (!m.label) continue;
      const e = m.ev, f = this.sc.cells[e.from], to = this.sc.cells[e.to];
      const st = e.status === 'failed' ? ' ✕' : '';   // ✓ is added per frame only once CU completion is reached
      m.pend = undefined;
      m.label.el.textContent = `${m.arm === 'baseline' ? (ko ? '기준' : 'Base') : 'HO'} ${e.n} · ${f ? f.letter : '?'}→${to ? to.letter : '?'}${st}`;
    }
  }
  _scBounds() {
    const sc = this.sc, P = sc.pos; let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
    for (let i = 0; i < P.t.length; i++) if (P.t[i] >= sc.highlight[0] && P.t[i] <= sc.highlight[1]) {
      x0 = Math.min(x0, P.x[i]); x1 = Math.max(x1, P.x[i]); y0 = Math.min(y0, P.y[i]); y1 = Math.max(y1, P.y[i]);
    }
    if (!isFinite(x0)) { x0 = -50; x1 = 50; y0 = -50; y1 = 50; }
    return { x0, x1, y0, y1, cx: (x0 + x1) / 2, cy: (y0 + y1) / 2, r: Math.max(60, Math.hypot(x1 - x0, y1 - y0) / 2) };
  }

  // ---------------------------------------------------------------- camera
  setView(v, snap = false) {
    this.view = v; this.snap = snap;
    this.onViewChange && this.onViewChange(v);
  }
  _goal(dev) {
    const b = this.scBox || { cx: dev.x, cy: dev.y, r: 60 }, B = this.bounds;
    const tgt = new THREE.Vector3(), pos = new THREE.Vector3();
    if (this.view === 'follow') {
      tgt.copy(W(dev.x, dev.y, 4));
      const hd = dev.heading; pos.set(dev.x - Math.sin(hd) * 75, 46, -(dev.y - Math.cos(hd) * 75));
    } else if (this.view === 'overview' || this.view === 'top') {
      const cx = (B.x0 + B.x1) / 2, cy = (B.y0 + B.y1) / 2, r = Math.max(B.x1 - B.x0, B.y1 - B.y0) * 0.5;
      tgt.copy(W(cx, cy, 0));
      const d = r / Math.tan(THREE.MathUtils.degToRad(this.camera.fov / 2)) * (this.camera.aspect < 1.3 ? 1.25 : 0.95);
      if (this.view === 'top') pos.set(cx, d * 1.05, -cy + 0.01);
      else pos.set(cx - d * 0.38, d * 0.72, -(cy - d * 0.62));
    } else { // hero: device-centred, framed on the scenario's footprint, from the south-west
      const span = Math.min(b.r, 420), cx = dev.x * 0.6 + b.cx * 0.4, cy = dev.y * 0.6 + b.cy * 0.4;
      // From the north-west, looking south: the device stays in front of the buildings
      // and the rest of the campus (and the walk) recedes behind it.
      tgt.copy(W(cx, cy - 30, 4));
      const d = Math.max(330, span * 2.4);
      pos.set(cx - d * 0.28, d * 0.74, -(cy - 30 + d * 0.66));
    }
    return { tgt, pos };
  }
  _click(e) {
    if (!this.pickables.length) return;
    const r = this.canvas.getBoundingClientRect();
    this.ray.setFromCamera(new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1), this.camera);
    this.ray.params.Points = { threshold: 3 };
    const hit = this.ray.intersectObjects(this.pickables.filter((o) => o.parent?.visible !== false), false)[0];
    if (hit && this.onPick) this.onPick(hit.object.userData.pick);
  }
  focusEvent(id) {
    const m = (this.markers || []).find((x) => x.ev.id === id); if (!m) return;
    m.flash = 1.5;
  }

  // ---------------------------------------------------------------- per-frame
  resize() {
    const w = this.canvas.clientWidth, h = this.canvas.clientHeight;
    if (w === this.size[0] && h === this.size[1]) return;
    this.size = [w, h]; this.renderer.setSize(w, h, false); this.camera.aspect = w / Math.max(1, h); this.camera.updateProjectionMatrix();
  }
  pulse(p, color, maxR = 30, life = 1.4) {
    const m = new THREE.Mesh(new THREE.RingGeometry(0.85, 1, 48), new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 1, side: THREE.DoubleSide, depthWrite: false, blending: THREE.AdditiveBlending }));
    m.rotation.x = -Math.PI / 2; m.position.copy(W(p.x, p.y, 1)); this.dynamic.add(m);
    this.fx.push({ m, age: 0, life, maxR });
  }
  /** t: scenario seconds. Returns derived state for the HUD. */
  update(t, state = {}) {
    const dt = Math.min(0.1, this.clock.getDelta()); this.time += dt; this.resize();
    const sc = this.sc; if (!sc) { this.renderer.render(this.scene, this.camera); return; }
    const dev = posAt(sc, t), D = this.device, hasPos = sc.pos.t.length > 0;
    D.grp.visible = hasPos; this.devLabel.hidden = !hasPos;     // no frames => no device, never a placeholder position
    const camDist = this.camera.position.distanceTo(this.controls.target);
    const k = THREE.MathUtils.clamp(camDist / 160, 1, 5.5);
    D.grp.position.copy(W(dev.x, dev.y)); D.grp.scale.setScalar(k); D.arrow.rotation.y = -dev.heading;
    const svcState = state.service || 'ok';
    D.svc.material.color.set(svcState === 'interrupted' ? '#D72638' : svcState === 'unknown' ? '#7d8ba0' : '#2ECC71');
    D.svc.material.opacity = 0.65 + 0.3 * Math.sin(this.time * 4);
    D.halo.material.color.set(state.stale ? '#7d8ba0' : '#FFD54F');
    D.halo.material.opacity = state.stale ? 0.35 : 0.85;
    this.devLabel.v.copy(W(dev.x, dev.y, 9 * k));
    this.devLabel.el.textContent = state.devLabel || 'UE';
    // beacons scale with distance so they stay legible in the campus view
    const kb = THREE.MathUtils.clamp(camDist / 220, 1, 4);
    const prim = armOf(sc, sc.primary) || sc.arms[0];
    const s = state.serving ?? servingAt(prim, t), tg = state.target ?? -1;
    for (const b of this.beacons) {
      const isS = b.cell === sc.cells[s], isT = b.cell === sc.cells[tg];
      b.grp.scale.set(kb, 1 + (kb - 1) * 0.6, kb);
      b.pillar.material.uniforms.uOpacity.value = isS ? 0.95 : isT ? 0.8 : 0.32;
      b.ring.material.opacity = isS ? 0.85 + 0.15 * Math.sin(this.time * 5) : 0.35;
      b.top.rotation.y += dt * (isS ? 1.6 : 0.4);
      if (b.label) {
        b.label.v.copy(b.grp.position).setY(34 * (1 + (kb - 1) * 0.6) + 4); b.label.el.classList.toggle('serving', isS);
        b.label.hidden = camDist > 520 && !isS && !isT;          // declutter the campus view
      }
    }
    const top = (i) => this.beacons[i].grp.position.clone().setY(30 * (1 + (kb - 1) * 0.6));
    const from = hasPos ? W(dev.x, dev.y, 2.4 * k) : null;
    this._beam(this.links.serving, s >= 0 ? from : null, s >= 0 ? top(s) : null, s >= 0 ? sc.cells[s].color : '#fff', 0.85, -1.2);
    this._beam(this.links.target, tg >= 0 && tg !== s ? from : null, tg >= 0 ? top(tg) : null, '#FFD54F', 0.95, 2.5);
    const base = armOf(sc, 'baseline'), bs = base ? servingAt(base, t) : -1;
    this._beam(this.links.baseline, bs >= 0 ? from : null, bs >= 0 ? top(bs) : null, '#9FB3D1', 0.45, 0);
    // route progress
    if (this.routeMat && this.routeAlong) {
      const R = this.routeAlong; let i = 0, lo = 0, hi = R.t.length - 1;
      while (lo < hi) { const m = (lo + hi + 1) >> 1; if (R.t[m] <= t) lo = m; else hi = m - 1; } i = lo;
      this.routeMat.uniforms.uProgress.value = t < R.t[0] ? -1 : R.a[i]; this.routeMat.uniforms.uTime.value = this.time;
    }
    // events: reveal markers, fire FX on forward crossings
    const forward = this.prevT != null && t >= this.prevT && t - this.prevT < 3;
    const fired = [];
    for (const m of this.markers) {
      const e = m.ev, ph = e.phases || {};
      const shown = t >= e.t;
      m.grp.visible = shown; if (m.label) m.label.hidden = !shown;
      m.grp.scale.setScalar(THREE.MathUtils.clamp(camDist / 200, 1, 4.5));
      const confirmedNow = ph.cu_confirmed != null && t >= ph.cu_confirmed;
      const color = e.status === 'confirmed' && !confirmedNow ? (ph.ack != null && t >= ph.ack ? STATUS_COLOR.acked : STATUS_COLOR.attempted) : STATUS_COLOR[e.status];
      m.mat.color.set(color);
      if (m.label) {
        const pend = e.status === 'acked' || e.status === 'attempted' || (e.status === 'confirmed' && !confirmedNow);
        if (m.pend !== pend) { m.pend = pend; m.label.el.classList.toggle('pending', pend); m.label.el.textContent = m.label.el.textContent.replace(/ ✓$/, '') + (pend ? '' : e.status === 'confirmed' ? ' ✓' : ''); }
      }
      if (m.flash) { m.flash -= dt; m.gem.scale.setScalar(1 + Math.max(0, m.flash) * 0.8); }
      m.gem.rotation.y += dt * 0.8;
      if (forward && m.arm === sc.primary) {
        if (this.prevT < e.t && t >= e.t) { this.pulse(m.p, e.status === 'observed' ? '#DDE6F3' : '#00D9FF', 26); fired.push({ kind: 'decision', ev: e }); }
        if (ph.ack != null && this.prevT < ph.ack && t >= ph.ack) fired.push({ kind: 'ack', ev: e });
        if (e.status === 'confirmed' && ph.cu_confirmed != null && this.prevT < ph.cu_confirmed && t >= ph.cu_confirmed) {
          const p = posAt(sc, t); this.pulse(p, '#FFD54F', 40, 1.8); m.flash = 1.2; fired.push({ kind: 'cu_confirmed', ev: e });
        }
      }
    }
    this.prevT = t;
    for (let i = this.fx.length - 1; i >= 0; i--) {
      const f = this.fx[i]; f.age += dt; const u = f.age / f.life;
      if (u >= 1) { this.dynamic.remove(f.m); f.m.geometry.dispose(); f.m.material.dispose(); this.fx.splice(i, 1); continue; }
      f.m.scale.setScalar(1 + u * f.maxR * k * 0.5); f.m.material.opacity = 1 - u;
    }
    // camera
    if (this.view !== 'free') {
      const goal = this._goal(dev), a = this.snap ? 1 : 1 - Math.exp(-dt * (this.view === 'follow' ? 3.2 : 1.6));
      this.camera.position.lerp(goal.pos, a); this.controls.target.lerp(goal.tgt, a); this.camera.lookAt(this.controls.target);
      this.snap = false;
    } else this.controls.update();
    this.ocid.visible = this.view === 'overview' || this.view === 'top' || camDist > 700;
    this.renderer.render(this.scene, this.camera);
    this._labels(camDist);
    this._quality(dt);
    return { dev, serving: s, fired, camDist };
  }
  _beam(mesh, a, b, color, opacity, flow) {
    if (!a || !b) { mesh.visible = false; return; }
    const d = b.clone().sub(a), L = d.length(); if (L < 0.5) { mesh.visible = false; return; }
    mesh.visible = true; mesh.position.copy(a); mesh.scale.set(1, L, 1);
    mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), d.normalize());
    const u = mesh.material.uniforms; u.uColor.value.set(color); u.uOpacity.value = opacity; u.uFlow.value = flow; u.uTime.value = this.time;
    const k = THREE.MathUtils.clamp(this.camera.position.distanceTo(this.controls.target) / 160, 1, 5); mesh.scale.x = mesh.scale.z = k;
  }
  _labels(camDist) {
    const w = this.size[0], h = this.size[1], v = new THREE.Vector3();
    for (const L of this.labels) {
      if (L.hidden || camDist > L.maxDist) { if (L.visible) { L.el.classList.add('hidden'); L.visible = false; } continue; }
      v.copy(L.v).project(this.camera);
      const on = v.z < 1 && v.x > -1.1 && v.x < 1.1 && v.y > -1.1 && v.y < 1.1;
      if (!on) { if (L.visible) { L.el.classList.add('hidden'); L.visible = false; } continue; }
      if (!L.visible) { L.el.classList.remove('hidden'); L.visible = true; }
      L.el.style.transform = `translate(-50%,-100%) translate(${((v.x + 1) / 2 * w).toFixed(1)}px,${((1 - v.y) / 2 * h).toFixed(1)}px)`;
    }
  }
  _quality(dt) {
    if (this.quality !== 'auto') return;
    this.frameMs.push(dt * 1000);
    if (this.frameMs.length < 90) return;
    const avg = this.frameMs.reduce((a, b) => a + b, 0) / this.frameMs.length; this.frameMs = [];
    if (avg > 26 && this.pixelRatio > 0.75) { this.pixelRatio = Math.max(0.75, this.pixelRatio - 0.25); this.renderer.setPixelRatio(this.pixelRatio); this.size = [0, 0]; }
    else if (avg < 14 && this.pixelRatio < Math.min(window.devicePixelRatio || 1, 1.5)) { this.pixelRatio = Math.min(1.5, this.pixelRatio + 0.25); this.renderer.setPixelRatio(this.pixelRatio); this.size = [0, 0]; }
    this.fps = Math.round(1000 / avg);
  }
  setQuality(q) {
    this.quality = q;
    if (q === 'low') { this.pixelRatio = 1; } else if (q === 'high') { this.pixelRatio = Math.min(window.devicePixelRatio || 1, 1.5); }
    this.renderer.setPixelRatio(this.pixelRatio); this.size = [0, 0];
  }
}
