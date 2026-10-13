"""Расчёт длин кабельных линий по исполнительному чертежу.

Алгоритм:
 1. Граф трассы из красных/синих линий, точки — номера в рамках.
 2. Каждая подпись L= привязывается к участку между двумя точками
    (по выноске подписи и по совпадению с длиной по масштабу 1:500).
    Красная подпись — кабель в земле, чёрная — в трубе, рамка СКТ/ГНБ — ГНБ (берётся Lпр).
 3. Для каждой КЛ из спецификации («... (т.1) - ВРЩ№1 (т.51) ... L=...») перебираются
    все маршруты от точки до точки, выбирается тот, чья сумма совпадает с длиной в спецификации.
    Если совпадения нет — КЛ помечается для ручной проверки, ничего не подгоняется.
"""
import collections
import io
import math
import re

from .extract import (BLACK, PT_PER_M, RED, build_graph, candidate_spans, col, load, polylines,
                      seg_dist, text_lines)

NUM = r'(\d+(?:[.,]\d+)?)'
TOL = 0.015  # допуск совпадения со спецификацией, м


def fnum(s):
    return float(s.replace(',', '.'))


def norm_pt(s):
    return s.strip().replace('a', 'а').replace('A', 'а').replace('А', 'а')


def hungarian(C):
    """Минимальное назначение строк столбцам (n <= m). Возвращает [(row, col)]."""
    n, m = len(C), len(C[0]) if C else 0
    if n == 0 or m == 0:
        return []
    transposed = n > m
    if transposed:
        C = [list(r) for r in zip(*C)]
        n, m = m, n
    INF = float('inf')
    u, v = [0.0] * (n + 1), [0.0] * (m + 1)
    p, way = [0] * (m + 1), [0] * (m + 1)
    for i in range(1, n + 1):
        p[0], j0 = i, 0
        minv, used = [INF] * (m + 1), [False] * (m + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], INF, 0
            for j in range(1, m + 1):
                if not used[j]:
                    cur = C[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j], way[j] = cur, j0
                    if minv[j] < delta:
                        delta, j1 = minv[j], j
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    res = [(p[j] - 1, j - 1) for j in range(1, m + 1) if p[j] != 0]
    return [(b, a) for a, b in res] if transposed else res


def parse_spec(rows):
    cables = []
    pat = re.compile(r'(\d+)\s*КЛ\s+(.+?)\s*\(\s*т\.?\s*([\dа-яa-zА-ЯA-Z]+)\s*\)\s*[-–—]\s*(.+?)\s*\(\s*т\.?\s*([\dа-яa-zА-ЯA-Z]+)\s*\)\s*\.?\s*(.*?),?\s*L\s*=\s*'
                     r'(?:(\d+)\s*[xх×*]\s*' + NUM + r'\s*=\s*)?' + NUM)
    for r in rows:
        m = pat.search(r['t'])
        if not m:
            continue
        n, frm, ta, to, tb, mark, k, per, tot = m.groups()
        n = int(n)
        if per:
            per = fnum(per)
        else:
            per = fnum(tot) / n if n > 1 and fnum(tot) > 0 else fnum(tot)
        mark = mark.strip().rstrip(',').strip()
        sec = re.search(r'\d+\s*[xх×]\s*\(?\d+(?:[/,.]\d+)?\)?(?:/\d+)?', mark)
        cables.append(dict(spec_text=r['t'], count=n, frm=frm.strip(), to=to.strip(), a=norm_pt(ta), b=norm_pt(tb),
                           mark=mark, section=sec.group(0).replace(' ', '') if sec else '', spec_len=round(per, 2)))
    return cables


def parse_totals(rows):
    totals = {}
    pats = {
        'l_no_gnb': r'L\s*без\s*ГНБ\s*=\s*' + NUM,
        'l_plan': r'Lплан\.?\s*=\s*' + NUM,
        'l_prof': r'Lпроф\.?\s*=\s*' + NUM,
        'l_cable_total': r'Итого\s*кабеля\s*:?\s*L\s*=\s*' + NUM,
        'l_ks': r'^\s*L\s*=\s*' + NUM + r'\s*м\s*$',
    }
    for r in rows:
        for key, pat in pats.items():
            mm = re.search(pat, r['t'])
            if mm and key not in totals:
                totals[key] = fnum(mm.group(1))
    return totals


