// HORUS finals dashboard — app shell: polling, panels, i18n, presenter mode,
// LIVE/REPLAY switch, and the gate promote/reject animation.
(function () {
  const { line, ci, hist, korea, hms, esc, fmt } = window.Charts;
  const PANELS = ["overview", "actuation", "pipeline", "results", "campus"];
  const NAVKEY = { overview: "nav_overview", actuation: "nav_actuation", pipeline: "nav_pipeline", results: "nav_results", campus: "nav_campus" };
  const UE_COLORS = ["#22D3EE", "#D4AF37", "#A78BFA", "#3B82F6"];
  const ARM_COLORS = { policy: "#22D3EE", a3_tuned: "#D4AF37", a3_stock: "#8796AE" };
  const ueColor = {};
  const colorOf = (ue) => (ueColor[ue] ??= UE_COLORS[Object.keys(ueColor).length % UE_COLORS.length]);

  // ------------------------------------------------------------- state --
  const ui = Object.assign({ p: "overview", lang: "ko", mode: "live", pres: "0" },
    Object.fromEntries(new URLSearchParams(location.hash.slice(1))));
  let S = null, lastOk = 0, seenFeed = new Set(), seenGate = null, lastLoop = null, restartReplay = false;
  const saveHash = () => history.replaceState(null, "", "#" + new URLSearchParams(ui).toString());

  const t = (k, vars) => {
    let s = (I18N[ui.lang] && I18N[ui.lang][k]) ?? I18N.en[k] ?? k;
    if (vars) for (const v in vars) s = s.replaceAll(`{${v}}`, vars[v] ?? "–");
    return s;
  };
  const L = (obj, base) => (ui.lang === "ko" && obj[base + "_ko"]) || obj[base];   // data-provided bilingual labels
  const $ = (id) => document.getElementById(id);

  // ------------------------------------------------------------ chrome --
  function applyStatic() {
    document.documentElement.lang = ui.lang;
    document.querySelectorAll("[data-i18n]").forEach((e) => (e.textContent = t(e.dataset.i18n)));
    $("nav").innerHTML = PANELS.map((p, i) => `<a data-p="${p}" class="${ui.p === p ? "on" : ""}"><span class="k">${i + 1}</span>${t(NAVKEY[p])}</a>`).join("");
    $("dots").innerHTML = PANELS.map((p) => `<i class="${ui.p === p ? "on" : ""}"></i>`).join("");
    document.querySelectorAll(".page").forEach((e) => e.classList.toggle("on", e.id === "pg-" + ui.p));
    $("ptitle").textContent = t(NAVKEY[ui.p]);
    document.documentElement.classList.toggle("presenter", ui.pres === "1");
    $("langbtn").textContent = ui.lang === "ko" ? "EN" : "한국어";
    saveHash();
  }
  function go(p) { ui.p = p; applyStatic(); if (S) renderPage(); }
  $("nav").addEventListener("click", (e) => { const a = e.target.closest("a[data-p]"); if (a) go(a.dataset.p); });
  $("langbtn").onclick = () => { ui.lang = ui.lang === "ko" ? "en" : "ko"; applyStatic(); if (S) render(); };
  $("presbtn").onclick = () => { ui.pres = ui.pres === "1" ? "0" : "1"; applyStatic(); if (S) render(); };
  function toggleMode() { ui.mode = ui.mode === "live" ? "replay" : "live"; seenGate = null; seenFeed = new Set(); restartReplay = ui.mode === "replay"; saveHash(); poll(); }

  document.addEventListener("keydown", (e) => {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    const i = PANELS.indexOf(ui.p);
    if (/^[1-5]$/.test(e.key)) go(PANELS[+e.key - 1]);
    else if (["ArrowRight", "PageDown", " "].includes(e.key)) { e.preventDefault(); go(PANELS[(i + 1) % PANELS.length]); }
    else if (["ArrowLeft", "PageUp"].includes(e.key)) { e.preventDefault(); go(PANELS[(i + PANELS.length - 1) % PANELS.length]); }
    else if (e.key === "l" || e.key === "L") $("langbtn").click();
    else if (e.key === "p" || e.key === "P") $("presbtn").click();
    else if (e.key === "r" || e.key === "R") toggleMode();
    else if (e.key === "a" || e.key === "A") replayGateAnimations();
    else if (e.key === "f" || e.key === "F") { document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen?.(); }
  });
  addEventListener("resize", () => S && renderPage());

  // -------------------------------------------------------------- poll --
  let polling = false;
  async function poll() {
    if (polling) return;
    polling = true;
    const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 8000);
    try {
      const r = await fetch(`/api/state?src=${ui.mode}${restartReplay ? "&restart=1" : ""}`, { cache: "no-store", signal: controller.signal });
      restartReplay = false;
      const st = await r.json();
      if (st.error && !st.health) { showErr(st.error === "no replay bundle" ? t("replay_missing") : st.error); return; }
      S = st; lastOk = Date.now(); $("errbar").hidden = true;
      render();
    } catch (e) { showErr(t("server_down")); }
    finally { clearTimeout(timeout); polling = false; }
  }
  function showErr(msg) {
    $("errbar").hidden = false; $("errbar").textContent = msg;
    if (S && ui.mode === "live") {
      S.health.overall = "warn";
      Object.keys(S.health.checks).forEach((k) => S.health.checks[k] = "unknown");
      if (S.runtime) {
        S.runtime.ai_active = false;
        S.runtime.effective = { ...S.runtime.effective, controller: null, stale: true };
        if (S.runtime.eligibility) S.runtime.eligibility.stale = true;
      }
      render();
    }
  }
  setInterval(poll, 1000);

  // ------------------------------------------------------------ render --
  function render() {
    header();
    detectGateEvents();
    renderPage();
  }
  let memo = "";
  function renderPage(force) {
    if (ui.p === "results" || ui.p === "campus") {   // static evidence: re-render only on change
      const k = ui.p + ui.lang + ui.pres + innerWidth + JSON.stringify(ui.p === "results" ? S.results : S.campus);
      if (k === memo && !force) return;
      memo = k;
    } else memo = "";
    ({ overview, actuation, pipeline, results, campus })[ui.p]();
  }

  function header() {
    const mb = $("modebadge");
    mb.className = "mode " + S.mode;
    mb.textContent = S.mode === "replay" ? (ui.lang === "ko" ? `${t("replay")} · REPLAY` : "REPLAY") : (ui.lang === "ko" ? `${t("live")} · LIVE` : "LIVE");
    const rb = $("replaybar");
    rb.hidden = S.mode !== "replay";
    if (S.mode === "replay") rb.textContent = "▶ " + t("replay_banner", { rec: S.meta.recorded_at ? kstDate(Date.parse(S.meta.recorded_at) / 1000) : "–", loop: (S.meta.loop || 0) + 1 });
    const sample = (S.meta && S.meta.sample) || (S.results && S.results.sample) || (S.campus && S.campus.sample);
    $("samplebar").hidden = !sample; $("samplebar").textContent = "◆ " + t("sample");
    const h = S.health, ck = h.checks;
    const chip = (st, label, val) => `<span class="hchip ${st}"><i>${st === "ok" ? "●" : st === "bad" ? "✕" : "○"}</i>${label} <b>${val}</b></span>`;
    const ages = Object.values(h.ages).filter((a) => a !== null);
    const age = ages.length ? Math.max(...ages) : null;
    $("health").innerHTML =
      chip(ck.stack, t("h_stack"), ck.stack === "ok" ? t("ok") : ck.stack === "bad" ? (h.containers_down.join(",") || t("bad")) : t("unknown")) +
      chip(ck.e2, t("h_e2"), h.e2_nodes ?? t("unknown")) +
      chip(ck.data, t("h_data"), age === null ? t("unknown") : `${fmt(age, 0)}s`) +
      chip(S.runtime && S.runtime.ai_active || S.pipeline.active ? "ok" : "unknown", t("h_policy"), S.runtime && S.runtime.ai_active ? S.runtime.eligibility.candidate_version : S.pipeline.active || "–");
    $("clock").textContent = `${hms(S.now)} ${t("kst")}`;
    const ks = S.kpm;
    $("feedstats").innerHTML = `<div class="kv"><span>KPM</span><b class="num">${(ks.total_rows || 0).toLocaleString()}</b></div>` +
      `<div class="kv"><span>rows/min</span><b class="num">${fmt(ks.rows_per_min)}</b></div>` +
      `<div class="kv"><span>controls</span><b class="num">${S.actuation.counts.actuated}</b></div>` +
      `<div class="kv"><span>shadow</span><b class="num">${S.actuation.counts.shadow}</b></div>`;
  }

  const tile = (cls, label, value, unit, sub, extra = "") =>
    `<div class="tile ${cls}" ${extra}><div class="tl">${label}</div><div class="tv num">${value}${unit ? `<small>${unit}</small>` : ""}</div><div class="ts">${sub || "&nbsp;"}</div></div>`;
  const kstD = new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false });
  function kstDate(t) { return kstD.format(new Date(t * 1000)) + " KST"; }
  const chartH = (rows) => { const F = parseFloat(getComputedStyle(document.body).fontSize); return Math.max(F * 12, Math.min(F * 26, (innerHeight - F * (ui.pres === "1" ? 22 : 26)) / rows)); };
  const ues = (o) => Object.keys(o || {}).sort();

  // ----------------------------------------------------------- overview --
  function overview() {
    const r = S.rtt, tp = S.tput, a = S.actuation, p = S.pipeline;
    const losses = ues(r.ues).map((u) => r.ues[u].loss_pct).filter((v) => v !== null);
    const loss = losses.length ? losses.reduce((x, y) => x + y, 0) / losses.length : null;
    const el = $("pg-overview");
    if (!el.dataset.built) {
      el.innerHTML = `<div class="grid6" id="ov-tiles"></div>
        <div class="row2"><div class="panel"><h2>${'<span data-i18n="c_rtt"></span>'}<span class="legend" id="lg-rtt"></span></h2><div class="chart" id="ch-rtt"></div></div>
        <div class="panel"><h2><span data-i18n="c_tput"></span><span class="legend" id="lg-tput"></span></h2><div class="chart" id="ch-tput"></div></div></div>
        <div class="row3"><div class="panel"><h2><span data-i18n="c_rsrp"></span><span class="legend dim" id="kpmrows"></span></h2><div class="chart" id="ch-rsrp"></div></div>
        <div class="panel"><h2 data-i18n="c_ue"></h2><div id="uetable"></div></div>
        <div class="panel"><h2 data-i18n="c_events"></h2><div id="events"></div></div></div>`;
      el.dataset.built = 1;
    }
    el.querySelectorAll("[data-i18n]").forEach((e) => (e.textContent = t(e.dataset.i18n)));
    $("ov-tiles").innerHTML =
      tile("hero cyan", t("t_rtt"), fmt(r.all.p50), "ms", t("t_rtt_sub", { p95: fmt(r.all.p95), loss: fmt(loss) })) +
      tile("", t("t_dl"), fmt(tp.total.dl_last), "Mbps", t("t_mean60", { v: fmt(tp.total.dl_mean) })) +
      tile("", t("t_ul"), fmt(tp.total.ul_last), "Mbps", t("t_mean60", { v: fmt(tp.total.ul_mean) })) +
      tile("", t("t_declat"), fmt(a.latency.p50), "ms", t("t_declat_sub", { p95: fmt(a.latency.p95) })) +
      tile("hero gold", t("t_policy"), S.runtime && S.runtime.ai_active ? S.runtime.eligibility.candidate_version : p.active || "–", "", S.runtime && S.runtime.ai_active ? t("v4_selector") : S.runtime && S.runtime.store_only ? t("t_policy_store_only") : p.active_xapp ? t("t_policy_xapp") : t("t_policy_store")) +
      tile("hero emer", t("t_gate"), `${p.counts.promoted}<small>/</small>${p.counts.rejected}`, "", t("t_gate_sub", { p: p.counts.promoted, r: p.counts.rejected }));
    const now = S.now, t0 = now - 180;
    const rs = ues(r.series).map((u) => ({ name: u, short: "ms", color: colorOf(u), pts: r.series[u], area: ues(r.series).length === 1 }));
    $("lg-rtt").innerHTML = rs.map((s) => `<span><span class="sw" style="background:${s.color}"></span>${esc(s.name)}</span>`).join("");
    line($("ch-rtt"), { series: rs, t0, t1: now, unit: "ms", yZero: true, h: chartH(2), empty: t("no_file", { f: "working/metrics/rtt.jsonl" }) });
    const ts = [];
    ues(tp.series).forEach((u) => {
      ts.push({ name: `${u} DL`, short: "DL", color: colorOf(u), pts: tp.series[u].dl, area: true });
      ts.push({ name: `${u} UL`, short: "UL", color: colorOf(u), pts: tp.series[u].ul, dash: true, width: 1.6 });
    });
    $("lg-tput").innerHTML = ues(tp.series).map((u) => `<span><span class="sw" style="background:${colorOf(u)}"></span>${esc(u)} DL</span><span><span class="sw dash" style="border-color:${colorOf(u)}"></span>UL</span>`).join("");
    line($("ch-tput"), { series: ts, t0, t1: now, unit: "Mbps", yZero: true, h: chartH(2), empty: t("no_file", { f: "working/metrics/tput.jsonl" }) });
    $("kpmrows").textContent = t("kpm_rows", { n: (S.kpm.total_rows || 0).toLocaleString(), r: fmt(S.kpm.rows_per_min) });
    line($("ch-rsrp"), { series: [{ name: "RSRP", short: "dBm", color: "#D4AF37", pts: S.kpm.rsrp }], t0: now - 600, t1: now, unit: "dBm", digits: 0, h: 9.5 * parseFloat(getComputedStyle(document.body).fontSize), empty: t("no_file", { f: "working/kpm/kpm.jsonl" }) });
    const rows = [...new Set([...ues(r.ues), ...ues(tp.ues)])].map((u) => {
      const x = r.ues[u] || {}, y = tp.ues[u] || {};
      return `<tr><td><span class="sw" style="background:${colorOf(u)}"></span> ${esc(u)}</td><td class="r num">${fmt(x.p50)}</td><td class="r num">${fmt(x.p95)}</td><td class="r num">${fmt(x.jitter)}</td><td class="r num">${fmt(x.loss_pct)}%</td><td class="r num">${fmt(y.dl_mean)}</td><td class="r num">${fmt(y.ul_mean)}</td></tr>`;
    }).join("");
    $("uetable").innerHTML = rows ? `<table><tr><th>${t("col_ue")}</th><th class="r">${t("col_p50")}</th><th class="r">${t("col_p95")}</th><th class="r">${t("col_jit")}</th><th class="r">${t("col_loss")}</th><th class="r">${t("col_dl")}</th><th class="r">${t("col_ul")}</th></tr>${rows}</table><div class="dim" style="font-size:.72rem;margin-top:.4rem">ms · Mbps</div>` : `<div class="empty">${t("no_data")}</div>`;
    const ev = [
      ...a.feed.slice(0, 8).map((f) => ({ t: f.t, html: `${f.kind === "actuated" ? `<span class="chip act">${t("k_actuated")}</span>` : `<span class="chip shd">${t("k_shadow")}</span>`} ${esc(actName(f.action))} · ${esc(f.ue || "")} ${f.kind === "actuated" ? resultChip(f) : ""}` })),
      ...p.events.slice(-4).map((e) => ({ t: e.t, html: `<span class="chip ${e.verdict === "promoted" ? "solid-ok" : "solid-bad"}">${t("v_" + e.verdict)}</span> ${esc(e.version)} · ${fmt(e.worst, 3)} ${e.verdict === "promoted" ? "≥" : "<"} ${fmt(e.threshold, 2)}` })),
    ].sort((x, y) => y.t - x.t).slice(0, 7);
    $("events").innerHTML = ev.length ? `<table>${ev.map((e) => `<tr><td class="dim num">${hms(e.t)}</td><td style="white-space:normal">${e.html}</td></tr>`).join("")}</table>` : `<div class="empty">${t("no_data")}</div>`;
  }
  const actName = (a) => t("act_" + String(a || "").toLowerCase()) === "act_" + String(a || "").toLowerCase() ? a : t("act_" + String(a).toLowerCase());
  const resultChip = (f) => `<span class="chip ${f.ok ? "ok" : "bad"}">${esc(f.result)}</span>`;

  // ---------------------------------------------------------- actuation --
  function actuation() {
    const a = S.actuation, c = a.counts, f = a.focus;
    const p = f && f.params, proof = p && p.rrc_completion_evidence;
    const cuComplete = p && p.rrc_handover_complete === true && proof && typeof proof.cu_container_id === "string" && proof.cu_container_id.length > 0
      && Number.isInteger(p.cu_ue_id) && p.cu_ue_id >= 0 && typeof p.target_nr_cell_id === "string" && p.target_nr_cell_id.length > 0
      && proof.cu_ue_id === p.cu_ue_id && proof.target_nr_cell_id === p.target_nr_cell_id
      && typeof proof.trigger_marker === "number" && Number.isFinite(proof.trigger_marker)
      && typeof proof.completion_marker === "number" && Number.isFinite(proof.completion_marker);
    const el = $("pg-actuation");
    const effTxt = (e) => {
      if (!e) return "–";
      if (e.status === "measured") return `<span class="${e.delta_pct >= 0 ? "up" : "down"}">${e.delta_pct >= 0 ? "▲" : "▼"} ${fmt(Math.abs(e.delta_pct))}%</span>`;
      if (e.status === "measuring") return `<span class="dim">${t("measuring", { s: fmt(e.ready_in_s, 0) })}</span>`;
      if (e.status === "not-applied") return `<span class="mute">${t("not_applied")}</span>`;
      return `<span class="mute">${t("no_effect")}</span>`;
    };
    let chain = `<div class="empty">${t("no_file", { f: "working/actuation/actions.jsonl" })}</div>`;
    if (f) {
      const e = f.effect || {}, trig = f.trigger && typeof f.trigger === "object" ? f.trigger : null;
      const params = Object.entries(f.params || {}).map(([k, v]) => `<div class="kv2"><span>${esc(k)}</span><b>${esc(v)}</b></div>`).join("");
      chain = `<div class="chainrow">
        <div class="cbox dec"><div class="ch">① ${t("chain_dec")}</div><div class="big num">${hms(f.t)}</div>
          <div class="kv2"><span>${t("policy")}</span><b style="color:var(--gold)">${esc(f.policy_version || "–")}</b></div>
          <div class="kv2"><span>UE</span><b>${esc(f.ue || "–")}</b></div>
          ${trig ? `<div class="kv2"><span>${t("trigger")}</span><b>${esc(trig.kpi || "")} ${fmt(trig.observed)} &lt; ${fmt(trig.slo)}</b></div>` : ""}</div>
        <div class="link">→<small class="num">${fmt(f.latency_ms)} ms</small></div>
        <div class="cbox act"><div class="ch">② ${t("chain_act")} · E2SM-RC</div><div class="big">${esc(actName(f.action))}</div>
          <div class="kv2"><span>${t("target")}</span><b>${esc(f.target || "–")}</b></div>
          ${p && p.ric_style === 3 && p.ric_action === 1 ? `<div class="kv2"><span>${t("cu_rrc")}</span><b class="${cuComplete ? "up" : "dim"}">${t(cuComplete ? "cu_verified" : "cu_unverified")}</b></div>` : ""}
          ${cuComplete && typeof p.decision_to_cu_confirmed_ms === "number" && Number.isFinite(p.decision_to_cu_confirmed_ms) ? `<div class="kv2"><span>${t("decision_cu")}</span><b class="num">${fmt(p.decision_to_cu_confirmed_ms)} ms</b></div>` : ""}${params}
          <div class="kv2"><span>${t("result")}</span>${resultChip(f)}</div></div>
        <div class="link">→</div>
        <div class="cbox eff ${e.delta_pct < 0 ? "neg" : ""}"><div class="ch">③ ${t("chain_eff")} · DL</div><div class="big num">${effTxt(e)}</div>
          <div class="kv2"><span>${t("before")}</span><b class="num">${fmt(e.dl_before)} Mbps</b></div>
          <div class="kv2"><span>${t("after")}</span><b class="num">${fmt(e.dl_after)} Mbps</b></div>
          <div class="kv2"><span>source</span><b>${esc(e.source || "–")}</b></div></div>
      </div><div class="chart" id="ch-eff" style="margin-top:.7rem"></div>`;
    }
    const feedRows = a.feed.map((x) => {
      const key = `${x.kind}${x.t}${x.ue}`, isNew = seenFeed.size && !seenFeed.has(key);
      seenFeed.add(key);
      const sh = x.kind === "shadow";
      return `<tr class="${isNew ? "new" : ""}"><td class="num dim">${hms(x.t)}</td>
        <td>${sh ? `<span class="chip shd">${t("k_shadow")}</span>` : `<span class="chip act">${t("k_actuated")}</span>`}</td>
        <td>${esc(x.ue || "–")}</td><td>${esc(actName(x.action))}${sh ? ` <span class="mute">RC ${x.ric.style}/${x.ric.action_id}</span>` : x.params && x.params.ric_style ? ` <span class="mute">RC ${x.params.ric_style}/${x.params.ric_action}</span>` : ""}</td>
        <td>${esc(sh ? `${x.serving || ""} → ${x.target || ""}` : x.target || "")}</td><td style="color:var(--gold)">${esc(x.policy_version || "–")}</td>
        <td>${sh ? `<span class="mute">would-issue · RSRP ${fmt(x.rsrp_dbm, 0)} dBm</span>` : resultChip(x)}</td>
        <td class="r num">${sh ? "–" : fmt(x.latency_ms) + " ms"}</td><td class="r">${sh ? "–" : effTxt(x.effect)}</td></tr>`;
    }).join("");
    if (!seenFeed.size) seenFeed.add("_");
    el.innerHTML = `<div class="grid5">
        ${tile("hero cyan", t("a_count"), c.actuated, "", t("a_count_sub", { ok: c.ok, f: c.failed }))}
        ${tile("", t("a_succ"), fmt(a.success_pct), "%", `n = ${c.actuated}`)}
        ${tile("hero gold", t("a_lat"), fmt(a.latency.p50), "ms", `p95 ${fmt(a.latency.p95)} · max ${fmt(a.latency.max)} ms`)}
        ${tile("hero emer", t("a_eff"), a.effect_median_pct === null ? "–" : (a.effect_median_pct > 0 ? "+" : "") + fmt(a.effect_median_pct), "%", t("a_eff_sub"))}
        ${tile("", t("a_shadow"), c.shadow, "", t("a_shadow_sub"))}</div>
      <div class="rowA"><div class="panel"><h2>${t("chain")}</h2>${chain}</div>
        <div class="panel"><h2>${t("lat_hist")}</h2><div class="chart" id="ch-lat"></div><div class="note">${t("shadow_note")}</div></div></div>
      <div class="panel"><h2>${t("feed")}</h2>${feedRows ? `<table><tr><th>${t("col_time")}</th><th>${t("col_kind")}</th><th>${t("col_ue")}</th><th>${t("col_action")}</th><th>${t("target")}</th><th>${t("col_policy")}</th><th>${t("col_result")}</th><th class="r">${t("col_lat")}</th><th class="r">${t("col_eff")}</th></tr>${feedRows}</table>` : `<div class="empty">${t("no_data")}</div>`}</div>`;
    hist($("ch-lat"), a.latency.hist, "#D4AF37", "ms");
    if (f && $("ch-eff")) {
      const marks = [{ t: f.t, color: "#22D3EE", label: actName(f.action) }];
      const bands = [{ t0: f.t - 10, t1: f.t, color: "#8796AE" }, { t0: f.t + 2, t1: f.t + 12, color: "#10B981" }];
      line($("ch-eff"), { series: [{ name: `${f.ue} DL`, short: "Mbps", color: colorOf(f.ue), pts: f.series || [], area: true }], t0: f.t - 30, t1: f.t + 30, unit: "Mbps", yZero: true, marks, bands, h: 9 * parseFloat(getComputedStyle(document.body).fontSize), empty: t("no_data") });
    }
  }

  // ----------------------------------------------------------- pipeline --
  const POS = { train: [9, 50], fed: [30, 50], gate: [52, 50], promote: [74, 18], reject: [74, 82], live: [93, 18] };
  let animQ = [], animating = false;
  function drawLane() {
    const s = $("lanesvg");
    if (s.dataset.built) return;
    const seg = (a, b, col) => `<line x1="${POS[a][0]}" y1="${POS[a][1]}" x2="${POS[b][0]}" y2="${POS[b][1]}" stroke="${col}" stroke-width="2" stroke-dasharray="1.5 1.5" vector-effect="non-scaling-stroke" opacity=".55"/>`;
    s.setAttribute("viewBox", "0 0 100 100"); s.setAttribute("preserveAspectRatio", "none");
    s.innerHTML = seg("train", "fed", "#22D3EE") + seg("fed", "gate", "#22D3EE") + seg("gate", "promote", "#10B981") + seg("gate", "reject", "#EF4444") + seg("promote", "live", "#10B981");
    s.dataset.built = 1;
  }
  function detectGateEvents() {
    const evs = S.pipeline.events || [];
    const key = (e) => `${e.version}:${e.verdict}`;
    const loop = S.meta && S.meta.loop;
    if (seenGate === null || (S.mode === "replay" && loop !== lastLoop)) {
      seenGate = new Set(evs.map(key)); lastLoop = loop; return;
    }
    evs.forEach((e) => { if (!seenGate.has(key(e))) { seenGate.add(key(e)); animQ.push(e); } });
    if (animQ.length && !animating) runAnim();
  }
  function replayGateAnimations() {
    const evs = (S && S.pipeline.events) || [];
    const lp = [...evs].reverse().find((e) => e.verdict === "promoted"), lr = [...evs].reverse().find((e) => e.verdict === "rejected");
    [lp, lr].filter(Boolean).forEach((e) => animQ.push(e));
    if (ui.p !== "pipeline") go("pipeline");
    if (!animating) runAnim();
  }
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  async function runAnim() {
    animating = true;
    while (animQ.length) {
      const e = animQ.shift(), promote = e.verdict === "promoted";
      if (ui.p !== "pipeline") go("pipeline");
      drawLane();
      const tok = $("token"), g = $("gauge"), narr = $("narr");
      const stages = document.querySelectorAll("#lane .stage");
      const hit = (st) => { stages.forEach((x) => x.classList.toggle("hit", x.dataset.st === st)); };
      const move = (st) => { tok.style.left = POS[st][0] + "%"; tok.style.top = POS[st][1] + "%"; hit(st); };
      tok.style.transition = "none"; tok.className = "token"; move("train"); void tok.offsetWidth; tok.style.transition = "";
      tok.querySelector(".tv").textContent = e.version;
      tok.querySelector(".tp").textContent = e.poisoned ? `☣ ${t("poisoned")}` : (e.aggregation || "");
      tok.style.opacity = 1; g.style.opacity = 0; g.querySelector(".gfill").style.width = "0";
      g.querySelector(".gfill").style.background = "var(--gold)";
      narr.className = "narr"; narr.textContent = `${e.version} · ${t("s_train")}`;
      await sleep(1100); move("fed"); narr.textContent = `${e.version} · ${t("s_fed")} · ${e.aggregation || ""}${e.poisoned ? " · ☣ " + t("poisoned") : ""}`;
      await sleep(1300); move("gate");
      g.style.opacity = 1; g.querySelector(".gthr").style.left = (e.threshold * 100).toFixed(1) + "%";
      g.querySelector(".gtxt").textContent = `${t("worst")} ${fmt(e.worst, 3)} / ${t("threshold")} ${fmt(e.threshold, 2)}`;
      narr.textContent = `${e.version} · ${t("s_gate")} · ${e.worst_case || "adversarial suite"}`;
      await sleep(250); g.querySelector(".gfill").style.width = Math.min(100, e.worst * 100).toFixed(1) + "%";
      await sleep(1600);
      g.querySelector(".gfill").style.background = promote ? "var(--ok)" : "var(--bad)";
      tok.classList.add(promote ? "promote" : "reject"); move(promote ? "promote" : "reject");
      narr.className = "narr " + (promote ? "promote" : "reject");
      const card = S.pipeline.cards.find((c) => c.version === e.version) || {};
      const rt = S.runtime && S.runtime.eligibility;
      const admitted = !!(rt && rt.candidate_version === e.version && rt.eligible === true && !rt.stale);
      const hotloaded = !!(S.runtime && S.runtime.ai_active && admitted) || S.pipeline.active_xapp === e.version;      // evidence, not assumption
      const rnd = card.round, ctx = e.aggregation && rnd != null ? t("narr_ctx", { agg: e.aggregation, r: rnd }) : e.aggregation ? " · " + e.aggregation : "";
      const nvars = { v: e.version, ctx, p: e.poisoned ? ` · ☣ ${t("poisoned")}` : "", w: fmt(e.worst, 3), t: fmt(e.threshold, 2) };
      narr.textContent = promote ? t(hotloaded && card.in_store ? "narr_promote" : card.in_store ? "narr_promote_store" : "narr_promote_gate", nvars) : t("narr_reject", nvars);
      await sleep(1500);
      if (promote && hotloaded && card.in_store) { move("live"); await sleep(1400); }
      await sleep(2600);
    }
    animating = false;
  }

  // ---------------------------------------------- four separate verdicts --
  // Research gate / final evaluation / runtime admission / effective controller are four different
  // facts. Never derive "AI is running" from the highest version in the A1 store.
  function verdictStrip() {
    const R = S.runtime;
    if (!R) return "";
    const g = R.research_gate, f = R.final_evaluation, e = R.eligibility, x = R.effective;
    const card = (cls, label, chip, val, sub) => `<div class="v4c ${cls}"><div class="v4l">${label}</div><div class="v4v"><span class="chip ${chipCls(cls)}">${chip}</span> ${val}</div><div class="v4s">${sub}</div></div>`;
    const chipCls = (c) => ({ ok: "solid-ok", bad: "solid-bad", warn: "warn", mute: "" }[c] || "");
    const gv = g.verdict === "promoted" ? ["ok", t("v4_promote")] : g.verdict === "rejected" ? ["bad", t("v4_reject")] : ["mute", t("v4_none")];
    const gscore = g.worst != null && g.threshold != null ? `<b class="num">${fmt(g.worst, 4)}</b> <span class="mute">/ ${fmt(g.threshold, 2)}</span>` : "";
    const gsub = (g.candidate_version ? `<b>${esc(g.candidate_version)}</b> · ` : "") + t("v4_gate_sub");
    const fv = f.verdict === "GO" ? ["ok", t("v4_go")] : f.verdict === "H1" ? ["ok", t("v4_h1")] : f.verdict === "H2" ? ["ok", t("v4_h2")] : f.verdict === "NO-GO" ? ["bad", t("v4_nogo")] : ["warn", t("v4_pending")];
    let av, asub;
    if (!e) { av = ["mute", t("v4_waiting")]; asub = t("v4_noinfo"); }
    else {
      av = e.stale ? ["warn", t("v4_stale")] : e.eligible ? ["ok", t("v4_admitted")] : ["bad", t("v4_refused")];
      asub = [e.reason ? esc(e.reason) : "", e.input_scope ? esc(e.input_scope) : "", e.session_state ? esc(e.session_state) : "", e.input_qualified ? t("v4_input_ok") : t("v4_input_no"), e.fixture_only ? t("v4_fixture") : "",
        e.live_eligible ? "" : t("v4_live_no"), e.stale && e.age_s != null ? t("v4_age", { s: fmt(e.age_s, 0) }) : ""].filter(Boolean).join(" · ");
    }
    const ctl = x.controller, bind = R.binding || { ok: false, reason: "no_record" };
    // a selector decision is only "AI" when it is a LEARNED decision bound to the admitted model session;
    // the warm-up default profile and decisions from another session / candidate / context stay visibly separate
    const ev = ctl == null ? ["mute", t("v4_unknown")] : x.stale ? ["warn", t("v4_stale")] :
      ctl === "selector" ? (x.stage === "warm_default" ? ["warn", t("v4_selector_warm")] : !bind.ok ? ["warn", t("v4_unverified")] : ["ok", t("v4_selector")]) :
      ctl === "a3" ? ["warn", t("v4_a3")] : ["mute", t("v4_hold")];
    const calls = e && e.inference_calls != null ? t("v4_calls", { n: e.inference_calls }) : "";
    const esub = [x.stage ? t("v4_stage", { s: esc(x.stage) }) : "", calls, x.stale && x.age_s != null ? t("v4_age", { s: fmt(x.age_s, 0) }) : "",
      ctl === "selector" && !x.stale && x.stage !== "warm_default" && !bind.ok ? t("v4_unbound", { r: esc(bind.reason || "?") }) : ""].filter(Boolean).join(" · ") || t("v4_noinfo");
    const note = R.store_only ? `<div class="v4note">${t("v4_store_only", { v: esc(R.store_active || "–") })}</div>` : "";
    return `<div class="panel v4"><h2>${t("v4_title")}</h2><div class="v4grid">
      ${card(gv[0], t("v4_gate"), gv[1], gscore, gsub)}
      ${card(fv[0], t("v4_final"), fv[1], "", f.decided ? (f.candidate_version ? esc(f.candidate_version) + " · " : "") + t("v4_final_sub") : t("v4_pending_note") + " · " + t("v4_final_sub"))}
      ${card(av[0], t("v4_adm"), av[1], "", asub)}
      ${card(ev[0], t("v4_eff"), ev[1], "", esub)}</div>${note}</div>`;
  }

  function pipeline() {
    drawLane();
    $("pg-pipeline").querySelectorAll("[data-i18n]").forEach((e) => (e.textContent = t(e.dataset.i18n)));
    if (!animating && !$("narr").textContent) $("narr").textContent = t("narr_idle");
    if (!animating) $("narr").textContent = $("narr").className === "narr" ? t("narr_idle") : $("narr").textContent;
    const p = S.pipeline;
    const bar = (c) => {
      if (c.worst === null || c.threshold === null) return `<span class="mute">–</span>`;
      const ok = c.worst >= c.threshold;
      return `<span class="sbar"><i style="width:${Math.min(100, c.worst * 100)}%;background:${ok ? "var(--ok)" : "var(--bad)"}"></i><b style="left:${c.threshold * 100}%"></b></span><b class="num" style="color:${ok ? "var(--ok)" : "var(--bad)"}">${fmt(c.worst, 3)}</b> <span class="mute">${ok ? "≥" : "<"} ${fmt(c.threshold, 2)}</span>`;
    };
    const vchip = (c) => ({ promoted: "solid-ok", rejected: "solid-bad", gating: "warn" }[c.stage] || "");
    const rows = p.cards.slice(0, 14).map((c) => `<tr class="${c.active ? "activerow" : ""}"><td><b style="color:var(--gold)">${esc(c.version)}</b> ${c.active ? `<span class="chip solid-ok">${t("active")}</span>` : ""}</td>
      <td class="num">${c.round ?? "–"}</td><td>${esc(c.aggregation || "–")}</td>
      <td>${c.poisoned ? `<span class="chip bad">☣ ${t("poisoned")}</span>` : `<span class="mute">${c.clients.length || "–"} clients</span>`}</td>
      <td>${bar(c)}</td><td><span class="chip ${vchip(c)}">${t("v_" + c.stage)}</span> ${c.in_store ? `<span class="chip ok">${t("in_store")}</span>` : ""}</td>
      <td class="mute">${esc(c.worst_case || c.suite || "")}</td><td class="num dim">${c.gate_t ? hms(c.gate_t) : "–"}</td></tr>`).join("");
    const k = p.counts;
    $("pipebody").innerHTML = verdictStrip() + `<div class="grid5">
      ${tile("", t("v_trained") + " / " + t("v_federated"), k.trained + k.federated, "", "")}
      ${tile("", t("v_gating"), k.gating, "", "")}
      ${tile("hero emer", t("v_promoted"), k.promoted, "", "")}
      ${tile("hero crim", t("v_rejected"), k.rejected, "", "")}
      ${tile("hero gold", t("t_policy"), S.runtime && S.runtime.ai_active ? S.runtime.eligibility.candidate_version : p.active || "–", "", S.runtime && S.runtime.ai_active ? t("v4_selector") : S.runtime && S.runtime.store_only ? t("t_policy_store_only") : p.active_xapp ? t("t_policy_xapp") : t("t_policy_store"))}</div>
      <div class="panel"><h2>${t("cand")}</h2>${rows ? `<table><tr><th>${t("col_ver")}</th><th>${t("col_round")}</th><th>${t("col_agg")}</th><th>clients</th><th>${t("col_score")}</th><th>${t("col_verdict")}</th><th>worst scenario</th><th>${t("col_time")}</th></tr>${rows}</table>` : `<div class="empty">${t("no_file", { f: "working/policies/ · working/candidates/" })}</div>`}</div>`;
  }

  // ------------------------------------------------------------ results --
  function results() {
    const R = S.results, el = $("pg-results");
    if (!R) { el.innerHTML = `<div class="panel"><div class="empty">${t("r_missing")}</div></div>`; return; }
    const arms = R.arms.map((a) => ({ id: a.id, label: L(a, "label") || t("arm_" + a.id), color: ARM_COLORS[a.id] || "#3B82F6" }));
    const legend = arms.map((a) => `<span><span class="sw" style="background:${a.color};height:.6rem;width:.6rem;border-radius:50%"></span>${esc(a.label)}</span>`).join("");
    const rows = R.metrics.map((m, i) => {
      const c = m.vs_tuned, digits = Math.abs(m.values.policy?.mean ?? 1) < 2 ? 2 : 1;
      const d = c ? `<span class="delta ${c.improves ? "up" : "down"}">${c.rel_pct > 0 ? "+" : ""}${fmt(c.rel_pct)}%</span>${t("vs_tuned")} · ${c.improves ? t("better") : t("worse")}<br><span class="${c.ci_separated ? "" : "mute"}">${c.ci_separated === null ? "" : c.ci_separated ? "✓ " + t("ci_sep") : "≈ " + t("ci_ovl")}</span>` : "";
      return `<div class="metric"><div class="ml"><b>${esc(L(m, "label"))}${m.unit ? ` <span class="mute">(${esc(m.unit)})</span>` : ""}</b><span>${m.better === "lower" ? "↓ " + t("lower_better") : "↑ " + t("higher_better")}${m.scenario ? " · " + esc(m.scenario) : ""}</span>
        <div class="num" style="font-size:.78rem;margin-top:.2rem">${arms.map((a) => m.values[a.id] ? `<span style="color:${a.color}">●</span> ${fmt(m.values[a.id].mean, digits)} ` : "").join(" ")}</div></div>
        <div class="chart" id="ci-${i}"></div><div class="md">${d}</div></div>`;
    }).join("");
    const pv = R.provenance || {};
    const tri = (x, n = 3) => x ? `${x[0] >= 0 ? "+" : ""}${fmt(x[0], n)} <span class="mute">[${fmt(x[1], n)}, ${fmt(x[2], n)}]</span>` : "–";
    const pass = (ok, lbl) => `<span class="chip ${ok ? "solid-ok" : "solid-bad"}">${lbl || (ok ? "PASS" : "FAIL")}</span>`;
    const P = R.paired, M = R.measured_route, Hh = R.confirmatory_history;
    const armLabel = (k) => { const a = R.arms.find((x) => x.id === k); return a ? L(a, "label") : k; };
    const claim = P ? `<div class="panel"><h2>${t("r_claim")} ${pass(P.H2 || P.H1, P.headline)}<span class="legend"><span class="mute">${P.episodes} ${t("r_paired_eps")}</span></span></h2>
        <div class="mute" style="margin:-.2rem 0 .5rem">${esc(pv.headline_meaning || "")}</div>
        <table><tr><th>${t("r_ref")}</th><th>${t("r_util")}</th><th>${t("r_ho")}</th><th>${t("r_fail")}</th><th>${t("r_check")}</th></tr>
        ${Object.entries(P.refs).map(([k, r]) => `<tr><td>${esc(armLabel(k))} <span class="mute">${r.group === "oracle" ? t("r_oracle") : ""}</span></td><td class="num">${tri(r.utility)}</td><td class="num">${tri(r.ho_rate)}</td><td class="num">${tri(r.fail_rate)}</td>
          <td>${r.passed ? pass(true) : pass(false)}${r.group === "oracle" && !r.passed ? ` <span class="mute">${t("r_not_claimed")}</span>` : ""}</td></tr>`).join("")}</table></div>` : "";
    const meas = M ? `<div class="panel"><h2>${t("r_measured")} ${pass(M.H2, "H2 " + (M.H2 ? "PASS" : "FAIL"))} ${pass(M.non_inferiority, t("r_ni") + " " + (M.non_inferiority ? "PASS" : "FAIL"))}<span class="legend"><span class="mute">${M.episodes} ${t("r_paired_eps")}</span></span></h2>
        <div class="mute" style="margin:-.2rem 0 .5rem">${esc(M.scope)}</div>
        <table><tr><th>${t("r_ref")}</th><th>${t("r_util")}</th><th>${t("r_check")}</th></tr>${Object.entries(M.refs).map(([k, r]) => `<tr><td>${esc(armLabel(k))}</td><td class="num">${tri(r.utility)}</td><td>${pass(r.passed)} ${r.failed_checks.length ? `<span class="mute">${esc(r.failed_checks.join(" · "))}</span>` : ""}</td></tr>`).join("")}</table></div>` : "";
    const hist = Hh ? `<div class="panel"><h2>${t("r_hist")}</h2><table><tr><th>${t("col_ver")}</th><th>${t("r_seeds")}</th><th>${t("col_verdict")}</th><th></th></tr>
        ${Hh.map((h) => `<tr><td><b>${esc(h.candidate)}</b></td><td class="mute">${esc(h.seeds)}</td><td>${pass(!/FAIL|NO-GO/.test(h.verdict), esc(h.verdict))}</td><td class="mute">${esc(h.note)}</td></tr>`).join("")}</table></div>` : "";
    el.innerHTML = claim + meas + hist + `<div class="panel"><h2>${esc(L(R, "title") || t("r_title"))}<span class="legend">${legend} <span class="mute">· ${t("ci95")}</span></span></h2>${rows}
      <div class="prov">${Object.entries(pv).map(([k, v]) => `<span><span class="mute">${esc(k)}:</span> ${esc(Array.isArray(v) ? v.join(", ") : v)}</span>`).join("")}</div></div>`;
    R.metrics.forEach((m, i) => ci($(`ci-${i}`), arms, m.values, m.unit, Math.abs(m.values.policy?.mean ?? 1) < 2 ? 2 : 1));
  }

  // ------------------------------------------------------------- campus --
  function campus() {
    const C = S.campus, el = $("pg-campus");
    if (!C.campuses.length) { el.innerHTML = `<div class="panel"><div class="empty">${t("m_missing")}</div></div>`; return; }
    const sites = C.campuses.reduce((s, c) => s + (c.sites || 0), 0);
    const nm = (c) => (ui.lang === "ko" && c.name_ko) || c.name || c.id;
    const vchip = (c) => `<span class="chip ${{ promote: "solid-ok", reject: "solid-bad", pending: "warn" }[c.verdict]}">${c.verdict === "promote" ? t("v_promoted") : c.verdict === "reject" ? t("v_rejected") : t("m_pending")}</span>`;
    const rows = [...C.campuses].sort((a, b) => (b.worst ?? 0) - (a.worst ?? 0)).map((c) => {
      const ok = c.worst !== null && c.threshold !== null && c.worst >= c.threshold, v = c.vs_tuned;
      return `<tr><td><b>${esc(nm(c))}</b> <span class="mute">${esc((ui.lang === "ko" && c.city_ko) || c.city || "")}</span></td><td class="r num">${c.sites ?? "–"}</td>
        <td>${c.worst === null ? "–" : `<span class="sbar" style="width:7rem"><i style="width:${c.worst * 100}%;background:${ok ? "var(--ok)" : "var(--bad)"}"></i><b style="left:${(c.threshold ?? 0) * 100}%"></b></span><b class="num">${fmt(c.worst, 3)}</b>`}</td>
        <td>${vchip(c)}</td><td class="r num">${v && v.delta_pct !== undefined ? `<span class="${v.delta_pct < 0 ? "up" : "down"}">${v.delta_pct > 0 ? "+" : ""}${fmt(v.delta_pct, 0)}%</span> <span class="mute">[${fmt(v.ci_low, 0)}, ${fmt(v.ci_high, 0)}]</span>` : "–"}</td>
        <td class="mute">${esc(c.worst_case || "")}</td></tr>`;
    }).join("");
    el.innerHTML = `<div class="grid4">${tile("", t("m_n"), C.campuses.length, "", "")}${tile("hero emer", t("m_prom"), C.promoted, "", "")}${tile("hero crim", t("m_rej"), C.rejected, "", "")}${tile("", t("m_sites"), sites.toLocaleString(), "", "")}</div>
      <div class="row2" style="grid-template-columns:.8fr 1.2fr"><div class="panel"><h2>${t("m_title")}<span class="legend"><span><span class="sw" style="background:var(--ok);height:.6rem;width:.6rem;border-radius:50%"></span>${t("v_promoted")}</span><span><span class="sw" style="background:var(--bad);height:.6rem;width:.6rem;border-radius:50%"></span>${t("v_rejected")}</span></span></h2><div class="mapwrap" id="map"></div></div>
      <div class="panel"><table><tr><th>${t("col_campus")}</th><th class="r">${t("col_sites")}</th><th>${t("col_score")}</th><th>${t("col_verdict")}</th><th class="r">${t("col_pp")}</th><th>worst scenario</th></tr>${rows}</table></div></div>`;
    korea($("map"), C.campuses, {
      note: t("map_note"), label: (c) => nm(c),
      tip: (c) => `<div class="tt">${esc(nm(c))}</div><div class="tr"><span>${t("worst")}</span><b>${fmt(c.worst, 3)}</b></div><div class="tr"><span>${t("threshold")}</span><b>${fmt(c.threshold, 2)}</b></div><div class="tr"><span>${t("col_sites")}</span><b>${c.sites ?? "–"}</b></div><div class="tr"><span>${t("col_verdict")}</span><b>${c.verdict}</b></div>`,
    });
  }

  applyStatic();
  poll().then(() => { if (ui.anim === "1") { delete ui.anim; setTimeout(replayGateAnimations, 300); } });
})();
