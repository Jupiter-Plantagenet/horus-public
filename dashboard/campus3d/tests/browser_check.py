#!/usr/bin/env python3
"""Browser verification of the campus twin (Playwright + installed Chrome, headless).

    python dashboard/campus3d/serve.py &                         # port 8030
    python dashboard/campus3d/tests/browser_check.py [--base URL] [--out DIR] [--headed]

Checks per case: no page errors / console errors, the WebGL canvas renders a non-trivial image,
no element extends past the viewport, mode badge text, and scenario-specific assertions
(handover phases at known recorded times, protocol replies). Writes JPEG screenshots and
results.json to --out. By default Chrome uses the real GPU (D3D11 on Windows) so the recorded
fps is meaningful on the demo laptop; --software-gl forces SwiftShader.
"""
import argparse, json, sys, time
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
OVERFLOW_JS = """() => {
  const W = innerWidth, H = innerHeight, bad = [];
  for (const el of document.querySelectorAll('body *')) {
    if (el.closest('#labels')) continue;                       // world labels are clipped by design
    const cs = getComputedStyle(el); if (cs.display === 'none' || cs.visibility === 'hidden' || el.hidden) continue;
    if (el.offsetParent === null && cs.position !== 'fixed') continue;
    const r = el.getBoundingClientRect(); if (!r.width || !r.height) continue;
    if (r.right > W + 1 || r.bottom > H + 1 || r.left < -1 || r.top < -1) bad.push(`${el.tagName}#${el.id}.${el.className} ${Math.round(r.left)},${Math.round(r.top)},${Math.round(r.right)},${Math.round(r.bottom)}`);
    if (el.scrollWidth > el.clientWidth + 2 && ['hidden', 'clip'].includes(cs.overflowX) && el.children.length === 0 && el.textContent.trim()
        && cs.textOverflow !== 'ellipsis' && !el.closest('.scen-label')) bad.push(`clipped-text ${el.tagName}.${el.className}: ${el.textContent.trim().slice(0, 40)}`);
  }
  return bad.slice(0, 12);
}"""
CANVAS_JS = """() => { const c = document.getElementById('scene'); return c.toDataURL('image/png').length; }"""


