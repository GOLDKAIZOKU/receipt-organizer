"""Local web interface. Binds to 127.0.0.1 only (never reachable from the network); every request needs a random per-session token."""
import json, os, re, secrets, subprocess, sys, threading, webbrowser, argparse, urllib.parse, socket, time, hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from . import app as core, sysdeps
from . import __version__

HERE = os.path.dirname(__file__); TOKEN = secrets.token_hex(16)
STATE = dict(out=None, entities=['Personal'], job=dict(running=False, log=[], error=None))

ENT_FILE = sysdeps.ENT_FILE
def clean_ent(n):
    """A company name becomes a folder name: no slashes, no leading dots."""
    n = ''.join('-' if c in '/\\:\0' else c for c in str(n)).strip().lstrip('.').strip()
    return n[:60]

def entities():
    for f in (ENT_FILE, os.path.join(os.path.dirname(HERE), 'entities.txt')):
        try:
            v = [l.strip() for l in open(f, encoding='utf-8') if l.strip()]
            if v: return v
        except Exception: pass
    return ['Personal']

def view():
    p = os.path.join(STATE['out'], '.work', 'view.json')
    return json.load(open(p)) if os.path.exists(p) else []

def pick_folder(prompt): return sysdeps.pick_folder(prompt)

def start_job(inp, entity):
    j = STATE['job']
    if j['running']: return
    j.update(running=True, log=[], error=None)
    def go():
        try: core.run(inp, STATE['out'], entity, log=lambda m: j['log'].append(str(m)))
        except Exception as e: j['error'] = str(e)
        j['running'] = False
    threading.Thread(target=go, daemon=True).start()

def _code_stamp():
    """Newest modification time of the program's own files; used to tell when a newer version was installed while the app is still open."""
    t = 0
    for d in (HERE, os.path.join(HERE, 'ui')):
        for f in os.listdir(d):
            if f.endswith(('.py', '.html')): t = max(t, os.path.getmtime(os.path.join(d, f)))
    return t
CODE_AT_START = _code_stamp()

def start_reread():
    """Read every receipt again with the installed version (slow). Saved crops are used, so your rotations and joins are kept; your corrections still win."""
    import cv2, shutil
    j = STATE['job']
    if j['running']: return
    j.update(running=True, log=[], error=None)
    def go():
        try:
            w = _work(); rp = os.path.join(w, 'records.json'); saved = json.load(open(rp)); recs = saved['records']
            shutil.copy2(rp, os.path.join(w, 'records.before_reread_' + time.strftime('%Y%m%d_%H%M%S') + '.json'))
            model = saved.get('model')
            for n, r in enumerate(recs, 1):
                im = cv2.imread(os.path.join(w, r['id'] + '.jpg'))
                if im is None: j['log'].append(f"{r['id']}: image missing, kept as it was"); continue
                j['log'].append(f"[{n}/{len(recs)}] {r['id']}")
                r.update(core.read_fields(im, model, bool(model), lambda m: None))
            json.dump(saved, open(rp, 'w'), ensure_ascii=False, indent=1, default=str)
            core.finalize(STATE['out'], log=lambda m: j['log'].append(str(m)))
            j['log'].append(f'Done: {len(recs)} receipts read again.')
        except Exception as e: j['error'] = str(e)
        j['running'] = False
    threading.Thread(target=go, daemon=True).start()

def rotate(cid, deg):
    import cv2, shutil
    f = os.path.join(STATE['out'], '.work', os.path.basename(cid) + '.jpg')
    if not os.path.exists(f): return
    bak = f[:-4] + '.original.jpg'
    if not os.path.exists(bak): shutil.copy2(f, bak)                 # the first version is kept, nothing is lost
    im = cv2.imread(f); code = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}.get(deg % 360)
    if code is None: return
    cv2.imwrite(f, cv2.rotate(im, code), [cv2.IMWRITE_JPEG_QUALITY, 95])
    p = os.path.join(STATE['out'], 'corrections.json'); c = json.load(open(p)) if os.path.exists(p) else {}
    cur = c.setdefault(cid, {}); cur['rotation'] = (int(cur.get('rotation', 0)) + deg) % 360
    json.dump(c, open(p, 'w'), ensure_ascii=False, indent=1)
    core.finalize(STATE['out'], log=lambda m: None)

def _work(): return os.path.join(STATE['out'], '.work')

