"""Извлечение геометрии и текста из векторного PDF исполнительного чертежа КЛ.

Работает с PDF, выгруженным из AutoCAD/nanoCAD (векторный, не скан):
  * красные линии  — кабель (в земле),
  * синие линии    — трубы и ГНБ,
  * номера точек   — текст в маленьких рамках с выноской на трассу,
  * подписи L=...  — красные (земля) и чёрные (трубы).
"""
import collections
import math
import re

import pdfplumber

# 1:500 -> 1 м на местности = 2 мм на листе = 5.669 pt
PT_PER_M = 2.0 / 25.4 * 72

RED = (1.0, 0.0, 0.0)
BLUE = (0.0, 0.0, 1.0)
BLACK = (0.0, 0.0, 0.0)


# ---------------------------------------------------------------- геометрия
def col(o, key='stroking_color'):
    c = o.get(key)
    if isinstance(c, (tuple, list)):
        if len(c) == 1:
            return (round(float(c[0]), 2),) * 3
        if len(c) == 4:  # CMYK
            cc, m, y, k = c
            return tuple(round((1 - v) * (1 - k), 2) for v in (cc, m, y))
        return tuple(round(float(x), 2) for x in c[:3])
    if isinstance(c, (int, float)):
        return (round(float(c), 2),) * 3
    return c


def polylines(o):
    """Path объекта -> список полилиний (у кривых Безье берём только концевые точки)."""
    out, cur = [], []
    for op in o.get('path') or []:
        kind = op[0]
        if kind == 'm':
            if len(cur) > 1:
                out.append(cur)
            cur = [op[1]]
        elif kind == 'l':
            cur.append(op[1])
        elif kind == 'c':
            cur.append(op[-1])
        elif kind == 'h' and cur:
            cur.append(cur[0])
    if len(cur) > 1:
        out.append(cur)
    if not out and o.get('pts'):
        out = [list(o['pts'])]
    return [[(float(x), float(y)) for x, y in pl] for pl in out]


def seg_dist(p, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / l2))
    q = (ax + t * dx, ay + t * dy)
    return math.dist(p, q), t, q


def rect_dist(p, box):
    x0, y0, x1, y1 = box
    dx = max(x0 - p[0], 0, p[0] - x1)
    dy = max(y0 - p[1], 0, p[1] - y1)
    return math.hypot(dx, dy)


# ---------------------------------------------------------------- текст
def texts(page):
    """Склеиваем символы в надписи с учётом поворота (подписи L= часто повёрнуты)."""
    out, cur = [], None
    for ch in page.chars:
        a, b, c, d, e, f = ch['matrix']
        ang = round(math.degrees(math.atan2(b, a)), 1)
        color = col(ch, 'non_stroking_color')
        x, y = e, f
        sz = max(ch['width'], ch['height'])
        if cur and cur['ang'] == ang and cur['col'] == color and math.dist(cur['last'], (x, y)) < sz * 1.6:
            if ch['text'] == ' ':
                cur['t'] += ' '
                cur['last'] = (x, y)
                continue
            cur['t'] += ch['text']
            cur['last'] = (x, y)
            cur['pts'].append((x, y))
            cur['bb'].append((ch['x0'], ch['top'], ch['x1'], ch['bottom']))
        else:
            if cur:
                out.append(cur)
            cur = None
            if ch['text'] == ' ':
                continue
            cur = dict(t=ch['text'], ang=ang, col=color, last=(x, y), pts=[(x, y)],
                       bb=[(ch['x0'], ch['top'], ch['x1'], ch['bottom'])])
    if cur:
        out.append(cur)
    H = page.height
    for o in out:
        o['t'] = o['t'].strip()
        xs = [(q[0] + q[2]) / 2 for q in o['bb']]
        ys = [(q[1] + q[3]) / 2 for q in o['bb']]
        o['cx'], o['cy'] = sum(xs) / len(xs), sum(ys) / len(ys)
        o['x'] = o['pts'][0][0]
        o['y'] = H - o['pts'][0][1]
    return out


