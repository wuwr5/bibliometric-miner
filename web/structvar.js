/* structvar.js -- structural variation view.
   Scatter of  cluster linkage (x)  against  modularity change dM (y),
   plus the per-slice table.                                              */
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
function fp(v, d) { return Number(v).toFixed(d === undefined ? 3 : d); }

/* ------------------------------- scatter -------------------------------- */
function renderScatter(canvas, items, opts) {
  opts = opts || {};
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth || 900, h = canvas.height || 420;
  canvas.width = Math.floor(w * dpr);
  canvas.height = Math.floor(h * dpr);
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  canvas._items = items;
  canvas._opts = opts;
  canvas._geom = null;
  if (!items || !items.length) {
    ctx.fillStyle = '#8b96a5'; ctx.font = '13px sans-serif'; ctx.textAlign = 'center';
    ctx.fillText('没有可评估的新增节点', w / 2, h / 2);
    return;
  }

  const pad = { l: 62, r: 130, t: 16, b: 38 };
  const iw = w - pad.l - pad.r, ih = h - pad.t - pad.b;
  const ys = items.map(d => d.delta_m);
  const xs = items.map(d => d.linkage);
  const yMin = Math.min(...ys), yMax = Math.max(...ys);
  const xMax = Math.max(1, ...xs);
  // CiteSpace convention: a transformative node REMOVES modularity, so its
  // delta-M is positive.  The axis therefore spans 0 .. max, but is extended
  // below 0 when some nodes increase modularity (they sit inside one cluster).
  const yLo = Math.min(0, yMin), yHi = Math.max(yMax, yLo + 1e-6);
  const span = (yHi - yLo) || 1;
  const X = v => pad.l + (v / (xMax + 0.6)) * iw;
  const Y = v => pad.t + ih - ((v - yLo) / span) * ih;

  ctx.fillStyle = '#fbfcfe';
  ctx.fillRect(pad.l, pad.t, iw, ih);
  ctx.strokeStyle = '#e3e7ee'; ctx.lineWidth = 1;
  ctx.strokeRect(pad.l + .5, pad.t + .5, iw, ih);

  // zero line (no change in modularity)
  if (yHi > 0 && yLo < 0) {
    ctx.strokeStyle = '#cbd5e1';
    ctx.setLineDash([4, 3]);
    ctx.beginPath(); ctx.moveTo(pad.l, Y(0)); ctx.lineTo(pad.l + iw, Y(0)); ctx.stroke();
    ctx.setLineDash([]);
  }

  // grid + y ticks
  ctx.font = '10.5px -apple-system,"Segoe UI",sans-serif';
  ctx.fillStyle = '#6b7686'; ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
  for (let i = 0; i <= 4; i++) {
    const v = yLo + span * i / 4;
    const y = Y(v);
    ctx.strokeStyle = '#eef1f6';
    ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(pad.l + iw, y); ctx.stroke();
    ctx.fillText(v.toFixed(3), pad.l - 6, y);
  }
  ctx.textAlign = 'center'; ctx.textBaseline = 'top';
  for (let x = 1; x <= xMax; x++) {
    ctx.fillText(String(x), X(x), pad.t + ih + 6);
  }

  // points
  const maxDeg = Math.max(1, ...items.map(d => d.degree));
  const years = [...new Set(items.map(d => d.year))].sort((a, b) => a - b);
  const yc = {};
  years.forEach((y, i) => { yc[y] = i; });
  items.forEach((d, i) => {
    const x = X(d.linkage + (i % 5) * 0.03 - 0.06);   // tiny jitter
    const y = Y(d.delta_m);
    const r = 3 + 7 * Math.sqrt(d.degree / maxDeg);
    d._px = x; d._py = y; d._pr = r;
    ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fillStyle = CLUSTER_COLORS[yc[d.year] % CLUSTER_COLORS.length];
    ctx.globalAlpha = 0.82; ctx.fill(); ctx.globalAlpha = 1;
    ctx.lineWidth = 0.9; ctx.strokeStyle = 'rgba(255,255,255,.9)'; ctx.stroke();
  });

  // label the strongest few
  const top = items.slice().sort((a, b) => b.delta_m - a.delta_m)
    .slice(0, opts.labelTop || 6);
  ctx.font = '10.5px -apple-system,"Segoe UI","Microsoft YaHei",sans-serif';
  ctx.textBaseline = 'middle'; ctx.textAlign = 'left';
  top.forEach(d => {
    const txt = (d.label || d.key).slice(0, 26);
    ctx.lineWidth = 3; ctx.strokeStyle = 'rgba(255,255,255,.95)';
    ctx.strokeText(txt, d._px + d._pr + 3, d._py);
    ctx.fillStyle = '#1b2430';
    ctx.fillText(txt, d._px + d._pr + 3, d._py);
  });

  // axis titles
  ctx.fillStyle = '#5a6675'; ctx.font = '11px -apple-system,"Segoe UI","Microsoft YaHei",sans-serif';
  ctx.textAlign = 'center'; ctx.textBaseline = 'top';
  ctx.fillText('聚类连接度 cluster linkage  \u2192  跨越越多聚类，结构影响越大',
    pad.l + iw / 2, pad.t + ih + 20);
  ctx.save();
  ctx.translate(14, pad.t + ih / 2); ctx.rotate(-Math.PI / 2);
  ctx.textBaseline = 'middle';
  ctx.fillText('\u2190 模块化变化 \u0394M（越负=越具结构变革性）', 0, 0);
  ctx.restore();

  // year legend
  let ly = pad.t + 6;
  ctx.font = '10.5px -apple-system,"Segoe UI",sans-serif';
  ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
  years.forEach(y => {
    const x = w - pad.r + 12;
    ctx.beginPath(); ctx.arc(x + 5, ly, 4.5, 0, Math.PI * 2);
    ctx.fillStyle = CLUSTER_COLORS[yc[y] % CLUSTER_COLORS.length]; ctx.fill();
    ctx.fillStyle = '#5a6675';
    ctx.fillText(String(y), x + 14, ly);
    ly += 14;
  });
}

