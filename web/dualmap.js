/* dualmap.js -- dual-map overlay renderer.
   Left half: the journals that publish (citing) the corpus.
   Right half: the journals it cites.  Every citation is a bezier curve. */
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
function discColor(list, name) {
  const i = list.indexOf(name);
  return CLUSTER_COLORS[(i < 0 ? 0 : i) % CLUSTER_COLORS.length];
}

class DualMapView {
  constructor(canvas, wrap, tip, legend) {
    this.cv = canvas; this.wrap = wrap; this.tip = tip; this.legend = legend;
    this.ctx = canvas.getContext('2d');
    this.dpr = window.devicePixelRatio || 1;
    this.res = null; this.hover = -1; this.hoverSide = '';
    this.opt = { minFlow: 1, labelTop: 12, showCurves: true, alpha: 0.30 };
    this.onSelect = null;
    this._bind();
    window.addEventListener('resize', () => { this.resize(); this.draw(); });
  }

  setData(res) {
    this.res = res;
    this.sources = res.sources || [];
    this.targets = res.targets || [];
    this.flows = (res.flows || []).slice();
    this.srcDisc = res.src_disciplines || [];
    this.tgtDisc = res.tgt_disciplines || [];
    // vertical extent of every discipline band
    this.bandSrc = this._bands(this.sources, this.srcDisc);
    this.bandTgt = this._bands(this.targets, this.tgtDisc);
    this.maxFlow = Math.max(1, ...this.flows.map(f => f.w));
    this.resize();
    this.drawLegend();
    this.draw();
  }

  setOptions(o) { Object.assign(this.opt, o); this.draw(); }

  _bands(side, discs) {
    const b = {};
    for (const d of discs) b[d] = { y0: 1, y1: 0, n: 0 };
    for (const s of side) {
      const k = b[s.discipline];
      if (!k) { b[s.discipline] = { y0: s.y, y1: s.y, n: 1 }; continue; }
      k.y0 = Math.min(k.y0, s.y); k.y1 = Math.max(k.y1, s.y); k.n++;
    }
    return b;
  }

  resize() {
    const w = this.wrap.clientWidth || 900, h = this.wrap.clientHeight || 620;
    this.w = w; this.h = h;
    this.cv.width = Math.floor(w * this.dpr);
    this.cv.height = Math.floor(h * this.dpr);
    this.cv.style.width = w + 'px';
    this.cv.style.height = h + 'px';
  }

  /* ---- geometry: normalised [0,1] box -> pixels ---- */
  _px(x) { return this.pad.l + x * this.iw; }
  _py(y) { return this.pad.t + y * this.ih; }

  draw() {
    const ctx = this.ctx;
    if (!this.res) {
      ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
      ctx.clearRect(0, 0, this.w, this.h);
      return;
    }
    this.pad = { l: 14, r: 14, t: 26, b: 14 };
    this.iw = this.w - this.pad.l - this.pad.r;
    this.ih = this.h - this.pad.t - this.pad.b;
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.clearRect(0, 0, this.w, this.h);

    // ---- header -------------------------------------------------------
    ctx.font = '600 12px -apple-system,"Segoe UI","Microsoft YaHei",sans-serif';
    ctx.fillStyle = '#5a6675'; ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
    ctx.fillText('施引期刊 Citing journals', this.pad.l, 16);
    ctx.textAlign = 'right';
    ctx.fillText('被引期刊 Cited journals', this.w - this.pad.r, 16);

    // ---- discipline bands ---------------------------------------------
    this._drawBands(ctx, this.bandSrc, this.srcDisc, true);
    this._drawBands(ctx, this.bandTgt, this.tgtDisc, false);

    // ---- flows ---------------------------------------------------------
    if (this.opt.showCurves) {
      ctx.save();
      ctx.lineCap = 'round';
      const flows = this.flows.filter(f => f.w >= this.opt.minFlow);
      for (const f of flows) {
        const s = this.sources[f.s], t = this.targets[f.t];
        if (!s || !t) continue;
        const x1 = this._px(s.x), y1 = this._py(s.y);
        const x2 = this._px(t.x), y2 = this._py(t.y);
        const dx = (x2 - x1) * 0.42;
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.bezierCurveTo(x1 + dx, y1, x2 - dx, y2, x2, y2);
        const lw = 0.5 + 3.4 * Math.log(1 + f.w) / Math.log(1 + this.maxFlow);
        ctx.lineWidth = Math.max(0.4, lw);
        ctx.strokeStyle = discColor(this.srcDisc, s.discipline);
        ctx.globalAlpha = Math.min(0.85, this.opt.alpha *
          (0.35 + 0.65 * Math.log(1 + f.w) / Math.log(1 + this.maxFlow)));
        ctx.stroke();
      }
      ctx.restore();
      ctx.globalAlpha = 1;
    }

    // ---- nodes ---------------------------------------------------------
    this._drawSide(ctx, this.sources, this.srcDisc, true);
    this._drawSide(ctx, this.targets, this.tgtDisc, false);

    // ---- labels --------------------------------------------------------
    this._drawLabels(ctx, this.sources, this.srcDisc, true);
    this._drawLabels(ctx, this.targets, this.tgtDisc, false);
  }