def manual_join(ids):
    """Stack pieces (already upright, in the order given) into one derived image and read it as one receipt.
    The pieces and the source scans are kept; the original records are saved so the join can be undone."""
    import cv2, numpy as np, shutil, datetime
    ids = [os.path.basename(i) for i in ids]
    if len(ids) < 2: raise ValueError('Pick at least two pieces.')
    w = _work(); rp = os.path.join(w, 'records.json'); saved = json.load(open(rp)); recs = saved['records']
    by = {r['id']: r for r in recs}
    if any(i not in by for i in ids): raise ValueError('One of the pieces was not found.')
    imgs = []
    for i in ids:
        im = cv2.imread(os.path.join(w, i + '.jpg'))
        if im is None: raise ValueError(f'Cannot read piece {i}.')
        imgs.append(im)
    W = int(np.median([im.shape[1] for im in imgs]))
    imgs = [cv2.resize(im, (W, max(1, int(im.shape[0] * W / im.shape[1]))), interpolation=cv2.INTER_CUBIC) if im.shape[1] != W else im for im in imgs]
    joined = np.vstack(imgs); nid = '__'.join(ids)
    if len(nid) > 120: nid = 'join_' + ids[0] + '_x' + str(len(ids))
    cp = os.path.join(w, nid + '.jpg'); cv2.imwrite(cp, joined, [cv2.IMWRITE_JPEG_QUALITY, 95])
    model = saved.get('model'); rec = core.read_fields(joined, model, bool(model), lambda m: None)
    srcs = []; boxes = []
    for i in ids:
        for x in by[i].get('sources', [by[i]['source_scan']]):
            if x not in srcs: srcs.append(x)
        boxes += by[i].get('boxes', [by[i]['box']])
    rec.update(id=nid, source_scan=srcs[0], sources=srcs, box=boxes[0], boxes=boxes, crop_flags=['JOINED', 'MANUAL_JOIN'], crop_path=cp)
    mj = os.path.join(w, 'manual_joins.json'); m = json.load(open(mj)) if os.path.exists(mj) else {}
    m[nid] = dict(pieces=ids, originals=[by[i] for i in ids], made=datetime.datetime.now().isoformat(timespec='seconds'))
    json.dump(m, open(mj, 'w'), ensure_ascii=False, indent=1, default=str)
    shutil.copy2(rp, os.path.join(w, 'records.before_join_' + time.strftime('%Y%m%d_%H%M%S') + '.json'))
    pos = min(recs.index(by[i]) for i in ids); recs = [r for r in recs if r['id'] not in ids]; recs.insert(pos, rec); saved['records'] = recs
    json.dump(saved, open(rp, 'w'), ensure_ascii=False, indent=1, default=str)
    core.finalize(STATE['out'], log=lambda m: None); return nid

def start_auto_unjoin(nid):
    """Undo a join the app made by itself. Its pieces were never saved on their own, so each one is cut again from its original scan
    (same box as before) and read again. The joined receipt is kept in .work/auto_unjoins.json and a records backup."""
    import cv2, shutil, datetime
    from . import segment, orient
    j = STATE['job']
    if j['running']: raise ValueError('Another job is still running.')
    w = _work(); rp = os.path.join(w, 'records.json'); saved = json.load(open(rp)); by = {r['id']: r for r in saved['records']}
    if nid not in by: raise ValueError('Receipt not found.')
    r0 = by[nid]; srcs = r0.get('sources', [r0['source_scan']]); bxs = r0.get('boxes', [r0['box']])
    if len(srcs) != len(bxs) or len(bxs) < 2: raise ValueError('This receipt cannot be split automatically. Use Re-crop on its scan instead.')
    parts = nid.split('__'); ids = parts if len(parts) == len(bxs) and not any(p_ in by for p_ in parts) else [f'{parts[0]}_u{k}' for k in range(1, len(bxs) + 1)]
    j.update(running=True, log=[], error=None)
    def go():
        try:
            model = saved.get('model'); new = []
            for k, (src, b, pid) in enumerate(zip(srcs, bxs, ids), 1):
                j['log'].append(f'[{k}/{len(bxs)}] cutting piece {k} again from {os.path.basename(src)}...')
                im = cv2.imread(src)
                if im is None: raise ValueError('The original scan cannot be opened (moved, renamed, or not downloaded from Google Drive?): ' + src)
                x0, y0, x1, y1 = [int(v) for v in b]; c = im[max(0, y0 - 30):y1 + 30, max(0, x0 - 30):x1 + 30].copy(); c, _a = segment.upright(c)
                if model: c = orient.fix(c, model)[0]
                cp = os.path.join(w, pid + '.jpg'); cv2.imwrite(cp, c, [cv2.IMWRITE_JPEG_QUALITY, 95])
                rec = core.read_fields(c, model, bool(model), lambda m: None)
                rec.update(id=pid, source_scan=src, sources=[src], box=[x0, y0, x1, y1], boxes=[[x0, y0, x1, y1]], crop_flags=['UNJOINED'], crop_path=cp); new.append(rec)
            cur = json.load(open(rp)); recs = cur['records']; pos = next(i for i, r in enumerate(recs) if r['id'] == nid)
            shutil.copy2(rp, os.path.join(w, 'records.before_unjoin_' + time.strftime('%Y%m%d_%H%M%S') + '.json'))
            ap = os.path.join(w, 'auto_unjoins.json'); a = json.load(open(ap)) if os.path.exists(ap) else {}
            a[nid] = dict(made=datetime.datetime.now().isoformat(timespec='seconds'), joined=recs[pos], pieces=ids); json.dump(a, open(ap, 'w'), ensure_ascii=False, indent=1, default=str)
            recs[pos:pos + 1] = new; json.dump(cur, open(rp, 'w'), ensure_ascii=False, indent=1, default=str)
            core.finalize(STATE['out'], log=lambda m: None); j['log'].append(f'Done: split into {len(new)} pieces.')
        except Exception as e: j['error'] = str(e)
        j['running'] = False
    threading.Thread(target=go, daemon=True).start()

