/* app.js -- application controller: data loading, analysis requests,
   view wiring and exports.                                              */
(function () {
'use strict';

const $ = id => document.getElementById(id);
const S = { result: null, files: [], selected: new Set(), key2node: {},
            dual: null, geo: null, sv: null, dualDone: false,
            geoDone: false, svDone: false,
            /* round-3 additions */
            topics: null, citenet: null, forecast: null, kbca: null };

let netV = null, zoneV = null, dualV = null, geoV = null;

/* ------------------------------ status -------------------------------- */
function status(msg, right, busy) {
  $('status').innerHTML = (busy ? '<span class="spin"></span>' : '') + msg;
  if (right !== undefined) $('statusRight').innerHTML = right || '';
}

/* ------------------------------ files --------------------------------- */
async function loadFiles() {
  const r = await fetch('/api/files').then(x => x.json());
  S.files = r.files || [];
  const box = $('fileList');
  if (!S.files.length) {
    box.innerHTML = '<div class="muted small">data/ 与 sample/ 下没有找到数据文件。<br>' +
      '点击上方「导入 WoS 数据」上传 Web of Science 纯文本导出文件。</div>';
    return;
  }
  box.innerHTML = S.files.map((f, i) =>
    '<label class="fi"><input type="checkbox" data-p="' + f.path.replace(/\\/g, '\\\\') +
    '" ' + (i === 0 ? 'checked' : '') + '>' +
    '<span class="nm" title="' + f.name + '">' + f.name + '</span>' +
    (f.group === 'sample' ? '<span class="tag">示例</span>' : '') +
    '<span class="sz">' + (f.size / 1024).toFixed(0) + 'K</span></label>').join('');
  box.querySelectorAll('input').forEach(cb => {
    cb.addEventListener('change', syncSel);
  });
  syncSel();
}
function syncSel() {
  S.selected.clear();
  $('fileList').querySelectorAll('input').forEach(cb => {
    if (cb.checked) S.selected.add(cb.getAttribute('data-p'));
  });
}

async function uploadFiles(files) {
  for (const f of files) {
    status('上传 ' + f.name + ' …', '', true);
    const txt = await f.text();
    await fetch('/api/upload', {
      method: 'POST',
      headers: { 'Content-Type': 'text/plain; charset=utf-8',
                 'X-Filename': encodeURIComponent(f.name) },
      body: txt
    }).then(x => x.json());
  }
  await loadFiles();
  status('上传完成，共 ' + S.files.length + ' 个文件');
}

/* ---------------------------- parameters ------------------------------ */
function collectParams() {
  const v = id => ($(id).value || '').trim();
  return {
    node_type: v('p_nodeType'),
    year_from: v('p_yearFrom') || null,
    year_to: v('p_yearTo') || null,
    slice_len: +v('p_sliceLen') || 1,
    criterion: v('p_criterion'),
    criterion_value: +v('p_critVal') || 40,
    max_nodes: +v('p_maxNodes') || 500,
    min_count: +v('p_minCount') || 1,
    normalize: v('p_normalize') || null,
    pruning: v('p_pruning'),
    prune_k: +v('p_pruneK') || 4,
    largest_component: $('p_lcc').checked,
    pf_r: v('p_pfR') === 'inf' ? 'inf' : (+v('p_pfR') || 2),
    pf_q: v('p_pfQ') || null,
    pf_metric: v('p_pfMetric') || 'count',
    cluster_resolution: +v('p_resolution') || 1,
    label_method: v('p_labelMethod'),
    label_source: v('p_labelSource'),
    burst_gamma: +v('p_bGamma') || 1,
    burst_base: +v('p_bBase') || 2,
    burst_min_duration: +v('p_bMinDur') || 2
  };
}

/* ----------------------------- analysis ------------------------------- */
async function runAnalysis() {
  if (!S.selected.size) { status('请先选择至少一个数据文件', '', false); return; }
  status('正在分析…', '', true);
  const t0 = performance.now();
  try {
    const res = await fetch('/api/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ files: Array.from(S.selected), params: collectParams() })
    }).then(x => x.json());
    if (res.error) { status('分析失败：' + res.error, '', false); return; }
    S.result = res;
    S.key2node = {};
    res.nodes.forEach(n => { S.key2node[n.key] = n; });
    // extended views depend on the same corpus + parameters
    S.dualDone = S.geoDone = S.svDone = false;
    S.dual = S.geo = S.sv = null;
    renderAll();
    const s = res.summary;
    status('分析完成',
      '<span class="pill">' + s.n_docs + ' 篇文献</span> ' +
      '<span class="pill g">' + s.n_nodes + ' 节点 / ' + s.n_edges + ' 连线</span> ' +
      '<span class="pill">' + s.n_clusters + ' 聚类</span> ' +
      '<span class="pill r">' + s.n_bursts + ' 突现</span> ' +
      'Q=' + s.modularity + ' · ' + ((performance.now() - t0) / 1000).toFixed(1) + 's');
  } catch (e) {
    status('请求失败：' + e.message, '', false);
  }
}

/* ----------------------------- rendering ------------------------------ */
function renderAll() {
  const res = S.result;
  if (!res) return;
  // network
  netV.setData(res);
  netV.setOptions(netOpts());
  netV.start();
  // zone
  zoneV.setData(res);
  zoneV.setOptions(zoneOpts());
  // bursts
  renderBurstView();
  // clusters
  charts.renderClusters($('clusterBox'), res.clusters,
    { expand: $('c_expand').checked });
  $('c_info').textContent = res.clusters.length + ' 个聚类 · 模块度 Q=' +
    res.summary.modularity;
  // nodes
  const sel = $('nd_cluster');
  sel.innerHTML = '<option value="">全部聚类</option>' + res.clusters.map(c =>
    '<option value="' + c.id + '">#' + c.id + ' ' + (c.label || '').slice(0, 40) +
    ' (n=' + c.size + ')</option>').join('');
  renderNodeTable();
  // overview
  renderOverview();
}

function netOpts() {
  return {
    mode: 'force',
    showLabels: $('n_labels').checked,
    showRings: $('n_rings').checked,
    showCentrality: $('n_cCirc').checked,
    colorBy: $('n_color').value,
    labelTop: +$('n_labelTop').value || 40,
    scale: +$('n_scale').value || 1
  };
}
function zoneOpts() {
  return {
    mode: $('z_mode').value,
    showLabels: $('z_labels').checked,
    showRings: $('z_rings').checked,
    labelTop: +$('z_labelTop').value || 30,
    colorBy: 'cluster', scale: 1
  };
}

function renderBurstView() {
  const res = S.result; if (!res) return;
  charts.renderBursts($('burstBox'), res.bursts, {
    top: +$('b_top').value || 40,
    minStrength: +$('b_minStrength').value || 0,
    onPick: term => { const n = S.key2node[term]; if (n) selectNode(n.id); }
  });
  $('b_info').textContent = res.bursts.length + ' 个突现（γ=' +
    res.params.burst_gamma + ', s=' + res.params.burst_base +
    ', 最短 ' + res.params.burst_min_duration + ' 年）';
}

function renderNodeTable() {
  const res = S.result; if (!res) return;
  charts.renderNodes($('nodeBox'), res.nodes, {
    cluster: $('nd_cluster').value,
    q: ($('nd_search').value || '').trim(),
    sort: S.nodeSort || 'count', dir: 'desc', limit: 400,
    onPick: id => selectNode(id)
  });
  $('nd_info').textContent = res.nodes.length + ' 个节点';
}

function renderOverview() {
  const res = S.result; if (!res) return;
  const s = res.summary, d = res.summary_dataset || {};
  const cards = [
    ['文献数', s.n_docs, d.n_docs && d.n_docs !== s.n_docs ? '全库 ' + d.n_docs + ' 篇' : ''],
    ['年份跨度', s.year_min + '–' + s.year_max, ''],
    ['网络节点', s.n_nodes, res.summary.node_type_label || ''],
    ['连线', s.n_edges, '密度 ' + s.density],
    ['聚类数', s.n_clusters, '模块度 Q = ' + s.modularity],
    ['突现', s.n_bursts, ''],
    ['参考文献总数', d.n_refs_total || '—', d.n_refs_mean ? '篇均 ' + d.n_refs_mean.toFixed(1) : ''],
    ['关键词种数', d.n_keywords_unique || '—', '']
  ];
  $('ovCards').innerHTML = cards.map(c =>
    '<div class="card"><div class="k">' + c[0] + '</div><div class="v">' + c[1] +
    '</div><div class="s">' + c[2] + '</div></div>').join('');
  charts.renderHistogram($('histCanvas'), res.year_hist, res.slices);
  $('ovLog').textContent = (res.log || []).join('\n') +
    '\n\n耗时 ' + res.elapsed + ' s\n数据源: ' + (res.source_files || []).join(', ');
}

/* --------------------- dual map / geo / structural var ---------------- */
function post(url, payload) {
  return fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  }).then(x => x.json());
}

