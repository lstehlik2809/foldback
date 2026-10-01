// Drives Foldback through the welcome window, the Sam example, "Build it with me" (the Petra case) and the results,
// capturing the screen with the Chrome DevTools screencast. Each narration segment starts with its actions and lasts at
// least as long as its voice clip ($WORK/segments.json, from tts.py).
// Writes $WORK/frames/*.jpg + $WORK/frames.json (frame times) and $WORK/timeline.json (when each line starts).
// Usage: NODE_PATH=$(npm root -g) node record.js     (DRY=1: fast run without capture, prints the result texts)
// Env: FOLDBACK_DEMO_WORK (default <tmp>/foldback-demo-work), FOLDBACK_APP (default ../../index.html from this folder)
const { chromium } = require('playwright');
const fs = require('fs'), path = require('path'), os = require('os'), { pathToFileURL } = require('url');
const SRC = __dirname, DRY = !!process.env.DRY;
const WORK = process.env.FOLDBACK_DEMO_WORK || path.join(os.tmpdir(), 'foldback-demo-work');
const APP = path.resolve(process.env.FOLDBACK_APP || path.join(SRC, '..', '..', 'index.html'));
const SEGS = Object.fromEntries(JSON.parse(fs.readFileSync(path.join(WORK, 'segments.json'), 'utf8')).map(s => [s.id, s]));
const W = 1280, HGT = 720, KEY = DRY ? 0 : 40; // per-key typing delay (ms)
const sleep = ms => new Promise(r => setTimeout(r, DRY ? Math.min(ms, 30) : ms));

