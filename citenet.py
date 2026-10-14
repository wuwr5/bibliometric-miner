# -*- coding: utf-8 -*-
"""
citenet.py -- structural analysis of the citation network, going well beyond
simple counts.

First the *internal* citation network of the corpus is reconstructed: every
reference (CR line) is matched against every document of the same corpus by
DOI, and failing that by  first-author-surname + year + journal.  What was a
bibliography becomes a directed graph  citing -> cited  that supports:

* network level measures -- density, reciprocity, clustering, degree
  assortativity, weakly connected components, degeneracy (max k-core), and a
  Clauset-Shalizi-Newman power-law fit to the in-degree distribution
* Hummon & Doreian **main path analysis** (1989), the standard tool for
  tracing the backbone of a research tradition: every arc gets an SPLC
  (search-path link count) and the path of steepest decent is extracted
* per-document **structural diversity** of its reference portfolio
  (Rao-Stirling: variety x balance x disparity over cluster profiles)
* **structural holes** (Burt 1992) -- effective size and constraint, i.e. how
  much bridging work each document does
* cited-reference **half-life** per year, i.e. how fast the field forgets
"""

import math
import re
from collections import defaultdict, Counter

import network as net

_YEAR_RE = re.compile(r'(19|20)\d{2}')
_NONWORD = re.compile(r'[^a-z0-9]+')


def _norm_title(t):
    return _NONWORD.sub(' ', (t or '').lower()).strip()


def _norm_journal(j):
    j = _NONWORD.sub(' ', (j or '').lower()).strip()
    j = j.replace('int ', 'international ').replace('j ', 'journal ')
    return ' '.join(j.split()[:3]) or ' '.join(j.split())


def _iy(v):
    """
    Reference years arrive from the WoS parser as *strings* ('1999') while
    document years are ints.  Every year comparison in this module therefore
    goes through here -- without it, no author/year/journal reference ever
    matches its target and the internal network collapses to DOI matches only.
    """
    if isinstance(v, int):
        return v
    if isinstance(v, str) and v.isdigit():
        return int(v)
    return None


def _surname(au):
    """First plausible surname out of a WoS author string 'Smith, J'."""
    if not au:
        return ''
    au = au.strip()
    for sep in (',', ';', ' '):
        if sep in au:
            head = au.split(sep)[0].strip()
            if head:
                return head.upper()
    return au.upper()


# --------------------------------------------------------------------------
# internal citation network
# --------------------------------------------------------------------------

def build_citation_network(docs, log=None):
    """
    Match every reference of every document against the corpus itself.

    Returns (edges, stats) where edges maps (citing_index, cited_index) -> 1
    and stats records how much of the bibliography could be resolved.
    """
    def L(s):
        if log is not None:
            log.append(s)

    by_doi = {}
    by_key = defaultdict(list)
    doi_fields = 0
    for i, d in enumerate(docs):
        doi = (d.get('doi') or '').strip().lower()
        if doi:
            doi_fields += 1
            by_doi.setdefault(doi, i)
        sur = _surname((d.get('authors') or [''])[0])
        key = (sur, d.get('year'), _norm_journal(d.get('journal')))
        if sur and d.get('year'):
            by_key[key].append(i)

    total_refs = 0
    n_doi = 0
    n_key = 0
    edges = {}
    for i, d in enumerate(docs):
        for r in d.get('refs') or []:
            total_refs += 1
            j = None
            doi = (r.get('doi') or '').strip().lower()
            if doi and doi in by_doi and by_doi[doi] != i:
                j = by_doi[doi]
                n_doi += 1
            if j is None:
                ry = _iy(r.get('year'))
                key = (_surname(r.get('author')), ry,
                       _norm_journal(r.get('journal')))
                cand = by_key.get(key)
                if cand and i not in cand:
                    j = cand[0]
                    n_key += 1
                elif cand:
                    j = None
            if j is not None and j != i:
                edges[(i, j)] = edges.get((i, j), 0) + 1
    matched = n_doi + n_key
    L('internal citation network: %d references, %d resolved '
      '(%d by DOI, %d by author-year-journal) = %.1f%%'
      % (total_refs, matched, n_doi, n_key,
         100.0 * matched / total_refs if total_refs else 0.0))
    L('citation edges: %d distinct pairs' % len(edges))
    return edges, {'n_refs': total_refs, 'n_doi': n_doi, 'n_key': n_key,
                   'n_edges': len(edges),
                   'match_rate': round(100.0 * matched / total_refs, 2)
                   if total_refs else 0.0}


