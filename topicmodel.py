# -*- coding: utf-8 -*-
"""
topicmodel.py -- topic modelling over **full text** (title + abstract), not
just the author keywords.

Two pipelines are provided:

1. ``lda``     Latent Dirichlet Allocation, estimated with collapsed Gibbs
               sampling (Heinrich).  Pure standard library; no numpy needed.
               Reported per topic: top terms (with the Sievert-Shirley
               "relevance" re-ranking), size, UMass coherence, doc-level PMI
               coherence, mean year and yearly prevalence.  Train perplexity
               is reported so that different K can be compared.

2. ``ctfidf``  The BERTopic recipe: document embeddings -> spherical k-means
               -> class-based TF-IDF cluster descriptors.  Because no neural
               encoder can be shipped offline, the embeddings are
               *count-based*: either a randomised truncated SVD of the
               TF-IDF matrix (default) or the LDA topic proportions.  The
               clustering and labelling stages are faithful to BERTopic.
"""

import math
import random
import re
from collections import defaultdict, Counter

import labeling as _lab

# --------------------------------------------------------------------------
# text handling
# --------------------------------------------------------------------------

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z\-']{1,}")

_STOP = set(_lab.STOPWORDS)
_STOP |= set("""
et al fig figure table shown table1 supplementary additional available
 copyright rights reserved publisher john wiley sons inc ltd
 abstracts abstract objective background methods material materials
 introduction discussion appendix chapter us ng ml mm cm kg
 doi pmid issn isbn http https www com org
""".split())


def _tokens(text):
    if not text:
        return []
    out = []
    for w in _WORD_RE.findall(text.lower()):
        if len(w) < 2 or w in _STOP:
            continue
        if w.isdigit():
            continue
        out.append(w)
    return out


def build_corpus(docs, use_title=True, use_abstract=True, use_keywords=False,
                 min_df=3, max_vocab=6000, bigrams=True, max_bigrams=6000,
                 log=None):
    """
    Turn documents into a document-term matrix of integer term ids.

    Returns a dict with the vocabulary, the per-document token id lists and
    the metadata needed by the visualisation.
    """
    def L(s):
        if log is not None:
            log.append(s)

    texts, years, titles = [], [], []
    for d in docs:
        parts = []
        if use_title:
            parts.append(d.get('title') or '')
        if use_abstract:
            parts.append(d.get('abstract') or '')
        if use_keywords:
            parts.append(' '.join(d.get('keywords') or []))
        texts.append(_tokens(' '.join(parts)))
        years.append(d.get('year'))
        titles.append(d.get('title') or '')

    n_docs = len(texts)
    L('corpus: %d documents' % n_docs)

    # ---- document frequency for unigrams ----------------------------------
    df = Counter()
    for t in texts:
        df.update(set(t))

    # ---- bigrams: adjacent non-stopword pairs -----------------------------
    # DF (document frequency), not raw occurrence count
    bigram_df = Counter()
    if bigrams:
        for t in texts:
            bigram_df.update(set(zip(t, t[1:])))

    keep_uni = [w for w, c in df.items() if c >= min_df]
    keep_uni.sort(key=lambda w: (-df[w], w))
    keep_bi = [g for g, c in bigram_df.items() if c >= min_df]
    keep_bi.sort(key=lambda g: (-bigram_df[g], g))
    keep_bi = keep_bi[:max_bigrams]

    vocab = keep_uni[:max_vocab]
    for g in keep_bi:
        vocab.append('%s %s' % g)
    term_id = {t: i for i, t in enumerate(vocab)}
    bmap = {}
    for g in keep_bi:
        bmap[g] = term_id.get('%s %s' % g)

    L('vocabulary: %d terms (%d unigrams + %d bigrams, min_df=%d)'
      % (len(vocab), len(keep_uni[:max_vocab]), len(keep_bi), min_df))

    # ---- document-term matrix --------------------------------------------
    dtm, empties = [], 0
    for t in texts:
        ids = [term_id[w] for w in t if w in term_id]
        if bigrams:
            for pair in zip(t, t[1:]):
                j = bmap.get(pair)
                if j is not None:
                    ids.append(j)
        if not ids:
            empties += 1
        dtm.append(ids)
    n_tokens = sum(len(x) for x in dtm)
    L('document-term matrix: %d documents, %d tokens (%d docs became empty)'
      % (len(dtm), n_tokens, empties))

    return {
        'vocab': vocab, 'term_id': term_id, 'dtm': dtm, 'years': years,
        'titles': titles, 'df': df, 'n_docs': n_docs, 'n_tokens': n_tokens,
        'V': len(vocab),
    }


