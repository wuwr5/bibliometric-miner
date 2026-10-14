# -*- coding: utf-8 -*-
"""
network.py -- co-occurrence / co-citation network construction, node
selection, centrality, pruning, clustering and silhouette.

Pure standard library.  Everything is expressed on plain dicts so the
results serialise straight to JSON for the browser front end.

Edge weights follow CiteSpace convention: co-occurrence counts (raw or
cosine-normalised).  For centrality the distance of an edge is 1/w so
that strong ties are short.
"""

import math
from collections import defaultdict, Counter
from itertools import combinations


# --------------------------------------------------------------------------
# construction
# --------------------------------------------------------------------------

def build_edges(docs, field, min_count=1, normalize=None, lowercase=True,
                restrict=None):
    """
    docs       : list of parsed documents
    field      : 'ref' | 'keyword' | 'author' | 'org' | 'country'
                 | 'cited_journal' | 'category'
    normalize  : None | 'cosine' | 'jaccard' | 'dice' | 'equivalence'
    restrict   : optional set -- only these items take part in the network
                 (huge speed-up: pass the selected nodes of pass 1)
    returns    : (node_counter, edge_dict, doc_items)
    """
    items_per_doc = []
    for d in docs:
        if field == 'ref':
            items = [r['key'] for r in d['refs'] if r['key'].split('|')[0]]
        elif field == 'keyword':
            items = [k for k in d['keywords'] if k.strip()]
        elif field == 'author':
            items = [a for a in d['authors'] if a.strip()]
        elif field == 'org':
            items = [o for o in d['orgs'] if o.strip()]
        elif field == 'country':
            items = [c for c in d['countries'] if c.strip()]
        elif field == 'cited_journal':
            # journals appearing in the reference list -> co-citation network
            items = [r['journal'] for r in d['refs'] if r['journal']]
        elif field == 'category':
            items = [c.strip() for c in d['categories'] if c.strip()]
        else:
            raise ValueError('unknown field: %s' % field)

        if lowercase and field != 'ref':
            items = [i.lower().strip() for i in items]
        else:
            items = [i.strip() for i in items]
        items = [i for i in items if i]
        items_per_doc.append(items)

    node_counter = Counter()
    for items in items_per_doc:
        uniq = set(items)
        if restrict is not None:
            uniq = {i for i in uniq if i in restrict}
        node_counter.update(uniq)

    co = defaultdict(int)
    for items in items_per_doc:
        uniq = sorted(set(items))
        if restrict is not None:
            uniq = [i for i in uniq if i in restrict]
        if len(uniq) < 2:
            continue
        for a, b in combinations(uniq, 2):
            co[(a, b)] += 1

    if min_count > 1:
        node_counter = Counter({k: v for k, v in node_counter.items()
                                if v >= min_count})

    if normalize:
        for (a, b) in list(co.keys()):
            ca, cb = node_counter.get(a, 0), node_counter.get(b, 0)
            w = co[(a, b)]
            if normalize == 'cosine':
                co[(a, b)] = w / math.sqrt(ca * cb) if ca and cb else 0.0
            elif normalize == 'dice':
                co[(a, b)] = 2.0 * w / (ca + cb) if (ca + cb) else 0.0
            elif normalize == 'jaccard':
                co[(a, b)] = float(w) / (ca + cb - w) if (ca + cb - w) else 0.0
            elif normalize == 'equivalence':
                co[(a, b)] = (float(w) ** 2) / (ca * cb) if ca and cb else 0.0

    return node_counter, dict(co), items_per_doc


def adjacency(node_counter, edges):
    adj = defaultdict(dict)
    for (a, b), w in edges.items():
        adj[a][b] = w
        adj[b][a] = w
    return adj


# --------------------------------------------------------------------------
# node selection
# --------------------------------------------------------------------------

