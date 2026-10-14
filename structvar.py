# -*- coding: utf-8 -*-
"""
structvar.py -- structural variation analysis.

Which newly appearing nodes actually change the shape of a network?

For every time slice the cumulative network built from everything that
appeared *before* the slice is taken as the baseline.  Each node that shows
up in the slice is then grafted on -- alone -- with the links it forms in
that slice, and three quantities are recorded:

  delta_m      modularity change, Q(after) - Q(before).  Adding a node that
               bridges otherwise separate clusters *lowers* modularity, so
               a strongly negative delta_m marks a structurally
               transformative contribution.
  linkage      cluster linkage -- how many different clusters of the
               baseline partition the new node attaches to.  High linkage
               means the node spans fields.
  divergence   Jensen-Shannon divergence between the cluster size
               distribution before and after the insertion (how much the
               cluster structure is rearranged).

`delta_m` is first evaluated with the baseline partition held fixed and the
new node as a singleton -- that is exact for that particular partition and
costs O(deg).  The `top_full` strongest candidates per slice are then
re-checked with a full Louvain re-clustering, because a transformative node
can also *merge* communities and the fixed-partition estimate cannot see
that.

Honest caveat: CiteSpace's own structural variation view additionally plots
a centrality-divergence axis based on betweenness recomputation; recomputing
Brandes betweenness once per candidate node is O(V*E) per candidate and is
not affordable in pure Python, so this module reports the cluster-structure
divergence instead of the betweenness divergence.
"""

import math
from collections import defaultdict, Counter

import network as net
import analyze as az


# --------------------------------------------------------------------------
# modularity of a fixed partition
# --------------------------------------------------------------------------

def modularity_of(nodes, edges, comm_of):
    """Q for an explicitly given partition (see network.modularity)."""
    deg = defaultdict(float)
    for (a, b), w in edges.items():
        w = float(w)
        deg[a] += w
        deg[b] += w
    m2 = sum(deg.values())
    if m2 <= 0:
        return 0.0
    inn = defaultdict(float)
    for (a, b), w in edges.items():
        w = float(w)
        ca, cb = comm_of.get(a, -1), comm_of.get(b, -1)
        if ca == cb and ca >= 0:
            inn[ca] += 2.0 * w
    tot = defaultdict(float)
    for n, v in deg.items():
        tot[comm_of.get(n, -1)] += v
    q = 0.0
    for c in set(list(inn.keys()) + list(tot.keys())):
        q += inn.get(c, 0.0) / m2 - (tot.get(c, 0.0) / m2) ** 2
    return q


def _removal_delta(nodes, edges, comm_of, new_links, m_before):
    """
    CiteSpace's delta-M: the modularity gain obtained by REMOVING the newly
    added node, i.e.  M(baseline) - M(baseline + node as its own community).

    A node that bridges existing communities lowers modularity, so removing
    it raises it and delta-M is positive -- the larger delta-M the more
    transformative the node.  Nodes that sit inside one community give a
    negative delta-M.  Exact and O(deg + #clusters).
    """
    deg = defaultdict(float)
    for (a, b), w in edges.items():
        w = float(w)
        deg[a] += w
        deg[b] += w
    m2 = sum(deg.values())
    if m2 <= 0:
        return 0.0
    inn = defaultdict(float)
    for (a, b), w in edges.items():
        w = float(w)
        ca, cb = comm_of.get(a, -1), comm_of.get(b, -1)
        if ca == cb and ca >= 0:
            inn[ca] += 2.0 * w
    tot = defaultdict(float)
    for n, v in deg.items():
        tot[comm_of.get(n, -1)] += v

    k_new = sum(float(w) for w in new_links.values())
    m2n = m2 + 2.0 * k_new
    per_comm = defaultdict(float)
    for u, w in new_links.items():
        per_comm[comm_of.get(u, -1)] += float(w)

    q = 0.0
    for c in set(list(inn.keys()) + list(tot.keys()) + list(per_comm.keys())):
        if c < 0:
            continue
        q += inn.get(c, 0.0) / m2n - ((tot.get(c, 0.0) + per_comm.get(c, 0.0)) / m2n) ** 2
    q -= (k_new / m2n) ** 2
    return m_before - q


