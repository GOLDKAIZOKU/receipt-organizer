"""Find every receipt on a scan, crop it, straighten it, and turn it upright. Originals are never modified."""
import cv2, numpy as np
from . import ocr_backend as ob

def ink_mask(im):
    g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY); ink = (g < 185).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(ink); keep = np.zeros_like(ink)
    big = np.nonzero(st[:, 4] >= 25)[0]; big = big[big > 0]
    keep = np.isin(lab, big).astype(np.uint8)
    return cv2.morphologyEx(keep, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))

def gaps(profile, min_gap, thr=2):
    on = profile >= thr; idx = np.nonzero(on)[0]
    if len(idx) == 0: return None, []
    a, b = idx[0], idx[-1]; res = []; start = None
    for i in range(a, b + 1):
        if not on[i]:
            if start is None: start = i
        elif start is not None:
            if i - start >= min_gap: res.append((start, i))
            start = None
    return (a, b), res

def good_box(w, h):
    L, S = max(w, h), min(w, h)
    if 1.9 <= L / S <= 7.0 and L >= 600 and S >= 300: return True
    return 1.15 <= L / S < 1.9 and 450 <= L <= 1000 and S >= 380

def split(ink, x0, y0, x1, y1, mg, out):
    sub = ink[y0:y1, x0:x1]; rx, gx = gaps(sub.sum(0), mg); ry, gy = gaps(sub.sum(1), mg)
    if rx is None: return
    bx0, bx1 = x0 + rx[0], x0 + rx[1] + 1; by0, by1 = y0 + ry[0], y0 + ry[1] + 1; w, h = bx1 - bx0, by1 - by0
    if w * h < 60000: return
    if good_box(w, h):
        big = [g for g in gx if g[1] - g[0] >= 2 * mg] if w < h else [g for g in gy if g[1] - g[0] >= 2 * mg]
        if not big: out.append((bx0, by0, bx1, by1)); return
    cands = [('x', g) for g in gx] + [('y', g) for g in gy]
    if not cands: out.append((bx0, by0, bx1, by1)); return
    ax, g = max(cands, key=lambda c: c[1][1] - c[1][0])
    if ax == 'x':
        split(ink, bx0, by0, x0 + g[0], by1, mg, out); split(ink, x0 + g[1], by0, bx1, by1, mg, out)
    else:
        split(ink, bx0, by0, bx1, y0 + g[0], mg, out); split(ink, bx0, y0 + g[1], bx1, by1, mg, out)

def find_boxes(im, mgs=(120, 90, 60, 45, 35, 25)):
    ink = ink_mask(im); best = None
    for mg in mgs:
        out = []; split(ink, 0, 0, ink.shape[1], ink.shape[0], mg, out)
        if not out: continue
        ng = sum(good_box(x1 - x0, y1 - y0) for x0, y0, x1, y1 in out)
        if ng == len(out): return out
        if best is None or ng > best[0]: best = (ng, out)
    return best[1] if best else []