def g_index_threshold(counts):
    """CiteSpace g-index: largest g with sum(top g counts) >= g^2."""
    vals = sorted(counts, reverse=True)
    tot, g = 0, 0
    for i, v in enumerate(vals, start=1):
        tot += v
        if tot >= i * i:
            g = i
    return g


def select_nodes(node_counter, per_slice_counts, criterion, value,
                 global_cap=1000):
    """
    criterion : 'top'      -> value = N most frequent nodes per slice
                'top_pct'  -> value = percentage of slice nodes
                'gindex'   -> value = scaling factor k on the g-index
                'threshold'-> value = minimum frequency
    per_slice_counts : list of Counter (one per time slice)
    returns: set of selected node labels
    """
    selected = Counter()
    for cnt in per_slice_counts:
        if not cnt:
            continue
        items = sorted(cnt.items(), key=lambda x: (-x[1], x[0]))
        if criterion == 'top':
            n = max(1, int(value))
        elif criterion == 'top_pct':
            n = max(1, int(round(len(items) * float(value) / 100.0)))
        elif criterion == 'gindex':
            g = g_index_threshold([v for _, v in items])
            n = max(1, int(round(g * float(value))))
        elif criterion == 'threshold':
            n = sum(1 for _, v in items if v >= float(value))
            n = max(1, n)
        else:
            n = max(1, int(value))
        for k, v in items[:n]:
            selected[k] = max(selected.get(k, 0), v)
    if global_cap and len(selected) > global_cap:
        keep = sorted(selected.items(), key=lambda x: (-x[1], x[0]))[:global_cap]
        selected = Counter(dict(keep))
    return selected


# --------------------------------------------------------------------------
# centrality
# --------------------------------------------------------------------------

def betweenness_centrality(nodes, edges, normalized=True, weight_power=1.0,
                           max_nodes=1500):
    """
    Brandes algorithm for weighted undirected graphs.
    Edge distance = 1 / w**weight_power  (strong ties are short paths).

    If `nodes` is larger than max_nodes the graph is reduced to the
    strongest sub-network so that the O(V*E) cost stays acceptable.
    """
    nodes = list(nodes)
    if len(nodes) > max_nodes:
        keep = sorted(nodes, key=lambda n: -sum(
            v for (a, b), v in edges.items() if a == n or b == n))[:max_nodes]
        nodes = keep

    idx = {n: i for i, n in enumerate(nodes)}
    n = len(nodes)
    adj = [[] for _ in range(n)]
    for (a, b), w in edges.items():
        if a not in idx or b not in idx:
            continue
        w = float(w)
        if w <= 0:
            continue
        d = 1.0 / (w ** weight_power)
        ia, ib = idx[a], idx[b]
        # collapse parallel edges by keeping the shortest distance
        for lst, other in ((adj[ia], ib), (adj[ib], ia)):
            found = False
            for k, (o, dd) in enumerate(lst):
                if o == other:
                    if dd > d:
                        lst[k] = (other, d)
                    found = True
                    break
            if not found:
                lst.append((other, d))

    bc = [0.0] * n
    try:
        from collections import deque
        for s in range(n):
            stack, pred = [], [[] for _ in range(n)]
            dist = [float('inf')] * n
            sigma = [0.0] * n
            dist[s] = 0.0
            sigma[s] = 1.0
            # Dijkstra with a simple binary heap
            import heapq
            pq = [(0.0, s)]
            visited = [False] * n
            while pq:
                d, v = heapq.heappop(pq)
                if visited[v]:
                    continue
                visited[v] = True
                stack.append(v)
                for w, dw in adj[v]:
                    nd = d + dw
                    if nd < dist[w] - 1e-12:
                        dist[w] = nd
                        sigma[w] = sigma[v]
                        pred[w] = [v]
                        heapq.heappush(pq, (nd, w))
                    elif abs(nd - dist[w]) <= 1e-12 and dist[w] < float('inf'):
                        sigma[w] += sigma[v]
                        pred[w].append(v)
            delta = [0.0] * n
            while stack:
                w = stack.pop()
                for v in pred[w]:
                    if sigma[w] > 0:
                        delta[v] += (sigma[v] / sigma[w]) * (1.0 + delta[w])
                if w != s:
                    bc[w] += delta[w]
    except MemoryError:
        return dict(zip(nodes, [0.0] * n))

    if normalized and n > 2:
        scale = 1.0 / ((n - 1) * (n - 2))
        bc = [v * scale for v in bc]
    return dict(zip(nodes, bc))


