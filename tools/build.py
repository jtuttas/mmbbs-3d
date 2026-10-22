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
    # remove specks
    n, lab, st, _ = cv2.connectedComponentsWithStats(walls, 8)
    for i in range(1, n):
        if st[i, cv2.CC_STAT_AREA] < 60: walls[lab == i] = 0
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
    Image.fromarray(grid * 100).save(f'{OUT}/{fid}_grid.png', optimize=True)

    # floor texture (full plan render) with footprint alpha
    pix = page.get_pixmap(matrix=pymupdf.Matrix(TR, TR), clip=pymupdf.Rect(X0, Y0, X1, Y1), alpha=False)
    img = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
    a = cv2.resize(fp, (pix.width, pix.height), interpolation=cv2.INTER_NEAREST)
    a = cv2.dilate(a, np.ones((5, 5), np.uint8))
    rgba = img.convert('RGBA'); rgba.putalpha(Image.fromarray(a))
    rgba.save(f'{OUT}/{fid}_floor.webp', quality=82, method=6)
    rgba.resize((pix.width // 2, pix.height // 2), Image.LANCZOS).save(f'{OUT}/{fid}_floor_s.webp', quality=78, method=6)
    if fid == 'EG':
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
    json.dump({'walls': polys, 'facade': facade_polys, 'footprint': fpolys, 'rooms': rooms, 'stairs': stairs,
               'grid': {'w': gw, 'h': gh, 'cell': cell}}, open(f'{OUT}/{fid}.json', 'w'), separators=(',', ':'))
    meta['floors'].append({'id': fid, 'level': lvl, 'name': name, 'source': os.path.basename(path)})
    print(fid, 'walls', len(polys), 'rooms', len(rooms), 'stairs', len(stairs), 'tex', pix.width, pix.height)
json.dump(meta, open(f'{OUT}/meta.json', 'w'), indent=1)
