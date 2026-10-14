/* geoview.js -- country collaboration network drawn over a world map.
   Equirectangular projection, Natural Earth 110m base map shipped as
   assets/world_110m.json (see tools_topo2geo.py).                        */
(function () {
'use strict';

const CLUSTER_COLORS = (window.vizColors && window.vizColors.CLUSTER_COLORS) ||
  ['#e6194b', '#3cb44b', '#4363d8', '#f58231', '#911eb4', '#008080',
   '#9a6324', '#808000', '#e6beff', '#f032e6', '#008b8b', '#a9a9a9',
   '#800000', '#000075', '#ff9f40', '#2f4f4f'];

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"]/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

let _worldPromise = null;
function loadWorld() {
  if (!_worldPromise) {
    _worldPromise = fetch('/assets/world_110m.json')
      .then(r => r.json())
      .catch(() => null);
  }
  return _worldPromise;
}

class GeoView {
  constructor(canvas, wrap, tip, legend) {
    this.cv = canvas; this.wrap = wrap; this.tip = tip; this.legend = legend;
    this.ctx = canvas.getContext('2d');
    this.dpr = window.devicePixelRatio || 1;
    this.nodes = []; this.edges = []; this.clusters = [];
    this.tf = { k: 1, x: 0, y: 0 };
    this.clipLat = [-58, 84];
    this.opt = { showLabels: true, labelTop: 14, showGraticule: true,
                 scale: 1, minWeight: 1, colorBy: 'count' };
    this.hover = -1; this.selected = -1;
    this.onSelect = null;
    this._bind();
    window.addEventListener('resize', () => { this.resize(); this.fit(); this.draw(); });
  }

  setData(res) {
    this.res = res;
    this.nodes = res.nodes || [];
    this.edges = res.edges || [];
    this.clusters = res.clusters || [];
    this.maxCount = Math.max(1, ...this.nodes.map(n => n.count));
    this.maxW = Math.max(1, ...this.edges.map(e => e.weight));
    this.years = this.nodes.map(n => n.mean_year).filter(Boolean);
    this.y0 = Math.min(...this.years) || 2000;
    this.y1 = Math.max(...this.years) || 2025;
    this.labelOrder = this.nodes.map((n, i) => i)
      .sort((a, b) => this.nodes[b].count - this.nodes[a].count);
    this.resize();
    this.fit();
    this.drawLegend();
    const self = this;
    loadWorld().then(w => { self.world = w; self.draw(); });
    this.draw();
  }

  setOptions(o) { Object.assign(this.opt, o); this.draw(); }

  resize() {
    const w = this.wrap.clientWidth || 900, h = this.wrap.clientHeight || 560;
    this.w = w; this.h = h;
    this.cv.width = Math.floor(w * this.dpr);
    this.cv.height = Math.floor(h * this.dpr);
    this.cv.style.width = w + 'px';
    this.cv.style.height = h + 'px';
  }

  /* base scale: fit lon [-180,180] / lat [clip] into the canvas */
  _baseScale() {
    const latSpan = this.clipLat[1] - this.clipLat[0];
    return Math.min(this.w / 360.0, this.h / latSpan);
  }
  /* total scale in px per degree (base scale x zoom) */
  _s() { return this._baseScale() * this.tf.k; }
  fit() {
    const s = this._baseScale();
    const latSpan = this.clipLat[1] - this.clipLat[0];
    this.tf.k = 1;
    this.tf.x = (this.w - 360 * s) / 2;
    this.tf.y = (this.h - latSpan * s) / 2;
    this.draw();
  }
  _proj(lon, lat) {
    const s = this._s();
    const x = this.tf.x + (lon + 180) * s;
    const y = this.tf.y + (this.clipLat[1] - lat) * s;
    return [x, y];
  }

  draw() {
    const ctx = this.ctx;
    if (!this.w) this.resize();
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.clearRect(0, 0, this.w, this.h);

    // ocean
    ctx.fillStyle = '#f7f9fc';
    ctx.fillRect(0, 0, this.w, this.h);

    if (this.opt.showGraticule) this._graticule(ctx);
    if (this.world) this._land(ctx);
    if (!this.nodes.length) {
      ctx.fillStyle = '#8b96a5';
      ctx.font = '13px sans-serif'; ctx.textAlign = 'center';
      ctx.fillText('暂无地理数据', this.w / 2, this.h / 2);
      return;
    }

    // ---- collaboration edges -------------------------------------------
    const shown = this.edges.filter(e => e.weight >= this.opt.minWeight);
    ctx.save();
    ctx.lineCap = 'round';
    for (const e of shown) {
      const a = this.nodes[e.source], b = this.nodes[e.target];
      if (!a || !b || !a.located || !b.located) continue;
      const [x1, y1] = this._proj(a.lon, a.lat);
      const [x2, y2] = this._proj(b.lon, b.lat);
      const mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
      const dx = x2 - x1, dy = y2 - y1;
      const len = Math.sqrt(dx * dx + dy * dy) || 1;
      const off = Math.min(70, len * 0.18);
      ctx.beginPath();
      ctx.moveTo(x1, y1);
      ctx.quadraticCurveTo(mx - dy / len * off, my + dx / len * off, x2, y2);
      const t = Math.log(1 + e.weight) / Math.log(1 + this.maxW);
      ctx.lineWidth = 0.4 + 3.2 * t;
      ctx.strokeStyle = 'rgba(37,99,235,' + (0.10 + 0.5 * t).toFixed(3) + ')';
      ctx.stroke();
    }
    ctx.restore();

    // ---- nodes ----------------------------------------------------------
    for (let i = 0; i < this.nodes.length; i++) {
      const n = this.nodes[i];
      if (!n.located) continue;
      const [x, y] = this._proj(n.lon, n.lat);
      const rel = Math.sqrt(n.count / this.maxCount);
      const r = (2.6 + 12 * rel) * this.opt.scale;
      const hot = (i === this.hover || i === this.selected);
      let fill;
      if (this.opt.colorBy === 'cluster') {
        fill = CLUSTER_COLORS[n.cluster % CLUSTER_COLORS.length];
      } else if (this.opt.colorBy === 'year' && n.mean_year) {
        fill = window.vizColors.yearColor(n.mean_year, this.y0, this.y1);
      } else {
        const t = rel;
        fill = 'rgba(' + Math.round(230 - 150 * t) + ',' +
          Math.round(90 - 40 * t) + ',' + Math.round(60 - 20 * t) + ',0.92)';
      }
      ctx.beginPath();
      ctx.arc(x, y, r, 0, Math.PI * 2);
      ctx.globalAlpha = hot ? 1 : 0.86;
      ctx.fillStyle = fill; ctx.fill();
      ctx.globalAlpha = 1;
      ctx.lineWidth = hot ? 2.2 : 0.9;
      ctx.strokeStyle = hot ? '#111827' : 'rgba(255,255,255,.92)';
      ctx.stroke();
      n._px = x; n._py = y; n._pr = r;
    }

    // ---- labels ----------------------------------------------------------
    if (this.opt.showLabels) {
      ctx.font = '11px -apple-system,"Segoe UI","Microsoft YaHei",sans-serif';
      ctx.textBaseline = 'middle';
      for (const i of this.labelOrder.slice(0, this.opt.labelTop)) {
        const n = this.nodes[i];
        if (!n.located || n._px === undefined) continue;
        const txt = n.name;
        const wT = ctx.measureText(txt).width;
        let x = n._px + n._pr + 4, align = 'left';
        if (x + wT > this.w - 4) { x = n._px - n._pr - 4; align = 'right'; }
        ctx.lineWidth = 3; ctx.strokeStyle = 'rgba(255,255,255,.95)';
        ctx.strokeText(txt, x, n._py);
        ctx.fillStyle = '#1b2430'; ctx.textAlign = align;
        ctx.fillText(txt, x, n._py);
      }
    }
  }

  _graticule(ctx) {
    ctx.save();
    ctx.strokeStyle = '#e6eaf1'; ctx.lineWidth = 1;
    for (let lon = -180; lon <= 180; lon += 30) {
      const [x, y1] = this._proj(lon, this.clipLat[0]);
      const [, y2] = this._proj(lon, this.clipLat[1]);
      ctx.beginPath(); ctx.moveTo(x, y1); ctx.lineTo(x, y2); ctx.stroke();
    }
    for (let lat = -60; lat <= 80; lat += 30) {
      const [x1, y] = this._proj(-180, lat);
      const [x2] = this._proj(180, lat);
      ctx.beginPath(); ctx.moveTo(x1, y); ctx.lineTo(x2, y); ctx.stroke();
    }
    ctx.restore();
  }

  _land(ctx) {
    const s = this._s();
    ctx.save();
    ctx.fillStyle = '#e4e9f0';
    ctx.strokeStyle = '#c3ccd8';
    ctx.lineWidth = 0.6;
    for (const c of this.world.countries || []) {
      for (const ring of c.rings || []) {
        if (ring.length < 3) continue;
        ctx.beginPath();
        for (let i = 0; i < ring.length; i++) {
          const x = this.tf.x + (ring[i][0] + 180) * s;
          const y = this.tf.y + (this.clipLat[1] - ring[i][1]) * s;
          if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }
        ctx.closePath();
        ctx.fill();
        ctx.stroke();
      }
    }
    ctx.restore();
  }

  drawLegend() {
    if (!this.legend || !this.res) return;
    let h = '<div class="lg-t">国家 / 地区 (' + this.nodes.length + ')</div>';
    if (this.opt.colorBy === 'cluster') {
      h += this.clusters.map(c => '<div class="lg-i"><span class="sw" style="background:' +
        CLUSTER_COLORS[c.id % CLUSTER_COLORS.length] + '"></span>#' + c.id + ' ' +
        esc(c.label.slice(0, 30)) + ' <span class="muted">(' + c.size + ')</span></div>').join('');
    } else {
      const top = this.labelOrder.slice(0, 10).map(i => this.nodes[i]);
      h += top.map(n => '<div class="lg-i">' + esc(n.name) +
        ' <span class="muted">' + n.count + '</span></div>').join('');
    }
    h += '<div class="lg-t" style="margin-top:7px">节点面积 ∝ 发文量；' +
      '连线粗细 ∝ 合作次数（≥' + this.opt.minWeight + '）</div>';
    this.legend.innerHTML = h;
  }

  _hit(mx, my) {
    let best = -1, bd = 1e9;
    for (let i = 0; i < this.nodes.length; i++) {
      const n = this.nodes[i];
      if (n._px === undefined) continue;
      const d = (mx - n._px) ** 2 + (my - n._py) ** 2;
      if (d <= (n._pr + 4) ** 2 && d < bd) { bd = d; best = i; }
    }
    return best;
  }

  _bind() {
    const cv = this.cv;
    const at = e => {
      const r = cv.getBoundingClientRect();
      return [e.clientX - r.left, e.clientY - r.top];
    };
    let drag = null;
    cv.addEventListener('mousedown', e => {
      drag = { x: e.clientX, y: e.clientY, tx: this.tf.x, ty: this.tf.y, moved: false };
    });
    window.addEventListener('mouseup', () => { drag = null; });
    cv.addEventListener('mousemove', e => {
      const [mx, my] = at(e);
      if (drag) {
        const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
        if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
        this.tf.x = drag.tx + dx; this.tf.y = drag.ty + dy;
        this.draw();
        return;
      }
      const i = this._hit(mx, my);
      if (i !== this.hover) { this.hover = i; this.draw(); }
      if (i < 0) { this.tip.style.opacity = 0; return; }
      const n = this.nodes[i];
      const partners = [];
      for (const e of this.edges) {
        if (e.source === i) partners.push([this.nodes[e.target].name, e.weight]);
        else if (e.target === i) partners.push([this.nodes[e.source].name, e.weight]);
      }
      partners.sort((a, b) => b[1] - a[1]);
      let h = '<b>' + esc(n.name) + '</b><br>发文 <b>' + n.count + '</b> 篇';
      if (n.mean_year) h += '<br>平均年份 ' + n.mean_year;
      h += '<br>中介中心性 ' + n.centrality.toFixed(4) + '<br>合作国家/地区 ' + n.degree;
      if (partners.length) {
        h += '<br>主要伙伴：' + partners.slice(0, 5)
          .map(p => esc(p[0]) + '(' + p[1] + ')').join('、');
      }
      this.tip.innerHTML = h;
      this.tip.style.opacity = 1;
      this.tip.style.left = Math.min(mx + 14, this.w - 300) + 'px';
      this.tip.style.top = Math.max(4, my - 10) + 'px';
    });
    cv.addEventListener('mouseleave', () => {
      this.hover = -1; this.tip.style.opacity = 0; this.draw();
    });
    cv.addEventListener('click', e => {
      if (!this.onSelect) return;
      const [mx, my] = at(e);
      const i = this._hit(mx, my);
      if (i < 0) return;
      this.selected = i; this.draw();
      this.onSelect(this.nodes[i]);
    });
    cv.addEventListener('wheel', e => {
      e.preventDefault();
      const [mx, my] = at(e);
      const k0 = this.tf.k;
      const k1 = Math.max(0.4, Math.min(12, k0 * (e.deltaY < 0 ? 1.12 : 0.89)));
      // keep the point under the cursor where it is
      this.tf.x = mx - (mx - this.tf.x) * (k1 / k0);
      this.tf.y = my - (my - this.tf.y) * (k1 / k0);
      this.tf.k = k1;
      this.draw();
    }, { passive: false });
  }

  toPNG() {
    const off = document.createElement('canvas');
    off.width = this.cv.width; off.height = this.cv.height;
    const c = off.getContext('2d');
    c.fillStyle = '#ffffff'; c.fillRect(0, 0, off.width, off.height);
    c.drawImage(this.cv, 0, 0);
    return off.toDataURL('image/png');
  }
}

/* ------------------------------ table ----------------------------------- */
function renderGeoTable(box, nodes, opts) {
  opts = opts || {};
  const list = nodes.slice().sort((a, b) => b.count - a.count);
  let h = '<table><thead><tr><th>国家 / 地区</th><th class="num-c">发文</th>' +
    '<th class="num-c">中心性</th><th class="num-c">合作数</th>' +
    '<th class="num-c">首现年</th><th class="num-c">平均年</th>' +
    '<th class="num-c">聚类</th></tr></thead><tbody>';
  list.forEach(n => {
    h += '<tr data-id="' + n.id + '"><td>' + esc(n.name) +
      (n.located ? '' : ' <span class="muted small">(无坐标)</span>') + '</td>' +
      '<td class="num-c">' + n.count + '</td>' +
      '<td class="num-c">' + n.centrality.toFixed(4) + '</td>' +
      '<td class="num-c">' + n.degree + '</td>' +
      '<td class="num-c">' + (n.first_year || '') + '</td>' +
      '<td class="num-c">' + (n.mean_year || '') + '</td>' +
      '<td class="num-c"><span class="chip" style="background:' +
      CLUSTER_COLORS[n.cluster % CLUSTER_COLORS.length] + '"></span>' +
      n.cluster + '</td></tr>';
  });
  h += '</tbody></table>';
  box.innerHTML = h;
  if (opts.onPick) {
    box.querySelectorAll('tbody tr').forEach(tr => {
      tr.addEventListener('click', () => opts.onPick(Number(tr.getAttribute('data-id'))));
    });
  }
}

window.GeoView = GeoView;
window.geoRenderTable = renderGeoTable;
})();