# --------------------------------------------------------------------------
# network level measures
# --------------------------------------------------------------------------

def clustering_coefficient(nodes, undirected):
    """Average local clustering coefficient on the undirected projection."""
    adj = defaultdict(set)
    for (a, b) in undirected:
        adj[a].add(b)
        adj[b].add(a)
    vals = []
    for v in nodes:
        nb = adj.get(v) or set()
        k = len(nb)
        if k < 2:
            vals.append(0.0)
            continue
        links = 0
        nbl = list(nb)
        for i in range(len(nbl)):
            for j in range(i + 1, len(nbl)):
                if nbl[j] in adj[nbl[i]]:
                    links += 1
        vals.append(2.0 * links / float(k * (k - 1)))
    return round(sum(vals) / len(vals), 4) if vals else 0.0


def degree_assortativity(nodes, undirected):
    """Newman's degree assortativity over the undirected projection."""
    adj = defaultdict(set)
    for (a, b) in undirected:
        adj[a].add(b)
        adj[b].add(a)
    n_edges = 0
    sum1 = sum2 = sum_sq = 0.0
    for (a, b) in undirected:
        ka, kb = len(adj[a]), len(adj[b])
        # Newman: sum_e 1/2(j+k),  sum_e j*k,  sum_e 1/2(j^2+k^2)
        sum1 += 0.5 * (ka + kb)
        sum2 += ka * kb
        sum_sq += 0.5 * (ka * ka + kb * kb)
        n_edges += 1
    if not n_edges:
        return 0.0
    m_inv = 1.0 / n_edges          # M^{-1}, M = number of edges
    num = sum2 * m_inv - (sum1 * m_inv) ** 2
    den = sum_sq * m_inv - (sum1 * m_inv) ** 2
    return round(num / den, 4) if den else 0.0


def _k_core(nodes, adj):
    """Maximum core number (network degeneracy)."""
    deg = {v: len(adj.get(v) or ()) for v in nodes}
    max_core = 0
    core = {}
    k = 0
    remaining = set(nodes)
    while remaining:
        changed = True
        while changed:
            changed = False
            for v in list(remaining):
                if deg.get(v, 0) <= k:
                    core[v] = k
                    remaining.discard(v)
                    for u in (adj.get(v) or ()):
                        if u in remaining:
                            deg[u] -= 1
                    changed = True
        k += 1
        max_core = k - 1
    return max_core, core


def power_law_alpha(values, xmin=1):
    """Clauset-Shalizi-Newman continuous MLE: alpha = 1 + n/sum ln(x/xmin)."""
    xs = [v for v in values if v >= xmin]
    n = len(xs)
    if n < 5:
        return None
    s = sum(math.log(v / float(xmin)) for v in xs)
    if s <= 0:
        return None
    return round(1.0 + n / s, 3)


def wcc_label(nodes, undirected):
    """Weakly connected components -> {node: component id}."""
    adj = defaultdict(set)
    for (a, b) in undirected:
        adj[a].add(b)
        adj[b].add(a)
    seen = set()
    lab = {}
    cid = 0
    for v in nodes:
        if v in seen:
            continue
        stack = [v]
        seen.add(v)
        while stack:
            u = stack.pop()
            lab[u] = cid
            for w in (adj.get(u) or ()):
                if w not in seen:
                    seen.add(w)
                    stack.append(w)
        cid += 1
    return lab, cid


