# -*- coding: utf-8 -*-
"""
analyze.py -- the analysis pipeline.  Turns parsed documents into the JSON
payload consumed by the browser front end.

Steps (mirroring the CiteSpace workflow):

  1. time slicing              2. per-slice node frequency
  3. node selection (TopN / TopN% / g-index / threshold)
  4. network construction on the selected nodes
  5. pruning (MST / skeleton)
  6. weighted betweenness centrality (Brandes)
  7. Louvain clustering + silhouette
  8. LLR / MI cluster labelling
  9. Kleinberg burst detection on the yearly frequency series
"""

import os
import json
import time
import math
from collections import defaultdict, Counter

import wos_parser as wos
import network as net
import burst as burstmod
import labeling as lab

NODE_TYPES = ['ref', 'keyword', 'author', 'org', 'country', 'cited_journal',
              'category']

TYPE_LABEL = {
    'ref': 'Cited reference',
    'keyword': 'Keyword',
    'author': 'Author',
    'org': 'Institution',
    'country': 'Country',
    'cited_journal': 'Cited journal',
    'category': 'WoS category',
}


def _display_map(docs, node_type):
    """key -> human readable label (+ extra metadata for references)."""
    disp = {}
    meta = {}
    for d in docs:
        if node_type == 'ref':
            for r in d['refs']:
                k = r['key']
                if k not in disp:
                    a = (r.get('surname') or r['author'] or '').strip()
                    disp[k] = ('%s (%s) %s' % (a.upper()[:32],
                                               r['year'] or '?',
                                               (r['journal'] or '').title()[:40])).strip()
                    meta[k] = {'author': r['author'], 'year': r['year'],
                               'journal': r['journal'], 'raw': r['raw']}
        elif node_type == 'keyword':
            for k in d['keywords']:
                key = k.lower().strip()
                disp.setdefault(key, Counter())[k.strip()] += 1
        elif node_type == 'author':
            for a in d['authors']:
                key = a.lower().strip()
                disp.setdefault(key, Counter())[a.strip()] += 1
        elif node_type == 'org':
            for o in d['orgs']:
                key = o.lower().strip()
                disp.setdefault(key, Counter())[o.strip()] += 1
        elif node_type == 'country':
            for c in d['countries']:
                key = c.lower().strip()
                disp.setdefault(key, Counter())[c.strip()] += 1
        elif node_type == 'cited_journal':
            for r in d['refs']:
                if r['journal']:
                    key = r['journal'].lower().strip()
                    disp.setdefault(key, Counter())[r['journal'].strip()] += 1
        elif node_type == 'category':
            for c in d['categories']:
                key = c.lower().strip()
                disp.setdefault(key, Counter())[c.strip()] += 1

    if node_type != 'ref':
        disp = {k: (v.most_common(1)[0][0] if isinstance(v, Counter) else v)
                for k, v in disp.items()}
    return disp, meta


def _doc_items(docs, node_type):
    """list of item lists (duplicates kept) used for slicing and index."""
    out = []
    for d in docs:
        if node_type == 'ref':
            items = [r['key'] for r in d['refs'] if r['key'].split('|')[0]]
        elif node_type == 'keyword':
            items = [k.lower().strip() for k in d['keywords'] if k.strip()]
        elif node_type == 'author':
            items = [a.lower().strip() for a in d['authors'] if a.strip()]
        elif node_type == 'org':
            items = [o.lower().strip() for o in d['orgs'] if o.strip()]
        elif node_type == 'country':
            items = [c.lower().strip() for c in d['countries'] if c.strip()]
        elif node_type == 'cited_journal':
            items = [r['journal'].lower().strip()
                     for r in d['refs'] if r['journal']]
        else:
            items = [c.lower().strip() for c in d['categories'] if c.strip()]
        out.append(items)
    return out