# --------------------------------------------------------------------------
# LDA -- collapsed Gibbs sampling
# --------------------------------------------------------------------------

def _gibbs(dtm, V, K, alpha, beta, iterations, burn_in, seed, callback=None):
    n_doc = len(dtm)
    nzw = [0] * (K * V)
    nz = [0] * K
    ndz = [0] * (n_doc * K)
    nd = [0] * n_doc
    rnd = random.Random(seed)

    Z = []
    for di, doc in enumerate(dtm):
        zi = []
        base = di * K
        for w in doc:
            k = rnd.randrange(K)
            zi.append(k)
            nzw[k * V + w] += 1
            nz[k] += 1
            ndz[base + k] += 1
            nd[di] += 1
        Z.append(zi)

    Vbeta = V * beta
    probs = [0.0] * K
    # running averages collected after burn-in
    s_nzw, s_ndz, s_nz = None, None, None
    n_samples = 0

    for it in range(iterations):
        for di, doc in enumerate(dtm):
            zi = Z[di]
            base = di * K
            for ti in range(len(doc)):
                w = doc[ti]
                zold = zi[ti]
                ndz[base + zold] -= 1
                nd[di] -= 1
                nzw[zold * V + w] -= 1
                nz[zold] -= 1

                cdf = 0.0
                base_w = w
                off = base
                for k in range(K):
                    cdf += ((ndz[off + k] + alpha) *
                            (nzw[k * V + base_w] + beta) / (nz[k] + Vbeta))
                    probs[k] = cdf
                u = rnd.random() * cdf
                knew = K - 1
                for k in range(K):
                    if u <= probs[k]:
                        knew = k
                        break
                zi[ti] = knew
                ndz[base + knew] += 1
                nd[di] += 1
                nzw[knew * V + w] += 1
                nz[knew] += 1

        if callback:
            callback(it)

        if it >= burn_in:
            if s_nzw is None:
                s_nzw = list(nzw)
                s_ndz = list(ndz)
                s_nz = list(nz)
            else:
                for i in range(K * V):
                    s_nzw[i] += nzw[i]
                for i in range(n_doc * K):
                    s_ndz[i] += ndz[i]
                for k in range(K):
                    s_nz[k] += nz[k]
            n_samples += 1

    if n_samples == 0:
        return nzw, nz, ndz, nd, Z
    inv = 1.0 / n_samples
    return ([x * inv for x in s_nzw], [x * inv for x in s_nz],
            [x * inv for x in s_ndz], nd, Z)


def coherence_umass(term_ids, docsets, top_n=10):
    """
    UMass coherence:  sum_i sum_{j<i} log( (D(vi,vj)+1) / D(vi) ).

    `docsets` is the precomputed list of per-document term sets -- building
    it once instead of once per topic is the difference between a second
    and a minute of runtime.
    """
    ids = term_ids[:top_n]
    dfi = Counter()
    for s in docsets:
        for w in ids:
            if w in s:
                dfi[w] += 1
    tot, cnt = 0.0, 0
    for i in range(1, len(ids)):
        di_ = dfi[ids[i]]
        if not di_:
            continue
        for j in range(i):
            c = 0
            for s in docsets:
                if ids[i] in s and ids[j] in s:
                    c += 1
            tot += math.log((c + 1.0) / float(di_))
            cnt += 1
    return round(tot / cnt, 4) if cnt else 0.0