def parse_gnb(rows):
    out = []
    for r in rows:
        m = re.search(r'ГНБ\s*№?\s*([\d.]+)', r['t'])
        if not m:
            continue
        box = dict(name='ГНБ №' + m.group(1).rstrip('.'), x=r['x0'], y=r['y'])
        for r2 in rows:
            if abs(r2['x0'] - r['x0']) < 3 and 0 < r2['y'] - r['y'] < 30:
                mp = re.search(r'Lпл\.?\s*=\s*' + NUM, r2['t'])
                if mp:
                    box['plan'] = fnum(mp.group(1))
                    mc = re.search(r'(\d+)\s*тр\.?\s*d\s*=\s*(\d+)', r2['t'])
                    if mc:
                        box['pipes'], box['d'] = int(mc.group(1)), int(mc.group(2))
                mr = re.search(r'Lпр\.?\s*=\s*' + NUM, r2['t'])
                if mr:
                    box['prof'] = fnum(mr.group(1))
            if abs(r2['x0'] - r['x0']) < 3 and -40 < r2['y'] - r['y'] < 0:
                ms = re.search(r'СКТ\s*№\s*(\d+)', r2['t'])
                if ms:
                    box['skt'] = ms.group(1)
        if 'plan' in box:
            out.append(box)
    return out


def parse_labels(T, rows, inplan):
    labels = []
    for t in T:
        m = re.fullmatch(r'L\s*=\s*' + NUM + r'\s*м?', t['t'])
        if not m or not inplan(t):
            continue
        kind = 'ground' if t['col'] == RED else 'pipe'
        lab = dict(v=fnum(m.group(1)), kind=kind, x=t['cx'], y=t['cy'], text=t['t'], bb=t['bb'], col=t['col'])
        if kind == 'pipe':
            cand = []
            for r in rows:
                mp = re.search(r'(\d+)\s*тр\.?\s*(ПЭ|ПНД|ПВХ|[АаХх]\s*/\s*[цЦ])', r['t'])
                if not mp:
                    continue
                dx, dy = abs(r['x0'] - t['x']), t['y'] - r['y']
                if dx < 45 and 0 < dy < 32:
                    score = dy + dx / 3
                elif math.hypot(r['x0'] - t['x'], dy) < 70:
                    score = 100 + math.hypot(r['x0'] - t['x'], dy)
                else:
                    continue
                cand.append((score, r, mp))
            if cand:
                score, r, mp = min(cand, key=lambda c: c[0])
                pt = mp.group(2).replace(' ', '')
                pt = {'а/ц': 'А/Ц', 'а/Ц': 'А/Ц', 'А/ц': 'А/Ц', 'х/ц': 'Х/Ц', 'Х/ц': 'Х/Ц'}.get(pt, pt)
                lab.update(n=int(mp.group(1)), ptype=pt, pipe_guess=score >= 100)
                for r2 in rows:
                    md = re.search(r'd\s*=\s*(\d+)', r2['t'])
                    if md and abs(r2['x0'] - r['x0']) < 45 and 0 < r2['y'] - r['y'] < 14:
                        lab['d'] = int(md.group(1))
        labels.append(lab)
    return labels


def attach_leaders(page, labels):
    thin = []
    for o in page.lines + page.curves:
        if o['linewidth'] >= 0.65 or not o.get('stroke', True):
            continue
        c = col(o)
        for pl in polylines(o):
            for a, b in zip(pl, pl[1:]):
                thin.append((a, b, c))
    for lab in labels:
        ends = []
        centers = [((q[0] + q[2]) / 2, (q[1] + q[3]) / 2) for q in lab['bb']]
        for a, b, c in thin:
            if c != lab['col']:
                continue
            if min(seg_dist(p, a, b)[0] for p in centers) < 3.5:
                ends += [a, b]
        lab['ends'] = ends


