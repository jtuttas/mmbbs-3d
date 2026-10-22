import pymupdf, sys, re, json, os, glob
import numpy as np, cv2
from PIL import Image

D = '/home/claude/plan/Grundrisse/Grundrisse_Zwischenstand_nach_vier_Workshops'
OUT = '/home/claude/site/data'
os.makedirs(OUT, exist_ok=True)
FLOORS = [('KG', -1, 'KG1', '1. Untergeschoss'), ('EG', 0, 'EG0', 'Erdgeschoss'),
          ('OG1', 1, 'OG1', '1. Obergeschoss'), ('OG2', 2, 'OG2', '2. Obergeschoss'),
          ('OG3', 3, 'OG3', '3. Obergeschoss'), ('OG4', 4, 'OG4', '4. Obergeschoss'),
          ('OG5', 5, 'OG5', '5. Obergeschoss')]
X0, Y0, X1, Y1 = 330.0, 200.0, 1760.0, 1408.0   # crop in pt
M = 0.0352778                                     # metres per pt at 1:100
R = 2.0                                           # raster px per pt (mask)
TR = 2.0                                          # texture px per pt
W, H = int((X1 - X0) * R), int((Y1 - Y0) * R)
EXCL = {'KG1': [(578, 705, 872, 1118), (325, 735, 568, 1025)]}           # inset drawings inside the plan area

def key(v): return tuple(round(c, 2) for c in v) if v else None

def inside_excl(rect, ex):
    return any(rect.x0 >= a and rect.y0 >= b and rect.x1 <= c and rect.y1 <= d for a, b, c, d in ex)

def P(pt): return ((pt.x - X0) * R, (pt.y - Y0) * R)