async function runDual(force) {
  if (!S.selected.size) { status('请先选择至少一个数据文件'); return; }
  if (S.dual && !force) return;
  status('正在计算双图叠加…', '', true);
  try {
    const res = await post('/api/dualmap', { files: Array.from(S.selected),
      options: { top_journals: 90, top_flows: 600 } });
    if (res.error) { status('双图叠加失败：' + res.error); return; }
    S.dual = res; S.dualDone = true;
    dualV.setData(res);
    dualV.setOptions(dualOpts());
    dualmapRenderMatrix($('dualMatrix'), res);
    const s = res.summary;
    $('d_info').textContent = s.n_source_journals + ' 种施引期刊 → ' +
      s.n_target_journals + ' 种被引期刊 · ' + s.n_flows + ' 条引用流 · ' +
      s.n_citations + ' 次引用';
    status('双图叠加完成');
  } catch (e) { status('请求失败：' + e.message); }
}
function dualOpts() {
  return {
    minFlow: +$('d_minFlow').value || 1,
    labelTop: +$('d_labelTop').value || 12,
    showCurves: $('d_curves').checked
  };
}

async function runGeo(force) {
  if (!S.selected.size) { status('请先选择至少一个数据文件'); return; }
  if (S.geo && !force) return;
  status('正在计算地理视图…', '', true);
  try {
    const res = await post('/api/geo', { files: Array.from(S.selected),
      options: { min_count: +$('g_minCount').value || 1,
                 top_edges: 600,
                 resolution: +$('p_resolution').value || 1 } });
    if (res.error) { status('地理视图失败：' + res.error); return; }
    S.geo = res; S.geoDone = true;
    geoV.setData(res);
    geoV.setOptions(geoOpts());
    window.geoRenderTable($('geoTable'), res.nodes,
      { onPick: id => showGeoDetail(res.nodes.find(n => n.id === id)) });
    const s = res.summary;
    $('g_info').textContent = s.n_countries + ' 个国家/地区 · ' +
      s.n_edges_total + ' 条合作边（显示 ' + s.n_edges_shown + '）· Q=' +
      s.modularity + (s.n_unresolved ? ' · ' + s.n_unresolved + ' 条无法解析的地址' : '');
    status('地理视图完成');
  } catch (e) { status('请求失败：' + e.message); }
}
function geoOpts() {
  return {
    showLabels: $('g_labels').checked,
    labelTop: 14, scale: 1, colorBy: $('g_color').value,
    minWeight: +$('g_minW').value || 1, showGraticule: $('g_grid').checked
  };
}

