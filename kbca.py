# -*- coding: utf-8 -*-
"""
kbca.py -- Keyword-Bibliographic Coupling Analysis and multi-channel fusion.

Two deliverables:

A.  Multi-channel document similarity
    Six independent similarity channels are computed over the same set of
    documents, each normalised to [0, 1]:

      bc        bibliographic coupling      shared references (cosine)
      cc        co-citation                 both cited by the same document
      tfidf     abstract/title TF-IDF       lexical (semantic) similarity
      topic     topic-distribution cosine   from topicmodel.LDA
      author    shared authors              Jaccard
      cat       shared WoS categories       Jaccard

    Channels are compared pairwise with a **Mantel test** (Pearson correlation
    of the off-diagonal entries, permutation p-value).  This says plainly
    whether the "semantic" channels actually carry information the structural
    ones do not — which is the premise of KBCA.

B.  Integrated network + composite document value
    The fused network is clustered with Louvain.  Every document then gets a
    **composite value** combining a structural axis (degree, betweenness,
    disruption CD index, local citations) with a semantic axis (topic novelty
    = atypical reference combination after Uzzi et al. 2013, interdiscipli-
    nary entropy over reference categories, lexical distinctiveness).

References
    Mantel N. The detection of disease clustering. Cancer Res 1967;27:209-220.
    Wu L, Wang D, Evans JA. Large teams develop and small teams disrupt.
        Nature 2019;566:378-382.   (CD / disruption index)
    Uzzi B, Mukherjee S, Stringer M, Jones B. Atypical combinations and
        scientific impact. Science 2013;342:468-472.
    Stirling A. A general framework for analysing diversity in science,
        technology and society. J R Soc Interface 2007;4:707-719.
"""

import math
import random
from collections import Counter, defaultdict

try:
    import numpy as _np
except Exception:
    _np = None

import network as net
import topicmodel as tm
import labeling as lbl


CHANNELS = ['bc', 'cc', 'tfidf', 'topic', 'author', 'cat']

CHANNEL_LABEL = {
    'bc': 'Bibliographic coupling (shared references)',
    'cc': 'Co-citation (cited together)',
    'tfidf': 'Title+abstract TF-IDF cosine',
    'topic': 'LDA topic-distribution cosine',
    'author': 'Shared authors (Jaccard)',
    'cat': 'Shared WoS categories (Jaccard)',
}


# --------------------------------------------------------------------------
# basic text handling
# --------------------------------------------------------------------------
def _tokens(d):
    txt = ((d.get('title') or '') + ' . ' + (d.get('abstract') or ''))
    return lbl._tokenize(txt)


def _tfidf_matrix(docs, min_df=2):
    """Term -> {doc_i: tf-idf weight}.  Sparse, idf-weighted, L2-normalised."""
    toks = []
    df = Counter()
    for d in docs:
        t = _tokens(d)
        toks.append(t)
        df.update(set(t))
    n = len(docs)
    keep = {w for w, c in df.items() if c >= min_df}
    inv = {w: [] for w in keep}
    for i, t in enumerate(toks):
        tf = Counter(w for w in t if w in keep)
        if not tf:
            continue
        mx = max(tf.values())
        for w, c in tf.items():
            inv[w].append((i, (0.5 + 0.5 * c / mx) *
                           math.log(1.0 + n / float(df[w]))))
    norm = defaultdict(float)
    for w, entries in inv.items():
        for i, v in entries:
            norm[i] += v * v
    for w in inv:
        inv[w] = [(i, v / math.sqrt(norm[i] or 1.0)) for i, v in inv[w]]
    return inv


# --------------------------------------------------------------------------
# channels
# --------------------------------------------------------------------------
def _sets(docs, field):
    out = []
    for d in docs:
        if field == 'author':
            out.append({a.lower().strip() for a in d.get('authors', [])
                        if a.strip()})
        else:
            out.append({c.lower().strip() for c in d.get('categories', [])
                        if c.strip()})
    return out


def _ref_keys(d):
    return {r['key'] for r in (d.get('refs') or []) if r.get('key')}


