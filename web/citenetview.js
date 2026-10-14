/* citenetview.js -- internal citation network structure rendering.
   Round-3 addition; captions carry the red "new" badge. */
(function (global) {
  'use strict';

  function setupCanvas(cv, cssH) {
    if (!cv) return null;
    var w = cv.clientWidth || cv.parentNode.clientWidth || 800;
    var h = cssH || cv.height;
    var dpr = global.devicePixelRatio || 1;
    cv.width = Math.max(1, Math.round(w * dpr));
    cv.height = Math.max(1, Math.round(h * dpr));
    cv.style.width = w + 'px';
    cv.style.height = h + 'px';
    var ctx = cv.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { ctx: ctx, w: w, h: h };
  }

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function empty(ctx, W, H, msg) {
    ctx.fillStyle = '#8b96a5'; ctx.font = '12px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(msg || '无数据', W / 2, H / 2);
  }

  /* ------------------------------------------------------- summary cards */
  function renderCards(box, res) {
    if (!box) return;
    var s = res.summary || {};
    var items = [
      ['文献节点', s.n_nodes || 0, '可被引用的库内文献'],
      ['引文边', s.n_edges || 0, '库内互引关系'],
      ['配额率', (s.match_rate || 0).toFixed(1) + '%', '参考文献命中库内'],
      ['网络密度', (s.density || 0).toFixed(5), '实际边 / 完全图'],
      ['聚类系数', (s.clustering || 0).toFixed(3), '局部聚集程度'],
      ['同配性', (s.assortativity || 0).toFixed(3), '度-度相关，∈[-1,1]'],
      ['简并度', s.degeneracy || 0, 'k-core 最大值'],
      ['幂律 α', s.power_law_alpha || '-', '引文入度分布'],
      ['连通分量', s.n_components || 0, '最大 ' + (s.largest_component || 0)],
      ['主路径长度', s.main_path_len || 0, 'SPLC 主路径节点数']
    ];
    box.innerHTML = items.map(function (it) {
      return '<div class="card"><div class="k">' + esc(it[0]) +
        '</div><div class="v">' + esc(it[1]) +
        '</div><div class="s">' + esc(it[2]) + '</div></div>';
    }).join('');
  }

  /* ---------------------------------------------------------- main path */
  function drawMainPath(cv, res) {
    var H = 118;
    var s = setupCanvas(cv, H);
    if (!s) return;
    var ctx = s.ctx, W = s.w;
    ctx.clearRect(0, 0, W, H);
    var mp = res.main_path || [];
    if (!mp.length) { empty(ctx, W, H, '主路径为空（库内引用链太稀疏）'); return; }

    var pad = 44, inner = W - pad * 2;
    var n = mp.length;
    var step = n > 1 ? inner / (n - 1) : 0;
    var baseY = 60;
    var maxLc = 1;
    for (var q = 0; q < n; q++) maxLc = Math.max(maxLc, mp[q].local_citations || 0);

    // links
    ctx.strokeStyle = '#c62828'; ctx.lineWidth = 2;
    ctx.beginPath();
    for (var i = 0; i < n; i++) {
      var x = pad + step * i;
      if (i === 0) ctx.moveTo(x, baseY); else ctx.lineTo(x, baseY);
    }
    ctx.stroke();

    for (var j = 0; j < n; j++) {
      var xx = pad + step * j;
      var r = 6 + 9 * Math.sqrt((mp[j].local_citations || 0) / maxLc);
      ctx.beginPath(); ctx.arc(xx, baseY, r, 0, 6.2832);
      ctx.fillStyle = '#c62828'; ctx.fill();
      ctx.strokeStyle = '#fff'; ctx.lineWidth = 2; ctx.stroke();

      ctx.fillStyle = '#5a6675'; ctx.font = '9.5px sans-serif';
      ctx.textAlign = 'right';
      ctx.save();
      ctx.translate(xx - 4, baseY + 16);
      ctx.rotate(-0.62);
      ctx.fillText((mp[j].year || '') + ' ' +
        trunc(mp[j].title || '', 26), 0, 0);
      ctx.restore();
      ctx.textAlign = 'center';
      ctx.fillStyle = '#8b96a5';
      ctx.fillText('lc ' + (mp[j].local_citations || 0), xx, baseY - r - 5);
    }
    ctx.textAlign = 'left';
    ctx.fillStyle = '#c62828'; ctx.font = '600 10px sans-serif';
    ctx.fillText('旧 \u2192 新', 4, 12);
  }

  function trunc(s, n) {
    return s.length > n ? s.slice(0, n - 1) + '\u2026' : s;
  }

  /* ------------------------------------------------------- half life */
  function drawHalfLife(cv, res) {
    var s = setupCanvas(cv, 150);
    if (!s) return;
    var ctx = s.ctx, W = s.w, H = s.h;
    ctx.clearRect(0, 0, W, H);
    var hl = res.half_life || [];
    if (!hl.length) { empty(ctx, W, H, '无半衰期数据'); return; }
    var pad = { l: 44, r: 16, t: 14, b: 26 };
    var pw = W - pad.l - pad.r, ph = H - pad.t - pad.b;
    var vals = hl.map(function (h) { return h.median_ref_age || 0; });
    var vmax = Math.max.apply(null, vals) * 1.15 || 1;

    ctx.strokeStyle = '#eef1f6';
    for (var g = 0; g <= 4; g++) {
      var gy = pad.t + ph * g / 4;
      ctx.beginPath(); ctx.moveTo(pad.l, gy); ctx.lineTo(pad.l + pw, gy);
      ctx.stroke();
      ctx.fillStyle = '#8b96a5'; ctx.font = '9.5px sans-serif';
      ctx.textAlign = 'right';
      ctx.fillText(Math.round(vmax * (1 - g / 4)), pad.l - 5, gy + 3);
    }

    ctx.beginPath();
    for (var i = 0; i < hl.length; i++) {
      var x = pad.l + pw * (hl.length === 1 ? 0.5 : i / (hl.length - 1));
      var y = pad.t + ph * (1 - vals[i] / vmax);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.strokeStyle = '#1565c0'; ctx.lineWidth = 2; ctx.stroke();
    for (var j = 0; j < hl.length; j++) {
      var xx = pad.l + pw * (hl.length === 1 ? 0.5 : j / (hl.length - 1));
      var yy = pad.t + ph * (1 - vals[j] / vmax);
      ctx.beginPath(); ctx.arc(xx, yy, 3.2, 0, 6.2832);
      ctx.fillStyle = '#1565c0'; ctx.fill();
      ctx.fillStyle = '#8b96a5'; ctx.font = '9.5px sans-serif';
      ctx.textAlign = 'center';
      if (hl.length <= 14 || j % 2 === 0) {
        ctx.fillText(hl[j].year, xx, H - 8);
      }
    }
    ctx.textAlign = 'left';
    ctx.fillStyle = '#8b96a5'; ctx.font = '9.5px sans-serif';
    ctx.fillText('中位引文年龄（年）', 2, 9);
  }

  /* ---------------------------------------------------------- scatter */
  var _pts = [];

  function drawScatter(cv, res, tip) {
    var s = setupCanvas(cv, 360);
    if (!s) return;
    var ctx = s.ctx, W = s.w, H = s.h;
    ctx.clearRect(0, 0, W, H);
    var rows = res.rows || [];
    if (!rows.length) { empty(ctx, W, H, '无节点数据'); return; }

    var pad = { l: 52, r: 18, t: 14, b: 44 };
    var pw = W - pad.l - pad.r, ph = H - pad.t - pad.b;
    var xs = rows.map(function (r) { return r.div_refs_rao || 0; });
    var ys = rows.map(function (r) { return r.effective_size || 0; });
    var xmax = Math.max.apply(null, xs) * 1.08 || 1;
    var ymax = Math.max.apply(null, ys) * 1.08 || 1;
    var lcmax = 1;
    for (var z = 0; z < rows.length; z++) {
      lcmax = Math.max(lcmax, rows[z].local_citations || 0);
    }

    ctx.strokeStyle = '#eef1f6';
    for (var g = 0; g <= 4; g++) {
      var gy = pad.t + ph * g / 4;
      ctx.beginPath(); ctx.moveTo(pad.l, gy); ctx.lineTo(pad.l + pw, gy);
      ctx.stroke();
      ctx.fillStyle = '#8b96a5'; ctx.font = '9.5px sans-serif';
      ctx.textAlign = 'right';
      ctx.fillText((ymax * (1 - g / 4)).toFixed(0), pad.l - 5, gy + 3);
    }
    for (var g2 = 0; g2 <= 4; g2++) {
      var gx = pad.l + pw * g2 / 4;
      ctx.strokeStyle = '#f4f6f9';
      ctx.beginPath(); ctx.moveTo(gx, pad.t); ctx.lineTo(gx, pad.t + ph);
      ctx.stroke();
      ctx.fillStyle = '#8b96a5'; ctx.textAlign = 'center';
      ctx.fillText((xmax * g2 / 4).toFixed(1), gx, pad.t + ph + 13);
    }

    _pts = [];
    var clusters = {};
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i];
      var x = pad.l + pw * ((r.div_refs_rao || 0) / xmax);
      var y = pad.t + ph * (1 - (r.effective_size || 0) / ymax);
      var rad = 2.6 + 7 * Math.sqrt((r.local_citations || 0) / lcmax);
      var col = r.on_main_path ? '#c62828' : palette(r.cluster);
      _pts.push({ x: x, y: y, r: Math.max(3, rad), row: r });
      if (r.on_main_path) clusters[r.cluster] = true;
    }
    _pts.sort(function (a, b) { return b.r - a.r; });
    for (var j = 0; j < _pts.length; j++) {
      var p = _pts[j];
      ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, 6.2832);
      ctx.fillStyle = p.row.on_main_path
        ? 'rgba(198,40,40,.85)' : hexA(palette(p.row.cluster), 0.5);
      ctx.fill();
      if (p.row.on_main_path) {
        ctx.strokeStyle = '#7f1d1d'; ctx.lineWidth = 1.2; ctx.stroke();
      }
    }

    ctx.strokeStyle = '#c9d0da'; ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(pad.l, pad.t); ctx.lineTo(pad.l, pad.t + ph);
    ctx.lineTo(pad.l + pw, pad.t + ph); ctx.stroke();

    ctx.fillStyle = '#8b96a5'; ctx.font = '10px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('参考文献结构多样性 Rao-Stirling \u2192',
      pad.l + pw / 2, H - 20);
    ctx.save();
    ctx.translate(12, pad.t + ph / 2); ctx.rotate(-Math.PI / 2);
    ctx.fillText('结构洞有效规模 \u2192', 0, 0); ctx.restore();
    ctx.textAlign = 'left'; ctx.fillStyle = '#c62828';
    ctx.font = '9.5px sans-serif';
    ctx.fillText('\u25cf 主路径节点', pad.l + 4, pad.t + 11);

    if (tip) bindTip(cv, tip);
  }

  var PALETTE = ['#1565c0', '#2e7d32', '#ef6c00', '#6a1b9a', '#00838f',
    '#ad1457', '#5d4037', '#9e9d24', '#283593', '#00695c'];

  function palette(i) {
    if (i === undefined || i === null || i < 0) return '#94a3b8';
    return PALETTE[i % PALETTE.length];
  }

  function hexA(hex, a) {
    var h = hex.replace('#', '');
    var n = parseInt(h, 16);
    return 'rgba(' + ((n >> 16) & 255) + ',' + ((n >> 8) & 255) + ',' +
      (n & 255) + ',' + a + ')';
  }

  function bindTip(cv, tip) {
    if (cv.__cn) return;
    cv.__cn = true;
    cv.addEventListener('mousemove', function (e) {
      var rect = cv.getBoundingClientRect();
      var mx = e.clientX - rect.left, my = e.clientY - rect.top;
      var hit = null;
      for (var i = 0; i < _pts.length; i++) {
        var p = _pts[i];
        if ((mx - p.x) * (mx - p.x) + (my - p.y) * (my - p.y) <=
          (p.r + 2) * (p.r + 2)) { hit = p; break; }
      }
      if (!hit) { tip.style.display = 'none'; return; }
      var r = hit.row;
      tip.innerHTML = '<b>' + esc(trunc(r.title || '', 70)) + '</b>' +
        '<br>' + (r.year || '') + ' · ' + esc(trunc(r.journal || '', 30)) +
        '<br>本地被引 ' + (r.local_citations || 0) +
        ' · k-core ' + (r.core || 0) +
        '<br>多样性 品种 ' + (r.div_refs_variety || 0) +
        ' / 均衡 ' + fmtf(r.div_refs_balance) +
        ' / 差异 ' + fmtf(r.div_refs_disparity) +
        '<br>Rao-Stirling ' + fmtf(r.div_refs_rao) +
        ' · 有效规模 ' + fmtf(r.effective_size) +
        '<br>限制度 ' + fmtf(r.constraint) +
        (r.on_main_path ? ' · <span style="color:#c62828">主路径</span>' : '');
      tip.style.display = 'block';
      tip.style.left = Math.min(hit.x + 12, rect.width - 260) + 'px';
      tip.style.top = Math.max(4, hit.y - 12) + 'px';
    });
    cv.addEventListener('mouseleave', function () {
      tip.style.display = 'none';
    });
  }

  function fmtf(v) {
    return (v === undefined || v === null) ? '-' : Number(v).toFixed(3);
  }

  /* ------------------------------------------------------------- table */
  function renderTable(box, res) {
    if (!box) return;
    var rows = (res.rows || []).slice();
    rows.sort(function (a, b) {
      return (b.local_citations || 0) - (a.local_citations || 0);
    });
    var cols = [
      ['title', '题名'], ['year', '年'], ['local_citations', '本地被引'],
      ['core', 'k-core'], ['div_refs_variety', '多样性品种'],
      ['div_refs_rao', 'Rao-Stirling'], ['effective_size', '有效规模'],
      ['constraint', '限制度'], ['on_main_path', '主路径']
    ];
    var head = '<thead><tr>' + cols.map(function (c) {
      return '<th>' + esc(c[1]) + '</th>';
    }).join('') + '</tr></thead>';
    var body = rows.slice(0, 400).map(function (r) {
      return '<tr>' + cols.map(function (c) {
        var v = r[c[0]];
        if (c[0] === 'title') {
          return '<td title="' + esc(v) + '">' + esc(trunc(v || '', 62)) + '</td>';
        }
        if (c[0] === 'on_main_path') {
          return '<td>' + (v ? '<span style="color:#c62828">\u2713</span>' : '') +
            '</td>';
        }
        if (typeof v === 'number') return '<td>' + Number(v.toFixed(3)) + '</td>';
        return '<td>' + esc(v) + '</td>';
      }).join('') + '</tr>';
    }).join('');
    box.innerHTML = '<table class="tbl">' + head + '<tbody>' + body +
      '</tbody></table>';
  }

  global.CiteNetView = {
    renderCards: renderCards,
    drawMainPath: drawMainPath,
    drawHalfLife: drawHalfLife,
    drawScatter: drawScatter,
    renderTable: renderTable
  };
})(window);
