# -*- coding: utf-8 -*-
"""
make_sample.py -- synthesise a Web of Science plain-text file that has the
structure a real export would have (clear topical clusters that rise and
fall over time, so that burst detection / timeline / clustering all have
something meaningful to find).

Deterministic (fixed RNG seed) -> the demo is reproducible.

    python make_sample.py [out_path] [n_docs]
"""

import os
import random
import sys

SEED = 20261011

# --------------------------------------------------------------------------
# topical clusters: (name, start, peak, end, weight, keywords, journals)
# --------------------------------------------------------------------------
CLUSTERS = [
    dict(name='transplant', start=1995, peak=2002, end=2012, w=1.0,
         kw=['liver transplantation', 'fulminant hepatic failure',
             'hepatic encephalopathy', 'donor selection', 'graft survival',
             'auxiliary transplantation', 'hepatocyte transplantation',
             'retransplantation', 'immunosuppression'],
         jo=['TRANSPLANTATION', 'LIVER TRANSPLANTATION', 'HEPATOLOGY',
             'AMERICAN JOURNAL OF TRANSPLANTATION', 'TRANSPLANT PROCEEDINGS']),
    dict(name='liver_support', start=2000, peak=2009, end=2017, w=1.0,
         kw=['artificial liver support', 'bioartificial liver',
             'plasma exchange', 'hemodiafiltration', 'albumin dialysis',
             'MARS', 'extracorporeal', 'detoxification', 'bridge to transplant'],
         jo=['ARTIFICIAL ORGANS', 'INTENSIVE CARE MEDICINE',
             'CRITICAL CARE MEDICINE', 'BLOOD PURIFICATION',
             'JOURNAL OF HEPATOLOGY']),
    dict(name='scores', start=2004, peak=2013, end=2020, w=1.1,
         kw=['MELD score', 'prognostic score', 'acute-on-chronic liver failure',
             'ACLF', 'Child-Pugh', 'SOFA score', 'King\'s College criteria',
             'mortality', 'risk stratification', 'organ failure'],
         jo=['JOURNAL OF HEPATOLOGY', 'HEPATOLOGY', 'GUT',
             'CRITICAL CARE', 'LIVER INTERNATIONAL', 'HEPATOLOGY INTERNATIONAL']),
    dict(name='critical_care', start=2009, peak=2017, end=2024, w=1.2,
         kw=['intensive care unit', 'critical care', 'mechanical ventilation',
             'sepsis', 'acute kidney injury', 'vasopressor',
             'intracranial pressure', 'multiple organ dysfunction',
             'hemodynamic monitoring', 'continuous renal replacement therapy'],
         jo=['CRITICAL CARE MEDICINE', 'INTENSIVE CARE MEDICINE',
             'CRITICAL CARE', 'JOURNAL OF CRITICAL CARE',
             'SHOCK', 'ANNALS OF INTENSIVE CARE']),
    dict(name='machine_learning', start=2016, peak=2022, end=2024, w=1.5,
         kw=['machine learning', 'deep learning', 'prediction model',
             'nomogram', 'artificial intelligence', 'risk prediction',
             'neural network', 'XGBoost', 'electronic health record',
             'MIMIC-IV', 'explainable', 'dynamic prediction'],
         jo=['JOURNAL OF MEDICAL INTERNET RESEARCH', 'CRITICAL CARE',
             'IEEE JOURNAL OF BIOMEDICAL AND HEALTH INFORMATICS',
             'HEPATOLOGY INTERNATIONAL', 'FRONTIERS IN MEDICINE',
             'JOURNAL OF HEPATOLOGY']),
    dict(name='omics', start=2011, peak=2019, end=2024, w=1.0,
         kw=['biomarkers', 'metabolomics', 'inflammation', 'cytokines',
             'gut microbiota', 'transcriptomics', 'immune dysfunction',
             'regeneration', 'proteomics', 'single-cell'],
         jo=['HEPATOLOGY', 'JOURNAL OF HEPATOLOGY', 'GUT',
             'HEPATOLOGY COMMUNICATIONS', 'SCIENTIFIC REPORTS',
             'FRONTIERS IN IMMUNOLOGY']),
]

# bursty terms: (term, cluster, from, to, multiplier)
BURSTS = [
    ('plasma exchange', 'liver_support', 2008, 2013, 6.0),
    ('acute-on-chronic liver failure', 'scores', 2012, 2018, 5.0),
    ('machine learning', 'machine_learning', 2019, 2024, 7.0),
    ('MIMIC-IV', 'machine_learning', 2021, 2024, 6.0),
    ('gut microbiota', 'omics', 2019, 2023, 4.0),
    ('acute kidney injury', 'critical_care', 2013, 2019, 4.0),
    ('bioartificial liver', 'liver_support', 2004, 2010, 5.0),
    ('MELD score', 'scores', 2006, 2013, 4.5),
]