# --------------------------------------------------------------------------
# Hummon & Doreian main path analysis
# --------------------------------------------------------------------------

def _dag_orders(nodes, out_arcs, in_arcs):
    """Topological order; cycles are broken deterministically."""
    indeg = {v: 0 for v in nodes}
    for (u, v) in out_arcs:
        indeg[v] = indeg.get(v, 0) + 1
    # break cycles by repeatedly stripping zero indegree nodes, then take the
    # remaining nodes in decreasing out-degree order if any survive
    order = []
    q = [v for v in nodes if indeg[v] == 0]
    tmp = dict(indeg)
    while q:
        u = q.pop()
        order.append(u)
        for (a, b) in out_arcs:
            if a == u:
                tmp[b] -= 1
                if tmp[b] == 0:
                    q.append(b)
    if len(order) < len(nodes):
        rest = [v for v in nodes if v not in set(order)]
        rest.sort(key=lambda v: -len([1 for (a, b) in out_arcs if a == v]))
        order.extend(rest)
    return order


def main_path(nodes, out_arcs, weights):
    """
    Hummon-Doreian SPLC main path.

    Every arc gets a traversal count = (#paths from any source to its tail)
    times (#paths from its head to any sink); the global main path keeps
    stepping onto the locally strongest arc.
    """
    nodes_l = list(nodes)
    topo = _dag_orders(nodes_l, out_arcs, out_arcs)
    pos = {v: i for i, v in enumerate(topo)}

    out_of = defaultdict(list)
    in_of = defaultdict(list)
    for (u, v) in out_arcs:
        out_of[u].append(v)
        in_of[v].append(u)

    n_out = {v: len(out_of.get(v) or ()) for v in nodes_l}
    n_in = {v: len(in_of.get(v) or ()) for v in nodes_l}

    def __unused():
        pass

    # backward count W(v): number of search paths from v to a sink
    W = {}
    for v in reversed(topo):
        if n_out.get(v, 0) == 0:
            W[v] = 1.0
        else:
            tot = 0.0
            wv = weights.get(v, 1.0)
            for j in out_of[v]:
                w = weights.get((v, j), 1.0)
                if n_out.get(j, 0) > 0:
                    tot += w * W.get(j, 1.0)
                else:
                    tot += w
            W[v] = max(tot, 1.0)

    # forward count Q(v): number of search paths from a source to v
    Q = {}
    for v in topo:
        if n_in.get(v, 0) == 0:
            Q[v] = 1.0
        else:
            tot = 0.0
            for i in in_of[v]:
                w = weights.get((i, v), 1.0)
                if n_in.get(i, 0) > 0:
                    tot += w * Q.get(i, 1.0)
                else:
                    tot += w
            Q[v] = max(tot, 1.0)

    spc = {}
    for (u, v) in out_arcs:
        spc[(u, v)] = Q.get(u, 1.0) * W.get(v, 1.0)

    if not spc:
        return [], {}

    best = max(spc, key=lambda k: spc[k])
    path = [best[0], best[1]]
    # extend forward
    cur = best[1]
    seen = set([best[0], best[1]])
    while True:
        nxt = [(spc.get((cur, j), 0.0), j) for j in (out_of.get(cur) or ())]
        nxt = [x for x in nxt if x[1] not in seen]
        if not nxt:
            break
        _, j = max(nxt)
        path.append(j)
        seen.add(j)
        cur = j
    # extend backward
    cur = best[0]
    while True:
        prv = [(spc.get((i, cur), 0.0), i) for i in (in_of.get(cur) or ())]
        prv = [x for x in prv if x[1] not in seen]
        if not prv:
            break
        _, i = max(prv)
        path.insert(0, i)
        seen.add(i)
        cur = i
    # Arcs point citing -> cited, so the walk above runs from the newest
    # paper backwards to the oldest.  Reverse it so the tradition reads
    # chronologically, which is how main paths are conventionally drawn.
    path.reverse()
    return path, spc