  _drawBands(ctx, bands, discs, left) {
    for (const d of discs) {
      const b = bands[d];
      if (!b || !b.n) continue;
      const y0 = this._py(Math.max(0, b.y0 - 0.022));
      const y1 = this._py(Math.min(1, b.y1 + 0.022));
      const x0 = left ? this.pad.l : this._px(0.52);
      const x1 = left ? this._px(0.48) : this.w - this.pad.r;
      ctx.fillStyle = discColor(discs, d);
      ctx.globalAlpha = 0.07;
      ctx.beginPath();
      ctx.rect(x0, y0, x1 - x0, y1 - y0);
      ctx.fill();
      ctx.globalAlpha = 1;
      // label
      ctx.font = '10.5px -apple-system,"Segoe UI","Microsoft YaHei",sans-serif';
      ctx.fillStyle = '#6b7686';
      ctx.textAlign = left ? 'left' : 'right';
      ctx.textBaseline = 'top';
      const ty = Math.max(this.pad.t + 2, y0);
      const tx = left ? this.pad.l + 3 : this.w - this.pad.r - 3;
      const txt = d + '  (' + b.n + ')';
      ctx.save();
      ctx.translate(tx, ty + (y1 - y0) / 2);
      ctx.rotate(left ? -Math.PI / 2 : Math.PI / 2);
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillText(txt, 0, 0);
      ctx.restore();
    }
  }

  _drawSide(ctx, side, discs, left) {
    for (let i = 0; i < side.length; i++) {
      const s = side[i];
      const x = this._px(s.x), y = this._py(s.y);
      const r = Math.max(2.2, s.r * this.iw);
      const hot = (this.hover === i && this.hoverSide === (left ? 's' : 't'));
      ctx.beginPath();
      ctx.arc(x, y, r, 0, Math.PI * 2);
      ctx.fillStyle = discColor(discs, s.discipline);
      ctx.globalAlpha = hot ? 1 : 0.92;
      ctx.fill();
      ctx.globalAlpha = 1;
      ctx.lineWidth = hot ? 2 : 0.8;
      ctx.strokeStyle = hot ? '#111827' : 'rgba(255,255,255,.9)';
      ctx.stroke();
      s._px = x; s._py = y; s._pr = r;
    }
  }

  _drawLabels(ctx, side, discs, left) {
    const top = side.map((s, i) => i)
      .sort((a, b) => side[b].count - side[a].count)
      .slice(0, this.opt.labelTop);
    ctx.font = '10.5px -apple-system,"Segoe UI","Microsoft YaHei",sans-serif';
    ctx.textBaseline = 'middle';
    for (const i of top) {
      const s = side[i];
      const txt = s.name.length > 26 ? s.name.slice(0, 25) + '\u2026' : s.name;
      const wTxt = ctx.measureText(txt).width;
      let x, align;
      if (left) {
        x = s._px - s._pr - 4;
        align = 'right';
        if (x - wTxt < 2) { x = s._px + s._pr + 4; align = 'left'; }
      } else {
        x = s._px + s._pr + 4;
        align = 'left';
        if (x + wTxt > this.w - 2) { x = s._px - s._pr - 4; align = 'right'; }
      }
      ctx.lineWidth = 3; ctx.strokeStyle = 'rgba(255,255,255,.92)';
      ctx.strokeText(txt, x, s._py);
      ctx.fillStyle = '#1b2430';
      ctx.textAlign = align;
      ctx.fillText(txt, x, s._py);
    }
  }

  drawLegend() {
    if (!this.legend || !this.res) return;
    const discs = this.srcDisc.concat(
      this.tgtDisc.filter(d => this.srcDisc.indexOf(d) < 0));
    this.legend.innerHTML =
      '<div class="lg-t">学科分区 Disciplines</div>' +
      discs.map(d => '<div class="lg-i"><span class="sw" style="background:' +
        discColor(discs, d) + '"></span>' + esc(d) + '</div>').join('') +
      '<div class="lg-t" style="margin-top:7px">流量 ' + this.maxFlow +
      ' (最粗) &rarr; 1</div>';
  }