prev_hole = None
meta = {'metersPerPx': M / R, 'width': W, 'height': H, 'floors': []}
for fid, lvl, code, name in FLOORS:
    path = glob.glob(f'{D}/*{code}_Grundriss*.pdf')[0]
    page = pymupdf.open(path)[0]
    ex = EXCL.get(code, [])
    mask = np.zeros((H, W), np.uint8)
    drs = page.get_drawings()
    sk = {}
    for d in drs:
        if d['type'] == 's' and d.get('color'):
            r = d['rect']; sk.setdefault((round(r.x0), round(r.y0), round(r.x1), round(r.y1)), set()).add(key(d['color']))
    tlines = []
    for b in page.get_text('dict')['blocks']:
        for L in b.get('lines', []):
            tlines.append(pymupdf.Rect(L['bbox']))
    wmask = np.zeros((H, W), np.uint8)
    roomf = np.zeros((H, W), np.uint8)
    for d in drs:
        op = d.get('fill_opacity') or 1
        fc = d.get('fill') or (0, 0, 0)
        grey = max(fc) - min(fc) < 0.05
        if d['type'] == 's' and d.get('color') and max(d['color']) - min(d['color']) > 0.3 and len(d['items']) >= 8 \
                and d['rect'].width < 1500 and not inside_excl(d['rect'], ex):
            for it in d['items']:
                if it[0] == 'l':
                    cv2.line(roomf, tuple(map(int, P(it[1]))), tuple(map(int, P(it[2]))), 255, 3)
        if d['type'] in ('f', 'fs') and 0.4 < op < 0.6 and d['rect'].width < 1500 and not (grey and len(d['items']) > 40) and sum(1 for it in d['items'] if it[0] == 'c') < 12 \
                and not inside_excl(d['rect'], ex) and d['rect'].x0 >= X0 and d['rect'].y0 >= Y0 and d['rect'].x1 <= X1 and d['rect'].y1 <= Y1:
            subs, cur, last = [], [], None
            for it in d['items']:
                if it[0] in ('l', 'c'):
                    a, b = it[1], it[-1]
                    if last is not None and abs(a.x - last.x) + abs(a.y - last.y) > 0.5:
                        subs.append(cur); cur = []
                    if not cur: cur.append(P(a))
                    cur.append(P(b)); last = b
                elif it[0] == 're':
                    q = it[1]; subs.append([P(q.tl), P(q.tr), P(q.br), P(q.bl)])
                elif it[0] == 'qu':
                    q = it[1]; subs.append([P(q.ul), P(q.ur), P(q.lr), P(q.ll)])
            subs.append(cur)
            for sp in subs:
                if len(sp) > 2:
                    cv2.fillPoly(roomf, [np.array(sp, np.int32)], 255)
    for d in drs:
        if d['type'] != 'f' or key(d.get('fill')) != (1.0, 1.0, 1.0) or d.get('fill_opacity') != 1.0: continue
        r = d['rect']
        if r.x1 < X0 or r.x0 > X1 or r.y1 < Y0 or r.y0 > Y1 or inside_excl(r, ex): continue
        if (0.75, 0.75, 0.75) in sk.get((round(r.x0), round(r.y0), round(r.x1), round(r.y1)), ()): continue
        if r.width * r.height > 3000 and min(r.width, r.height) > 17: pass
        pts = []
        for it in d['items']:
            if it[0] == 'l': pts += [P(it[1]), P(it[2])]
            elif it[0] == 're': q = it[1]; pts += [P(q.tl), P(q.tr), P(q.br), P(q.bl)]
            elif it[0] == 'qu': q = it[1]; pts += [P(q.ul), P(q.ur), P(q.lr), P(q.ll)]
            elif it[0] == 'c': pts += [P(it[1]), P(it[4])]
        if len(pts) < 3: continue
        arr = np.array(pts, np.float32)
        (_, _), (rw, rh), _ = cv2.minAreaRect(arr)
        mn, mx = min(rw, rh) / R, max(rw, rh) / R      # in pt
        curved = any(it[0] == 'c' for it in d['items'])
        if not (mn <= 17 or (mx <= 22 and curved)): continue   # thin wall layer or round column
        if mx <= 22 and not curved and mn > 6: continue
        if mx > 900: continue                            # page-scale masks
        ta = r.width * r.height
        if ta > 0 and any((r & t).get_area() > 0.4 * ta for t in tlines if r.intersects(t)): continue   # label backgrounds
        cv2.fillPoly(wmask, [arr.astype(np.int32)], 255)
    for d in drs:
        r = d['rect']
        if r.x1 < X0 or r.x0 > X1 or r.y1 < Y0 or r.y0 > Y1 or inside_excl(r, ex):
            continue
        t, fill, col, w = d['type'], key(d.get('fill')), key(d.get('color')), round(d.get('width') or 0, 2)
        isline = t == 's' and col is not None and max(col) < 0.05 and w >= 0.7
        isfill = t == 'f' and fill in [(1.0, 0.0, 0.0), (0.96, 0.0, 0.0), (0.0, 0.0, 0.0)] and (d.get('fill_opacity') or 1) > 0.99 and r.width * r.height < 16000
        if not (isline or isfill):
            continue
        for it in d['items']:
            if it[0] == 'l':
                a, b = P(it[1]), P(it[2])
                if isline:
                    cv2.line(mask, tuple(map(int, a)), tuple(map(int, b)), 255, max(2, int(round(w * R))))
            elif it[0] == 're':
                q = it[1]; pts = np.array([P(q.tl), P(q.tr), P(q.br), P(q.bl)], np.int32)
                (cv2.fillPoly if isfill else cv2.polylines)(*((mask, [pts], 255) if isfill else (mask, [pts], True, 255, 2)))
            elif it[0] == 'qu':
                q = it[1]; pts = np.array([P(q.ul), P(q.ur), P(q.lr), P(q.ll)], np.int32)
                if isfill: cv2.fillPoly(mask, [pts], 255)
                else: cv2.polylines(mask, [pts], True, 255, 2)
            elif it[0] == 'c' and isline:
                a, b = P(it[1]), P(it[4]); cv2.line(mask, tuple(map(int, a)), tuple(map(int, b)), 255, 2)
        if isfill:
            pts = [P(it[1]) for it in d['items'] if it[0] == 'l'] + [P(it[2]) for it in d['items'] if it[0] == 'l'][-1:]
            if len(pts) > 2: cv2.fillPoly(mask, [np.array(pts, np.int32)], 255)
    for a, b, c, dd in ex:
        mask[int((b - Y0) * R):int((dd - Y0) * R), int((a - X0) * R):int((c - X0) * R)] = 0
    # fill the space between double wall lines
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (25, 25))
    walls = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k)
    wm = cv2.morphologyEx(wmask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(wm, 8)
    for i in range(1, n):
        if st[i, cv2.CC_STAT_AREA] < 300: continue
        comp = (lab == i).astype(np.uint8)
        er = cv2.erode(comp, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (31, 31)))
        if er.sum() > 0.15 * st[i, cv2.CC_STAT_AREA]:
            wm[lab == i] = 0            # solid blob (stair flights, landings) -> not a wall
    walls = cv2.bitwise_or(walls, wm)
    # Türen öffnen: Schwenkbereich jeder Türaufschlag-Bogenlinie freiräumen
    doors = np.zeros((H, W), np.uint8); ndoor = 0
    for d in drs:
        if d['type'] != 's' or not d.get('color') or max(d['color']) > 0.3: continue
        r0 = d['rect']
        if r0.x1 < X0 or r0.x0 > X1 or r0.y1 < Y0 or r0.y0 > Y1 or inside_excl(r0, ex): continue
        for it in d['items']:
            if it[0] != 'c': continue
            p1, c1, c2, p2 = it[1], it[2], it[3], it[4]
            t1 = np.array([c1.x - p1.x, c1.y - p1.y]); t2 = np.array([p2.x - c2.x, p2.y - c2.y])
            if np.linalg.norm(t1) < 1e-3 or np.linalg.norm(t2) < 1e-3: continue
            n1 = np.array([-t1[1], t1[0]]); n2 = np.array([-t2[1], t2[0]])
            A = np.array([n1, -n2]).T; b = np.array([p2.x - p1.x, p2.y - p1.y])
            if abs(np.linalg.det(A)) < 1e-6: continue
            k = np.linalg.solve(A, b)
            cx_, cy_ = p1.x + k[0] * n1[0], p1.y + k[0] * n1[1]
            r1 = np.hypot(p1.x - cx_, p1.y - cy_); r2 = np.hypot(p2.x - cx_, p2.y - cy_)
            if not (15 <= r1 <= 42) or abs(r1 - r2) > 0.08 * r1: continue
            ang = np.degrees(np.arccos(np.clip(np.dot([p1.x - cx_, p1.y - cy_], [p2.x - cx_, p2.y - cy_]) / (r1 * r2), -1, 1)))
            if ang < 30 or ang > 100: continue
            # Sektor als Polygon (Mittelpunkt + Bogenpunkte)
            a1 = np.arctan2(p1.y - cy_, p1.x - cx_); a2 = np.arctan2(p2.y - cy_, p2.x - cx_)
            da = (a2 - a1 + np.pi) % (2 * np.pi) - np.pi
            pts = [P(pymupdf.Point(cx_, cy_))] + [P(pymupdf.Point(cx_ + r1 * np.cos(a1 + da * t), cy_ + r1 * np.sin(a1 + da * t))) for t in np.linspace(0, 1, 8)]
            cv2.fillPoly(doors, [np.array(pts, np.int32)], 255); ndoor += 1
        # gestrichelte / polygonale Bögen: Kreis an Linienpunkte anpassen
        ls = [it for it in d['items'] if it[0] == 'l']
        if len(ls) >= 4 and len(ls) == len(d['items']) and max(r0.width, r0.height) <= 45 and max(r0.width, r0.height) >= 12:
            pts_ = np.array([[it[1].x, it[1].y] for it in ls] + [[ls[-1][2].x, ls[-1][2].y]])
            A = np.c_[2 * pts_, np.ones(len(pts_))]; bb = (pts_ ** 2).sum(1)
            try:
                sol = np.linalg.lstsq(A, bb, rcond=None)[0]
            except Exception:
                continue
            cx_, cy_ = sol[0], sol[1]; rr = np.sqrt(max(sol[2] + cx_ ** 2 + cy_ ** 2, 0))
            if not (15 <= rr <= 42): continue
            if np.abs(np.hypot(pts_[:, 0] - cx_, pts_[:, 1] - cy_) - rr).max() > 0.08 * rr: continue
            angs = np.unwrap(np.arctan2(pts_[:, 1] - cy_, pts_[:, 0] - cx_))
            span = np.degrees(angs.max() - angs.min())
            if span < 30 or span > 100: continue
            pts = [P(pymupdf.Point(cx_, cy_))] + [P(pymupdf.Point(cx_ + rr * np.cos(a), cy_ + rr * np.sin(a))) for a in np.linspace(angs.min(), angs.max(), 8)]
            cv2.fillPoly(doors, [np.array(pts, np.int32)], 255); ndoor += 1
    doors = cv2.dilate(doors, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (19, 19)))
    walls[doors > 0] = 0
    # remove specks
    n, lab, st, _ = cv2.connectedComponentsWithStats(walls, 8)
    for i in range(1, n):
        if st[i, cv2.CC_STAT_AREA] < 60: walls[lab == i] = 0
    # ---- Treppen aus den Stufennummern der Pläne ----
    nums, stg = [], []
    for b in page.get_text('dict')['blocks']:
        for L in b.get('lines', []):
            for sp in L['spans']:
                t = sp['text'].strip(); bb = sp['bbox']
                if not (X0 < bb[0] < X1 and Y0 < bb[1] < Y1) or inside_excl(pymupdf.Rect(bb), ex): continue
                mm = re.match(r'(\d+)\s*STG\s*x\s*([\d,]+)', t)
                if mm: stg.append((int(mm.group(1)), float(mm.group(2).replace(',', '.')) / 100))
                if re.fullmatch(r'\d{1,2}', t) and sp['size'] < 6.5:
                    nums.append((int(t), (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2))
    chains = []
    used = set()
    for i, (k, x, y) in enumerate(nums):
        if k != 1: continue
        ch = [(x, y)]; cx, cy = x, y; kk = 1
        while True:
            cand = [(np.hypot(x2 - cx, y2 - cy), j) for j, (k2, x2, y2) in enumerate(nums) if k2 == kk + 1 and j not in used]
            cand = [c for c in cand if c[0] < 80]
            if not cand: break
            dmin, j = min(cand); used.add(j); cx, cy = nums[j][1], nums[j][2]; ch.append((cx, cy)); kk += 1
        if len(ch) >= 20: chains.append(ch)
    Hs = [N * r for N, r in stg if any(len(c) == N for c in chains)]
    Hf = min(Hs) if Hs else 4.35
    stairs3d = []; smask = np.zeros((H, W), np.uint8); hole = np.zeros((H, W), np.uint8)
    def ray(px, py, dx, dy, maxpx):
        for t in range(6, int(maxpx), 2):
            xx, yy = int(px + dx * t), int(py + dy * t)
            if not (0 <= xx < W and 0 <= yy < H) or walls[yy, xx]: return t
        return maxpx
    for ch in chains:
        N = len(ch); rr = Hf / N
        pts = np.array([P(pymupdf.Point(x, y)) for x, y in ch], np.float64)
        gaps = np.hypot(*(pts[1:] - pts[:-1]).T)
        med = np.median(gaps)
        treads = []
        for k in range(N):
            a = pts[max(k - 1, 0)]; b = pts[min(k + 1, N - 1)]
            # Laufrichtung lokal; an Knicken nur den Nachbarn im selben Lauf verwenden
            if k > 0 and gaps[k - 1] > 1.6 * med: a = pts[k]
            if k < N - 1 and gaps[k] > 1.6 * med: b = pts[k]
            dv = b - a; ln = np.hypot(*dv)
            if ln < 1e-6: dv = pts[k] - pts[k - 1] if k else pts[1] - pts[0]; ln = np.hypot(*dv)
            dv = dv / ln; nv = np.array([-dv[1], dv[0]])
            maxw = 1.8 / (M / R)
            wp = ray(pts[k][0], pts[k][1], nv[0], nv[1], maxw); wm2 = ray(pts[k][0], pts[k][1], -nv[0], -nv[1], maxw)
            treads.append([pts[k], dv, nv, wp, wm2])
        # Treppenläufe: einheitliche Seite und Breite (Mehrheitsentscheid je Lauf)
        flight = [0]
        for k in range(1, N): flight.append(flight[-1] + (1 if gaps[k - 1] > 1.6 * med else 0))
        for fl in set(flight):
            idx = [k for k in range(N) if flight[k] == fl]
            dm = np.mean([treads[k][1] for k in idx], axis=0); dm /= (np.hypot(*dm) or 1)
            nref = np.array([-dm[1], dm[0]])
            plus, minus = [], []
            for k in idx:
                c, dv, nv, wp, wm2 = treads[k]
                if np.dot(nv, nref) < 0: wp, wm2 = wm2, wp
                plus.append(wp); minus.append(wm2)
            side = 1 if np.median(plus) >= np.median(minus) else -1
            far = plus if side == 1 else minus; near = minus if side == 1 else plus
            ws = min(np.percentile(far, 75), maxw); bs = min(np.median(near), 0.2 / (M / R))
            for k in idx:
                nv = treads[k][2]
                if np.dot(nv, nref) * side < 0: nv = -nv
                treads[k] = [treads[k][0], treads[k][1], nv, ws, bs]
        for k in range(N):
            c, dv, nv, w, back = treads[k]; depth = med
            poly = [c - dv * depth / 2 - nv * back, c + dv * depth / 2 - nv * back, c + dv * depth / 2 + nv * w, c - dv * depth / 2 + nv * w]
            dc = depth * 0.7   # Kollisionsfläche überlappend, damit keine Lücken zwischen Stufen entstehen
            pc = [c - dv * dc - nv * back, c + dv * dc - nv * back, c + dv * dc + nv * w, c - dv * dc + nv * w]
            treads[k] = (poly, dv, nv, w, back)
            stairs3d.append({'p': [[round(float(v), 1) for v in q] for q in poly], 'pc': [[round(float(v), 1) for v in q] for q in pc], 'h': round((k + 1) * rr, 3), 'k': k + 1, 'n': N})
        # Podeste bei großen Lücken
        for k in range(N - 1):
            if gaps[k] > 1.6 * med:
                p1, d1, n1, w1_, _ = treads[k]; p2, d2, n2, w2_, _ = treads[k + 1]
                hullpts = np.array(p1 + p2 + ([q + d1 * w1_ for q in p1] + [q - d2 * w2_ for q in p2] if gaps[k] > 3 * med else []), np.float32)
                hull = cv2.convexHull(hullpts).reshape(-1, 2)
                stairs3d.append({'p': [[round(float(v), 1) for v in q] for q in hull], 'h': round((k + 1) * rr, 3), 'k': k + 1, 'n': N, 'landing': True})
    for st_ in stairs3d:
        arr = np.array(st_['p'], np.int32)
        cv2.fillPoly(smask, [arr], 255)
        if st_['k'] < st_['n'] and st_['h'] >= Hf - 2.4: cv2.fillPoly(hole, [np.array(st_.get('pc', st_['p']), np.int32)], 255)
    walls[cv2.dilate(smask, np.ones((3, 3), np.uint8)) > 0] = 0
    hole = cv2.dilate(hole, np.ones((5, 5), np.uint8))
    # footprint from room fills + walls
    roomf = cv2.morphologyEx(roomf, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (45, 45)))
    fp = cv2.bitwise_or(roomf, walls)
    fp = cv2.morphologyEx(fp, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (41, 41)))
    inv = 255 - fp
    n, lab, st, _ = cv2.connectedComponentsWithStats(inv, 4)
    for i in range(1, n):
        if st[i, cv2.CC_STAT_AREA] < 12000: fp[lab == i] = 255   # fill holes < ~4 m2
    fp = cv2.morphologyEx(fp, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (21, 21)))
    # keep largest footprint components only (drop stray bits)
    n, lab, st, _ = cv2.connectedComponentsWithStats(fp, 8)
    for i in range(1, n):
        if st[i, cv2.CC_STAT_AREA] < 20000: fp[lab == i] = 0

    walls = cv2.bitwise_and(walls, cv2.dilate(fp, np.ones((9, 9), np.uint8)))
    band = cv2.subtract(fp, cv2.erode(fp, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (45, 45))))
    if prev_hole is not None:
        fp[prev_hole > 0] = 0          # Treppenauge: Deckenöffnung über der Treppe des Geschosses darunter
    facade = cv2.bitwise_and(walls, band) if lvl >= 0 else np.zeros_like(walls)
    inner = cv2.subtract(walls, facade)
    def polys_of(mm):
        out = []
        cs, hi = cv2.findContours(mm, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
        if hi is None: return out
        hi = hi[0]
        for i, c in enumerate(cs):
            if hi[i][3] != -1 or cv2.contourArea(c) < 40: continue
            o = cv2.approxPolyDP(c, 1.2, True).reshape(-1, 2)
            if len(o) < 3: continue
            hs = []; j = hi[i][2]
            while j != -1:
                if cv2.contourArea(cs[j]) > 30:
                    hh = cv2.approxPolyDP(cs[j], 1.2, True).reshape(-1, 2)
                    if len(hh) >= 3: hs.append(hh.tolist())
                j = hi[j][0]
            out.append([o.tolist(), hs])
        return out
    facade_polys = polys_of(facade)
    # wall polygons (with holes)
    cnts, hier = cv2.findContours(inner, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    polys = []
    if hier is not None:
        hier = hier[0]
        for i, c in enumerate(cnts):
            if hier[i][3] != -1: continue
            if cv2.contourArea(c) < 40: continue
            outer = cv2.approxPolyDP(c, 1.2, True).reshape(-1, 2)
            if len(outer) < 3: continue
            holes = []
            j = hier[i][2]
            while j != -1:
                if cv2.contourArea(cnts[j]) > 30:
                    hh = cv2.approxPolyDP(cnts[j], 1.2, True).reshape(-1, 2)
                    if len(hh) >= 3: holes.append(hh.tolist())
                j = hier[j][0]
            polys.append([outer.tolist(), holes])
    # footprint polygons
    cnts2, hier2 = cv2.findContours(fp, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    fpolys = []
    if hier2 is not None:
        hier2 = hier2[0]
        for i, c in enumerate(cnts2):
            if hier2[i][3] != -1: continue
            outer = cv2.approxPolyDP(c, 2, True).reshape(-1, 2).tolist()
            holes = []; j = hier2[i][2]
            while j != -1:
                if cv2.contourArea(cnts2[j]) > 2000:
                    holes.append(cv2.approxPolyDP(cnts2[j], 2, True).reshape(-1, 2).tolist())
                j = hier2[j][0]
            fpolys.append([outer, holes])

    # collision grid at 10 cm
    cell = 0.10
    gs = cell / (M / R)
    gw, gh = int(W / gs), int(H / gs)
    wsmall = cv2.resize(walls, (gw, gh), interpolation=cv2.INTER_AREA)
    fsmall = cv2.resize(fp, (gw, gh), interpolation=cv2.INTER_AREA)
    grid = np.zeros((gh, gw), np.uint8)
    grid[fsmall > 127] = 1          # walkable interior
    grid[wsmall > 60] = 2           # wall
    if prev_hole is not None:
        hsmall = cv2.resize(prev_hole, (gw, gh), interpolation=cv2.INTER_AREA)
        ssmall = cv2.resize(smask, (gw, gh), interpolation=cv2.INTER_AREA)
        grid[(hsmall > 127) & (ssmall < 60)] = 3
    Image.fromarray(np.array([0, 100, 200, 50], np.uint8)[grid]).save(f'{OUT}/{fid}_grid.png', optimize=True)

    # floor texture (full plan render) with footprint alpha
    pix = page.get_pixmap(matrix=pymupdf.Matrix(TR, TR), clip=pymupdf.Rect(X0, Y0, X1, Y1), alpha=False)
    img = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
    a = cv2.resize(fp, (pix.width, pix.height), interpolation=cv2.INTER_NEAREST)
    a = cv2.dilate(a, np.ones((5, 5), np.uint8))
    rgba = img.convert('RGBA'); rgba.putalpha(Image.fromarray(a))
    rgba.save(f'{OUT}/{fid}_floor.webp', quality=82, method=6)
    rgba.resize((pix.width // 2, pix.height // 2), Image.LANCZOS).save(f'{OUT}/{fid}_floor_s.webp', quality=78, method=6)
    if fid == 'EG':
        gm = cv2.resize(255 - fp, (W // 2, H // 2), interpolation=cv2.INTER_AREA)
        Image.fromarray(gm).save(f'{OUT}/ground_mask.png', optimize=True)
        # Bäume aus den Baumkronen-Flächen des Lageplans
        tm = np.zeros((H, W), np.uint8)
        for d in drs:
            if d['type'] not in ('f', 'fs') or not d.get('fill'): continue
            fc = key(d['fill']); op = d.get('fill_opacity') or 1
            if not (0.4 < op < 0.6 and len(d['items']) >= 100 and 100 < d['rect'].width < 600): continue
            r0 = d['rect']
            subs, cur, last = [], [], None
            for it in d['items']:
                if it[0] in ('l', 'c'):
                    a_, b_ = it[1], it[-1]
                    if last is not None and abs(a_.x - last.x) + abs(a_.y - last.y) > 0.5: subs.append(cur); cur = []
                    if not cur: cur.append(P(a_))
                    cur.append(P(b_)); last = b_
            subs.append(cur)
            for sp_ in subs:
                if len(sp_) > 2: cv2.fillPoly(tm, [np.array(sp_, np.int32)], 255)
        tm = cv2.morphologyEx(tm, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (41, 41)))
        tm[cv2.dilate(fp, np.ones((41, 41), np.uint8)) > 0] = 0
        n_, lab_, st_, cen_ = cv2.connectedComponentsWithStats(tm, 8)
        trees = []
        for i in range(1, n_):
            area = st_[i, cv2.CC_STAT_AREA] * (M / R) ** 2
            if area < 4: continue
            ys, xs = np.where(lab_ == i)
            ptsT = np.c_[xs, ys].astype(np.float32)
            (cx_, cy_), (w_, h_), ang_ = cv2.minAreaRect(ptsT)
            mj, mn_ = max(w_, h_), min(w_, h_)
            rad_px = min(mn_ / 2, 4.5 / (M / R))
            cnt = max(1, int(round(mj / (2 * rad_px))))
            ax = np.array([np.cos(np.radians(ang_)), np.sin(np.radians(ang_))]) if w_ >= h_ else np.array([-np.sin(np.radians(ang_)), np.cos(np.radians(ang_))])
            rad = rad_px * M / R
            for t in range(cnt):
                off = (t - (cnt - 1) / 2) * mj / cnt
                trees.append([round(float(cx_ + ax[0] * off), 1), round(float(cy_ + ax[1] * off), 1), round(float(min(rad, 6)), 2)])
        meta['trees'] = trees
        g = img.convert('RGBA'); g.putalpha(Image.fromarray(255 - cv2.resize(fp, (pix.width, pix.height), interpolation=cv2.INTER_NEAREST)))
        g.resize((pix.width // 2, pix.height // 2), Image.LANCZOS).save(f'{OUT}/ground.webp', quality=75, method=6)
        for b in page.get_text('dict')['blocks']:
            t = ' '.join(''.join(s['text'] for s in L['spans']) for L in b.get('lines', []))
            if 'Haupteingang' in t:
                bb = b['bbox']; meta['spawn'] = {'x': ((bb[0] + bb[2]) / 2 - X0) * R, 'y': ((bb[1] + bb[3]) / 2 - Y0) * R}
    Image.fromarray(np.dstack([walls, fp // 2, roomf // 2])).save(f'/home/claude/prev/dbg_{fid}.png')

    # room labels
    rooms = []
    for b in page.get_text('dict')['blocks']:
        lines = [''.join(s['text'] for s in L['spans']).strip() for L in b.get('lines', [])]
        lines = [l for l in lines if l]
        if not lines: continue
        bb = b['bbox']
        if not (X0 < bb[0] < X1 and Y0 < bb[1] < Y1): continue
        if any(inside_excl(pymupdf.Rect(bb), [e]) for e in ex): continue
        cx, cy = ((bb[0] + bb[2]) / 2 - X0) * R, ((bb[1] + bb[3]) / 2 - Y0) * R
        if re.match(r'^-?\d\.[A-Z]\.\d{3}', lines[0]):
            nm = lines[1] if len(lines) > 1 and not lines[1].startswith('NGF') else ''
            ngf = next((l for l in lines if l.startswith('NGF')), '')
            rooms.append({'id': lines[0].split()[0], 'name': nm, 'ngf': ngf.replace('m2', 'm²'), 'x': cx, 'y': cy})
        elif lines[0].upper().startswith('CLUSTER') and len(lines[0]) < 14:
            area = lines[1] if len(lines) > 1 else ''
            rooms.append({'id': lines[0].upper(), 'name': 'Cluster', 'ngf': area.replace('m2', 'm²'), 'x': cx, 'y': cy, 'cluster': True})
    # stair/elevator markers
    stairs = []
    for b in page.get_text('dict')['blocks']:
        txt = ' '.join(''.join(s['text'] for s in L['spans']) for L in b.get('lines', []))
        bb = b['bbox']
        if 'Treppenhaus' in txt and X0 < bb[0] < X1 and Y0 < bb[1] < Y1:
            stairs.append({'x': ((bb[0] + bb[2]) / 2 - X0) * R, 'y': ((bb[1] + bb[3]) / 2 - Y0) * R})
    # Möblierung aus den Plänen (weiße Flächen mit grauer Kontur)
    furn = []
    for d in drs:
        if d['type'] != 'f' or key(d.get('fill')) != (1.0, 1.0, 1.0): continue
        r = d['rect']
        if r.x1 < X0 or r.x0 > X1 or r.y1 < Y0 or r.y0 > Y1 or inside_excl(r, ex): continue
        if (0.75, 0.75, 0.75) not in sk.get((round(r.x0), round(r.y0), round(r.x1), round(r.y1)), ()): continue
        pts = []
        for it in d['items']:
            for q in it[1:]:
                if hasattr(q, 'x'): pts.append(P(q))
                elif hasattr(q, 'x0'): pts += [P(q.tl), P(q.br)]
                elif hasattr(q, 'ul'): pts += [P(q.ul), P(q.ur), P(q.lr), P(q.ll)]
        if len(pts) < 3: continue
        (cx, cy), (w, h), ang = cv2.minAreaRect(np.array(pts, np.float32))
        wm_, hm_ = w * M / R, h * M / R
        mn, mx = sorted([wm_, hm_])
        curved = any(it[0] == 'c' for it in d['items'])
        ix, iy = int(cx), int(cy)
        if not (0 <= ix < W and 0 <= iy < H) or fp[iy, ix] == 0: continue
        if curved:
            if 0.6 <= mn and mx <= 1.5 and mx - mn < 0.15: t = 'round'
            else: continue
        elif 0.3 <= mn <= 0.5 and mx <= 0.56: t = 'chair'
        elif mn >= 0.48 and mx <= 2.5 and mn * mx <= 4.5: t = 'table'
        elif 0.35 <= mn <= 0.9 and mx > 2.5: t = 'cab'
        else: continue
        furn.append([t, round(cx, 1), round(cy, 1), round(wm_, 2), round(hm_, 2), round(float(ang), 1)])
    prev_hole = hole
    json.dump({'walls': polys, 'furn': furn, 'stairs3d': stairs3d, 'facade': facade_polys, 'footprint': fpolys, 'rooms': rooms, 'stairs': stairs,
               'grid': {'w': gw, 'h': gh, 'cell': cell}}, open(f'{OUT}/{fid}.json', 'w'), separators=(',', ':'))
    meta['floors'].append({'id': fid, 'level': lvl, 'name': name, 'height': round(Hf, 3), 'source': os.path.basename(path)})
    print(fid, 'H', round(Hf,3), 'stairs', len(chains), [len(c) for c in chains], 'furn', len(furn), 'doors', ndoor, 'walls', len(polys), 'rooms', len(rooms), 'stairs', len(stairs), 'tex', pix.width, pix.height)
json.dump(meta, open(f'{OUT}/meta.json', 'w'), indent=1)