def expand_box(im, box, others, M=220):
    g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY); H, W = g.shape; x0, y0, x1, y1 = box
    ex0, ey0, ex1, ey1 = max(0, x0 - M), max(0, y0 - M), min(W, x1 + M), min(H, y1 + M)
    for (ox0, oy0, ox1, oy1) in others:
        if ox0 >= x1: ex1 = min(ex1, (x1 + ox0) // 2)
        elif ox1 <= x0: ex0 = max(ex0, (x0 + ox1) // 2)
        elif oy0 >= y1: ey1 = min(ey1, (y1 + oy0) // 2)
        elif oy1 <= y0: ey0 = max(ey0, (y0 + oy1) // 2)
    sens = (g < 232).astype(np.uint8); reg = np.zeros_like(sens); reg[ey0:ey1, ex0:ex1] = 1
    for (ox0, oy0, ox1, oy1) in others: reg[max(0, oy0 - 8):oy1 + 8, max(0, ox0 - 8):ox1 + 8] = 0
    reg[y0:y1, x0:x1] = 1
    n, lab, st, _ = cv2.connectedComponentsWithStats(cv2.morphologyEx((sens * reg).astype(np.uint8), cv2.MORPH_CLOSE, np.ones((45, 45), np.uint8)))
    X0, Y0, X1, Y1 = x0, y0, x1, y1
    for i in range(1, n):
        cx, cy, cw, ch, a = st[i]
        if a >= 400 and cx < x1 + 60 and cx + cw > x0 - 60 and cy < y1 + 60 and cy + ch > y0 - 60:
            X0 = min(X0, cx); Y0 = min(Y0, cy); X1 = max(X1, cx + cw); Y1 = max(Y1, cy + ch)
    return max(X0, ex0), max(Y0, ey0), min(X1, ex1), min(Y1, ey1)

KW = {'TOTAL', 'INVOICE', 'RECEIPT', 'DATE', 'TAX', 'CARD', 'THANK', 'SUBTOTAL', 'SUB-TOTAL', 'RM', 'QTY', 'CASHIER', 'MASTERCARD', 'SDN', 'BHD', 'ITEM',
      'AMOUNT', 'PAYMENT', 'CHANGE', 'ROUNDING', 'SERVICE', 'TEL', 'ORDER', 'TABLE', 'PUMP', 'SUBSIDY', 'SCAN', 'PLEASE', 'COME', 'AGAIN', 'REG', 'SST'}
def score(img):
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if max(g.shape) > 1600: g = cv2.resize(g, None, fx=0.6, fy=0.6, interpolation=cv2.INTER_AREA)
    tot = 0.0
    for v in (g, cv2.createCLAHE(3.0, (8, 8)).apply(g)):
        for l in ob.lines(cv2.cvtColor(v, cv2.COLOR_GRAY2BGR)):
            for w in l['text'].upper().replace(':', ' ').replace(',', ' ').split():
                w = w.strip('.')
                if w in KW and l['conf'] > .4: tot += 60
                elif len(w) >= 3 and l['conf'] > .55: tot += 3
    return tot

def skew_angle(c, lim=45.0):
    """Tilt of the printed lines, in degrees (rotate by this to make them level), searched over +-lim.
    Measured inside round patches of the receipt (so a tall, narrow receipt's outline does not bias it), scoring how sharply
    the row profile alternates between text lines and gaps. Coarse 1-degree steps, then 0.2 around the best.
    -> (angle, sure) ; sure=False when the text gives no clear answer."""
    g = cv2.cvtColor(c, cv2.COLOR_BGR2GRAY) if c.ndim == 3 else c
    ink = (g < 170).astype(np.float32); h, w = ink.shape; k = 900 / max(h, w)
    if k < 1: ink = cv2.resize(ink, (max(1, int(w * k)), max(1, int(h * k))), interpolation=cv2.INTER_AREA)
    if ink.sum() < 50: return 0.0, False
    hh, ww = ink.shape; cx = ww // 2; R = max(8, min(hh, ww) // 2)
    centers = [hh // 2] if hh < 1.6 * ww else [int(hh * f) for f in (0.25, 0.5, 0.75)]
    patches = []
    for cy in centers:
        sub = ink[max(0, cy - R):min(hh, cy + R), max(0, cx - R):min(ww, cx + R)]
        yy, xx = np.mgrid[0:sub.shape[0], 0:sub.shape[1]]
        patches.append(sub * (((yy - sub.shape[0] / 2) ** 2 + (xx - sub.shape[1] / 2) ** 2) <= (min(sub.shape) / 2) ** 2))
    def score(a):
        t = 0.0
        for d in patches:
            r = cv2.warpAffine(d, cv2.getRotationMatrix2D((d.shape[1] / 2, d.shape[0] / 2), a, 1), (d.shape[1], d.shape[0])).sum(1)
            t += float((np.diff(r) ** 2).sum())
        return t
    coarse = [(score(a), a) for a in np.arange(-lim, lim + 0.01, 1.0)]
    vb, ab = max(coarse)
    vb, ab = max([(score(a), a) for a in np.arange(ab - 1.0, ab + 1.01, 0.2)])
    vals = sorted(x for x, _ in coarse); med = vals[len(vals) // 2] or 1.0
    return float(round(ab, 1)), bool(vb > 1.3 * med)

def rotate_any(c, a):
    """Turn by any angle (degrees, counter-clockwise like OpenCV), growing the picture so no corner is cut; new corners are white."""
    h, w = c.shape[:2]; M = cv2.getRotationMatrix2D((w / 2, h / 2), a, 1)
    cos, sin = abs(M[0, 0]), abs(M[0, 1]); W, H = int(h * sin + w * cos), int(h * cos + w * sin)
    M[0, 2] += W / 2 - w / 2; M[1, 2] += H / 2 - h / 2
    return cv2.warpAffine(c, M, (W, H), flags=cv2.INTER_CUBIC, borderValue=(255, 255, 255))

def trim_white(c, margin=24):
    """Cut away plain white border (after turning a slanted receipt there is a lot of it)."""
    g = cv2.cvtColor(c, cv2.COLOR_BGR2GRAY) if c.ndim == 3 else c
    ys, xs = np.nonzero(g < 215)
    if len(ys) < 50: return c
    y0, y1 = max(0, ys.min() - margin), min(g.shape[0], ys.max() + margin); x0, x1 = max(0, xs.min() - margin), min(g.shape[1], xs.max() + margin)
    return c[y0:y1, x0:x1]

def deskew(c, lim=45.0):
    """Straighten a receipt that was scanned at a slant (up to 45 degrees)."""
    a, sure = skew_angle(c, lim)
    if abs(a) < 0.4: return c, 0.0
    if not sure or abs(a) >= lim - 0.5: return c, 'NEEDS_MANUAL_ROTATION'
    return trim_white(rotate_any(c, a)), a

def upright(c):
    if c.shape[1] > c.shape[0]: c = cv2.rotate(c, cv2.ROTATE_90_CLOCKWISE)
    d, a = deskew(c); cands = [d, cv2.rotate(d, cv2.ROTATE_180)]
    k = int(np.argmax([score(x) for x in cands])); return cands[k], a

def merge_contiguous(boxes, max_gap=30, min_xoverlap=0.6, min_width_ratio=0.7):
    """One long receipt can be cut into several boxes at folds or creases. Boxes that sit directly on top of each other in the same
    scan (touching, or a few pixels apart) and have about the same width are one piece of paper, so they become one box.
    Returns (merged_boxes, groups) where groups[i] lists the indices merged into merged_boxes[i]."""
    order = sorted(range(len(boxes)), key=lambda i: (boxes[i][1], boxes[i][0])); groups = []
    for i in order:
        x0, y0, x1, y1 = boxes[i]; placed = False
        for g in groups:
            gx0 = min(boxes[k][0] for k in g); gx1 = max(boxes[k][2] for k in g); gy1 = max(boxes[k][3] for k in g)
            ov = min(x1, gx1) - max(x0, gx0); wmin = min(x1 - x0, gx1 - gx0); wr = wmin / max(1, max(x1 - x0, gx1 - gx0))
            if -10 <= y0 - gy1 <= max_gap and ov >= min_xoverlap * wmin and wr >= min_width_ratio: g.append(i); placed = True; break
        if not placed: groups.append([i])
    merged = [(min(boxes[k][0] for k in g), min(boxes[k][1] for k in g), max(boxes[k][2] for k in g), max(boxes[k][3] for k in g)) for g in groups]
    return merged, groups

def crops_from_scan(im, pad=30):
    """-> [(crop_bgr, box, flags)] ; flags are plain strings."""
    H, W = im.shape[:2]
    b = sorted(find_boxes(im), key=lambda t: (round(t[1] / 500), t[0]))
    b = [expand_box(im, bx, [o for o in b if o is not bx]) for bx in b]; b, _ = merge_contiguous(b); out = []
    for (x0, y0, x1, y1) in b:
        c = im[max(0, y0 - pad):y1 + pad, max(0, x0 - pad):x1 + pad].copy(); d, a = upright(c); flags = []
        if x0 <= 3 or y0 <= 3 or x1 >= W - 3 or y1 >= H - 3: flags.append('CLIPPED_BY_SCAN_EDGE')
        if a == 'NEEDS_MANUAL_ROTATION': flags.append('NEEDS_MANUAL_ROTATION')
        out.append((d, (x0, y0, x1, y1), flags))
    return out
