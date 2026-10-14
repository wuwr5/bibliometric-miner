# -*- coding: utf-8 -*-
"""
forecast.py -- Trend forecasting and emerging-topic detection.

Two independent parts:

1.  Time-series models for the volume of each term / topic, with rolling
    hold-out backtesting used to weight the models in an ensemble.
    Pure standard library; no numpy required.

    Models
      holt        Holt linear trend (exponential smoothing with trend)
      holt_damped Holt with damped trend (phi < 1), Gardner-McKenzie
      ar          AR(p) fitted by least squares (normal equations + Gauss elim.)
      gm11        Grey model GM(1,1) for short / sparse series
      logistic    Logistic growth S-curve
      gompertz    Gompertz growth S-curve

    Ensemble weights come from inverse-error backtesting on trailing windows
    (default origin = n-3), which is the usual recipe for short annual series.

2.  Emergence scoring after Rotolo et al. (2015): novelty, persistence,
    growth, -- all normalised into [0, 1] -- combined into an emergence
    score used to rank candidate emerging topics.  Candidate terms are
    additionally required to be "structured", i.e. to have moved into new
    clusters / gained new co-occurring neighbours (a structural-proximity
    signal in the spirit of the BiBLoX framework).

Reference
    Rotolo D, Hicks D, Martin BR. What is an emerging technology?
    Research Policy 2015;44(10):1827-1843.
"""

import math
from collections import Counter, defaultdict

try:
    import numpy as _np
except Exception:
    _np = None


EPS = 1e-12


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _fit_line(xs, ys):
    """Least squares y = a + b*x.  Returns (a, b)."""
    n = len(xs)
    if n == 0:
        return 0.0, 0.0
    if n == 1:
        return ys[0], 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= EPS:
        return my, 0.0
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    b = sxy / sxx
    return my - b * mx, b


def _solve(A, b):
    """Gaussian elimination with partial pivoting."""
    n = len(b)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(M[r][c]))
        if abs(M[piv][c]) < 1e-12:
            return [0.0] * n
        M[c], M[piv] = M[piv], M[c]
        pv = M[c][c]
        for r in range(n):
            if r == c:
                continue
            f = M[r][c] / pv
            if not f:
                continue
            for k in range(c, n + 1):
                M[r][k] -= f * M[c][k]
    return [M[i][n] / M[i][i] for i in range(n)]


def _rmse(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)) / len(a))


def _mape(actual, pred):
    tot, cnt = 0.0, 0
    for a, p in zip(actual, pred):
        if abs(a) > EPS:
            tot += abs((a - p) / a)
            cnt += 1
    return (tot / cnt if cnt else float('inf')), cnt


# --------------------------------------------------------------------------
# individual models
# --------------------------------------------------------------------------
def _holt(y, h, alpha=0.4, beta=0.15, phi=1.0):
    """Holt (damped) linear trend.  Returns list of h forecasts."""
    n = len(y)
    if n == 0:
        return [0.0] * h
    if n == 1:
        return [y[0] * 1.0] * h
    l = y[0]
    t = y[1] - y[0]
    for v in y:
        lp = l
        l = alpha * v + (1 - alpha) * (l + phi * t)
        t = beta * (l - lp) + (1 - beta) * phi * t
    out = []
    cum = 0.0
    for i in range(1, h + 1):
        cum += phi ** i
        out.append(max(0.0, l + cum * t))
    return out