def coherence_pmi(term_ids, docsets, n_docs, top_n=10):
    """
    Document-level PMI coherence (a pragmatic stand-in for c_v, which
    normally uses a sliding window rather than the whole document).
    """
    ids = term_ids[:top_n]
    eps = 1e-12
    dfi = Counter()
    for w in ids:
        dfi[w] = sum(1 for s in docsets if w in s)
    tot, cnt = 0.0, 0
    for i in range(1, len(ids)):
        wi = ids[i]
        pi = (dfi[wi] + eps) / n_docs
        for j in range(i):
            wj = ids[j]
            pj = (dfi[wj] + eps) / n_docs
            c = sum(1 for s in docsets if wi in s and wj in s)
            pij = (c + eps) / n_docs
            tot += math.log(pij / (pi * pj))
            cnt += 1
    return round(tot / cnt, 4) if cnt else 0.0




def lda(corpus, n_topics=10, alpha=0.1, beta=0.01, iterations=60,
        burn_in=25, top_terms=12, seed=42, log=None, progress=None):
    dtm = corpus['dtm']
    V = corpus['V']
    n_docs = corpus['n_docs']
    K = int(n_topics)

    def L(s):
        if log is not None:
            log.append(s)

    L('lda: K=%d, alpha=%.3f, beta=%.3f, %d iterations (burn-in %d)'
      % (K, alpha, beta, iterations, burn_in))
    nzw, nz, ndz, nd, Z = _gibbs(dtm, V, K, alpha, beta, iterations,
                                 burn_in, seed, callback=progress)

    Vbeta = V * beta
    Kalpha = K * alpha
    vocab = corpus['vocab']

    docsets = [set(doc) for doc in dtm]      # built once for all topics
    topics = []
    for k in range(K):
        base = k * V
        nz_k = nz[k] or 1.0
        row = nzw[base:base + V]
        # phi for this topic
        phi_row = [(row[w] + beta) / (nz_k + Vbeta) for w in range(V)]
        # marginal probability of each word across topics (for relevance)
        order = sorted(range(V), key=lambda w: -phi_row[w])[:max(top_terms * 4, 40)]
        marg = {}
        for w in order:
            c = 0
            for kk in range(K):
                c += nzw[kk * V + w]
            marg[w] = max(c, 1)
        tot_all = float(sum(marg.values())) or 1.0

        def rel(w):
            return (0.6 * math.log(max(phi_row[w], 1e-12)) +
                    0.4 * math.log(max(phi_row[w], 1e-12) /
                                   max(marg[w] / tot_all, 1e-12)))

        cand = sorted(order, key=lambda w: -rel(w))[:top_terms]
        phi_top = sorted(order, key=lambda w: -phi_row[w])[:top_terms]
        if all(x == y for x, y in zip(cand, phi_top)):
            cand = phi_top
        terms = [(vocab[w], float(round(phi_row[w], 6))) for w in cand]
        ids = [w for w in cand]
        topics.append({
            'id': k,
            'terms': terms,
            'term_ids': ids,
            'size': int(round(nz[k])),
            'coherence_umass': coherence_umass(ids, docsets),
            'coherence_pmi': coherence_pmi(ids, docsets, n_docs),
            'label': ', '.join(vocab[w] for w in cand[:4]),
        })

    # ---- document-topic proportions ---------------------------------------
    theta = []
    for di in range(n_docs):
        base = di * K
        s = nd[di] or 1
        theta.append([(ndz[base + k] + alpha) / (s + Kalpha) for k in range(K)])

    # ---- perplexity (train) ----------------------------------------------
    ll = 0.0
    ntok = 0
    for di, doc in enumerate(dtm):
        th = theta[di]
        for w in doc:
            p = 0.0
            for k in range(K):
                p += th[k] * (nzw[k * V + w] + beta) / (nz[k] + Vbeta)
            if p > 0:
                ll += math.log(p)
            ntok += 1
    perplexity = round(math.exp(-ll / ntok), 1) if ntok else 0.0
    L('lda done: perplexity=%.1f, %d tokens' % (perplexity, ntok))

    # ---- yearly prevalence ------------------------------------------------
    years = corpus['years']
    yr = defaultdict(lambda: [0.0] * K)
    cnt = Counter()
    for di in range(n_docs):
        y = years[di]
        if y is None:
            continue
        cnt[y] += 1
        th = theta[di]
        for k in range(K):
            yr[y][k] += th[k]
    year_list = sorted(yr)
    topic_year = []
    for y in year_list:
        row = [v / cnt[y] for v in yr[y]]
        topic_year.append({'year': y, 'shares': [round(x, 5) for x in row]})

    # dominant topic per document
    dom = Counter()
    for di in range(n_docs):
        dom[max(range(K), key=lambda k: theta[di][k])] += 1
    for t in topics:
        t['n_docs'] = int(dom[t['id']])
        ys = [corpus['years'][di] for di in range(n_docs)
              if max(range(K), key=lambda k: theta[di][k]) == t['id']
              and corpus['years'][di]]
        t['mean_year'] = round(sum(ys) / len(ys), 2) if ys else 0

    return {
        'method': 'lda',
        'params': {'K': K, 'alpha': alpha, 'beta': beta,
                   'iterations': iterations, 'burn_in': burn_in,
                   'top_terms': top_terms, 'vocab': V},
        'topics': topics,
        'theta': [[round(x, 5) for x in row] for row in theta],
        'dominant': [max(range(K), key=lambda k: theta[di][k])
                     for di in range(n_docs)],
        'topic_year': topic_year,
        'perplexity': perplexity,
        'coherence_mean': round(sum(t['coherence_umass'] for t in topics) / K, 4),
    }