async function runSV(force) {
  if (!S.selected.size) { status('请先选择至少一个数据文件'); return; }
  if (S.sv && !force) return;
  status('正在计算结构变异…', '', true);
  try {
    const p = collectParams();
    p.node_type = $('s_nodeType').value;
    p.sv_top_full = +$('s_topFull').value || 10;
    const res = await post('/api/structvar',
      { files: Array.from(S.selected), params: p });
    if (res.error) { status('结构变异失败：' + res.error); return; }
    S.sv = res; S.svDone = true;
    const years = (res.years || []).filter(y => y.n_scored);
    $('s_year').innerHTML = '<option value="">全部年份</option>' +
      years.map(y => '<option value="' + y.year + '">' + y.year +
        ' (' + y.n_scored + ')</option>').join('');
    renderSV();
    $('s_info').textContent = res.summary.n_items + ' 个可评估的新增节点 · ' +
      res.summary.n_years + ' 个年度 · 最具变革性：' +
      res.summary.most_transformative;
    status('结构变异完成');
  } catch (e) { status('请求失败：' + e.message); }
}
function renderSV() {
  const r = S.sv; if (!r) return;
  window.structvar.renderScatter($('svCanvas'), r.items, { labelTop: 6 });
  window.structvar.bindScatter($('svCanvas'), $('svTip'), it => showSVDetail(it));
  window.structvar.renderYearBars($('svYearCanvas'), r.years);
  renderSVTable();
}
function renderSVTable() {
  const r = S.sv; if (!r) return;
  window.structvar.renderTable($('svTable'), r.items, {
    year: $('s_year').value,
    minLinkage: +$('s_minLink').value || 1,
    onPick: k => {
      const it = r.items.find(x => x.key === k);
      if (it) showSVDetail(it);
    }
  });
}

/* =======================  round-3 additions  ===========================
   Topic modelling / citation-network structure / trend forecasting /
   KBCA multi-channel fusion.  All four panels are tagged red in the UI. */
async function api(name, params, label) {
  const files = S.selected && S.selected.size
    ? Array.from(S.selected)
    : [...document.querySelectorAll('#fileList input:checked')]
      .map(x => x.getAttribute('data-p'));
  if (!files.length) { status('请先在左侧勾选数据文件'); return null; }
  status((label || '计算') + '中…', '', true);
  try {
    const r = await post('/api/' + name, { files: files, params: params });
    if (r.error) { status((label || '计算') + '失败：' + r.error); return null; }
    status((label || '计算') + '完成');
    return r;
  } catch (e) {
    status('请求失败：' + (e && e.message ? e.message : e));
    return null;
  }
}

/* ------------------------------------------------ topic modelling ----- */
async function runTopics() {
  const fields = $('t_fields').value;
  const p = {
    method: $('t_method').value,
    n_topics: +$('t_k').value || 10,
    iterations: +$('t_iter').value || 60,
    burn_in: Math.max(5, Math.round((+$('t_iter').value || 60) * 0.4)),
    bigrams: $('t_bigrams').checked,
    use_title: fields !== 'abstract',
    use_abstract: fields !== 'title'
  };
  const r = await api('topics', p, '主题建模');
  if (!r) return;
  S.topics = r;
  renderTopics();
}
function renderTopics() {
  const r = S.topics;
  if (!r || !window.TopicsView) return;
  const T = window.TopicsView;
  T.drawTopicYear($('tYearCanvas'), r);
  T.drawBubble($('tBubbleCanvas'), r, $('tTip'));
  T.renderTable($('tTable'), r);
  if (r.topics && r.topics.length) T.renderTerms(r.topics, r.topics[0].id);
  const per = r.perplexity;
  $('t_info').innerHTML = '<span class="new-badge">新增</span> ' +
    (r.method === 'lda' ? 'LDA' : 'c-TF-IDF') + ' · ' +
    (r.topics ? r.topics.length : 0) + ' 个主题 · 词汇 ' +
    (r.params ? (r.params.vocab || r.params.k || '-') : '-') +
    (per ? ' · 困惑度 ' + per : '') +
    (r.coherence_mean !== undefined && r.coherence_mean !== null
      ? ' · 平均 UMass ' + r.coherence_mean : '');
  bindTopicTable();
}
function bindTopicTable() {
  const box = $('tTable');
  Array.prototype.forEach.call(box.querySelectorAll('tbody tr'), tr => {
    tr.style.cursor = 'pointer';
    tr.addEventListener('click', () => {
      const id = +tr.getAttribute('data-id');
      window.TopicsView.renderTerms(S.topics.topics, id);
    });
  });
}

/* ------------------------------------------------- citation network --- */
async function runCiteNet() {
  const r = await api('citenet', {}, '引文网络分析');
  if (!r) return;
  S.citenet = r;
  renderCiteNet();
}
function renderCiteNet() {
  const r = S.citenet;
  if (!r || !window.CiteNetView) return;
  const C = window.CiteNetView;
  C.renderCards($('cnCards'), r);
  C.drawMainPath($('cnPathCanvas'), r);
  C.drawHalfLife($('cnHalfCanvas'), r);
  C.drawScatter($('cnScatterCanvas'), r, $('cnTip'));
  C.renderTable($('cnTable'), r);
  $('cn_info').innerHTML = '<span class="new-badge">新增</span> ' +
    r.summary.n_nodes + ' 节点 / ' + r.summary.n_edges + ' 条库内引文 · ' +
    '配额率 ' + r.summary.match_rate.toFixed(2) + '% · 主路径 ' +
    r.summary.main_path_len + ' 篇';
}

