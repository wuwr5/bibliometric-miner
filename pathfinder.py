# -*- coding: utf-8 -*-
"""
pathfinder.py -- Pathfinder network scaling (PFNET).

Removes transitive (redundant) links from a proximity network: the edge
(u, v) with weight w survives only when no alternative path from u to v is
strictly shorter than w.  Path length is the Minkowski-r norm of the edge
weights along the path, and paths may contain at most q edges.

    r = 1    city block   (path cost = sum of the weights)
    r = 2    euclidean    (CiteSpace's usual setting)
    r = inf  minimax      (path cost = largest weight; PFNET(n-1, inf) is
                           exactly the minimum spanning tree)

Reference: Schvaneveldt, Durso & Dearholt (1989); Dearholt & Schvaneveldt
(1990).  The implementation below is the incremental ("fast pathfinder")
scheme: edges are processed in ascending order of weight, and the current
all-pairs shortest path matrix W is only relaxed through edges that have
been kept.  That is sound because any edge dropped from the network is by
definition replaceable by a strictly cheaper path, so by induction the
cheapest path between two nodes can always be written with kept edges only.

Pure standard library.  Cost is O(K * n^2) with K the number of surviving
edges (K is O(n) in practice), so the routine caps n at `max_nodes`.
"""

import math
from collections import defaultdict

INF = float('inf')
_EPS = 1e-12


def _transform(w, r):
    """Weight -> additive path cost for the given Minkowski r."""
    if r == INF:
        return w
    if r == 1.0:
        return w
    return w ** r


def pfnet(nodes, dist, q=None, r=2.0, max_nodes=400):
    """
    nodes : list of hashable node labels
    dist  : dict {(a, b): weight}  -- symmetric; missing pairs = infinite.
            Weights are *proximity* (larger = stronger) only if you invert
            them yourself; PFNET needs a distance (smaller = closer).
    q     : maximum number of edges on an alternative path (default n-1)
    r     : Minkowski parameter, or float('inf')
    returns: dict {(a, b): weight} of surviving edges
    """
    nodes = list(nodes)
    n = len(nodes)
    if n < 3:
        return dict(dist)
    if len(nodes) > max_nodes:
        # keep the strongest nodes so the O(n^2) matrix stays affordable
        strength = defaultdict(float)
        for (a, b), w in dist.items():
            strength[a] += 1.0 / (w + 1e-9)
            strength[b] += 1.0 / (w + 1e-9)
        nodes = sorted(nodes, key=lambda x: -strength[x])[:max_nodes]
        n = len(nodes)
        dist = {k: v for k, v in dist.items()
                if k[0] in set(nodes) and k[1] in set(nodes)}

    idx = {v: i for i, v in enumerate(nodes)}
    rinf = (r == INF or r is None)

    # ---- initial all-pairs matrix: direct edges, identity on the diagonal
    W = [[INF] * n for _ in range(n)]
    groups = defaultdict(list)
    for (a, b), w in dist.items():
        if a == b or a not in idx or b not in idx:
            continue
        w = float(w)
        if not (w > 0) or w == INF:
            continue
        ia, ib = idx[a], idx[b]
        # W carries *additive path costs*: w**r for finite r, w itself for
        # the minimax metric, so that "cost < w**r" <=> "Minkowski-r length
        # of the path < w".
        xw = _transform(w, r)
        if xw < W[ia][ib]:
            W[ia][ib] = xw
            W[ib][ia] = xw
        groups[w].append((ia, ib))
    for i in range(n):
        W[i][i] = 0.0

    if q is None or q >= n - 1:
        return _pfnet_full(nodes, W, groups, r, rinf)
    if n > 150:
        # hop-limited bookkeeping is a factor q^2 more expensive
        raise ValueError(
            'q < n-1 is only supported for networks of up to 150 nodes '
            '(this one has %d); use q = n-1.' % n)
    return _pfnet_hop_limited(nodes, dist, W, groups, int(q), r, rinf)


def _pfnet_full(nodes, W, groups, r, rinf):
    n = len(nodes)
    kept = {}
    range_n = range(n)
    for w in sorted(groups):
        grp = groups[w]
        x = _transform(w, r)
        # ---- decide (uses only edges strictly lighter than w)
        for ia, ib in grp:
            if W[ia][ib] >= x - _EPS:
                kept[(nodes[ia], nodes[ib])] = w
        # ---- relax through the whole group of equal weight
        for ia, ib in grp:
            row_a = W[ia]
            row_b = W[ib]
            for i in range_n:
                Wi = W[i]
                da = Wi[ia]
                if da == INF:
                    continue
                if rinf:
                    base = da if da > w else w
                    for j in range_n:
                        d2 = row_b[j]
                        if d2 == INF:
                            continue
                        cand = base if base > d2 else d2
                        if cand < Wi[j] - _EPS:
                            Wi[j] = cand
                else:
                    base = da + x
                    for j in range_n:
                        d2 = row_b[j]
                        if d2 == INF:
                            continue
                        cand = base + d2
                        if cand < Wi[j] - _EPS:
                            Wi[j] = cand
    return kept