// overlay: fake cursor, highlight ring, black cover, end card. It lives in a manual popover so it can sit above the modal dialog.
const OVERLAY = () => {
  const boot = () => {
    if (document.getElementById('ov')) return;
    const st = document.createElement('style');
    st.textContent = `#ov{position:fixed;inset:0;margin:0;padding:0;border:0;background:transparent;width:100vw;height:100vh;max-width:none;max-height:none;overflow:hidden;pointer-events:none}
#ov-cur{position:absolute;left:-40px;top:-40px;width:26px;height:26px;filter:drop-shadow(0 1px 2px rgba(0,0,0,.35))}
#ov-cur.down{transform:scale(.85)}
#ov-ring{position:absolute;border:3px solid #e8590c;border-radius:12px;box-shadow:0 0 0 6px rgba(232,89,12,.18);opacity:0;transition:opacity .35s,left .35s,top .35s,width .35s,height .35s}
#ov-black{position:absolute;inset:0;background:#000}
#ov-card{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;background:rgba(15,23,42,.72);opacity:0;transition:opacity .8s}
#ov-card .c{background:#fff;color:#14213d;border-radius:18px;padding:40px 56px;text-align:center;box-shadow:0 20px 60px rgba(0,0,0,.35);font-family:"Atkinson Hyperlegible",sans-serif}
#ov-card h1{font-family:"Bricolage Grotesque",sans-serif;font-size:56px;margin:0 0 6px;letter-spacing:-.5px}
#ov-card p{font-size:22px;margin:6px 0;color:#475569}
#ov-card .u{font-size:30px;color:#1f5f8b;font-weight:700;margin-top:18px}`;
    document.head.appendChild(st);
    const ov = document.createElement('div'); ov.id = 'ov'; ov.setAttribute('popover', 'manual');
    ov.innerHTML = `<div id="ov-ring"></div><svg id="ov-cur" viewBox="0 0 24 24"><path d="M3 2 L3 19 L7.5 14.8 L10.6 21.5 L13.4 20.3 L10.4 13.7 L16.5 13.7 Z" fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg><div id="ov-black"></div><div id="ov-card"></div>`;
    document.body.appendChild(ov); ov.showPopover();
    const cur = ov.querySelector('#ov-cur');
    addEventListener('mousemove', e => { cur.style.left = e.clientX + 'px'; cur.style.top = e.clientY + 'px'; }, true);
    addEventListener('mousedown', () => cur.classList.add('down'), true); addEventListener('mouseup', () => cur.classList.remove('down'), true);
    let ringSel = null, ringPad = 6;
    const place = () => { const r = ov.querySelector('#ov-ring'); const el = ringSel && document.querySelector(ringSel); if (!el) { r.style.opacity = 0; return; }
      const b = el.getBoundingClientRect(); Object.assign(r.style, { left: b.left - ringPad + 'px', top: b.top - ringPad + 'px', width: b.width + 2 * ringPad + 'px', height: b.height + 2 * ringPad + 'px', opacity: 1 }); };
    addEventListener('scroll', place, true);
    window.__ov = {
      raise() { ov.hidePopover(); ov.showPopover(); },
      ring(sel, pad = 6) { ringSel = sel; ringPad = pad; place(); },
      unring() { ringSel = null; place(); },
      uncover() { ov.querySelector('#ov-black').remove(); },
      card(html) { const c = ov.querySelector('#ov-card'); c.innerHTML = html; c.style.opacity = 1;
        setTimeout(() => { c.style.transition = 'none'; c.style.background = 'rgba(15,23,42,.73)'; }, 1200); }, // nudge a repaint so the screencast gets the final frame
    };
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
};

(async () => {
  const b = await chromium.launch();
  // 1280x720. Frames are captured with the CDP screencast (wall-clock
  // timestamps), not recordVideo: recordVideo's timeline drifted 3-6% from real time here, which put the voice out of sync.
  const ctx = await b.newContext({ viewport: { width: W, height: HGT }, deviceScaleFactor: 1, ignoreHTTPSErrors: true });
  // Google Fonts: if setup_tts.sh saved a local copy, serve it (some sandboxes break the browser's TLS to Google Fonts)
  const fdir = path.join(WORK, 'fonts');
  if (fs.existsSync(path.join(fdir, 'fonts.css'))) {
  await ctx.route(/fonts\.googleapis\.com/, r => r.fulfill({ path: path.join(fdir, 'fonts.css'), headers: { 'content-type': 'text/css', 'access-control-allow-origin': '*' } }));
  await ctx.route(/fonts\.gstatic\.com/, r => r.fulfill({ path: path.join(fdir, r.request().url().split('/').pop()), headers: { 'content-type': 'font/woff2', 'access-control-allow-origin': '*' } }));
  }
  const p = await ctx.newPage(); const errs = [];
  p.on('pageerror', e => errs.push(e.message));
  await p.addInitScript(OVERLAY);
  await p.goto(pathToFileURL(APP).href);
  await p.evaluate(() => document.fonts.ready); await p.waitForTimeout(1200);
  // a fresh tab opens the welcome window (modal); keep the overlay above it
  await p.waitForSelector('#welcome[open]'); await p.evaluate(() => window.__ov.raise());

  // ---- helpers ----
  // the drawn cursor starts in the bottom-right corner, off the welcome window, so the first frame (the poster) is clean
  let mx = W - 36, my = HGT - 30; await p.mouse.move(mx, my);
  const wz = s => p.locator(`#wiz ${s}`), nm = v => p.locator(`input.nm[value="${v}"]`).first();
  const ov = (fn, ...a) => p.evaluate(([fn, a]) => window.__ov[fn](...a), [fn, a]);
  async function moveTo(loc, fx = 0.5, fy = 0.5) {
    await loc.scrollIntoViewIfNeeded(); const bb = await loc.boundingBox(); const x = bb.x + bb.width * fx, y = bb.y + bb.height * fy;
    const steps = DRY ? 1 : Math.max(8, Math.min(30, Math.round(Math.hypot(x - mx, y - my) / 20)));
    await p.mouse.move(x, y, { steps }); mx = x; my = y; }
  async function click(loc, fx, fy) { await moveTo(loc, fx, fy); await sleep(100); await p.mouse.down(); await sleep(60); await p.mouse.up(); await sleep(130); }
  let key = KEY; async function type(loc, text) { await click(loc, 0.3, 0.5); await p.keyboard.press('Control+A'); await p.keyboard.type(text, { delay: key }); await sleep(100); }
  const pick = (name, value) => click(wz(`label:has(input[name$="${name}"][value="${value}"])`));
  async function next(pause = 500) { await click(wz('[data-wiz="next"]')); await sleep(pause); const e = (await p.textContent('#wiz-err')).trim(); if (e) throw new Error('wizard: ' + e); }
  async function money(pre, kind, lo, hi, ml, ev) { await pick(`${pre}.kind`, kind); if (kind === 'none') return;
    await type(wz(`[data-w$="${pre}.lo"]`), lo); await type(wz(`[data-w$="${pre}.hi"]`), hi); await type(wz(`[data-w$="${pre}.ml"]`), ml);
    if (ev) await pick(`${pre}.ev`, ev); }
  async function ways(names) { await pick('.shape', 'two'); await sleep(300);
    for (let i = 0; i < names.length; i++) { if (i >= 2) await click(wz('[data-wwadd]')); await type(wz('[data-w$=".label"]').nth(i), names[i]); } }
  async function scrollTo(y) { await p.evaluate(y => window.scrollTo({ top: y, behavior: 'smooth' }), y); await sleep(900); }
  async function scrollToEl(sel, offset = 70) { const y = await p.evaluate(([s, o]) => document.querySelector(s).getBoundingClientRect().top + scrollY - o, [sel, offset]); await scrollTo(Math.max(0, y)); }

  // ---- segments ----
  await ov('uncover'); await sleep(300);
  const FR = path.join(WORK, 'frames'); fs.rmSync(FR, { recursive: true, force: true }); fs.mkdirSync(FR);
  const frames = []; let fi = 0, first;
  const cdp = await ctx.newCDPSession(p); const gotFirst = new Promise(r => first = r);
  cdp.on('Page.screencastFrame', ({ data, metadata, sessionId }) => {
    const f = path.join(FR, String(fi++).padStart(6, '0') + '.jpg'); fs.writeFileSync(f, Buffer.from(data, 'base64'));
    frames.push({ f, t: metadata.timestamp }); first(); cdp.send('Page.screencastFrameAck', { sessionId }).catch(() => {}); });
  const t0 = Date.now();
  if (!DRY) { await cdp.send('Page.startScreencast', { format: 'jpeg', quality: 92, maxWidth: 1920, maxHeight: 1080, everyNthFrame: 1 });
    await p.evaluate(() => document.body.style.outline = '0px solid transparent'); await gotFirst; }
  const timeline = [];
  async function seg(id, actions = async () => {}, tail = 250) {
    const s = SEGS[id], start = (Date.now() - t0) / 1000; timeline.push({ id, start, dur: s.dur, file: s.file, text: s.text, screen: s.screen });
    await Promise.all([actions(), sleep(s.dur * 1000)]); await sleep(tail);
    console.log(id.padEnd(4), 'start', start.toFixed(2), 'voice', s.dur.toFixed(2), 'took', ((Date.now() - t0) / 1000 - start).toFixed(2));
  }

  await sleep(500);
  // INTRO: the welcome window, then the Sam example
  const wl = a => p.locator(`#welcome .wl-choice[data-welcome="${a}"]`);
  await seg('i1', async () => { await sleep(1500); await moveTo(p.locator('#welcome-title'), 0.7, 0.5); await sleep(3500); await moveTo(p.locator('#welcome .lede'), 0.6, 0.5); }, 150);
  await seg('i1b', async () => { await moveTo(wl('build'), 0.3, 0.35); await sleep(2300); await moveTo(wl('example'), 0.3, 0.35); await sleep(900);
    await moveTo(wl('demo'), 0.3, 0.35); await sleep(900); await moveTo(wl('blank'), 0.3, 0.35); await sleep(1000); await click(wl('example'), 0.3, 0.35); }, 500);
  await seg('i2', async () => { await sleep(2600); await moveTo(nm('Keep and hope')); await sleep(1800);
    await moveTo(nm('Coach for six months')); await sleep(1000); await moveTo(nm('Sam reaches par')); await sleep(1000);
    await moveTo(nm("Sam doesn't: exit")); await sleep(1000); await moveTo(p.locator('.total:has-text("43,000")').first()); });
  await seg('i3', async () => { await moveTo(p.locator('#v-head'), 0.3, 0.2); await ov('ring', '#v-head', 8); });
  await seg('i4', async () => { await ov('ring', '#v-flip', 8); await moveTo(p.locator('#v-flip'), 0.4, 0.15); await sleep(4500); await ov('unring'); }, 500);

  // BUILD IT WITH ME
  await seg('w1', async () => { await sleep(1800); await click(p.locator('[data-wiz="open"]')); await sleep(300); await ov('raise'); await sleep(800); await moveTo(wz('#wiz-count'), 0.5, 0.5); }, 200);
  await seg('w2', async () => { await sleep(600); await type(wz('[data-w="title"]'), 'Petra has an outside offer. How do we respond?'); });
  await next(600);
  await seg('w3', async () => { const o = wz('[data-w^="opt."]');
    for (const [i, v] of ['Counter-offer: match the pay', 'Promote her to tech lead', 'Let her go and hire'].entries()) await type(o.nth(i), v); });
  await next(600);
  await seg('w4', async () => { await sleep(1500); await ov('ring', '#wiz .wiz-choice', 6); await moveTo(wz('label:has(input[name="base"][value="now"])'), 0.25, 0.4); await sleep(4200);
    await ov('unring'); await type(wz('[data-w="period"]'), 'the next 2 years'); await sleep(600);
    await ov('ring', '#wiz .wiz-body > .wiz-note', 4); await sleep(1500); }, 600);
  await ov('unring'); await next(500);
  await seg('w5', async () => { await sleep(1000); await ways(['She accepts and stays', 'She accepts, but leaves within a year', 'She turns it down and leaves']); }, 500);
  await next(500);
  await seg('w6', async () => { await sleep(600); await pick('.sure.kind', 'none'); });
  await next(600);
  const pr = (f, i) => wz(`[data-w$=".p.${f}"]`).nth(i);
  await seg('w7', async () => { await ov('ring', '#wiz .wiz-ctab', 6); await sleep(2600); await ov('unring');
    await type(pr('lo', 0), '30'); await sleep(500); await type(pr('hi', 0), '60'); await sleep(600); await type(pr('ml', 0), '45'); }, 200);
  await seg('w8', async () => { await type(pr('lo', 1), '10'); await type(pr('hi', 1), '30'); await type(pr('ml', 1), '20');
    await ov('ring', '#wiz-left', 4); await moveTo(wz('#wiz-left'), 0.7, 0.5); await sleep(2600); await ov('unring'); await pick('.pev', 'expert'); }, 900);
  await next(600);
  await seg('w9', async () => { await sleep(1000); await ov('ring', '#wiz .wiz-seg', 5); await sleep(1600); await ov('unring');
    await money('.v', 'cost', '24k', '32k', '28k'); await ov('ring', '#wiz .wiz-ev', 5); await sleep(1500); await pick('.v.ev', 'data'); await sleep(400); await ov('unring'); }, 600);
  await next(600);
  key = DRY ? 0 : 28;
  await seg('w10', () => money('.v', 'cost', '50k', '95k', '67k', 'expert'), 400);
  await next(500);
  await seg('w11', () => money('.v', 'cost', '40k', '90k', '60k', 'expert'), 400);
  await next(500);
  await seg('w12', async () => { await ways(['She takes it and stays', 'She leaves anyway']); await next(500); await pick('.sure.kind', 'none'); }, 300);
  await next(600);
  await seg('w13', async () => { await sleep(500); await type(pr('lo', 0), '20'); await type(pr('hi', 0), '60'); await type(pr('ml', 0), '40'); await pick('.pev', 'guess'); }, 500);
  await next(500);
  await seg('w14', async () => { await money('.v', 'cost', '10k', '20k', '15k', 'data'); await next(500); await money('.v', 'cost', '45k', '95k', '63k', 'expert'); }, 400);
  await next(500);
  await seg('w15', async () => { await pick('.shape', 'sure'); await next(500); await money('.sure', 'cost', '40k', '90k', '60k', 'expert'); }, 400);
  await next(700);
  await seg('w16', async () => { await ov('ring', '#wiz .wiz-review', 6); await moveTo(wz('.wiz-review'), 0.5, 0.3);
    await p.evaluate(() => document.querySelector('#wiz-body').scrollBy({ top: 600, behavior: 'smooth' })); await sleep(2500);
    await p.evaluate(() => document.querySelector('#wiz-body').scrollTo({ top: 0, behavior: 'smooth' })); }, 800);
  await ov('unring');
  await click(wz('[data-wiz="next"]')); await sleep(1500); await ov('raise');

  // RESULTS
  if (DRY) for (const s of ['#v-head', '#v-flip', '#v-bars']) console.log(s, (await p.textContent(s)).replace(/\s+/g, ' ').trim().slice(0, 700));
  await seg('r1', async () => { await scrollTo(0); const fit = p.getByRole('button', { name: 'Fit', exact: true }); if (await fit.count()) await click(fit); await sleep(600);
    await moveTo(nm('Promote her to tech lead'), 0.5, 0.5); }, 600);
  await seg('r2', async () => { await ov('ring', '#v-head', 8); await moveTo(p.locator('#v-head'), 0.25, 0.15); }, 500);
  await seg('r3', async () => { await ov('unring'); await scrollToEl('#v-flip', 20); await ov('ring', '#v-flip li:nth-child(2)', 6); await moveTo(p.locator('#v-flip li').nth(1), 0.3, 0.3); }, 600);
  await seg('r4', async () => { await ov('unring'); await scrollToEl('#v-bars', 120); await ov('ring', '#v-bars', 6); await moveTo(p.locator('#v-bars'), 0.4, 0.3); }, 500);
  await seg('r5', async () => { await ov('unring'); await click(p.locator('#deep summary')); await sleep(700);
    if (DRY) console.log('#v-voi', (await p.textContent('#v-voi')).replace(/\s+/g, ' ').trim().slice(0, 600));
    await scrollToEl('#v-voi', 90); await ov('ring', '#v-voi', 6); await moveTo(p.locator('#v-voi'), 0.3, 0.2); }, 700);
  const takes = '.card:has(input.nm[value="She takes it and stays"])';
  await seg('r6', async () => { await ov('unring'); await scrollToEl(takes, 300); await ov('ring', takes, 6); await moveTo(p.locator(takes), 0.85, 0.35); await sleep(3500); await ov('unring'); }, 500);
  await seg('r7', async () => { await sleep(300); await ov('card', `<div class="c"><h1>Foldback</h1><p>Decision trees for people decisions</p><p>Free, and it runs entirely in your browser</p><div class="u">lstehlik2809.github.io/foldback</div></div>`); }, 3500);

  const total = (Date.now() - t0) / 1000;
  fs.writeFileSync(path.join(WORK, DRY ? 'timeline-dry.json' : 'timeline.json'), JSON.stringify({ total, segments: timeline }, null, 1));
  if (DRY) await p.screenshot({ path: path.join(WORK, 'dry-end.png') });
  console.log('total', total.toFixed(1), 's; errors', errs);
  if (!DRY) { await cdp.send('Page.stopScreencast'); await sleep(300);
    fs.writeFileSync(path.join(WORK, 'frames.json'), JSON.stringify({ t0: t0 / 1000, total, frames: frames.map(x => ({ f: x.f, t: +(x.t - t0 / 1000).toFixed(3) })) })); console.log('frames', frames.length); }
  await ctx.close(); await b.close();
})().catch(e => { console.error(e); process.exit(1); });