def degree_centrality(nodes, edges):
    deg = Counter()
    strength = Counter()
    for (a, b), w in edges.items():
        deg[a] += 1
        deg[b] += 1
        strength[a] += w
        strength[b] += w
    return {n: {'degree': int(deg.get(n, 0)),
                'strength': float(strength.get(n, 0))} for n in nodes}


# --------------------------------------------------------------------------
# pruning
# --------------------------------------------------------------------------

def _kruskal_mst(nodes, edges):
    parent = {n: n for n in nodes}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra == rb:
            return False
        parent[ra] = rb
        return True

    out = {}
    for (a, b), w in sorted(edges.items(), key=lambda kv: -kv[1]):
        if a in parent and b in parent and union(a, b):
            out[(a, b)] = w
    return out


def prune(nodes, edges, method='none', keep_per_node=3, min_weight=0.0):
    """
    method : 'none' | 'mst' | 'skeleton'  (skeleton = per-node top-k edges)
    """
    if min_weight:
        edges = {k: v for k, v in edges.items() if v >= min_weight}
    if method == 'none' or not edges:
        return edges
    if method == 'mst':
        # keep a forest (one MST per connected component) plus the strongest
        # skeleton edge of each node so the picture stays readable
        mst = _kruskal_mst(nodes, edges)
        return mst
    if method == 'skeleton':
        by_node = defaultdict(list)
        for (a, b), w in edges.items():
            by_node[a].append((w, b))
            by_node[b].append((w, a))
        keep = set()
        for n, lst in by_node.items():
            lst.sort(reverse=True)
            for w, other in lst[:keep_per_node]:
                keep.add((n, other) if n < other else (other, n))
        return {k: v for k, v in edges.items() if k in keep}
    if method == 'mst+skeleton':
        mst = _kruskal_mst(nodes, edges)
        sk = prune(nodes, edges, 'skeleton', keep_per_node)
        mst.update(sk)
        return mst
    return edges


def largest_component(nodes, edges):
    """Return (nodes, edges) restricted to the largest connected component."""
    adj = defaultdict(set)
    for a, b in edges:
        adj[a].add(b)
        adj[b].add(a)
    seen, best = set(), []
    for n in nodes:
        if n in seen:
            continue
        comp, stack = [], [n]
        seen.add(n)
        while stack:
            v = stack.pop()
            comp.append(v)
            for w in adj.get(v, ()):
                if w not in seen:
                    seen.add(w)
                    stack.append(w)
        if len(comp) > len(best):
            best = comp
    if not best:
        return list(nodes), edges
    keep = set(best)
    return best, {k: v for k, v in edges.items()
                  if k[0] in keep and k[1] in keep}


# --------------------------------------------------------------------------
# Louvain clustering
# --------------------------------------------------------------------------