def _js_divergence(p, q):
    """Jensen-Shannon divergence (base 2) of two dicts of counts."""
    keys = set(p) | set(q)
    sp = float(sum(p.values())) or 1.0
    sq = float(sum(q.values())) or 1.0
    d = 0.0
    for k in keys:
        a = p.get(k, 0) / sp
        b = q.get(k, 0) / sq
        m = 0.5 * (a + b)
        if a > 0:
            d += 0.5 * a * math.log(a / m, 2) if m > 0 else 0.0
        if b > 0:
            d += 0.5 * b * math.log(b / m, 2) if m > 0 else 0.0
    return d


# --------------------------------------------------------------------------
# main entry
# --------------------------------------------------------------------------

def run(docs, params, log=None):
    def L(m):
        if log is not None:
            log.append('[structvar] %s' % m)

    node_type = params.get('node_type', 'ref')
    slice_len = max(1, int(params.get('slice_len', 1) or 1))
    criterion = params.get('criterion', 'top')
    crit_val = params.get('criterion_value', 30)
    cap = int(params.get('max_nodes', 400) or 400)
    min_count = int(params.get('min_count', 1) or 1)
    _tf = params.get('sv_top_full', 10)
    top_full = 10 if _tf is None or _tf == '' else int(_tf)
    resolution = float(params.get('cluster_resolution', 1.0) or 1.0)

    work = [d for d in docs if d.get('year')]
    if params.get('year_from'):
        work = [d for d in work if d['year'] >= int(params['year_from'])]
    if params.get('year_to'):
        work = [d for d in work if d['year'] <= int(params['year_to'])]
    if not work:
        return {'error': '没有可用的文献。'}
    y0, y1 = min(d['year'] for d in work), max(d['year'] for d in work)

    doc_items = az._doc_items(work, node_type)

    # ---- selection over the whole period --------------------------------
    slices = []
    start = y0
    while start <= y1:
        end = min(start + slice_len - 1, y1)
        cnt = Counter()
        for i, d in enumerate(work):
            if start <= d['year'] <= end:
                cnt.update(set(doc_items[i]))
        slices.append({'from': start, 'to': end, 'counter': cnt})
        start += slice_len
    selected = net.select_nodes(None, [s['counter'] for s in slices],
                                criterion, crit_val, global_cap=cap)
    if min_count > 1:
        selected = Counter({k: v for k, v in selected.items()
                            if v >= min_count})
    node_set = set(selected)
    L('%d nodes selected over %d-%d' % (len(node_set), y0, y1))
    if len(node_set) < 10:
        return {'error': '节点太少（%d），无法做结构变异分析。' % len(node_set)}

    # ---- first appearance ------------------------------------------------
    first_year = {}
    count_of = Counter()
    for d, items in zip(work, doc_items):
        y = d['year']
        for it in set(items):
            if it in node_set:
                count_of[it] += 1
                if it not in first_year or y < first_year[it]:
                    first_year[it] = y

    disp, _ = az._display_map(work, node_type)

    # ---- incremental cumulative network ----------------------------------
    docs_by_year = defaultdict(list)
    for i, d in enumerate(work):
        docs_by_year[d['year']].append(i)

    def edges_of(idxs):
        c = defaultdict(int)
        for i in idxs:
            items = sorted(set(it for it in doc_items[i] if it in node_set))
            for a_i in range(len(items)):
                for b_i in range(a_i + 1, len(items)):
                    a, b = items[a_i], items[b_i]
                    c[(a, b) if a < b else (b, a)] += 1
        return c

    cum = defaultdict(int)
    items = []
    year_stats = []

    for y in range(y0, y1 + 1):
        idxs = docs_by_year.get(y, [])
        e_new = edges_of(idxs)
        new_nodes = [n for n in first_year if first_year[n] == y]
        # NOTE: the baseline is the network *before* this slice, so the
        # current slice's edges are only folded into `cum` at the end.
        if not cum or not new_nodes:
            for k, v in e_new.items():
                cum[k] += v
            year_stats.append({'year': y, 'n_new': len(new_nodes),
                               'n_scored': 0, 'max_dm': 0.0,
                               'min_dm': 0.0, 'max_linkage': 0})
            continue

        base_edges = dict(cum)
        nodes_now = set()
        for (a, b) in base_edges:
            nodes_now.add(a)
            nodes_now.add(b)
        if len(nodes_now) < 8:
            year_stats.append({'year': y, 'n_new': len(new_nodes),
                               'n_scored': 0, 'max_dm': 0.0,
                               'min_dm': 0.0, 'max_linkage': 0})
            continue
        comms = net.louvain_full(list(nodes_now), base_edges,
                                 resolution=resolution)
        comm_of = {}
        for ci, c in enumerate(comms):
            for n in c:
                comm_of[n] = ci
        m_before = modularity_of(nodes_now, base_edges, comm_of)
        size_before = Counter(comm_of.values())

        scored = []
        for v in new_nodes:
            links = {}
            for (a, b), w in e_new.items():
                if a == v and b in comm_of:
                    links[b] = links.get(b, 0) + w
                elif b == v and a in comm_of:
                    links[a] = links.get(a, 0) + w
            if not links:
                continue
            dm = _removal_delta(nodes_now, base_edges, comm_of,
                                links, m_before)
            linkage = len(set(comm_of[u] for u in links))
            size_after = Counter(comm_of.values())
            size_after[max(size_after) + 1 if size_after else 0] = 1
            div = _js_divergence(size_before, size_after)
            scored.append({
                'year': y, 'key': v, 'label': disp.get(v, v),
                'count': count_of.get(v, 0),
                'degree': len(links),
                'strength': sum(links.values()),
                'delta_m': round(dm, 5),
                'delta_m_rate': round(dm / m_before, 5) if m_before else 0.0,
                'linkage': linkage,
                'divergence': round(div, 5),
                'full': False,
                'links': links,
            })
        if not scored:
            for k, v in e_new.items():
                cum[k] += v
            year_stats.append({'year': y, 'n_new': len(new_nodes),
                               'n_scored': 0, 'max_dm': 0.0,
                               'min_dm': 0.0, 'max_linkage': 0})
            continue

        # ---- full Louvain re-check for the strongest candidates ---------
        scored.sort(key=lambda x: x['delta_m'])
        for rec in scored[:top_full]:
            aug = dict(base_edges)
            for u, w in rec['links'].items():
                k = (rec['key'], u) if rec['key'] < u else (u, rec['key'])
                aug[k] = aug.get(k, 0) + w
            nodes_aug = list(nodes_now) + [rec['key']]
            comms2 = net.louvain_full(nodes_aug, aug, resolution=resolution)
            cof2 = {}
            for ci, c in enumerate(comms2):
                for n in c:
                    cof2[n] = ci
            m2 = modularity_of(nodes_aug, aug, cof2)
            rec['delta_m_full'] = round(m_before - m2, 5)
            rec['delta_m_full_rate'] = round((m_before - m2) / m_before, 5) \
                if m_before else 0.0
            rec['linkage_full'] = len(set(cof2[u] for u in rec['links']
                                          if u in cof2))
            rec['full'] = True

        # ---- within-slice standardisation --------------------------------
        # ΔM is only comparable inside one slice (it depends on the baseline
        # network), so every node also gets a z score and a rank inside its
        # own slice.
        dms = [r['delta_m'] for r in scored]
        mu = sum(dms) / len(dms)
        sd = (sum((d - mu) ** 2 for d in dms) / len(dms)) ** 0.5
        scored.sort(key=lambda x: -x['delta_m'])
        for i, r in enumerate(scored):
            r['dm_z'] = round((r['delta_m'] - mu) / sd, 3) if sd > 1e-12 else 0.0
            r['rank_in_year'] = i

        items.extend(scored)
        for k, v in e_new.items():
            cum[k] += v
        year_stats.append({
            'year': y,
            'n_new': len(new_nodes),
            'n_scored': len(scored),
            'max_dm': round(max(r['delta_m'] for r in scored), 5),
            'min_dm': round(min(r['delta_m'] for r in scored), 5),
            'mean_dm': round(sum(r['delta_m'] for r in scored) / len(scored), 5),
            'max_linkage': max(r['linkage'] for r in scored),
            'm_before': round(m_before, 4),
        })
        L('%d: %d new nodes, %d scored, ΔM in [%.4f, %.4f]'
          % (y, len(new_nodes), len(scored),
             year_stats[-1]['min_dm'], year_stats[-1]['max_dm']))

    # strip the heavy per-node link dictionaries before serialising
    for rec in items:
        rec.pop('links', None)

    if not items:
        return {'error': '没有可以评估的新增节点（可能每个切片的新节点都没有形成连线）。'}

    items.sort(key=lambda x: -x['delta_m'])
    for i, rec in enumerate(items):
        rec['rank'] = i
    summary = {
        'n_years': len([s for s in year_stats if s['n_scored']]),
        'n_items': len(items),
        'node_type': node_type,
        'year_min': y0, 'year_max': y1,
        'n_nodes': len(node_set),
        'most_transformative': items[0]['label'] if items else '',
    }
    return {'items': items, 'years': year_stats, 'summary': summary,
            'params': params}