/* ------------------------------------------------------ forecasting --- */
async function runForecast() {
  const p = {
    node_type: $('f_nodeType').value,
    criterion_value: +$('f_top').value || 50,
    horizon: +$('f_h').value || 3,
    holdout: +$('f_ho').value || 3,
    top: Math.max(10, Math.min(60, +$('f_top').value || 50))
  };
  const r = await api('forecast', p, '趋势预测');
  if (!r) return;
  S.forecast = r;
  renderForecast();
}
function renderForecast() {
  const r = S.forecast;
  if (!r || !window.ForecastView) return;
  const F = window.ForecastView;
  const df = r.doc_forecast || {};
  F.plotSeries($('fDocCanvas'), r.years, df.history || r.doc_series,
    df.forecast, df.lower, df.upper, { height: 200, title: '年度发文量' });
  F.drawEmergence($('fEmCanvas'), r);
  F.renderTable($('fTable'), r, term => pickForecastTerm(term));
  // default selection = top emerging item
  const em = r.emergence || [];
  if (em.length) pickForecastTerm(em[0].term);
  let note = '';
  if (r.dropped_year) {
    note = ' · 已剔除不完整尾年 ' + r.dropped_year;
  }
  $('f_info').innerHTML = '<span class="new-badge">新增</span> ' +
    (r.summary.n_terms || 0) + ' 个节点 · ' + (r.summary.n_years || 0) +
    ' 个完整年份 · 预测 ' + (r.summary.horizon || 0) + ' 年' + note;
}
function pickForecastTerm(term) {
  const r = S.forecast;
  if (!r || !term) return;
  const f = (r.forecast || {})[term];
  const lab = (r.labels || {})[term] || term;
  window.ForecastView.plotSeries($('fSeriesCanvas'), r.years,
    (r.series || {})[term] || [],
    f ? f.forecast : [], f ? f.lower : [], f ? f.upper : [],
    { height: 220, title: lab });
  const head = $('fSelT');
  if (head) {
    let w = '';
    if (f && f.weights) {
      w = ' ｜ 模型权重 ' + Object.keys(f.weights)
        .sort((a, b) => f.weights[b] - f.weights[a]).slice(0, 4)
        .map(k => k + ' ' + (f.weights[k] * 100).toFixed(0) + '%').join(', ');
    }
    head.innerHTML = lab + '：历史与预测' + w +
      '<span class="new-badge">新增</span>';
  }
  // offer "download row" is handled by the table click itself
  S.fcTerm = term;
}

/* -------------------------------------------------------------- KBCA -- */
async function runKBCA() {
  const p = {
    n_topics: +$('k_topics').value || 12,
    lda_iter: 25,
    max_edges: +$('k_edges').value || 20000,
    mantel_perms: +$('k_perms').value || 199
  };
  const r = await api('kbca', p, '多维融合');
  if (!r) return;
  S.kbca = r;
  renderKBCA();
}
function renderKBCA() {
  const r = S.kbca;
  if (!r || !window.KBCAView) return;
  const K = window.KBCAView;
  K.renderCards($('kCards'), r);
  K.drawMantel($('kMantelCanvas'), r);
  K.drawNetwork($('kNetCanvas'), r, $('kTip'));
  K.drawScatter($('kScatterCanvas'), r, $('kTip2'));
  K.renderTable($('kTable'), r);
  const mant = (r.mantel || []).slice().sort((a, b) => Math.abs(b.r) - Math.abs(a.r));
  $('k_info').innerHTML = '<span class="new-badge">新增</span> ' +
    r.summary.n_nodes + ' 节点 / ' + r.summary.n_edges + ' 边 · Q=' +
    r.summary.modularity + (mant.length ? ' · 最强通道相关 ' +
      mant[0].a + '↔' + mant[0].b + ' r=' + mant[0].r : '');
}

/* ------------------------------ detail -------------------------------- */
function selectNode(id) {
  const res = S.result; if (!res) return;
  const n = res.nodes.find(x => x.id === id);
  if (!n) return;
  netV.selected = id; netV.draw();
  showDetail(n);
  // jump to the network tab
  switchView('network');
}
function showDetail(n) {
  const res = S.result;
  const cl = res.clusters.find(c => c.id === n.cluster) || {};
  const years = Object.keys(n.years).map(Number).sort((a, b) => a - b);
  const maxY = Math.max(1, ...years.map(y => n.years[y]));
  let bars = '';
  years.forEach(y => {
    bars += '<span title="' + y + ': ' + n.years[y] + '" style="display:inline-block;' +
      'width:9px;vertical-align:bottom;background:#3b82f6;margin-right:1px;height:' +
      Math.max(2, n.years[y] / maxY * 34) + 'px"></span>';
  });
  const b = n.burst;
  let h = '<h4>' + charts.esc(n.label) + '</h4>' +
    '<div class="kv"><span>频次</span><b>' + n.count + '</b></div>' +
    '<div class="kv"><span>首现年</span><b>' + n.first_year + '</b></div>' +
    '<div class="kv"><span>中介中心性</span><b>' + n.centrality.toFixed(4) + '</b></div>' +
    '<div class="kv"><span>度 / 加权度</span><b>' + n.degree + ' / ' + n.strength.toFixed(1) + '</b></div>' +
    '<div class="kv"><span>聚类</span><b><span class="chip" style="background:' +
    window.vizColors.clusterColor(n.cluster) + '"></span>#' + n.cluster + ' ' +
    charts.esc(cl.label || '') + '</b></div>' +
    '<div class="kv"><span>轮廓值</span><b>' + n.silhouette + '</b></div>';
  if (b) {
    h += '<div class="kv"><span>突现区间</span><b style="color:#c2410c">' + b.begin +
      ' – ' + b.end + '</b></div>' +
      '<div class="kv"><span>突现强度</span><b>' + b.strength + '</b></div>' +
      '<div class="kv"><span>突现内/外频次</span><b>' + b.count + ' / ' + b.count_out + '</b></div>';
  }
  h += '<h4>逐年频次</h4><div style="height:36px">' + bars + '</div>';
  if (n.meta && n.meta.raw) {
    h += '<h4>原始参考文献</h4><div class="small muted">' + charts.esc(n.meta.raw) + '</div>';
  }
  // strongest neighbours
  const nb = [];
  for (const e of res.edges) {
    if (e.source === n.id) nb.push([e.target, e.weight]);
    else if (e.target === n.id) nb.push([e.source, e.weight]);
  }
  nb.sort((a, b2) => b2[1] - a[1]);
  if (nb.length) {
    h += '<h4>最强共现邻居</h4>';
    nb.slice(0, 8).forEach(([i, w]) => {
      const m = res.nodes.find(x => x.id === i);
      if (m) h += '<div class="kv small"><span>' + charts.esc(m.label.slice(0, 30)) +
        '</span><b>' + w + '</b></div>';
    });
  }
  $('detailBody').innerHTML = h;
}