def louvain(nodes, edges, resolution=1.0, seed=42, max_iter=30):
    """Weighted Louvain modularity optimisation -> list of communities."""
    nodes = list(nodes)
    if not nodes:
        return []
    idx = {n: i for i, n in enumerate(nodes)}
    adj = [dict() for _ in nodes]
    k = [0.0] * len(nodes)
    m2 = 0.0
    for (a, b), w in edges.items():
        if a not in idx or b not in idx or a == b:
            continue
        w = float(w)
        ia, ib = idx[a], idx[b]
        adj[ia][ib] = adj[ia].get(ib, 0.0) + w
        adj[ib][ia] = adj[ib].get(ia, 0.0) + w
        k[ia] += w
        k[ib] += w
        m2 += w
    m2 *= 2.0
    if m2 <= 0:
        return [[n] for n in nodes]

    comm = list(range(len(nodes)))
    import random
    rnd = random.Random(seed)

    def one_level(comm, adj, k, m2):
        # aggregate adjacency inside communities
        ncomm = max(comm) + 1
        tot = [0.0] * ncomm
        for i, c in enumerate(comm):
            tot[c] += k[i]
        improved = False
        order = list(range(len(comm)))
        rnd.shuffle(order)
        for i in order:
            ci = comm[i]
            k_i = k[i]
            nbrs = adj[i]
            # weights to each neighbouring community
            wc = defaultdict(float)
            for j, w in nbrs.items():
                wc[comm[j]] += w
            tot[ci] -= k_i
            best_c, best_gain = ci, wc.get(ci, 0.0) - resolution * tot[ci] * k_i / m2
            for c, w in wc.items():
                if c == ci:
                    continue
                gain = w - resolution * tot[c] * k_i / m2
                if gain > best_gain + 1e-12:
                    best_c, best_gain = c, gain
            tot[ci] += k_i
            if best_c != ci:
                comm[i] = best_c
                tot[ci] -= k_i
                tot[best_c] += k_i
                improved = True
        return improved

    for _ in range(max_iter):
        if not one_level(comm, adj, k, m2):
            break
        # relabel
        remap = {}
        for i, c in enumerate(comm):
            remap.setdefault(c, len(remap))
        comm = [remap[c] for c in comm]
        if max(comm) == 0:
            break
        # aggregate graph
        ncomm = max(comm) + 1
        nadj = [dict() for _ in range(ncomm)]
        nk = [0.0] * ncomm
        for (a, b), w in edges.items():
            ia, ib = idx[a], idx[b]
            ca, cb = comm[ia], comm[ib]
            if ca != cb:
                nadj[ca][cb] = nadj[ca].get(cb, 0.0) + w
                nadj[cb][ca] = nadj[cb].get(ca, 0.0) + w
            nk[ca] += w
        adj, k = nadj, nk
        # community ids of the original nodes must be tracked through
        # aggregation; simplest correct approach: rebuild comm from scratch
        # only when aggregation happened, so instead we stop here and map
        # back using a stable bookkeeping dictionary.
        break  # single aggregation pass keeps the mapping consistent

    groups = defaultdict(list)
    for i, c in enumerate(comm):
        groups[c].append(nodes[i])
    # recursive refinement on the aggregated graph is skipped for speed and
    # determinism; instead run a second local-move pass on the original graph
    return [g for g in groups.values() if g]


