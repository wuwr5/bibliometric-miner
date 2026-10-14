/* forecastview.js -- trend forecasting + emergence ranking rendering.
   Round-3 addition. */
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

  function empty(ctx, W, H, m) {
    ctx.fillStyle = '#8b96a5'; ctx.font = '12px sans-serif';
    ctx.textAlign = 'center'; ctx.fillText(m || '无数据', W / 2, H / 2);
  }

  function trunc(s, n) {
    s = String(s == null ? '' : s);
    return s.length > n ? s.slice(0, n - 1) + '\u2026' : s;
  }

  /* -------------------------------------------------- generic series plot */
  function plotSeries(cv, years, hist, fc, lo, hi, opts) {
    opts = opts || {};
    var cssH = opts.height || 200;
    var s = setupCanvas(cv, cssH);
    if (!s) return;
    var ctx = s.ctx, W = s.w, H = s.h;
    ctx.clearRect(0, 0, W, H);
    if (!years || !years.length) { empty(ctx, W, H, '无时间序列'); return; }

    var horizon = fc ? fc.length : 0;
    var fYears = [];
    for (var q = 0; q < horizon; q++) fYears.push(years[years.length - 1] + q + 1);
    var allY = years.concat(fYears);
    var allV = hist.concat(fc || []).concat(lo || []).concat(hi || []);
    var vmax = Math.max.apply(null, allV.concat([1]));
    vmax = vmax * 1.12;

    var pad = { l: 46, r: 16, t: 16, b: 26 };
    var pw = W - pad.l - pad.r, ph = H - pad.t - pad.b;
    var N = allY.length;
    var X = function (i) {
      return pad.l + pw * (N <= 1 ? 0.5 : i / (N - 1));
    };
    var Y = function (v) { return pad.t + ph * (1 - v / vmax); };

    // grid
    ctx.strokeStyle = '#eef1f6'; ctx.lineWidth = 1;
    for (var g = 0; g <= 4; g++) {
      var gy = pad.t + ph * g / 4;
      ctx.beginPath(); ctx.moveTo(pad.l, gy); ctx.lineTo(pad.l + pw, gy);
      ctx.stroke();
      ctx.fillStyle = '#8b96a5'; ctx.font = '9.5px sans-serif';
      ctx.textAlign = 'right';
      ctx.fillText(Math.round(vmax * (1 - g / 4)), pad.l - 5, gy + 3);
    }

    // vertical divider at the forecast origin
    if (horizon) {
      var x0 = X(years.length - 1);
      ctx.strokeStyle = '#f0c3c3'; ctx.setLineDash([4, 3]);
      ctx.beginPath(); ctx.moveTo(x0, pad.t); ctx.lineTo(x0, pad.t + ph);
      ctx.stroke(); ctx.setLineDash([]);
    }

    // prediction band
    if (horizon && lo && hi) {
      ctx.beginPath();
      ctx.moveTo(X(years.length - 1), Y(hist[hist.length - 1]));
      for (var i2 = 0; i2 < horizon; i2++) {
        ctx.lineTo(X(years.length + i2), Y(hi[i2]));
      }
      for (var j2 = horizon - 1; j2 >= 0; j2--) {
        ctx.lineTo(X(years.length + j2), Y(lo[j2]));
      }
      ctx.closePath();
      ctx.fillStyle = 'rgba(198,40,40,.14)'; ctx.fill();
    }

    // forecast line
    if (horizon) {
      ctx.beginPath();
      ctx.moveTo(X(years.length - 1), Y(hist[hist.length - 1]));
      for (var k = 0; k < horizon; k++) {
        ctx.lineTo(X(years.length + k), Y(fc[k]));
      }
      ctx.strokeStyle = '#c62828'; ctx.lineWidth = 2;
      ctx.setLineDash([5, 3]); ctx.stroke(); ctx.setLineDash([]);
      for (var m2 = 0; m2 < horizon; m2++) {
        ctx.beginPath(); ctx.arc(X(years.length + m2), Y(fc[m2]), 3.4, 0, 6.2832);
        ctx.fillStyle = '#c62828'; ctx.fill();
      }
    }

    // history
    ctx.beginPath();
    for (var i = 0; i < years.length; i++) {
      var xx = X(i), yy = Y(hist[i]);
      if (i === 0) ctx.moveTo(xx, yy); else ctx.lineTo(xx, yy);
    }
    ctx.strokeStyle = '#1565c0'; ctx.lineWidth = 2; ctx.stroke();
    for (var n2 = 0; n2 < years.length; n2++) {
      ctx.beginPath(); ctx.arc(X(n2), Y(hist[n2]), 3, 0, 6.2832);
      ctx.fillStyle = '#1565c0'; ctx.fill();
    }

    // x labels
    ctx.fillStyle = '#8b96a5'; ctx.font = '9.5px sans-serif';
    ctx.textAlign = 'center';
    var stride = Math.ceil(N / 14);
    for (var t = 0; t < N; t += stride) {
      ctx.fillText(allY[t], X(t), H - 8);
    }
    ctx.textAlign = 'left'; ctx.fillStyle = '#1565c0';
    ctx.font = '9.5px sans-serif';
    ctx.fillText('\u2500 观测', pad.l + 4, pad.t + 10);
    if (horizon) {
      ctx.fillStyle = '#c62828';
      ctx.fillText('\u2500 集成预测（含区间）', pad.l + 52, pad.t + 10);
    }
    if (opts.title) {
      ctx.fillStyle = '#1b2430'; ctx.font = '600 11px sans-serif';
      ctx.textAlign = 'right';
      ctx.fillText(trunc(opts.title, 46), pad.l + pw, pad.t + 10);
      ctx.textAlign = 'left';
    }
  }

  /* ------------------------------------------------------- emergence bars */
  function drawEmergence(cv, res) {
    var s = setupCanvas(cv, 330);
    if (!s) return;
    var ctx = s.ctx, W = s.w, H = s.h;
    ctx.clearRect(0, 0, W, H);
    var em = (res.emergence || []).slice(0, 20);
    if (!em.length) { empty(ctx, W, H, '无涌现性数据'); return; }

    var pad = { l: 150, r: 108, t: 8, b: 8 };
    var pw = W - pad.l - pad.r;
    var rowH = Math.min(16, (H - pad.t - pad.b) / em.length);
    var maxE = Math.max.apply(null, em.map(function (e) { return e.emergence; })) || 1;
    var segs = [
      ['growth_n', '增长', '#c62828', 0.30],
      ['persistence_n', '持续', '#1565c0', 0.25],
      ['novelty_n', '新颖', '#2e7d32', 0.25],
      ['uncertainty_n', '不确定', '#ef6c00', 0.20]
    ];

    ctx.font = '9.5px sans-serif';
    for (var i = 0; i < em.length; i++) {
      var e = em[i];
      var y = pad.t + i * rowH + 1;
      var x = pad.l;
      // stacked bar: each component's width is its weighted contribution
      for (var j = 0; j < segs.length; j++) {
        var wgt = segs[j][3];
        var v = (e[segs[j][0]] || 0) * wgt;
        var lw = pw * v / maxE;
        ctx.fillStyle = segs[j][2];
        ctx.fillRect(x, y, lw, Math.max(4, rowH - 5));
        x += lw;
      }
      ctx.fillStyle = '#5a6675'; ctx.textAlign = 'right';
      ctx.fillText(trunc(e.label || e.term || '', 22), pad.l - 6, y + rowH - 4);
      ctx.textAlign = 'left';
      ctx.fillStyle = '#1b2430';
      ctx.fillText(e.emergence.toFixed(3), pad.l + pw * (e.emergence / maxE) + 5,
        y + rowH - 4);
      ctx.fillStyle = '#8b96a5';
      ctx.fillText('g' + Number(e.growth).toFixed(2) + ' p' +
        Number(e.persistence).toFixed(2) + ' n' +
        Number(e.novelty).toFixed(2) + ' u' +
        Number(e.uncertainty).toFixed(2), pad.l + pw + 34, y + rowH - 4);
    }
    // legend
    ctx.textAlign = 'left'; ctx.font = '9.5px sans-serif';
    var lx = 6;
    for (var k = 0; k < segs.length; k++) {
      ctx.fillStyle = segs[k][2];
      ctx.fillRect(lx, H - 4, 8, 8);
      ctx.fillStyle = '#5a6675';
      ctx.fillText(segs[k][1] + '×' + segs[k][3], lx + 11, H - 4 + 8);
      lx += 62;
    }
  }

  /* -------------------------------------------------------------- table */
  function renderTable(box, res, onPick) {
    if (!box) return;
    var em = res.emergence || [];
    var fc = res.forecast || {};
    var head = '<thead><tr><th>#</th><th>词/节点</th><th>总量</th>' +
      '<th>首现</th><th>近期均值</th><th>前期均值</th><th>增长</th>' +
      '<th>持续</th><th>新颖</th><th>不确定</th><th>涌现</th>' +
      '<th>预测(' + (res.summary && res.summary.horizon) + '年)</th>' +
      '<th>最优模型 MAE</th></tr></thead>';
    var body = em.map(function (e) {
      var f = fc[e.term];
      return '<tr data-term="' + esc(e.term) + '">' +
        '<td>' + e.rank + '</td>' +
        '<td title="' + esc(e.term) + '">' + esc(trunc(e.label || e.term, 30)) + '</td>' +
        '<td>' + e.total + '</td><td>' + e.first_year + '</td>' +
        '<td>' + e.recent_mean + '</td><td>' + e.prior_mean + '</td>' +
        '<td>' + Number(e.growth).toFixed(2) + '</td>' +
        '<td>' + Number(e.persistence).toFixed(2) + '</td>' +
        '<td>' + Number(e.novelty).toFixed(2) + '</td>' +
        '<td>' + Number(e.uncertainty).toFixed(2) + '</td>' +
        '<td><b>' + e.emergence.toFixed(3) + '</b></td>' +
        '<td>' + (f ? f.forecast.map(function (v) {
          return Number(v).toFixed(1);
        }).join(', ') : '-') + '</td>' +
        '<td>' + (f && f.mae !== null && f.mae !== undefined ? f.mae : '-') +
        '</td></tr>';
    }).join('');
    box.innerHTML = '<table class="tbl">' + head + '<tbody>' + body +
      '</tbody></table>';
    if (onPick) {
      Array.prototype.forEach.call(
        box.querySelectorAll('tbody tr'), function (tr) {
          tr.style.cursor = 'pointer';
          tr.addEventListener('click', function () {
            onPick(tr.getAttribute('data-term'));
          });
        });
    }
  }

  global.ForecastView = {
    plotSeries: plotSeries,
    drawEmergence: drawEmergence,
    renderTable: renderTable
  };
})(window);
