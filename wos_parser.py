# -*- coding: utf-8 -*-
"""
wos_parser.py -- Web of Science plain-text (full record) parser.

Zero third-party dependency. Handles the classic "download_*.txt" format
produced by Web of Science Core Collection (also works for most exported
files from other platforms that mimic this layout):

    FN Thomson Reuters Web of Science
    VR 1.0
    PT J
    AU Smith, J
       Doe, A
    TI The title of the paper
    SO LANCET
    DE keyword one; keyword two
    ID keywords plus
    AB The abstract ...
    C1 [Smith, J] Harvard Univ, Dept Med; [Doe, A] Yale Univ
    CR Smith J, 2010, LANCET, V375, P123, DOI 10.1016/xxx
       Doe A, 2012, NEW ENGL J MED
    NR 45
    TC 12
    PY 2020
    UT WOS:000123456700001
    ER

Layout rule: a field tag occupies columns 1-2, column 3 is a space, the
value starts at column 4.  Continuation lines begin with three spaces.

Only `CR` and `NR` are read as cited references; `TC` is the WoS cited
reference count (used as an external citation indicator only).
"""

import os
import re
import glob
import json

# --------------------------------------------------------------------------
# low level record splitting
# --------------------------------------------------------------------------

_TAG_RE = re.compile(r'^[A-Z0-9]{2} $')
# fields that keep one value per physical line
_MULTI = {'AU', 'AF', 'BA', 'BF', 'CA', 'GP', 'BE', 'C1', 'RP', 'EM', 'RI',
          'OI', 'CR', 'DE', 'ID', 'WC', 'SC', 'WE', 'UT', 'PM', 'HC', 'DA'}
# fields whose continuation lines should be joined with a space
_TEXT = {'TI', 'AB', 'SO', 'JI', 'J9', 'SE', 'BS', 'LA', 'DT', 'CT', 'CY',
         'HO', 'CL', 'SP', 'DE', 'ID', 'PU', 'PA', 'SN', 'EI', 'BN', 'DI',
         'D2', 'EA', 'PG', 'GA', 'OA', 'HP'}


def parse_wos_text(text):
    """Parse raw WoS text -> list of dicts keyed by two-letter tag."""
    if text.startswith('\ufeff'):
        text = text[1:]
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    records, cur, tag = [], None, None

    for raw in text.split('\n'):
        line = raw.rstrip()
        if not line.strip():
            continue
        head = line[:2]
        if head == 'EF':
            break
        if head == 'ER':
            if cur is not None:
                records.append(cur)
            cur, tag = None, None
            continue
        if len(line) > 2 and _TAG_RE.match(line[:3]):
            if cur is None:
                cur = {}
            tag = head
            val = line[3:].strip()
            if tag in _MULTI:
                cur.setdefault(tag, [])
                if val:
                    cur[tag].append(val)
            else:
                cur[tag] = val
        elif line.startswith('   ') and cur is not None and tag is not None:
            val = line[3:].strip()
            if tag in _MULTI:
                cur.setdefault(tag, []).append(val)
            else:
                cur[tag] = (cur.get(tag, '') + ' ' + val).strip()

    if cur is not None:
        records.append(cur)
    return records


# --------------------------------------------------------------------------
# reference / institution / keyword normalisation
# --------------------------------------------------------------------------

_REF_RE = re.compile(
    r'^\s*(?P<au>[^,]+?)\s*,\s*(?P<yr>(?:19|20|21)\d{2}|IN PRESS|N\.D\.)\s*'
    r'(?:,\s*(?P<jo>[^,]+))?'
    r'(?:,\s*[Vv](?P<vol>[^,]+))?'
    r'(?:,\s*[Pp](?P<pg>[^,]+))?'
    r'(?:,\s*DOI\s*(?P<doi>[^,]+))?\s*$'
)
_YEAR_RE = re.compile(r'(19|20|21)\d{2}')
_PUNCT_RE = re.compile(r'[^a-z0-9 ]+')
_WS_RE = re.compile(r'\s+')


def _norm(txt):
    return _WS_RE.sub(' ', _PUNCT_RE.sub(' ', (txt or '').lower())).strip()


def parse_reference(raw):
    """Parse one CR line -> {author, year, journal, volume, page, doi, key}."""
    m = _REF_RE.match(raw or '')
    if not m:
        # fall back: take whatever is before the first comma as author
        parts = (raw or '').split(',')
        au = parts[0].strip() if parts else ''
        yr = ''
        for p in parts[1:]:
            if _YEAR_RE.search(p):
                yr = _YEAR_RE.search(p).group(0)
                break
        return {'author': au, 'year': yr, 'journal': '',
                'volume': '', 'page': '', 'doi': '',
                'key': _norm(au) + '|' + yr, 'raw': (raw or '').strip()}

    au = m.group('au').strip()
    yr_txt = m.group('yr').strip()
    yr = yr_txt if yr_txt.isdigit() else ''
    jo = (m.group('jo') or '').strip()
    # first author surname: WoS writes "SMITH J" or "SMITH, J"
    surname = au.split(',')[0].strip().split(' ')[0].strip()
    key = _norm(surname) + '|' + yr + '|' + _norm(jo)[:28]
    return {'author': au, 'surname': surname, 'year': yr, 'journal': jo,
            'volume': (m.group('vol') or '').strip(),
            'page': (m.group('pg') or '').strip(),
            'doi': (m.group('doi') or '').strip(),
            'key': key, 'raw': (raw or '').strip()}