function bindScatter(canvas, tip, onPick) {
  if (canvas._bound) { canvas._onPick = onPick; return; }
  canvas._bound = true;
  canvas._onPick = onPick;
  const at = e => {
    const r = canvas.getBoundingClientRect();
    return [e.clientX - r.left, e.clientY - r.top];
  };
  canvas.addEventListener('mousemove', e => {
    const items = canvas._items || [];
    const [mx, my] = at(e);
    let best = null, bd = 1e9;
    for (const d of items) {
      if (d._px === undefined) continue;
      const dd = (mx - d._px) ** 2 + (my - d._py) ** 2;
      if (dd <= (d._pr + 4) ** 2 && dd < bd) { bd = dd; best = d; }
    }
    if (!best) { if (tip) tip.style.opacity = 0; return; }
    if (tip) {
      tip.innerHTML = '<b>' + esc(best.label || best.key) + '</b><br>' +
        '年份 ' + best.year + '<br>\u0394M <b>' + fp(best.delta_m, 5) +
        '</b> (z ' + fp(best.dm_z || 0, 2) + ')<br>' +
        '连接度 ' + best.linkage + ' · 度 ' + best.degree + '<br>' +
        '结构偏移 ' + fp(best.divergence || 0, 4) +
        (best.delta_m_full !== undefined
          ? '<br>Louvain 复核 \u0394M ' + fp(best.delta_m_full, 5) : '');
      tip.style.opacity = 1;
      tip.style.left = Math.min(mx + 14, canvas.clientWidth - 300) + 'px';
      tip.style.top = Math.max(2, my - 12) + 'px';
    }
  });
  canvas.addEventListener('mouseleave', () => { if (tip) tip.style.opacity = 0; });
  canvas.addEventListener('click', e => {
    const items = canvas._items || [];
    const [mx, my] = at(e);
    let best = null, bd = 1e9;
    for (const d of items) {
      if (d._px === undefined) continue;
      const dd = (mx - d._px) ** 2 + (my - d._py) ** 2;
      if (dd <= (d._pr + 4) ** 2 && dd < bd) { bd = dd; best = d; }
    }
    if (best && canvas._onPick) canvas._onPick(best);
  });
}