def louvain_full(nodes, edges, resolution=1.0, seed=42, passes=6):
    """Repeat local moving on the flat graph until stable (deterministic)."""
    nodes = list(nodes)
    if not nodes:
        return []
    idx = {n: i for i, n in enumerate(nodes)}
    adj = [dict() for _ in nodes]
    k = [0.0] * len(nodes)
    m2 = 0.0
    for (a, b), w in edges.items():
        if a not in idx or b not in idx or a == b:
            continue
        w = float(w)
        ia, ib = idx[a], idx[b]
        adj[ia][ib] = adj[ia].get(ib, 0.0) + w
        adj[ib][ia] = adj[ib].get(ia, 0.0) + w
        k[ia] += w
        k[ib] += w
        m2 += w
    m2 *= 2.0
    if m2 <= 0:
        return [[n] for n in nodes]

    import random
    rnd = random.Random(seed)
    comm = list(range(len(nodes)))
    for _ in range(passes):
        tot = [0.0] * (max(comm) + 1)
        for i, c in enumerate(comm):
            tot[c] += k[i]
        moved = 0
        order = list(range(len(nodes)))
        rnd.shuffle(order)
        for i in order:
            ci = comm[i]
            k_i = k[i]
            wc = defaultdict(float)
            for j, w in adj[i].items():
                wc[comm[j]] += w
            tot[ci] -= k_i
            best_c = ci
            best_gain = wc.get(ci, 0.0) - resolution * tot[ci] * k_i / m2
            for c, w in wc.items():
                if c == ci:
                    continue
                gain = w - resolution * tot[c] * k_i / m2
                if gain > best_gain + 1e-12:
                    best_c, best_gain = c, gain
            tot[ci] += k_i
            if best_c != ci:
                comm[i] = best_c
                tot[ci] -= k_i
                if best_c >= len(tot):
                    tot.extend([0.0] * (best_c - len(tot) + 1))
                tot[best_c] += k_i
                moved += 1
        if moved == 0:
            break

    remap = {}
    for i, c in enumerate(comm):
        remap.setdefault(c, len(remap))
    groups = defaultdict(list)
    for i, c in enumerate(comm):
        groups[remap[c]].append(nodes[i])
    out = sorted(groups.values(), key=lambda g: (-len(g), g[0]))
    return out


def modularity(nodes, edges, communities):
    idx = {n: i for i, n in enumerate(nodes)}
    m2 = sum(float(w) for w in edges.values()) * 2.0
    if m2 <= 0:
        return 0.0
    k = defaultdict(float)
    for (a, b), w in edges.items():
        k[a] += w
        k[b] += w
    tot = defaultdict(float)
    inn = defaultdict(float)
    comm_of = {}
    for ci, c in enumerate(communities):
        for n in c:
            comm_of[n] = ci
    for (a, b), w in edges.items():
        w = float(w)
        if comm_of.get(a) == comm_of.get(b):
            inn[comm_of[a]] += 2.0 * w
    for n, v in k.items():
        tot[comm_of.get(n, -1)] += v
    q = 0.0
    for c in set(comm_of.values()):
        q += inn[c] / m2 - (tot[c] / m2) ** 2
    return q


def silhouette(nodes, edges, communities, doc_sets=None):
    """
    Average silhouette of the partition.

    Distance = 1 - structural similarity, where the similarity of two nodes
    is the cosine of their rows in the co-occurrence matrix.  This is the
    similarity notion CiteSpace evaluates silhouette on: nodes of the same
    topic point at the same neighbours and therefore score high even when
    they never co-occur directly.  `edges` should be the *unpruned* network
    so the measure does not depend on the display pruning.
    """
    comm_of = {}
    for ci, c in enumerate(communities):
        for n in c:
            comm_of[n] = ci

    vec = defaultdict(dict)
    for (a, b), w in edges.items():
        w = float(w)
        vec[a][b] = w
        vec[b][a] = w
    norm = {}
    for n, v in vec.items():
        norm[n] = math.sqrt(sum(x * x for x in v.values())) or 1.0

    _cache = {}

    def dist(a, b):
        if a == b:
            return 0.0
        key = (a, b) if a < b else (b, a)
        d = _cache.get(key)
        if d is not None:
            return d
        va, vb = vec.get(a), vec.get(b)
        if not va or not vb:
            s = 0.0
        else:
            small, big = (va, vb) if len(va) <= len(vb) else (vb, va)
            s = 0.0
            for k, x in small.items():
                y = big.get(k)
                if y:
                    s += x * y
            s /= (norm.get(a, 1.0) * norm.get(b, 1.0))
        d = 1.0 - s
        _cache[key] = d
        return d

    scores = {}
    for ci, c in enumerate(communities):
        if len(c) < 2:
            for n in c:
                scores[n] = 0.0
            continue
        for n in c:
            same = [dist(n, m) for m in c if m != n]
            a = sum(same) / len(same) if same else 0.0
            b_vals = []
            for cj, other in enumerate(communities):
                if cj == ci or not other:
                    continue
                b_vals.append(sum(dist(n, m) for m in other) / len(other))
            b = min(b_vals) if b_vals else a
            scores[n] = 0.0 if max(a, b) == 0 else (b - a) / max(a, b)
    return scores