def _ar(y, h, p=2):
    """AR(p) fitted by least squares, iterated multi-step forecast."""
    n = len(y)
    if n < p + 2:
        return None
    X, Y = [], []
    for i in range(p, n):
        X.append([1.0] + [y[i - 1 - k] for k in range(p)])
        Y.append(y[i])
    A = [[0.0] * (p + 1) for _ in range(p + 1)]
    b = [0.0] * (p + 1)
    for row, yi in zip(X, Y):
        for i in range(p + 1):
            b[i] += row[i] * yi
            for j in range(p + 1):
                A[i][j] += row[i] * row[j]
    for i in range(p + 1):
        A[i][i] += 1e-8
    coef = _solve(A, b)
    hist = list(y)
    out = []
    for _ in range(h):
        nxt = coef[0] + sum(coef[1 + k] * hist[-1 - k] for k in range(p))
        nxt = max(0.0, nxt)
        out.append(nxt)
        hist.append(nxt)
    return out


def _gm11(y, h):
    """Grey model GM(1,1): accumulate, fit a first-order ODE, restore."""
    n = len(y)
    if n < 3:
        return None
    yy = [max(0.0, v) for v in y]
    if sum(yy) <= EPS:
        return [0.0] * h
    ago = []
    s = 0.0
    for v in yy:
        s += v
        ago.append(s)
    Z = [0.5 * (ago[i] + ago[i - 1]) for i in range(1, n)]
    B = [[-z, 1.0] for z in Z]
    Ymat = yy[1:]
    A = [[0.0, 0.0], [0.0, 0.0]]
    bb = [0.0, 0.0]
    for i, row in enumerate(B):
        for r in range(2):
            bb[r] += row[r] * Ymat[i]
            for c in range(2):
                A[r][c] += row[r] * B[i][c]
    A[0][0] += 1e-9
    A[1][1] += 1e-9
    a, u = _solve(A, bb)
    if abs(a) < 1e-9:
        return None
    base = yy[0] - u / a
    out = []
    for k in range(n, n + h):
        vk = (base * math.exp(-a * k)) * (1 - math.exp(a))
        out.append(max(0.0, vk))
    return out


def _grow(y, h, kind='logistic'):
    """
    Fit a 3-parameter S-curve (logistic or Gompertz) by coarse grid search
    over the carrying capacity K, the growth rate r and the inflection point
    t0.  Grid search keeps this dependency-free and avoids the divergence of
    plain Newton schemes on short, noisy series.
    """
    n = len(y)
    if n < 4:
        return None
    ymax = max(y)
    best = None
    for mult in [1.02, 1.1, 1.2, 1.35, 1.6, 2.0, 3.0, 5.0]:
        Kt = max(ymax * mult, 1.0)
        if Kt <= ymax:
            continue
        for r in [0.05, 0.1, 0.15, 0.2, 0.3, 0.45, 0.6, 0.8]:
            for t0 in [0.5 * i for i in range(0, 2 * n)]:
                err = 0.0
                for i, v in enumerate(y):
                    if kind == 'logistic':
                        p = Kt / (1.0 + math.exp(-r * (i - t0)))
                    else:
                        p = Kt * math.exp(-math.exp(-r * (i - t0)))
                    err += (p - v) ** 2
                if best is None or err < best[0]:
                    best = (err, Kt, r, t0)
    if best is None:
        return None
    _err, Kt, r, t0 = best
    out = []
    for i in range(n, n + h):
        if kind == 'logistic':
            out.append(max(0.0, Kt / (1.0 + math.exp(-r * (i - t0)))))
        else:
            out.append(max(0.0, Kt * math.exp(-math.exp(-r * (i - t0)))))
    return out


# --------------------------------------------------------------------------
# ensemble with rolling backtest
# --------------------------------------------------------------------------
def _backtest(series, spec, holdout=3, max_origin=None):
    """
    Trailing-origin backtest.  Returns (mean_abs_err, rmse) or None when there
    is not enough history for even one origin.
    """
    n = len(series)
    origins = []
    for o in range(max(spec.get('min_n', 5), n - holdout), n):
        origins.append(o)
    if max_origin:
        origins = origins[-max_origin:]
    if not origins:
        return None
    errs, sqs = [], []
    for o in origins:
        tr = series[:o]
        try:
            pred = spec['fn'](tr, holdout)
        except Exception:
            continue
        if pred is None:
            continue
        act = series[o:o + holdout]
        m = min(len(pred), len(act))
        for i in range(m):
            errs.append(abs(act[i] - pred[i]))
            sqs.append((act[i] - pred[i]) ** 2)
    if not errs:
        return None
    return (sum(errs) / len(errs), math.sqrt(sum(sqs) / len(sqs)))