# --------------------------------------------------------------------------
# BERTopic-style pipeline: embeddings -> spherical k-means -> c-TF-IDF
# --------------------------------------------------------------------------

def _tfidf_sparse(corpus):
    """Return {term_id: [(doc_id, weight), ...]} for TF-IDF."""
    dtm = corpus['dtm']
    n = corpus['n_docs']
    tf = defaultdict(lambda: defaultdict(int))
    for di, doc in enumerate(dtm):
        for w in doc:
            tf[w][di] += 1
    dfn = Counter()
    for w, d in tf.items():
        dfn[w] = len(d)
    out = {}
    for w, dd in tf.items():
        idf = math.log((1.0 + n) / (1.0 + dfn[w])) + 1.0
        out[w] = [(di, (1.0 + math.log(c)) * idf) for di, c in dd.items()]
    return out


def _random_svd(sparse_map, V, n_docs, dim=32, seed=7, power_iters=1):
    """
    Randomised truncated SVD of a sparse V x n_docs matrix represented as
    {row: [(col, value), ...]}.  Returns (U, S, Vt) with U as a list of
    length-V lists of length `dim`.
    """
    rnd = random.Random(seed)
    Omega = [[rnd.gauss(0, 1) for _ in range(dim)] for _ in range(n_docs)]
    # Y = A @ Omega
    Y = [[0.0] * dim for _ in range(V)]
    for w, entries in sparse_map.items():
        row = Y[w]
        for di, val in entries:
            om = Omega[di]
            for j in range(dim):
                row[j] += val * om[j]
    # orthogonalise with modified Gram-Schmidt
    Q = [[0.0] * dim for _ in range(V)]
    for j in range(dim):
        # column j
        nj = 0.0
        for i in range(V):
            nj += Y[i][j] * Y[i][j]
        nj = math.sqrt(nj) or 1.0
        for i in range(V):
            Q[i][j] = Y[i][j] / nj
        for jj in range(j + 1, dim):
            d = 0.0
            for i in range(V):
                d += Q[i][j] * Y[i][jj]
            for i in range(V):
                Y[i][jj] -= d * Q[i][j]
    # B = A^T @ Q  (n_docs x dim); its SVD gives the row/column factors
    Bt = [[0.0] * dim for _ in range(n_docs)]
    for w, entries in sparse_map.items():
        qw = Q[w]
        for di, val in entries:
            row = Bt[di]
            for j in range(dim):
                row[j] += val * qw[j]
    # small SVD of Bt via one-sided Jacobi on Bt^T Bt
    small = min(dim, 32)
    Ub, S, _ = _jacobi_svd(Bt, small)
    # U_rows = Q @ Ub
    U = []
    for i in range(V):
        qi = Q[i]
        row = []
        for j in range(small):
            s = 0.0
            for t in range(dim):
                s += qi[t] * Ub[t][j]
            row.append(s)
        U.append(row)
    return U, S