def build_channels(docs, params, log=None):
    """Returns dict channel -> {(i, j): similarity}, all in [0, 1]."""
    L = log.append if log is not None else (lambda *_: None)
    n = len(docs)
    L('building channels for %d documents' % n)

    refs = [_ref_keys(d) for d in docs]
    rsize = [len(r) for r in refs]
    L('references: mean %.1f per document' % (sum(rsize) / float(n or 1)))

    # ---- bibliographic coupling -----------------------------------------
    inverted = defaultdict(list)
    for i, r in enumerate(refs):
        for k in r:
            inverted[k].append(i)
    bc = {}
    for k, lst in inverted.items():
        if len(lst) > 400:          # ultra-generic reference: skip
            continue
        for a in range(len(lst)):
            for b in range(a + 1, len(lst)):
                i, j = lst[a], lst[b]
                key = (i, j)
                bc[key] = bc.get(key, 0.0) + 1.0
    del inverted
    for (i, j), c in list(bc.items()):
        den = math.sqrt(rsize[i] * rsize[j])
        bc[(i, j)] = c / den if den else 0.0
    L('bibliographic coupling: %d pairs' % len(bc))

    # ---- co-citation -----------------------------------------------------
    citers = defaultdict(set)       # ref key -> set of citing doc indices
    for i, r in enumerate(refs):
        for k in r:
            citers[k].add(i)
    cc = {}
    for k, lst in citers.items():
        lst = sorted(lst)
        if len(lst) > 200:
            continue
        for a in range(len(lst)):
            for b in range(a + 1, len(lst)):
                key = (lst[a], lst[b])
                cc[key] = cc.get(key, 0.0) + 1.0
    del citers
    if cc:
        mx = max(cc.values())
        cc = {k: v / mx for k, v in cc.items()}
    L('co-citation: %d pairs' % len(cc))

    # ---- TF-IDF ----------------------------------------------------------
    # Sparse multiplication by accumulating over postings lists: cost is
    # sum_w df(w)^2 rather than n^2 * |vocab|, which is what makes this
    # tractable without numpy.
    inv = _tfidf_matrix(docs)
    tfidf = {}
    acc = Counter()
    skipped = 0
    for w, entries in inv.items():
        if len(entries) > 400:      # near-universal term: no signal, huge cost
            skipped += 1
            continue
        for a in range(len(entries)):
            ia, va = entries[a]
            for b in range(a + 1, len(entries)):
                ib, vb = entries[b]
                acc[(ia, ib)] += va * vb
    if skipped:
        L('tf-idf: skipped %d near-universal terms' % skipped)
    thr = float(params.get('tfidf_min', 0.05))
    items = sorted(((v, k) for k, v in acc.items()), reverse=True)
    cap = int(params.get('tfidf_max_pairs', 400000))
    for v, k in items[:cap]:
        if v > thr:
            tfidf[k] = v
    if len(acc) > cap:
        L('tf-idf: kept the %d strongest of %d non-zero pairs'
          % (len(tfidf), len(acc)))
    L('tf-idf vocabulary: %d terms' % len(inv))
    del acc
    L('tf-idf: %d pairs above threshold' % len(tfidf))

    # ---- topic distribution ---------------------------------------------
    topic_ch = {}
    n_topics = int(params.get('n_topics', 12) or 12)
    try:
        tlog = []
        tres = tm.run(docs, {'method': 'lda', 'n_topics': n_topics,
                             'iterations': int(params.get('lda_iter', 25)),
                             'burn_in': 10, 'min_df': 3,
                             'max_vocab': 5000,
                             'text_fields': params.get('text_fields',
                                                       'title_abstract')},
                      tlog)
        rows = tres.get('theta') or []
        if len(rows) == n and rows and len(rows[0]) == n_topics:
            theta = rows
            for a in range(n):
                va = theta[a]
                if not va:
                    continue
                na = math.sqrt(sum(x * x for x in va)) or 1.0
                for b in range(a + 1, n):
                    vb = theta[b]
                    if not vb:
                        continue
                    nb = math.sqrt(sum(x * x for x in vb)) or 1.0
                    s = sum(x * y for x, y in zip(va, vb)) / (na * nb)
                    if s > 0.05:
                        topic_ch[(a, b)] = s
            L('topic channel: %d pairs (%s)' % (len(topic_ch),
                                                tres.get('perplexity')))
        else:
            L('topic channel: skipped (shape mismatch)')
    except Exception as exc:
        L('topic channel: disabled (%s)' % exc)

    # ---- Jaccard channels -------------------------------------------------
    def _jacc(sets_list):
        inverted = defaultdict(list)
        for i, s in enumerate(sets_list):
            for x in s:
                inverted[x].append(i)
        inter = Counter()
        for x, lst in inverted.items():
            if len(lst) > 300:
                continue
            for a in range(len(lst)):
                for b in range(a + 1, len(lst)):
                    inter[(lst[a], lst[b])] += 1
        out = {}
        for (i, j), c in inter.items():
            u = len(sets_list[i]) + len(sets_list[j]) - c
            if u:
                out[(i, j)] = c / float(u)
        return out

    author_ch = _jacc(_sets(docs, 'author'))
    cat_ch = _jacc(_sets(docs, 'cat'))
    L('author channel: %d pairs, category channel: %d pairs'
      % (len(author_ch), len(cat_ch)))

    return {
        'bc': bc, 'cc': cc, 'tfidf': tfidf, 'topic': topic_ch,
        'author': author_ch, 'cat': cat_ch,
    }