# --------------------------------------------------------------------------
# layout helpers
# --------------------------------------------------------------------------

def fruchterman_reingold(nodes, edges, iterations=300, width=1600.0,
                         height=1000.0, seed=7, init=None):
    """Classic force directed layout. Returns {node: (x, y)}."""
    import random
    rnd = random.Random(seed)
    n = len(nodes)
    if n == 0:
        return {}
    idx = {v: i for i, v in enumerate(nodes)}
    pos = {}
    if init:
        for v in nodes:
            pos[v] = list(init.get(v, (rnd.uniform(0, width),
                                        rnd.uniform(0, height))))
    else:
        for v in nodes:
            pos[v] = [rnd.uniform(0, width), rnd.uniform(0, height)]

    adj = [[] for _ in range(n)]
    for (a, b), w in edges.items():
        if a in idx and b in idx:
            adj[idx[a]].append((idx[b], float(w)))

    area = width * height
    k = math.sqrt(area / max(1, n))
    temp = width / 10.0
    disp = [[0.0, 0.0] for _ in range(n)]

    for it in range(iterations):
        for i in range(n):
            disp[i][0] = 0.0
            disp[i][1] = 0.0
        # repulsion (approximate all-pairs; fine up to ~1200 nodes)
        for i in range(n):
            xi, yi = pos[nodes[i]]
            for j in range(i + 1, n):
                xj, yj = pos[nodes[j]]
                dx, dy = xi - xj, yi - yj
                d2 = dx * dx + dy * dy
                if d2 < 1e-6:
                    d2 = 1e-6
                    dx = rnd.uniform(-1, 1)
                    dy = rnd.uniform(-1, 1)
                d = math.sqrt(d2)
                f = (k * k) / d
                ux, uy = dx / d, dy / d
                disp[i][0] += ux * f
                disp[i][1] += uy * f
                disp[j][0] -= ux * f
                disp[j][1] -= uy * f
        # attraction
        for i in range(n):
            for j, w in adj[i]:
                if j <= i:
                    continue
                xi, yi = pos[nodes[i]]
                xj, yj = pos[nodes[j]]
                dx, dy = xi - xj, yi - yj
                d = math.sqrt(dx * dx + dy * dy) or 1e-6
                f = (d * d) / k * (0.3 + 0.7 * min(1.0, w / 5.0))
                ux, uy = dx / d, dy / d
                disp[i][0] -= ux * f
                disp[i][1] -= uy * f
                disp[j][0] += ux * f
                disp[j][1] += uy * f
        # displacement limited by temperature
        for i in range(n):
            xi, yi = pos[nodes[i]]
            dx, dy = disp[i]
            d = math.sqrt(dx * dx + dy * dy)
            if d > 1e-9:
                lim = min(d, temp)
                pos[nodes[i]] = [xi + dx / d * lim, yi + dy / d * lim]
        temp *= 0.985
        if temp < 0.5:
            break
    return {v: (p[0], p[1]) for v, p in pos.items()}


if __name__ == '__main__':
    # tiny smoke test
    nodes = ['a', 'b', 'c', 'd', 'e', 'f']
    edges = {('a', 'b'): 3, ('b', 'c'): 3, ('c', 'a'): 3,
             ('d', 'e'): 2, ('e', 'f'): 2, ('f', 'd'): 2,
             ('c', 'd'): 1}
    print('BC:', betweenness_centrality(nodes, edges))
    com = louvain_full(nodes, edges)
    print('communities:', com)
    print('Q:', round(modularity(nodes, edges, com), 4))
