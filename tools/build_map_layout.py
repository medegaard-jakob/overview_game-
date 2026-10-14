"""Build data/map_layout.js from the Heathrow T1/T2 ground movement chart (UK AIP AD 2-EGLL-2-7, PDF).

Usage: python3 tools/build_map_layout.py <chart.pdf>

Reads the published stand coordinate table (exact positions for every stand) and the terminal
outlines from the chart's vector drawing, and writes positions in metres (x east, y south).
The chart image itself is not stored. Stand headings point the nose at the nearest terminal or
pier face; the remote 251-258 line faces east as drawn on the chart. Roads and the baggage-hall
docks are a simplified layout drawn on top of that geometry.
"""
import sys, re, json, math, collections, os
import pymupdf as fitz
import numpy as np

pdf = sys.argv[1]
page = fitz.open(pdf)[0]
R = page.rotation_matrix
OX, OY = 1050, 400          # shift so the area of interest starts near (0, 0)

# ---- stand coordinate table ----
words = []
for w in page.get_text('words'):
    c = fitz.Point((w[0] + w[2]) / 2, (w[1] + w[3]) / 2) * R
    words.append((c.x, c.y, w[4]))
lat_re = re.compile(r'^(\d{2})(\d{2})(\d{2}\.\d+)N$'); lon_re = re.compile(r'^(\d{3})(\d{2})(\d{2}\.\d+)W$')
rows = collections.defaultdict(list)
for x, y, t in words:
    if x > 860 and y > 330: rows[round(y)].append((x, t))
table = {}
for ws in rows.values():
    toks = [t for _, t in sorted(ws)]
    i = 0
    while i < len(toks) - 2:
        a, b = lat_re.match(toks[i + 1]), lon_re.match(toks[i + 2])
        if a and b:
            table[toks[i]] = (int(a[1]) + int(a[2]) / 60 + float(a[3]) / 3600, -(int(b[1]) + int(b[2]) / 60 + float(b[3]) / 3600)); i += 3
        else: i += 1
lat0 = sum(v[0] for v in table.values()) / len(table); lon0 = sum(v[1] for v in table.values()) / len(table)
metres = {k: ((lon - lon0) * math.cos(math.radians(lat0)) * 111320, -(lat - lat0) * 110574) for k, (lat, lon) in table.items()}

# chart points -> metres, fitted on the stand labels
labels = {}
for x, y, t in words:
    if x < 860 and t in metres and t not in labels: labels[t] = (x, y)
A = np.array([[labels[k][0], labels[k][1], 1] for k in labels])
cx = np.linalg.lstsq(A, np.array([metres[k][0] for k in labels]), rcond=None)[0]
cy = np.linalg.lstsq(A, np.array([metres[k][1] for k in labels]), rcond=None)[0]
to_m = lambda p: (float(cx @ [p.x, p.y, 1]) + OX, float(cy @ [p.x, p.y, 1]) + OY)

# ---- terminal outlines (navy fills on the chart) ----
def simplify(pts, tol):
    """Drop points that sit within tol metres of the line through their neighbours."""
    out = list(pts)
    changed = True
    while changed and len(out) > 3:
        changed = False
        for i in range(len(out)):
            a, p, b = np.array(out[i - 1]), np.array(out[i]), np.array(out[(i + 1) % len(out)])
            ab = b - a; n = np.linalg.norm(ab)
            d = abs(ab[0] * (p - a)[1] - ab[1] * (p - a)[0]) / n if n else np.linalg.norm(p - a)
            if d < tol:
                del out[i]; changed = True; break
    return out
buildings = []
for dr in page.get_drawings():
    f = dr.get('fill')
    if not f or not (abs(f[0] - .2) < .04 and abs(f[1] - .2) < .04 and abs(f[2] - .56) < .03): continue
    pts = []
    for it in dr['items']:
        if it[0] == 'l': pts += [it[1], it[2]]
        elif it[0] == 'c': pts += [it[1], it[4]]
        elif it[0] == 're': r = it[1]; pts += [r.tl, r.tr, r.br, r.bl]
    pts = [to_m(p * R) for p in pts]
    dedup = [p for i, p in enumerate(pts) if i == 0 or math.dist(p, pts[i - 1]) > .5]
    if len(dedup) < 3: continue
    xs = [p[0] for p in dedup]; ys = [p[1] for p in dedup]
    area = (max(xs) - min(xs)) * (max(ys) - min(ys))
    if area < 1500 or area > 400000 or max(xs) < 380 or min(xs) > 1850 or min(ys) < -40 or max(ys) > 900: continue
    simple = simplify(dedup, 1.5)
    buildings.append([[round(x, 1), round(y, 1)] for x, y in simple])

