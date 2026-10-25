"""Utility bills -> the user's own bills folder (e.g. Google Drive "Utilities Bill"), laid out as   <type>/<property>/<year>/<code> <month> <year>.jpg
The property is recognised from the account number on the bill, learned from the bills already in that folder and from the user's own choices.
Only ever ADDS files there (and moves files this app itself put there when a bill is corrected). Nothing in that folder is deleted or overwritten."""
import json, os, re, shutil, threading, time, collections
from . import sysdeps

APPDIR = sysdeps.APPDIR
CFG = os.path.join(APPDIR, 'config.json'); INDEX = os.path.join(APPDIR, 'bills_index.json'); LEARNED = os.path.join(APPDIR, 'bills_learned.json')
MONTHS = ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october', 'november', 'december']
EXTS = ('.pdf', '.png', '.jpg', '.jpeg')
STATUS = dict(running=False, files=0, done=0, error=None, at=None)

def _load(p, d):
    try: return json.load(open(p))
    except Exception: return d
def _save(p, v):
    os.makedirs(os.path.dirname(p), exist_ok=True); tmp = p + '.tmp'; json.dump(v, open(tmp, 'w'), ensure_ascii=False, indent=1); os.replace(tmp, p)
def root():
    r = _load(CFG, {}).get('bills_dir')            # chosen in Settings
    return r if r and os.path.isdir(r) else None

# ---------- which top folder a bill goes to ----------
def type_folder(sub, merchant):
    m = (merchant or '').lower()
    want = {'Electricity': 'Electric', 'Water': 'Water', 'Sewerage': 'IWK', 'Assessment & land tax': 'Cukai Tanah', 'Gas': 'Gas'}.get(sub)
    if not want:
        if 'unifi' in m: want = 'UNIFI'
        elif 'maxis' in m: want = 'MAXIS'
        elif merchant and sub in ('Internet & phone', 'TV & streaming'): want = merchant
        else: want = 'Other bills'
    r = root()
    if r:
        try:
            for d in os.listdir(r):
                if d.lower() == want.lower() and os.path.isdir(os.path.join(r, d)): return d       # use the user's own spelling
        except Exception: pass
    return want

def access_error():
    """None if the bills folder can be read, else why not (macOS privacy settings can block a Google Drive folder)."""
    r = root()
    if not r: return None
    try: os.listdir(r); return None
    except PermissionError: return 'permission'
    except Exception as e: return str(e)

def places(tf):
    """Property folders under one type folder (year folders are not properties)."""
    r = root()
    if not r or not os.path.isdir(os.path.join(r, tf)): return []
    try: os.listdir(os.path.join(r, tf))
    except Exception: return []
    return sorted(d for d in os.listdir(os.path.join(r, tf)) if os.path.isdir(os.path.join(r, tf, d)) and not d.startswith('.') and not re.fullmatch(r'(19|20)\d\d', d))

# ---------- account numbers: what identifies a property ----------
def keys(text):
    t = text or ''; k = set()
    if re.search(r'TENAGA|\bTNB\b', t, re.I):
        for m in re.finditer(r'(?<![\d(])(2[0-2]\d{8})(?:\d\d|XX|xx)?(?!\d)', t): k.add('tnb:' + m.group(1))   # TNB account: 12 digits, the first 10 are fixed
    for m in re.finditer(r'(?<!\d)\S{2}\s*-\s*(\d{6})\s*-\s*\d{2}(?!\d)', t): k.add('acc:' + m.group(1))       # 01-277398-77 (PAIP / water)
    for l in t.splitlines():
        if re.search(r'AKAUN|ACCOUNT|HAKMILIK|NO\.?\s*LOT', l, re.I):
            for d in re.findall(r'\d[\d\s\-]{6,}\d', l):
                d = re.sub(r'\D', '', d)
                if 7 <= len(d) <= 16: k.add('num:' + d)
    return k

def _text_of(path, ocr):
    if path.lower().endswith('.pdf'):
        try:                                           # Mac: built-in PDFKit
            from Quartz import PDFDocument
            from Foundation import NSURL
            doc = PDFDocument.alloc().initWithURL_(NSURL.fileURLWithPath_(path))
            return str(doc.string() or '') if doc else ''
        except ImportError: pass
        except Exception: return ''
        try:                                           # Windows: pypdf
            from pypdf import PdfReader
            return '\n'.join((pg.extract_text() or '') for pg in PdfReader(path).pages[:3])
        except Exception: return ''
    try:
        import cv2
        im = cv2.imread(path)
        return ocr(im) if im is not None else ''
    except Exception: return ''

def _code(folder_files, prop):
    """The short name the user puts in front of file names in this folder, e.g. 'hq' in 'hq april 2026.pdf'."""
    c = collections.Counter()
    for f in folder_files:
        w = re.split(r'[\s_\-]+', os.path.splitext(f)[0].strip())
        if w and w[0] and not re.fullmatch(r'\d+|img\d*|image|bil|billing|' + '|'.join(MONTHS) + '|' + '|'.join(x[:3] for x in MONTHS), w[0], re.I): c[w[0]] += 1
    if c:
        best, n = c.most_common(1)[0]
        if n >= 2: return best
    return prop