if __name__ == '__main__':
    # Two dense blocks (a "liver" side and a "sepsis" side) that live apart
    # until 2020, when a bridging study drags them together.  The bridge
    # keyword must come out as the most structurally transformative item.
    import random
    rnd = random.Random(11)
    A = ['alpha', 'beta', 'gamma', 'delta', 'eta']
    B = ['theta', 'iota', 'kappa', 'lambda', 'mu']

    def rec(y, kws):
        kws = list(kws)
        rnd.shuffle(kws)
        return {'year': y, 'keywords': kws[:4], 'title': '', 'abstract': '',
                'journal': '', 'authors': [], 'orgs': [], 'countries': [],
                'categories': [], 'refs': []}

    docs = []
    for y in range(2015, 2019):
        for _ in range(8):
            docs.append(rec(y, A))
        for _ in range(8):
            docs.append(rec(y, B))
    for _ in range(10):
        docs.append(rec(2020, ['alpha', 'theta', 'bridge']))
    for _ in range(6):
        docs.append(rec(2021, A))
        docs.append(rec(2021, B))
    res = run(docs, {'node_type': 'keyword', 'criterion': 'top',
                     'criterion_value': 30}, [])
    print('summary:', res['summary'])
    print('year stats:')
    for s in res['years']:
        print('   ', s)
    print('most transformative:')
    for r in res['items'][:5]:
        print('   %-8s ΔM=%+.4f (rate %+.3f) linkage=%d div=%.4f full=%s'
              % (r['label'], r['delta_m'], r['delta_m_rate'], r['linkage'],
                 r['divergence'], r['full']))

    top = res['items'][0]
    assert top['label'] == 'bridge', 'bridge should be the top item, got %s' \
        % top['label']
    assert top['delta_m'] > 0, 'a bridging node must give a positive ΔM'
    assert top['linkage'] == 2, 'bridge should reach 2 clusters, got %s' \
        % top['linkage']
    print('\nOK: bridge is top, ΔM>0, linkage=2')