def pixel_stats(png_bytes):
    from PIL import Image
    import io
    im = Image.open(io.BytesIO(png_bytes)).convert("RGB").resize((160, 90))
    px = list(im.getdata()); bg = (5, 15, 34)
    nonbg = sum(1 for p in px if sum(abs(a - b) for a, b in zip(p, bg)) > 40)
    colours = len(set((p[0] // 16, p[1] // 16, p[2] // 16) for p in px))
    return {"nonbg_fraction": round(nonbg / len(px), 3), "colour_buckets": colours}


FPS_JS = """() => new Promise(r => { const ts = []; const t0 = performance.now();
  function f(t) { ts.push(t); if (t - t0 < 3000) requestAnimationFrame(f); else { const d = ts.slice(1).map((x, i) => x - ts[i]).sort((a, b) => a - b);
    r({ fps: +((ts.length - 1) / ((t - ts[0]) / 1000)).toFixed(1), p50_ms: +d[d.length >> 1].toFixed(1), p95_ms: +d[Math.floor(d.length * 0.95)].toFixed(1) }); } }
  requestAnimationFrame(f); })"""
RENDERER_JS = """() => { const g = document.createElement('canvas').getContext('webgl2') || document.createElement('canvas').getContext('webgl');
  const e = g && g.getExtension('WEBGL_debug_renderer_info'); return e ? g.getParameter(e.UNMASKED_RENDERER_WEBGL) : 'unknown'; }"""


def guard_checks(page, out, name):
    """Exercise real browser clocks using explicitly labelled rehearsal fixtures."""
    result = page.evaluate("""async () => {
      const src = await import('./js/sources.js'), hud = await import('./js/hud.js');
      const base = await src.loadBase(), cells = base.route.cells.slice(0, 2).map(c => c.key || c.id);
      const feed = {format:'horus.campus3d.feed/1', mode:'live', label:'LIVE path rehearsal · SAMPLE frames',
        scenario:{segment:'reverse-supported-0'}, cells,
        live:{cycle:'SAMPLE-REHEARSAL', stale:false,age_s:0,rehearsal:true}, traffic:{kind:'icmp_probe'},
        frames:{t_s:[.1,.2],step:[0,1],serving:[0,0],rsrp:[[-90,-95],[-90,-95]],sinr_db:[3,3]},events:[]};
      const live = new src.LiveSource(null, null); await live.init(false); live.ingest(feed);
      const count=live.sc.pos.t.length;live.ingest(feed);
      const duplicate_ignored=live.sc.pos.t.length===count;
      const repeated_snapshot_stales=live.freshness(live.lastProgressAt+2100)==='stale';
      let finish, callbacks=0; const originalFetch=window.fetch;
      const pending=new src.LiveSource('/__campus_guard__',()=>callbacks++);await pending.init(false);
      window.fetch=(u,o)=>String(u).startsWith('/__campus_guard__')?new Promise(r=>finish=r):originalFetch(u,o);
      try { const polling=pending.poll();pending.stop();finish({ok:true,json:async()=>feed});await polling; }
      finally {window.fetch=originalFetch;pending.stop();}
      const stopped_fetch_does_not_restart=callbacks===0 && pending.timer===null && pending.after===-1;
      const scene={schema:'horus.twin-scene/1',id:'recorded-path-rehearsal',mode:'REPLAY',label:'Recorded scene · LIVE path rehearsal',
        clock:{duration_s:60},traffic:{kind:'icmp_probe'},route:{columns:['t_s','lat','lon','x_m','y_m'],points:[[0,0,0,0,0],[60,0,0,10,10]]},
        cells:[{id:'a',short:'A',anchor:{x:0,y:0}},{id:'b',short:'B',anchor:{x:10,y:10}}],
        arms:{horus:{label:'Recorded actor',provenance:'recorded',serving:[[0,'A'],[2,'B']],events:[
          {id:'missing-cu',t:2,from:'A',to:'B',status:'confirmed',decision_to_send_ms:10,ack_ms:2}]}}};
      const normalized=await src.buildFromConsoleScene(scene), event=normalized.arms[0].events[0];
      const missing_completion_not_confirmed=event.status!=='confirmed' && event.phases.cu_confirmed===null;
      const unresolved_control_preserves_source=hud.currentLink(normalized,20).serving===0;
      return {duplicate_ignored,repeated_snapshot_stales,stopped_fetch_does_not_restart,
        missing_completion_not_confirmed,unresolved_control_preserves_source,feed,scene};
    }""")
    feed, scene = result.pop('feed'), result.pop('scene')
    page.evaluate("s=>window.postMessage({type:'horus.twin.scene',v:1,scene:s},location.origin)",scene)
    page.wait_for_timeout(300)
    page.evaluate("window.postMessage({type:'horus.twin.tick',v:1,t:10,playing:true,rate:1,mode:'LIVE',live:{stale:false,age_s:0,rehearsal:true}},location.origin)")
    page.wait_for_timeout(250)
    result['external_fresh_live'] = ' live' in page.get_attribute('#mode-badge','class')
    result['unconfirmed_marker_stays_cyan'] = page.evaluate("""()=>{const m=[...document.querySelectorAll('.wl.ho')].find(e=>e.textContent.includes('A→B'));return !!m&&m.classList.contains('pending')&&getComputedStyle(m).color==='rgb(0, 217, 255)'}""")
    page.wait_for_timeout(2200)
    t1 = float(page.inner_text('#t-now'));page.wait_for_timeout(350);t2=float(page.inner_text('#t-now'))
    result['external_stops_and_freezes'] = 'stale' in page.get_attribute('#mode-badge','class') and abs(t2-t1)<.15
    page.screenshot(path=str(out/f'{name}-external-stale.jpg'),type='jpeg',quality=85)
    page.evaluate("window.postMessage({type:'horus.twin.tick',v:1,t:30,playing:true,rate:1,mode:'LIVE',live:{stale:true,age_s:9,rehearsal:true}},location.origin)")
    page.wait_for_timeout(100)
    result['explicit_stale_honored'] = 'stale' in page.get_attribute('#mode-badge','class') and float(page.inner_text('#t-now'))<11
    page.evaluate("window.postMessage({type:'horus.campus3d.command',v:1,cmd:'setMode',mode:'live'},location.origin)")
    page.wait_for_timeout(300)
    page.evaluate("feed=>window.postMessage({type:'horus.campus3d.command',v:1,cmd:'pushFeed',feed},location.origin)",feed)
    page.wait_for_timeout(250)
    result['pushed_fresh_live'] = ' live' in page.get_attribute('#mode-badge','class')
    page.wait_for_timeout(2200)
    result['pushed_stops_and_stales'] = 'stale' in page.get_attribute('#mode-badge','class')
    page.screenshot(path=str(out/f'{name}-pushed-stale.jpg'),type='jpeg',quality=85)
    page.evaluate("window.postMessage({type:'horus.campus3d.command',v:1,cmd:'setMode',mode:'replay'},location.origin)")
    page.wait_for_timeout(500)
    page.evaluate("window.postMessage({type:'horus.campus3d.command',v:1,cmd:'setStatus',status:{artifact:{version:'UNACCEPTED_SAMPLE',kind:'federated'},gate:{state:'pending'}}},location.origin)")
    page.wait_for_timeout(250)
    body=page.inner_text('#artifact-body')
    result['historical_artifact_not_overwritten'] = 'v3.39.0' in body and 'UNACCEPTED_SAMPLE' not in body
    result['historical_traffic_not_video'] = 'video' not in page.inner_text('.dev').lower()
    return result


def run(base, out, headed, live_base=None, only=None, software=False):
    out.mkdir(parents=True, exist_ok=True)
    cases = []
    if live_base:
        cases.append(dict(name="live-rehearsal-1280-en", url="scen=live&lang=en", size=(1280, 720), expect_mode="live", base=live_base, live=True))
    for (w, h) in ((1280, 720), (1920, 1080)):
        for lang in ("en", "ko"):
            cases.append(dict(name=f"seg0-{w}x{h}-{lang}", url=f"scen=seg0&lang={lang}&t=160&autoplay=0", size=(w, h), expect_mode="replay"))
    cases += [
        dict(name="seg0-inflight-1280-en", url="scen=seg0&lang=en&t=155.5&autoplay=0", size=(1280, 720), expect_mode="replay", inflight=True),
        dict(name="walk-1920-en", url="scen=walk&lang=en&t=900&autoplay=0", size=(1920, 1080), expect_mode="replay"),
        dict(name="walk-overview-1280-ko", url="scen=walk&lang=ko&t=1500&autoplay=0&view=overview", size=(1280, 720), expect_mode="replay"),
        dict(name="sample-1280-en", url="scen=sample&lang=en&t=120&autoplay=0", size=(1280, 720), expect_mode="sample"),
        dict(name="live-waiting-1280-en", url="scen=live&lang=en", size=(1280, 720), expect_mode="waiting"),
        dict(name="embed-operator-960x540", url="embed=operator&lang=en&t=160&autoplay=0", size=(960, 540), expect_mode="replay", embed=True),
        dict(name="top-1920-ko", url="scen=seg0&lang=ko&t=180&autoplay=0&view=top", size=(1920, 1080), expect_mode="replay"),
        dict(name="guard-live-1280-en", url="scen=seg0&lang=en&t=160&autoplay=0", size=(1280,720),expect_mode="replay",guard=True),
        dict(name="guard-live-1920-ko", url="scen=seg0&lang=ko&t=160&autoplay=0", size=(1920,1080),expect_mode="replay",guard=True),
    ]
    results = []
    with sync_playwright() as p:
        gl = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] if software else ["--use-angle=d3d11" if sys.platform == "win32" else "--use-angle=default", "--enable-gpu"]
        browser = p.chromium.launch(channel="chrome", headless=not headed, args=gl + ["--ignore-gpu-blocklist"])
        for c in cases:
            if only and not any(o in c["name"] for o in only): continue
            page = browser.new_page(viewport={"width": c["size"][0], "height": c["size"][1]})
            errors = []
            requests=[]
            page.on('request',lambda req:requests.append(req.url))
            page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
            page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
            page.goto(f"{c.get('base', base)}/campus3d/index.html?{c['url']}")
            page.wait_for_function("document.getElementById('scen-label').textContent.length > 0", timeout=20000)
            page.wait_for_timeout(6000 if c.get("live") else 2500)     # camera settles / live frames arrive
            r = {"case": c["name"], "errors": errors, "renderer": page.evaluate(RENDERER_JS)}
            r["mode_text"] = page.inner_text("#mode-text")
            r["mode_class"] = page.get_attribute("#mode-badge", "class")
            r["overflow"] = page.evaluate(OVERFLOW_JS)
            shot = page.screenshot(type="png")
            r["pixels"] = pixel_stats(shot)
            page.screenshot(path=str(out / f"{c['name']}.jpg"), type="jpeg", quality=82)
            r["serving"] = page.inner_text("#serving") if not c.get("embed") else page.inner_text(".embed-pill")
            r['device_label']=page.inner_text('.dev')
            r['offline_assets']=all(u.startswith(('http://127.0.0.1:','http://localhost:','data:','blob:')) for u in requests)
            if c["name"].startswith("seg0-1280x720-en"):
                r["ran"] = page.inner_text("#ran-body"); r["evidence"] = page.inner_text("#accept-body")
                # protocol: seek via horus.campus3d.command, then a horus.twin/1 scene from the console's example if present
                page.evaluate("window.postMessage({type:'horus.campus3d.command', v:1, cmd:'seek', t_s: 176.5}, location.origin)")
                page.wait_for_timeout(600); r["after_seek_t"] = page.inner_text("#t-now")
                r["after_seek_ran"] = page.inner_text("#ran-body")
            if c.get("inflight"):
                r["target"] = page.inner_text("#target"); r["ran"] = page.inner_text("#ran-body")
            if c.get("embed"):
                ex = next((q for q in (HERE.parent.parent / "operator/data/twin-scene.example.json",
                                       Path("D:/Horus/competition-console/dashboard/operator/data/twin-scene.example.json")) if q.exists()), None)
                if ex:
                    scene = json.loads(ex.read_text(encoding="utf-8"))
                    page.evaluate("s => window.postMessage({type:'horus.twin.scene', v:1, scene:s}, location.origin)", scene)
                    page.wait_for_timeout(800)
                    page.evaluate("window.postMessage({type:'horus.twin.tick', v:1, t:158.0, playing:false, rate:1, mode:'REPLAY', arm:'horus'}, location.origin)")
                    page.wait_for_timeout(1500)
                    r["console_scene_label"] = page.inner_text("#scen-label"); r["console_pill"] = page.inner_text(".embed-pill")
                    page.screenshot(path=str(out / f"{c['name']}-console-scene.jpg"), type="jpeg", quality=82)
                else:
                    r["console_scene_label"] = "operator example not present in this workspace"
            if c.get('guard'):r['guards']=guard_checks(page,out,c['name'])
            r["frame"] = page.evaluate(FPS_JS)
            if c.get("live"):
                r["t_now_1"] = float(page.inner_text("#t-now")); page.wait_for_timeout(5000); r["t_now_2"] = float(page.inner_text("#t-now"))
            ok = (not errors and not r["overflow"] and r["pixels"]["nonbg_fraction"] > 0.15 and r["pixels"]["colour_buckets"] > 12
                  and c["expect_mode"] in r["mode_class"] and r['offline_assets'])
            if c.get('guard'):ok=ok and all(r['guards'].values())
            if c.get("live"):   # clock must advance with arriving frames and the badge must say REHEARSAL
                ok = ok and r["t_now_2"] > r["t_now_1"] + 1.0 and "REHEARSAL" in r["mode_text"]
            r["pass"] = ok; results.append(r); page.close()
            print(("PASS " if ok else "FAIL ") + c["name"], f"{r['frame']['fps']} fps", "" if ok else json.dumps({k: r[k] for k in ("errors", "overflow", "pixels", "mode_class")}, ensure_ascii=False),flush=True)
        browser.close()
    (out / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    return all(r["pass"] for r in results)


def self_serve(out,headed,only,software):
    """Own two lightweight local servers and one browser, then close all of them."""
    import tempfile,threading
    from http.server import ThreadingHTTPServer
    sys.path.insert(0,str(HERE.parent))
    import serve
    out=Path(out).resolve();out.parent.mkdir(parents=True,exist_ok=True)
    stop=threading.Event()
    class Server(ThreadingHTTPServer):
        allow_reuse_address=False
        daemon_threads=True
    with tempfile.TemporaryDirectory(prefix='campus-qa-rehearsal-',dir=out.parent) as folder:
        feed=serve.LiveFeed(folder,rehearsal=True)
        servers=[Server(('127.0.0.1',0),serve.make_handler(item)) for item in (None,feed)]
        threads=[threading.Thread(target=s.serve_forever,daemon=True) for s in servers]
        writer=threading.Thread(target=serve.rehearse,args=(Path(folder),stop),daemon=True)
        for thread in threads:thread.start()
        writer.start()
        try:
            return run(f'http://127.0.0.1:{servers[0].server_port}',out,headed,
                       f'http://127.0.0.1:{servers[1].server_port}',only,software)
        finally:
            stop.set()
            for server in servers:server.shutdown();server.server_close()
            writer.join(timeout=3)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8030")
    ap.add_argument("--out", default=str(HERE.parent / "evidence"))
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--live-base", help="a serve.py --rehearse (or --capture) server to exercise the LIVE path, e.g. http://127.0.0.1:8031")
    ap.add_argument("--only", nargs="*", help="run only cases whose name contains one of these strings")
    ap.add_argument("--software-gl", action="store_true", help="force SwiftShader (no GPU); fps then is not representative")
    ap.add_argument('--self-serve',action='store_true',help='Own temporary local static/rehearsal servers; all scratch remains beside --out')
    a = ap.parse_args()
    ok=self_serve(a.out,a.headed,a.only,a.software_gl) if a.self_serve else run(a.base, Path(a.out), a.headed, a.live_base, a.only, a.software_gl)
    sys.exit(0 if ok else 1)