def unjoin(nid):
    w = _work(); mj = os.path.join(w, 'manual_joins.json'); m = json.load(open(mj)) if os.path.exists(mj) else {}
    nid = os.path.basename(nid)
    if nid not in m: start_auto_unjoin(nid); return 'started'
    rp = os.path.join(w, 'records.json'); saved = json.load(open(rp)); recs = saved['records']
    pos = next(i for i, r in enumerate(recs) if r['id'] == nid); recs = [r for r in recs if r['id'] != nid]
    for k, o in enumerate(m[nid]['originals']): recs.insert(pos + k, o)
    saved['records'] = recs; json.dump(saved, open(rp, 'w'), ensure_ascii=False, indent=1, default=str)
    m.pop(nid); json.dump(m, open(mj, 'w'), ensure_ascii=False, indent=1, default=str)   # the joined image stays in .work, nothing is deleted
    core.finalize(STATE['out'], log=lambda m: None)

def _scan_of(cid):
    w = _work(); saved = json.load(open(os.path.join(w, 'records.json'))); by = {r['id']: r for r in saved['records']}
    if cid not in by: raise ValueError('Receipt not found.')
    return w, saved, by[cid]['source_scan']

def _editable(r, scan):
    """Pieces cut from this one scan only. Pieces joined with other scans are left alone here (undo the join first)."""
    return r['source_scan'] == scan and len(r.get('sources', [scan])) == 1 and '__' not in r['id']

def scan_info(cid):
    import cv2
    w, saved, scan = _scan_of(cid); im = cv2.imread(scan)
    if im is None: raise ValueError('The original scan cannot be opened (moved, renamed, or not downloaded from Google Drive?): ' + scan)
    boxes = []
    for r in saved['records']:
        if _editable(r, scan): boxes.append(dict(id=r['id'], box=r['box'], locked=False))
        elif scan in r.get('sources', [r['source_scan']]):
            srcs = r.get('sources', [r['source_scan']]); bxs = r.get('boxes', [r['box']])
            for s_, b_ in zip(srcs, bxs):
                if s_ == scan and len(srcs) == len(bxs): boxes.append(dict(id=r['id'], box=b_, locked=True))
    return dict(scan=os.path.basename(scan), w=im.shape[1], h=im.shape[0], boxes=boxes, can_undo=scan_was_recropped(cid))

def start_recrop(cid, boxes):
    """Replace the pieces cut from one scan with the boxes the user drew, and read each new piece. The old pieces are kept in
    .work/manual_crops.json and a records backup, and their images stay in .work, so nothing is lost. The original scan is only read."""
    import cv2, shutil, datetime
    from . import segment, orient
    j = STATE['job']
    if j['running']: raise ValueError('Another job is still running.')
    w, saved, scan = _scan_of(cid); im = cv2.imread(scan)
    if im is None: raise ValueError('The original scan cannot be opened: ' + scan)
    H, W = im.shape[:2]; clean = []
    for b in boxes:
        x0, y0, x1, y1 = [int(round(float(v))) for v in b]
        x0, x1 = sorted((max(0, min(W, x0)), max(0, min(W, x1)))); y0, y1 = sorted((max(0, min(H, y0)), max(0, min(H, y1))))
        if x1 - x0 >= 40 and y1 - y0 >= 40: clean.append([x0, y0, x1, y1])
    j.update(running=True, log=[], error=None)
    def go():
        try:
            model = saved.get('model'); stem = os.path.splitext(os.path.basename(scan))[0]; ts = time.strftime('%H%M%S'); new = []
            keep = {tuple(r['box']): r['id'] for r in saved['records'] if _editable(r, scan)}      # unchanged boxes: keep that receipt as it is
            for k, (x0, y0, x1, y1) in enumerate(clean, 1):
                if (x0, y0, x1, y1) in keep: new.append(keep[(x0, y0, x1, y1)]); j['log'].append(f'[{k}/{len(clean)}] unchanged, kept'); continue
                j['log'].append(f'[{k}/{len(clean)}] reading piece {k}...'); t0 = time.time()
                c = im[max(0, y0 - 10):y1 + 10, max(0, x0 - 10):x1 + 10].copy(); c, _a = segment.upright(c)
                if model: c = orient.fix(c, model)[0]
                nid = f'{stem}_m{ts}_{k}'; cp = os.path.join(w, nid + '.jpg'); cv2.imwrite(cp, c, [cv2.IMWRITE_JPEG_QUALITY, 95])
                rec = core.read_fields(c, model, bool(model), lambda m: None)
                rec.update(id=nid, source_scan=scan, sources=[scan], box=[x0, y0, x1, y1], boxes=[[x0, y0, x1, y1]], crop_flags=['MANUAL_CROP'], crop_path=cp)
                new.append(rec); j['log'].append(f'   {rec["merchant"] or "?"} | {rec["ocr_date"] or rec["ai_date"] or "no date"} | {rec["ocr_total"] or rec["ai_total"] or "?"}  ({time.time()-t0:.0f}s)')
            rp = os.path.join(w, 'records.json'); cur = json.load(open(rp)); recs = cur['records']          # re-read: nothing else may have changed meanwhile, but be safe
            byid = {r['id']: r for r in recs}; new = [byid[x] if isinstance(x, str) else x for x in new if not isinstance(x, str) or x in byid]
            kept = {r['id'] for r in new}; old = [r for r in recs if _editable(r, scan) and r['id'] not in kept]
            shutil.copy2(rp, os.path.join(w, 'records.before_recrop_' + time.strftime('%Y%m%d_%H%M%S') + '.json'))
            mp = os.path.join(w, 'manual_crops.json'); m = json.load(open(mp)) if os.path.exists(mp) else {}
            m.setdefault(scan, []).append(dict(made=datetime.datetime.now().isoformat(timespec='seconds'), originals=old, new=[r['id'] for r in new if r['id'] not in keep.values()]))
            json.dump(m, open(mp, 'w'), ensure_ascii=False, indent=1, default=str)
            pos = min([recs.index(r) for r in recs if _editable(r, scan)], default=len(recs)); recs = [r for r in recs if not _editable(r, scan)]
            recs[pos:pos] = new; cur['records'] = recs
            json.dump(cur, open(rp, 'w'), ensure_ascii=False, indent=1, default=str)
            core.finalize(STATE['out'], log=lambda m: None)
            j['log'].append(f'Done: this page now has {len(new)} receipt(s).')
        except Exception as e: j['error'] = str(e)
        j['running'] = False
    threading.Thread(target=go, daemon=True).start()
    return len(clean)