# --------------------------------------------------------------------------
# Mantel test
# --------------------------------------------------------------------------
def mantel(n, ch_a, ch_b, perms=199, seed=11, max_pairs=20000):
    """
    Mantel correlation between two similarity channels, restricted to the
    document pairs present in *either* channel (off-diagonal, upper triangle).
    Returns (r, p, n_pairs).

    The pair set is subsampled to `max_pairs` because a full version would
    cost O(n^2 * perms); with 20k pairs and 199 permutations the Monte-Carlo
    resolution on p is 0.005, far finer than any decision this informs.
    """
    keys = set(ch_a) | set(ch_b)
    if len(keys) < 6:
        return 0.0, 1.0, len(keys)
    keys = sorted(keys)
    if len(keys) > max_pairs:
        rnd0 = random.Random(seed)
        keys = rnd0.sample(keys, max_pairs)
        keys.sort()
    xs = [ch_a.get(k, 0.0) for k in keys]
    ys = [ch_b.get(k, 0.0) for k in keys]
    m = len(xs)

    def _pear(a, b):
        ma = sum(a) / m
        mb = sum(b) / m
        sa = sum((v - ma) ** 2 for v in a) ** 0.5
        sb = sum((v - mb) ** 2 for v in b) ** 0.5
        if sa < 1e-12 or sb < 1e-12:
            return 0.0
        return sum((p - ma) * (q - mb) for p, q in zip(a, b)) / (sa * sb)

    r = _pear(xs, ys)
    rnd = random.Random(seed)
    howmany = 0
    for _ in range(perms):
        perm = ys[:]
        rnd.shuffle(perm)
        if abs(_pear(xs, perm)) >= abs(r) - 1e-12:
            howmany += 1
    p = (howmany + 1.0) / (perms + 1.0)
    return round(r, 4), round(p, 4), m


# --------------------------------------------------------------------------
# disruption (CD index) and novelty
# --------------------------------------------------------------------------
def disruption_index(docs, log=None, cite_edges=None):
    """
    CD index restricted to the in-corpus citation graph, per
    Wu, Wang & Evans (2019).  For every paper i:

        n_i = papers citing i but none of i's own references
        n_j = papers citing i and at least one of i's references
        n_k = papers citing >= 1 reference of i but not i itself

        CD = (n_i - n_j) / (n_i + n_j + n_k)          (0 when denominator 0)

    Positive => disruptive (later work bypasses the ancestors),
    negative => developmental (it consolidates an existing lineage).

    Resolution of references against the corpus is delegated to
    citenet.build_citation_network (DOI first, then author-year-journal)
    so that this module and the citation-network view cannot disagree.
    Integer bitmaps keep the set algebra at O(n/64) per operation; the
    naive nested-set form is O(n^3) and unusable beyond a few hundred docs.
    """
    L = log.append if log is not None else (lambda *_: None)
    n = len(docs)

    import citenet as cn
    edges, _stats = (cite_edges if cite_edges is not None else
                     cn.build_citation_network(docs, log))

    # forward = who cites me ; backward = whom I cite (both restricted to
    # the corpus)
    cited_by = defaultdict(set)
    cites = defaultdict(set)
    for (citing, cited) in edges:
        cited = int(cited)
        citing = int(citing)
        cited_by[cited].add(citing)
        cites[citing].add(cited)
    L('disruption: %d internal citation edges resolved' % len(edges))
    if not edges:
        return [0.0] * n

    mask_cited_by = {}
    for i, src in cited_by.items():
        m = 0
        for j in src:
            m |= 1 << j
        mask_cited_by[i] = m

    out = [0.0] * n
    for i in range(n):
        own_refs = cites.get(i) or set()
        own = 1 << i
        ci_mask = mask_cited_by.get(i, 0) & ~own
        if not ci_mask:
            continue
        mask_refs = 0
        for j in own_refs:
            mask_refs |= mask_cited_by.get(j, 0)
        mask_refs &= ~own
        nj = _popcount(ci_mask & mask_refs)
        ni = _popcount(ci_mask) - nj
        nk = _popcount(mask_refs & ~ci_mask)
        den = ni + nj + nk
        if den:
            out[i] = (ni - nj) / float(den)
    return out


