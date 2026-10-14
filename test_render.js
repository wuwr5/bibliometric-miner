/* test_render.js -- numeric check of the canvas renderers.
   Replays the real drawing code against a recording 2D context and checks
   that every emitted coordinate is finite and inside the canvas, so
   off-screen / NaN geometry cannot slip through unnoticed.

   node test_render.js
*/
const fs = require('fs');
const path = require('path');
const { JSDOM, VirtualConsole } = require('jsdom');

const DIR = path.join(__dirname, 'web');
const BASE = 'http://127.0.0.1:8765';
const errors = [];
const vc = new VirtualConsole();

const W = 1200, H = 700;
const dom = new JSDOM(fs.readFileSync(path.join(DIR, 'index.html'), 'utf8'), {
  runScripts: 'outside-only', pretendToBeVisual: true,
  url: BASE + '/', virtualConsole: vc
});
const w = dom.window;

/* ---- recording context ------------------------------------------------- */
function recorder(tag, stats) {
  const nums = [];
  const rec = {
    _t: tag,
    arc: (x, y, r) => { nums.push([x, y, r]); stats.arcs++; },
    moveTo: (x, y) => nums.push([x, y]),
    lineTo: (x, y) => nums.push([x, y]),
    quadraticCurveTo: (a, b, c, d) => nums.push([a, b, c, d]),
    bezierCurveTo: (a, b, c, d, e, f) => nums.push([a, b, c, d, e, f]),
    rect: (x, y, ww, hh) => nums.push([x, y, ww, hh]),
    fillRect: (x, y, ww, hh) => nums.push([x, y, ww, hh]),
    fillText: (t, x, y) => { nums.push([x, y]); stats.texts++; },
    strokeText: (t, x, y) => nums.push([x, y]),
    _nums: nums
  };
  const ctx = new Proxy(rec, {
    get(t, p) {
      if (p in t) return t[p];
      if (p === 'canvas') return { width: W, height: H };
      if (p === 'measureText') return s => ({ width: 6.2 * String(s || '').length });
      return () => undefined;
    },
    set(t, p, v) { t[p] = v; return true; }
  });
  return ctx;
}

const stats = { arcs: 0, texts: 0 };
w.HTMLCanvasElement.prototype.getContext = function () {
  if (!this._ctx) this._ctx = recorder(this.id, stats);
  return this._ctx;
};
Object.defineProperty(w.HTMLCanvasElement.prototype, 'clientWidth', { get: () => W });
Object.defineProperty(w.HTMLCanvasElement.prototype, 'clientHeight', { get: () => H });
w.Element.prototype.getBoundingClientRect = () =>
  ({ left: 0, top: 0, width: W, height: H, right: W, bottom: H, x: 0, y: 0 });
w.fetch = (u, o) => fetch(new URL(u, BASE), o);

for (const f of ['netview.js', 'charts.js', 'dualmap.js', 'geoview.js',
                 'structvar.js', 'topics.js', 'citenetview.js',
                 'forecastview.js', 'kbcaview.js', 'app.js']) {
  try { w.eval(fs.readFileSync(path.join(DIR, f), 'utf8')); }
  catch (e) { errors.push('load ' + f + ': ' + e.stack); }
}

function checkCanvas(id, margin) {
  const el = w.document.getElementById(id);
  if (!el || !el._ctx) return id + ': no drawing';
  let bad = 0, minX = 1e9, maxX = -1e9, minY = 1e9, maxY = -1e9, n = 0;
  for (const arr of el._ctx._nums) {
    for (const v of arr) {
      if (!isFinite(v)) { bad++; continue; }
      n++;
    }
    if (arr.length >= 2) {
      minX = Math.min(minX, arr[0]); maxX = Math.max(maxX, arr[0]);
      minY = Math.min(minY, arr[1]); maxY = Math.max(maxY, arr[1]);
    }
  }
  const m = margin === undefined ? 400 : margin;
  const out = minX < -m || maxX > W + m || minY < -m || maxY > H + m;
  return id + ': ' + el._ctx._nums.length + ' ops, ' + n + ' coords, nonfinite=' + bad +
    ', x[' + minX.toFixed(0) + ',' + maxX.toFixed(0) + '] y[' +
    minY.toFixed(0) + ',' + maxY.toFixed(0) + ']' + (out ? '  <-- OUT OF RANGE' : '');
}

setTimeout(() => {
  w.document.querySelectorAll('.tab').forEach(t => t.click());
  setTimeout(() => {
    ['netCanvas', 'zoneCanvas', 'dualCanvas', 'geoCanvas', 'svCanvas',
     'svYearCanvas', 'histCanvas'].forEach(id => console.log(checkCanvas(id)));
    console.log('arcs=' + stats.arcs + ' texts=' + stats.texts);
    // round-3 canvases need the long-running server analyses to finish
    setTimeout(() => {
      ['tYearCanvas', 'tBubbleCanvas', 'cnPathCanvas', 'cnHalfCanvas',
       'cnScatterCanvas', 'fDocCanvas', 'fSeriesCanvas', 'fEmCanvas',
       'kMantelCanvas', 'kNetCanvas', 'kScatterCanvas']
        .forEach(id => console.log(checkCanvas(id, 900)));
      console.log('arcs=' + stats.arcs + ' texts=' + stats.texts);
      console.log('errors: ' + errors.length);
      errors.slice(0, 5).forEach(e => console.log(e.slice(0, 300)));
      process.exit(errors.length ? 1 : 0);
    }, 240000);
  }, 7000);
}, 3500);
