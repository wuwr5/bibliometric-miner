/* charts.js -- burst bars, cluster / node tables, publication histogram. */
(function () {
'use strict';

const CC = window.vizColors.clusterColor;

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"]/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}
function fp(v, d) { return Number(v).toFixed(d === undefined ? 3 : d); }

/* ------------------------------ bursts --------------------------------- */
function renderBursts(box, bursts, opts) {
  opts = opts || {};
  const rows = bursts.slice(0, opts.top || 40)
    .filter(b => b.strength >= (opts.minStrength || 0));
  if (!rows.length) { box.innerHTML = '<div class="muted">没有满足条件的突现。</div>'; return; }

  let y0 = 1e9, y1 = -1e9;
  rows.forEach(b => { y0 = Math.min(y0, b.begin); y1 = Math.max(y1, b.end); });
  const span = Math.max(1, y1 - y0);
  const pct = y => ((y - y0) / span * 100).toFixed(2) + '%';
  const step = Math.max(1, Math.round(span / 12));

  let ticks = '';
  for (let y = Math.ceil(y0 / step) * step; y <= y1; y += step) {
    ticks += '<span class="tick" style="left:' + pct(y) + '"><b>' + y + '</b></span>';
  }

  let html = '<div class="burst-head"><div>突现词 / 被引文献</div><div>时间轴 ' +
    y0 + ' – ' + y1 + ' （红色段 = 突现持续期）</div></div>';
  rows.forEach(b => {
    const strong = b.strength >= (rows[0].strength * 0.6);
    html += '<div class="burst-row" data-term="' + esc(b.term) + '">' +
      '<div class="burst-name" title="' + esc(b.label) + '">' + esc(b.label) +
      ' <span class="muted small">' + fp(b.strength, 1) + '</span></div>' +
      '<div class="burst-track"><span class="axis"></span>' + ticks +
      '<span class="seg' + (strong ? '' : ' lo') + '" style="left:' + pct(b.begin) +
      ';width:' + Math.max(1.2, (b.end - b.begin + 1) / span * 100).toFixed(2) + '%" ' +
      'title="' + b.begin + '–' + b.end + ' 强度 ' + b.strength + '"></span></div>' +
      '</div>';
  });
  box.innerHTML = html;
  if (opts.onPick) {
    box.querySelectorAll('.burst-row').forEach(el => {
      el.addEventListener('click', () => opts.onPick(el.getAttribute('data-term')));
    });
  }
}

/* ------------------------------ clusters ------------------------------- */
function renderClusters(box, clusters, opts) {
  opts = opts || {};
  let html = '<table><thead><tr>' +
    '<th data-s="id">#</th><th data-s="size" class="num-c">规模</th>' +
    '<th data-s="silhouette" class="num-c">Silhouette</th>' +
    '<th data-s="mean_year" class="num-c">平均年</th>' +
    '<th data-s="label">LLR 聚类标签</th>' +
    '<th class="num-c">突现数</th><th>代表节点</th></tr></thead><tbody>';
  clusters.forEach(c => {
    let terms = '';
    (c.terms || []).slice(0, 8).forEach(t => {
      terms += '<span class="term">' + esc(t.term) + ' <i>' + fp(t.score, 1) + '</i></span>';
    });
    html += '<tr data-id="' + c.id + '">' +
      '<td><span class="chip" style="background:' + CC(c.id) + '"></span>' + c.id + '</td>' +
      '<td class="num-c">' + c.size + '</td>' +
      '<td class="num-c">' + fp(c.silhouette) + '</td>' +
      '<td class="num-c">' + fp(c.mean_year, 1) + '</td>' +
      '<td><b>' + esc(c.label) + '</b>' +
      (opts.expand === false ? '' : '<br>' + terms) + '</td>' +
      '<td class="num-c">' + (c.n_burst || 0) + '</td>' +
      '<td class="small muted">' + esc((c.top_nodes || []).join('; ')).slice(0, 120) + '</td></tr>';
  });
  html += '</tbody></table>';
  box.innerHTML = html;
}

/* -------------------------------- nodes -------------------------------- */
function renderNodes(box, nodes, opts) {
  opts = opts || {};
  let list = nodes.slice();
  if (opts.cluster !== '' && opts.cluster != null) {
    list = list.filter(n => String(n.cluster) === String(opts.cluster));
  }
  if (opts.q) {
    const q = opts.q.toLowerCase();
    list = list.filter(n => n.label.toLowerCase().indexOf(q) >= 0);
  }
  const key = opts.sort || 'count';
  const dir = opts.dir === 'asc' ? 1 : -1;
  list.sort((a, b) => {
    let va = a[key], vb = b[key];
    if (key === 'burst') { va = a.burst ? a.burst.strength : 0; vb = b.burst ? b.burst.strength : 0; }
    if (typeof va === 'string') return dir * va.localeCompare(vb);
    return dir * ((va || 0) - (vb || 0));
  });

  let html = '<table><thead><tr>' +
    '<th data-s="label">标签</th>' +
    '<th data-s="count" class="num-c">频次</th>' +
    '<th data-s="centrality" class="num-c">中心性</th>' +
    '<th data-s="first_year" class="num-c">首现年</th>' +
    '<th data-s="burst" class="num-c">突现</th>' +
    '<th data-s="cluster" class="num-c">聚类</th>' +
    '<th class="num-c">度</th></tr></thead><tbody>';
  const shown = list.slice(0, opts.limit || 500);
  shown.forEach(n => {
    const b = n.burst;
    html += '<tr data-id="' + n.id + '">' +
      '<td>' + esc(n.label) + '</td>' +
      '<td class="num-c">' + n.count + '</td>' +
      '<td class="num-c">' + fp(n.centrality, 4) + '</td>' +
      '<td class="num-c">' + n.first_year + '</td>' +
      '<td class="num-c">' + (b ? b.begin + '–' + b.end + ' <b>' + fp(b.strength, 1) + '</b>' : '') + '</td>' +
      '<td class="num-c"><span class="chip" style="background:' + CC(n.cluster) + '"></span>' + n.cluster + '</td>' +
      '<td class="num-c">' + n.degree + '</td></tr>';
  });
  html += '</tbody></table>';
  if (list.length > shown.length) {
    html += '<div class="muted small" style="margin-top:6px">显示前 ' + shown.length +
      ' / ' + list.length + ' 条</div>';
  }
  box.innerHTML = html;
  if (opts.onPick) {
    box.querySelectorAll('tbody tr').forEach(tr => {
      tr.addEventListener('click', () => opts.onPick(Number(tr.getAttribute('data-id'))));
    });
  }
}

/* ----------------------------- histogram ------------------------------- */
function renderHistogram(canvas, yearHist, slices) {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth || 800, h = canvas.height || 220;
  canvas.width = Math.floor(w * dpr); canvas.height = Math.floor(h * dpr);
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  if (!yearHist || !yearHist.length) return;

  const pad = { l: 44, r: 16, t: 12, b: 26 };
  const iw = w - pad.l - pad.r, ih = h - pad.t - pad.b;
  const maxV = Math.max(...yearHist.map(d => d[1])) || 1;
  const n = yearHist.length;
  const bw = iw / n;

  ctx.fillStyle = '#eef2f8';
  ctx.fillRect(pad.l, pad.t, iw, ih);

  yearHist.forEach((d, i) => {
    const bh = d[1] / maxV * ih;
    const x = pad.l + i * bw + bw * 0.16;
    const bwid = bw * 0.68;
    ctx.fillStyle = '#3b82f6';
    ctx.fillRect(x, pad.t + ih - bh, bwid, bh);
  });

  // axis
  ctx.strokeStyle = '#cbd5e1'; ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(pad.l, pad.t + ih + .5); ctx.lineTo(pad.l + iw, pad.t + ih + .5); ctx.stroke();
  ctx.fillStyle = '#6b7686'; ctx.font = '11px sans-serif'; ctx.textAlign = 'center';
  const step = Math.max(1, Math.round(n / 14));
  yearHist.forEach((d, i) => {
    if (i % step !== 0 && i !== n - 1) return;
    ctx.fillText(d[0], pad.l + i * bw + bw / 2, pad.t + ih + 16);
  });
  ctx.textAlign = 'right';
  ctx.fillText(String(maxV), pad.l - 6, pad.t + 10);
  ctx.fillText('0', pad.l - 6, pad.t + ih);

  if (slices && slices.length) {
    const maxN = Math.max(...slices.map(s => s.n_nodes)) || 1;
    ctx.beginPath();
    slices.forEach((s, i) => {
      const x = pad.l + i * bw + bw / 2;
      const y = pad.t + ih - s.n_nodes / maxN * ih;
      i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
    });
    ctx.strokeStyle = '#c2410c'; ctx.lineWidth = 1.6; ctx.stroke();
  }
}

window.charts = {
  renderBursts: renderBursts, renderClusters: renderClusters,
  renderNodes: renderNodes, renderHistogram: renderHistogram, esc: esc, fp: fp
};
})();