  _hit(mx, my) {
    for (let i = 0; i < this.targets.length; i++) {
      const t = this.targets[i];
      if ((mx - t._px) ** 2 + (my - t._py) ** 2 <= (t._pr + 3) ** 2) return ['t', i];
    }
    for (let i = 0; i < this.sources.length; i++) {
      const s = this.sources[i];
      if ((mx - s._px) ** 2 + (my - s._py) ** 2 <= (s._pr + 3) ** 2) return ['s', i];
    }
    return null;
  }

  _bind() {
    const cv = this.cv;
    const at = e => {
      const r = cv.getBoundingClientRect();
      return [e.clientX - r.left, e.clientY - r.top];
    };
    cv.addEventListener('mousemove', e => {
      if (!this.res) return;
      const [mx, my] = at(e);
      const hit = this._hit(mx, my);
      const prev = this.hover + this.hoverSide;
      this.hover = hit ? hit[1] : -1;
      this.hoverSide = hit ? hit[0] : '';
      if (prev !== this.hover + this.hoverSide) this.draw();
      if (!hit) { this.tip.style.opacity = 0; return; }
      const side = hit[0] === 's' ? this.sources : this.targets;
      const nd = side[hit[1]];
      const rel = hit[0] === 's'
        ? this.flows.filter(f => f.s === hit[1]).sort((a, b) => b.w - a.w).slice(0, 4)
        : this.flows.filter(f => f.t === hit[1]).sort((a, b) => b.w - a.w).slice(0, 4);
      const other = hit[0] === 's' ? this.targets : this.sources;
      let h = '<b>' + esc(nd.name) + '</b><br>' +
        '学科：' + esc(nd.discipline) + '<br>' +
        (hit[0] === 's' ? '发文 ' : '被引 ') + '<b>' + nd.count + '</b> 次';
      if (rel.length) {
        h += '<br>主要' + (hit[0] === 's' ? '引用' : '施引') + '：' +
          rel.map(f => esc(other[hit[0] === 's' ? f.t : f.s].name.slice(0, 22)) +
            ' (' + f.w + ')').join('、');
      }
      this.tip.innerHTML = h;
      this.tip.style.opacity = 1;
      this.tip.style.left = Math.min(mx + 14, this.w - 300) + 'px';
      this.tip.style.top = Math.max(4, my - 10) + 'px';
    });
    cv.addEventListener('mouseleave', () => {
      this.hover = -1; this.hoverSide = '';
      this.tip.style.opacity = 0; this.draw();
    });
    cv.addEventListener('click', e => {
      if (!this.res || !this.onSelect) return;
      const [mx, my] = at(e);
      const hit = this._hit(mx, my);
      if (!hit) return;
      const side = hit[0] === 's' ? this.sources : this.targets;
      this.onSelect(side[hit[1]], hit[0]);
    });
  }

  toPNG() {
    const off = document.createElement('canvas');
    off.width = this.cv.width; off.height = this.cv.height;
    const c = off.getContext('2d');
    c.fillStyle = '#ffffff';
    c.fillRect(0, 0, off.width, off.height);
    c.drawImage(this.cv, 0, 0);
    return off.toDataURL('image/png');
  }
}

/* --------------------- discipline x discipline table --------------------- */
function renderMatrix(box, res) {
  if (!res || !res.matrix) { box.innerHTML = ''; return; }
  const rows = res.src_disciplines, cols = res.tgt_disciplines;
  let h = '<table><thead><tr><th>施引学科 \\ 被引学科</th>';
  cols.forEach(c => { h += '<th class="num-c">' + esc(c.slice(0, 22)) + '</th>'; });
  h += '</tr></thead><tbody>';
  res.matrix.forEach((row, i) => {
    h += '<tr><td><b>' + esc(rows[i]) + '</b></td>';
    row.forEach(c => {
      const strong = c.z > 1.96, weak = c.z < -1.96;
      h += '<td class="num-c" style="background:' +
        (strong ? 'rgba(37,99,235,.10)' : weak ? 'rgba(220,38,38,.08)' : 'transparent') +
        '">' + c.obs + '<br><span class="muted" style="font-size:10px">exp ' +
        c.exp + ' · z ' + (c.z > 0 ? '+' : '') + c.z + '</span></td>';
    });
    h += '</tr>';
  });
  h += '</tbody></table>';
  h += '<div class="muted small" style="margin-top:8px">' +
    '单元格为学科间引用流量；exp 为超几何期望值，z 为标准化的偏离度，' +
    '|z| &gt; 1.96 视为显著（蓝=高于期望，红=低于期望）。</div>';
  box.innerHTML = h;
}

window.DualMapView = DualMapView;
window.dualmapRenderMatrix = renderMatrix;
})();