def run(docs, params, log=None):
    t0 = time.time()

    def L(msg):
        if log is not None:
            log.append('[%6.1fs] %s' % (time.time() - t0, msg))

    node_type = params.get('node_type', 'keyword')
    slice_len = max(1, int(params.get('slice_len', 1) or 1))
    y_from = params.get('year_from')
    y_to = params.get('year_to')
    criterion = params.get('criterion', 'top')
    crit_val = params.get('criterion_value', 50)
    pruning = params.get('pruning', 'none')
    prune_k = int(params.get('prune_k', 3) or 3)
    normalize = params.get('normalize') or None
    min_count = int(params.get('min_count', 1) or 1)
    keep_lcc = bool(params.get('largest_component', True))
    resolution = float(params.get('cluster_resolution', 1.0) or 1.0)
    label_method = params.get('label_method', 'llr')
    label_source = params.get('label_source', 'all')
    b_gamma = float(params.get('burst_gamma', 1.0) or 1.0)
    b_base = float(params.get('burst_base', 2.0) or 2.0)
    b_min_dur = int(params.get('burst_min_duration', 2) or 2)
    cap = int(params.get('max_nodes', 500) or 500)

    # ---- filter by year -------------------------------------------------
    work = [d for d in docs if d['year']]
    if y_from:
        work = [d for d in work if d['year'] >= int(y_from)]
    if y_to:
        work = [d for d in work if d['year'] <= int(y_to)]
    L('year filter: %d / %d documents' % (len(work), len(docs)))
    if not work:
        return {'error': 'No documents left after year filtering.'}

    years = [d['year'] for d in work]
    y0, y1 = min(years), max(years)

    # ---- 1. time slicing ------------------------------------------------
    doc_items = _doc_items(work, node_type)
    # node -> documents that contain it (needed by the silhouette, the
    # cluster labels and by Pathfinder, so build it once up front)
    full_doc_index = defaultdict(list)
    for i, items in enumerate(doc_items):
        for it in set(items):
            full_doc_index[it].append(i)
    slices = []
    start = y0
    while start <= y1:
        end = start + slice_len - 1
        idxs = [i for i, d in enumerate(work) if start <= d['year'] <= end]
        cnt = Counter()
        for i in idxs:
            cnt.update(set(doc_items[i]))
        slices.append({'from': start, 'to': min(end, y1),
                       'n_docs': len(idxs), 'counter': cnt})
        start += slice_len
    L('%d time slices (%d-%d)' % (len(slices), y0, y1))

    # ---- 2/3. node selection -------------------------------------------
    selected = net.select_nodes(None, [s['counter'] for s in slices],
                                criterion, crit_val, global_cap=cap)
    if min_count > 1:
        selected = Counter({k: v for k, v in selected.items() if v >= min_count})
    node_set = set(selected)
    L('selected %d nodes (%s=%s)' % (len(node_set), criterion, crit_val))
    if not node_set:
        return {'error': 'No nodes survived the selection criterion.'}

    # ---- 4. network ------------------------------------------------------
    node_counter, edges, _ = net.build_edges(
        work, node_type, min_count=1, normalize=normalize,
        lowercase=True, restrict=node_set)
    L('raw network: %d nodes, %d edges' % (len(node_counter), len(edges)))

    edges_full = dict(edges)   # keep the unpruned network for silhouette
    if keep_lcc and edges:
        node_set2, edges = net.largest_component(list(node_counter.keys()), edges)
        L('largest component: %d nodes, %d edges' % (len(node_set2), len(edges)))
        nodes = node_set2
    else:
        nodes = list(node_counter.keys())
        if not edges:
            L('warning: no co-occurrence edge could be built (each document '
              'carries a single value of this node type) - showing '
              'frequency-ranked nodes only')

    doc_sets = {n: set(full_doc_index.get(n, ())) for n in nodes}

    if pruning and pruning != 'none':
        if pruning == 'pathfinder':
            import pathfinder as pf
            pf_r = params.get('pf_r', 2.0)
            pf_r = float('inf') if pf_r in (None, '', 'inf') else float(pf_r)
            pf_q = params.get('pf_q') or None
            pf_q = None if pf_q in (None, '', 0) else int(pf_q)
            pf_metric = params.get('pf_metric', 'count')
            pf_cap = int(params.get('pf_max_nodes', 300) or 300)
            dist = pf.distance_matrix(nodes, doc_sets, metric=pf_metric,
                                      counts=edges)
            kept = pf.pfnet(nodes, dist, q=pf_q, r=pf_r, max_nodes=pf_cap)
            # PFNET may keep a pair that never co-occurs (typically two
            # nodes that are otherwise disconnected); those carry no
            # bibliometric evidence and are dropped here.
            dropped = 0
            out = {}
            for k in kept:
                w = edges.get(k, edges.get((k[1], k[0])))
                if w:
                    out[k if k in edges else (k[1], k[0])] = w
                else:
                    dropped += 1
            edges = out
            L('pathfinder (r=%s, q=%s, %s): %d edges kept, %d without '
              'co-occurrence dropped' % (pf_r, pf_q or 'n-1', pf_metric,
                                         len(edges), dropped))
        else:
            edges = net.prune(nodes, edges, pruning, prune_k)
            L('after pruning (%s): %d edges' % (pruning, len(edges)))

    # ---- 5. yearly series + bursts --------------------------------------
    node_lookup = set(nodes)
    per_year = defaultdict(Counter)
    first_year = {}
    for d, items in zip(work, doc_items):
        y = d['year']
        for it in set(items):
            if it in node_lookup:
                per_year[it][y] += 1
                if it not in first_year or y < first_year[it]:
                    first_year[it] = y

    disp, ref_meta = _display_map(work, node_type)

    burst_res = burstmod.detect_all(
        {n: dict(per_year.get(n, {})) for n in nodes},
        base=b_base, gamma=b_gamma, min_duration=b_min_dur)
    bursts = burstmod.top_bursts(burst_res, limit=None)
    for b in bursts:
        b['label'] = disp.get(b['term'], b['term'])
    L('burst detection done: %d bursts' % len(bursts))

    # ---- 6. centrality ---------------------------------------------------
    L('computing betweenness on %d nodes ...' % len(nodes))
    bc = net.betweenness_centrality(nodes, edges, normalized=True)
    deg = net.degree_centrality(nodes, edges)
    L('centrality done')

    # ---- 7. clustering ---------------------------------------------------
    communities = net.louvain_full(nodes, edges, resolution=resolution)
    L('louvain: %d communities, Q=%.4f'
      % (len(communities), net.modularity(nodes, edges, communities)))

    # ---- 8. document incidence (silhouette + labelling) -------------------
    doc_index = {n: full_doc_index.get(n, []) for n in nodes}
    sil = net.silhouette(nodes, edges_full, communities, doc_sets=doc_sets)
    L('silhouette done')

    use_kw = label_source in ('all', 'keywords')
    use_ti = label_source in ('all', 'title')
    use_ab = label_source in ('all', 'abstract', 'title_abstract')
    if label_source == 'title':
        use_ab = False
    if label_source == 'abstract':
        use_ti = False
    doc_terms, df = lab.build_term_index(work, use_title=use_ti,
                                         use_abstract=use_ab,
                                         use_keywords=use_kw, min_df=2)
    labels = lab.label_all(communities, doc_index, doc_terms, df,
                           len(work), top_k=8, method=label_method)
    L('cluster labelling done')

    # ---- assemble --------------------------------------------------------
    comm_of = {}
    for ci, c in enumerate(communities):
        for n in c:
            comm_of[n] = ci

    node_out = []
    for i, n in enumerate(nodes):
        years_counts = dict(per_year.get(n, {}))
        b = burst_res.get(n, {})
        bz = b.get('bursts', [])
        bz = max(bz, key=lambda x: x['strength']) if bz else None
        tot_y = sum(years_counts.values()) or 1
        mean_year = sum(int(y) * c for y, c in years_counts.items()) / float(tot_y)
        node_out.append({
            'id': i,
            'key': n,
            'label': disp.get(n, n),
            'count': int(node_counter.get(n, 0)),
            'first_year': first_year.get(n, y0),
            'mean_year': round(mean_year, 2),
            'years': years_counts,
            'centrality': round(bc.get(n, 0.0), 5),
            'degree': deg.get(n, {}).get('degree', 0),
            'strength': round(deg.get(n, {}).get('strength', 0.0), 3),
            'cluster': comm_of.get(n, 0),
            'silhouette': round(sil.get(n, 0.0), 3),
            'burst': bz,
            'meta': ref_meta.get(n),
        })
    node_out.sort(key=lambda x: (-x['count'], x['label']))

    id_of = {n: i for i, n in enumerate(nodes)}
    edge_out = [{'source': id_of[a], 'target': id_of[b],
                 'weight': round(float(w), 4)}
                for (a, b), w in edges.items()
                if a in id_of and b in id_of]

    cluster_out = []
    for ci, c in enumerate(communities):
        members = [node_out[id_of[n]] for n in c if n in id_of]
        if not members:
            continue
        # weighted average of the members' mean activity year
        mean_year = sum(m['count'] * m['mean_year'] for m in members) / \
            float(sum(m['count'] for m in members) or 1)
        info = labels.get(ci, {})
        cluster_out.append({
            'id': ci,
            'size': len(members),
            'label': info.get('label', 'cluster %d' % ci),
            'terms': info.get('terms', []),
            'mean_year': round(mean_year, 1),
            'silhouette': round(sum(m['silhouette'] for m in members) /
                                float(len(members)), 3),
            'top_nodes': [m['label'] for m in
                          sorted(members, key=lambda x: -x['count'])[:5]],
            'n_burst': sum(1 for m in members if m['burst']),
        })
    cluster_out.sort(key=lambda x: (-x['size'], x['id']))

    # re-map cluster ids to a stable, size-ordered sequence
    remap = {c['id']: i for i, c in enumerate(cluster_out)}
    for nd in node_out:
        nd['cluster'] = remap.get(nd['cluster'], 0)
    for c in cluster_out:
        c['id'] = remap[c['id']]

    year_hist = Counter(d['year'] for d in work)
    slices_out = [{'from': s['from'], 'to': s['to'], 'n_docs': s['n_docs'],
                   'n_nodes': len([k for k in s['counter'] if k in set(nodes)])}
                  for s in slices]

    L('done')
    return {
        'params': params,
        'summary': {
            'n_docs': len(work),
            'n_docs_total': len(docs),
            'year_min': y0, 'year_max': y1,
            'n_nodes': len(node_out),
            'n_edges': len(edge_out),
            'n_clusters': len(cluster_out),
            'modularity': round(net.modularity(nodes, edges, communities), 4),
            'node_type': node_type,
            'node_type_label': TYPE_LABEL.get(node_type, node_type),
            'n_bursts': len(bursts),
            'density': round(2.0 * len(edge_out) /
                             max(1, len(node_out) * (len(node_out) - 1)), 5),
        },
        'nodes': node_out,
        'edges': edge_out,
        'clusters': cluster_out,
        'bursts': bursts,
        'slices': slices_out,
        'year_hist': sorted(year_hist.items()),
        'log': log or [],
        'elapsed': round(time.time() - t0, 2),
    }


def run_files(paths, params, log=None):
    docs, meta = wos.parse_files(paths)
    log = log if log is not None else []
    log.append('[  0.0s] parsed %d files -> %d records'
               % (len(meta['files']), len(docs)))
    res = run(docs, params, log)
    res['summary_dataset'] = wos.summarise(docs)
    res['files'] = meta['files']
    return res
