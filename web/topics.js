/* topics.js -- LDA / BERTopic-style topic model rendering.
   Part of the round-3 additions; every caption carries the red "new" badge. */
(function (global) {
  'use strict';

  function el(id) { return document.getElementById(id); }

  var PALETTE = [
    '#c62828', '#1565c0', '#2e7d32', '#ef6c00', '#6a1b9a',
    '#00838f', '#ad1457', '#5d4037', '#455a64', '#9e9d24',
    '#d84315', '#283593', '#00695c', '#7b1fa2', '#558b2f'
  ];

  function clusterColor(i) { return PALETTE[i % PALETTE.length]; }

  function hexToRgba(hex, a) {
    var h = hex.replace('#', '');
    if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
    var n = parseInt(h, 16);
    return 'rgba(' + ((n >> 16) & 255) + ',' + ((n >> 8) & 255) + ',' +
      (n & 255) + ',' + a + ')';
  }

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

  /* ------------------------------------------------------- stacked area */
  function drawTopicYear(cv, res) {
    var s = setupCanvas(cv, 200);
    if (!s) return;
    var ctx = s.ctx, W = s.w, H = s.h;
    ctx.clearRect(0, 0, W, H);
    var ty = res.topic_year || [];
    if (!ty.length) { empty(ctx, W, H, '无逐年主题数据'); return; }

    var pad = { l: 40, r: 90, t: 10, b: 24 };
    var pw = W - pad.l - pad.r, ph = H - pad.t - pad.b;
    var K = ty[0].shares.length;

    // stack
    var stacked = ty.map(function (r) {
      var acc = 0;
      return r.shares.map(function (v) { var o = acc; acc += v; return o; });
    });
    for (var k = 0; k < K; k++) {
      ctx.beginPath();
      for (var i = 0; i < ty.length; i++) {
        var x = pad.l + pw * (ty.length === 1 ? 0.5 : i / (ty.length - 1));
        var y1 = pad.t + ph * (1 - stacked[i][k]);
        if (i === 0) ctx.moveTo(x, y1); else ctx.lineTo(x, y1);
      }
      for (var j = ty.length - 1; j >= 0; j--) {
        var x2 = pad.l + pw * (ty.length === 1 ? 0.5 : j / (ty.length - 1));
        var y2 = pad.t + ph * (1 - (stacked[j][k] + ty[j].shares[k]));
        ctx.lineTo(x2, y2);
      }
      ctx.closePath();
      ctx.fillStyle = hexToRgba(clusterColor(k), 0.72);
      ctx.fill();
    }

    // axes
    ctx.strokeStyle = '#c9d0da'; ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(pad.l, pad.t); ctx.lineTo(pad.l, pad.t + ph);
    ctx.lineTo(pad.l + pw, pad.t + ph); ctx.stroke();
    ctx.fillStyle = '#8b96a5'; ctx.font = '10px sans-serif';
    ctx.textAlign = 'center';
    for (var t = 0; t < ty.length; t++) {
      var xx = pad.l + pw * (ty.length === 1 ? 0.5 : t / (ty.length - 1));
      if (ty.length > 12 && t % 2) continue;
      ctx.fillText(ty[t].year, xx, pad.t + ph + 13);
    }
    ctx.textAlign = 'left';
    ctx.fillText('0%', 4, pad.t + ph);
    ctx.fillText('100%', 4, pad.t + 9);

    // legend
    var lx = W - pad.r + 6, ly = pad.t + 4;
    ctx.font = '10px sans-serif';
    for (var m = 0; m < K; m++) {
      var lab = res.topics[m] ? shortLabel(res.topics[m]) : ('T' + m);
      ctx.fillStyle = clusterColor(m);
      ctx.fillRect(lx, ly + m * 13 - 7, 8, 8);
      ctx.fillStyle = '#5a6675';
      ctx.fillText(lab, lx + 12, ly + m * 13);
    }
  }

  function shortLabel(t) {
    if (!t) return '';
    var s = (t.label || '').split(',').slice(0, 3).join(',');
    return s.length > 15 ? s.slice(0, 14) + '\u2026' : s;
  }

  /* ----------------------------------------------------------- bubbles */
  var _bubbles = [];

  function drawBubble(cv, res, tip) {
    var s = setupCanvas(cv, 360);
    if (!s) return;
    var ctx = s.ctx, W = s.w, H = s.h;
    ctx.clearRect(0, 0, W, H);
    var ts = res.topics || [];
    if (!ts.length) { empty(ctx, W, H, '无主题数据'); return; }

    var years = ts.map(function (t) { return t.mean_year || 0; });
    var sizes = ts.map(function (t) { return t.n_docs || t.size || 0; });
    var y0 = Math.min.apply(null, years), y1 = Math.max.apply(null, years);
    if (y1 - y0 < 0.5) { y0 -= 0.5; y1 += 0.5; }
    var pad = { l: 46, r: 18, t: 14, b: 30 };
    var pw = W - pad.l - pad.r, ph = H - pad.t - pad.b;
    var smax = Math.max.apply(null, sizes) || 1;
    var rmax = Math.min(pw, ph) / 9;

    // grid
    ctx.strokeStyle = '#eef1f6'; ctx.lineWidth = 1;
    for (var g = 1; g < 4; g++) {
      var gy = pad.t + ph * g / 4;
      ctx.beginPath(); ctx.moveTo(pad.l, gy); ctx.lineTo(pad.l + pw, gy);
      ctx.stroke();
    }

    _bubbles = [];
    for (var i = 0; i < ts.length; i++) {
      var t = ts[i];
      var x = pad.l + pw * ((years[i] - y0) / (y1 - y0 || 1));
      var y = pad.t + ph * (1 - (sizes[i] / smax));
      var r = Math.max(7, rmax * Math.sqrt(sizes[i] / smax));
      _bubbles.push({ x: x, y: y, r: r, t: t });
      ctx.beginPath(); ctx.arc(x, y, r, 0, 6.2832);
      ctx.fillStyle = hexToRgba(clusterColor(t.id || i), 0.42);
      ctx.fill();
      ctx.strokeStyle = clusterColor(t.id || i); ctx.lineWidth = 1.6;
      ctx.stroke();
      if (r > 13) {
        ctx.fillStyle = '#1b2430'; ctx.font = '600 10px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('#' + t.id, x, y + 3);
      }
    }

    ctx.strokeStyle = '#c9d0da'; ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(pad.l, pad.t); ctx.lineTo(pad.l, pad.t + ph);
    ctx.lineTo(pad.l + pw, pad.t + ph); ctx.stroke();
    ctx.fillStyle = '#8b96a5'; ctx.font = '10px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText((y0).toFixed(1) + ' \u2192 ' + (y1).toFixed(1) +
      '（平均年份）', pad.l + pw / 2, H - 8);
    ctx.save(); ctx.translate(11, pad.t + ph / 2); ctx.rotate(-Math.PI / 2);
    ctx.textAlign = 'center'; ctx.fillText('文献规模', 0, 0); ctx.restore();

    if (tip) bindTip(cv, tip, res);
  }

  function bindTip(cv, tip, res) {
    if (cv.__tbound) return;
    cv.__tbound = true;
    cv.addEventListener('mousemove', function (e) {
      var rect = cv.getBoundingClientRect();
      var mx = e.clientX - rect.left, my = e.clientY - rect.top;
      var hit = null;
      for (var i = 0; i < _bubbles.length; i++) {
        var b = _bubbles[i];
        if ((mx - b.x) * (mx - b.x) + (my - b.y) * (my - b.y) <= b.r * b.r) {
          hit = b; break;
        }
      }
      if (!hit) { tip.style.display = 'none'; return; }
      var rows = (hit.t.terms || []).slice(0, 8).map(function (x) {
        return x[0];
      }).join(', ');
      tip.innerHTML = '<b>#' + hit.t.id + '</b> ' + (hit.t.label || '') +
        '<br>规模 ' + (hit.t.n_docs || hit.t.size || 0) +
        ' 篇 · 平均年 ' + (hit.t.mean_year || '-') +
        (hit.t.coherence_umass !== undefined
          ? '<br>一致性 UMass ' + hit.t.coherence_umass +
          ' / PMI ' + hit.t.coherence_pmi : '') +
        '<br><span style="opacity:.75">' + rows + '</span>';
      tip.style.display = 'block';
      tip.style.left = Math.min(hit.x + 12, rect.width - 240) + 'px';
      tip.style.top = (hit.y + 10) + 'px';
    });
    cv.addEventListener('mouseleave', function () {
      tip.style.display = 'none';
    });
    cv.addEventListener('click', function (e) {
      var rect = cv.getBoundingClientRect();
      var mx = e.clientX - rect.left, my = e.clientY - rect.top;
      for (var i = 0; i < _bubbles.length; i++) {
        var b = _bubbles[i];
        if ((mx - b.x) * (mx - b.x) + (my - b.y) * (my - b.y) <= b.r * b.r) {
          renderTerms(res.topics, b.t.id);
          var tr = document.querySelector('#tTable tr[data-id="' + b.t.id + '"]');
          if (tr) tr.scrollIntoView({ block: 'nearest' });
          break;
        }
      }
    });
  }

  /* ------------------------------------------------------------- terms */
  function renderTerms(topics, id) {
    var box = el('tTerms');
    if (!box) return;
    var t = null;
    for (var i = 0; i < topics.length; i++) {
      if (topics[i].id === id) { t = topics[i]; break; }
    }
    if (!t) { box.innerHTML = ''; return; }
    var terms = t.terms || [];
    var mx = 0;
    for (var j = 0; j < terms.length; j++) mx = Math.max(mx, terms[j][1] || 0);
    mx = mx || 1;
    var head = el('tTermT');
    if (head) {
      head.innerHTML = '主题 #' + t.id + ' 代表词（条形 = 该词在该主题内的概率）' +
        '<span class="new-badge">新增</span>';
    }
    var html = '';
    for (var k = 0; k < terms.length; k++) {
      var pct = Math.round((terms[k][1] || 0) / mx * 100);
      html += '<div class="term-bar"><span class="tw" title="' +
        esc(terms[k][0]) + '">' + esc(terms[k][0]) + '</span>' +
        '<span class="tg"><span class="tf" style="width:' + pct + '%"></span>' +
        '</span><span class="tv">' + (terms[k][1] || 0).toFixed(4) +
        '</span></div>';
    }
    box.innerHTML = html;
  }

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  /* ------------------------------------------------------------- table */
  function renderTable(box, res) {
    if (!box) return;
    var ts = res.topics || [];
    var head = '<thead><tr><th>#</th><th>标签</th><th>规模</th>' +
      '<th>平均年</th><th>U-mass</th><th>PMI</th></tr></thead>';
    var body = ts.map(function (t) {
      return '<tr data-id="' + t.id + '"><td>' + t.id + '</td>' +
        '<td title="' + esc(t.label) + '">' + esc(t.label || '') + '</td>' +
        '<td>' + (t.n_docs || t.size || 0) + '</td>' +
        '<td>' + (t.mean_year || '-') + '</td>' +
        '<td>' + fmt(t.coherence_umass) + '</td>' +
        '<td>' + fmt(t.coherence_pmi) + '</td></tr>';
    }).join('');
    box.innerHTML = '<table class="tbl">' + head + '<tbody>' + body +
      '</tbody></table>';
  }

  function fmt(v) {
    return (v === undefined || v === null) ? '-' : v;
  }

  function empty(ctx, W, H, msg) {
    ctx.fillStyle = '#8b96a5';
    ctx.font = '12px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(msg || '无数据', W / 2, H / 2);
  }

  global.TopicsView = {
    drawTopicYear: drawTopicYear,
    drawBubble: drawBubble,
    renderTerms: renderTerms,
    renderTable: renderTable,
    color: clusterColor,
    hexToRgba: hexToRgba
  };
})(window);
