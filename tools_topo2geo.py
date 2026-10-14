# -*- coding: utf-8 -*-
"""
tools_topo2geo.py -- one-off converter.

Turns assets/countries-110m.json (TopoJSON, Natural Earth 110m via the
`world-atlas` package) into a plain, compact polygon file that the browser
front end can draw without any GIS library:

    python tools_topo2geo.py            -> assets/world_110m.json

Output shape
    {"countries": [ {"name": ..., "iso": ..., "rings": [[[lon, lat], ...]]} ]}

Rings are Douglas-Peucker simplified (tolerance in degrees) and the
coordinates are rounded, which keeps the file around 200 KB instead of
several MB.  Only run this when the base map needs to be refreshed.
"""

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'assets', 'countries-110m.json')
DST = os.path.join(HERE, 'assets', 'world_110m.json')

TOLERANCE = 0.12      # degrees; 0.12 ~ 13 km, plenty for a background map
MIN_RING_POINTS = 4
MIN_BBOX_DEG = 0.35   # drop islets smaller than this on both axes


def decode_arcs(topology):
    tr = topology.get('transform')
    out = []
    for arc in topology['arcs']:
        x = y = 0
        pts = []
        for dx, dy in arc:
            x += dx
            y += dy
            if tr:
                pts.append((x * tr['scale'][0] + tr['translate'][0],
                            y * tr['scale'][1] + tr['translate'][1]))
            else:
                pts.append((x, y))
        out.append(pts)
    return out


def stitch(arc_ids, arcs):
    """TopoJSON arc index list -> one coordinate ring."""
    ring = []
    for i in arc_ids:
        rev = i < 0
        idx = ~i if rev else i
        seg = arcs[idx]
        if rev:
            seg = seg[::-1]
        if ring:
            ring.extend(seg[1:])
        else:
            ring.extend(seg)
    return ring


def perp_dist(p, a, b):
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    cx, cy = ax + t * dx, ay + t * dy
    return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5


def simplify(pts, tol):
    """Iterative Douglas-Peucker."""
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        best_d, best_k = -1.0, -1
        for k in range(i + 1, j):
            d = perp_dist(pts[k], pts[i], pts[j])
            if d > best_d:
                best_d, best_k = d, k
        if best_d > tol:
            keep[best_k] = True
            stack.append((i, best_k))
            stack.append((best_k, j))
    return [p for p, k in zip(pts, keep) if k]


def main():
    topo = json.load(open(SRC, encoding='utf-8'))
    arcs = decode_arcs(topo)
    geoms = topo['objects']['countries']['geometries']

    countries = []
    for g in geoms:
        name = (g.get('properties') or {}).get('name') or ''
        iso = str(g.get('id') or '')
        arcs_field = g.get('arcs')
        polys = []
        if g['type'] == 'Polygon':
            polys = [arcs_field]
        elif g['type'] == 'MultiPolygon':
            polys = arcs_field
        else:
            continue

        rings = []
        for poly in polys:
            for ring_ids in poly:
                ring = stitch(ring_ids, arcs)
                xs = [p[0] for p in ring]
                ys = [p[1] for p in ring]
                if max(xs) - min(xs) < MIN_BBOX_DEG and \
                        max(ys) - min(ys) < MIN_BBOX_DEG:
                    continue
                ring = simplify(ring, TOLERANCE)
                if len(ring) < MIN_RING_POINTS:
                    continue
                rings.append([[round(x, 2), round(y, 2)] for x, y in ring])
        if rings:
            countries.append({'name': name, 'iso': iso, 'rings': rings})

    countries.sort(key=lambda c: c['name'])
    out = {
        'source': 'Natural Earth 110m (world-atlas 2.0.2)',
        'projection': 'lon/lat WGS84',
        'tolerance_deg': TOLERANCE,
        'countries': countries,
    }
    with open(DST, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
    npts = sum(len(r) for c in countries for r in c['rings'])
    print('countries: %d   rings: %d   points: %d   -> %s (%.0f KB)'
          % (len(countries),
             sum(len(c['rings']) for c in countries), npts, DST,
             os.path.getsize(DST) / 1024.0))


if __name__ == '__main__':
    main()
