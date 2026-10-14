/* netview.js -- canvas renderer for the bibliometric network.
   Force-directed layout, CiteSpace-style citation tree-rings, betweenness
   purple halo, timeline / timezone layouts, zoom-pan-drag interaction.  */
(function () {
'use strict';

/* ------------------------------- colour -------------------------------- */
const YEAR_STOPS = [
  [8, 48, 107], [25, 90, 160], [33, 138, 176], [64, 168, 130],
  [140, 197, 78], [243, 205, 63], [243, 152, 18], [226, 87, 30], [186, 30, 45]
];
const CLUSTER_COLORS = [
  '#e6194b', '#3cb44b', '#4363d8', '#f58231', '#911eb4', '#008080',
  '#9a6324', '#808000', '#e6beff', '#f032e6', '#008b8b', '#a9a9a9',
  '#800000', '#000075', '#ff9f40', '#2f4f4f'
];

function hex2rgb(h) {
  h = h.replace('#', '');
  return [parseInt(h.substr(0, 2), 16), parseInt(h.substr(2, 2), 16), parseInt(h.substr(4, 2), 16)];
}
function mix(a, b, t) {
  return [Math.round(a[0] + (b[0] - a[0]) * t),
          Math.round(a[1] + (b[1] - a[1]) * t),
          Math.round(a[2] + (b[2] - a[2]) * t)];
}
function rgbCss(c, a) {
  return a === undefined || a >= 1 ? 'rgb(' + c[0] + ',' + c[1] + ',' + c[2] + ')'
                                   : 'rgba(' + c[0] + ',' + c[1] + ',' + c[2] + ',' + a + ')';
}
function yearColor(y, y0, y1) {
  if (y1 <= y0) return rgbCss(YEAR_STOPS[0]);
  let t = (y - y0) / (y1 - y0);
  t = Math.max(0, Math.min(1, t));
  const seg = (YEAR_STOPS.length - 1) * t;
  const i = Math.min(YEAR_STOPS.length - 2, Math.floor(seg));
  return rgbCss(mix(YEAR_STOPS[i], YEAR_STOPS[i + 1], seg - i));
}
function clusterColor(i) { return CLUSTER_COLORS[i % CLUSTER_COLORS.length]; }

/* -------------------------------- view --------------------------------- */
class NetView {
  constructor(canvas, wrap, tip, legend) {
    this.cv = canvas; this.wrap = wrap; this.tip = tip; this.legend = legend;
    this.ctx = canvas.getContext('2d');
    this.dpr = window.devicePixelRatio || 1;
    this.nodes = []; this.edges = []; this.clusters = [];
    this.pos = [];            // {x,y,vx,vy,fixed}
    this.opt = {
      mode: 'force', showLabels: true, showRings: true, showCentrality: true,
      colorBy: 'cluster', labelTop: 40, scale: 1, labelField: 'label'
    };
    this.tf = { k: 1, x: 0, y: 0 };
    this.hover = -1; this.selected = -1;
    this.running = false; this.alpha = 1;
    this.onSelect = null;
    this._bind();
    window.addEventListener('resize', () => this.resize());
  }

  /* ---------------------------- data ---------------------------------- */
  setData(res) {
    this.res = res;
    this.nodes = res.nodes || [];
    this.edges = res.edges || [];
    this.clusters = res.clusters || [];
    this.maxCount = Math.max(1, ...this.nodes.map(n => n.count));
    this.maxBC = Math.max(1e-9, ...this.nodes.map(n => n.centrality));
    this.maxBurst = Math.max(1e-9, ...this.nodes.map(n => n.burst ? n.burst.strength : 0));
    this.y0 = res.summary ? res.summary.year_min : 2000;
    this.y1 = res.summary ? res.summary.year_max : 2024;
    this.adj = this.nodes.map(() => []);
    for (const e of this.edges) {
      this.adj[e.source].push({ i: e.target, w: e.weight });
      this.adj[e.target].push({ i: e.source, w: e.weight });
    }
    this.labelOrder = this.nodes.map((n, i) => i)
      .sort((a, b) => this.nodes[b].count - this.nodes[a].count);
    this.layout(true);
    this.fit();
    this.drawLegend();
  }

  setOptions(o, relayout) {
    const prevMode = this.opt.mode;
    Object.assign(this.opt, o);
    if (relayout || prevMode !== this.opt.mode) this.layout(true); else this.draw();
    this.drawLegend();
  }

  /* --------------------------- layout --------------------------------- */
  layout(reset) {
    const n = this.nodes.length;
    if (!n) return;
    const W = 1400, H = 900;
    if (reset || this.pos.length !== n) {
      this.pos = this.nodes.map((nd, i) => ({
        x: (Math.random() - 0.5) * W, y: (Math.random() - 0.5) * H, vx: 0, vy: 0
      }));
    }
    if (this.opt.mode === 'force') {
      this.alpha = 1;
    } else {
      this._layoutTime();
      this._relax(60);
    }
    this.draw();
  }

  _layoutTime() {
    const n = this.nodes.length;
    const y0 = this.y0, y1 = this.y1;
    const xOf = nd => 120 + (nd.first_year - y0) / Math.max(1, y1 - y0) * 1300;
    if (this.opt.mode === 'timezone') {
      // each year is a vertical column, strongest node in the middle
      const byYear = new Map();
      this.nodes.forEach((nd, i) => {
        const y = nd.first_year;
        if (!byYear.has(y)) byYear.set(y, []);
        byYear.get(y).push(i);
      });
      for (const [y, ids] of byYear) {
        ids.sort((a, b) => this.nodes[b].count - this.nodes[a].count);
        const gap = 26;
        const mid = (ids.length - 1) / 2;
        ids.forEach((id, k) => {
          const x = 120 + (y - y0) / Math.max(1, y1 - y0) * 1300;
          this.pos[id].x = x;
          this.pos[id].y = (k - mid) * gap * -1 + (k % 2 ? 9 : -9);
        });
      }
    } else {
      // timeline: horizontal band per cluster
      const bands = [];
      let acc = 0;
      this.clusters.forEach(c => {
        const h = Math.max(70, Math.min(320, c.size * 7 + 40));
        bands.push({ id: c.id, y: acc, h: h, label: c.label, size: c.size });
        acc += h + 14;
      });
      this.bands = bands;
      const total = Math.max(1, acc);
      this.nodes.forEach((nd, i) => {
        const b = bands.find(b => b.id === nd.cluster) || bands[0];
        if (!b) { this.pos[i].x = xOf(nd); this.pos[i].y = 0; return; }
        this.pos[i].x = xOf(nd);
        const r = this.radius(this.nodes[i]);
        this.pos[i].y = b.y + b.h / 2 + (Math.random() - 0.5) * (b.h - 2 * r - 6);
      });
      this.bandTotal = total;
    }
  }

  _relax(iters) {
    const n = this.nodes.length;
    for (let it = 0; it < iters; it++) {
      // simple pairwise y-separation for nodes that overlap in x
      for (let i = 0; i < n; i++) {
        for (let j = i + 1; j < n; j++) {
          const a = this.pos[i], b = this.pos[j];
          const ra = this.radius(this.nodes[i]) + 3, rb = this.radius(this.nodes[j]) + 3;
          const dx = a.x - b.x, dy = a.y - b.y;
          const need = ra + rb;
          const d2 = dx * dx + dy * dy;
          if (d2 > need * need || d2 < 1e-6) continue;
          const d = Math.sqrt(d2);
          const push = (need - d) * 0.5;
          const uy = dy / d;
          a.y += uy * push; b.y -= uy * push;
          if (this.opt.mode === 'timeline') {
            a.x += (dx / d) * push * 0.15;
            b.x -= (dx / d) * push * 0.15;
          }
        }
      }
    }
  }

  /* ------------------------- force iteration --------------------------- */
  step() {
    const n = this.nodes.length;
    if (!n) return;
    const P = this.pos, E = this.edges;
    const k = Math.sqrt((1600 * 1000) / Math.max(1, n)) * 0.9;
    const A = this.alpha;
    for (let i = 0; i < n; i++) { P[i].fx = 0; P[i].fy = 0; }
    // repulsion (O(n^2); fine up to ~1500 nodes)
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        let dx = P[i].x - P[j].x, dy = P[i].y - P[j].y;
        let d2 = dx * dx + dy * dy;
        if (d2 < 1e-4) { dx = (Math.random() - 0.5) * 2; dy = (Math.random() - 0.5) * 2; d2 = 4; }
        if (d2 > 640000) continue;              // cut-off 800px
        const d = Math.sqrt(d2);
        const f = (k * k) / d;
        const ux = dx / d, uy = dy / d;
        const wi = 1 + Math.sqrt(this.nodes[i].count / this.maxCount) * 0.8;
        const wj = 1 + Math.sqrt(this.nodes[j].count / this.maxCount) * 0.8;
        P[i].fx += ux * f * wj; P[i].fy += uy * f * wj;
        P[j].fx -= ux * f * wi; P[j].fy -= uy * f * wi;
      }
    }
    // attraction along edges
    for (const e of E) {
      const a = P[e.source], b = P[e.target];
      const dx = a.x - b.x, dy = a.y - b.y;
      const d = Math.sqrt(dx * dx + dy * dy) || 1e-6;
      const w = 0.25 + 0.75 * Math.min(1, e.weight / 6);
      const f = (d / k) * w * 1.6;
      const ux = dx / d, uy = dy / d;
      a.fx -= ux * f; a.fy -= uy * f;
      b.fx += ux * f; b.fy += uy * f;
    }
    // gravity + integrate
    for (let i = 0; i < n; i++) {
      const p = P[i];
      p.fx -= p.x * 0.0016 * (1 + this.nodes[i].count / this.maxCount);
      p.fy -= p.y * 0.0016 * (1 + this.nodes[i].count / this.maxCount);
      p.vx = (p.vx + p.fx * A) * 0.72;
      p.vy = (p.vy + p.fy * A) * 0.72;
      p.x += Math.max(-28, Math.min(28, p.vx));
      p.y += Math.max(-28, Math.min(28, p.vy));
    }
    this.alpha = Math.max(0.02, this.alpha * 0.992);
  }

  /* ----------------------------- drawing ------------------------------- */
  resize() {
    const r = this.wrap.getBoundingClientRect();
    this.cv.width = Math.max(1, Math.floor(r.width * this.dpr));
    this.cv.height = Math.max(1, Math.floor(r.height * this.dpr));
    this.w = r.width; this.h = r.height;
    this.draw();
  }

  radius(nd) {
    const base = 3.4 + 15 * Math.sqrt(nd.count / this.maxCount);
    return base * (this.opt.scale || 1);
  }

  colorOf(nd) {
    if (this.opt.colorBy === 'year') return yearColor(nd.first_year, this.y0, this.y1);
    if (this.opt.colorBy === 'burst') {
      const s = nd.burst ? nd.burst.strength / this.maxBurst : 0;
      if (!s) return 'rgba(150,158,170,.85)';
      return rgbCss(mix([255, 237, 213], [185, 28, 28], Math.min(1, s * 1.4)));
    }
    return clusterColor(nd.cluster);
  }

  w2s(x, y) { return [x * this.tf.k + this.tf.x, y * this.tf.k + this.tf.y]; }
  s2w(x, y) { return [(x - this.tf.x) / this.tf.k, (y - this.tf.y) / this.tf.k]; }

  fit() {
    const r = this.wrap.getBoundingClientRect();
    this.w = r.width; this.h = r.height;
    this.cv.width = Math.max(1, Math.floor(r.width * this.dpr));
    this.cv.height = Math.max(1, Math.floor(r.height * this.dpr));
    if (!this.nodes.length) return;
    let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
    for (let i = 0; i < this.nodes.length; i++) {
      const p = this.pos[i], rr = this.radius(this.nodes[i]) + 6;
      x0 = Math.min(x0, p.x - rr); y0 = Math.min(y0, p.y - rr);
      x1 = Math.max(x1, p.x + rr); y1 = Math.max(y1, p.y + rr);
    }
    const pad = 46;
    const kx = (this.w - pad * 2) / Math.max(1, x1 - x0);
    const ky = (this.h - pad * 2) / Math.max(1, y1 - y0);
    this.tf.k = Math.max(0.05, Math.min(3.2, Math.min(kx, ky)));
    this.tf.x = (this.w - (x1 + x0) * this.tf.k) / 2;
    this.tf.y = (this.h - (y1 + y0) * this.tf.k) / 2;
    this.draw();
  }

  draw() {
    const ctx = this.ctx;
    if (!this.cv.width) this.resize();
    ctx.save();
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.clearRect(0, 0, this.w, this.h);
    ctx.translate(this.tf.x, this.tf.y);
    ctx.scale(this.tf.k, this.tf.k);

    if (this.opt.mode === 'timeline') this._drawBands(ctx);
    if (this.opt.mode !== 'force') this._drawTimeAxis(ctx);

    // edges
    const hi = this.hover >= 0 ? new Set(this.adj[this.hover].map(a => a.i)) : null;
    ctx.lineCap = 'round';
    for (const e of this.edges) {
      const a = this.pos[e.source], b = this.pos[e.target];
      if (!a || !b) continue;
      let on = false;
      if (hi) on = (e.source === this.hover || e.target === this.hover);
      ctx.beginPath();
      ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y);
      if (on) { ctx.strokeStyle = 'rgba(200,40,60,.85)'; ctx.lineWidth = 1.6 / this.tf.k; }
      else if (hi) { ctx.strokeStyle = 'rgba(150,160,175,.13)'; ctx.lineWidth = 0.5 / this.tf.k; }
      else { ctx.strokeStyle = 'rgba(130,142,160,.34)'; ctx.lineWidth = (0.4 + Math.min(2.2, Math.log(1 + e.weight) * 0.55)) / this.tf.k; }
      ctx.stroke();
    }

    // nodes
    for (let i = 0; i < this.nodes.length; i++) this._drawNode(ctx, i, hi);
    // labels
    if (this.opt.showLabels) this._drawLabels(ctx, hi);
    ctx.restore();
  }

  _drawNode(ctx, i, hi) {
    const nd = this.nodes[i], p = this.pos[i];
    const R = this.radius(nd);
    const dim = hi && i !== this.hover && !hi.has(i);
    ctx.globalAlpha = dim ? 0.22 : 1;

    if (this.opt.showRings && nd.years) {
      const ys = Object.keys(nd.years).map(Number).sort((a, b) => a - b);
      if (ys.length > 1) {
        const total = ys.reduce((s, y) => s + nd.years[y], 0) || 1;
        let cum = total;
        // draw from the outermost (newest) ring inwards
        for (let k = ys.length - 1; k >= 0; k--) {
          const r = R * Math.sqrt(cum / total);
          ctx.beginPath(); ctx.arc(p.x, p.y, r, 0, 6.2832);
          ctx.fillStyle = yearColor(ys[k], this.y0, this.y1);
          ctx.fill();
          cum -= nd.years[ys[k]] || 0;
        }
      } else {
        ctx.beginPath(); ctx.arc(p.x, p.y, R, 0, 6.2832);
        ctx.fillStyle = this.colorOf(nd); ctx.fill();
      }
    } else {
      ctx.beginPath(); ctx.arc(p.x, p.y, R, 0, 6.2832);
      ctx.fillStyle = this.colorOf(nd); ctx.fill();
    }
    // border
    ctx.beginPath(); ctx.arc(p.x, p.y, R, 0, 6.2832);
    ctx.strokeStyle = 'rgba(35,45,60,.35)'; ctx.lineWidth = 0.6 / this.tf.k; ctx.stroke();

    // betweenness halo (CiteSpace purple ring)
    if (this.opt.showCentrality && nd.centrality > 0.02) {
      const w = 1 + 7 * Math.sqrt(nd.centrality / this.maxBC);
      ctx.beginPath(); ctx.arc(p.x, p.y, R + w / 2 + 1.2, 0, 6.2832);
      ctx.strokeStyle = 'rgba(126,34,206,' + Math.min(0.85, 0.25 + nd.centrality / this.maxBC) + ')';
      ctx.lineWidth = w / this.tf.k; ctx.stroke();
    }
    // burst marker
    if (nd.burst && nd.burst.strength > 0) {
      ctx.beginPath(); ctx.arc(p.x, p.y, R + 4.5, 0, 6.2832);
      ctx.strokeStyle = 'rgba(220,38,38,.9)';
      ctx.setLineDash([3 / this.tf.k, 2.5 / this.tf.k]);
      ctx.lineWidth = 1.4 / this.tf.k; ctx.stroke(); ctx.setLineDash([]);
    }
    if (i === this.selected) {
      ctx.beginPath(); ctx.arc(p.x, p.y, R + 6, 0, 6.2832);
      ctx.strokeStyle = '#111827'; ctx.lineWidth = 1.8 / this.tf.k; ctx.stroke();
    }
    ctx.globalAlpha = 1;
  }

  _drawLabels(ctx, hi) {
    const top = this.opt.labelTop || 0;
    const set = new Set(this.labelOrder.slice(0, top));
    if (hi) for (const j of hi) set.add(j);
    if (this.selected >= 0) set.add(this.selected);
    ctx.font = (11.5 / this.tf.k).toFixed(1) + 'px "Segoe UI","Microsoft YaHei",sans-serif';
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.lineJoin = 'round';
    for (const i of set) {
      const nd = this.nodes[i], p = this.pos[i];
      const R = this.radius(nd);
      const txt = nd.label.length > 42 ? nd.label.substr(0, 40) + '…' : nd.label;
      const y = p.y + R + (10 / this.tf.k);
      ctx.strokeStyle = 'rgba(255,255,255,.95)';
      ctx.lineWidth = 3 / this.tf.k;
      ctx.strokeText(txt, p.x, y);
      ctx.fillStyle = i === this.selected ? '#111827' : '#26303d';
      ctx.fillText(txt, p.x, y);
    }
  }

  _drawTimeAxis(ctx) {
    const y0 = this.y0, y1 = this.y1;
    let x0 = 1e9, x1 = -1e9, ya = 1e9, yb = -1e9;
    for (let i = 0; i < this.nodes.length; i++) {
      const p = this.pos[i], r = this.radius(this.nodes[i]);
      x0 = Math.min(x0, p.x); x1 = Math.max(x1, p.x);
      ya = Math.min(ya, p.y - r); yb = Math.max(yb, p.y + r);
    }
    const axisY = yb + 40;
    ctx.strokeStyle = 'rgba(120,132,150,.55)'; ctx.lineWidth = 1 / this.tf.k;
    ctx.beginPath(); ctx.moveTo(x0 - 20, axisY); ctx.lineTo(x1 + 60, axisY); ctx.stroke();
    const stepY = Math.max(1, Math.round((y1 - y0) / 12));
    ctx.font = (11 / this.tf.k).toFixed(1) + 'px sans-serif';
    ctx.fillStyle = '#6b7686'; ctx.textAlign = 'center'; ctx.textBaseline = 'top';
    for (let y = y0; y <= y1; y += stepY) {
      const x = 120 + (y - y0) / Math.max(1, y1 - y0) * 1300;
      ctx.beginPath(); ctx.moveTo(x, axisY); ctx.lineTo(x, axisY + 6 / this.tf.k); ctx.stroke();
      ctx.fillText(String(y), x, axisY + 9 / this.tf.k);
    }
    // vertical gridlines
    ctx.strokeStyle = 'rgba(160,170,185,.22)';
    for (let y = y0; y <= y1; y += stepY) {
      const x = 120 + (y - y0) / Math.max(1, y1 - y0) * 1300;
      ctx.beginPath(); ctx.moveTo(x, ya - 20); ctx.lineTo(x, axisY); ctx.stroke();
    }
  }

  _drawBands(ctx) {
    if (!this.bands) return;
    ctx.font = (12 / this.tf.k).toFixed(1) + 'px "Segoe UI","Microsoft YaHei",sans-serif';
    ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
    this.bands.forEach((b, i) => {
      ctx.fillStyle = i % 2 ? 'rgba(240,244,250,.55)' : 'rgba(247,249,252,.75)';
      ctx.fillRect(80, b.y, 1420, b.h);
      ctx.fillStyle = clusterColor(b.id);
      ctx.fillRect(80, b.y, 5, b.h);
      ctx.strokeStyle = 'rgba(120,132,150,.25)'; ctx.lineWidth = 1 / this.tf.k;
      ctx.beginPath(); ctx.moveTo(80, b.y + b.h); ctx.lineTo(1500, b.y + b.h); ctx.stroke();
      const t = '#' + b.id + '  ' + b.label + '  (n=' + b.size + ')';
      ctx.fillStyle = '#39424f';
      ctx.fillText(t.length > 60 ? t.substr(0, 58) + '…' : t, 92, b.y + 13 / this.tf.k);
    });
  }

  drawLegend() {
    if (!this.legend) return;
    let html = '';
    if (this.opt.colorBy === 'cluster') {
      html += '<div class="lg-t">聚类（按规模排序）</div>';
      this.clusters.slice(0, 14).forEach(c => {
        html += '<div class="lg-i"><span class="sw" style="background:' +
          clusterColor(c.id) + '"></span>#' + c.id + ' ' +
          (c.label || '').slice(0, 34) + ' <span class="muted">(' + c.size + ')</span></div>';
      });
    } else if (this.opt.colorBy === 'year' || this.opt.showRings) {
      html += '<div class="lg-t">年轮色阶</div><div class="yr"><span>' + this.y0 +
        '</span><span class="yrbar" style="background:linear-gradient(90deg,' +
        YEAR_STOPS.map((c, i) => rgbCss(c) + ' ' + (i / (YEAR_STOPS.length - 1) * 100) + '%').join(',') +
        ')"></span><span>' + this.y1 + '</span></div>';
    }
    html += '<div class="lg-t" style="margin-top:8px">图例</div>' +
      '<div class="lg-i"><span class="sw" style="background:#7e22ce"></span>外圈紫色 = 中介中心性</div>' +
      '<div class="lg-i"><span class="sw" style="background:#dc2626;height:3px;border:0"></span>红色虚线圈 = 突现</div>' +
      '<div class="lg-i"><span class="sw" style="background:#8b96a5;border-radius:50%"></span>圆面积 ∝ 频次</div>';
    this.legend.innerHTML = html;
  }

  /* --------------------------- interaction ----------------------------- */
  _bind() {
    const cv = this.cv;
    let drag = null;
    cv.addEventListener('mousedown', e => {
      const r = cv.getBoundingClientRect();
      const x = e.clientX - r.left, y = e.clientY - r.top;
      const hit = this._hit(x, y);
      if (hit >= 0) {
        drag = { node: hit, x: x, y: y };
        this.selected = hit;
        if (this.onSelect) this.onSelect(this.nodes[hit], hit);
      } else {
        drag = { pan: true, x: x, y: y, tx: this.tf.x, ty: this.tf.y };
      }
      this.draw();
    });
    window.addEventListener('mouseup', () => { drag = null; });
    cv.addEventListener('mousemove', e => {
      const r = cv.getBoundingClientRect();
      const x = e.clientX - r.left, y = e.clientY - r.top;
      if (drag && drag.pan) {
        this.tf.x = drag.tx + (x - drag.x); this.tf.y = drag.ty + (y - drag.y);
        this.draw(); return;
      }
      if (drag && drag.node >= 0) {
        const w = this.s2w(x, y);
        this.pos[drag.node].x = w[0]; this.pos[drag.node].y = w[1];
        this.pos[drag.node].vx = this.pos[drag.node].vy = 0;
        this.draw(); return;
      }
      const hit = this._hit(x, y);
      if (hit !== this.hover) {
        this.hover = hit;
        this.draw();
        if (hit >= 0) this._tip(e, this.nodes[hit]);
        else if (this.tip) this.tip.style.opacity = 0;
      } else if (hit >= 0) {
        this._tip(e, this.nodes[hit]);
      }
    });
    cv.addEventListener('mouseleave', () => {
      this.hover = -1; if (this.tip) this.tip.style.opacity = 0; this.draw();
    });
    cv.addEventListener('wheel', e => {
      e.preventDefault();
      const r = cv.getBoundingClientRect();
      const x = e.clientX - r.left, y = e.clientY - r.top;
      const f = e.deltaY < 0 ? 1.12 : 1 / 1.12;
      const nk = Math.max(0.05, Math.min(6, this.tf.k * f));
      this.tf.x = x - (x - this.tf.x) * (nk / this.tf.k);
      this.tf.y = y - (y - this.tf.y) * (nk / this.tf.k);
      this.tf.k = nk;
      this.draw();
    }, { passive: false });
    cv.addEventListener('dblclick', () => this.fit());
  }

  _tip(e, nd) {
    if (!this.tip) return;
    const r = this.wrap.getBoundingClientRect();
    const b = nd.burst;
    let h = '<b>' + nd.label + '</b><br>' +
      '频次 ' + nd.count + ' · 首现 ' + nd.first_year + ' · 度 ' + nd.degree + '<br>' +
      '中介中心性 ' + nd.centrality.toFixed(4) + ' · 聚类 #' + nd.cluster;
    if (b) h += '<br>突现 ' + b.begin + '–' + b.end + ' · 强度 ' + b.strength;
    this.tip.innerHTML = h;
    this.tip.style.opacity = 1;
    const tw = this.tip.offsetWidth, th = this.tip.offsetHeight;
    let L = e.clientX - r.left + 14, T = e.clientY - r.top + 14;
    if (L + tw > r.width - 8) L = r.width - tw - 8;
    if (T + th > r.height - 8) T = r.height - th - 8;
    this.tip.style.left = L + 'px'; this.tip.style.top = T + 'px';
  }

  _hit(x, y) {
    const w = this.s2w(x, y);
    for (let i = this.nodes.length - 1; i >= 0; i--) {
      const p = this.pos[i];
      if (!p) continue;
      const r = this.radius(this.nodes[i]) + 3 / this.tf.k;
      if ((p.x - w[0]) * (p.x - w[0]) + (p.y - w[1]) * (p.y - w[1]) <= r * r) return i;
    }
    return -1;
  }

  /* ----------------------------- animation ----------------------------- */
  start() {
    if (this.running) return;
    this.running = true;
    const loop = () => {
      if (!this.running) return;
      if (this.opt.mode === 'force' && this.alpha > 0.03) { this.step(); this.draw(); }
      requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
  }
  pause() { this.running = false; }

  toPNG() {
    const c = document.createElement('canvas');
    c.width = this.cv.width; c.height = this.cv.height;
    const x = c.getContext('2d');
    x.fillStyle = '#ffffff'; x.fillRect(0, 0, c.width, c.height);
    x.drawImage(this.cv, 0, 0);
    return c.toDataURL('image/png');
  }
}

window.NetView = NetView;
window.vizColors = { clusterColor: clusterColor, yearColor: yearColor,
  rgbCss: rgbCss, CLUSTER_COLORS: CLUSTER_COLORS };
})();
