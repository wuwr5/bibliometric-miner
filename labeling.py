# -*- coding: utf-8 -*-
"""
labeling.py -- automatic cluster labelling with Dunning's log-likelihood
ratio (LLR), the same statistic CiteSpace uses for its cluster labels.

For a candidate term w:

    c  = # documents INSIDE  the cluster containing w
    C  = # documents INSIDE  the cluster (total)
    n  = # documents in the WHOLE corpus containing w
    N  = # documents in the WHOLE corpus

    p1 = c / C            p2 = (n - c) / (N - C)        p = n / N

    LLR = 2 * [ c*ln(p1/p) + (C-c)*ln((1-p1)/(1-p))
                + (n-c)*ln(p2/p) + (N-C-n+c)*ln((1-p2)/(1-p)) ]

Terms exclusively concentrated in one cluster get a large LLR.  We keep
the terms with the highest LLR as the cluster label.  A mutual-information
(MI) score is also computed as a secondary ranking option.
"""

import math
import re
from collections import defaultdict, Counter

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z\-']{2,}")

STOPWORDS = set("""
a about above after again against all also am an and any are aren as at be
because been before being below between both but by can cannot could couldnt
did didi do does doesnt doing dont down during each few for form from further
had has have having he her here hers herself him himself his how i if in into
is isnt it its itself lets me more most must my myself no nor not of off on
once only or other ought our ours ourselves out over own same shant she should
shouldnt so some such than that the their theirs them themselves then there
these they this those through to too under until up very was we were what when
where which while who whom why with would you your yours yourself yourselves
study studies research paper article review analysis result results method
methods using used use based patients patient case cases data group groups
significant association associated level levels rate rates risk high low
among between within during among group cohort trial trials year years
conclusion conclusions objective objectives background purpose aims aim
however therefore thus may might can could also however moreover
effect effects outcome outcomes value values index score scores model models
clinical trial randomized controlled systematic meta analysis analyses
literature field research topic topics future directions limitations
name proposed nov sp spp type types group groups new new first second
one two three four five several many most least common general total
report reports reported present presents presented describe describes
described show shows showed find finds found observe observes observed
however therefore thus although while since because due according
respectively including include included involve involved appear appears
consider considered suggest suggests suggested remain remains
also well may might must shall should would could can cannot
case cases patient patients disease diseases disorder disorders
therapy therapies treatment treatments management diagnosis diagnostic
""".split())


def _tokenize(text):
    return [w.lower() for w in _WORD_RE.findall(text or '')]


def candidate_terms(doc, use_title=True, use_abstract=True, use_keywords=True):
    """Term set of one document (document frequency counted once per doc)."""
    terms = set()
    if use_keywords:
        for k in doc.get('keywords', []):
            k = k.lower().strip()
            if 2 < len(k) < 60 and k not in STOPWORDS:
                terms.add(k)
    if use_title:
        for w in _tokenize(doc.get('title', '')):
            if w not in STOPWORDS and len(w) > 2:
                terms.add(w)
    if use_abstract:
        for w in _tokenize(doc.get('abstract', '')):
            if w not in STOPWORDS and len(w) > 2:
                terms.add(w)
    return terms


def build_term_index(docs, use_title=True, use_abstract=True,
                     use_keywords=True, min_df=2):
    """doc_terms[i] = set(terms); df = document frequency per term."""
    doc_terms = []
    df = Counter()
    for d in docs:
        t = candidate_terms(d, use_title, use_abstract, use_keywords)
        doc_terms.append(t)
        df.update(t)
    if min_df > 1:
        keep = {t for t, c in df.items() if c >= min_df}
        doc_terms = [t & keep for t in doc_terms]
        df = Counter({t: c for t, c in df.items() if t in keep})
    return doc_terms, df


def llr(c, C, n, N):
    """Dunning log-likelihood ratio for the 2x2 contingency table."""
    if C <= 0 or N <= 0 or n <= 0 or c <= 0:
        return 0.0
    p1 = c / float(C)
    p2 = (n - c) / float(N - C) if (N - C) > 0 else 0.0
    p = n / float(N)
    tot = 0.0

    def _t(x, q):
        if x <= 0 or q <= 0:
            return 0.0
        return x * math.log(q)

    tot += _t(c, p1 / p) if p > 0 else 0.0
    if 0.0 < p1 < 1.0 and 0.0 < p < 1.0:
        tot += (C - c) * math.log((1 - p1) / (1 - p))
    if p2 > 0 and p > 0:
        tot += (n - c) * math.log(p2 / p)
    if 0.0 < p2 < 1.0 and 0.0 < p < 1.0:
        tot += (N - C - n + c) * math.log((1 - p2) / (1 - p))
    return 2.0 * tot


def mutual_information(c, C, n, N):
    """MI for the same table (secondary ranking)."""
    if c <= 0 or C <= 0 or n <= 0 or N <= 0:
        return 0.0
    p_wc = c / float(N)
    p_w = n / float(N)
    p_c = C / float(N)
    if p_wc <= 0:
        return 0.0
    return p_wc * math.log(p_wc / (p_w * p_c))


def label_cluster(cluster_doc_idx, doc_terms, df, N, top_k=5,
                  method='llr'):
    """Return [(term, score), ...] for one cluster."""
    C = len(cluster_doc_idx)
    if C == 0:
        return []
    cnt = Counter()
    for i in cluster_doc_idx:
        if i < len(doc_terms):
            cnt.update(doc_terms[i])
    scored = []
    for term, c in cnt.items():
        n = df.get(term, c)
        if method == 'mi':
            s = mutual_information(c, C, n, N)
        else:
            s = llr(c, C, n, N)
        if s > 0:
            scored.append((term, s, c, n))
    scored.sort(key=lambda x: (-x[1], -x[2], x[0]))
    return scored[:top_k]


def label_all(clusters, doc_index, doc_terms, df, N, top_k=5, method='llr'):
    """
    clusters   : list of node lists (a partition of the network nodes)
    doc_index  : node -> list of document indices that contain the node
    returns    : {cluster_id: {'label': str, 'terms': [...], 'size': n}}
    """
    out = {}
    for ci, nodes in enumerate(clusters):
        idxs = set()
        for nd in nodes:
            for i in doc_index.get(nd, ()):
                idxs.add(i)
        idxs = sorted(idxs)
        scored = label_cluster(idxs, doc_terms, df, N, top_k, method)
        label = ', '.join(t for t, *_ in scored[:3]) if scored else 'cluster %d' % ci
        out[ci] = {'label': label,
                   'terms': [{'term': t, 'score': round(s, 3),
                              'in': int(c), 'all': int(n)}
                             for t, s, c, n in scored],
                   'n_docs': len(idxs)}
    return out


if __name__ == '__main__':
    # smoke test: a term perfectly confined to one cluster must win
    print(round(llr(20, 20, 20, 100), 2))   # very high
    print(round(llr(20, 20, 100, 100), 2))  # zero (term everywhere)