_SPECS = [
    ('holt',        {'min_n': 4, 'fn': lambda y, h: _holt(y, h)}),
    ('holt_damped', {'min_n': 4, 'fn': lambda y, h: _holt(y, h, phi=0.85)}),
    ('ar1',         {'min_n': 5, 'fn': lambda y, h: _ar(y, h, 1)}),
    ('ar2',         {'min_n': 6, 'fn': lambda y, h: _ar(y, h, 2)}),
    ('gm11',        {'min_n': 4, 'fn': _gm11}),
    ('logistic',    {'min_n': 5, 'fn': lambda y, h: _grow(y, h, 'logistic')}),
    ('gompertz',    {'min_n': 5, 'fn': lambda y, h: _grow(y, h, 'gompertz')}),
]


def forecast_series(series, horizon=3, holdout=3):
    """
    Fit all models, weight them by trailing backtest error, and return the
    ensemble forecast with a rough 80% band derived from the backtest residual
    spread scaled by sqrt(lead).

    Returns dict with keys: history, forecast, lower, upper, models, weights,
    mae, rmse, trend_slope, doubling (None when not applicable).
    """
    n = len(series)
    res_m, active = {}, []
    for name, spec in _SPECS:
        if n < spec['min_n']:
            continue
        m = _backtest(series, spec, holdout=holdout)
        if m is None:
            continue
        res_m[name] = m
        try:
            f = spec['fn'](series, horizon)
        except Exception:
            f = None
        if f is not None and all(math.isfinite(v) for v in f):
            active.append((name, f, m[0]))
    if not active:
        last = series[-1] if series else 0.0
        return {
            'history': list(series),
            'forecast': [last] * horizon,
            'lower': [max(0.0, last * 0.6)] * horizon,
            'upper': [last * 1.4] * horizon,
            'models': {}, 'weights': {}, 'mae': None, 'rmse': None,
            'trend_slope': 0.0, 'note': 'naive',
        }
    # inverse-MSE weights (bounded) so that one excellent model cannot
    # completely silence the others
    ws = {}
    for name, _f, mae in active:
        ws[name] = 1.0 / (mae + 0.5)
    tot = sum(ws.values())
    ws = {k: v / tot for k, v in ws.items()}
    fc = []
    for i in range(horizon):
        fc.append(sum(ws[n] * f[i] for n, f, _m in active))
    # Residual scale from the best model's backtest error, widened by the
    # disagreement among the retained models so the band does not collapse
    # when one model happens to fit the last few origins very well.
    best_mae = min(m for _n, _f, m in active)
    disag = []
    for i in range(horizon):
        vals = [f[i] for _n, f, _m in active]
        disag.append(max(vals) - min(vals))
    lo, hi = [], []
    for i, v in enumerate(fc):
        spread = max(0.674 * best_mae, 0.5 * disag[i]) * math.sqrt(i + 1)
        lo.append(max(0.0, v - spread))
        hi.append(v + spread)
    a, b = _fit_line(list(range(n)), [float(v) for v in series])
    return {
        'history': [round(v, 3) for v in series],
        'forecast': [round(v, 3) for v in fc],
        'lower': [round(v, 3) for v in lo],
        'upper': [round(v, 3) for v in hi],
        'models': {name: {'mae': round(m[0], 3), 'rmse': round(m[1], 3)}
                   for name, m in res_m.items()},
        'weights': {k: round(v, 4) for k, v in ws.items()},
        'mae': round(best_mae, 3),
        'trend_slope': round(b, 4),
        'note': '',
    }


