# -*- coding: utf-8 -*-
"""
geoview.py -- country / region collaboration network on a world map.

Turns the C1 (author address) country field of every record into a
geographic network: nodes are countries placed at their centroid, edges are
co-authorship (or co-mention) counts between two countries.

The country spellings that Web of Science writes into C1 differ from the
display names ("Peoples R China", "USA", "England", "U Arab Emirates", ...),
so the module carries an alias table.  Anything that cannot be resolved is
reported in `unknown` instead of being silently dropped.

Coordinate source: public-domain country centroids (Natural Earth style).
The base map itself ships as assets/world_110m.json (Natural Earth 110m,
simplified with tools_topo2geo.py).
"""

import os
import re
import math
from collections import defaultdict, Counter

import network as net

HERE = os.path.dirname(os.path.abspath(__file__))
WORLD_FILE = os.path.join(HERE, 'assets', 'world_110m.json')

# canonical name | lat | lon | aliases (semicolon separated)
_TABLE = """
Afghanistan|33.8|66.0|AFGHANISTAN
Albania|41.1|20.0|ALBANIA
Algeria|28.0|2.6|ALGERIA
Argentina|-34.6|-58.4|ARGENTINA
Armenia|40.1|44.5|ARMENIA
Australia|-25.3|133.8|AUSTRALIA
Austria|47.5|14.6|AUSTRIA
Azerbaijan|40.1|47.6|AZERBAIJAN
Bahrain|26.0|50.6|BAHRAIN
Bangladesh|23.7|90.4|BANGLADESH
Belarus|53.7|27.9|BELARUS;BYELORUSSIA;BYELARUS
Belgium|50.6|4.7|BELGIUM
Benin|6.5|2.6|BENIN
Bolivia|-16.7|-64.7|BOLIVIA
Bosnia and Herzegovina|43.9|17.7|BOSNIA & HERZEGOVINA;BOSNIA AND HERZEGOVINA
Botswana|-22.3|23.8|BOTSWANA
Brazil|-10.8|-53.0|BRAZIL
Brunei|4.5|114.7|BRUNEI
Bulgaria|42.7|25.5|BULGARIA
Burkina Faso|12.3|-1.6|BURKINA FASO
Burundi|-3.4|29.9|BURUNDI
Cambodia|12.6|104.9|CAMBODIA
Cameroon|3.8|11.5|CAMEROON
Canada|56.1|-106.3|CANADA
Chad|15.4|18.7|CHAD
Chile|-35.7|-71.5|CHILE
China|35.9|104.2|CHINA;PEOPLES R CHINA;P R CHINA;CHINA MAINLAND;CHN
Colombia|4.6|-74.3|COLOMBIA
Congo|-0.8|15.5|CONGO;CONGO DEMOCRATIC REP;DEMOCRATIC REPUBLIC OF THE CONGO
Costa Rica|9.7|-83.8|COSTA RICA
Croatia|45.1|15.2|CROATIA
Cuba|21.5|-79.0|CUBA
Cyprus|35.1|33.4|CYPRUS
Czech Republic|49.8|15.5|CZECH REPUBLIC;CZECHIA
Denmark|56.3|9.5|DENMARK
Dominican Republic|18.7|-70.2|DOMINICAN REPUBLIC
Ecuador|-1.8|-78.2|ECUADOR
Egypt|26.8|30.8|EGYPT
El Salvador|13.7|-88.9|EL SALVADOR
Eritrea|15.2|39.8|ERITREA
Estonia|58.6|25.0|ESTONIA
Eswatini|-26.5|31.5|ESWATINI;SWAZILAND
Ethiopia|9.1|40.5|ETHIOPIA
Fiji|-17.7|178.1|FIJI
Finland|61.9|25.7|FINLAND
France|46.6|2.2|FRANCE
Gabon|-0.8|11.6|GABON
Georgia|42.3|43.4|GEORGIA
Germany|51.1|10.4|GERMANY;WEST GERMANY;GERMANY FED REP
Ghana|7.9|-1.2|GHANA
Greece|39.1|21.8|GREECE
Guatemala|15.8|-90.2|GUATEMALA
Guinea|9.9|-9.7|GUINEA
Haiti|19.0|-72.6|HAITI
Honduras|14.8|-86.6|HONDURAS
Hong Kong, China|22.3|114.2|HONG KONG
Hungary|47.2|19.5|HUNGARY
Iceland|65.0|-18.6|ICELAND
India|22.9|79.6|INDIA
Indonesia|-2.5|118.0|INDONESIA
Iran|32.4|53.7|IRAN
Iraq|33.2|43.7|IRAQ
Ireland|53.4|-8.2|IRELAND;REPUBLIC OF IRELAND;EIRE
Israel|31.0|34.9|ISRAEL
Italy|41.9|12.6|ITALY
Ivory Coast|7.6|-5.5|IVORY COAST;COTE DIVOIRE;COTE D IVOIRE
Jamaica|18.1|-77.3|JAMAICA
Japan|36.2|138.3|JAPAN
Jordan|30.6|36.2|JORDAN
Kazakhstan|48.0|66.9|KAZAKHSTAN
Kenya|-0.0|37.9|KENYA
Kuwait|29.3|47.5|KUWAIT
Kyrgyzstan|41.2|74.8|KYRGYZSTAN
Laos|18.2|103.9|LAOS
Latvia|56.9|24.9|LATVIA
Lebanon|33.9|35.9|LEBANON
Libya|27.0|17.2|LIBYA
Lithuania|55.2|23.9|LITHUANIA
Luxembourg|49.8|6.1|LUXEMBOURG
Macao, China|22.2|113.5|MACAO;MACAU
Madagascar|-18.8|46.9|MADAGASCAR
Malawi|-13.3|34.3|MALAWI
Malaysia|4.2|102.0|MALAYSIA
Mali|17.6|-4.0|MALI
Malta|35.9|14.4|MALTA
Mauritius|-20.3|57.6|MAURITIUS
Mexico|23.6|-102.6|MEXICO
Moldova|47.4|28.4|MOLDOVA
Mongolia|46.9|103.8|MONGOLIA
Montenegro|42.7|19.4|MONTENEGRO
Morocco|31.8|-7.1|MOROCCO
Mozambique|-17.3|35.5|MOZAMBIQUE
Myanmar|21.9|96.0|MYANMAR;BURMA
Namibia|-22.6|17.1|NAMIBIA
Nepal|28.4|84.1|NEPAL
Netherlands|52.2|5.5|NETHERLANDS;THE NETHERLANDS
New Zealand|-41.0|174.0|NEW ZEALAND
Nicaragua|12.9|-85.0|NICARAGUA
Niger|17.6|8.1|NIGER
Nigeria|9.1|8.7|NIGERIA
North Korea|40.3|127.5|NORTH KOREA;DEMOCRATIC PEOPLES REPUBLIC OF KOREA
North Macedonia|41.6|21.7|NORTH MACEDONIA;MACEDONIA
Norway|61.0|9.0|NORWAY
Oman|20.6|56.1|OMAN
Pakistan|30.0|69.3|PAKISTAN
Palestine|31.9|35.2|PALESTINE
Panama|8.5|-80.8|PANAMA
Papua New Guinea|-6.5|147.0|PAPUA NEW GUINEA
Paraguay|-23.4|-58.4|PARAGUAY
Peru|-9.2|-75.0|PERU
Philippines|12.9|121.8|PHILIPPINES
Poland|52.0|19.3|POLAND
Portugal|39.4|-8.2|PORTUGAL
Qatar|25.3|51.2|QATAR
Romania|45.9|25.0|ROMANIA
Russia|61.5|90.0|RUSSIA;RUSSIAN FEDERATION;USSR
Rwanda|-2.0|29.9|RWANDA
Saudi Arabia|24.1|45.1|SAUDI ARABIA
Senegal|14.5|-14.5|SENEGAL
Serbia|44.0|21.0|SERBIA
Sierra Leone|8.5|-11.8|SIERRA LEONE
Singapore|1.4|103.8|SINGAPORE
Slovakia|48.7|19.7|SLOVAKIA
Slovenia|46.1|15.0|SLOVENIA
Somalia|5.2|46.2|SOMALIA
South Africa|-29.0|25.0|SOUTH AFRICA
South Korea|36.5|127.9|SOUTH KOREA;KOREA;REPUBLIC OF KOREA;KOREA REP
Spain|40.2|-3.6|SPAIN
Sri Lanka|7.9|80.8|SRI LANKA
Sudan|15.5|30.2|SUDAN
Sweden|62.0|15.0|SWEDEN
Switzerland|46.8|8.2|SWITZERLAND
Syria|35.0|38.5|SYRIA
Taiwan, China|23.7|121.0|TAIWAN
Tajikistan|38.5|71.0|TAJIKISTAN
Tanzania|-6.4|34.9|TANZANIA
Thailand|15.1|101.0|THAILAND
Togo|8.6|0.9|TOGO
Trinidad and Tobago|10.5|-61.3|TRINIDAD TOBAGO;TRINIDAD & TOBAGO;TRINIDAD AND TOBAGO
Tunisia|34.1|9.6|TUNISIA
Turkey|39.0|35.2|TURKEY;TURKIYE
Turkmenistan|39.1|59.4|TURKMENISTAN
Uganda|1.4|32.5|UGANDA
Ukraine|48.4|31.2|UKRAINE
United Arab Emirates|23.4|53.8|U ARAB EMIRATES;UNITED ARAB EMIRATES;UAE
United Kingdom|54.0|-2.0|UK;UNITED KINGDOM;ENGLAND;SCOTLAND;WALES;N IRELAND;NORTH IRELAND;GREAT BRITAIN
United States|39.8|-98.6|USA;UNITED STATES;US;U S A;UNITED STATES OF AMERICA
Uruguay|-32.9|-56.0|URUGUAY
Uzbekistan|41.4|64.6|UZBEKISTAN
Venezuela|6.4|-66.6|VENEZUELA
Vietnam|16.0|106.0|VIETNAM;VIET NAM
Yemen|15.5|47.9|YEMEN
Zambia|-13.1|27.8|ZAMBIA
Zimbabwe|-19.0|29.9|ZIMBABWE
Antigua and Barbuda|17.1|-61.8|ANTIGUA;ANTIGUA AND BARBUDA
Andorra|42.5|1.6|ANDORRA
Aruba|12.5|-70.0|ARUBA
Bahamas|25.0|-78.0|BAHAMAS
Barbados|13.1|-59.5|BARBADOS
Bermuda|32.3|-64.7|BERMUDA
Bhutan|27.5|90.4|BHUTAN
Cape Verde|16.5|-23.9|CAPE VERDE;CAPE VERDE ISLANDS
Cayman Islands|19.5|-80.9|CAYMAN ISLANDS
Central African Republic|6.6|20.5|CENT AFR REPUBL;CENTRAL AFRICAN REPUBLIC
Curacao|12.2|-69.0|CURACAO
Djibouti|11.8|42.6|DJIBOUTI
Dominica|15.4|-61.4|DOMINICA
Equatorial Guinea|1.7|10.3|EQUATORIAL GUINEA
Faroe Islands|62.0|-6.9|FAROE ISLANDS
French Guiana|4.0|-53.0|FRENCH GUIANA
Gambia|13.4|-15.4|GAMBIA
Gibraltar|36.1|-5.3|GIBRALTAR
Greenland|72.0|-42.0|GREENLAND
Grenada|12.1|-61.7|GRENADA
Guadeloupe|16.2|-61.5|GUADELOUPE
Guam|13.4|144.8|GUAM
Guinea-Bissau|12.0|-14.9|GUINEA-BISSAU
Guyana|5.0|-58.9|GUYANA
Isle of Man|54.2|-4.5|ISLE OF MAN
Kiribati|1.9|-157.4|KIRIBATI
Kosovo|42.6|20.9|KOSOVO
Lesotho|-29.6|28.2|LESOTHO
Liberia|6.4|-9.4|LIBERIA
Liechtenstein|47.1|9.5|LIECHTENSTEIN
Marshall Islands|7.1|171.2|MARSHALL ISLANDS
Martinique|14.6|-61.0|MARTINIQUE
Micronesia|6.9|158.2|MICRONESIA
Monaco|43.7|7.4|MONACO
New Caledonia|-21.3|165.7|NEW CALEDONIA
Palau|7.3|134.5|PALAU
Puerto Rico|18.2|-66.4|PUERTO RICO;PUERTO-RICO
Reunion|-21.1|55.5|REUNION
Saint Kitts and Nevis|17.3|-62.7|ST KITTS;SAINT KITTS;ST KITTS & NEVIS
Saint Lucia|13.9|-61.0|SAINT LUCIA;ST LUCIA
Saint Vincent|13.2|-61.2|SAINT VINCENT;ST VINCENT
Samoa|-13.6|-172.1|SAMOA
San Marino|43.9|12.5|SAN MARINO
Sao Tome and Principe|0.4|6.7|SAO TOME;SAO TOME AND PRINCIPE
Seychelles|-4.7|55.5|SEYCHELLES
Solomon Islands|-9.6|160.2|SOLOMON ISLANDS
South Sudan|7.3|30.3|SOUTH SUDAN
Timor-Leste|-8.8|125.9|TIMOR-LESTE;EAST TIMOR
Tonga|-20.4|-174.8|TONGA
Turks and Caicos|21.7|-71.6|TURKS & CAICOS
Vanuatu|-16.2|167.7|VANUATU
Virgin Islands|18.3|-64.8|VIRGIN ISLANDS;US VIRGIN ISLANDS
Western Sahara|24.2|-14.5|WESTERN SAHARA
"""

