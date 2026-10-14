/* test_frontend.js -- headless smoke test of the browser front end.
   Loads index.html in jsdom, stubs canvas + fetch, boots app.js and
   checks that every view renders without throwing.

   node test_frontend.js
*/
const fs = require('fs');
const path = require('path');
const { JSDOM, VirtualConsole } = require('jsdom');

const DIR = path.join(__dirname, 'web');
const BASE = 'http://127.0.0.1:8765';

const errors = [];
const vc = new VirtualConsole();
vc.on('jsdomError', e => errors.push('jsdomError: ' + (e.detail || e.message)));
vc.on('error', (...a) => errors.push('console.error: ' + a.join(' ')));

const html = fs.readFileSync(path.join(DIR, 'index.html'), 'utf8');
const dom = new JSDOM(html, {
  runScripts: 'outside-only', pretendToBeVisual: true,
  url: BASE + '/', virtualConsole: vc
});
const w = dom.window;

/* ---- canvas stub ------------------------------------------------------ */
const ctxStub = () => new Proxy({}, {
  get(t, p) {
    if (p in t) return t[p];
    if (p === 'canvas') return { width: 1200, height: 700 };
    return (...a) => (p === 'measureText' ? { width: 10 * String(a[0] || '').length } : undefined);
  },
  set(t, p, v) { t[p] = v; return true; }
});
w.HTMLCanvasElement.prototype.getContext = ctxStub;
Object.defineProperty(w.HTMLCanvasElement.prototype, 'clientWidth', { get: () => 1200 });
Object.defineProperty(w.HTMLCanvasElement.prototype, 'clientHeight', { get: () => 700 });
w.Element.prototype.getBoundingClientRect = function () {
  return { left: 0, top: 0, width: 1200, height: 700, right: 1200, bottom: 700, x: 0, y: 0 };
};

/* ---- fetch stub (relative -> absolute) -------------------------------- */
w.fetch = (u, o) => fetch(new URL(u, BASE), o);
w.performance = w.performance || { now: () => Date.now() };

/* ---- run the app ------------------------------------------------------ */
for (const f of ['netview.js', 'charts.js', 'dualmap.js', 'geoview.js',
                 'structvar.js', 'topics.js', 'citenetview.js',
                 'forecastview.js', 'kbcaview.js', 'app.js']) {
  try {
    w.eval(fs.readFileSync(path.join(DIR, f), 'utf8'));
  } catch (e) { errors.push('load ' + f + ': ' + e.stack); }
}

function txt(id) {
  const el = w.document.getElementById(id);
  return el ? el.textContent.trim().slice(0, 200) : '(missing)';
}
function count(id, sel) {
  const el = w.document.getElementById(id);
  return el ? el.querySelectorAll(sel).length : 0;
}