# --------------------------------------------------------------------------
# Rotolo emergence
# --------------------------------------------------------------------------
def _entropy(counter):
    tot = sum(counter.values())
    if tot <= 0:
        return 0.0
    h = 0.0
    for v in counter.values():
        p = v / float(tot)
        if p > 0:
            h -= p * math.log(p)
    return h


def emergence_scores(series_map, years, cluster_of=None, nbr_of=None,
                     cat_of=None, recent_window=3, prior_window=3):
    """
    series_map : term -> {year: count} restricted to the (selected) nodes
    years      : sorted list of analysis years
    cluster_of : term -> community id (optional)
    nbr_of     : term -> set of neighbours (optional)
    cat_of     : term -> Counter of WoS categories (optional); when given,
                 the normalised Shannon entropy of this distribution is used
                 as the "uncertainty" component.  In Rotolo's framework
                 uncertainty means the topic has not yet settled into a
                 stable institutional / cognitive home; spreading across
                 many disciplines is the closest bibliometric analogue.
    """
    if not years:
        return []
    y_last = years[-1]
    recent = [y for y in years if y > y_last - recent_window]
    prior = [y for y in years if y <= y_last - recent_window
             and y > y_last - recent_window - prior_window]
    rows = []
    by_term = {}
    for term, yc in series_map.items():
        tot = sum(yc.values())
        if tot < 3:
            continue
        first_year = min(y for y in yc if yc[y] > 0)
        # ---- persistence: number of active years / span -------------------
        active = [y for y in years if yc.get(y, 0) > 0]
        pers = len(active) / float(len(years))
        # ---- growth: recent vs prior mean count ---------------------------
        r_sum = sum(yc.get(y, 0) for y in recent)
        p_sum = sum(yc.get(y, 0) for y in prior)
        r_mean = r_sum / max(1, len(recent))
        p_mean = p_sum / max(1, len(prior))
        growth = 0.0
        if p_mean > 0:
            growth = (r_mean - p_mean) / p_mean
        elif r_mean > 0:
            growth = 2.0
        growth = max(-1.0, min(5.0, growth))
        # ---- novelty: late arrival + rising shape -------------------------
        span = max(1, y_last - min(years))
        novelty = 1.0 - (first_year - min(years)) / float(span)
        # recency-weighted centre of mass (0 = old, 1 = new)
        com = sum(yc[y] * (y - min(years)) for y in yc) / float(tot * span)
        novelty = 0.5 * novelty + 0.5 * com
        # ---- uncertainty: not yet settled into one cognitive home ---------
        unc = 0.0
        if cat_of and cat_of.get(term):
            h = _entropy(cat_of[term])
            hmax = math.log(max(2, len(cat_of[term])))
            unc = max(0.0, min(1.0, h / hmax))
        if nbr_of and term in nbr_of:
            nb = nbr_of[term]
            if nb:
                newish = sum(1 for t in nb
                             if (series_map.get(t) and
                                 min(series_map[t]) >= recent[0]))
                unc = max(unc, newish / float(len(nb)))
        rows.append({
            'term': term,
            'total': int(tot),
            'first_year': int(first_year),
            'recent_mean': round(r_mean, 2),
            'prior_mean': round(p_mean, 2),
            'growth': round(growth, 3),
            'persistence': round(pers, 3),
            'novelty': round(novelty, 3),
            'uncertainty': round(unc, 3),
        })
        by_term[term] = True
    if not rows:
        return []
    # normalise components to [0, 1] across the candidate set
    def _norm(key, lo=None, hi=None):
        vals = [r[key] for r in rows]
        mn = lo if lo is not None else min(vals)
        mx = hi if hi is not None else max(vals)
        for r in rows:
            r[key + '_n'] = 0.0 if mx - mn < EPS else (r[key] - mn) / (mx - mn)
    _norm('growth', 0.0, None)
    _norm('persistence', 0.0, 1.0)
    _norm('novelty', 0.0, 1.0)
    _norm('uncertainty', 0.0, 1.0)
    for r in rows:
        r['emergence'] = round(
            0.30 * r['growth_n'] + 0.25 * r['persistence_n'] +
            0.25 * r['novelty_n'] + 0.20 * r['uncertainty_n'], 4)
    rows.sort(key=lambda r: (-r['emergence'], -r['total']))
    for i, r in enumerate(rows):
        r['rank'] = i + 1
    del by_term
    return rows


