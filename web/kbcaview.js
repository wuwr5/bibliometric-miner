/* kbcaview.js -- KBCA multi-channel fusion rendering.
   Round-3 addition. */
(function (global) {
  'use strict';

  var CH_LABEL = {
    bc: '文献耦合',
    cc: '共被引',
    tfidf: 'TF-IDF 文本',
    topic: '主题分布',
    author: '共同作者',
    cat: '同学科'
  };

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

  function trunc(s, n) {
    s = String(s == null ? '' : s);
    return s.length > n ? s.slice(0, n - 1) + '\u2026' : s;
  }

  function empty(ctx, W, H, m) {
    ctx.fillStyle = '#8b96a5'; ctx.font = '12px sans-serif';
    ctx.textAlign = 'center'; ctx.fillText(m || '无数据', W / 2, H / 2);
  }

  function col(i) {
    var P = ['#c62828', '#1565c0', '#2e7d32', '#ef6c00', '#6a1b9a',
      '#00838f', '#ad1457', '#5d4037', '#283593', '#00695c'];
    if (i === undefined || i === null || i < 0) return '#94a3b8';
    return P[i % P.length];
  }

  function hexA(hex, a) {
    var h = hex.replace('#', '');
    var n = parseInt(h, 16);
    return 'rgba(' + ((n >> 16) & 255) + ',' + ((n >> 8) & 255) + ',' +
      (n & 255) + ',' + a + ')';
  }

  /* --------------------------------------------------------------- cards */
  function renderCards(box, res) {
    if (!box) return;
    var s = res.summary || {};
    var chans = res.channels || {};
    var items = [
      ['文献节点', s.n_nodes || 0, '有融合连边的文献'],
      ['融合边', s.n_edges || 0, '加权后保留的最强边'],
      ['聚类数', s.n_clusters || 0, 'Louvain 分区'],
      ['模块度 Q', (s.modularity || 0).toFixed(3), '融合网络分区质量'],
      ['通道数', (s.active_channels || []).length, '参与融合的相似度通道'],
      ['耦合对数', chans.bc || 0, '共享参考文献的文献对']
    ];
    box.innerHTML = items.map(function (it) {
      return '<div class="card"><div class="k">' + esc(it[0]) +
        '</div><div class="v">' + esc(it[1]) +
        '</div><div class="s">' + esc(it[2]) + '</div></div>';
    }).join('');
  }

  /* -------------------------------------------------------- mantel matrix */
  function drawMantel(cv, res) {
    var keys0 = (res.summary && res.summary.active_channels) || [];
    // size the grid to the available width so the matrix does not end up as
    // a tiny square floating in a very wide canvas
    var availW = cv.clientWidth || cv.parentNode.clientWidth || 800;
    var cellW = keys0.length
      ? (availW - 86) / keys0.length : 40;
    var cell = Math.max(18, Math.min(96, cellW));
    var cssH = keys0.length ? (26 + cell * keys0.length + 18) : 260;
    var s = setupCanvas(cv, cssH);
    if (!s) return;
    var ctx = s.ctx, W = s.w, H = s.h;
    ctx.clearRect(0, 0, W, H);
    var mant = res.mantel || [];
    var keys = (res.summary && res.summary.active_channels) || [];
    if (!mant.length || !keys.length) {
      empty(ctx, W, H, 'Mantel 矩阵为空'); return;
    }
    var n = keys.length;
    var pad = { l: 74, r: 12, t: 26 };
    var cell = Math.min((W - pad.l - pad.r) / n, (H - pad.t - 12) / n);
    if (!(cell > 4)) cell = 4;

    ctx.font = '10px sans-serif';
    // headers
    for (var i = 0; i < n; i++) {
      ctx.fillStyle = '#5a6675'; ctx.textAlign = 'center';
      ctx.save();
      ctx.translate(pad.l + cell * (i + 0.5), pad.t - 6);
      ctx.rotate(-Math.PI / 4);
      ctx.fillText(CH_LABEL[keys[i]] || keys[i], 0, 0);
      ctx.restore();
      ctx.textAlign = 'right';
      ctx.fillText(CH_LABEL[keys[i]] || keys[i], pad.l - 5,
        pad.t + cell * (i + 0.5) + 3);
    }

    // symmetric matrix
    var getR = function (a, b) {
      for (var k = 0; k < mant.length; k++) {
        var m = mant[k];
        if ((m.a === a && m.b === b) || (m.a === b && m.b === a)) {
          return m.r;
        }
      }
      return null;
    };
    for (var r = 0; r < n; r++) {
      for (var c = 0; c < n; c++) {
        var x = pad.l + cell * c, y = pad.t + cell * r;
        var v = (r === c) ? 1 : getR(keys[r], keys[c]);
        if (v === null || v === undefined) {
          ctx.fillStyle = '#f8fafc';
          ctx.fillRect(x + 1, y + 1, cell - 2, cell - 2);
          continue;
        }
        var a = Math.min(1, Math.abs(v));
        ctx.fillStyle = v >= 0 ? 'rgba(21,101,192,' + (0.10 + 0.85 * a) + ')'
          : 'rgba(198,40,40,' + (0.10 + 0.85 * a) + ')';
        ctx.fillRect(x + 1, y + 1, cell - 2, cell - 2);
        ctx.strokeStyle = 'rgba(255,255,255,.75)';
        ctx.lineWidth = Math.max(0.4, 2.4 * a);
        ctx.strokeRect(x + 1.5, y + 1.5, cell - 3, cell - 3);
        if (cell >= 30 && r !== c) {
          ctx.fillStyle = a > 0.5 ? '#fff' : '#334155';
          ctx.font = '9px sans-serif'; ctx.textAlign = 'center';
          ctx.fillText(Number(v).toFixed(2), x + cell / 2, y + cell / 2 + 3);
        }
      }
    }

    ctx.textAlign = 'left'; ctx.font = '9.5px sans-serif';
    ctx.fillStyle = '#1565c0';
    ctx.fillText('\u25a0 正相关 r', pad.l, H - 4);
    ctx.fillStyle = '#c62828';
    ctx.fillText('\u25a0 负相关 r', pad.l + 66, H - 4);
    ctx.fillStyle = '#8b96a5';
    ctx.fillText('（全部检验 p < 0.05 时边框加粗）', pad.l + 132, H - 4);
  }

  /* -------------------------------------------------------- network view */
  var _pos = null;

  function drawNetwork(cv, res, tip, onDone) {
    var s = setupCanvas(cv, 400);
    if (!s) return;
    var nodes = res.nodes || [];
    var edges = res.edges || [];
    if (!nodes.length || !edges.length) {
      empty(s.ctx, s.w, s.h, '融合网络为空'); return;
    }
    // deterministic "cluster ring" layout keeps re-renders stable
    _pos = layout(res);
    fitView(res, s.w, s.h);
    paint(cv, s.ctx, s.w, s.h, res, _pos);
    if (tip) bindTip(cv, tip, res);
    if (onDone) onDone();
  }

  function layout(res) {
    var nodes = res.nodes || [];
    var rowsArr = res.rows || [];
    var cluOf = {};
    for (var k = 0; k < rowsArr.length; k++) cluOf[rowsArr[k].i] = rowsArr[k].cluster;
    var groups = {};
    nodes.forEach(function (n) {
      var c = cluOf[n];
      (groups[c] = groups[c] || []).push(n);
    });
    var keys = Object.keys(groups).map(Number).sort(function (a, b) {
      return groups[b].length - groups[a].length;
    });
    var pos = {};
    var cols = Math.max(1, Math.ceil(Math.sqrt(keys.length)));
    keys.forEach(function (c, gi) {
      var gx = gi % cols, gy = Math.floor(gi / cols);
      var members = groups[c];
      var rr = Math.max(24, Math.sqrt(members.length) * 13);
      members.forEach(function (n, idx) {
        var ang = idx * 2.39996;          // golden angle => even spread
        var rr2 = rr * Math.sqrt((idx + 0.5) / members.length);
        pos[n] = [gx * 190 + Math.cos(ang) * rr2,
        gy * 175 + Math.sin(ang) * rr2];
      });
    });
    return { pos: pos, cluOf: cluOf };
  }

  var _view = { k: 1, x: 0, y: 0 };

  /* Fit the whole ring layout into the canvas once, so the first frame is
     not clipped to whatever happens to be near the origin. */
  function fitView(res, W, H) {
    var pos = _pos && _pos.pos;
    if (!pos) return;
    var minX = 1e9, maxX = -1e9, minY = 1e9, maxY = -1e9;
    for (var key in pos) {
      var p = pos[key];
      if (p[0] < minX) minX = p[0];
      if (p[0] > maxX) maxX = p[0];
      if (p[1] < minY) minY = p[1];
      if (p[1] > maxY) maxY = p[1];
    }
    if (minX > maxX) return;
    var pad = 34;
    var k = Math.min((W - pad * 2) / Math.max(1, maxX - minX),
                     (H - pad * 2) / Math.max(1, maxY - minY));
    _view.k = Math.max(0.08, Math.min(1.6, k));
    _view.x = pad - minX * _view.k +
      (W - pad * 2 - (maxX - minX) * _view.k) / 2;
    _view.y = pad - minY * _view.k +
      (H - pad * 2 - (maxY - minY) * _view.k) / 2;
  }

  function paint(cv, ctx, W, H, res, lay) {
    ctx.clearRect(0, 0, W, H);
    var edges = res.edges || [];
    var pos = lay.pos;
    ctx.save();
    ctx.translate(_view.x, _view.y);
    ctx.scale(_view.k, _view.k);

    ctx.strokeStyle = 'rgba(148,163,184,.16)';
    ctx.lineWidth = 0.6;
    ctx.beginPath();
    for (var i = 0; i < edges.length; i += 2) {
      var a = pos[edges[i].s], b = pos[edges[i].t];
      if (!a || !b) continue;
      ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]);
    }
    ctx.stroke();

    var deg = {};
    edges.forEach(function (e) {
      deg[e.s] = (deg[e.s] || 0) + e.w;
      deg[e.t] = (deg[e.t] || 0) + e.w;
    });
    var dmax = 1;
    for (var kk in deg) dmax = Math.max(dmax, deg[kk]);

    var ids = (res.nodes || []).slice().sort(function (a, b) {
      return (deg[a] || 0) - (deg[b] || 0);
    });
    ids.forEach(function (n) {
      var p = pos[n];
      if (!p) return;
      var r = 2.2 + 6.5 * Math.sqrt((deg[n] || 0) / dmax);
      ctx.beginPath(); ctx.arc(p[0], p[1], r, 0, 6.2832);
      ctx.fillStyle = hexA(col(lay.cluOf[n]), 0.62);
      ctx.fill();
    });
    ctx.restore();

    ctx.fillStyle = '#8b96a5'; ctx.font = '9.5px sans-serif';
    ctx.textAlign = 'left';
    ctx.fillText('拖动平移 · 滚轮缩放 · 悬停查看文献', 6, 12);
    if (!cv.__kb) {
      cv.__kb = true;
      cv.addEventListener('wheel', function (e) {
        e.preventDefault();
        var f = e.deltaY < 0 ? 1.12 : 1 / 1.12;
        _view.k = Math.max(0.08, Math.min(8, _view.k * f));
        var s2 = setupCanvas(cv, 400);
        if (s2) paint(cv, s2.ctx, s2.w, s2.h, res, lay);
      }, { passive: false });
      var drag = null;
      cv.addEventListener('mousedown', function (e) {
        drag = { x: e.clientX, y: e.clientY, vx: _view.x, vy: _view.y };
      });
      global.addEventListener('mouseup', function () { drag = null; });
      cv.addEventListener('mousemove', function (e) {
        if (!drag) return;
        _view.x = drag.vx + (e.clientX - drag.x);
        _view.y = drag.vy + (e.clientY - drag.y);
        var s3 = setupCanvas(cv, 400);
        if (s3) paint(cv, s3.ctx, s3.w, s3.h, res, lay);
      });
    }
  }

  function bindTip(cv, tip, res) {
    if (cv.__kbt) return;
    cv.__kbt = true;
    var byId = {};
    (res.rows || []).forEach(function (r) { byId[r.i] = r; });
    cv.addEventListener('mousemove', function (e) {
      if (!_pos) return;
      var rect = cv.getBoundingClientRect();
      var mx = (e.clientX - rect.left - _view.x) / _view.k;
      var my = (e.clientY - rect.top - _view.y) / _view.k;
      var hit = null, bestd = 9 * 9;
      for (var key in _pos.pos) {
        var p = _pos.pos[key];
        var d = (p[0] - mx) * (p[0] - mx) + (p[1] - my) * (p[1] - my);
        if (d < bestd) { bestd = d; hit = Number(key); }
      }
      if (hit === null) { tip.style.display = 'none'; return; }
      var r = byId[hit];
      if (!r) { tip.style.display = 'none'; return; }
      tip.innerHTML = '<b>' + esc(trunc(r.title, 64)) + '</b><br>' +
        (r.year || '') + ' · ' + esc(trunc(r.journal, 30)) +
        '<br>加权度 ' + r.degree + ' · 介数 ' + r.betweenness +
        '<br>CD ' + r.disruption + ' · 新颖 ' + r.novelty +
        '<br>跨学科 ' + r.interdisciplinarity +
        '<br>结构 ' + r.structural + ' / 语义 ' + r.semantic +
        ' / <b>综合 ' + r.composite + '</b>';
      tip.style.display = 'block';
      tip.style.left = Math.min(e.clientX - rect.left + 12, rect.width - 250) + 'px';
      tip.style.top = Math.max(4, e.clientY - rect.top - 10) + 'px';
    });
    cv.addEventListener('mouseleave', function () { tip.style.display = 'none'; });
  }

  /* ------------------------------------------------------------- scatter */
  var _pts = [];

  function drawScatter(cv, res, tip) {
    var s = setupCanvas(cv, 380);
    if (!s) return;
    var ctx = s.ctx, W = s.w, H = s.h;
    ctx.clearRect(0, 0, W, H);
    var rows = res.rows || [];
    if (!rows.length) { empty(ctx, W, H, '无文献得分'); return; }

    var pad = { l: 52, r: 18, t: 14, b: 44 };
    var pw = W - pad.l - pad.r, ph = H - pad.t - pad.b;
    var xs = rows.map(function (r) { return r.structural || 0; });
    var ys = rows.map(function (r) { return r.semantic || 0; });
    var xmax = Math.max.apply(null, xs) * 1.06 || 1;
    var ymax = Math.max.apply(null, ys) * 1.06 || 1;

    ctx.strokeStyle = '#eef1f6';
    for (var g = 0; g <= 4; g++) {
      var gy = pad.t + ph * g / 4;
      ctx.beginPath(); ctx.moveTo(pad.l, gy); ctx.lineTo(pad.l + pw, gy);
      ctx.stroke();
      ctx.fillStyle = '#8b96a5'; ctx.font = '9.5px sans-serif';
      ctx.textAlign = 'right';
      ctx.fillText((ymax * (1 - g / 4)).toFixed(2), pad.l - 5, gy + 3);
    }
    for (var g2 = 1; g2 <= 4; g2++) {
      var gx = pad.l + pw * g2 / 4;
      ctx.strokeStyle = '#f4f6f9';
      ctx.beginPath(); ctx.moveTo(gx, pad.t); ctx.lineTo(gx, pad.t + ph);
      ctx.stroke();
      ctx.textAlign = 'center';
      ctx.fillText((xmax * g2 / 4).toFixed(2), gx, pad.t + ph + 13);
    }
    // diagonal reference (composite iso-lines)
    ctx.strokeStyle = '#e8eef6'; ctx.setLineDash([3, 3]);
    for (var d = 1; d <= 3; d++) {
      ctx.beginPath();
      ctx.moveTo(pad.l, pad.t + ph * (1 - d / 4));
      ctx.lineTo(pad.l + pw * (d / 4), pad.t + ph);
      ctx.stroke();
    }
    ctx.setLineDash([]);

    _pts = [];
    rows.forEach(function (r) {
      var x = pad.l + pw * ((r.structural || 0) / xmax);
      var y = pad.t + ph * (1 - (r.semantic || 0) / ymax);
      _pts.push({ x: x, y: y, r: Math.max(2.6, 3 + 8 * (r.composite || 0)), row: r });
    });
    _pts.sort(function (a, b) { return b.r - a.r; });
    _pts.forEach(function (p) {
      ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, 6.2832);
      ctx.fillStyle = hexA(col(p.row.cluster), 0.58);
      ctx.fill();
      if (p.r > 7) {
        ctx.strokeStyle = hexA(col(p.row.cluster), 0.9);
        ctx.lineWidth = 1; ctx.stroke();
      }
    });

    ctx.strokeStyle = '#c9d0da'; ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(pad.l, pad.t); ctx.lineTo(pad.l, pad.t + ph);
    ctx.lineTo(pad.l + pw, pad.t + ph); ctx.stroke();
    ctx.fillStyle = '#8b96a5'; ctx.font = '10px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('结构轴（度 / 介数 / CD）\u2192', pad.l + pw / 2, H - 20);
    ctx.save();
    ctx.translate(12, pad.t + ph / 2); ctx.rotate(-Math.PI / 2);
    ctx.fillText('语义轴（新颖 / 跨学科）\u2192', 0, 0);
    ctx.restore();
    ctx.textAlign = 'left'; ctx.fillStyle = '#8b96a5';
    ctx.font = '9px sans-serif';
    ctx.fillText('虚线 = 综合分等值线', pad.l + 4, pad.t + 11);

    if (tip && !cv.__ks) {
      cv.__ks = true;
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
        tip.innerHTML = '<b>' + esc(trunc(r.title, 66)) + '</b><br>' +
          (r.year || '') + ' · 聚类 #' + r.cluster +
          '<br>综合 ' + r.composite + '（结构 ' + r.structural +
          ' × 语义 ' + r.semantic + '）<br>' +
          'CD ' + r.disruption + ' · 新颖 ' + r.novelty +
          ' · 跨学科 ' + r.interdisciplinarity;
        tip.style.display = 'block';
        tip.style.left = Math.min(hit.x + 12, rect.width - 250) + 'px';
        tip.style.top = Math.max(4, hit.y - 12) + 'px';
      });
      cv.addEventListener('mouseleave', function () {
        tip.style.display = 'none';
      });
    }
  }

  /* --------------------------------------------------------------- table */
  function renderTable(box, res) {
    if (!box) return;
    var rows = (res.rows || []).slice(0, 500);
    var cols = [
      ['rank', '#'], ['title', '题名'], ['year', '年'],
      ['cluster', '簇'], ['composite', '综合'], ['structural', '结构'],
      ['semantic', '语义'], ['disruption', 'CD'],
      ['novelty', '新颖'], ['interdisciplinarity', '跨学科'],
      ['betweenness', '介数'], ['cited_by', '被引']
    ];
    var head = '<thead><tr>' + cols.map(function (c) {
      return '<th>' + esc(c[1]) + '</th>';
    }).join('') + '</tr></thead>';
    var body = rows.map(function (r) {
      return '<tr>' + cols.map(function (c) {
        var v = r[c[0]];
        if (c[0] === 'title') {
          return '<td title="' + esc(v) + '">' + esc(trunc(v, 58)) + '</td>';
        }
        if (typeof v === 'number') return '<td>' + Number(v.toFixed(3)) + '</td>';
        return '<td>' + esc(v) + '</td>';
      }).join('') + '</tr>';
    }).join('');
    box.innerHTML = '<table class="tbl">' + head + '<tbody>' + body +
      '</tbody></table>';
  }

  global.KBCAView = {
    renderCards: renderCards,
    drawMantel: drawMantel,
    drawNetwork: drawNetwork,
    drawScatter: drawScatter,
    renderTable: renderTable,
    channelLabel: CH_LABEL
  };
})(window);