# ---- stand headings: nose towards the nearest terminal face ----
def nearest_on_poly(p, poly):   # kept for reference: used to check the group headings above
    best = None
    for i in range(len(poly)):
        a, b = np.array(poly[i]), np.array(poly[(i + 1) % len(poly)]); ab = b - a
        t = max(0, min(1, np.dot(np.array(p) - a, ab) / (np.dot(ab, ab) or 1))); q = a + t * ab
        d = np.linalg.norm(np.array(p) - q)
        if best is None or d < best[0]: best = (d, q)
    return best
stands = {}
for k, (x, y) in metres.items():
    p = (x + OX, y + OY)
    n = int(re.match(r'\d+', k)[0])
    # nose direction per stand group, as drawn by the lead-in lines on the chart
    if n in (209, 210): h = (0.0, -1.0)                  # north, towards the T1 finger
    elif 211 <= n <= 220: h = (-1.0, 0.0)                # west, towards T1 / T2A
    elif 221 <= n <= 226: h = (0.0, -1.0)                # north, towards the T2A south face
    elif 231 <= n <= 239: h = (1.0, 0.0)                 # east, towards the T2B pier
    elif 241 <= n <= 249: h = (-1.0, 0.0)                # west, towards the T2B pier
    elif 251 <= n <= 258: h = (1.0, 0.0)                 # remote line, east
    else: h = (0.0, -1.0)
    stands[k] = {'x': round(p[0], 1), 'y': round(p[1], 1), 'hx': h[0], 'hy': h[1]}

# ---- L/R positions the chart's table doesn't list: estimate from neighbours on the same pier face ----
def estimate_split(base):
    """Place <base>L / <base>R using the average L/R offset of other split stands in the same group."""
    group = int(base) // 10
    offs = {'L': [], 'R': []}
    for k, v in stands.items():
        m = re.match(r'^(\d+)([LR])$', k)
        if m and int(m[1]) // 10 == group and m[1] in stands and stands[m[1]]['hx'] == stands[base]['hx']:
            offs[m[2]].append((v['x'] - stands[m[1]]['x'], v['y'] - stands[m[1]]['y']))
    for side, lst in offs.items():
        name = base + side
        if name in stands or not lst: continue
        dx = sum(o[0] for o in lst) / len(lst); dy = sum(o[1] for o in lst) / len(lst)
        b = stands[base]
        stands[name] = {'x': round(b['x'] + dx, 1), 'y': round(b['y'] + dy, 1), 'hx': b['hx'], 'hy': b['hy'], 'estimated': True}
for base in ('236',):          # 236L / 236R are stands in the GHS data but not in the AIP coordinate table
    estimate_split(base)

# ---- simplified airside roads (head-of-stand roads and the loop around the piers) ----
roads = [
    [[780, 40], [780, 800]],                     # along T1 / T2A east faces
    [[470, 712], [780, 712]],                    # in front of T2A south stands
    [[780, 40], [1420, 40]],                     # north link
    [[780, 800], [1420, 800]],                   # south link
    [[1060, 40], [1060, 800]],                   # T2B west face
    [[1128, 40], [1128, 800]],                   # T2B east face
    [[1420, 40], [1420, 800]],                   # remote 251-258 line
]
# ---- taxiway centre lines: the yellow ribbons on the chart, traced along one edge, joined into a graph ----
def is_yellow(f): return f and abs(f[0] - .97) < .03 and abs(f[1] - .905) < .03 and abs(f[2] - .215) < .03
def bezier(p0, p1, p2, p3, n=8):
    for k in range(1, n + 1):
        t = k / n; u = 1 - t
        yield fitz.Point(u**3 * p0.x + 3 * u * u * t * p1.x + 3 * u * t * t * p2.x + t**3 * p3.x, u**3 * p0.y + 3 * u * u * t * p1.y + 3 * u * t * t * p2.y + t**3 * p3.y)