SURNAMES = ['WU', 'CHEN', 'SMITH', 'LI', 'ZHANG', 'BROWN', 'WANG', 'LEE',
            'BERNAL', 'WENDON', 'ARROYO', 'OLSON', 'KIM', 'GARCIA', 'LIU',
            'MORE', 'JALAN', 'SHAH', 'KUMAR', 'PARK', 'SINGH', 'MARTIN',
            'JOHNSON', 'HUANG', 'XU', 'ANDERSON', 'TAYLOR', 'MOORE', 'YANG',
            'CLARK', 'HARRIS', 'ROBINSON', 'ZHOU', 'THOMAS', 'WALKER',
            'ALLEN', 'SCOTT', 'NELSON', 'ADAMS', 'BAKER', 'GONZALEZ',
            'PEREZ', 'TORRES', 'RAMIREZ', 'DIAZ', 'REYES', 'CRUZ', 'MORALES']

INITIALS = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'J', 'K', 'L', 'M',
            'N', 'P', 'Q', 'R', 'S', 'T', 'W', 'X', 'Y', 'Z']

ORGS = [
    'Kings Coll London, Inst Liver Studies',
    'Univ Barcelona, Hosp Clin, Barcelona, Spain',
    'Capital Med Univ, Beijing, Peoples R China',
    'Fudan Univ, Shanghai, Peoples R China',
    'Mayo Clin, Rochester, MN USA',
    'Harvard Univ, Massachusetts Gen Hosp, Boston, MA USA',
    'Univ Paris Sud, Hop Beaujon, Clichy, France',
    'Zhejiang Univ, Hangzhou, Peoples R China',
    'Univ Libre Bruxelles, Brussels, Belgium',
    'Univ Toronto, Toronto, ON Canada',
    'Chinese Acad Med Sci, Beijing, Peoples R China',
    'Sun Yat Sen Univ, Guangzhou, Peoples R China',
    'Univ Milan, Milan, Italy',
    'Univ Copenhagen, Copenhagen, Denmark',
    'Sichuan Univ, Chengdu, Peoples R China',
    'Univ Melbourne, Melbourne, Australia',
    'Seoul Natl Univ, Seoul, South Korea',
    'Naval Med Univ, Shanghai, Peoples R China',
    'Univ Amsterdam, Amsterdam, Netherlands',
    'Duke Univ, Durham, NC USA',
]

COUNTRIES = ['USA', 'Peoples R China', 'England', 'Spain', 'France',
             'Italy', 'Germany', 'Japan', 'South Korea', 'Netherlands',
             'Canada', 'Australia', 'Belgium', 'Denmark']

TITLE_TPL = [
    'Outcome of {kw1} in patients with acute liver failure',
    'A {method} study of {kw1} and {kw2}',
    'Risk factors for {kw1} among critically ill patients with {kw2}',
    '{kw1} and {kw2}: a multicenter cohort study',
    'Early identification of {kw1} using {kw2}',
    'Impact of {kw1} on mortality in the intensive care unit',
    'Temporal trends of {kw1} and {kw2}: 1995 to 2024',
    '{kw1} versus {kw2} in acute liver failure: a comparative analysis',
    'Dynamic prediction of {kw1} with {kw2}',
    'Association between {kw1} and short-term mortality',
]
METHODS = ['prospective', 'retrospective', 'nationwide', 'single-center',
           'population-based', 'propensity-matched', 'nested case-control']

ABS_TPL = [
    'Background & Aims: {kw1} remains a major determinant of outcome in '
    'acute liver failure. Methods: we evaluated {kw2} in {n} patients '
    'admitted to the intensive care unit. Results: {kw1} was independently '
    'associated with 28-day mortality (adjusted hazard ratio 1.{r}). '
    'Conclusions: incorporating {kw2} into routine assessment may improve '
    'risk stratification and guide {kw3}.',
    'Objective: to characterise the epidemiology of {kw1} and its interplay '
    'with {kw2}. Design: {method} cohort of {n} admissions with acute '
    'liver failure. Results: the incidence of {kw1} increased over the study '
    'period, and {kw2} modified this association. Conclusion: {kw1} and '
    '{kw2} should be jointly considered when predicting outcome.',
]
WOS_CATS = ['Gastroenterology & Hepatology', 'Critical Care Medicine',
            'Medicine, General & Internal', 'Transplantation',
            'Computer Science, Interdisciplinary Applications']


def _cluster_weight(c, year):
    """Bell shaped activity curve over the cluster life span."""
    span = max(1.0, float(c['end'] - c['peak']))
    rise = max(1.0, float(c['peak'] - c['start']))
    if year < c['peak']:
        x = (year - c['start']) / rise
        v = max(0.0, x) ** 1.4
    else:
        x = (year - c['peak']) / span
        v = max(0.0, 1.0 - x) ** 1.1
    return max(0.02, v * c['w'])


