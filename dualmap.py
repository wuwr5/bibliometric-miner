# -*- coding: utf-8 -*-
"""
dualmap.py -- dual-map overlay (Chen & Leydesdorff 2014).

A dual-map overlay draws two global science maps facing each other: on the
left the journals that do the citing (the *source* / citing side), on the
right the journals that are cited (the *target* side).  Every citation is a
curve from the citing journal to the cited journal, so the picture shows
where a body of literature draws its knowledge from and where it publishes.

Both sides need a discipline label per journal.  Web of Science exports do
not carry a journal-to-category dictionary, so the label is inferred from
the data itself:

  * citing journals  -> the dominant WoS subject category (WC/SC) of the
                        documents published in that journal;
  * cited journals   -> the dominant WoS category of the documents that cite
                        it (its "field as seen by the citing literature");
  * fallback         -> a keyword heuristic on the journal title.

The inference is written into `journal_discipline` in the output so a user
can inspect it (and override it in assets/journal_discipline.json).

Output is layout-ready: node coordinates live in a normalised [0,1] box and
are scaled by the front end.
"""

import os
import json
import math
import re
from collections import defaultdict, Counter

HERE = os.path.dirname(os.path.abspath(__file__))
OVERRIDE_FILE = os.path.join(HERE, 'assets', 'journal_discipline.json')


# --------------------------------------------------------------------------
# WoS subject category -> macro discipline
# --------------------------------------------------------------------------
# Ordered: the first matching rule wins, so specific fields come first.
MACRO_RULES = [
    ('Neuroscience & Psychology',
     ('NEUROSCI', 'NEUROLOG', 'BEHAVIORAL', 'PSYCHOL', 'PSYCHIATR')),
    ('Pharmacology & Toxicology',
     ('PHARMACOL', 'TOXICOL', 'PHARMACY', 'DRUG')),
    ('Microbiology & Immunology',
     ('MICROBIOL', 'IMMUNOL', 'VIROLOG', 'PARASITOL', 'MYCOLOG')),
    ('Molecular Biology & Genetics',
     ('BIOCHEM', 'MOLECULAR BIOLOGY', 'GENETICS', 'CELL BIOLOGY',
      'BIOLOGY', 'BIOPHYS', 'BIOTECHNOL', 'DEVELOPMENTAL BIOLOGY',
      'REPRODUCTIVE', 'ANATOMY')),
    ('Chemistry & Materials',
     ('CHEM', 'MATERIALS', 'POLYMER', 'CRYSTALLOGR', 'METALLURG',
      'NANOSCI', 'SPECTROSCOP')),
    ('Physics & Astronomy',
     ('PHYSICS', 'ASTRONOM', 'OPTICS', 'ACOUSTICS', 'NUCLEAR')),
    ('Engineering & Technology',
     ('ENGINEER', 'COMPUTER', 'TELECOMMUN', 'ROBOTICS', 'AUTOMATION',
      'INSTRUMENTS', 'ENERGY', 'ELECTRIC', 'REMOTE SENSING', 'IMAGING')),
    ('Mathematics & Statistics',
     ('MATHEMAT', 'STATISTIC', 'PROBABIL')),
    ('Environmental & Ecology',
     ('ENVIRONMENTAL', 'ECOLOG', 'MARINE', 'WATER', 'METEOROLOG',
      'GEOSCIENC', 'GEOLOG', 'SOIL', 'BIODIVERSITY', 'OCEANOGR',
      'PALEONTOL', 'LIMNOLOG', 'ORNITHOLOG')),
    ('Agriculture & Veterinary',
     ('AGRICULT', 'AGRONOM', 'VETERINARY', 'ANIMAL', 'FISHER',
      'DAIRY', 'FOOD SCIENCE', 'HORTICULT', 'PLANT SCIENCE',
      'ENTOMOLOG', 'FORESTRY', 'AQUACULT')),
    ('Health, Nursing & Public Health',
     ('NURSING', 'HEALTH CARE', 'HEALTH POLICY', 'PUBLIC HEALTH',
      'REHABILITAT', 'OCCUPATIONAL', 'SPORT SCIENCE', 'GERIATRIC',
      'SUBSTANCE ABUSE', 'HEALTH')),
    ('Medicine & Clinical',
     ('MEDICINE', 'CLINICAL', 'SURGERY', 'SURG', 'PEDIATR', 'CARDIO',
      'ONCOLOG', 'RADIOLOG', 'ANESTHESIOL', 'EMERGENCY', 'INFECTIOUS',
      'UROLOGY', 'OBSTET', 'GASTRO', 'HEMATOLOG', 'DERMATOL',
      'OPHTHALMOL', 'ORTHOPED', 'OTORHINOLARYNG', 'PATHOLOG',
      'RESPIRATORY', 'RHEUMATOL', 'TRANSPLANT', 'CRITICAL CARE',
      'DENTISTRY', 'NEPHROL', 'ENDOCRINOL', 'GERONTOLOG',
      'INTEGRATIVE', 'TROPICAL')),
    ('Social Sciences & Humanities',
     ('ECONOM', 'BUSINESS', 'MANAGEMENT', 'POLITICAL', 'SOCIOLOG',
      'EDUCATION', 'LAW', 'HISTORY', 'GEOGRAPHY', 'ANTHROPOL',
      'LINGUISTIC', 'COMMUNICATION', 'INFORMATION SCIENCE', 'LIBRARY',
      'ETHICS', 'INTERNATIONAL RELATIONS', 'URBAN', 'TRANSPORTATION',
      'FAMILY STUDIES', 'SOCIAL', 'AREA STUDIES', 'HUMANITIES',
      'CRIMINOLOGY', 'PENOLOG')),
]