setTimeout(() => {
  const rep = [];
  rep.push('status      : ' + txt('status'));
  rep.push('statusRight : ' + txt('statusRight'));
  rep.push('fileList    : ' + count('fileList', 'input') + ' files');
  rep.push('cluster rows: ' + count('clusterBox', 'tbody tr'));
  rep.push('node rows   : ' + count('nodeBox', 'tbody tr'));
  rep.push('burst rows  : ' + count('burstBox', '.burst-row'));
  rep.push('overview    : ' + count('ovCards', '.card') + ' cards');
  rep.push('legend      : ' + count('netLegend', '.lg-i') + ' items');
  rep.push('log         : ' + txt('ovLog').split('\n').length + ' lines');
  console.log(rep.join('\n'));

  // exercise interactions
  try {
    w.document.querySelectorAll('.tab').forEach(t => t.click());
    const sel = w.document.getElementById('nd_cluster');
    sel.value = '1'; sel.dispatchEvent(new w.Event('change'));
    console.log('filter clu=1: node rows = ' + count('nodeBox', 'tbody tr'));
    sel.value = ''; sel.dispatchEvent(new w.Event('change'));
    const sb = w.document.getElementById('nd_search');
    sb.value = 'nocardia'; sb.dispatchEvent(new w.Event('input'));
    console.log('filter "nocardia": node rows = ' + count('nodeBox', 'tbody tr'));
    sb.value = 'liver'; sb.dispatchEvent(new w.Event('input'));
    w.document.getElementById('n_color').value = 'year';
    w.document.getElementById('n_color').dispatchEvent(new w.Event('change'));
    w.document.getElementById('z_mode').value = 'timezone';
    w.document.getElementById('z_mode').dispatchEvent(new w.Event('change'));
    const tr = w.document.querySelector('#clusterBox tbody tr');
    if (tr) tr.click();
    console.log('detail      : ' + txt('detailBody').slice(0, 90).replace(/\s+/g, ' '));
    console.log('after filter: node rows = ' + count('nodeBox', 'tbody tr'));
  } catch (e) { errors.push('interaction: ' + e.stack); }

  // the extended views are fetched lazily when their tab is opened
  setTimeout(() => {
    const ext = [];
    ext.push('dual info   : ' + txt('d_info'));
    ext.push('dual matrix : ' + count('dualMatrix', 'tbody tr') + ' rows');
    ext.push('geo info    : ' + txt('g_info'));
    ext.push('geo table   : ' + count('geoTable', 'tbody tr') + ' rows');
    ext.push('sv info     : ' + txt('s_info'));
    ext.push('sv table    : ' + count('svTable', 'tbody tr') + ' rows');
    ext.push('sv years    : ' + count('s_year', 'option') + ' options');
    console.log(ext.join('\n'));

    // interactions inside the extended views
    try {
      const gtr = w.document.querySelector('#geoTable tbody tr');
      if (gtr) gtr.click();
      const str = w.document.querySelector('#svTable tbody tr');
      if (str) str.click();
      const sy = w.document.getElementById('s_year');
      if (sy.options.length > 1) {
        sy.value = sy.options[1].value;
        sy.dispatchEvent(new w.Event('change'));
      }
      w.document.getElementById('g_color').value = 'cluster';
      w.document.getElementById('g_color').dispatchEvent(new w.Event('change'));
      console.log('sv detail   : ' + txt('detailBody').slice(0, 90).replace(/\s+/g, ' '));
    } catch (e) { errors.push('ext interaction: ' + e.stack); }

    // the round-3 views are the slowest (LDA / KBCA run server side), so give
    // them a long window before asserting anything
    setTimeout(() => {
      const r3 = [];
      r3.push('topics info : ' + txt('t_info'));
      r3.push('topics rows : ' + count('tTable', 'tbody tr'));
      r3.push('topics terms: ' + count('tTerms', '.term-bar'));
      r3.push('citenet info: ' + txt('cn_info'));
      r3.push('citenet rows: ' + count('cnTable', 'tbody tr'));
      r3.push('citenet card: ' + count('cnCards', '.card'));
      r3.push('forecast inf: ' + txt('f_info'));
      r3.push('forecast row: ' + count('fTable', 'tbody tr'));
      r3.push('kbca info   : ' + txt('k_info'));
      r3.push('kbca rows   : ' + count('kTable', 'tbody tr'));
      r3.push('kbca card   : ' + count('kCards', '.card'));
      console.log(r3.join('\n'));

      try {
        const ttr = w.document.querySelector('#tTable tbody tr');
        if (ttr) ttr.click();
        const ftr = w.document.querySelector('#fTable tbody tr');
        if (ftr) ftr.click();
        const ktr = w.document.querySelector('#kTable tbody tr');
        if (ktr) ktr.click();
      } catch (e) { errors.push('round3 interaction: ' + e.stack); }

      console.log('\n--- errors (' + errors.length + ') ---');
      errors.slice(0, 12).forEach(e => console.log(e.slice(0, 400)));
      process.exit(errors.length ? 1 : 0);
    }, 240000);
  }, 6000);
}, 3500);