def text_lines(T, tol=1.5):
    """Горизонтальные надписи -> строки (для спецификации, ГНБ, подписей труб)."""
    hz = sorted([t for t in T if t['ang'] == 0], key=lambda t: (round(t['y']), t['x']))
    rows = []
    for t in hz:
        for r in rows:
            if abs(r['y'] - t['y']) < tol and t['x'] - r['xe'] < 40 and t['x'] >= r['x0'] - 1:
                r['items'].append(t)
                r['xe'] = t['bb'][-1][2] + 6
                break
        else:
            rows.append(dict(y=t['y'], x0=t['x'], xe=t['bb'][-1][2] + 6, items=[t]))
    for r in rows:
        r['t'] = ' '.join(i['t'] for i in sorted(r['items'], key=lambda i: i['x']))
    return rows


def markers(page, T):
    """Номера точек: число в маленькой рамке."""
    out = []
    for r in page.rects:
        if not (6 < r['width'] < 22 and 8 < r['height'] < 16):
            continue
        inside = [t for t in T if r['x0'] - 1 < t['cx'] < r['x1'] + 1 and r['top'] - 1 < t['cy'] < r['bottom'] + 1
                  and re.fullmatch(r'\d+[аaАA]?', t['t'])]
        if len(inside) == 1:
            n = inside[0]['t'].replace('a', 'а').replace('A', 'А').replace('А', 'а')
            out.append(dict(n=n, box=(r['x0'], r['top'], r['x1'], r['bottom'])))
    # дубликаты номеров (рамка нарисована дважды) — оставляем одну
    seen, uniq = set(), []
    for m in out:
        if m['n'] in seen:
            continue
        seen.add(m['n'])
        uniq.append(m)
    return uniq


# ---------------------------------------------------------------- трасса
def collapse_parallel(segs, kind, wmin, wmax, minlen, caps):
    """Две параллельные линии (труба-прямоугольник или пучок кабелей двумя линиями) -> осевая."""
    idx = [i for i, s in enumerate(segs) if s[2] == kind]
    used, add = set(), []

    def ang(a, b):
        return math.atan2(b[1] - a[1], b[0] - a[0])

    for ii, i in enumerate(idx):
        if i in used:
            continue
        a1, b1, _ = segs[i]
        L1 = math.dist(a1, b1)
        if L1 < minlen:
            continue
        best = None
        for j in idx[ii + 1:]:
            if j in used:
                continue
            a2, b2, _ = segs[j]
            L2 = math.dist(a2, b2)
            if L2 < minlen or abs(L1 - L2) > 0.25 * max(L1, L2) + 3:
                continue
            da = abs((ang(a1, b1) - ang(a2, b2) + math.pi / 2) % math.pi - math.pi / 2)
            if da > math.radians(6):
                continue
            if math.dist(a1, a2) + math.dist(b1, b2) > math.dist(a1, b2) + math.dist(b1, a2):
                a2, b2 = b2, a2
            w = (math.dist(a1, a2) + math.dist(b1, b2)) / 2
            if wmin <= w <= wmax and (best is None or w < best[0]):
                best = (w, j, a2, b2)
        if best:
            w, j, a2, b2 = best
            used |= {i, j}
            m1 = ((a1[0] + a2[0]) / 2, (a1[1] + a2[1]) / 2)
            m2 = ((b1[0] + b2[0]) / 2, (b1[1] + b2[1]) / 2)
            add.append((m1, m2, (a1, a2, b1, b2)))
    if caps:
        for k in idx:
            if k in used:
                continue
            a, b, _ = segs[k]
            for m1, m2, (a1, a2, b1, b2) in add:
                for p, q in ((a1, a2), (b1, b2)):
                    if (math.dist(a, p) < 2 and math.dist(b, q) < 2) or (math.dist(a, q) < 2 and math.dist(b, p) < 2):
                        used.add(k)
    return [s for i, s in enumerate(segs) if i not in used] + [(m1, m2, kind) for m1, m2, _ in add]


