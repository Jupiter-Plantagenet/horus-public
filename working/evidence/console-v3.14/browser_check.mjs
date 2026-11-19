// Browser verification of the v3.14 console/dashboard changes (headless Chromium via Playwright).
import { chromium } from 'playwright';
import fs from 'node:fs';

const OUT = process.argv[2];
fs.mkdirSync(OUT, { recursive: true });
const cases = [
  { id: 'console-v314-en', url: 'http://127.0.0.1:8030/campus3d/?scen=v314&lang=en&autoplay=0&t=156&view=hero', w: 1920, h: 1080,
    expect: ['v3.14.24', 'H2', 'H1 not claimed', 'H2 FAIL', 'Network CHO', '-0.046', 'ping-pong guardrail fails'] },
  { id: 'console-v314-ko', url: 'http://127.0.0.1:8030/campus3d/?scen=v314&lang=ko&autoplay=0&t=156', w: 1280, h: 720,
    expect: ['v3.14.24', 'H2', '미주장'] },
  { id: 'console-walk-en', url: 'http://127.0.0.1:8030/campus3d/?scen=walk&lang=en&autoplay=0&t=400', w: 1920, h: 1080,
    expect: ['HORUS v3.14.24', 'Network CHO'] },
  { id: 'console-seg0v314-en', url: 'http://127.0.0.1:8030/campus3d/?scen=seg0v314&lang=en&autoplay=0&t=157', w: 1920, h: 1080,
    expect: ['v3.14.24', '2-hour run', '2.05 h', '82', 'CU RRC', 'Executed · v3.14.24'] },
  { id: 'console-seg0v314-ko', url: 'http://127.0.0.1:8030/campus3d/?scen=seg0v314&lang=ko&autoplay=0&t=181', w: 1280, h: 720,
    expect: ['v3.14.24', '2시간 실행'] },
  { id: 'console-seg0-en', url: 'http://127.0.0.1:8030/campus3d/?scen=seg0&lang=en&autoplay=0&t=150', w: 1920, h: 1080,
    expect: ['v3.39.0'] },
  { id: 'dash-results-en', url: 'http://127.0.0.1:8014/#p=results&lang=en&mode=live', w: 1920, h: 1080,
    expect: ['Pre-registered held-out claim', 'H2', 'Measured campus route', 'Every pre-registered confirmatory test', 'not claimed'] },
  { id: 'dash-results-ko', url: 'http://127.0.0.1:8014/#p=results&lang=ko&mode=live', w: 1280, h: 720,
    expect: ['사전 등록 홀드아웃 결과', 'H2'] },
  { id: 'dash-pipeline-en', url: 'http://127.0.0.1:8014/#p=pipeline&lang=en&mode=live', w: 1920, h: 1080, expect: ['H2 PASS'] },
  { id: 'finals-results-en', url: 'http://127.0.0.1:8015/#p=results&lang=en&mode=live', w: 1920, h: 1080,
    expect: ['Pre-registered held-out claim', 'H2', 'Measured campus route'] },
];
const browser = await chromium.launch({ args: ['--use-gl=swiftshader', '--enable-unsafe-swiftshader'] });
const results = [];
for (const c of cases) {
  const page = await browser.newPage({ viewport: { width: c.w, height: c.h } });
  const errors = [];
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
  await page.goto(c.url, { waitUntil: 'networkidle' });
  await page.waitForTimeout(4000);
  const text = await page.evaluate(() => document.body.innerText);
  const low = text.toLowerCase(); const missing = c.expect.filter((s) => !low.includes(s.toLowerCase()));
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
  await page.screenshot({ path: `${OUT}/${c.id}.jpg`, type: 'jpeg', quality: 70 });
  const ok = !errors.length && !missing.length && !overflow;
  results.push({ id: c.id, ok, errors, missing, overflow });
  console.log(`${ok ? 'PASS' : 'FAIL'} ${c.id}${errors.length ? ' errors=' + JSON.stringify(errors.slice(0, 3)) : ''}${missing.length ? ' missing=' + JSON.stringify(missing) : ''}${overflow ? ' overflow' : ''}`);
  await page.close();
}
await browser.close();
fs.writeFileSync(`${OUT}/results.json`, JSON.stringify(results, null, 1));
process.exit(results.every((r) => r.ok) ? 0 : 1);