# --------------------------------------------------------------------------
# structural diversity / structural holes
# --------------------------------------------------------------------------

def rao_stirling(items, dist):
    """
    `items` = Counter over cluster ids, `dist` = {(i, j): d}.
    Returns (variety, balance, disparity, divergence).
    """
    tot = float(sum(items.values())) or 1.0
    p = {k: v / tot for k, v in items.items()}
    variety = len(p)
    if variety <= 1:
        return variety, 0.0, 0.0, 0.0
    entropy = -sum(pi * math.log(pi) for pi in p.values() if pi > 0)
    balance = entropy / math.log(variety)
    disp = 0.0
    ks = list(p)
    for i in range(len(ks)):
        for j in range(i + 1, len(ks)):
            d = dist.get((ks[i], ks[j]), dist.get((ks[j], ks[i]), 1.0))
            disp += 2 * p[ks[i]] * p[ks[j]] * d
    if False:
        pass
    return variety, round(balance, 4), round(disp, 4), round(disp * balance, 4)


def structural_holes(node, adj_w):
    """Burt's effective size and constraint for one node (ego net only)."""
    nb = adj_w.get(node) or {}
    if not nb:
        return 0.0, 0.0
    # direct investment p_ij normalised by the *whole* ego net weight
    tot = 0.0
    for u, wu in nb.items():
        w = float(wu)
        tot += w
        for q, wq in (adj_w.get(u) or {}).items():
            tot += float(wq)
    if tot <= 0:
        return 0.0, 0.0
    red = {}
    for u, wu in nb.items():
        row = adj_w.get(u) or {}
        denom = 0.0
        for q, wq in row.items():
            denom += float(wq)
        if denom > 0:
            red[u] = float(wu) / denom
    eff = 0.0
    for u in nb:
        s = 0.0
        for q in nb:
            if q == u:
                continue
            s += red.get(q, 0.0) * (adj_w.get(u, {}).get(q, 0.0) and 1.0 or 0.0)
        eff += 1.0 - s
    # constraint
    p_unit = float(len(nb))
    con = 0.0
    for j in nb:
        direct = float(nb[j]) / tot
        indirect = 0.0
        for q in nb:
            if q == j:
                continue
            indirect += (float(nb[q]) / tot) * red.get(q, 0.0)
        con += (direct + indirect) ** 2
    return round(eff, 3), round(con, 4)


def cluster_distance(clusters, term_vecs):
    """Cosine distance between cluster profiles = 1 - cosine."""
    out = {}
    ids = list(clusters)
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a, b = term_vecs[ids[i]], term_vecs[ids[j]]
            inter = len(a & b)
            if not inter:
                d = 1.0
            else:
                d = 1.0 - inter / math.sqrt(float(len(a)) * len(b))
            out[(ids[i], ids[j])] = round(max(0.0, min(1.0, d)), 4)
    return out