# journal title -> macro discipline (only used when the data says nothing)
TITLE_RULES = [
    ('Medicine & Clinical',
     ('J CLIN', 'CLINICAL', 'CLIN ', 'MEDICINE', 'MED ', 'LANCET', 'JAMA',
      'BRIT MED', 'NEW ENGL', 'SURG', 'PEDIATR', 'CARDIO', 'CANCER',
      'ONCOL', 'RADIOL', 'ANAESTH', 'ANESTH', 'INTENS', 'CRIT CARE',
      'INFECT', 'UROL', 'OBSTET', 'GASTRO', 'HAEMATOL', 'HEMATOL',
      'DERMATOL', 'OPHTHALM', 'ORTHOP', 'NEPHROL', 'ENDOCRIN',
      'RESPIR', 'NEUROL', 'STROKE', 'HEART', 'BLOOD', 'GUT',
      'AM J MED', 'CHEST', 'THORAC', 'TRANSPLANT', 'EMERG')),
    ('Microbiology & Immunology',
     ('MICROBIOL', 'IMMUNOL', 'VIROL', 'PARASITOL', 'MYCOL', 'BACTERIOL',
      'INFECT DIS', 'CLIN MICROBIOL', 'J INFECT', 'ANTIMICROB',
      'VACCINE', 'FRONT IMMUNOL', 'FRONT MICROBIOL')),
    ('Molecular Biology & Genetics',
     ('BIOCHEM', 'MOL BIOL', 'GENET', 'CELL BIOL', 'GENOM', 'NUCLEIC',
      'PROTEIN', 'BIOPHYS', 'PLOS GENET', 'STEM CELL', 'RNA')),
    ('Pharmacology & Toxicology',
     ('PHARMACOL', 'TOXICOL', 'PHARM', 'DRUG', 'THERAPEUT', 'ANTIBIOT')),
    ('Chemistry & Materials',
     ('CHEM', 'MATER', 'POLYM', 'CRYST', 'NANO', 'ANALYT', 'SPECTRO',
      'METALL', 'J MATER')),
    ('Physics & Astronomy',
     ('PHYS', 'OPTIC', 'ASTRON', 'ACOUST', 'NUCL')),
    ('Engineering & Technology',
     ('ENG', 'COMPUT', 'IEEE', 'ROBOT', 'SENSOR', 'ENERG', 'ELECTR',
      'TELECOMM', 'AUTOMAT', 'INFORM', 'SOFTWARE', 'ARTIF INTELL')),
    ('Environmental & Ecology',
     ('ENVIRON', 'ECOLOG', 'MARINE', 'WATER', 'SOIL', 'GEOLOG',
      'METEOROL', 'OCEAN', 'POLLUT', 'BIODIVERS', 'GEOPHYS')),
    ('Agriculture & Veterinary',
     ('AGRIC', 'VET', 'ANIM', 'FISH', 'AQUAC', 'FOOD', 'PLANT', 'CROP',
      'POULTRY', 'DAIRY', 'FOREST', 'ENTOMOL')),
    ('Health, Nursing & Public Health',
     ('NURS', 'PUBLIC HEALTH', 'HEALTH', 'EPIDEMIOL', 'REHABIL',
      'OCCUP', 'SPORT', 'PREV MED', 'GERIATR')),
    ('Neuroscience & Psychology',
     ('NEUROSCI', 'NEURO', 'BRAIN', 'PSYCHOL', 'PSYCHIAT', 'BEHAV')),
    ('Social Sciences & Humanities',
     ('ECON', 'SOCIO', 'POLIT', 'EDUC', 'MANAG', 'BUSINESS', 'LAW',
      'HIST', 'GEOGR', 'ANTHROPOL', 'LINGUIST', 'COMMUN', 'LIBR',
      'SOCIAL', 'TOURISM', 'URBAN')),
    ('Mathematics & Statistics',
     ('MATH', 'STATIST', 'PROBAB')),
]