/* -------------------------------- table --------------------------------- */
function renderTable(box, items, opts) {
  opts = opts || {};
  let list = items.slice();
  if (opts.year !== '' && opts.year != null) {
    list = list.filter(d => String(d.year) === String(opts.year));
  }
  if (opts.minLinkage) list = list.filter(d => d.linkage >= opts.minLinkage);
  list.sort((a, b) => (b.delta_m - a.delta_m));   // most transformative first
  let h = '<table><thead><tr>' +
    '<th>新增节点</th><th class="num-c">年份</th><th class="num-c">\u0394M</th>' +
    '<th class="num-c">\u0394M 率</th><th class="num-c">z(年内)</th>' +
    '<th class="num-c">连接度</th><th class="num-c">度</th>' +
    '<th class="num-c">频次</th><th class="num-c">结构偏移</th>' +
    '<th class="num-c">Louvain 复核</th></tr></thead><tbody>';
  list.forEach(d => {
    h += '<tr data-k="' + esc(d.key) + '"><td>' + esc(d.label || d.key) + '</td>' +
      '<td class="num-c">' + d.year + '</td>' +
      '<td class="num-c"><b>' + fp(d.delta_m, 5) + '</b></td>' +
      '<td class="num-c">' + fp(d.delta_m_rate, 4) + '</td>' +
      '<td class="num-c">' + fp(d.dm_z || 0, 2) + '</td>' +
      '<td class="num-c">' + d.linkage + '</td>' +
      '<td class="num-c">' + d.degree + '</td>' +
      '<td class="num-c">' + d.count + '</td>' +
      '<td class="num-c">' + fp(d.divergence || 0, 4) + '</td>' +
      '<td class="num-c">' + (d.delta_m_full !== undefined
        ? fp(d.delta_m_full, 5) : '<span class="muted">—</span>') + '</td></tr>';
  });
  h += '</tbody></table>';
  if (!list.length) h = '<div class="muted">没有满足条件的记录。</div>';
  box.innerHTML = h;
  if (opts.onPick) {
    box.querySelectorAll('tbody tr').forEach(tr => {
      tr.addEventListener('click', () => opts.onPick(tr.getAttribute('data-k')));
    });
  }
}

/* ------------------------- per-year structuration ----------------------- */
function renderYearBars(canvas, years) {
  const rows = (years || []).filter(y => y.n_scored);
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth || 900, h = canvas.height || 120;
  canvas.width = Math.floor(w * dpr); canvas.height = Math.floor(h * dpr);
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  if (!rows.length) return;
  const pad = { l: 40, r: 12, t: 10, b: 22 };
  const iw = w - pad.l - pad.r, ih = h - pad.t - pad.b;
  const bw = iw / rows.length;
  const maxAbs = Math.max(1e-6, ...rows.map(r => Math.abs(r.max_dm)));
  ctx.font = '10px -apple-system,"Segoe UI",sans-serif';
  rows.forEach((r, i) => {
    const x = pad.l + i * bw;
    const v = Math.abs(r.max_dm);
    const bh = v / maxAbs * ih;
    ctx.fillStyle = '#c2410c';
    ctx.fillRect(x + bw * 0.18, pad.t + ih - bh, bw * 0.64, bh);
    ctx.fillStyle = '#6b7686'; ctx.textAlign = 'center'; ctx.textBaseline = 'top';
    ctx.fillText(String(r.year), x + bw / 2, pad.t + ih + 5);
    ctx.fillStyle = '#8b96a5'; ctx.textBaseline = 'bottom';
    ctx.fillText(r.n_scored, x + bw / 2, pad.t + ih - bh - 2);
  });
  ctx.strokeStyle = '#cbd5e1'; ctx.beginPath();
  ctx.moveTo(pad.l, pad.t + ih + .5); ctx.lineTo(pad.l + iw, pad.t + ih + .5); ctx.stroke();
  ctx.fillStyle = '#6b7686'; ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
  ctx.fillText('max \u0394M', 2, pad.t + 8);
}

window.structvar = {
  renderScatter: renderScatter, bindScatter: bindScatter,
  renderTable: renderTable, renderYearBars: renderYearBars
};
})();