def _jacobi_svd(A, dim):
    """One-sided Jacobi SVD of a dim x dim matrix given as list of lists."""
    n = len(A)
    m = len(A[0]) if n else 0
    U = [[A[i][j] for j in range(m)] for i in range(n)]
    # Gram matrix
    G = [[0.0] * m for _ in range(m)]
    for i in range(n):
        for a in range(m):
            uia = U[i][a]
            if uia == 0:
                continue
            for b in range(a, m):
                G[a][b] += uia * U[i][b]
    for a in range(m):
        for b in range(a):
            G[a][b] = G[b][a]
    V = [[1.0 if i == j else 0.0 for j in range(m)] for i in range(m)]
    for sweep in range(30):
        off = 0.0
        for p in range(m - 1):
            for q in range(p + 1, m):
                off += G[p][q] * G[p][q]
        if off < 1e-14:
            break
        for p in range(m - 1):
            for q in range(p + 1, m):
                gpp, gqq, gpq = G[p][p], G[q][q], G[p][q]
                if abs(gpq) < 1e-14 * math.sqrt(max(gpp * gqq, 1e-30)):
                    continue
                theta = (gqq - gpp) / (2.0 * gpq)
                t = (1.0 if theta >= 0 else -1.0) / \
                    (abs(theta) + math.sqrt(theta * theta + 1.0))
                c = 1.0 / math.sqrt(t * t + 1.0)
                s = t * c
                for k in range(m):
                    vkp, vkq = V[k][p], V[k][q]
                    V[k][p] = c * vkp - s * vkq
                    V[k][q] = s * vkp + c * vkq
                for k in range(m):
                    gkp, gkq = G[k][p], G[k][q]
                    G[k][p] = c * gkp - s * gkq
                    G[k][q] = s * gkp + c * gkq
                for k in range(m):
                    gpk, gqk = G[p][k], G[q][k]
                    G[p][k] = c * gpk - s * gqk
                    G[q][k] = s * gpk + c * gqk
    sing = [math.sqrt(max(G[j][j], 0.0)) for j in range(m)]
    order = sorted(range(m), key=lambda j: -sing[j])
    Uo = [[V[i][j] for j in order] for i in range(m)]
    So = [sing[j] for j in order]
    return Uo, So, None


def _spherical_kmeans(vecs, k, seed=3, max_iter=40, sample=1500):
    """Cosine k-means.  `vecs` is a list of vectors (may be huge: only up to
    `sample` documents are used to build the centroids, everyone gets
    assigned afterwards)."""
    n = len(vecs)
    rnd = random.Random(seed)
    idx = list(range(n))
    rnd.shuffle(idx)
    idx = idx[:min(sample, n)]

    def norm(v):
        s = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / s for x in v]

    cents = [norm(list(vecs[i])) for i in rnd.sample(idx, min(k, len(idx)))]
    assign = [0] * n
    for it in range(max_iter):
        moved = 0
        newc = [[0.0] * len(cents[0]) for _ in cents]
        cnt = [0] * len(cents)
        for i in idx:
            v = vecs[i]
            best, bd = 0, -1e18
            for ci, c in enumerate(cents):
                d = 0.0
                for a, b in zip(v, c):
                    d += a * b
                if d > bd:
                    bd, best = d, ci
            if assign[i] != best:
                assign[i] = best
                moved += 1
            nc = newc[best]
            for j, x in enumerate(v):
                nc[j] += x
            cnt[best] += 1
        for ci in range(len(cents)):
            if cnt[ci]:
                cents[ci] = norm([x / cnt[ci] for x in newc[ci]])
        if moved == 0:
            break
    # assign the rest
    for i in range(n):
        if i in set(idx):
            continue
        v = vecs[i]
        best, bd = 0, -1e18
        for ci, c in enumerate(cents):
            d = 0.0
            for a, b in zip(v, c):
                d += a * b
            if d > bd:
                bd, best = d, ci
        assign[i] = best
    return assign, cents


