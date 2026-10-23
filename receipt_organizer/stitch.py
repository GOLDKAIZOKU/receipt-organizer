"""Join a long receipt that was scanned in two overlapping pieces. Pieces are matched by image content (not by name or position);
a join is only accepted when the overlap is found with high confidence. The joined image is a derived file; both source scans stay untouched."""
import cv2, numpy as np

def _gray(img): return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
def _ink_rows(g):
    ink = (g < 200).sum(1); idx = np.nonzero(ink > 3)[0]
    return (int(idx[0]), int(idx[-1]) + 1) if len(idx) else (0, g.shape[0])

LR = 0.4
def _prep(img):
    """Ink map that ignores paper tone and lighting differences between the two scans (faded thermal paper looks different in each)."""
    g = cv2.resize(_gray(img), None, fx=LR, fy=LR, interpolation=cv2.INTER_AREA)
    bg = cv2.medianBlur(g, 31); d = cv2.subtract(bg, g)               # dark-on-light ink, background removed
    d = cv2.GaussianBlur(d, (0, 0), 1.0); d = cv2.normalize(d, None, 0, 255, cv2.NORM_MINMAX)
    return (255 - d)                                                   # back to dark ink on light, matches the rest of the code
def match_pair(A, B, min_score=0.62, debug=False):
    """A = upper piece, B = lower piece (both upright). Returns None or dict(score, a_cut, b_start, joined)."""
    s = A.shape[1] / B.shape[1]
    if not (0.8 <= s <= 1.25): return None
    B2 = cv2.resize(B, None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC)
    ga = _prep(A); gb = _prep(B2)
    a0, a1 = _ink_rows(ga); b0, b1 = _ink_rows(gb); W = ga.shape[1]; best = None
    h = max(24, min(90, (a1 - a0) // 6)); x0, x1 = int(W * .1), int(W * .9)
    # candidate template strips from the lower 45% of A
    for y in range(max(a0, a1 - int((a1 - a0) * .45)), a1 - h + 1, max(8, h // 3)):
        t = ga[y:y + h, x0:x1]
        if t.std() < 14: continue                      # blank strip: cannot be matched reliably
        # search only in the upper 60% of B (the overlap must be near B's start)
        lim = b0 + int((b1 - b0) * .85)
        reg = gb[max(0, b0 - 10):min(gb.shape[0], lim + h), :]
        if reg.shape[0] < t.shape[0] or reg.shape[1] < t.shape[1]: continue
        r = cv2.matchTemplate(reg, t, cv2.TM_CCOEFF_NORMED); _, sc, _, loc = cv2.minMaxLoc(r)
        if best is None or sc > best['score']:
            best = dict(score=float(sc), a_y=y, b_y=loc[1] + max(0, b0 - 10), dx=loc[0] - x0)
    if debug: return best
    if not best or best['score'] < min_score or abs(best['dx']) > 25 * LR: return None
    a_y = int(best['a_y'] / LR); b_y = int(best['b_y'] / LR); dx = int(best['dx'] / LR)
    joined_h = a_y + (B2.shape[0] - b_y)
    if joined_h < ga.shape[0] / LR + 0.12 * B2.shape[0]:
        return dict(score=best['score'], duplicate=True)      # B adds almost nothing new: same piece scanned twice
    top = A[:a_y]; bot = B2[b_y:]
    if dx:  # shift bottom piece sideways to line up
        M = np.float32([[1, 0, -dx], [0, 1, 0]]); bot = cv2.warpAffine(bot, M, (bot.shape[1], bot.shape[0]), borderValue=(255, 255, 255))
    Wd = min(top.shape[1], bot.shape[1]); out = np.vstack([top[:, :Wd], bot[:, :Wd]])
    return dict(score=best['score'], duplicate=False, joined=out, a_cut=a_y, b_start=b_y)

# ---------------------------------------------------------------------------------------------------------------------
# Fallback for crumpled / badly lit receipts where pixels do not line up: match by the TEXT of the printed lines.
import difflib, re
from . import ocr_backend as ob
_rows_cache = {}
def _rows(img, key):
    if key not in _rows_cache: _rows_cache[key] = ob.rows(img)
    return _rows_cache[key]
def _norm(t): return re.sub(r'[^A-Z0-9]', '', t.upper())

def match_by_text(A, B, rowsA=None, rowsB=None, min_run=3, min_ratio=0.82):
    s = A.shape[1] / B.shape[1]
    if not (0.8 <= s <= 1.25): return None
    B2 = cv2.resize(B, None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC)
    ra = [dict(r, n=_norm(r['text'])) for r in (rowsA if rowsA is not None else ob.rows(A))]
    rb = [dict(r, n=_norm(r['text']), y0=r['y0'] * s, y1=r['y1'] * s) for r in (rowsB if rowsB is not None else ob.rows(B))]
    ra = [r for r in ra if len(r['n']) >= 6]; rb = [r for r in rb if len(r['n']) >= 6]
    if len(ra) < 4 or len(rb) < 4: return None
    eq = lambda x, y: difflib.SequenceMatcher(None, x, y).ratio() >= min_ratio
    best = None
    for i in range(0, int(len(rb) * 0.85)):
        for j in range(len(ra) // 3, len(ra)):
            if not eq(rb[i]['n'], ra[j]['n']): continue
            m = 1
            while j + m < len(ra) and i + m < len(rb) and eq(rb[i + m]['n'], ra[j + m]['n']): m += 1
            reaches_end = (j + m == len(ra))
            if m >= min_run and reaches_end and (best is None or m > best[0]): best = (m, i, j)
    if not best: return None
    m, i, j = best; a_y = int(max(0, ra[j]['y0'] - 4)); b_y = int(max(0, rb[i]['y0'] - 4))
    top = A[:a_y]; bot = B2[b_y:]; Wd = min(top.shape[1], bot.shape[1])
    out = np.vstack([top[:, :Wd], bot[:, :Wd]])
    if out.shape[0] < A.shape[0] + 0.12 * B2.shape[0]: return dict(score=m / 10, duplicate=True)
    return dict(score=min(1.0, 0.5 + m / 20), duplicate=False, joined=out, matched_rows=m, a_cut=a_y, b_start=b_y)


def join_all(items, log=lambda m: None, min_score=0.62):
    """items: [{'crop','flags','scan', ...}]. Only crops clipped by the scan edge are candidates; pieces must come from different scans.
    Tries the fast image match first, then the text match. Returns a list of dict(kind, a, b, score, method, image)."""
    cl = [i for i, it in enumerate(items) if 'CLIPPED_BY_SCAN_EDGE' in it['flags']]
    cands = []
    def rot(x, r): return cv2.rotate(x, cv2.ROTATE_180) if r else x
    for i in cl:
        for j in cl:
            if i == j or items[i]['scan'] == items[j]['scan']: continue
            if not (0.8 <= items[i]['crop'].shape[1] / items[j]['crop'].shape[1] <= 1.25): continue
            for r in (0, 1):                       # both pieces are upright, or both are upside down
                A = rot(items[i]['crop'], r); B = rot(items[j]['crop'], r)
                m = match_pair(A, B, min_score)
                if m: cands.append((m['score'], i, j, r, 'image', m))
    used = set(); joins = []
    def take(c):
        sc, i, j, r, how, m = c
        if i in used or j in used: return
        if m.get('duplicate'): joins.append(dict(kind='duplicate_piece', a=i, b=j, score=sc, method=how)); return
        used.update((i, j)); joins.append(dict(kind='joined', a=i, b=j, score=sc, method=how, rot=r, image=m['joined']))
    for c in sorted(cands, key=lambda c: -c[0]): take(c)
    # text fallback for clipped crops that found no partner
    left = [i for i in cl if i not in used]
    tc = []
    for i in left:
        for j in left:
            if i == j or items[i]['scan'] == items[j]['scan']: continue
            if not (0.8 <= items[i]['crop'].shape[1] / items[j]['crop'].shape[1] <= 1.25): continue
            for r in (0, 1):
                A = rot(items[i]['crop'], r); B = rot(items[j]['crop'], r)
                m = match_by_text(A, B, _rows(A, (id(items[i]['crop']), r)), _rows(B, (id(items[j]['crop']), r)))
                if m: tc.append((m['score'], i, j, r, 'text', m))
    for c in sorted(tc, key=lambda c: -c[0]): take(c)
    return joins