def _pfnet_hop_limited(nodes, dist, W, groups, q, r, rinf):
    """q < n-1: track the best path cost per number of edges."""
    n = len(nodes)
    idx = {v: i for i, v in enumerate(nodes)}
    # D[h][i][j] = cheapest path with at most h edges
    D = [[[INF] * n for _ in range(n)] for _ in range(q + 1)]
    for i in range(n):
        D[0][i][i] = 0.0
    kept = {}
    for w in sorted(groups):
        x = _transform(w, r)
        for ia, ib in groups[w]:
            best = INF
            for h in range(1, q + 1):
                if D[h][ia][ib] < best:
                    best = D[h][ia][ib]
            if best >= x - _EPS:
                kept[(nodes[ia], nodes[ib])] = w
        # relax: paths that use one more edge of weight w
        for ia, ib in groups[w]:
            for h in range(q, 0, -1):
                Dh = D[h]
                for h1 in range(0, h):
                    Dh1 = D[h1]
                    h2 = h - 1 - h1
                    Dh2 = D[h2]
                    for i in range(n):
                        a = Dh1[i][ia]
                        if a == INF:
                            continue
                        row_b = Dh2[ib]
                        left = (a if a > w else w) if rinf else (a + x)
                        for j in range(n):
                            b = row_b[j]
                            if b == INF:
                                continue
                            cand = (left if left > b else b) if rinf else (left + b)
                            if cand < Dh[i][j] - _EPS:
                                Dh[i][j] = cand
    return kept


# --------------------------------------------------------------------------
# helpers to turn a co-occurrence network into a distance matrix
# --------------------------------------------------------------------------

def distance_matrix(nodes, doc_sets, metric='count', counts=None):
    """
    Complete distance matrix over `nodes`.

    metric='count'  : d = 1 / co-occurrence count, infinite when the pair
                      never co-occurs.  This is the classic Pathfinder
                      input: a strong tie is a short link, so a two-step
                      path over strong ties (cost ~ 2/c^2 under r=2) easily
                      undercuts a single weak tie (cost 1/c) and prunes it.
    metric='cosine' : d = 1 - cosine of the document incidence vectors.
                      All distances then live in [0, 1] and the pruning is
                      much weaker -- offered for comparison only.
    Returns dict {(a, b): d} for every unordered pair.
    """
    nodes = list(nodes)
    n = len(nodes)
    out = {}
    if metric == 'count':
        for i in range(n):
            for j in range(i + 1, n):
                c = (counts or {}).get((nodes[i], nodes[j]),
                                       (counts or {}).get((nodes[j], nodes[i]), 0))
                out[(nodes[i], nodes[j])] = 1.0 / c if c > 0 else INF
        return out

    sizes = {v: float(len(doc_sets.get(v) or ())) or 1.0 for v in nodes}
    for i in range(n):
        A = doc_sets.get(nodes[i]) or set()
        if not A:
            for j in range(i + 1, n):
                out[(nodes[i], nodes[j])] = 1.0
            continue
        for j in range(i + 1, n):
            B = doc_sets.get(nodes[j]) or set()
            if not B:
                out[(nodes[i], nodes[j])] = 1.0
                continue
            small, big = (A, B) if len(A) <= len(B) else (B, A)
            inter = 0
            for k in small:
                if k in big:
                    inter += 1
            cos = inter / math.sqrt(sizes[nodes[i]] * sizes[nodes[j]])
            out[(nodes[i], nodes[j])] = 1.0 - cos
    return out


if __name__ == '__main__':
    # ---- classic textbook example -------------------------------------
    # triangle  a-b 1, b-c 1, a-c 1.4 : with r=1 the path costs 2 > 1.4
    # so the long edge survives;  with a-c = 2.5 it is pruned.
    nodes = ['a', 'b', 'c']
    for w_ac in (1.4, 2.5):
        d = {('a', 'b'): 1.0, ('b', 'c'): 1.0, ('a', 'c'): w_ac}
        print('a-c =', w_ac, '-> r=1 kept:', sorted(pfnet(nodes, d, r=1.0)),
              '| r=inf kept:', sorted(pfnet(nodes, d, r=INF)))

    # ---- MST identity: PFNET(n-1, inf) must equal the MST --------------
    import random
    rnd = random.Random(3)
    nodes = [chr(97 + i) for i in range(8)]
    d = {}
    for i in range(8):
        for j in range(i + 1, 8):
            d[(nodes[i], nodes[j])] = round(rnd.uniform(1, 9), 3)
    pf = pfnet(nodes, d, r=INF)
    # kruskal
    parent = {x: x for x in nodes}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    mst = set()
    for (a, b), w in sorted(d.items(), key=lambda kv: kv[1]):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
            mst.add(frozenset((a, b)))
    pfset = set(frozenset(k) for k in pf)
    print('PFNET(inf) size=%d  MST size=%d  identical=%s'
          % (len(pfset), len(mst), pfset == mst))

    # ---- r=2 keeps more than the MST but is still sparse ---------------
    pf2 = pfnet(nodes, d, r=2.0)
    print('r=2 -> %d edges (of %d)' % (len(pf2), len(d)))