def ctfidf_model(corpus, n_topics=12, embedding='svd', dim=24,
                 top_terms=12, seed=7, log=None):
    """BERTopic-style clustering + class-based TF-IDF descriptors."""
    def L(s):
        if log is not None:
            log.append(s)

    dtm = corpus['dtm']
    n_docs = corpus['n_docs']
    V = corpus['V']
    if embedding == 'svd':
        sp = _tfidf_sparse(corpus)
        L('ctfidf: randomised SVD over TF-IDF (dim=%d)' % dim)
        U, S = _random_svd(sp, V, n_docs, dim=dim, seed=seed)
        # document embeddings ~ rows of Vt; approximate by projecting docs
        vecs = []
        for di, doc in enumerate(dtm):
            v = [0.0] * dim
            for w in doc:
                uw = U[w]
                for j in range(dim):
                    v[j] += uw[j]
            vecs.append(v)
    else:
        L('ctfidf: embeddings = LDA topic proportions')
        res = lda(corpus, n_topics=dim, alpha=0.1, beta=0.01,
                  iterations=30, burn_in=15, seed=seed)
        vecs = res['theta']

    L('ctfidf: spherical k-means with k=%d' % n_topics)
    assign, cents = _spherical_kmeans(vecs, n_topics, seed=seed)
    used = len(set(assign))

    # ---- class-based TF-IDF ----------------------------------------------
    vocab = corpus['vocab']
    # frequency of each term inside each class, and global frequency
    cls_tf = defaultdict(Counter)
    for di, doc in enumerate(dtm):
        c = Counter(doc)
        cls_tf[assign[di]].update(c)
    global_tf = Counter()
    for di, doc in enumerate(dtm):
        global_tf.update(set(doc))
    avg_words = (sum(len(cls_tf[c]) for c in cls_tf) / max(len(cls_tf), 1)) or 1.0

    topics = []
    docsets = [set(doc) for doc in dtm]
    for ci in sorted(cls_tf, key=lambda c: -sum(cls_tf[c].values())):
        members = sum(1 for a in assign if a == ci)
        tf = cls_tf[ci]
        total = sum(tf.values()) or 1
        scored = []
        for w, cnt in tf.items():
            f = global_tf.get(w, 1)
            score = (cnt / total) * math.log(1.0 + avg_words / max(f, 1))
            scored.append((score, w))
        scored.sort(reverse=True)
        ids = [w for _, w in scored[:top_terms]]
        terms = [(vocab[w], round(s, 6)) for s, w in scored[:top_terms]]
        topics.append({
            'id': ci, 'terms': terms, 'term_ids': ids,             'size': members,
            'coherence_umass': coherence_umass(ids, docsets),
            'coherence_pmi': coherence_pmi(ids, docsets, n_docs),
            'label': ', '.join(vocab[w] for w in ids[:4]),
        })
        ys = [corpus['years'][di] for di in range(n_docs)
              if assign[di] == ci and corpus['years'][di]]
        topics[-1]['mean_year'] = round(sum(ys) / len(ys), 2) if ys else 0
        topics[-1]['n_docs'] = members

    years = corpus['years']
    by_year = defaultdict(Counter)
    cnt = Counter()
    for di in range(n_docs):
        y = years[di]
        if y is None:
            continue
        cnt[y] += 1
        by_year[y][assign[di]] += 1
    topic_year = []
    for y in sorted(by_year):
        row = [by_year[y].get(t['id'], 0) / float(cnt[y]) for t in topics]
        topic_year.append({'year': y, 'shares': [round(x, 5) for x in row]})

    return {
        'method': 'ctfidf',
        'params': {'k': n_topics, 'embedding': embedding, 'dim': dim,
                   'top_terms': top_terms},
        'topics': topics,
        'assign': assign,
        'topic_year': topic_year,
        'perplexity': None,
        'coherence_mean': round(
            sum(t['coherence_umass'] for t in topics) / max(len(topics), 1), 4),
    }