DEFAULT_DISC = 'Unclassified'


def macro_discipline(category):
    up = (category or '').upper()
    if not up:
        return ''
    if 'MULTIDISCIPLINARY' in up:
        return 'Multidisciplinary'
    for name, keys in MACRO_RULES:
        for k in keys:
            if k in up:
                return name
    return DEFAULT_DISC


def discipline_from_title(title):
    up = (title or '').upper()
    if not up:
        return DEFAULT_DISC
    for name, keys in TITLE_RULES:
        for k in keys:
            if k in up:
                return name
    return DEFAULT_DISC


def _norm_journal(s):
    s = (s or '').strip()
    s = re.sub(r'\s+', ' ', s)
    return s.upper()


def load_overrides():
    if os.path.isfile(OVERRIDE_FILE):
        try:
            with open(OVERRIDE_FILE, encoding='utf-8') as f:
                raw = json.load(f)
            return {_norm_journal(k): v for k, v in raw.items()}
        except Exception:
            return {}
    return {}


# --------------------------------------------------------------------------
# main entry
# --------------------------------------------------------------------------

def build(docs, min_docs=1, min_citations=1, top_flows=600, top_journals=90,
          use_title_heuristic=True):
    """
    docs : parsed WoS records
    returns a dict ready to be rendered by the front end
    """
    overrides = load_overrides()

    # ---- citation flow:  citing journal -> cited journal ----------------
    flow = defaultdict(int)            # (src, tgt) -> citations
    src_docs = Counter()               # journal -> number of documents
    tgt_cit = Counter()                # cited journal -> citations received
    # category evidence
    src_cat = defaultdict(Counter)     # journal -> Counter(category)
    tgt_cat = defaultdict(Counter)     # cited journal -> Counter(category)

    for d in docs:
        s = _norm_journal(d.get('journal'))
        if not s:
            continue
        src_docs[s] += 1
        cats = [c for c in (d.get('categories') or []) if c]
        for c in cats:
            src_cat[s][c] += 1
        seen = set()
        for r in d.get('refs') or []:
            t = _norm_journal(r.get('journal'))
            if not t:
                continue
            flow[(s, t)] += 1
            if t not in seen:
                tgt_cit[t] += 1
                seen.add(t)
            for c in cats:
                tgt_cat[t][c] += 1

    if min_docs > 1:
        src_docs = Counter({k: v for k, v in src_docs.items() if v >= min_docs})
    if min_citations > 1:
        tgt_cit = Counter({k: v for k, v in tgt_cit.items() if v >= min_citations})
    src_keep = set(src_docs)
    tgt_keep = set(tgt_cit)
    flow = {k: v for k, v in flow.items()
            if k[0] in src_keep and k[1] in tgt_keep}
    if not flow:
        return {'error': '数据量不足：没有找到可用的施引/被引期刊对。'}

    # ---- discipline per journal ----------------------------------------
    def pick(counter, name):
        if name in overrides:
            return overrides[name]
        if counter:
            tally = Counter()
            for cat, n in counter.items():
                m = macro_discipline(cat)
                if m and m != DEFAULT_DISC:
                    tally[m] += n
            if tally:
                return tally.most_common(1)[0][0]
        if use_title_heuristic:
            m = discipline_from_title(name)
            if m != DEFAULT_DISC:
                return m
        return DEFAULT_DISC

    src_disc = {j: pick(src_cat.get(j), j) for j in src_keep}
    tgt_disc = {j: pick(tgt_cat.get(j), j) for j in tgt_keep}

    # ---- keep the strongest journals on each side ------------------------
    def top(counter, disc, n):
        items = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:n]
        return [(j, v, disc.get(j, DEFAULT_DISC)) for j, v in items]

    srcs = top(src_docs, src_disc, top_journals)
    tgts = top(tgt_cit, tgt_disc, top_journals)
    src_ids = {j: i for i, (j, _, _) in enumerate(srcs)}
    tgt_ids = {j: i for i, (j, _, _) in enumerate(tgts)}

    flows = []
    for (a, b), w in flow.items():
        if a in src_ids and b in tgt_ids:
            flows.append((src_ids[a], tgt_ids[b], w))
    flows.sort(key=lambda x: -x[2])
    flows = flows[:top_flows]

    # ---- discipline x discipline matrix + z scores ----------------------
    src_order = _order_disciplines(srcs, flows, 0)
    tgt_order = _order_disciplines(tgts, flows, 1)
    si = {d: i for i, d in enumerate(src_order)}
    ti = {d: i for i, d in enumerate(tgt_order)}
    M = [[0] * len(tgt_order) for _ in src_order]
    for a, b, w in flows:
        da = srcs[a][2]
        db = tgts[b][2]
        if da in si and db in ti:
            M[si[da]][ti[db]] += w
    matrix = _zscores(M)

    # ---- layout ---------------------------------------------------------
    layout_src = _layout_side(srcs, src_order, 0.30)
    layout_tgt = _layout_side(tgts, tgt_order, 0.70)

    return {
        'sources': [{'id': i, 'name': _title_case(j), 'key': j,
                     'count': c, 'discipline': d,
                     'x': layout_src[i][0], 'y': layout_src[i][1],
                     'r': layout_src[i][2]}
                    for i, (j, c, d) in enumerate(srcs)],
        'targets': [{'id': i, 'name': _title_case(j), 'key': j,
                     'count': c, 'discipline': d,
                     'x': layout_tgt[i][0], 'y': layout_tgt[i][1],
                     'r': layout_tgt[i][2]}
                    for i, (j, c, d) in enumerate(tgts)],
        'flows': [{'s': a, 't': b, 'w': w} for a, b, w in flows],
        'src_disciplines': src_order,
        'tgt_disciplines': tgt_order,
        'matrix': matrix,
        'summary': {
            'n_source_journals': len(srcs),
            'n_target_journals': len(tgts),
            'n_flows': len(flows),
            'n_citations': sum(w for _, _, w in flows),
            'n_source_all': len(src_docs),
            'n_target_all': len(tgt_cit),
        },
        'discipline_of': {('S:' + k): v for k, v in src_disc.items()} |
                         {('T:' + k): v for k, v in tgt_disc.items()},
    }