def uncrop(cid):
    """Undo the last re-crop of the scan this receipt came from: pieces it made are taken out, the pieces it removed come back."""
    import shutil
    w, saved, scan = _scan_of(cid); mp = os.path.join(w, 'manual_crops.json'); m = json.load(open(mp)) if os.path.exists(mp) else {}
    if not m.get(scan): raise ValueError('This page was not re-cropped by hand.')
    ev = m[scan].pop(); rp = os.path.join(w, 'records.json'); recs = saved['records']
    shutil.copy2(rp, os.path.join(w, 'records.before_uncrop_' + time.strftime('%Y%m%d_%H%M%S') + '.json'))
    pos = min([i for i, r in enumerate(recs) if r['id'] in ev['new']], default=len(recs))
    recs = [r for r in recs if r['id'] not in ev['new']]; pos = min(pos, len(recs)); recs[pos:pos] = ev['originals']; saved['records'] = recs
    json.dump(saved, open(rp, 'w'), ensure_ascii=False, indent=1, default=str)
    if not m[scan]: m.pop(scan)
    json.dump(m, open(mp, 'w'), ensure_ascii=False, indent=1, default=str)
    core.finalize(STATE['out'], log=lambda m: None)
    return [r['id'] for r in ev['originals']]

def scan_was_recropped(cid):
    try: w, saved, scan = _scan_of(cid)
    except Exception: return False
    mp = os.path.join(w, 'manual_crops.json'); return bool(os.path.exists(mp) and json.load(open(mp)).get(scan))

def delete(ids):
    """Take receipts out of the list. Nothing is destroyed: the record goes to .work/deleted.json (can be put back), the cut-out image stays
    in .work, and the original scan is never touched."""
    import datetime
    w = _work(); rp = os.path.join(w, 'records.json'); dp = os.path.join(w, 'deleted.json'); ids = {os.path.basename(i) for i in ids}
    with core._FLOCK:
        saved = json.load(open(rp)); gone = [r for r in saved['records'] if r['id'] in ids]
        if not gone: raise ValueError('Nothing to delete.')
        saved['records'] = [r for r in saved['records'] if r['id'] not in ids]
        d = json.load(open(dp)) if os.path.exists(dp) else []
        d += [dict(record=r, deleted=datetime.datetime.now().isoformat(timespec='seconds'), position=i) for i, r in enumerate(gone)]
        json.dump(d, open(dp, 'w'), ensure_ascii=False, indent=1, default=str); json.dump(saved, open(rp, 'w'), ensure_ascii=False, indent=1, default=str)
    core.finalize(STATE['out'], log=lambda m: None); return [r['id'] for r in gone]

def undelete(ids):
    w = _work(); rp = os.path.join(w, 'records.json'); dp = os.path.join(w, 'deleted.json'); ids = {os.path.basename(i) for i in ids}
    with core._FLOCK:
        d = json.load(open(dp)) if os.path.exists(dp) else []; back = [x['record'] for x in d if x['record']['id'] in ids]
        saved = json.load(open(rp)); have = {r['id'] for r in saved['records']}
        saved['records'] += [r for r in back if r['id'] not in have]
        json.dump([x for x in d if x['record']['id'] not in ids], open(dp, 'w'), ensure_ascii=False, indent=1, default=str)
        json.dump(saved, open(rp, 'w'), ensure_ascii=False, indent=1, default=str)
    core.finalize(STATE['out'], log=lambda m: None)