function showDualDetail(nd, side) {
  const res = S.dual; if (!res) return;
  const other = side === 's' ? res.targets : res.sources;
  const rel = res.flows.filter(f => side === 's' ? f.s === nd.id : f.t === nd.id)
    .sort((a, b) => b.w - a.w);
  let h = '<h4>' + charts.esc(nd.name) + '</h4>' +
    '<div class="kv"><span>角色</span><b>' +
    (side === 's' ? '施引期刊' : '被引期刊') + '</b></div>' +
    '<div class="kv"><span>学科分区</span><b>' + charts.esc(nd.discipline) + '</b></div>' +
    '<div class="kv"><span>' + (side === 's' ? '发文数' : '被引次数') +
    '</span><b>' + nd.count + '</b></div>';
  h += '<h4>' + (side === 's' ? '主要引用去向' : '主要施引来源') + '</h4>';
  rel.slice(0, 12).forEach(f => {
    const o = other[side === 's' ? f.t : f.s];
    if (o) h += '<div class="kv small"><span>' + charts.esc(o.name.slice(0, 30)) +
      '</span><b>' + f.w + '</b></div>';
  });
  $('detailBody').innerHTML = h;
}

function showGeoDetail(n) {
  const res = S.geo; if (!res || !n) return;
  const partners = [];
  for (const e of res.edges) {
    if (e.source === n.id) partners.push([res.nodes[e.target].name, e.weight]);
    else if (e.target === n.id) partners.push([res.nodes[e.source].name, e.weight]);
  }
  partners.sort((a, b) => b[1] - a[1]);
  const years = Object.keys(n.years || {}).map(Number).sort((a, b) => a - b);
  const maxY = Math.max(1, ...years.map(y => n.years[y]));
  let bars = '';
  years.forEach(y => {
    bars += '<span style="display:inline-block;width:9px;vertical-align:bottom;' +
      'background:#3b82f6;margin-right:1px;height:' +
      Math.max(2, n.years[y] / maxY * 34) + 'px"></span>';
  });
  let h = '<h4>' + charts.esc(n.name) + '</h4>' +
    '<div class="kv"><span>发文量</span><b>' + n.count + '</b></div>' +
    '<div class="kv"><span>首现年 / 平均年</span><b>' + (n.first_year || '—') +
    ' / ' + (n.mean_year || '—') + '</b></div>' +
    '<div class="kv"><span>中介中心性</span><b>' + n.centrality.toFixed(4) + '</b></div>' +
    '<div class="kv"><span>合作国家/地区</span><b>' + n.degree + '</b></div>' +
    '<div class="kv"><span>聚类</span><b><span class="chip" style="background:' +
    window.vizColors.clusterColor(n.cluster) + '"></span>#' + n.cluster + '</b></div>';
  h += '<h4>逐年发文</h4><div style="height:36px">' + bars + '</div>';
  if (partners.length) {
    h += '<h4>主要合作伙伴</h4>';
    partners.slice(0, 12).forEach(p => {
      h += '<div class="kv small"><span>' + charts.esc(p[0]) + '</span><b>' + p[1] + '</b></div>';
    });
  }
  $('detailBody').innerHTML = h;
}

function showSVDetail(it) {
  const res = S.sv; if (!res || !it) return;
  let h = '<h4>' + charts.esc(it.label || it.key) + '</h4>' +
    '<div class="kv"><span>出现年份</span><b>' + it.year + '</b></div>' +
    '<div class="kv"><span>模块化变化 ΔM</span><b style="color:#c2410c">' +
    it.delta_m.toFixed(5) + '</b></div>' +
    '<div class="kv"><span>ΔM 变化率</span><b>' + it.delta_m_rate.toFixed(4) + '</b></div>' +
    '<div class="kv"><span>年内 z 值</span><b>' + (it.dm_z || 0).toFixed(2) + '</b></div>' +
    '<div class="kv"><span>年内排名</span><b>' + (it.rank_in_year + 1) + '</b></div>' +
    '<div class="kv"><span>聚类连接度</span><b>' + it.linkage + '</b></div>' +
    '<div class="kv"><span>当年连线数 / 权重</span><b>' + it.degree + ' / ' +
    it.strength + '</b></div>' +
    '<div class="kv"><span>结构偏移 JS</span><b>' + (it.divergence || 0).toFixed(4) + '</b></div>' +
    '<div class="kv"><span>节点总频次</span><b>' + it.count + '</b></div>';
  if (it.delta_m_full !== undefined) {
    h += '<div class="kv"><span>Louvain 复核 ΔM</span><b>' +
      it.delta_m_full.toFixed(5) + '</b></div>' +
      '<div class="kv"><span>复核连接度</span><b>' + it.linkage_full + '</b></div>';
  }
  h += '<div class="small muted" style="margin-top:8px">ΔM 越负，说明该节点接入后' +
    '网络的模块化程度下降越明显（把原本分离的聚类连到一起）；连接度越高，' +
    '说明它同时跨越越多既有聚类。</div>';
  $('detailBody').innerHTML = h;
}

/* ------------------------------- tabs --------------------------------- */
function switchView(name) {
  document.querySelectorAll('.tab').forEach(t =>
    t.classList.toggle('active', t.getAttribute('data-view') === name));
  document.querySelectorAll('.view').forEach(v =>
    v.classList.toggle('active', v.id === 'view-' + name));
  if (name === 'network') { netV.resize(); netV.fit(); netV.start(); }
  if (name === 'zone') { zoneV.resize(); zoneV.fit(); }
  if (name === 'overview') charts.renderHistogram($('histCanvas'),
    S.result ? S.result.year_hist : [], S.result ? S.result.slices : []);
  if (name === 'dual') {
    dualV.resize();
    if (S.dual) dualV.draw(); else runDual();
  }
  if (name === 'geo') { geoV.resize(); if (S.geo) geoV.draw(); else runGeo(); }
  if (name === 'sv') { if (S.sv) renderSV(); else runSV(); }
  if (name === 'topics') { if (S.topics) renderTopics(); else runTopics(); }
  if (name === 'citenet') { if (S.citenet) renderCiteNet(); else runCiteNet(); }
  if (name === 'forecast') { if (S.forecast) renderForecast(); else runForecast(); }
  if (name === 'kbca') { if (S.kbca) renderKBCA(); else runKBCA(); }
}