def build_index(ocr, per_folder=3, log=lambda m: None):
    """Learn each property's account numbers from its newest few bills. Incremental: files already read are not read again.
    Reading a file that is only in the cloud makes Google Drive download it."""
    r = root()
    if not r or access_error(): return
    idx = _load(INDEX, {}); idx.setdefault('files', {}); STATUS.update(running=True, error=None, done=0)
    try:
        jobs = []; layout = {}
        for tf in sorted(os.listdir(r)):
            if not os.path.isdir(os.path.join(r, tf)) or tf.startswith('.'): continue
            for p in places(tf):
                allf = []
                for dp, dn, fn in os.walk(os.path.join(r, tf, p)):
                    for f in fn:
                        if f.lower().endswith(EXTS) and not f.startswith('.'): allf.append(os.path.join(dp, f))
                allf.sort(key=lambda x: os.path.getmtime(x), reverse=True)
                layout[f'{tf}/{p}'] = dict(code=_code([os.path.basename(x) for x in allf], p), years=any(re.fullmatch(r'(19|20)\d\d', d) for d in os.listdir(os.path.join(r, tf, p))))
                jobs += [(tf, p, x) for x in allf[:per_folder] if x not in idx['files']]
        STATUS['files'] = len(jobs)
        for n, (tf, p, x) in enumerate(jobs, 1):
            idx['files'][x] = dict(place=f'{tf}/{p}', keys=sorted(keys(_text_of(x, ocr))), at=time.time()); STATUS['done'] = n
            if n % 5 == 0: idx['layout'] = layout; _save(INDEX, idx)
        idx['layout'] = layout; _save(INDEX, idx); STATUS['at'] = time.strftime('%Y-%m-%d %H:%M')
    except Exception as e: STATUS['error'] = str(e)
    STATUS['running'] = False

def start_index(ocr):
    if STATUS['running'] or not root(): return
    threading.Thread(target=build_index, args=(ocr,), daemon=True).start()

def summary():
    idx = _load(INDEX, {}); n = collections.Counter(v['place'] for v in idx.get('files', {}).values() if v.get('keys'))
    return dict(root=root(), places=len(idx.get('layout', {})), learned=len(n), status=STATUS, access=access_error())

# ---------- which property a bill belongs to ----------
def resolve(tf, text, corr):
    """-> (property, how) ; how: 'user' / 'learned' / 'account' / 'name' / None"""
    if corr.get('property'): return corr['property'], 'user'
    k = keys(text); props = places(tf)
    lk = _load(LEARNED, {}).get(tf, {})
    hit = {lk[x] for x in k if x in lk and lk[x] in props}
    if len(hit) == 1: return hit.pop(), 'learned'
    idx = _load(INDEX, {})
    votes = collections.Counter(v['place'].split('/', 1)[1] for v in idx.get('files', {}).values() if v['place'].split('/', 1)[0] == tf and k & set(v['keys']))
    if votes:
        (best, a), *rest = votes.most_common(2) + [(None, 0)]
        if a > rest[0][1] and best in props: return best, 'account'
    low = re.sub(r'\s+', ' ', (text or '').lower())
    named = [p for p in props if re.search(r'(daerah|mukim)\W+(\d+\W+)?' + re.escape(p.lower()) + r'\b', low)]          # land tax: "DAERAH 06 <district>"
    if not named: named = [p for p in props if len(p.split()) >= 2 and re.search(r'\b' + re.escape(p.lower()) + r'\b', low)]   # e.g. a two-word street name; one-word names are too common in addresses
    if len(named) == 1: return named[0], 'name'
    return None, None

def learn(tf, text, prop):
    if not prop: return
    lk = _load(LEARNED, {}); m = lk.setdefault(tf, {})
    for x in keys(text): m[x] = prop
    _save(LEARNED, lk)

# ---------- copy into the bills folder ----------
def target(tf, prop, d, ext='.jpg', text=''):
    r = root()
    if not (r and prop and d): return None
    if tf.lower() == 'cukai tanah':                                                  # land tax files are named by lot number: "<lot> <year>.png"
        lot = re.search(r'\bLOT\W{0,3}0*(\d{2,7})', text or '', re.I)
        if lot: return os.path.join(r, tf, prop, f'{lot.group(1)} {d.year}{ext}')
    lay = _load(INDEX, {}).get('layout', {}).get(f'{tf}/{prop}', {}); code = lay.get('code') or prop
    base = os.path.join(r, tf, prop)
    yearly = lay.get('years', True) if os.path.isdir(base) else True
    folder = os.path.join(base, str(d.year)) if yearly else base
    return os.path.join(folder, f'{code} {MONTHS[d.month - 1]} {d.year}{ext}')

def sync(work, items):
    """items: [(id, source image, target path or None)]. Copies new bills, moves the ones this app placed earlier when the target changed.
    Returns {id: path placed}. Never overwrites: an existing different file gets ' (2)', ' (3)' ..."""
    if not root(): return {}
    lp = os.path.join(work, 'bills_placed.json'); placed = _load(lp, {}); out = {}
    for cid, src, dst in items:
        old = placed.get(cid)
        if not dst:
            if old and os.path.exists(old): out[cid] = old
            continue
        if old and os.path.exists(old) and os.path.dirname(old) == os.path.dirname(dst) and re.fullmatch(re.escape(os.path.splitext(dst)[0]) + r'( \(\d+\))?' + re.escape(os.path.splitext(dst)[1]), old):
            out[cid] = old; continue                                       # already there (possibly as 'name (2)')
        p = dst; n = 2
        while os.path.exists(p) and p != old: p = f'{os.path.splitext(dst)[0]} ({n}){os.path.splitext(dst)[1]}'; n += 1
        os.makedirs(os.path.dirname(p), exist_ok=True)
        if old and os.path.exists(old): shutil.move(old, p)
        else: shutil.copy2(src, p)
        placed[cid] = p; out[cid] = p
    _save(lp, placed)
    return out