def _burst_bonus(term, year):
    for t, cl, a, b, mult in BURSTS:
        if t.lower() == term.lower() and a <= year <= b:
            return mult
    return 1.0


def build(out_path, n_docs=800, year_lo=1995, year_hi=2024, seed=SEED):
    rnd = random.Random(seed)
    random.Random(seed + 1)

    # ---- author / reference pools per cluster ---------------------------
    pools = {}
    for c in CLUSTERS:
        authors = ['%s %s' % (rnd.choice(SURNAMES), rnd.choice(INITIALS))
                   for _ in range(46)]
        authors = list(dict.fromkeys(authors))
        while len(authors) < 40:
            authors.append('%s %s' % (rnd.choice(SURNAMES),
                                      rnd.choice(INITIALS)))
        # classic references of this cluster (the co-citation backbone)
        refs = []
        for i in range(46):
            y = max(c['start'] - 1,
                    int(c['peak'] - abs(rnd.gauss(0, 3.5))))
            y = min(y, c['end'])
            refs.append({
                'au': '%s %s' % (rnd.choice(SURNAMES), rnd.choice(INITIALS)),
                'yr': y,
                'jo': rnd.choice(c['jo']),
                'vol': rnd.randint(1, 90),
                'pg': rnd.randint(1, 2500),
            })
        pools[c['name']] = {'authors': authors, 'refs': refs}

    # ---- yearly document counts -----------------------------------------
    years = list(range(year_lo, year_hi + 1))
    weights = []
    for y in years:
        tot = sum(_cluster_weight(c, y) for c in CLUSTERS)
        # overall publication growth
        growth = 0.55 + 0.9 * (y - year_lo) / float(year_hi - year_lo)
        weights.append(tot * growth)
    scale = n_docs / float(sum(weights))
    n_per_year = [max(1, int(round(w * scale))) for w in weights]

    docs = []     # published docs, used as recent citation targets
    lines = ['FN Clarivate Analytics Web of Science',
             'VR 1.0']

    def ref_line(au, yr, jo, vol, pg, doi=True):
        s = '%s, %d, %s, V%d, P%d' % (au, yr, jo, vol, pg)
        if doi:
            s += ', DOI 10.%d/j.jhep.%d.%03d' % (rnd.randint(1000, 9999),
                                                 yr, rnd.randint(100, 999))
        return s

    for y, k in zip(years, n_per_year):
        cw = [(_cluster_weight(c, y), c) for c in CLUSTERS]
        tot_w = sum(w for w, _ in cw) or 1.0
        for _ in range(k):
            # pick a primary cluster
            r = rnd.random() * tot_w
            acc, primary = 0.0, cw[-1][1]
            for w, c in cw:
                acc += w
                if r <= acc:
                    primary = c
                    break
            # sometimes a paper bridges two clusters
            bridge = None
            if rnd.random() < 0.34:
                others = [c for c in CLUSTERS if c['name'] != primary['name']]
                bridge = rnd.choice(others)

            # ---- keywords -----------------------------------------------
            kws = []
            pool = list(primary['kw'])
            rnd.shuffle(pool)
            for term in pool[:rnd.randint(3, 5)]:
                if rnd.random() < 0.30 * _burst_bonus(term, y) / 6.0 or True:
                    kws.append(term)
            if bridge:
                bp = list(bridge['kw'])
                rnd.shuffle(bp)
                kws.extend(bp[:rnd.randint(1, 2)])
            # inject the bursty terms with their boosted probability
            for t, cl, a, b, mult in BURSTS:
                if a <= y <= b and any(c['name'] == cl for c in CLUSTERS):
                    if rnd.random() < 0.16 * mult / 6.0:
                        kws.append(t)
            kws = list(dict.fromkeys(kws))
            if len(kws) < 3:
                kws.extend(primary['kw'][:3])
            kws = list(dict.fromkeys(kws))[:8]

            # ---- authors --------------------------------------------------
            n_au = rnd.randint(2, 7)
            apool = pools[primary['name']]['authors']
            if bridge and rnd.random() < 0.5:
                apool = apool + pools[bridge['name']]['authors']
            authors = rnd.sample(apool, min(n_au, len(apool)))
            rnd.shuffle(authors)

            # ---- title / abstract ------------------------------------------
            kw1, kw2 = kws[0], (kws[1] if len(kws) > 1 else primary['kw'][1])
            kw3 = kws[2] if len(kws) > 2 else primary['kw'][2]
            title = rnd.choice(TITLE_TPL).format(kw1=kw1, kw2=kw2,
                                                method=rnd.choice(METHODS))
            abstract = rnd.choice(ABS_TPL).format(
                kw1=kw1, kw2=kw2, kw3=kw3, n=rnd.randint(80, 2600),
                r=rnd.randint(10, 95), method=rnd.choice(METHODS))

            # ---- references -------------------------------------------------
            refs = []
            n_ref = rnd.randint(16, 38)
            # 60% classic backbone of the primary (+bridge) cluster
            for _ in range(int(n_ref * 0.6)):
                c = primary if rnd.random() < 0.78 or not bridge else bridge
                r0 = rnd.choice(pools[c['name']]['refs'])
                refs.append(ref_line(r0['au'], r0['yr'], r0['jo'],
                                     r0['vol'], r0['pg'],
                                     rnd.random() < 0.7))
            # 40% recent literature (last 8 years), preferring same cluster
            recent = [d for d in docs if y - d['year'] <= 8]
            if recent:
                for _ in range(n_ref - len(refs)):
                    if rnd.random() < 0.6:
                        same = [d for d in recent
                                if d['cluster'] == primary['name']]
                        src = rnd.choice(same) if same else rnd.choice(recent)
                    else:
                        src = rnd.choice(recent[-400:])
                    refs.append(ref_line(src['au'], src['year'], src['jo'],
                                         src['vol'], src['pg'],
                                         rnd.random() < 0.75))
            # a few evergreen external classics shared by every cluster
            for au, yr, jo in (('BERNAL W', 2007, 'LANCET'),
                               ('ARROYO V', 2000, 'J HEPATOL'),
                               ('WENDON J', 2005, 'SEMIN LIVER DIS')):
                if rnd.random() < 0.35:
                    refs.append(ref_line(au, yr, jo, rnd.randint(1, 90),
                                         rnd.randint(1, 1800)))
            refs = list(dict.fromkeys(refs))

            # ---- addresses ----------------------------------------------------
            n_org = rnd.randint(1, 3)
            orgs = rnd.sample(ORGS, n_org)
            c1_parts = []
            for i, o in enumerate(orgs):
                au = authors[i] if i < len(authors) else authors[0]
                c1_parts.append('[%s] %s' % (au, o))
            c1 = '; '.join(c1_parts)

            age = max(0, year_hi - y)
            tc = max(0, int(rnd.expovariate(1.0 / (2 + age * 2.4))))
            vol = rnd.randint(1, 90)
            pg0 = rnd.randint(1, 2400)
            doi = '10.%d/j.jhep.%d.%04d' % (rnd.randint(1000, 9999), y,
                                            rnd.randint(1000, 9999))
            ut = 'WOS:%09d%03d' % (rnd.randint(100000000, 999999999), y)

            rec = []
            rec.append('PT J')
            for i, a in enumerate(authors):
                rec.append(('AU ' if i == 0 else '   ') + a)
            rec.append('TI ' + title)
            rec.append('SO ' + rnd.choice(primary['jo']))
            rec.append('LA English')
            rec.append('DT Article')
            rec.append('DE ' + '; '.join(kws[:5]))
            rec.append('ID ' + '; '.join(kws[3:6] if len(kws) > 5 else kws[:3]))
            rec.append('AB ' + abstract)
            rec.append('C1 ' + c1)
            rec.append('RP %s (corresponding author), %s' % (authors[0],
                                                             orgs[0]))
            rec.append('EM %s@example.org' % authors[0].split(' ')[0].lower())
            for i, r in enumerate(refs):
                rec.append(('CR ' if i == 0 else '   ') + r)
            rec.append('NR %d' % len(refs))
            rec.append('TC %d' % tc)
            rec.append('PY %d' % y)
            rec.append('VL %d' % vol)
            rec.append('IS %d' % rnd.randint(1, 12))
            rec.append('DI %s' % doi)
            rec.append('PG %d-%d' % (pg0, pg0 + rnd.randint(6, 16)))
            rec.append('SC ' + rnd.choice(WOS_CATS))
            rec.append('UT %s' % ut)
            if rnd.random() < 0.55:
                rec.append('PM %d' % rnd.randint(10000000, 39999999))
            rec.append('ER')
            rec.append('')
            lines.extend(rec)

            docs.append({'au': authors[0], 'year': y,
                         'jo': rnd.choice(primary['jo']), 'vol': vol,
                         'pg': pg0, 'cluster': primary['name']})

    lines.append('EF')
    text = '\n'.join(lines) + '\n'
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(text)
    return out_path, len(docs), len(text)


if __name__ == '__main__':
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), 'sample',
        'wos_alf_demo_800.txt')
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 800
    p, nd, size = build(out, n)
    print('wrote %s' % p)
    print('  documents : %d' % nd)
    print('  size      : %.2f MB' % (size / 1048576.0))