# --------------------------------------------------------------------------
# driver
# --------------------------------------------------------------------------
def run(docs, params, log=None):
    """
    params
      node_type    'keyword' | 'ref' | 'author' | ... (default 'keyword')
      criterion / criterion_value
      horizon      forecast years ahead (default 3)
      holdout      backtest horizon (default 3)
      top          number of terms to model in detail (default 40)
    """
    L = log.append if log is not None else (lambda *_: None)
    node_type = params.get('node_type', 'keyword')
    top_n = int(params.get('criterion_value', 40) or 40)
    horizon = int(params.get('horizon', 3) or 3)
    holdout = int(params.get('holdout', 3) or 3)
    detail_top = int(params.get('top', 30) or 30)

    import analyze as az
    n = Counter()
    per_year = defaultdict(Counter)
    first_year = {}
    nbr = defaultdict(set)
    cat_of = defaultdict(Counter)
    try:
        nested = az._doc_items(docs, node_type)
    except Exception as exc:
        return {'error': 'unsupported node type %s (%s)' % (node_type, exc)}
    for items, d in zip(nested, docs):
        try:
            year = int(d.get('year'))
        except Exception:
            continue
        uniq = sorted(set(items))
        for it in uniq:
            n[it] += 1
            per_year[it][year] += 1
            if it not in first_year or year < first_year[it]:
                first_year[it] = year
        for a, b in _combinations(uniq):
            nbr[a].add(b)
            nbr[b].add(a)
        cats = [c.strip() for c in (d.get('categories') or []) if c.strip()]
        if cats:
            for it in uniq:
                cat_of[it].update(cats)
    if not n:
        return {'error': 'no terms found'}

    order = [t for t, _c in n.most_common(top_n)]
    years_all = sorted({int(d['year']) for d in docs if d.get('year')})

    # ---- drop an incomplete trailing year --------------------------------
    # A partially observed final year (e.g. an export taken mid-year) is the
    # single most damaging artefact here: every model anchors on the last
    # observation, so a truncated tail silently drags the whole forecast
    # down and inflates the backtest error.  We compare the last year against
    # the median of the three preceding ones and discard it when it has not
    # reached half that level.
    dropped_year = None
    if len(years_all) >= 4:
        tail = []
        for y in years_all:
            tail.append(sum(1 for d in docs
                            if d.get('year') and int(d['year']) == y))
        prev = sorted(tail[-4:-1])
        med_prev = prev[1] if len(prev) == 3 else (prev[0] + prev[-1]) / 2.0
        if med_prev > 0 and tail[-1] < 0.5 * med_prev:
            dropped_year = years_all[-1]
            L('dropped incomplete trailing year %d (%d records vs median %.0f '
              'of the three preceding years)' % (dropped_year, tail[-1],
                                                 med_prev))
    years = [y for y in years_all if y != dropped_year]
    if len(years) < 4:
        return {'error': 'too few complete years (%d) to forecast' % len(years)}

    series_map = {}
    for t in order:
        row = []
        for y in years:
            row.append(float(per_year[t].get(y, 0)))
        series_map[t] = row

    L('forecasting %d series over %d years (horizon=%d, holdout=%d)'
      % (len(order), len(years), horizon, holdout))
    labels = {t: t.title() if node_type == 'keyword' else t for t in order}
    fc = {}
    for t in order[:detail_top]:
        fc[t] = forecast_series(series_map[t], horizon=horizon,
                                holdout=holdout)
    # document counts per year (overall activity trend)
    doc_series = [float(sum(1 for d in docs
                            if d.get('year') and int(d['year']) == y))
                  for y in years]

    em = emergence_scores({t: {y: per_year[t].get(y, 0) for y in years}
                           for t in order}, years, nbr_of=nbr, cat_of=cat_of)
    for r in em:
        r['label'] = labels.get(r['term'], r['term'])
        r = _maybe_forecast(r, fc, r['term'])
    return {
        'years': years,
        'dropped_year': dropped_year,
        'doc_series': [int(v) for v in doc_series],
        'doc_forecast': forecast_series(doc_series, horizon=horizon,
                                        holdout=max(1, holdout)),
        'terms': order,
        'labels': labels,
        'series': {t: [int(v) for v in series_map[t]] for t in order},
        'forecast': {t: fc[t] for t in list(fc)[:detail_top]},
        'emergence': em,
        'summary': {
            'n_terms': len(order),
            'n_years': len(years),
            'horizon': horizon,
            'n_emerging': len(em),
            'node_type': node_type,
        },
    }


