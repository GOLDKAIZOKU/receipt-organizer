"""Find the same receipt scanned more than once, by comparing the pictures (so it also works when nothing could be read from them).
Two pieces are called duplicates only when they line up almost everywhere they overlap; two different receipts from the same shop share
a header but not the rest, so they do not pass."""
import cv2, numpy as np

W = 520
def _ink(img):
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    k = W / g.shape[1]; g = cv2.resize(g, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
    if g.shape[0] > 3000: g = g[:3000]
    bg = cv2.medianBlur(g, 31); d = cv2.subtract(bg, g); d = cv2.normalize(d, None, 0, 255, cv2.NORM_MINMAX)
    return d, k
def features(img):
    d, k = _ink(img); orb = cv2.ORB_create(2000, fastThreshold=8); kp, de = orb.detectAndCompute(d, None)
    return dict(ink=d, kp=kp, de=de)
def compare(fa, fb):
    """Returns dict(score, inliers, overlap) or None. score = ink correlation over the overlap after alignment."""
    if fa['de'] is None or fb['de'] is None or len(fa['kp']) < 40 or len(fb['kp']) < 40: return None
    m = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(fb['de'], fa['de'], k=2)
    good = [a for a, b in (x for x in m if len(x) == 2) if a.distance < .75 * b.distance]
    if len(good) < 25: return None
    src = np.float32([fb['kp'][g.queryIdx].pt for g in good]); dst = np.float32([fa['kp'][g.trainIdx].pt for g in good])
    M, inl = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=4.0)
    if M is None or inl.sum() < 20: return None
    s = float(np.hypot(M[0, 0], M[1, 0])); ang = abs(np.degrees(np.arctan2(M[1, 0], M[0, 0])))
    if not (.8 <= s <= 1.25) or ang > 8: return None
    A, B = fa['ink'], fb['ink']; Bw = cv2.warpAffine(B, M, (A.shape[1], A.shape[0])); mask = cv2.warpAffine(np.full(B.shape, 255, np.uint8), M, (A.shape[1], A.shape[0])) > 0
    ov = mask.sum() / max(1, min(mask.size, A.size, B.shape[0] * B.shape[1] * s * s)); 
    # compare on ink rows only, blurred so a 1-2 px shift does not matter
    a = cv2.GaussianBlur(A, (0, 0), 2)[mask].astype(np.float32); b = cv2.GaussianBlur(Bw, (0, 0), 2)[mask].astype(np.float32)
    if a.std() < 1 or b.std() < 1: return None
    score = float(np.corrcoef(a, b)[0, 1])
    return dict(score=score, inliers=int(inl.sum()), overlap=float(ov), scale=s)
def find_duplicates(imgs, min_score=0.55, min_overlap=0.6):
    """imgs: list of images. Returns [(i, j, info)] with i < j for pairs that look like the same receipt."""
    F = [features(im) for im in imgs]; out = []
    for i in range(len(F)):
        for j in range(i + 1, len(F)):
            r = compare(F[i], F[j])
            if r and r['score'] >= min_score and r['overlap'] >= min_overlap: out.append((i, j, r))
    return out


def cached_pairs(work, items, min_score=0.78, min_overlap=0.6, log=lambda m: None):
    """items: [(id, image_path)] in order. Results are cached in .work/dupes.json per pair and file time, so a refresh is quick.
    Returns {later_id: (earlier_id, score)}."""
    import os, json
    cp = os.path.join(work, 'dupes.json'); cache = json.load(open(cp)) if os.path.exists(cp) else {}
    mt = {i: os.path.getmtime(p) for i, p in items if os.path.exists(p)}; feats = {}; res = {}; dirty = False
    def F(i, p):
        if i not in feats:
            im = cv2.imread(p); feats[i] = features(im) if im is not None else None
        return feats[i]
    paths = dict(items)
    ids = [i for i, _ in items if i in mt]
    for x in range(len(ids)):
        for y in range(x + 1, len(ids)):
            a, b = ids[x], ids[y]; key = f'{a}|{b}|{mt[a]:.0f}|{mt[b]:.0f}'
            if key not in cache:
                fa, fb = F(a, paths[a]), F(b, paths[b]); r = compare(fa, fb) if fa and fb else None
                cache[key] = None if r is None else dict(score=r['score'], overlap=r['overlap']); dirty = True
            r = cache[key]
            if r and r['score'] >= min_score and r['overlap'] >= min_overlap and b not in res: res[b] = (a, r['score'])
    if dirty:
        live = {k for k in cache if k.split('|')[0] in mt and k.split('|')[1] in mt}
        json.dump({k: v for k, v in cache.items() if k in live}, open(cp, 'w'))
    return res