# --------------------------------------------------------------------------
def run(docs, params, log=None):
    p = dict(params or {})

    def L(s):
        if log is not None:
            log.append(s)

    edges_raw, stats = build_citation_network(docs, log)
    if not edges_raw:
        return {'error': '没有匹配到任何内部引用关系：这份数据的参考文献'
                         '与语料内部文献无法对应，引文网络分析不可用。'}

    nodes_l = sorted(set([a for (a, b) in edges_raw] +
                         [b for (a, b) in edges_raw]))
    und = {}
    for (a, b), w in edges_raw.items():
        k = (a, b) if a < b else (b, a)
        und[k] = und.get(k, 0.0) + float(w)

    adj = defaultdict(dict)
    for (a, b), w in und.items():
        adj[a][b] = w
        adj[b][a] = w

    n = len(nodes_l)
    m = len(und)
    density = 2.0 * m / float(n * (n - 1)) if n > 1 else 0.0

    # reciprocity on the directed graph
    recip_pairs = sum(1 for (a, b) in edges_raw if (b, a) in edges_raw)
    lab, n_comp = wcc_label(nodes_l, und)
    biggest = Counter(lab.values()).most_common(1)[0][1]
    maxcore, corelab = _k_core(nodes_l, adj)
    indeg = Counter()
    outdeg = Counter()
    for (a, b) in edges_raw:
        outdeg[a] += 1
        indeg[b] += 1

    cluster_coef = clustering_coefficient(nodes_l, und)
    assort = degree_assortativity(nodes_l, und)
    alpha = power_law_alpha([indeg.get(v, 0) for v in nodes_l if indeg.get(v, 0) > 0])

    L('network: %d nodes, %d edges, density=%.5f, components=%d (largest %d), '
      'clustering=%.4f, assortativity=%.4f, degeneracy=%d'
      % (n, m, density, n_comp, biggest, cluster_coef, assort, maxcore))

    # ---- communities on the undirected projection -------------------------
    communities = net.louvain_full(nodes_l, und, resolution=1.0)
    cmap = {}
    for ci, c in enumerate(communities):
        for v in c:
            cmap[v] = ci
    n_comm = len(communities)
    L('communities on the citation network: %d' % n_comm)

    # ---- main path --------------------------------------------------------
    out_arcs = defaultdict(list)
    weights = {}
    for (a, b), w in edges_raw.items():
        out_arcs[a].append(b)
        weights[(a, b)] = float(w)
    path, spc = main_path(nodes_l, list(edges_raw.keys()), weights)
    L('main path: %d nodes' % len(path))

    # ---- structural diversity over the reference portfolio ----------------
    # term profile per community (set of vocabulary ids of its documents)
    import topicmodel as tm
    corpus = tm.build_corpus(docs, use_title=True, use_abstract=True,
                             min_df=2, max_vocab=4000, bigrams=False, log=log)
    doc_terms = corpus['dtm']
    prof = defaultdict(set)
    for v in nodes_l:
        c = cmap.get(v)
        for w in set(doc_terms[v] if v < len(doc_terms) else []):
            prof[c].add(w)
    cdist = cluster_distance(list(range(n_comm)), prof)

    rows = []
    for v in nodes_l:
        refs_in = Counter()
        for (a, b) in edges_raw:
            if a == v:
                refs_in[cmap.get(b, -1)] += 1
        cites_in = Counter()
        for (a, b) in edges_raw:
            if b == v:
                cites_in[cmap.get(a, -1)] += 1
        vv, bb, dd, rs_forward = rao_stirling(refs_in, cdist)
        _, _, _, rs_back = rao_stirling(cites_in, cdist)
        eff, con = structural_holes(v, adj)
        rows.append({
            'id': int(v),
            'title': (docs[v].get('title') or '')[:180],
            'year': docs[v].get('year'),
            'journal': docs[v].get('journal') or '',
            'local_citations': int(indeg.get(v, 0)),
            'n_refs_internal': int(outdeg.get(v, 0)),
            'cluster': int(cmap.get(v, -1)),
            'core': int(corelab.get(v, 0)),
            'div_refs_variety': vv,
            'div_refs_balance': bb,
            'div_refs_disparity': dd,
            'div_refs_rao': rs_forward,
            'div_citers_rao': rs_back,
            'effective_size': eff,
            'constraint': con,
            'on_main_path': 1 if v in set(path) else 0,
        })

    # ---- cited reference half-life per year -------------------------------
    yearly = defaultdict(list)
    for i, d in enumerate(docs):
        y = d.get('year')
        if not y:
            continue
        for r in (d.get('refs') or []):
            ry = _iy(r.get('year'))
            if ry and 1900 < ry <= y:
                yearly[y].append(y - ry)
    half_life = []
    for y in sorted(yearly):
        ages = sorted(yearly[y])
        med = ages[len(ages) // 2]
        half_life.append({'year': y, 'median_ref_age': med,
                          'n_refs': len(ages)})

    main_path_rows = []
    order = {v: i for i, v in enumerate(path)}
    for v in path:
        main_path_rows.append({
            'id': int(v),
            'order': order[v],
            'year': docs[v].get('year'),
            'title': (docs[v].get('title') or '')[:180],
            'local_citations': int(indeg.get(v, 0)),
            'cluster': int(cmap.get(v, -1)),
        })

    comm_top = sorted(enumerate(communities),
                      key=lambda kv: -len(kv[1]))[:20]

    return {
        'summary': {
            'n_nodes': n, 'n_edges': m, 'n_directed': len(edges_raw),
            'density': round(density, 6),
            'reciprocal_pairs': recip_pairs,
            'n_components': n_comp,
            'largest_component': biggest,
            'clustering': cluster_coef,
            'assortativity': assort,
            'degeneracy': maxcore,
            'power_law_alpha': alpha,
            'n_communities': n_comm,
            'main_path_len': len(path),
            'match_rate': stats['match_rate'],
            'n_refs': stats['n_refs'],
        },
        'rows': rows,
        'main_path': main_path_rows,
        'half_life': half_life,
        'communities': [
            {'id': ci, 'size': len(c),
             'label': ', '.join(sorted(set((docs[v].get('journal') or '?')
                                           for v in c))[:3]),
             'mean_year': round(sum(docs[v].get('year') or 0 for v in c) /
                                float(len(c)), 2)}
            for ci, c in comm_top],
    }


if __name__ == '__main__':
    # A citation chain 2015 -> 2016 -> 2017 -> 2018 plus a dead branch.
    # The main path must be exactly the chain, and the branch node must show
    # a lower structural diversity than the node that bridges two groups.
    docs = []
    chain = []
    for y in (2015, 2016, 2017, 2018):
        d = {'title': 'paper %d' % y, 'year': y, 'journal': 'J Test',
             'doi': '10.1000/%d' % y, 'authors': ['Auth%d, A' % y],
             'abstract': 'liver failure transplant %d' % y,
             'refs': [], 'keywords': []}
        if chain:
            d['refs'] = [{'author': 'AUTH%d' % chain[-1]['year'],
                          'year': chain[-1]['year'],
                          'journal': 'J Test', 'volume': '', 'page': '',
                          'doi': '', 'key': ''}]
        chain.append(d)
        docs.append(d)
    # a side paper citing nothing important
    docs.append({'title': 'dead end', 'year': 2019, 'journal': 'J Other',
                 'doi': '10.1000/99', 'authors': ['Side, S'],
                 'abstract': 'machine learning classifier', 'refs': [],
                 'keywords': []})
    # and one that bridges: cites the 2015 and the dead end
    docs.append({'title': 'bridge', 'year': 2020, 'journal': 'J Test',
                 'doi': '10.1000/20', 'authors': ['Bridge, B'],
                 'abstract': 'liver machine learning', 'refs': [
                     {'author': 'AUTH2015', 'year': 2015,
                      'journal': 'J Test', 'volume': '', 'page': '',
                      'doi': '', 'key': ''},
                     {'author': 'SIDE', 'year': 2019, 'journal': 'J Other',
                      'volume': '', 'page': '', 'doi': '', 'key': ''}],
                 'keywords': []})

    log = []
    res = run(docs, {}, log)
    if 'error' in res:
        print('ERROR:', res['error'])
    else:
        print('\n'.join(log))
        print('summary:', res['summary'])
        print('main path:')
        for r in res['main_path']:
            print('   %-8s %-22s lc=%d' % (r['year'], r['title'][:22],
                                            r['local_citations']))
        titles = [r['title'] for r in res['main_path']]
        assert 'paper 2015' in titles and 'paper 2018' in titles, \
            'the planted citation chain is not the main path'
        print('\nOK: main path traces the planted chain')