taxi_lines = []
for dr in page.get_drawings():
    if not is_yellow(dr.get('fill')): continue
    rects = [it[1] for it in dr['items'] if it[0] == 're']
    if rects:   # straight taxiway sections are thin rectangles; near-square boxes are signs
        for r in rects:
            q = [to_m(p * R) for p in (r.tl, r.tr, r.br, r.bl)]
            w, h = math.dist(q[0], q[1]), math.dist(q[1], q[2])
            if max(w, h) < 15 or max(w, h) < 6 * min(w, h): continue
            line = [((q[0][0] + q[3][0]) / 2, (q[0][1] + q[3][1]) / 2), ((q[1][0] + q[2][0]) / 2, (q[1][1] + q[2][1]) / 2)] if w > h else \
                   [((q[0][0] + q[1][0]) / 2, (q[0][1] + q[1][1]) / 2), ((q[3][0] + q[2][0]) / 2, (q[3][1] + q[2][1]) / 2)]
            n = max(1, int(math.dist(*line) // 20))
            taxi_lines.append([(line[0][0] + (line[1][0] - line[0][0]) * k / n, line[0][1] + (line[1][1] - line[0][1]) * k / n) for k in range(n + 1)])
        continue
    # trace each ribbon outline (a drawing can hold several); the two edges are under 2 m apart and merge when snapped
    subs, pts = [], []
    for it in dr['items']:
        if it[0] not in ('l', 'c'): continue
        start = it[1]
        if pts and abs(start.x - pts[-1].x) + abs(start.y - pts[-1].y) > .8: subs.append(pts); pts = []
        if not pts: pts.append(start)
        pts += [it[2]] if it[0] == 'l' else list(bezier(it[1], it[2], it[3], it[4]))
    if pts: subs.append(pts)
    for pts in subs:
        m = [to_m(p * R) for p in pts]
        if len(m) < 2: continue
        xs = [p[0] for p in m]; ys = [p[1] for p in m]
        if math.hypot(max(xs) - min(xs), max(ys) - min(ys)) < 15: continue      # holding marks, arrows
        line = [m[0]]
        for q in m[1:]:
            if math.dist(q, line[-1]) >= 3: line.append(q)
        if math.dist(line[-1], line[0]) < 6: line.append(line[0])           # close the ribbon only across its end cap
        taxi_lines.append(line)
nodes, node_at, edges = [], {}, set()
def node(p, tol=3.0):
    k = (round(p[0] / tol), round(p[1] / tol))
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for i in node_at.get((k[0] + dx, k[1] + dy), []):
                if math.dist(nodes[i], p) < tol: return i
    nodes.append(list(p)); node_at.setdefault(k, []).append(len(nodes) - 1); return len(nodes) - 1
def densify(line, step=10):       # a point every 10 m, so stands and crossings attach where they meet a straight section
    out = [line[0]]
    for p, q in zip(line, line[1:]):
        n = max(1, int(math.dist(p, q) // step))
        out += [(p[0] + (q[0] - p[0]) * k / n, p[1] + (q[1] - p[1]) * k / n) for k in range(1, n + 1)]
    return out
for line in taxi_lines:
    ids = [node(p) for p in densify(line)]
    for a, b in zip(ids, ids[1:]):
        if a != b: edges.add((min(a, b), max(a, b)))
# join loose ends (lead-ins meeting a taxilane, small gaps) to the nearest edge within 12 m
deg = collections.Counter(i for e in edges for i in e)
for i in [i for i in range(len(nodes)) if deg[i] == 1]:
    p = np.array(nodes[i]); best = None
    for a, b in edges:
        if i in (a, b): continue
        A, B = np.array(nodes[a]), np.array(nodes[b]); ab = B - A; L = np.dot(ab, ab)
        t = 0 if L == 0 else max(0, min(1, np.dot(p - A, ab) / L)); q = A + t * ab; d = np.linalg.norm(p - q)
        if d < 12 and (best is None or d < best[0]): best = (d, a, b, t, q)
    if not best: continue
    d, a, b, t, q = best
    if t < .02: edges.add((min(i, a), max(i, a)))
    elif t > .98: edges.add((min(i, b), max(i, b)))
    else:
        nodes.append([float(q[0]), float(q[1])]); k = len(nodes) - 1
        edges.discard((min(a, b), max(a, b))); edges |= {(min(a, k), max(a, k)), (min(b, k), max(b, k)), (min(i, k), max(i, k))}
used = sorted({i for e in edges for i in e}); remap = {o: n for n, o in enumerate(used)}
taxi = {'nodes': [[round(nodes[i][0], 1), round(nodes[i][1], 1)] for i in used], 'edges': sorted([remap[a], remap[b]] for a, b in edges)}

# T1 baggage hall: a dock face on the east side of T1 with one door per bank / store
hall = {'x0': 690, 'x1': 752, 'y0': 280, 'y1': 470}
layout = {'source': 'UK AIP AD 2-EGLL-2-7 (Heathrow T1/T2 ground movement chart)', 'units': 'metres', 'stands': stands,
          'buildings': buildings, 'roads': roads, 'hall': hall, 'taxi': taxi}
out = os.path.join(os.path.dirname(__file__), '..', 'data', 'map_layout.js')
open(out, 'w').write('window.MAP_LAYOUT=' + json.dumps(layout, separators=(',', ':')) + ';\n')
print(len(stands), 'stands,', len(buildings), 'buildings,', sum(len(b) for b in buildings), 'points,', len(taxi['nodes']), 'taxi nodes,', len(taxi['edges']), 'taxi edges →', os.path.relpath(out))
print({k: (v['hx'], v['hy']) for k, v in stands.items() if k in ('209', '211', '213', '216', '221', '231', '241', '251', '258')})
