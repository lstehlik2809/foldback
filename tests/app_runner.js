// Runs test cases through the real app (index.html) in headless Chromium and prints the app's results as JSON.
//
// Each case's `state` is the app's own saved-tree format. It is put into sessionStorage, exactly where the app keeps a
// tree, and the page is reloaded, so the app loads, computes and renders it through its normal start-up path.
// To read the results at full precision (not the rounded text on screen), a one-line hook that returns the app's
// internal results object is added to a temporary copy of index.html. The app in the repository is not changed.
//
// Usage: NODE_PATH=$(npm root -g) node tests/app_runner.js tests/cases/01_*.json ... > app_results.json
// Env:   FOLDBACK_APP (default: index.html next to this folder)
const { chromium } = require('playwright');
const fs = require('fs'), path = require('path'), os = require('os'), { pathToFileURL } = require('url');

const APP = path.resolve(process.env.FOLDBACK_APP || path.join(__dirname, '..', 'index.html'));
const ANCHOR = '// ---------- boot ----------';
const HOOK = 'window.__foldbackTest = { R: () => R, S: () => S };\n';
const STORE_KEY = 'foldback2:v1';

function patchedApp() {
  const html = fs.readFileSync(APP, 'utf8');
  const n = html.split(ANCHOR).length - 1;
  if (n !== 1) throw new Error(`Expected the line "${ANCHOR}" exactly once in ${APP}, found ${n}. Update ANCHOR in tests/app_runner.js.`);
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'foldback-test-'));
  const file = path.join(dir, 'index.html');
  fs.writeFileSync(file, html.replace(ANCHOR, HOOK + ANCHOR));
  return file;
}

// Runs inside the page: turns the app's results object into plain JSON.
function extract() {
  const R = window.__foldbackTest.R(), S = window.__foldbackTest.S();
  const mean = a => { let s = 0; for (let i = 0; i < a.length; i++) s += a[i]; return s / a.length; };
  const sd = a => { const m = mean(a); let s = 0; for (let i = 0; i < a.length; i++) s += (a[i] - m) ** 2; return Math.sqrt(s / (a.length - 1)); };
  const num = x => (Number.isFinite(x) ? x : null);
  const out = {
    ok: R.ok, errors: R.errors.map(e => ({ where: e.where, msg: e.msg })),
    options: S.options.map(o => o.label), seed: String(S.seed),
    point: Array.from(R.point.vals, num), pointLeader: R.pBest, tie: !!R.tie,
    scope: Object.fromEntries(Object.entries(R.point.v).map(([k, v]) => [k, num(v)])),
    dom: { leader: (document.querySelector('#mini-best') || {}).textContent || '', headline: ((document.querySelector('#v-head') || {}).innerText || '').trim(), note: ((document.querySelector('#v-note') || {}).value || '') },
  };
  if (!R.ok) return out;
  out.order = R.order;
  out.sim = {
    N: R.sim.N, badWorlds: R.sim.badWorlds, evpi: R.sum.evpi, meanLeader: R.sum.bestIdx,
    opts: R.sum.opts.map((o, k) => ({ mean: o.mean, q025: o.q025, q975: o.q975, pBest: o.pBest, sd: sd(R.sim.vals[k]) })),
    hasRanges: !!R.hasRanges,
    drawsHead: Object.fromEntries(Object.entries(R.sim.draws).map(([k, a]) => [k, Array.from(a.slice(0, 5))])),
  };
  if (R.pair) { const d = R.pair.d; out.pair = { a: R.pair.a, b: R.pair.b, threat: R.pair.threat, pB: R.pair.pB, meanDiff: mean(d), q025: E.quantile(d, 0.025), q975: E.quantile(d, 0.975) }; }
  // R.evppi holds labels; map them back to the numbers' names through the app's own label table
  const byLabel = {}; for (const [name, m] of Object.entries(R.M.meta)) (byLabel[m.label] = byLabel[m.label] || []).push(name);
  out.evppi = (R.evppi || []).map(x => { const ns = (byLabel[x.label] || []).filter(n => R.sim.draws[n]); return { name: ns.length === 1 ? ns[0] : null, label: x.label, v: x.v }; });
  out.breakevens = R.be.list.map(b => ({ name: b.name, isProb: b.isProb, uncertain: b.uncertain, range: b.range, L: num(b.L), U: num(b.U), crossings: b.crossings.map(c => ({ at: c.at, from: c.from, to: c.to, inRange: c.inRange })) }));
  if (R.diag) {
    const d = R.diag;
    out.diag = d.error ? { error: d.error } : {
      evsi: d.evsi, cost: d.cost, enbs: d.enbs, changes: d.changes, now: d.now, nowIdx: d.nowIdx,
      pos: { P: d.pos.P, ev: d.pos.ev, bestIdx: d.pos.bestIdx }, neg: { P: d.neg.P, ev: d.neg.ev, bestIdx: d.neg.bestIdx },
      postPos: d.postPos, postNeg: d.postNeg, pGood: d.pGood, pkWindows: d.pk && d.pk.windows,
    };
  }
  return out;
}

(async () => {
  const files = process.argv.slice(2);
  if (!files.length) { console.error('Usage: node tests/app_runner.js <case.json>...'); process.exit(2); }
  const url = pathToFileURL(patchedApp()).href;
  const browser = await chromium.launch();
  const results = {};
  try {
    for (const f of files) {
      const c = JSON.parse(fs.readFileSync(f, 'utf8'));
      const page = await browser.newPage();
      const pageErrors = [];
      page.on('pageerror', e => pageErrors.push(String(e && e.message || e)));
      await page.route(/^https?:/, r => r.abort()); // fonts and video only: the results never need the network
      await page.goto(url);
      await page.evaluate(([k, s]) => sessionStorage.setItem(k, JSON.stringify(s)), [STORE_KEY, c.state]);
      await page.reload();
      await page.waitForFunction(() => window.__foldbackTest && window.__foldbackTest.R() && document.querySelector('#v-note') && document.querySelector('#v-note').value, null, { timeout: 60000 });
      const r = await page.evaluate(extract);
      r.pageErrors = pageErrors;
      results[c.id] = r;
      await page.close();
    }
  } finally { await browser.close(); }
  process.stdout.write(JSON.stringify(results));
})().catch(e => { console.error(e); process.exit(1); });