def load(path_or_file):
    pdf = pdfplumber.open(path_or_file)
    page = pdf.pages[0]
    T = texts(page)
    M = markers(page, T)
    if len(M) < 2:
        raise ValueError('На чертеже не найдены номера точек трассы (цифры в рамках). '
                         'Нужен векторный PDF, выгруженный из CAD, а не скан/картинка.')
    bx0 = min(m['box'][0] for m in M) - 60
    by0 = min(m['box'][1] for m in M) - 60
    bx1 = max(m['box'][2] for m in M) + 60
    by1 = max(m['box'][3] for m in M) + 60

    def inplan(x, y):
        return bx0 <= x <= bx1 and by0 <= y <= by1

    objs = page.lines + page.curves + page.rects
    segs = []
    for o in objs:
        if not o.get('stroke', True) or o['linewidth'] <= 0.65:
            continue
        c = col(o)
        kind = 'r' if c == RED else 'b' if c == BLUE else None
        if not kind:
            continue
        for pl in polylines(o):
            for a, b in zip(pl, pl[1:]):
                if math.dist(a, b) > 0.05 and inplan(*a) and inplan(*b):
                    segs.append((a, b, kind))
    segs = collapse_parallel(segs, 'b', 2.5, 14, 8, caps=True)
    segs = collapse_parallel(segs, 'r', 1.5, 6.5, 12, caps=False)

    # выноски номеров -> точки на трассе
    blacks = [o for o in page.lines + page.curves if col(o) == BLACK and o.get('stroke', True)]
    anchors, problems = {}, []
    for m in M:
        best = None
        for o in blacks:
            for pl in polylines(o):
                for end, other in ((pl[0], pl[-1]), (pl[-1], pl[0])):
                    if rect_dist(end, m['box']) < 1.5 and rect_dist(other, m['box']) > 5:
                        d = min((seg_dist(other, a, b)[0] for a, b, _ in segs), default=1e9)
                        if best is None or d < best[0]:
                            best = (d, other)
        if best and best[0] < 8:
            anchors[m['n']] = best[1]
        else:
            problems.append(f"Точка т.{m['n']}: не найдена выноска на трассу")
    return dict(pdf=pdf, page=page, T=T, M=M, segs=segs, anchors=anchors,
                bbox=(bx0, by0, bx1, by1), problems=problems)