def pieces():
    """Every piece in the results folder, so the user can pick which ones belong together."""
    w = _work(); saved = json.load(open(os.path.join(w, 'records.json')))
    return [dict(id=r['id'], scan=os.path.basename(r['source_scan'])) for r in saved['records']]

def correct(body):
    p = os.path.join(STATE['out'], 'corrections.json'); c = json.load(open(p)) if os.path.exists(p) else {}
    cur = c.setdefault(body['id'], {})
    for k in ('date', 'total', 'merchant', 'entity', 'category', 'subcategory', 'crop_ok', 'not_duplicate', 'tax_tag', 'hold', 'not_slip', 'kind', 'property'):
        if k in body and body[k] not in (None, ''): cur[k] = clean_ent(body[k]) if k == 'entity' else body[k]
    if body.get('kind') == 'bill':                              # marked as a bill: it becomes a utility bill right away, with the type read from the page
        sub = None
        try:                                                    # read the page: which utility it is, and its account number (to learn / match the property)
            import cv2
            from . import fields as F
            rp = os.path.join(_work(), 'records.json'); saved = json.load(open(rp)); rec = next(r for r in saved['records'] if r['id'] == body['id'])
            if not rec.get('bill_text'):
                im = cv2.imread(os.path.join(_work(), body['id'] + '.jpg'))
                if im is not None: rec['bill_text'] = core.ob.text(im)
            ok, name, sub = F.utility_bill([rec.get('bill_text') or '']); sub = sub if ok else None
            rec['doc_kind'] = 'bill'; rec['bill_sub'] = sub
            if name and (not rec.get('merchant') or rec.get('merchant_source') in (None, 'unmatched-first-line', 'card-slip') or re.search(r'SALINAN|PEMBAYAR', rec.get('merchant') or '', re.I)):
                rec['merchant'] = name; rec['merchant_source'] = 'header'
            json.dump(saved, open(rp, 'w'), ensure_ascii=False, indent=1, default=str)
        except Exception: pass
        if cur.get('category') != 'Utilities': cur['category'] = 'Utilities'; cur['subcategory'] = body.get('subcategory') or sub or 'Other bills'
    if body.get('kind') == 'receipt' and cur.get('category') == 'Utilities': cur.pop('category', None); cur.pop('subcategory', None)
    if body.get('not_slip_of'): cur['not_slip_of'] = sorted(set(cur.get('not_slip_of', [])) | {str(body['not_slip_of'])})   # 'not the same payment'
    json.dump(c, open(p, 'w'), ensure_ascii=False, indent=1)
    if body.get('property'):                                    # remember: this bill's account number belongs to that property
        try:
            from . import bills
            rec = next(r for r in json.load(open(os.path.join(_work(), 'records.json')))['records'] if r['id'] == body['id'])
            row = next(r for r in view() if r['id'] == body['id']); bills.learn(row.get('drive_type'), rec.get('bill_text'), body['property'])
        except Exception: pass
    core.finalize(STATE['out'], log=lambda m: None)

def field_crop(cid, kind):
    """JPEG of the receipt line that holds the current date or total, or None. Lines are located on the current (possibly rotated) image, so nothing is stored."""
    import cv2, re, datetime
    from . import ocr_backend as ob, fields as F
    f = os.path.join(STATE['out'], '.work', cid + '.jpg')
    row = next((r for r in view() if r['id'] == cid), None)
    if not row or not os.path.exists(f): return None
    img = cv2.imread(f)
    if img is None: return None
    want = None
    if kind == 'date' and row.get('date'): want = datetime.date.fromisoformat(row['date'])
    if kind == 'total' and row.get('total_myr') is not None: want = '%.2f' % float(row['total_myr'])
    if want is None: return None
    hit = None
    for r in ob.rows(img):
        t = r['text']
        if kind == 'total':
            if want in t.replace(',', ''): hit = r
        else:
            for _k, a, b, c, _l in F.find_dates(t):
                if not all(isinstance(v, int) for v in (a, b, c)): continue
                y = c + 2000 if c < 100 else c
                if (want.day, want.month, want.year) in {(a, b, y), (b, a, y), (c if c > 31 else a, b, a if c > 31 else y)}: hit = r
        if hit is r and kind == 'date': break
    if not hit: return None
    H, W = img.shape[:2]; h = max(hit['y1'] - hit['y0'], 18); a = int(max(0, hit['y0'] - .5 * h)); b = int(min(H, hit['y1'] + .5 * h))
    c = img[a:b]; k = max(1.0, 900 / max(c.shape[1], 1)); c = cv2.resize(c, None, fx=k, fy=k, interpolation=cv2.INTER_CUBIC)
    ok, buf = cv2.imencode('.jpg', c, [cv2.IMWRITE_JPEG_QUALITY, 90]); return buf.tobytes() if ok else None