def _maybe_forecast(row, fc, term):
    f = fc.get(term)
    if f:
        row['forecast'] = f['forecast']
        row['forecast_dir'] = 1 if f['forecast'] and \
            f['forecast'][-1] > f['history'][-1] else 0
    return row


def _combinations(seq):
    for i in range(len(seq)):
        for j in range(i + 1, len(seq)):
            yield seq[i], seq[j]


def _default_items(d, node_type):
    if node_type == 'keyword':
        return [k.strip().lower() for k in d.get('keywords', []) if k.strip()]
    if node_type == 'author':
        return [a.strip() for a in d.get('authors', []) if a.strip()]
    if node_type == 'ref':
        return [r.get('key') for r in d.get('refs', []) if r.get('key')]
    return []


# --------------------------------------------------------------------------
if __name__ == '__main__':
    print('=== forecast: synthetic monotone series ===')
    y = [1, 2, 3, 4, 6, 8, 11, 15, 20, 27, 36, 48]
    r = forecast_series([float(v) for v in y], horizon=3)
    print('history  ', r['history'])
    print('forecast ', r['forecast'])
    print('band     ', r['lower'], '->', r['upper'])
    print('weights  ', r['weights'])
    print('models   ', r['models'])
    assert r['forecast'][-1] > r['history'][-1], 'increasing series must rise'
    ok = 'OK increasing'

    r2 = forecast_series([10.0, 9, 8, 7, 6, 5, 4, 3, 2, 1], horizon=2)
    print('\ndecreasing ->', r2['forecast'], r2['weights'])
    assert r2['forecast'][-1] < r2['history'][-1], 'decreasing series must fall'
    print('OK decreasing')

    print('\n=== emergence: late-rising term must outrank flat old term ===')
    years = list(range(2015, 2026))
    sm = {
        'new_thing': {y: (0 if y < 2022 else 30) for y in years},
        'old_flat': {y: 12 for y in years},
        'old_dying': {y: (40 if y < 2019 else 2) for y in years},
    }
    em = emergence_scores(sm, years, nbr_of={'new_thing': {'a', 'b'},
                                             'old_flat': {'new_thing'},
                                             'old_dying': set()})
    for e in em:
        print('   %-10s em=%.3f growth=%.2f pers=%.2f nov=%.2f unc=%.2f'
              % (e['term'], e['emergence'], e['growth'], e['persistence'],
                 e['novelty'], e['uncertainty']))
    assert em[0]['term'] == 'new_thing', 'late riser must rank first'
    assert em[-1]['term'] == 'old_dying', 'declining old term must rank last'
    print('OK emergence ranking ->', ok)