# ---------------------------------------------------------------- граф
def build_graph(R, snap=1.2, on_tol=1.0, absorb=4.5, gap=6.0):
    segs = R['segs']
    ends = [e for a, b, k in segs for e in (a, b)]
    anc_pt = {}
    for n, p in R['anchors'].items():
        (d, t, q) = min((seg_dist(p, a, b) for a, b, k in segs), key=lambda x: x[0])
        ne = min(ends, key=lambda e: math.dist(e, p))
        anc_pt[n] = ne if math.dist(ne, p) < 4 else q
    extra = list(anc_pt.values())

    G = 10
    grid = collections.defaultdict(list)
    for p in ends + extra:
        grid[(int(p[0] // G), int(p[1] // G))].append(p)

    def near(a, b):
        for x in range(int(min(a[0], b[0]) // G) - 1, int(max(a[0], b[0]) // G) + 2):
            for y in range(int(min(a[1], b[1]) // G) - 1, int(max(a[1], b[1]) // G) + 2):
                yield from grid.get((x, y), [])

    pieces = []
    for a, b, k in segs:
        L = math.dist(a, b)
        cuts = [(0, a), (1, b)]
        for p in near(a, b):
            d, t, q = seg_dist(p, a, b)
            if d < on_tol and 0 < t < 1 and t * L > snap and (1 - t) * L > snap:
                cuts.append((t, q))
        cuts.sort()
        for (t1, p1), (t2, p2) in zip(cuts, cuts[1:]):
            if math.dist(p1, p2) > 0.01:
                pieces.append((p1, p2, k))

    allp = [p for a, b, k in pieces for p in (a, b)] + extra
    parent = list(range(len(allp)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    g2 = collections.defaultdict(list)
    for i, p in enumerate(allp):
        g2[(int(p[0] // snap), int(p[1] // snap))].append(i)
    for i, p in enumerate(allp):
        cx, cy = int(p[0] // snap), int(p[1] // snap)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in g2.get((cx + dx, cy + dy), []):
                    if j > i and math.dist(p, allp[j]) <= snap:
                        parent[find(j)] = find(i)

    base0 = len(pieces) * 2
    # точка трассы "впитывает" ближайшие вершины (линии на чертеже не всегда сходятся точно)
    pairs = []
    r = int(absorb // snap) + 1
    for ai, p in enumerate(extra):
        cx, cy = int(p[0] // snap), int(p[1] // snap)
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                for j in g2.get((cx + dx, cy + dy), []):
                    if j < base0:
                        d = math.dist(p, allp[j])
                        if d <= absorb:
                            pairs.append((d, j, ai))
    pairs.sort()
    for d, j, ai in pairs:
        others = [math.dist(allp[j], extra[k]) for k in range(len(extra)) if k != ai]
        if others and min(others) < 2 * d:
            continue
        rj, ra = find(j), find(base0 + ai)
        if rj == ra:
            continue
        if rj in {find(base0 + k) for k in range(len(extra))}:
            continue
        parent[rj] = ra

    adj = collections.defaultdict(dict)
    coord = {}
    k = 0
    for a, b, kind in pieces:
        u, v = find(k), find(k + 1)
        coord.setdefault(u, a)
        coord.setdefault(v, b)
        k += 2
        if u == v:
            continue
        L = math.dist(a, b)
        if v not in adj[u] or adj[u][v][0] > L:
            adj[u][v] = (L, kind, a, b)
            adj[v][u] = (L, kind, b, a)
    for i, n in enumerate(anc_pt):
        coord[find(base0 + i)] = anc_pt[n]
    anchor_roots = {find(base0 + i) for i in range(len(anc_pt))}
    # висячие концы линий, оборванные рядом с другой вершиной, — соединяем
    nodes = list(coord)
    for u in nodes:
        if len(adj[u]) != 1 or u in anchor_roots:
            continue
        pu, nb = coord[u], next(iter(adj[u]))
        best = None
        for v in nodes:
            if v in (u, nb) or v in adj[u]:
                continue
            d = math.dist(pu, coord[v])
            if d < gap and (best is None or d < best[0]):
                best = (d, v)
        if best:
            d, v = best
            kind = adj[u][nb][1]
            adj[u][v] = (d, kind, pu, coord[v])
            adj[v][u] = (d, kind, coord[v], pu)
    anchor_node = {n: find(base0 + i) for i, n in enumerate(anc_pt)}
    return adj, anchor_node, anc_pt


def candidate_spans(adj, anchor_node):
    """Участки между соседними номерами точек (геометрическая длина в метрах по масштабу)."""
    node2anchor = collections.defaultdict(list)
    for n, u in anchor_node.items():
        node2anchor[u].append(n)
    spans = {}
    for n, s in anchor_node.items():
        stack = [(s, 0.0, [s], [])]
        while stack:
            u, L, path, segp = stack.pop()
            for v, (l, kind, a, b) in adj[u].items():
                if v in path:
                    continue
                if v in node2anchor:
                    for m in node2anchor[v]:
                        if m == n:
                            continue
                        key = tuple(sorted((n, m), key=str))
                        if key not in spans or spans[key]['geo_pt'] > L + l:
                            spans[key] = dict(a=key[0], b=key[1], geo_pt=L + l, segs=segp + [(a, b)])
                    continue
                if len(path) < 400:
                    stack.append((v, L + l, path + [v], segp + [(a, b)]))
    for s in spans.values():
        s['geo'] = s['geo_pt'] / PT_PER_M
    # убираем "обходные" участки, которые проходят мимо другой точки
    import heapq
    kept = {}

    def sp(a, b):
        dist, h = {a: 0}, [(0, a)]
        while h:
            d, u = heapq.heappop(h)
            if u == b:
                return d
            if d > dist.get(u, 1e18):
                continue
            for (x, y), s in kept.items():
                v = y if x == u else x if y == u else None
                if v is None:
                    continue
                nd = d + s['geo']
                if nd < dist.get(v, 1e18):
                    dist[v] = nd
                    heapq.heappush(h, (nd, v))
        return 1e18

    for key, s in sorted(spans.items(), key=lambda kv: kv[1]['geo']):
        if sp(*key) > s['geo'] * 1.06 + 0.3:
            kept[key] = s
    return list(kept.values())