def _popcount(x):
    return x.bit_count() if hasattr(x, 'bit_count') else bin(x).count('1')


def _uzzi_atypicality(docs, top=12):
    """
    For every cited-journal pair (A, B) the observed co-citation count is
    compared with its hypergeometric expectation; a paper's atypicality is
    the 10th percentile of the z-scores of the pairs it uses, following
    Uzzi et al. (2013).  Negative => the paper combines unusually rare pairs.
    """
    # N = number of papers that contribute at least one journal pair; this
    # is the correct denominator for the expected co-occurrence count
    # E(A,B) = n_A * n_B / N, NOT the total number of observed pairs (using
    # the latter shrinks the expectation by orders of magnitude and produces
    # nonsensical z-scores in the tens).
    pairs = Counter()
    single = Counter()
    n_pairs_docs = 0
    for d in docs:
        js = sorted({(r.get('journal') or '').lower().strip()
                     for r in (d.get('refs') or [])
                     if (r.get('journal') or '').strip()})
        for j in js:
            single[j] += 1
        if len(js) >= 2:
            n_pairs_docs += 1
        for a in range(len(js)):
            for b in range(a + 1, len(js)):
                pairs[(js[a], js[b])] += 1
    N = float(max(1, n_pairs_docs))
    if not pairs:
        return [0.0] * len(docs), {}
    z = {}
    for (a, b), obs in pairs.items():
        exp = single[a] * single[b] / N
        # binomial-style variance; floored so rare pairs stay finite
        sd = math.sqrt(max(exp * (1.0 - min(1.0, exp / N)), 1e-6))
        z[(a, b)] = (obs - exp) / sd if sd else 0.0
    out = []
    for d in docs:
        js = sorted({(r.get('journal') or '').lower().strip()
                     for r in (d.get('refs') or [])
                     if (r.get('journal') or '').strip()})
        zs = []
        for a in range(len(js)):
            for b in range(a + 1, len(js)):
                v = z.get((js[a], js[b]))
                if v is not None:
                    zs.append(v)
        if not zs:
            out.append(0.0)
            continue
        zs.sort()
        out.append(zs[:max(1, len(zs) // 10)][-1])
    return out, z


def _ref_category_entropy(docs):
    """
    Interdisciplinarity of what a document *builds on*: Shannon entropy of its
    reference list over journals, normalised by log of the number of distinct
    journals in the whole corpus's reference pool.

    The normaliser must be a corpus-level constant, not log of this paper's
    own distinct-journal count -- the latter is self-referential and returns
    ~1.0 for virtually every paper, i.e. it carries no information.  With a
    global pool a short, narrow reference list scores low and a long list
    spread over many journals scores high, which is the intended reading.
    """
    per = []
    pool = set()
    for d in docs:
        c = Counter()
        for r in (d.get('refs') or []):
            j = (r.get('journal') or '').lower().strip()
            if j:
                c[j] += 1
        per.append(c)
        pool.update(c)
    hmax = math.log(max(2, len(pool)))
    out = []
    for c in per:
        tot = sum(c.values())
        if tot < 3:
            out.append(0.0)
            continue
        h = 0.0
        for v in c.values():
            p = v / float(tot)
            if p > 0:
                h -= p * math.log(p)
        out.append(max(0.0, min(1.0, h / hmax)))
    return out


# --------------------------------------------------------------------------
# driver
# --------------------------------------------------------------------------
def run(docs, params, log=None):
    L = log.append if log is not None else (lambda *_: None)
    n = len(docs)
    if n < 12:
        return {'error': 'need at least 12 documents (got %d)' % n}

    chans = build_channels(docs, params, log)
    active = [c for c in CHANNELS if chans[c]]
    L('active channels: %s' % ', '.join(active))

    # ---- Mantel cross-correlation ----------------------------------------
    mant = []
    for a in range(len(active)):
        for b in range(a + 1, len(active)):
            r, p, m = mantel(n, chans[active[a]], chans[active[b]],
                             perms=int(params.get('mantel_perms', 199)))
            mant.append({'a': active[a], 'b': active[b], 'r': r, 'p': p,
                         'n_pairs': m})
    L('mantel: %d channel pairs' % len(mant))

    # ---- weight fusion ----------------------------------------------------
    w = params.get('weights') or {}
    weights = {c: float(w.get(c, 1.0)) for c in active}
    tot = sum(weights.values()) or 1.0
    weights = {c: v / tot for c, v in weights.items()}
    L('fusion weights: %s' % ', '.join('%s=%.2f' % kv for kv in weights.items()))

    fused = Counter()
    for c in active:
        wc = weights[c]
        for k, v in chans[c].items():
            fused[k] += wc * v
    # keep the strongest links only: the raw union is O(n^2) and unusable
    keep_n = int(params.get('max_edges', min(20000, n * 12)))
    keep = sorted(fused.items(), key=lambda kv: -kv[1])[:keep_n]
    edges = {k: v for k, v in keep}
    L('fused network: %d candidate pairs -> keep top %d'
      % (len(fused), len(edges)))

    nodes = list(range(n))
    touching = set()
    for (i, j) in edges:
        touching.add(i)
        touching.add(j)
    nodes = sorted(touching)
    L('nodes with at least one fused link: %d' % len(nodes))

    communities = net.louvain(nodes, edges,
                              resolution=float(params.get('resolution', 1.0)))
    Q = net.modularity(nodes, edges, communities)
    L('louvain: %d communities, Q=%.4f' % (len(communities), Q))
    between = net.betweenness_centrality(nodes, edges)

    cid = disruption_index(docs, log)
    atyp, _zpair = _uzzi_atypicality(docs)
    integ_disc = _ref_category_entropy(docs)

    # ---- per-document composite value -------------------------------------
    deg = Counter()
    for (i, j), v in edges.items():
        deg[i] += v
        deg[j] += v
    if deg:
        dmax = max(deg.values()) or 1.0
    else:
        dmax = 1.0
    if between:
        bmax = max(between.values()) or 1.0
    else:
        bmax = 1.0

    def _pct(vals):
        vs = sorted(vals)
        m = len(vs) - 1

        def f(v):
            if m <= 0:
                return 0.0
            lo, hi = 0, m
            while lo < hi:
                mid = (lo + hi) // 2
                if vs[mid] < v:
                    lo = mid + 1
                else:
                    hi = mid
            return lo / float(m)
        return f

    p_deg = _pct([deg.get(i, 0.0) for i in range(n)])
    p_bet = _pct([between.get(i, 0.0) for i in range(n)])
    p_cid = _pct([(cid[i] + 1.0) / 2.0 for i in range(n)])
    p_aty = _pct([-atyp[i] for i in range(n)])          # rare pairs = higher
    p_int = _pct(integ_disc)

    rows = []
    for i, d in enumerate(docs):
        if i not in touching:
            continue
        struct = 0.40 * p_deg(deg.get(i, 0.0)) + \
            0.30 * p_bet(between.get(i, 0.0)) + \
            0.30 * p_cid((cid[i] + 1.0) / 2.0)
        seman = 0.40 * p_aty(-atyp[i]) + 0.35 * p_int(integ_disc[i]) + \
            0.25 * p_deg(deg.get(i, 0.0))
        rows.append({
            'i': i,
            'title': (d.get('title') or '')[:220],
            'year': d.get('year'),
            'journal': d.get('journal') or '',
            'cited_by': d.get('cited_by') or 0,
            'degree': round(deg.get(i, 0.0), 3),
            'betweenness': round(between.get(i, 0.0), 5),
            'disruption': round(cid[i], 4),
            'novelty': round(atyp[i], 3),
            'interdisciplinarity': round(integ_disc[i], 4),
            'structural': round(struct, 4),
            'semantic': round(seman, 4),
            'composite': round(math.sqrt(max(struct, 0) * max(seman, 0)), 4),
            'cluster': _cluster_of(i, communities),
        })
    rows.sort(key=lambda r: -r['composite'])
    for k, r in enumerate(rows):
        r['rank'] = k + 1

    comm_out = []
    for ci, c in enumerate(sorted(communities, key=len, reverse=True)):
        mem = [r for r in rows if r['cluster'] == ci]
        comm_out.append({
            'id': ci,
            'size': len(c),
            'mean_year': round(sum((r['year'] or 0) for r in mem) /
                               float(len(mem) or 1), 1),
            'mean_composite': round(sum(r['composite'] for r in mem) /
                                    float(len(mem) or 1), 4),
            'top': [r['title'][:70] for r in
                    sorted(mem, key=lambda x: -x['composite'])[:3]],
        })

    return {
        'summary': {
            'n_docs': n,
            'n_nodes': len(nodes),
            'n_edges': len(edges),
            'n_clusters': len(communities),
            'modularity': round(Q, 4),
            'active_channels': active,
        },
        'channels': {c: len(chans[c]) for c in CHANNELS},
        'mantel': mant,
        'weights': {k: round(v, 4) for k, v in weights.items()},
        'nodes': nodes,
        'edges': [{'s': i, 't': j, 'w': round(v, 5)}
                  for (i, j), v in edges.items()],
        'rows': rows,
        'clusters': comm_out,
        'doc_meta': [{'title': (d.get('title') or '')[:160],
                      'year': d.get('year'),
                      'journal': d.get('journal') or '',
                      'cluster': _cluster_of(i, communities)}
                     for i, d in enumerate(docs)],
    }


def _cluster_of(i, communities):
    for ci, c in enumerate(communities):
        if i in c:
            return ci
    return -1


# --------------------------------------------------------------------------
if __name__ == '__main__':
    print('=== KBCA self test ===')
    rnd = random.Random(3)
    docs = []
    # block A: shares references AND words
    for i in range(14):
        docs.append({
            'title': 'Alpha protein expression in nocardia %d' % i,
            'abstract': 'Alpha protein regulation and gene expression in '
                        'nocardia species under oxidative stress.',
            'year': 2018 + (i % 5),
            'journal': 'J Microbiol',
            'authors': ['Smith J', 'Lee K'],
            'categories': ['Microbiology'],
            'cited_by': 4,
            'refs': [{'key': 'core%d|2010|j microbiol' % (k % 3),
                      'journal': 'J Microbiol', 'author': 'Core K',
                      'year': 2010} for k in range(6)],
        })
    # block B: completely different references and vocabulary
    for i in range(14):
        docs.append({
            'title': 'Beta catalyst synthesis for water treatment %d' % i,
            'abstract': 'Beta catalyst synthesis for photocatalytic water '
                        'treatment and dye degradation kinetics.',
            'year': 2018 + (i % 5),
            'journal': 'J Chem Eng',
            'authors': ['Wang L', 'Chen M'],
            'categories': ['Chemistry'],
            'cited_by': 2,
            'refs': [{'key': 'chem%d|2011|j chem eng' % (k % 3),
                      'journal': 'J Chem Eng', 'author': 'Chem A',
                      'year': 2011} for k in range(6)],
        })
    log = []
    res = run(docs, {'n_topics': 4, 'lda_iter': 15, 'mantel_perms': 99}, log)
    print('\n'.join(log))
    print('summary :', res['summary'])
    print('channels:', res['channels'])
    print('weights :', res['weights'])
    print('mantel  :')
    for m in res['mantel'][:6]:
        print('   %-6s vs %-6s r=%+.3f p=%.3f (n=%d)'
              % (m['a'], m['b'], m['r'], m['p'], m['n_pairs']))
    print('top composite:')
    for r in res['rows'][:5]:
        print('   %-46s comp=%.3f str=%.2f sem=%.2f CD=%+.2f c%d'
              % (r['title'][:46], r['composite'], r['structural'],
                 r['semantic'], r['disruption'], r['cluster']))
    assert res['summary']['n_clusters'] >= 2, 'two blocks must separate'
    assert res['summary']['modularity'] > 0.3, 'blocks must be well separated'
    assert len(res['mantel']) >= 3, 'mantel matrix must be populated'
    print('OK')