def render_plan(data, bbox, page_w, page_h, scale=4.0):
    """Подложка для просмотра: участок плана трассы в JPEG (base64)."""
    try:
        import base64
        import pypdfium2 as pdfium
        x0, y0, x1, y1 = (max(0, bbox[0]), max(0, bbox[1]), min(page_w, bbox[2]), min(page_h, bbox[3]))
        doc = pdfium.PdfDocument(data)
        pg = doc[0]
        # pdfium: поля обрезки слева, снизу, справа, сверху
        img = pg.render(scale=scale, crop=(x0, page_h - y1, page_w - x1, y0)).to_pil().convert('RGB')
        buf = io.BytesIO()
        img.save(buf, 'JPEG', quality=82)
        doc.close()
        return dict(src='data:image/jpeg;base64,' + base64.b64encode(buf.getvalue()).decode(), x0=x0, y0=y0, x1=x1, y1=y1)
    except Exception as e:  # подложка не критична для расчёта
        return dict(error=str(e))


def compute(source, zavodka_default=(5.0, 5.0), k_ground=1.02, k_pipe=1.01, with_image=True):
    if isinstance(source, (str, bytes)) and not isinstance(source, bytes):
        data = open(source, 'rb').read()
    elif isinstance(source, bytes):
        data = source
    else:
        data = source.read()
    R = load(io.BytesIO(data))
    page, T = R['page'], R['T']
    bx0, by0, bx1, by1 = R['bbox']

    def inplan(t):
        return bx0 <= t['cx'] <= bx1 and by0 <= t['cy'] <= by1

    warnings = list(R['problems'])
    adj, anchor_node, anc_pt = build_graph(R)
    spans = candidate_spans(adj, anchor_node)
    rows = text_lines(T)
    cables = parse_spec(rows)
    totals = parse_totals(rows)
    gnb = parse_gnb(rows)
    labels = parse_labels(T, rows, inplan)
    attach_leaders(page, labels)

    # ---------- привязка подписей к участкам
    def pdist(x, y, s):
        return min(seg_dist((x, y), a, b)[0] for a, b in s['segs'])

    items = [('L', l) for l in labels] + [('G', g) for g in gnb]
    BIG = 1e6
    C = [[BIG] * len(spans) for _ in items]
    for i, (typ, it) in enumerate(items):
        for j, s in enumerate(spans):
            geo = s['geo']
            if typ == 'L':
                d = pdist(it['x'], it['y'], s)
                if d > 110:
                    continue
                rel = abs(it['v'] - geo) / max(0.35, 0.12 * it['v'])
                dc = min((pdist(e[0], e[1], s) for e in it['ends']), default=None)
                C[i][j] = (dc / 3 + rel * 2) if dc is not None and dc < 3.0 else (1.5 + d / 8 + rel * 2)
            else:
                rel = abs(it['plan'] - geo) / max(0.5, 0.03 * it['plan'])
                C[i][j] = rel * 3 + pdist(it['x'], it['y'], s) / 100
    for i, j in hungarian(C):
        if C[i][j] >= BIG / 10:
            continue
        typ, it = items[i]
        s = spans[j]
        if typ == 'L':
            s.update(kind=it['kind'], len=it['v'], label=it['text'], dev=round(abs(it['v'] - s['geo']), 2))
            if it['kind'] == 'pipe':
                s.update(pipes=it.get('n'), ptype=it.get('ptype'), d=it.get('d'), pipe_guess=it.get('pipe_guess', False))
        else:
            s.update(kind='gnb', len=it.get('prof', it['plan']), len_plan=it['plan'], gnb=it['name'], skt=it.get('skt'),
                     pipes=it.get('pipes'), d=it.get('d'), ptype='ПЭ', dev=round(abs(it['plan'] - s['geo']), 2))
            if 'prof' not in it:
                warnings.append(f"{it['name']}: не найдена длина по профилю (Lпр), взята плановая")
        it['assigned'] = True
    for typ, it in items:
        if not it.get('assigned'):
            warnings.append(f"Подпись «{it.get('text', it.get('name'))}» не привязана к участку трассы")
    used = [s for s in spans if 'kind' in s]
    for s in used:
        if s['kind'] != 'gnb' and s['dev'] > max(0.6, 0.12 * s['len']):
            warnings.append(f"Инфо: участок т.{s['a']}–т.{s['b']} подписан {s['len']} м, а по масштабу 1:500 ≈ {s['geo']:.2f} м (в расчёт идёт подпись)")
        if s['kind'] == 'pipe' and not s.get('pipes'):
            warnings.append(f"Труба т.{s['a']}–т.{s['b']} L={s['len']}: не найдено количество/тип труб")

    # ---------- маршруты КЛ
    g = collections.defaultdict(list)
    for s in used:
        g[s['a']].append((s['b'], s))
        g[s['b']].append((s['a'], s))

    def all_paths(a, b, limit):
        out = []

        def dfs(u, seen, acc, L):
            if L > limit or len(out) > 5000:
                return
            if u == b:
                out.append((L, list(acc)))
                return
            for v, s in g[u]:
                if v in seen:
                    continue
                seen.add(v)
                acc.append((u, v, s))
                dfs(v, seen, acc, L + s['len'])
                acc.pop()
                seen.discard(v)

        dfs(a, {a}, [], 0.0)
        return out

    def describe(path):
        steps = [dict(frm=u, to=v, kind=s['kind'], len=s['len'], pipes=s.get('pipes'), ptype=s.get('ptype'),
                      d=s.get('d'), gnb=s.get('gnb')) for u, v, s in path]
        r = dict(steps=steps)
        for k in ('ground', 'pipe', 'gnb'):
            parts = [x['len'] for x in steps if x['kind'] == k]
            r[k] = round(sum(parts), 2)
            r[k + '_parts'] = parts
        r['route_len'] = round(sum(x['len'] for x in steps), 2)
        return r

    for c in cables:
        if c['a'] not in g or c['b'] not in g:
            miss = c['a'] if c['a'] not in g else c['b']
            c.update(status='error', msg=f'Точка т.{miss} не найдена на трассе')
            continue
        limit = (c['spec_len'] + 40) if c['spec_len'] else 5000
        P = all_paths(c['a'], c['b'], limit)
        if not P:
            c.update(status='error', msg='Маршрут между точками не найден')
            continue
        if c['spec_len']:
            P.sort(key=lambda p: (abs(p[0] - c['spec_len']), p[0]))
        else:
            P.sort(key=lambda p: p[0])
        best = P[0]
        c.update(describe(best[1]))
        c['diff'] = round(best[0] - c['spec_len'], 2) if c['spec_len'] else None
        same = [p for p in P if abs(p[0] - best[0]) < 0.005]
        if c['spec_len'] and abs(best[0] - c['spec_len']) <= TOL:
            c['status'] = 'ok'
            if len(same) > 1:
                variants = {(d_['ground'], d_['pipe'], d_['gnb']) for d_ in (describe(p[1]) for p in same)}
                if len(variants) > 1:
                    c['status'] = 'ambiguous'
                    c['msg'] = f'{len(same)} маршрута дают одинаковую длину, но разный состав — выберите вручную'
        elif not c['spec_len']:
            c.update(status='nospec', msg='Нет длины в спецификации — взят кратчайший маршрут')
        else:
            c.update(status='mismatch', msg=f"Ни один маршрут не совпал со спецификацией (ближайший {best[0]:.2f} м, разница {c['diff']:+.2f} м)")
        c['alternatives'] = [dict(describe(p[1]), path=[x[0] for x in p[1]] + [c['b']]) for p in P[:6]]
        c['path'] = [x[0] for x in best[1]] + [c['b']]

    # ---------- строки таблицы «кВ» (каждый кабель отдельной строкой, как в журнале)
    table = []
    zf, zt = zavodka_default
    for ci, c in enumerate(cables):
        if 'steps' not in c:
            continue
        for k in range(c['count']):
            name = f"{c['frm']} - {c['to']}"
            total = c['ground'] * k_ground + c['gnb'] + c['pipe'] * k_pipe + zf + zt
            table.append(dict(cable=ci, name=name, mark=c['mark'], section=c['section'], ground=c['ground'],
                              ground_parts=c['ground_parts'], gnb=c['gnb'], gnb_parts=c['gnb_parts'], pipe=c['pipe'],
                              pipe_parts=c['pipe_parts'], zav_from=zf, zav_to=zt, total=round(total, 4),
                              rounded=int(math.floor(total + 0.5)), status=c['status']))

    # ---------- общие итоги по трассе (каждый участок один раз)
    route_spans = {}
    for c in cables:
        for st in c.get('steps', []):
            route_spans[tuple(sorted((st['frm'], st['to'])))] = st
    if not route_spans:
        route_spans = {(s['a'], s['b']): dict(kind=s['kind'], len=s['len'], pipes=s.get('pipes'), ptype=s.get('ptype'), d=s.get('d')) for s in used}
    t_ground = round(sum(s['len'] for s in route_spans.values() if s['kind'] == 'ground'), 2)
    t_pipe = round(sum(s['len'] for s in route_spans.values() if s['kind'] == 'pipe'), 2)
    t_gnb = round(sum(s['len'] for s in route_spans.values() if s['kind'] == 'gnb'), 2)
    pipe_rows = collections.OrderedDict()
    for key, s in sorted(route_spans.items(), key=lambda kv: (str(kv[1].get('ptype')), -kv[1]['len'])):
        if s['kind'] != 'pipe':
            continue
        name = f"Труба {s.get('ptype') or '?'} {s.get('d') or ''}".strip()
        pipe_rows.setdefault(name, []).append(dict(span=f't.{key[0]}–т.{key[1]}', len=s['len'], count=s.get('pipes') or 0,
                                                   total=round(s['len'] * (s.get('pipes') or 0), 2)))
    summary = dict(trench_ground=t_ground, trench_pipe=t_pipe, trench_no_gnb=round(t_ground + t_pipe, 2), gnb_prof=t_gnb,
                   pipes={k: dict(rows=v, total=round(sum(x['total'] for x in v), 2)) for k, v in pipe_rows.items()},
                   cable_total=sum(r['rounded'] for r in table), cables_count=len(table))
    checks = []
    if 'l_no_gnb' in totals:
        checks.append(dict(name='L без ГНБ (по чертежу)', drawing=totals['l_no_gnb'], calc=summary['trench_no_gnb']))
    if 'l_ks' in totals and 'l_no_gnb' not in totals:
        checks.append(dict(name='L трассы (по чертежу)', drawing=totals['l_ks'], calc=summary['trench_no_gnb']))
    if 'l_cable_total' in totals:
        checks.append(dict(name='Итого кабеля по спецификации', drawing=totals['l_cable_total'],
                           calc=round(sum(c.get('route_len', 0) * c['count'] for c in cables), 2)))
    for ch in checks:
        tol = 0.02 if 'Итого' not in ch['name'] else 0.011 * max(1, sum(c['count'] for c in cables))
        ch['ok'] = abs(ch['drawing'] - ch['calc']) <= tol

    title = next((r['t'] for r in rows if 'По адресу' in r['t']), '')
    W, H = float(page.width), float(page.height)
    out = dict(
        page=dict(w=W, h=H), bbox=R['bbox'], address=title.replace('По адресу:', '').strip(),
        cables=cables, table=table, summary=summary, totals=totals, checks=checks, gnb=gnb, warnings=warnings,
        spans=[dict(a=s['a'], b=s['b'], kind=s['kind'], len=s['len'], geo=round(s['geo'], 2), pipes=s.get('pipes'),
                    ptype=s.get('ptype'), d=s.get('d'), gnb=s.get('gnb'), pipe_guess=s.get('pipe_guess', False),
                    pts=[list(a) for a, b in s['segs']] + [list(s['segs'][-1][1])]) for s in used],
        points={n: list(p) for n, p in anc_pt.items()},
        params=dict(k_ground=k_ground, k_pipe=k_pipe, zavodka=list(zavodka_default)),
    )
    R['pdf'].close()
    if with_image:
        out['image'] = render_plan(data, R['bbox'], W, H)
    return out