_STOP_ORG_HINT = ('UNIV', 'HOSP', 'HOSPITAL', 'INST', 'COLL', 'COLLEGE',
                  'SCH', 'SCHOOL', 'CTR', 'CENTER', 'CENTRE', 'ACAD',
                  'LAB', 'DEPT', 'CLIN', 'MED', 'FOUND', 'MINIST',
                  'COUNCIL', 'NATL', 'NACL', 'CORP', 'INC', 'LTD', 'GMBH')

# canonical country names -> alias patterns (longer aliases first)
_COUNTRY_ALIASES = {
    'USA': ['usa', 'united states', 'united states of america', 'u s a'],
    'China': ['peoples r china', "people's republic of china", 'pr china', 'china'],
    'England': ['england', 'united kingdom', 'uk'],
    'Scotland': ['scotland'], 'Wales': ['wales'], 'Ireland': ['ireland'],
    'Japan': ['japan'], 'South Korea': ['south korea', 'korea'],
    'Germany': ['germany', 'deutschland'], 'France': ['france'],
    'Italy': ['italy', 'italia'], 'Spain': ['spain', 'espana'],
    'Netherlands': ['netherlands', 'holland'], 'Belgium': ['belgium'],
    'Denmark': ['denmark'], 'Sweden': ['sweden'], 'Norway': ['norway'],
    'Finland': ['finland'], 'Switzerland': ['switzerland'],
    'Austria': ['austria'], 'Canada': ['canada'], 'Australia': ['australia'],
    'New Zealand': ['new zealand'], 'Brazil': ['brazil'], 'India': ['india'],
    'Russia': ['russia'], 'Turkey': ['turkey'], 'Poland': ['poland'],
    'Portugal': ['portugal'], 'Greece': ['greece'], 'Israel': ['israel'],
    'Mexico': ['mexico'], 'Argentina': ['argentina'], 'Chile': ['chile'],
    'Egypt': ['egypt'], 'Iran': ['iran'], 'Saudi Arabia': ['saudi arabia'],
    'Singapore': ['singapore'], 'Thailand': ['thailand'],
    'Taiwan, China': ['taiwan'], 'Hong Kong, China': ['hong kong'],
    'South Africa': ['south africa'], 'Nigeria': ['nigeria'],
}
_COUNTRY_PATS = []
for _canon, _al in _COUNTRY_ALIASES.items():
    for _a in _al:
        _COUNTRY_PATS.append((len(_a), re.compile(r'\b' + re.escape(_a) + r'\b'),
                              _canon))
_COUNTRY_PATS.sort(key=lambda x: -x[0])


def _match_country(parts):
    """Guess the country from the tail of an address segment."""
    if not parts:
        return ''
    tail = ' '.join(parts[-2:]).lower() if len(parts) >= 2 else parts[-1].lower()
    for _ln, pat, canon in _COUNTRY_PATS:
        if pat.search(tail):
            return canon
    last = parts[-1].strip()
    last = re.sub(r'(^|[\s,])[A-Z]{2}([\s,]|$)', ' ', last)   # drop state codes
    last = re.sub(r'\s+', ' ', last).strip(' .,')
    # the tail is still an organisation (address without an explicit country)
    if any(h in last.upper() for h in _STOP_ORG_HINT):
        return ''
    if 2 < len(last) < 40 and re.match(r'^[A-Za-z .]+$', last):
        return last.title()
    return ''


def split_organisations(c1_list):
    """Extract organisation + country strings from C1 (author address) lines."""
    orgs, countries = [], []
    for line in c1_list or []:
        # drop the bracketed author part "[Smith, J] "
        line = re.sub(r'\[[^\]]*\]\s*', '', line)
        for seg in line.split(';'):
            seg = seg.strip()
            if not seg:
                continue
            parts = [p.strip() for p in seg.split(',') if p.strip()]
            if not parts:
                continue
            # organisation = the first part that looks like an organisation
            org = ''
            for p in parts[:-1]:
                up = p.upper()
                if any(h in up for h in _STOP_ORG_HINT) or len(p) > 4:
                    org = p
                    break
            if not org and parts:
                org = parts[0]
            org = re.sub(r'\s+', ' ', org).strip(' .')
            if len(org) > 2:
                orgs.append(org)
            c = _match_country(parts)
            if c:
                countries.append(c)
    return orgs, countries


def _split_categories(values):
    out = []
    for v in values or []:
        for part in str(v).split(';'):
            p = part.strip()
            if p:
                out.append(p)
    return out


