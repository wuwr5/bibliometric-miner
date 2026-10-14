# -*- coding: utf-8 -*-
"""
burst.py -- Kleinberg (2003) burst detection.

Implementation of the "bursty and hierarchical structure in streams"
infinite-state automaton.  A stream of yearly counts r_1..r_n is modelled
by states i = 0..K-1 where state i emits counts with mean intensity

        lambda_i = base_rate * s ** i          (s = base parameter, > 1)

State 0 is the "baseline" (non-bursty) state.  Moving upward in the state
ladder is penalised by a transition cost

        tau(i, j) = (j - i) * gamma * ln(n)    for j > i,  0 otherwise

The optimal state sequence is obtained by dynamic programming

        C(t, i) = -ln f_i(r_t) + min_j [ C(t-1, j) + tau(j, i) ]

Contiguous runs with state > 0 are reported as bursts.  Strength is
reported as the log-likelihood gain of the bursty states over the
baseline state, which is monotone in how surprising the surge is:

        strength = sum_t [ ln f_{q_t}(r_t) - ln f_0(r_t) ]

Reference: J. Kleinberg, "Bursty and Hierarchical Structure in Streams",
Proc. ACM SIGKDD 2003.
"""

import math

# cached log-factorials
_LOG_FACT = [0.0]


def _logfact(n):
    while len(_LOG_FACT) <= n:
        k = len(_LOG_FACT)
        _LOG_FACT.append(_LOG_FACT[-1] + math.log(k))
    return _LOG_FACT[n]


def _log_poisson(r, lam):
    """ln P(X = r) for X ~ Poisson(lam)."""
    if lam <= 0:
        lam = 1e-9
    return -lam + r * math.log(lam) - _logfact(int(r))


def _log_exponential(r, lam):
    """ln density of Exp(mean=lam) evaluated on integer counts."""
    if lam <= 0:
        lam = 1e-9
    return -math.log(lam) - r / lam


def detect(series, base=2.0, gamma=1.0, density='poisson',
           max_states=8, min_duration=1):
    """
    series : list of (x, count) sorted by x (x may be a year).
             Gaps in x are filled with zeros so the automaton sees a
             contiguous stream.
    returns: dict with the state path and a list of bursts:
             {begin, end, strength, level, peak, weight, r_in, r_out}
             `weight` is Kleinberg's own weight, i.e. the sum of the
             levels visited during the burst; `strength` is the LLR.
    """
    if not series:
        return {'bursts': [], 'path': [], 'states': 0}

    xs = [int(s[0]) for s in series]
    lo, hi = min(xs), max(xs)
    n = hi - lo + 1
    grid = dict((int(a), int(b)) for a, b in series)
    r = [grid.get(lo + i, 0) for i in range(n)]

    total = float(sum(r))
    if total <= 0 or n < 2:
        return {'bursts': [], 'path': [], 'states': 0, 'r': r, 'x0': lo}

    base_rate = total / n
    if base_rate <= 0:
        base_rate = 1e-9

    # number of states: enough that the top state is clearly above the
    # maximum observed rate, but bounded so DP stays cheap
    if max(r) > 0:
        need = int(math.ceil(math.log(max(r) / base_rate + 1e-9, base))) + 1
    else:
        need = 1
    K = max(2, min(max_states, need + 1))

    emit = _log_poisson if density == 'poisson' else _log_exponential
    lams = [base_rate * (base ** i) for i in range(K)]

    # log emission matrix: logf[i][t]
    logf = [[emit(r[t], lams[i]) for t in range(n)] for i in range(K)]

    tau = [[(j - i) * gamma * math.log(n) if j > i else 0.0
            for j in range(K)] for i in range(K)]

    NEG = float('inf')
    C = [[0.0] * K for _ in range(n)]
    prev = [[0] * K for _ in range(n)]
    for i in range(K):
        C[0][i] = -logf[i][0]
        prev[0][i] = -1

    for t in range(1, n):
        for i in range(K):
            best, bj = NEG, 0
            for j in range(K):
                v = C[t - 1][j] + tau[j][i]
                if v < best:
                    best, bj = v, j
            C[t][i] = best - logf[i][t]
            prev[t][i] = bj

    # backtrack
    last = min(range(K), key=lambda i: C[n - 1][i])
    q = [0] * n
    q[n - 1] = last
    for t in range(n - 1, 0, -1):
        q[t - 1] = prev[t][q[t]]

    # contiguous runs with state > 0
    bursts = []
    t = 0
    while t < n:
        if q[t] == 0:
            t += 1
            continue
        s = t
        while t < n and q[t] > 0:
            t += 1
        e = t - 1
        if (e - s + 1) >= min_duration:
            seg = list(range(s, e + 1))
            strength = sum(logf[q[k]][k] - logf[0][k] for k in seg)
            weight = float(sum(q[k] for k in seg))
            r_in = sum(r[k] for k in seg)
            r_out = total - r_in
            bursts.append({
                'begin': lo + s,
                'end': lo + e,
                'duration': e - s + 1,
                'strength': round(float(strength), 3),
                'weight': round(weight, 3),
                'level': max(q[k] for k in seg),
                'count': int(r_in),
                'count_out': int(r_out),
                'peak': int(max(r[k] for k in seg)),
                'peak_year': lo + max(seg, key=lambda k: r[k]),
                'rate_in': round(r_in / float(len(seg)), 3),
                'rate_out': round(r_out / float(max(1, n - len(seg))), 3),
                'series': [r[k] for k in seg],
            })

    bursts.sort(key=lambda b: (-b['strength'], b['begin']))
    return {'bursts': bursts, 'path': q, 'states': K, 'r': r, 'x0': lo,
            'base_rate': round(base_rate, 4)}


def detect_all(counter_by_year, **kw):
    """counter_by_year: dict {item: {year: count}} -> {item: detect-result}."""
    out = {}
    for item, per_year in counter_by_year.items():
        if not per_year:
            continue
        res = detect(sorted(per_year.items()), **kw)
        res['total'] = sum(per_year.values())
        out[item] = res
    return out


def top_bursts(results, min_strength=0.0, limit=None):
    """Flatten detect_all output into one sorted list of burst records."""
    rows = []
    for item, res in results.items():
        for b in res['bursts']:
            if b['strength'] < min_strength:
                continue
            row = dict(b)
            row['term'] = item
            row['total'] = res.get('total', 0)
            rows.append(row)
    rows.sort(key=lambda x: (-x['strength'], -x['duration'], x['term']))
    if limit:
        rows = rows[:limit]
    return rows


if __name__ == '__main__':
    # synthetic sanity check: a flat stream with one obvious spike
    data = [(2000 + i, 2) for i in range(10)]
    data[5] = (2005, 3)
    data[6] = (2006, 14)
    data[7] = (2007, 16)
    data[8] = (2008, 12)
    res = detect(data)
    print('states:', res['states'], ' path:', res['path'])
    for b in res['bursts']:
        print(b)