_COORDS = {}       # canonical -> (lat, lon)
_ALIAS = {}        # normalised alias -> canonical


def _norm(s):
    s = (s or '').upper()
    s = s.replace('&', ' AND ')
    s = re.sub(r'[^A-Z ]+', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


for _line in _TABLE.strip().splitlines():
    _parts = [p.strip() for p in _line.split('|')]
    _name, _lat, _lon = _parts[0], float(_parts[1]), float(_parts[2])
    _COORDS[_name] = (_lat, _lon)
    _ALIAS[_norm(_name)] = _name
    if len(_parts) > 3 and _parts[3]:
        for _a in _parts[3].split(';'):
            if _a.strip():
                _ALIAS[_norm(_a)] = _name


def resolve(name):
    """WoS country string -> canonical name, or None."""
    if not name:
        return None
    key = _norm(name)
    if key in _ALIAS:
        return _ALIAS[key]
    # try dropping trailing qualifiers such as "GERMANY (WEST)"
    short = re.sub(r'\s*\([^)]*\)\s*', ' ', key).strip()
    if short in _ALIAS:
        return _ALIAS[short]
    for a, canon in _ALIAS.items():
        if len(a) > 4 and (a in key or key in a):
            return canon
    return None


def coords(canonical):
    return _COORDS.get(canonical)


# --------------------------------------------------------------------------
# network
# --------------------------------------------------------------------------

def build(docs, min_count=1, top_edges=400, resolution=1.0, log=None):
    """
    docs : parsed records (country field already extracted by wos_parser)
    returns a dict with geo-referenced nodes and collaboration edges
    """
    def L(m):
        if log is not None:
            log.append('[geo] %s' % m)

    per_doc = []
    unknown = Counter()
    for d in docs:
        cs = []
        for raw in d.get('countries') or []:
            c = resolve(raw)
            if c:
                cs.append(c)
            else:
                unknown[raw] += 1
        per_doc.append(sorted(set(cs)))
    L('%d documents scanned, %d unresolved country strings'
      % (len(docs), sum(unknown.values())))

    counts = Counter()
    for cs in per_doc:
        counts.update(cs)
    if min_count > 1:
        counts = Counter({k: v for k, v in counts.items() if v >= min_count})
    keep = set(counts)
    if not keep:
        return {'error': '没有可解析的国家字段（C1 地址未能提取出国家）。'}

    edges = defaultdict(int)
    years = defaultdict(Counter)
    for d, cs in zip(docs, per_doc):
        cs = [c for c in cs if c in keep]
        if d.get('year'):
            for c in cs:
                years[c][d['year']] += 1
        for i in range(len(cs)):
            for j in range(i + 1, len(cs)):
                a, b = cs[i], cs[j]
                edges[(a, b) if a < b else (b, a)] += 1
    edges = dict(edges)
    L('%d countries, %d collaboration edges' % (len(keep), len(edges)))

    nodes = sorted(keep)
    communities = net.louvain_full(nodes, edges, resolution=resolution) \
        if edges else [[n] for n in nodes]
    comm_of = {}
    for ci, c in enumerate(communities):
        for n in c:
            comm_of[n] = ci
    bc = net.betweenness_centrality(nodes, edges) if edges else \
        {n: 0.0 for n in nodes}
    deg = net.degree_centrality(nodes, edges)

    node_out = []
    for i, n in enumerate(nodes):
        la, lo = coords(n) or (0.0, 0.0)
        yc = dict(years.get(n, {}))
        tot = sum(yc.values()) or 1
        node_out.append({
            'id': i, 'name': n, 'lat': la, 'lon': lo,
            'count': counts[n],
            'first_year': min(yc) if yc else None,
            'mean_year': round(sum(int(y) * v for y, v in yc.items()) / float(tot), 2) if yc else None,
            'years': yc,
            'cluster': comm_of.get(n, 0),
            'centrality': round(bc.get(n, 0.0), 5),
            'degree': deg.get(n, {}).get('degree', 0),
            'strength': round(deg.get(n, {}).get('strength', 0.0), 2),
            'located': coords(n) is not None,
        })
    node_out.sort(key=lambda x: -x['count'])
    id_of = {n['name']: n['id'] for n in node_out}

    all_edges = sorted(edges.items(), key=lambda kv: -kv[1])
    shown = all_edges[:top_edges]
    edge_out = [{'source': id_of[a], 'target': id_of[b], 'weight': w}
                for (a, b), w in shown if a in id_of and b in id_of]

    # re-number clusters by size for stable colours
    order = sorted(set(n['cluster'] for n in node_out),
                   key=lambda c: -sum(1 for n in node_out if n['cluster'] == c))
    remap = {c: i for i, c in enumerate(order)}
    for n in node_out:
        n['cluster'] = remap.get(n['cluster'], 0)

    cluster_out = []
    for ci in order:
        members = [n for n in node_out if n['cluster'] == remap[ci]]
        cluster_out.append({
            'id': remap[ci], 'size': len(members),
            'label': ', '.join(m['name'] for m in
                               sorted(members, key=lambda x: -x['count'])[:3]),
            'top': [m['name'] for m in sorted(members, key=lambda x: -x['count'])[:6]],
        })
    cluster_out.sort(key=lambda c: c['id'])

    return {
        'nodes': node_out,
        'edges': edge_out,
        'clusters': cluster_out,
        'summary': {
            'n_countries': len(node_out),
            'n_edges_total': len(edges),
            'n_edges_shown': len(edge_out),
            'n_unresolved': sum(unknown.values()),
            'modularity': round(net.modularity(nodes, edges, communities), 4)
            if edges else 0.0,
        },
        'unknown': [{'name': k, 'count': v}
                    for k, v in unknown.most_common(25)],
    }


def world_geojson():
    with open(WORLD_FILE, encoding='utf-8') as f:
        import json
        return json.load(f)


if __name__ == '__main__':
    print('countries in table:', len(_COORDS), ' aliases:', len(_ALIAS))
    for probe in ['USA', 'Peoples R China', 'England', 'U Arab Emirates',
                  'South Korea', 'Taiwan', 'Hong Kong', 'Germany (West)',
                  'Netherlands', 'Nowhere Land']:
        print('  %-18s -> %s %s' % (probe, resolve(probe),
                                    coords(resolve(probe)) if resolve(probe) else ''))
    import json as _json
    docs = [
        {'countries': ['USA', 'Peoples R China'], 'year': 2020},
        {'countries': ['USA', 'Germany'], 'year': 2021},
        {'countries': ['Peoples R China', 'Japan'], 'year': 2021},
        {'countries': ['England', 'France', 'USA'], 'year': 2022},
    ]
    r = build(docs)
    print('summary:', r['summary'])
    for n in r['nodes']:
        print('   %-18s n=%d (%.1f, %.1f) c%d bc=%.3f'
              % (n['name'], n['count'], n['lat'], n['lon'], n['cluster'], n['centrality']))
    print('edges:', r['edges'])
    print('unknown:', r['unknown'])