def _title_case(s):
    s = s.strip()
    if not s:
        return s
    # WoS writes cited sources as abbreviations, e.g. "NEW ENGL J MED";
    # those read better in plain title case.  Full journal names are cased
    # the usual way (small words stay lower case).
    upper = sum(1 for ch in s if ch.isupper())
    letters = sum(1 for ch in s if ch.isalpha()) or 1
    if upper / float(letters) > 0.9:
        return ' '.join(w.capitalize() for w in s.split(' '))
    small = {'of', 'and', 'the', 'for', 'in', 'on', 'a', 'an', 'to', 'de',
             'der', 'van', 'het', 'j', 'med', 'rev', 'int'}
    out = []
    for i, w in enumerate(s.split(' ')):
        lw = w.lower()
        if i == 0 or lw not in small:
            out.append(w.capitalize())
        else:
            out.append(lw)
    return ' '.join(out)


def _order_disciplines(side, flows, which):
    """Disciplines ordered by total volume so the sectors read top-down."""
    tally = Counter()
    for item in side:
        tally[item[2]] += item[1]
    return [d for d, _ in tally.most_common()]


def _layout_side(side, order, x_center):
    """
    Place the journals of one side inside their discipline's vertical band.
    Returns {index: (x, y, radius)} in a normalised [0,1] box.
    """
    n = len(side)
    if n == 0:
        return {}
    counts = [c for _, c, _ in side]
    cmax = float(max(counts)) or 1.0
    cmin = float(min(counts))
    span = max(1e-9, cmax - cmin)

    by_disc = defaultdict(list)
    for i, (_, c, d) in enumerate(side):
        by_disc[d].append(i)

    # vertical space proportional to the number of journals per discipline
    total_w = sum(len(v) for v in by_disc.values())
    pos = {}
    y = 0.04
    band_h = 0.92
    for d in order:
        members = by_disc.get(d)
        if not members:
            continue
        share = len(members) / float(total_w)
        h = band_h * share
        members = sorted(members, key=lambda i: -side[i][1])
        # pack into rows: how many columns fit in a band of this height?
        k = len(members)
        ncols = max(1, int(math.ceil(math.sqrt(max(1.0, k * 1.6)))))
        nrows = int(math.ceil(k / float(ncols)))
        for r_ in range(nrows):
            row = members[r_ * ncols:(r_ + 1) * ncols]
            yy = y + h * (r_ + 0.5) / nrows
            m = len(row)
            for c_, i in enumerate(row):
                xx = x_center + (c_ - (m - 1) / 2.0) * 0.052
                rel = (side[i][1] - cmin) / span
                rad = 0.005 + 0.017 * math.sqrt(rel + 0.02)
                pos[i] = (round(xx, 4), round(yy, 4), round(rad, 4))
        y += h
    return pos