def split_keywords(values):
    out = []
    for v in values or []:
        for k in re.split(r';', v):
            k = k.strip()
            if k:
                out.append(k)
    return out


def _to_int(v):
    try:
        return int(re.sub(r'[^0-9].*$', '', str(v)).strip() or 0)
    except Exception:
        return 0


# --------------------------------------------------------------------------
# record -> normalised document dict
# --------------------------------------------------------------------------

def record_to_doc(rec):
    def g(tag):
        v = rec.get(tag)
        if v is None:
            return ''
        if isinstance(v, list):
            return ' '.join(v)
        return v

    year = _to_int(g('PY'))
    if not year:
        m = _YEAR_RE.search(g('PY') or g('DA') or '')
        year = int(m.group(0)) if m else None

    refs = [parse_reference(x) for x in (rec.get('CR') or []) if x.strip()]
    refs = [r for r in refs if r['author'] or r['year']]

    orgs, countries = split_organisations(rec.get('C1') or [])
    if not orgs:
        orgs, countries = split_organisations([g('C1')] if g('C1') else [])

    authors = []
    for a in (rec.get('AU') or rec.get('AF') or []):
        a = a.strip()
        if a:
            authors.append(a)

    return {
        'title': (g('TI') or g('BT') or '').strip(),
        'authors': authors,
        'year': year,
        'journal': (g('SO') or g('J9') or g('JI') or '').strip(),
        'keywords': split_keywords(rec.get('DE')) + split_keywords(rec.get('ID')),
        'de': split_keywords(rec.get('DE')),
        'abstract': g('AB').strip(),
        'orgs': orgs,
        'countries': countries,
        'refs': refs,
        'n_refs': _to_int(g('NR')) or len(refs),
        'cited_by': _to_int(g('TC')),
        'doi': (g('DI') or g('D2')).strip(),
        'wosid': (g('UT')).strip(),
        'doc_type': g('DT').strip(),
        # WC = Web of Science Categories (modern), SC = Subject Categories.
        # One physical line may hold several categories separated by ';'.
        'categories': _split_categories(rec.get('WC') or rec.get('SC') or []),
        'address': g('C1').strip(),
        'language': g('LA').strip(),
    }


def parse_files(paths, verbose=False):
    """Parse a list of WoS files -> (docs, meta)."""
    docs, meta = [], {'files': [], 'n_raw_records': 0, 'skipped': 0}
    for p in paths:
        for enc in ('utf-8-sig', 'utf-8', 'gb18030', 'latin-1'):
            try:
                with open(p, 'r', encoding=enc) as f:
                    text = f.read()
                break
            except UnicodeDecodeError:
                continue
        else:
            continue
        recs = parse_wos_text(text)
        good = 0
        for r in recs:
            d = record_to_doc(r)
            if not d['title'] and not d['refs'] and not d['year']:
                meta['skipped'] += 1
                continue
            d['source_file'] = os.path.basename(p)
            docs.append(d)
            good += 1
        meta['files'].append({'file': os.path.basename(p), 'records': good})
        meta['n_raw_records'] += len(recs)
        if verbose:
            print('[wos] %-40s %5d records' % (os.path.basename(p), good))
    return docs, meta


def find_wos_files(folder):
    out = []
    for p in sorted(glob.glob(os.path.join(folder, '*'))):
        if os.path.isfile(p) and os.path.splitext(p)[1].lower() in ('.txt', '.ciw', ''):
            out.append(p)
    return out


# --------------------------------------------------------------------------
# dataset summary
# --------------------------------------------------------------------------

def summarise(docs):
    years = [d['year'] for d in docs if d['year']]
    n_refs = [len(d['refs']) for d in docs]
    kw = {}
    for d in docs:
        for k in d['keywords']:
            kw[k.lower()] = kw.get(k.lower(), 0) + 1
    from_stat = {}
    for d in docs:
        j = (d['journal'] or 'UNKNOWN').upper()
        from_stat[j] = from_stat.get(j, 0) + 1
    return {
        'n_docs': len(docs),
        'year_min': min(years) if years else None,
        'year_max': max(years) if years else None,
        'n_refs_total': sum(n_refs),
        'n_refs_mean': (sum(n_refs) / len(n_refs)) if n_refs else 0,
        'n_keywords_unique': len(kw),
        'n_journals': len(from_stat),
        'top_journals': sorted(from_stat.items(), key=lambda x: -x[1])[:15],
        'docs_with_refs': sum(1 for d in docs if d['refs']),
        'docs_with_abstract': sum(1 for d in docs if d['abstract']),
        'docs_with_keywords': sum(1 for d in docs if d['keywords']),
    }


if __name__ == '__main__':
    import sys
    files = sys.argv[1:] or find_wos_files('data')
    docs, meta = parse_files(files, verbose=True)
    print(json.dumps({'meta': meta, 'summary': summarise(docs)},
                     ensure_ascii=False, indent=2))