# --------------------------------------------------------------------------
def run(docs, params, log=None):
    p = dict(params or {})
    corpus = build_corpus(
        docs,
        use_title=p.get('use_title', True),
        use_abstract=p.get('use_abstract', True),
        use_keywords=p.get('use_keywords', False),
        min_df=int(p.get('min_df', 3) or 3),
        max_vocab=int(p.get('max_vocab', 6000) or 6000),
        bigrams=p.get('bigrams', True),
        log=log)
    if corpus['n_tokens'] < 500:
        return {'error': '可用于主题建模的词太少（%d 个 token），'
                         '请确认数据含标题/摘要。' % corpus['n_tokens']}
    method = p.get('method', 'lda')
    if method == 'ctfidf':
        return ctfidf_model(corpus,
                            n_topics=int(p.get('n_topics', 12) or 12),
                            embedding=p.get('embedding', 'svd'),
                            dim=int(p.get('dim', 24) or 24),
                            top_terms=int(p.get('top_terms', 12) or 12),
                            log=log)
    return lda(corpus,
               n_topics=int(p.get('n_topics', 10) or 10),
               alpha=float(p.get('alpha', 0.1) or 0.1),
               beta=float(p.get('beta', 0.01) or 0.01),
               iterations=int(p.get('iterations', 60) or 60),
               burn_in=int(p.get('burn_in', 25) or 25),
               top_terms=int(p.get('top_terms', 12) or 12),
               log=log)


# --------------------------------------------------------------------------
if __name__ == '__main__':
    # Three perfectly separated topics; LDA must recover them and the
    # true topic vocabulary must be more coherent than a random draw.
    rnd = random.Random(2024)
    A = 'liver failure transplant graft survival donor hepatectomy'
    B = 'nocardia bacteria gram stain colony antibiotic susceptibility'
    C = 'machine learning neural network classifier accuracy training'
    vocab_sets = [A.split(), B.split(), C.split()]
    docs = []
    for gi in range(3):
        for _ in range(60):
            words = [rnd.choice(vocab_sets[gi]) for _ in range(40)]
            for _ in range(10):
                words.append(rnd.choice(['a', 'the', 'of', 'to']))
            rnd.shuffle(words)
            docs.append({'title': 'doc %d' % len(docs),
                         'abstract': ' '.join(words), 'year': 2016 + gi,
                         'keywords': []})
    log = []
    res = run(docs, {'method': 'lda', 'n_topics': 3, 'iterations': 40,
                     'burn_in': 20, 'min_df': 2}, log)
    print('\n'.join(log))
    print('perplexity:', res['perplexity'], ' mean coherence (umass):',
          res['coherence_mean'])
    for t in res['topics']:
        print('  #%d n=%-3d yr=%s C=%.3f | %s'
              % (t['id'], t['n_docs'], t['mean_year'], t['coherence_umass'],
                 t['label'][:70]))

    ok = True
    # every discovered topic should be dominated by exactly one true group
    for gi, names in enumerate(vocab_sets):
        hit = [t for t in res['topics']
               if sum(1 for term, _ in t['terms'][:6]
                      if term.split()[0] in names) >= 4]
        if not hit:
            ok = False
        print('  true group %d -> %d topic(s) recovered' % (gi, len(hit)))
    # assignment accuracy against the generating group
    mapping = {}
    for gi, names in enumerate(vocab_sets):
        best, bs = None, 0
        for t in res['topics']:
            s = sum(1 for term, _ in t['terms'][:6]
                    if term.split()[0] in names)
            if s > bs:
                best, bs = t['id'], s
        mapping[best] = gi
    acc = sum(1 for i, k in enumerate(res['dominant'])
              if mapping.get(k) == i // 60) / float(len(docs))
    print('assignment accuracy: %.3f' % acc)
    assert acc > 0.9, 'LDA failed to separate three well defined topics'
    assert ok, 'some generated topic was not recovered'
    print('\nOK: LDA recovers the planted topics')