def _zscores(M):
    """Hypergeometric z score per cell of a discipline x discipline matrix."""
    rows = len(M)
    cols = len(M[0]) if rows else 0
    R = [float(sum(r)) for r in M]
    C = [float(sum(M[i][j] for i in range(rows))) for j in range(cols)]
    T = float(sum(R)) or 1.0
    out = []
    for i in range(rows):
        row = []
        for j in range(cols):
            exp = R[i] * C[j] / T
            if T > 1 and R[i] > 0 and C[j] > 0:
                var = R[i] * C[j] * (T - R[i]) * (T - C[j]) / (T * T * (T - 1.0))
                z = (M[i][j] - exp) / math.sqrt(var) if var > 0 else 0.0
            else:
                z = 0.0
            row.append({'obs': M[i][j], 'exp': round(exp, 2),
                        'z': round(z, 2)})
        out.append(row)
    return out


if __name__ == '__main__':
    docs = [
        {'journal': 'Journal of Hepatology',
         'categories': ['Gastroenterology & Hepatology'],
         'refs': [{'journal': 'NEW ENGL J MED'}, {'journal': 'HEPATOLOGY'},
                  {'journal': 'LANCET'}]},
        {'journal': 'Journal of Hepatology',
         'categories': ['Gastroenterology & Hepatology'],
         'refs': [{'journal': 'LANCET'}, {'journal': 'J CLIN ONCOL'}]},
        {'journal': 'Frontiers in Immunology',
         'categories': ['Immunology'],
         'refs': [{'journal': 'NATURE'}, {'journal': 'CELL'}]},
        {'journal': 'Water Research',
         'categories': ['Environmental Sciences', 'Engineering Environmental'],
         'refs': [{'journal': 'APPL ENVIRON MICROB'}, {'journal': 'SCIENCE'}]},
    ]
    res = build(docs)
    print('summary:', res['summary'])
    for s in res['sources']:
        print('  SRC %-24s %-28s n=%d  (%.2f, %.2f)'
              % (s['name'][:24], s['discipline'], s['count'], s['x'], s['y']))
    for t in res['targets']:
        print('  TGT %-24s %-28s n=%d' % (t['name'][:24], t['discipline'], t['count']))
    print('flows:', res['flows'])
    print('src disciplines:', res['src_disciplines'])
    print('tgt disciplines:', res['tgt_disciplines'])
    print('z of first row:', [(c['obs'], c['z']) for c in res['matrix'][0]])