LOCAL = ('127.0.0.1', '::1', '::ffff:127.0.0.1')
PHONE = dict(on=False, port=None, pin=None, sessions=set(), fails={})   # phone mode: opt-in, PIN protected, same Wi-Fi / private network only
BLOCKED_REMOTE = ('/api/export', '/api/pick-folder', '/api/run', '/api/open', '/api/set-output', '/api/entities', '/api/phone', '/api/join', '/api/unjoin', '/api/refresh', '/api/reread', '/api/recrop', '/api/uncrop', '/api/report', '/api/update-start', '/api/restart', '/api/delete', '/api/undelete', '/api/bills-dir', '/api/bills-learn', '/api/scan-info', '/scan')
LOGIN = '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>单据整理</title>
<style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#eef1f4;font:16px -apple-system,"PingFang SC",sans-serif;color:#17212b}
form{background:#fff;border:1px solid #dfe5ea;border-radius:16px;padding:28px;width:min(340px,90vw);display:grid;gap:14px}h1{font-size:18px;margin:0}
input{font-size:22px;letter-spacing:.3em;text-align:center;padding:12px;border:1px solid #dfe5ea;border-radius:10px}button{font-size:16px;padding:12px;border:0;border-radius:10px;background:#0e6b75;color:#fff;font-weight:600}
p{margin:0;color:#667482;font-size:13px}.e{color:#b3433b}</style></head><body><form method="post" action="/login"><h1>单据整理 · Receipt Organizer</h1><p>请输入电脑上“设置”里显示的 6 位 PIN。<br>Enter the 6-digit PIN shown in Settings on the computer.</p>
<input name="pin" inputmode="numeric" autocomplete="one-time-code" maxlength="6" autofocus>__MSG__<button>进入 · Enter</button></form></body></html>'''

def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(('10.255.255.255', 1)); ip = s.getsockname()[0]; s.close(); return ip
    except Exception: return None

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, body, ctype='application/json'):
        b = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False, default=str).encode()
        self.send_response(code); self.send_header('Content-Type', ctype); self.send_header('Content-Length', str(len(b))); self.send_header('Cache-Control', 'no-store'); self.end_headers(); self.wfile.write(b)
    def _remote(self): return self.client_address[0] not in LOCAL
    def _cookie(self):
        for part in (self.headers.get('Cookie') or '').split(';'):
            k, _, v = part.strip().partition('=')
            if k == 'ro_s': return v
        return ''
    def _ok(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        tok = q.get('t', [''])[0] == TOKEN or self.headers.get('X-Token') == TOKEN
        if not self._remote(): return tok
        return tok and PHONE['on'] and self._cookie() in PHONE['sessions']
    def _login_page(self, msg='', code=200):
        return self._send(code, LOGIN.replace('__MSG__', msg).encode(), 'text/html; charset=utf-8')
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if self._remote() and not PHONE['on']: return self._send(403, {'error': 'phone mode is off'})
        if u.path == '/' and self._remote() and self._cookie() not in PHONE['sessions']: return self._login_page()
        if u.path == '/':
            html = open(os.path.join(HERE, 'ui', 'index.html'), encoding='utf-8').read().replace('__TOKEN__', TOKEN)
            return self._send(200, html.encode(), 'text/html; charset=utf-8')
        if not self._ok(): return self._send(403, {'error': 'forbidden'})
        if u.path == '/api/records': return self._send(200, dict(rows=view(), out=STATE['out'], entities=entities(), job=STATE['job'], stale=_code_stamp() > CODE_AT_START + 1))
        if u.path == '/api/pieces': return self._send(200, {'pieces': pieces()})
        if u.path == '/api/progress': return self._send(200, STATE['job'])
        if u.path == '/api/phone-info' and not self._remote():
            ip = lan_ip(); return self._send(200, dict(on=PHONE['on'], pin=PHONE['pin'] if PHONE['on'] else None, url=f"http://{ip}:{PHONE['port']}/" if PHONE['on'] and ip else None, wanted=bool(cfg().get('phone'))))
        if u.path == '/api/field':
            q = urllib.parse.parse_qs(u.query); cid = os.path.basename(q.get('id', [''])[0]); k = q.get('k', [''])[0]
            if k in ('date', 'total'):
                try: data = field_crop(cid, k)
                except Exception: data = None
                if data: return self._send(200, data, 'image/jpeg')
            return self._send(404, {'error': 'not found'})
        if u.path == '/api/update':
            from . import updater
            q = urllib.parse.parse_qs(u.query)
            if self._remote(): return self._send(200, dict(updater.info(), available=False))
            return self._send(200, updater.check(force=q.get('force', ['0'])[0] == '1') if not updater.STATE['busy'] else updater.info())
        if u.path == '/api/bills-info':
            from . import bills
            r = bills.root()
            try: tfs = sorted(d for d in os.listdir(r) if os.path.isdir(os.path.join(r, d)) and not d.startswith('.')) if r else []
            except Exception: tfs = []
            return self._send(200, dict(bills.summary(), places={t: bills.places(t) for t in tfs}))
        if u.path == '/api/scan-info':
            try: return self._send(200, scan_info(os.path.basename(urllib.parse.parse_qs(u.query).get('id', [''])[0])))
            except Exception as e: return self._send(400, {'error': str(e)})
        if u.path == '/scan':
            try: _w, _s, scan = _scan_of(os.path.basename(urllib.parse.parse_qs(u.query).get('id', [''])[0])); return self._send(200, open(scan, 'rb').read(), 'image/png' if scan.lower().endswith('.png') else 'image/jpeg')
            except Exception as e: return self._send(404, {'error': str(e)})
        if u.path.startswith('/crop/'):
            cid = os.path.basename(urllib.parse.unquote(u.path[6:])); cid = cid[:-4] if cid.endswith('.jpg') else cid   # names may have spaces etc.
            f = os.path.join(STATE['out'], '.work', cid + '.jpg')
            if os.path.exists(f): return self._send(200, open(f, 'rb').read(), 'image/jpeg')
        self._send(404, {'error': 'not found'})
    def do_POST(self):
        if self._remote() and self.path.split('?')[0] == '/login':
            if not PHONE['on']: return self._send(403, {'error': 'phone mode is off'})
            ip = self.client_address[0]; n, until = PHONE['fails'].get(ip, (0, 0))
            if time.time() < until: return self._login_page('<p class="e">尝试次数过多,请 5 分钟后再试。 Too many tries; wait 5 minutes.</p>', 429)
            raw = self.rfile.read(int(self.headers.get('Content-Length', 0))).decode(); pin = urllib.parse.parse_qs(raw).get('pin', [''])[0].strip()
            if PHONE['pin'] and hmac.compare_digest(pin, PHONE['pin']):
                PHONE['fails'].pop(ip, None); sid = secrets.token_urlsafe(24); PHONE['sessions'].add(sid)
                self.send_response(303); self.send_header('Set-Cookie', f'ro_s={sid}; HttpOnly; SameSite=Strict; Path=/; Max-Age=2592000'); self.send_header('Location', '/'); self.end_headers(); return
            n += 1; PHONE['fails'][ip] = (n, time.time() + 300 if n >= 5 else 0)
            return self._login_page('<p class="e">PIN 不对。 Wrong PIN.</p>', 401)
        if not self._ok(): return self._send(403, {'error': 'forbidden'})
        if self._remote() and self.path.split('?')[0] in BLOCKED_REMOTE: return self._send(403, {'error': 'only available on the computer'})
        n = int(self.headers.get('Content-Length', 0)); body = json.loads(self.rfile.read(n) or b'{}'); p = self.path.split('?')[0]
        if p == '/api/pick-folder': return self._send(200, {'path': pick_folder(body.get('prompt', 'Choose a folder'))})
        if p == '/api/run': start_job(body['input'], body.get('entity', 'Personal')); return self._send(200, {'started': True})
        if p == '/api/refresh':
            try:
                try: core.upgrade_readings(STATE['out'], log=lambda m: None)
                except Exception: pass
                core.finalize(STATE['out'], log=lambda m: None); return self._send(200, {'rows': view(), 'stale': _code_stamp() > CODE_AT_START + 1})
            except Exception as e: return self._send(400, {'error': str(e)})
        if p == '/api/reread': start_reread(); return self._send(200, {'started': True})
        if p == '/api/join':
            try: nid = manual_join(body.get('ids', [])); return self._send(200, {'rows': view(), 'id': nid})
            except Exception as e: return self._send(400, {'error': str(e)})
        if p == '/api/unjoin':
            try: res = unjoin(body.get('id', '')); return self._send(200, {'started': True} if res == 'started' else {'rows': view()})
            except Exception as e: return self._send(400, {'error': str(e)})
        if p == '/api/recrop':
            try: n = start_recrop(os.path.basename(body.get('id', '')), body.get('boxes', [])); return self._send(200, {'started': True, 'n': n})
            except Exception as e: return self._send(400, {'error': str(e)})
        if p == '/api/uncrop':
            try: back = uncrop(os.path.basename(body.get('id', ''))); return self._send(200, {'rows': view(), 'ids': back})
            except Exception as e: return self._send(400, {'error': str(e)})
        if p == '/api/bills-dir':
            from . import bills
            f = pick_folder('Choose your utility bills folder')
            if f: c = cfg(); c['bills_dir'] = f.rstrip('/'); save_cfg(c); learn_bills()
            return self._send(200, bills.summary())
        if p == '/api/bills-learn':
            from . import bills
            learn_bills(); return self._send(200, bills.summary())
        if p == '/api/update-start':
            from . import updater
            try: return self._send(200, updater.start())
            except Exception as e: return self._send(400, {'error': str(e)})
        if p == '/api/restart':
            from . import updater
            updater.restart(); return self._send(200, {'ok': True})
        if p == '/api/report':
            try:
                from . import report
                path, pdf = report.make(STATE['out'], view(), body.get('entity') or None, body.get('start') or None, body.get('end') or None, 'en' if body.get('lang') == 'en' else 'zh')
                sysdeps.open_path(path)
                return self._send(200, {'path': path, 'pdf': pdf})
            except Exception as e: return self._send(400, {'error': str(e)})
        if p == '/api/delete':
            try: gone = delete(body.get('ids', [])); return self._send(200, {'rows': view(), 'ids': gone})
            except Exception as e: return self._send(400, {'error': str(e)})
        if p == '/api/undelete':
            try: undelete(body.get('ids', [])); return self._send(200, {'rows': view()})
            except Exception as e: return self._send(400, {'error': str(e)})
        if p == '/api/rotate': rotate(body['id'], int(body['deg'])); return self._send(200, {'rows': view()})
        if p == '/api/correct': correct(body); return self._send(200, {'rows': view()})
        if p == '/api/entities':
            names = []
            for n in body.get('names', []):
                n = clean_ent(n)
                if n and n not in names: names.append(n)
            if not names: names = ['Personal']
            os.makedirs(os.path.dirname(ENT_FILE), exist_ok=True); open(ENT_FILE, 'w', encoding='utf-8').write('\n'.join(names) + '\n')
            return self._send(200, {'entities': names})
        if p == '/api/set-output':
            d = os.path.abspath(body['path']); os.makedirs(d, exist_ok=True); STATE['out'] = d; remember(d); return self._send(200, {'out': d})
        if p == '/api/phone':
            c = cfg(); c['phone'] = bool(body.get('on'))
            if c['phone'] and not c.get('pin'): c['pin'] = ''.join(secrets.choice('0123456789') for _ in range(6))
            if body.get('newpin'): c['pin'] = ''.join(secrets.choice('0123456789') for _ in range(6)); PHONE['sessions'].clear()
            save_cfg(c); PHONE['pin'] = c.get('pin'); return self._send(200, {'wanted': c['phone'], 'pin': c.get('pin'), 'restart': c['phone'] and not PHONE['on']})
        if p == '/api/export':
            from . import export
            try: d, made = export.build(STATE['out'])
            except Exception as e: return self._send(200, {'error': str(e)})
            sysdeps.open_path(d)
            return self._send(200, {'dir': d, 'files': [os.path.basename(m) for m in made]})
        if p == '/api/open': sysdeps.open_path(os.path.join(STATE['out'], body.get('sub', ''))); return self._send(200, {})
        self._send(404, {'error': 'not found'})

CFG = sysdeps.CFG
def cfg():
    try: return json.load(open(CFG))
    except Exception: return {}
def save_cfg(c):
    try:
        os.makedirs(os.path.dirname(CFG), exist_ok=True); json.dump(c, open(CFG, 'w')); os.chmod(CFG, 0o600)
    except Exception: pass
def remembered(): return cfg().get('out')
def remember(out): c = cfg(); c['out'] = out; save_cfg(c)

def serve(out, port=0):
    STATE['out'] = os.path.abspath(out); os.makedirs(STATE['out'], exist_ok=True)
    srv = ThreadingHTTPServer(('127.0.0.1', port), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
    c = cfg()
    if c.get('phone') and c.get('pin'):          # opt-in only; off by default
        try: ps = ThreadingHTTPServer(('0.0.0.0', int(c.get('phone_port', 8765))), H)
        except OSError: ps = ThreadingHTTPServer(('0.0.0.0', 0), H)
        PHONE.update(on=True, port=ps.server_address[1], pin=c['pin']); threading.Thread(target=ps.serve_forever, daemon=True).start()
    learn_bills()
    return srv.server_address[1]

def learn_bills():
    """In the background: learn the properties' account numbers from the bills folder, then refile so confirmed bills are copied there."""
    from . import bills
    if bills.STATUS['running']: return
    def go():
        try:
            if os.path.exists(os.path.join(_work(), 'records.json')): core.upgrade_readings(STATE['out'], log=lambda m: None)   # older readings: bank slips / bills
        except Exception: pass
        bills.build_index(core.ob.text)
        try:
            if os.path.exists(os.path.join(_work(), 'records.json')): core.finalize(STATE['out'], log=lambda m: None)
        except Exception: pass
    threading.Thread(target=go, daemon=True).start()

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--output', default=os.path.expanduser('~/Receipt Organizer')); ap.add_argument('--port', type=int, default=0); a = ap.parse_args()
    STATE['out'] = os.path.abspath(a.output); os.makedirs(STATE['out'], exist_ok=True)
    srv = ThreadingHTTPServer(('127.0.0.1', a.port), H); port = srv.server_address[1]
    print(f'Receipt Organizer running at http://127.0.0.1:{port}  (this computer only). Close this window to stop.', flush=True)
    webbrowser.open(f'http://127.0.0.1:{port}/'); srv.serve_forever()

if __name__ == '__main__': main()