/* ------------------------------ exports ------------------------------- */
function dl(text, name, mime) {
  const b = new Blob([text], { type: mime || 'text/plain;charset=utf-8' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(b); a.download = name;
  document.body.appendChild(a); a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 400);
}
function csv(rows) {
  return '\ufeff' + rows.map(r => r.map(c => {
    const s = String(c == null ? '' : c);
    return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  }).join(',')).join('\r\n');
}
function exportData(kind) {
  const res = S.result;
  if (!res) { status('尚无分析结果可导出'); return; }
  const tag = res.summary.node_type + '_' + res.summary.year_min + '-' + res.summary.year_max;
  if (kind === 'csv-nodes') {
    dl(csv([['id', 'label', 'count', 'first_year', 'centrality', 'degree',
             'cluster', 'silhouette', 'burst_begin', 'burst_end', 'burst_strength']]
      .concat(res.nodes.map(n => [n.id, n.label, n.count, n.first_year, n.centrality,
        n.degree, n.cluster, n.silhouette,
        n.burst ? n.burst.begin : '', n.burst ? n.burst.end : '',
        n.burst ? n.burst.strength : '']))), 'nodes_' + tag + '.csv', 'text/csv');
  } else if (kind === 'csv-edges') {
    const lb = {}; res.nodes.forEach(n => lb[n.id] = n.label);
    dl(csv([['source', 'target', 'weight', 'source_label', 'target_label']]
      .concat(res.edges.map(e => [e.source, e.target, e.weight, lb[e.source], lb[e.target]]))),
      'edges_' + tag + '.csv', 'text/csv');
  } else if (kind === 'csv-cluster') {
    dl(csv([['id', 'size', 'silhouette', 'mean_year', 'label', 'terms', 'top_nodes']]
      .concat(res.clusters.map(c => [c.id, c.size, c.silhouette, c.mean_year, c.label,
        (c.terms || []).map(t => t.term + '(' + t.score + ')').join(' | '),
        (c.top_nodes || []).join(' | ')]))), 'clusters_' + tag + '.csv', 'text/csv');
  } else if (kind === 'csv-burst') {
    dl(csv([['label', 'begin', 'end', 'duration', 'strength', 'weight', 'count', 'peak']]
      .concat(res.bursts.map(b => [b.label, b.begin, b.end, b.duration, b.strength,
        b.weight, b.count, b.peak]))), 'bursts_' + tag + '.csv', 'text/csv');
  } else if (kind === 'graphml') {
    let x = '<?xml version="1.0" encoding="UTF-8"?>\n' +
      '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">\n' +
      '<key id="label" for="node" attr.name="label" attr.type="string"/>\n' +
      '<key id="count" for="node" attr.name="count" attr.type="int"/>\n' +
      '<key id="bc" for="node" attr.name="betweenness" attr.type="double"/>\n' +
      '<key id="cluster" for="node" attr.name="cluster" attr.type="int"/>\n' +
      '<key id="year" for="node" attr.name="first_year" attr.type="int"/>\n' +
      '<key id="w" for="edge" attr.name="weight" attr.type="double"/>\n' +
      '<graph edgedefault="undirected">\n';
    res.nodes.forEach(n => {
      x += '<node id="n' + n.id + '">' +
        '<data key="label">' + charts.esc(n.label) + '</data>' +
        '<data key="count">' + n.count + '</data>' +
        '<data key="bc">' + n.centrality + '</data>' +
        '<data key="cluster">' + n.cluster + '</data>' +
        '<data key="year">' + n.first_year + '</data></node>\n';
    });
    res.edges.forEach((e, i) => {
      x += '<edge source="n' + e.source + '" target="n' + e.target + '">' +
        '<data key="w">' + e.weight + '</data></edge>\n';
    });
    x += '</graph>\n</graphml>\n';
    dl(x, 'network_' + tag + '.graphml', 'application/xml');
  } else if (kind === 'json') {
    dl(JSON.stringify(res, null, 1), 'analysis_' + tag + '.json', 'application/json');
  } else if (kind === 'png-net') {
    switchView('network');
    const a = document.createElement('a');
    a.href = netV.toPNG(); a.download = 'network_' + tag + '.png';
    a.click();
  } else if (kind === 'png-dual') {
    if (!S.dual) { status('尚无双图叠加结果，请先打开该视图'); return; }
    switchView('dual');
    dualV.resize(); dualV.draw();
    const a = document.createElement('a');
    a.href = dualV.toPNG(); a.download = 'dualmap_' + tag + '.png'; a.click();
  } else if (kind === 'png-geo') {
    if (!S.geo) { status('尚无地理视图结果，请先打开该视图'); return; }
    switchView('geo');
    geoV.resize(); geoV.draw();
    const a = document.createElement('a');
    a.href = geoV.toPNG(); a.download = 'geoview_' + tag + '.png'; a.click();
  } else if (kind === 'csv-dual') {
    if (!S.dual) { status('尚无双图叠加结果'); return; }
    const d = S.dual;
    const sn = {}; d.sources.forEach(s => sn[s.id] = s.name);
    const tn = {}; d.targets.forEach(t => tn[t.id] = t.name);
    dl(csv([['citing_journal', 'citing_discipline', 'citing_docs',
             'cited_journal', 'cited_discipline', 'cited_count', 'citations']]
      .concat(d.flows.map(f => [sn[f.s], d.sources[f.s].discipline,
        d.sources[f.s].count, tn[f.t], d.targets[f.t].discipline,
        d.targets[f.t].count, f.w]))), 'dualmap_flows_' + tag + '.csv', 'text/csv');
  } else if (kind === 'csv-geo') {
    if (!S.geo) { status('尚无地理视图结果'); return; }
    dl(csv([['country', 'lat', 'lon', 'count', 'first_year', 'mean_year',
             'centrality', 'degree', 'cluster']]
      .concat(S.geo.nodes.map(n => [n.name, n.lat, n.lon, n.count,
        n.first_year || '', n.mean_year || '', n.centrality, n.degree,
        n.cluster]))), 'geo_countries_' + tag + '.csv', 'text/csv');
  } else if (kind === 'csv-sv') {
    if (!S.sv) { status('尚无结构变异结果'); return; }
    dl(csv([['year', 'label', 'count', 'delta_m', 'delta_m_rate', 'dm_z',
             'rank_in_year', 'linkage', 'degree', 'strength', 'divergence',
             'delta_m_full', 'linkage_full']]
      .concat(S.sv.items.map(i => [i.year, i.label, i.count, i.delta_m,
        i.delta_m_rate, i.dm_z || 0, i.rank_in_year, i.linkage, i.degree,
        i.strength, i.divergence || 0,
        i.delta_m_full === undefined ? '' : i.delta_m_full,
        i.linkage_full === undefined ? '' : i.linkage_full]))),
      'structvar_' + tag + '.csv', 'text/csv');
  } else if (kind === 'json-sv') {
    if (!S.sv) { status('尚无结构变异结果'); return; }
    dl(JSON.stringify(S.sv, null, 1), 'structvar_' + tag + '.json',
      'application/json');
  } else if (kind === 'png-zone') {
    switchView('zone');
    zoneV.resize(); zoneV.draw();
    const a = document.createElement('a');
    a.href = zoneV.toPNG(); a.download = ($('z_mode').value === 'timezone' ?
      'timezone_' : 'timeline_') + tag + '.png';
    a.click();
  } else if (kind === 'csv-topics') {
    if (!S.topics) { status('尚无主题建模结果'); return; }
    const t = S.topics;
    dl(csv([['topic_id', 'label', 'size', 'mean_year', 'coherence_umass',
             'coherence_pmi', 'top_terms']]
      .concat((t.topics || []).map(x => [x.id, x.label,
        x.n_docs === undefined ? x.size : x.n_docs, x.mean_year,
        x.coherence_umass, x.coherence_pmi,
        (x.terms || []).map(y => y[0] + ':' + y[1]).join(' | ')]))),
    'topics_' + tag + '.csv', 'text/csv');
  } else if (kind === 'json-topics') {
    if (!S.topics) { status('尚无主题建模结果'); return; }
    dl(JSON.stringify(S.topics, null, 1), 'topics_' + tag + '.json',
      'application/json');
  } else if (kind === 'csv-citenet') {
    if (!S.citenet) { status('尚无引文网络结果'); return; }
    const c = S.citenet;
    dl(csv([['title', 'year', 'journal', 'cluster', 'local_citations',
             'core', 'on_main_path', 'div_refs_variety', 'div_refs_balance',
             'div_refs_disparity', 'div_refs_rao', 'effective_size',
             'constraint']]
      .concat((c.rows || []).map(r => [r.title, r.year, r.journal, r.cluster,
        r.local_citations, r.core, r.on_main_path ? 1 : 0,
        r.div_refs_variety, r.div_refs_balance, r.div_refs_disparity,
        r.div_refs_rao, r.effective_size, r.constraint]))),
    'citenet_' + tag + '.csv', 'text/csv');
  } else if (kind === 'csv-forecast') {
    if (!S.forecast) { status('尚无趋势预测结果'); return; }
    const f = S.forecast;
    const rows = [['term', 'label', 'total', 'first_year', 'growth',
                   'persistence', 'novelty', 'uncertainty', 'emergence',
                   'rank', 'forecast_path']];
    (f.emergence || []).forEach(e => {
      const fc = (f.forecast || {})[e.term];
      rows.push([e.term, e.label, e.total, e.first_year, e.growth,
        e.persistence, e.novelty, e.uncertainty, e.emergence, e.rank,
        fc ? fc.forecast.join(' | ') : '']);
    });
    dl(csv(rows), 'forecast_' + tag + '.csv', 'text/csv');
  } else if (kind === 'csv-kbca') {
    if (!S.kbca) { status('尚无多维融合结果'); return; }
    const k = S.kbca;
    dl(csv([['rank', 'title', 'year', 'journal', 'cluster', 'composite',
             'structural', 'semantic', 'disruption', 'novelty',
             'interdisciplinarity', 'betweenness', 'degree', 'cited_by']]
      .concat((k.rows || []).map(r => [r.rank, r.title, r.year, r.journal,
        r.cluster, r.composite, r.structural, r.semantic, r.disruption,
        r.novelty, r.interdisciplinarity, r.betweenness, r.degree,
        r.cited_by]))), 'kbca_documents_' + tag + '.csv', 'text/csv');
  } else if (kind === 'json-kbca') {
    if (!S.kbca) { status('尚无多维融合结果'); return; }
    dl(JSON.stringify(S.kbca, null, 1), 'kbca_' + tag + '.json',
      'application/json');
  }
  status('已导出 ' + kind);
}

/* ------------------------------- wiring ------------------------------- */
function bind() {
  $('btnRun').addEventListener('click', runAnalysis);
  $('btnReload').addEventListener('click', () => { loadFiles(); });
  $('btnUpload').addEventListener('click', () => $('fileInput').click());
  $('fileInput').addEventListener('change', e => {
    if (e.target.files.length) uploadFiles(Array.from(e.target.files));
  });

  document.querySelectorAll('.tab').forEach(t =>
    t.addEventListener('click', () => switchView(t.getAttribute('data-view'))));

  // network toolbar
  ['n_labels', 'n_rings', 'n_cCirc', 'n_color', 'n_labelTop', 'n_scale']
    .forEach(id => $(id).addEventListener('change', () => netV.setOptions(netOpts())));
  $('n_relayout').addEventListener('click', () => { netV.layout(true); netV.fit(); netV.start(); });
  $('n_fit').addEventListener('click', () => netV.fit());
  $('n_pause').addEventListener('click', () => {
    if (netV.running) { netV.pause(); $('n_pause').textContent = '继续'; }
    else { netV.start(); $('n_pause').textContent = '暂停'; }
  });

  // zone toolbar
  ['z_mode', 'z_labels', 'z_rings', 'z_labelTop'].forEach(id =>
    $(id).addEventListener('change', () => { zoneV.setOptions(zoneOpts(), true); zoneV.fit(); }));
  $('z_fit').addEventListener('click', () => zoneV.fit());

  // burst
  $('b_apply').addEventListener('click', renderBurstView);

  // Pathfinder options are only meaningful for that pruning method
  const syncPf = () => {
    $('pfBox').style.display = $('p_pruning').value === 'pathfinder' ? '' : 'none';
  };
  $('p_pruning').addEventListener('change', syncPf);
  syncPf();

  // dual map
  $('d_run').addEventListener('click', () => runDual(true));
  ['d_minFlow', 'd_labelTop', 'd_curves'].forEach(id =>
    $(id).addEventListener('change', () => {
      if (S.dual) dualV.setOptions(dualOpts());
    }));
  $('d_matrix').addEventListener('change', () => {
    $('dualMatrix').hidden = !$('d_matrix').checked;
    if ($('d_matrix').checked) dualV.resize(), dualV.draw();
  });
  dualV.onSelect = (n, side) => showDualDetail(n, side);

  // geo
  $('g_run').addEventListener('click', () => runGeo(true));
  ['g_color', 'g_labels', 'g_grid', 'g_minW'].forEach(id =>
    $(id).addEventListener('change', () => {
      if (S.geo) { geoV.setOptions(geoOpts()); geoV.drawLegend(); }
    }));
  $('g_minCount').addEventListener('change', () => runGeo(true));
  $('g_fit').addEventListener('click', () => geoV.fit());
  geoV.onSelect = n => showGeoDetail(n);

  // structural variation
  $('s_run').addEventListener('click', () => runSV(true));
  $('s_nodeType').addEventListener('change', () => runSV(true));
  $('s_topFull').addEventListener('change', () => runSV(true));
  $('s_year').addEventListener('change', renderSVTable);
  $('s_minLink').addEventListener('change', renderSVTable);

  // ---- round-3 additions -------------------------------------------------
  $('t_run').addEventListener('click', () => runTopics());
  $('t_method').addEventListener('change', () => runTopics());
  $('t_k').addEventListener('change', () => runTopics());
  $('t_iter').addEventListener('change', () => runTopics());
  $('t_fields').addEventListener('change', () => runTopics());
  $('t_bigrams').addEventListener('change', () => runTopics());

  $('cn_run').addEventListener('click', () => runCiteNet());

  $('f_run').addEventListener('click', () => runForecast());
  $('f_nodeType').addEventListener('change', () => runForecast());
  $('f_top').addEventListener('change', () => runForecast());
  $('f_h').addEventListener('change', () => runForecast());
  $('f_ho').addEventListener('change', () => runForecast());

  $('k_run').addEventListener('click', () => runKBCA());
  $('k_topics').addEventListener('change', () => runKBCA());
  $('k_edges').addEventListener('change', () => runKBCA());
  $('k_perms').addEventListener('change', () => runKBCA());

  // clusters / nodes
  $('c_expand').addEventListener('change', () => {
    if (!S.result) return;
    charts.renderClusters($('clusterBox'), S.result.clusters,
      { expand: $('c_expand').checked });
  });
  $('clusterBox').addEventListener('click', e => {
    const tr = e.target.closest('tr'); if (!tr || !S.result) return;
    const c = S.result.clusters.find(x => String(x.id) === tr.getAttribute('data-id'));
    if (!c) return;
    let h = '<h4>#' + c.id + ' ' + charts.esc(c.label) + '</h4>' +
      '<div class="kv"><span>规模</span><b>' + c.size + '</b></div>' +
      '<div class="kv"><span>Silhouette</span><b>' + c.silhouette + '</b></div>' +
      '<div class="kv"><span>平均年份</span><b>' + c.mean_year + '</b></div>' +
      '<div class="kv"><span>含突现节点</span><b>' + (c.n_burst || 0) + '</b></div>' +
      '<h4>LLR 标签词</h4>';
    (c.terms || []).forEach(t => {
      h += '<div class="kv small"><span>' + charts.esc(t.term) + '</span><b>' +
        charts.fp(t.score, 1) + ' <span class="muted">(' + t.in + '/' + t.all + ')</span></b></div>';
    });
    h += '<h4>代表节点</h4><div class="small">' + charts.esc((c.top_nodes || []).join('; ')) + '</div>';
    $('detailBody').innerHTML = h;
  });
  $('nd_cluster').addEventListener('change', renderNodeTable);
  $('nd_search').addEventListener('input', renderNodeTable);
  $('nodeBox').addEventListener('click', e => {
    const th = e.target.closest('th');
    if (th) { S.nodeSort = th.getAttribute('data-s'); renderNodeTable(); return; }
  });

  document.querySelectorAll('[data-export]').forEach(b =>
    b.addEventListener('click', () => exportData(b.getAttribute('data-export'))));

  // any parameter change invalidates the current result
  document.querySelectorAll('#panel select, #panel input').forEach(el =>
    el.addEventListener('change', () => {
      if (S.result) status('参数已修改，点击「运行分析」重新计算');
    }));

  window.addEventListener('resize', () => {
    const v = document.querySelector('.tab.active').getAttribute('data-view');
    if (v === 'zone') zoneV.resize();
    if (v === 'dual') { dualV.resize(); dualV.draw(); }
    if (v === 'geo') { geoV.resize(); geoV.draw(); }
    if (v === 'sv' && S.sv) renderSV();
    if (v === 'topics' && S.topics) renderTopics();
    if (v === 'citenet' && S.citenet) renderCiteNet();
    if (v === 'forecast' && S.forecast) renderForecast();
    if (v === 'kbca' && S.kbca) renderKBCA();
  });
}

/* -------------------------------- boot -------------------------------- */
async function boot() {
  netV = new NetView($('netCanvas'), $('netWrap'), $('netTip'), $('netLegend'));
  zoneV = new NetView($('zoneCanvas'), $('zoneWrap'), $('zoneTip'), $('zoneLegend'));
  dualV = new DualMapView($('dualCanvas'), $('dualWrap'), $('dualTip'), $('dualLegend'));
  geoV = new GeoView($('geoCanvas'), $('geoWrap'), $('geoTip'), $('geoLegend'));
  netV.onSelect = n => showDetail(n);
  zoneV.onSelect = n => showDetail(n);
  bind();
  await loadFiles();
  status('就绪');
  if (S.files.length) runAnalysis();
}
window.addEventListener('DOMContentLoaded', boot);
})();
