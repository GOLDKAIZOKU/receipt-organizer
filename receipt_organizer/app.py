"""Receipt & Invoice Organizer - local test version (Mac first).
 scans folder -> find/crop/rotate each receipt -> read merchant/date/total (Apple Vision + your local Ollama as second reader)
 -> name + file into  <output>/Organised Receipts/<entity>/<year>/<month>/  or  <output>/Needs Review/<reason>/
Originals are only ever READ. Nothing is deleted. Your corrections in corrections.json always win over OCR/AI."""
import argparse, csv, datetime, json, os, re, shutil, statistics, sys, threading, time
import cv2
import numpy as np
from . import bills as BL, dupes,  ocr_backend as ob, segment, fields as F, ollama_reader as OR, catalog, stitch, orient

EXTS = ('.jpg', '.jpeg', '.png')

def read_fields(crop, model, use_ai, log):
    texts = F.ocr_variants(crop)
    mer, src = F.pick_merchant(texts)
    if src in (None, 'unmatched-first-line'):                   # name not recognised: try the top of the receipt again with faded ink boosted
        m2, s2 = F.pick_merchant(F.header_variants(crop))
        if s2 in ('header', 'body'): mer, src = m2, s2
    slip, sname = F.card_slip(texts)
    if slip and sname: mer, src = sname, ('header' if sname in {n for n, _ in F.MERCH} else 'card-slip')   # bank slip: the shop is on the line under the bank
    bill, bname, bsub = (False, None, None) if slip else F.utility_bill(texts)
    if bill and bname: mer, src = bname, 'header'
    dt, dc, dev, dnotes = F.pick_date(texts, mer); tot, tc, tev = F.pick_total(texts)
    notes = list(dnotes)
    ti = F.total_from_items(texts, tot)
    if ti: tot, tc = ti[0], 0.9; notes.append(ti[1])
    tot2, n = F.repair_total(tot, texts)
    if n: notes.append(n)
    if tot2 != tot: tot, tc = tot2, 0.4
    rec = dict(merchant=mer, merchant_source=src, ocr_date=dt, ocr_date_conf=dc, ocr_total=tot, ocr_total_conf=tc, notes=notes,
               doc_no=F.doc_no(texts), sst_id=F.sst(texts), ai_date=None, ai_total=None, ai_evidence=[], card_slip=slip, slip_checked=SLIPV, doc_kind='bill' if bill else 'receipt', bill_sub=bsub, bill_checked=True, fields_v=FIELDSV, bill_text=texts[0] if bill else None)
    need_d = True   # the date is the key field: always get a second reading (OCR variants can agree on a wrong day)
    need_t = tot is None or tc < .8
    if use_ai and (need_d or need_t):
        r = OR.read_candidate_lines(crop, model, need_d, need_t)
        rec['ai_evidence'] = r['date'] + r['total']
        if r['date']:
            adt, adc, _, an = F.pick_date(r['date'], mer); rec['ai_date'] = adt
        if r['total']:
            best = None
            for t in r['total']:
                if F.BADT.search(t): continue
                w = max([wt for p, wt in F.TOTK if re.search(p, t, re.I)] or [0]); a = F.amounts(t)
                if w >= 3 and a and (best is None or w >= best[0]): best = (w, max(a))
            rec['ai_total'] = best[1] if best else None
    return rec

def decide(rec, corr, med):
    """Combine readers. Disagreement is never resolved silently; user corrections always win."""
    st = {}; flags = []
    o, a = rec['ocr_date'], rec['ai_date']
    if corr.get('date'): rec['date'] = datetime.date.fromisoformat(corr['date']); st['date'] = 'user confirmed'
    elif o and a and o == a: rec['date'] = o; st['date'] = 'OCR+AI agree'
    elif o and a: rec['date'] = None; st['date'] = f'DISAGREE ocr {o} / ai {a}'; flags.append('Confirm date')
    elif a: rec['date'] = a; st['date'] = 'AI only'; flags.append('Confirm date')
    elif o: rec['date'] = o; st['date'] = 'OCR only' + ('' if rec['ocr_date_conf'] >= .5 else ' (low confidence)'); \
        flags += [] if rec['ocr_date_conf'] >= .5 else ['Confirm date']      # corrections so far: OCR-only dates were right 15 of 15 times
    else: rec['date'] = None; st['date'] = 'unreadable'; flags.append('Date missing')
    d = rec['date']
    if d and not corr.get('date') and med and abs((d - med).days) > 75 and st['date'] != 'OCR+AI agree':   # both readers agreeing is enough (7 of 7 such dates were right)
        st['date'] += f' | far from the rest of this batch ({med})'; flags.append('Confirm date')
    o, a = rec['ocr_total'], rec['ai_total']
    if corr.get('total') is not None: rec['total'] = float(corr['total']); st['total'] = 'user confirmed'
    elif o and a and abs(o - a) < .005: rec['total'] = o; st['total'] = 'OCR+AI agree'
    elif o and a: rec['total'] = None; st['total'] = f'DISAGREE ocr {o} / ai {a}'; flags.append('Confirm total')
    elif a: rec['total'] = a; st['total'] = 'AI only - confirm'; flags.append('Confirm total')
    elif o:
        rec['total'] = o; low = rec['ocr_total_conf'] < .55; st['total'] = 'OCR only' + (' - confirm' if low else '')   # corrections so far: right 38 of 39 times
        if low: flags.append('Confirm total')
    else: rec['total'] = None; st['total'] = 'not found'; flags.append('Confirm total')   # a receipt with no total is never filed as finished
    def _bad(n):                     # a total a little below the subtotal is a discount; only a big gap is a misread
        m = re.search(r'total ([\d.]+) is below subtotal ([\d.]+)', n)
        if m: return float(m.group(1)) < 0.8 * float(m.group(2))
        return 'was below subtotal' in n
    if corr.get('total') is None and rec['total'] is not None and any(_bad(n) for n in rec.get('notes', [])):
        flags.append('Confirm total'); st['total'] += ' | below the printed subtotal'          # the readers agree but the numbers contradict each other
    if corr.get('merchant'): rec['merchant'] = corr['merchant']; st['merchant'] = 'user confirmed'
    elif rec['merchant_source'] in (None, 'unmatched-first-line', 'card-slip'): st['merchant'] = 'not in directory - check'; flags.append('Confirm merchant')
    else: st['merchant'] = 'directory match'
    rec['status'] = st; return flags

def run(inp, out, entity, model='qwen3.5:9b', use_ai=True, log=print):
    out = os.path.abspath(out); work = os.path.join(out, '.work'); os.makedirs(work, exist_ok=True)
    corr_all = json.load(open(os.path.join(out, 'corrections.json'))) if os.path.exists(os.path.join(out, 'corrections.json')) else {}
    if use_ai and not OR.available(model):
        log(f'Ollama model {model} not reachable on localhost - continuing WITHOUT the AI second reader (faded dates will go to review).'); use_ai = False
    log(f'OCR engine: {ob.engine()}  |  AI second reader: {"on ("+model+")" if use_ai else "off"}')
    scans = sorted(f for f in os.listdir(inp) if f.lower().endswith(EXTS) and not f.startswith('.'))
    import hashlib
    hp = os.path.join(work, 'source_hashes.json'); hashes = json.load(open(hp)) if os.path.exists(hp) else {}
    for s in scans: hashes.setdefault(s, hashlib.sha256(open(os.path.join(inp, s), 'rb').read()).hexdigest())   # proof that originals are never changed
    json.dump(hashes, open(hp, 'w'), indent=1)
    items = []
    for s in scans:
        im = cv2.imread(os.path.join(inp, s))
        if im is None: log(f'  cannot read {s} - skipped'); continue
        stem = os.path.splitext(s)[0]
        for k, (crop, box, flags) in enumerate(segment.crops_from_scan(im), 1):
            items.append(dict(id=f'{stem}_{k}', crop=crop, boxes=[[int(v) for v in box]], flags=list(flags), scan=stem, sources=[os.path.abspath(os.path.join(inp, s))]))
    if use_ai:
        log(f'Found {len(items)} receipt pieces. Checking which way up each one is...')
        for it in items:
            it['crop'], how = orient.fix(it['crop'], model)
            if how == 'ai-uncertain': it['flags'].append('ORIENTATION_UNSURE')
    log(f'Looking for long receipts split across two scans...')
    joins = stitch.join_all(items, log); drop = set(); extra = []
    for j in joins:
        a, b = items[j['a']], items[j['b']]
        if j['kind'] == 'duplicate_piece':
            b['flags'].append('DUPLICATE_PIECE'); b.setdefault('dup_piece_of', []).append(a['id']); log(f'  {b["id"]} looks like the same piece as {a["id"]} (scanned twice)'); continue
        img = j['image']; cands = [img, cv2.rotate(img, cv2.ROTATE_180)]
        img = orient.fix(img, model)[0] if use_ai else cands[int(max(range(2), key=lambda q: segment.score(cands[q])))]
        flags = [f for f in a['flags'] + b['flags'] if f not in ('CLIPPED_BY_SCAN_EDGE',)] + ['JOINED']
        extra.append(dict(id=f'{a["id"]}__{b["id"]}', crop=img, boxes=a['boxes'] + b['boxes'], flags=sorted(set(flags)), scan=a['scan'] + '+' + b['scan'], sources=a['sources'] + b['sources']))
        drop |= {j['a'], j['b']}; log(f'  joined {a["id"]} + {b["id"]} ({j["method"]} match, score {j["score"]:.2f})')
    items = [it for i, it in enumerate(items) if i not in drop] + extra
    recs = []
    for it in items:
        cid = it['id']; t0 = time.time(); cp = os.path.join(work, cid + '.jpg'); cv2.imwrite(cp, it['crop'], [cv2.IMWRITE_JPEG_QUALITY, 95])
        rec = read_fields(it['crop'], model, use_ai, log)
        rec.update(id=cid, source_scan=it['sources'][0], sources=it['sources'], box=it['boxes'][0], boxes=it['boxes'], crop_flags=it['flags'], crop_path=cp, dup_piece_of=it.get('dup_piece_of', []))
        recs.append(rec); log(f'  {cid}: {rec["merchant"]} | ocr {rec["ocr_date"]} {rec["ocr_total"]} | ai {rec["ai_date"]} {rec["ai_total"]}  ({time.time()-t0:.0f}s)')
    ser = [dict(r, ocr_date=str(r['ocr_date']) if r['ocr_date'] else None, ai_date=str(r['ai_date']) if r['ai_date'] else None) for r in recs]
    json.dump(dict(model=model if use_ai else None, entity=entity, records=ser), open(os.path.join(work, 'records.json'), 'w'), ensure_ascii=False, indent=1, default=str)
    rows = finalize(out, entity, log)
    log(f'\nDone: {len(rows)} receipts from {len(scans)} scans.')
    return rows

FIELDSV = 1  # bump when shop-name / date reading improves, so older readings with no shop or date are read again
SLIPV = 2   # bump when slip reading improves, so older readings are looked at again
def _img_of(work, r):
    """The current picture of a piece (with the user's rotations)."""
    p = os.path.join(work, r['id'] + '.jpg')
    return p if os.path.exists(p) else r['crop_path']

def side_by_side(left, right, dst, gap=40):
    """One picture: left image and right image next to each other, tops aligned, on white. -> True when written."""
    a, b = cv2.imread(left), cv2.imread(right)
    if a is None or b is None: return False
    if b.shape[0] > 1.6 * a.shape[0] or b.shape[1] > 1.6 * a.shape[1]:          # a much bigger scan of the slip: bring it to the receipt's scale
        k = min(1.6 * a.shape[0] / b.shape[0], 1.6 * a.shape[1] / b.shape[1]); b = cv2.resize(b, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
    H = max(a.shape[0], b.shape[0]); W = a.shape[1] + gap + b.shape[1]
    canvas = np.full((H, W, 3), 255, np.uint8); canvas[:a.shape[0], :a.shape[1]] = a; canvas[:b.shape[0], a.shape[1] + gap:] = b
    return bool(cv2.imwrite(dst, canvas, [cv2.IMWRITE_JPEG_QUALITY, 92]))

def piece_twin(r, recs, corr_all):
    """The other copy of a piece flagged 'scanned twice': the piece it was matched with, or any other receipt with the same total on the
    same day (or the same shop and day when no total was read). None when there is no such receipt, i.e. the flag was a false alarm."""
    def same(o):
        if o is r or o['id'] in (corr_all.get(r['id'], {}).get('not_dup_of') or []): return False
        if is_slip(o, corr_all.get(o['id'], {})): return False
        if r['total'] is not None and o['total'] is not None:
            return abs(r['total'] - o['total']) < 0.005 and (not r['date'] or not o['date'] or r['date'] == o['date'])
        return bool(r['merchant'] and r['merchant'] == o['merchant'] and r['date'] and r['date'] == o['date'])
    named = [o for o in recs if o['id'] in (r.get('dup_piece_of') or []) and same(o)]
    if named: return named[0]['id']
    other = [o for o in recs if same(o)]
    other.sort(key=lambda o: (o['source_scan'] == r['source_scan'], o['id']))
    return other[0]['id'] if other else None

def is_slip(r, corr): return bool((r.get('card_slip') or corr.get('card_slip')) and not corr.get('not_slip'))

_GENERIC = {'sdn', 'bhd', 'the', 'and', 'enterprise', 'trading', 'restaurant', 'restoran', 'cafe', 'malaysia', 'store', 'shop', 'services', 'plt', 'kiara', 'bay'}
def _words(s): return {w for w in re.findall(r'[a-z]{3,}', (s or '').lower()) if w not in _GENERIC}

def _alike(a, b):
    """Shop names that look alike even when misread: a shared word, or 5+ letters in a row in common (WATSONS / MATSON'S KUCHAI)."""
    if _words(a) & _words(b): return True
    x, y = re.sub(r'[^A-Z]', '', (a or '').upper()), re.sub(r'[^A-Z]', '', (b or '').upper())
    if len(x) < 5 or len(y) < 5: return False
    import difflib
    m = difflib.SequenceMatcher(None, x, y).find_longest_match(0, len(x), 0, len(y))
    return m.size >= 5

def match_slips(recs, corr_all):
    """Bank card slip -> the receipt / invoice for the same payment.
    1. Pairs the user made by hand (corrections: slip_of) always stand.
    2. Same total and same day (or the day after); or same total, names alike and up to a week apart (a misread date).
    Only a clear single best match is paired; 'not the same payment' is never paired again."""
    C = lambda r: corr_all.get(r['id'], {})
    byid = {r['id']: r for r in recs}
    pairs = {}; taken = set()
    for s in recs:                                                          # by hand
        t = C(s).get('slip_of')
        if t and t in byid and t not in taken and t != s['id']: pairs[s['id']] = t; taken.add(t)
    slips = [r for r in recs if is_slip(r, C(r)) and r['id'] not in pairs]
    rc = [r for r in recs if not is_slip(r, C(r)) and r['total'] is not None and not C(r).get('hold')]
    for s in sorted(slips, key=lambda r: r['id']):
        if s['total'] is None: continue
        no = set(C(s).get('not_slip_of', [])); cands = []
        for r in rc:
            if r['id'] in taken or r['id'] in no or abs(r['total'] - s['total']) > 0.005: continue
            dd = abs((s['date'] - r['date']).days) if s['date'] and r['date'] else None
            alike = _alike(s['merchant'], r['merchant'])
            if dd is not None and dd > (7 if alike else 1): continue
            sc = (2 if dd == 0 else 1 if dd == 1 else 0) + 3 * len(_words(s['merchant']) & _words(r['merchant'])) + (2 if alike else 0)
            if dd is None and not alike: continue                           # no date to compare: the names must agree
            cands.append((sc, r['id']))
        cands.sort(reverse=True)
        if cands and (len(cands) == 1 or cands[0][0] > cands[1][0]): pairs[s['id']] = cands[0][1]; taken.add(cands[0][1])
    return pairs

def upgrade_readings(out, log=print):
    """Readings made by older versions: look once more (text only, quick) at pieces that may be bank slips or utility bills."""
    work = os.path.join(out, '.work'); rp = os.path.join(work, 'records.json'); saved = json.load(open(rp)); ns = nb = 0
    cp = os.path.join(out, 'corrections.json'); corr_all = json.load(open(cp)) if os.path.exists(cp) else {}
    names = {x for x, _ in F.MERCH}
    F.LEARNED[:] = sorted({c['merchant'] for c in corr_all.values() if c.get('merchant')})
    for r in saved['records']:
        needtext = (r.get('doc_kind') == 'bill' or (corr_all.get(r['id'], {}).get('kind') == 'bill')) and not r.get('bill_text')
        redo = r.get('fields_v') != FIELDSV and (r.get('merchant_source') in (None, 'unmatched-first-line') or not r.get('ocr_date') or r.get('ocr_total') is None)
        if r.get('slip_checked') == SLIPV and r.get('bill_checked') and not needtext and not redo: continue
        m = r.get('merchant') or ''
        maybe = needtext or redo or r.get('card_slip') or not m or r.get('merchant_source') in (None, 'unmatched-first-line', 'card-slip') or re.search(F.BANKS, m, re.I) or catalog.category(m)[0][0] == 'Utilities' or re.search(r'SALINAN|PEMBAYAR|BIL\b|CUKAI|MAJLIS|KERAJAAN', m, re.I)
        im = cv2.imread(os.path.join(work, r['id'] + '.jpg')) if maybe else None
        texts = [ob.text(im)] if im is not None else None
        if texts and r.get('slip_checked') != SLIPV:
            slip, name = F.card_slip(texts)
            if slip:                                                  # never downgraded: an earlier, better reading may have seen it
                r['card_slip'] = True; ns += 1
                weak = not m or r.get('merchant_source') in (None, 'unmatched-first-line') or re.search(F.BANKS, m, re.I) or re.search(F._ADDRESS, m, re.I)
                if name and weak: r['merchant'] = name; r['merchant_source'] = 'header' if name in names else 'card-slip'
        if texts and not r.get('bill_checked') and not r.get('card_slip'):
            bill, name, sub = F.utility_bill(texts)
            if bill:
                r['doc_kind'] = 'bill'; r['bill_sub'] = sub; r['bill_text'] = texts[0]; nb += 1
                if name: r['merchant'] = name; r['merchant_source'] = 'header'
        if texts and needtext: r['bill_text'] = texts[0]
        if texts and redo and r.get('ocr_total') is None:
            tot, tc, _e = F.pick_total(texts)
            if tot is not None: r['ocr_total'] = tot; r['ocr_total_conf'] = tc
        if texts and redo and not r.get('card_slip') and r.get('doc_kind') != 'bill':
            if r.get('merchant_source') in (None, 'unmatched-first-line'):
                nm, src = F.pick_merchant(texts)
                if nm and src != 'unmatched-first-line': r['merchant'] = nm; r['merchant_source'] = src
            if not r.get('ocr_date'):
                dt, dc, _e, _n = F.pick_date(texts, r.get('merchant'))
                if dt: r['ocr_date'] = str(dt); r['ocr_date_conf'] = dc
        r['fields_v'] = FIELDSV
        r['slip_checked'] = SLIPV; r['bill_checked'] = True
    # may run in the background while the user works: re-read the file and only touch these fields of pieces that still exist
    K = ('merchant', 'merchant_source', 'card_slip', 'slip_checked', 'bill_checked', 'doc_kind', 'bill_sub', 'bill_text', 'ocr_date', 'ocr_date_conf', 'ocr_total', 'ocr_total_conf', 'fields_v')
    upd = {r['id']: {k: r.get(k) for k in K} for r in saved['records']}
    with _FLOCK:
        cur = json.load(open(rp))
        for r in cur['records']:
            if r['id'] in upd and not (r.get('slip_checked') == SLIPV and r.get('bill_checked') and r.get('fields_v') == FIELDSV): r.update(upd[r['id']])
        json.dump(cur, open(rp, 'w'), ensure_ascii=False, indent=1, default=str)
    if ns or nb: log(f'{ns} bank card slip(s) and {nb} utility bill(s) recognised')
    return ns, nb

def upgrade_slips(out, log=print):
    """Readings made before slips were understood: look again at pieces whose 'shop' is a bank name (or unread) and take the shop from the
    line under the bank. Runs once per piece (marked slip_checked)."""
    work = os.path.join(out, '.work'); rp = os.path.join(work, 'records.json'); saved = json.load(open(rp)); n = 0
    names = {x for x, _ in F.MERCH}
    for r in saved['records']:
        if r.get('slip_checked'): continue
        if not (r.get('merchant') is None or re.search(F.BANKS, r.get('merchant') or '', re.I)): r['slip_checked'] = True; continue
        im = cv2.imread(os.path.join(work, r['id'] + '.jpg')); r['slip_checked'] = True
        if im is None: continue
        slip, name = F.card_slip([ob.text(im)])
        if slip:
            r['card_slip'] = True; n += 1
            if name: r['merchant'] = name; r['merchant_source'] = 'header' if name in names else 'card-slip'
    json.dump(saved, open(rp, 'w'), ensure_ascii=False, indent=1, default=str)
    if n: log(f'{n} bank card slip(s) recognised')
    return n

def _bills_to_folder(work, rows, byid, corr_all):
    """Confirmed utility bills (nothing left to check, has a date) are copied to <bills folder>/<type>/<property>/<year>/ when the property is known."""
    items = []
    for x in rows:
        if not x.get('is_bill') or x.get('card_slip_of'): continue
        r = byid[x['id']]; corr = corr_all.get(x['id'], {}); tf = BL.type_folder(x['subcategory'], x['merchant'])
        prop, how = BL.resolve(tf, r.get('bill_text'), corr); x.update(drive_type=tf, drive_prop=prop, drive_how=how, drive_path=None)
        d = datetime.date.fromisoformat(x['date']) if x['date'] else None
        ready = d and not x['review'] and not x['hold'] and not x['duplicate']
        dst = BL.target(tf, prop, d, os.path.splitext(r['crop_path'])[1] or '.jpg', r.get('bill_text')) if ready else None
        x['drive_plan'] = BL.target(tf, prop, d, '.jpg', r.get('bill_text')) if d else None
        items.append((x['id'], os.path.join(work, x['id'] + '.jpg') if os.path.exists(os.path.join(work, x['id'] + '.jpg')) else r['crop_path'], dst))
    placed = BL.sync(work, items)
    for x in rows:
        if x['id'] in placed: x['drive_path'] = placed[x['id']]

_FLOCK = threading.RLock()     # one refile at a time (the bills learner refiles in the background)
def finalize(out, entity=None, log=print):
    with _FLOCK: return _finalize(out, entity, log)

def _finalize(out, entity=None, log=print):
    """Apply decisions + user corrections to the saved readings and (re)file the derived copies. No OCR/AI is re-run.
    Previous derived copies are moved to .work/superseded, never deleted."""
    out = os.path.abspath(out); work = os.path.join(out, '.work'); saved = json.load(open(os.path.join(work, 'records.json')))
    entity = entity or saved.get('entity', 'Personal'); model = saved.get('model'); use_ai = bool(model)
    cp = os.path.join(out, 'corrections.json'); corr_all = json.load(open(cp)) if os.path.exists(cp) else {}
    ts = time.strftime('%Y%m%d_%H%M%S'); k = 1
    while os.path.exists(os.path.join(work, 'superseded', ts)): k += 1; ts = time.strftime('%Y%m%d_%H%M%S') + f'_{k}'   # two refiles in the same second
    for d in ('Organised Receipts', 'Needs Review', 'On Hold', 'Duplicates', 'Utility Bills'):
        if os.path.exists(os.path.join(out, d)):
            os.makedirs(os.path.join(work, 'superseded', ts), exist_ok=True); shutil.move(os.path.join(out, d), os.path.join(work, 'superseded', ts, d))
    recs = saved['records']
    for r in recs:
        for k in ('ocr_date', 'ai_date'): r[k] = datetime.date.fromisoformat(r[k]) if r[k] else None
    ds = sorted(r['ocr_date'] or r['ai_date'] for r in recs if (r['ocr_date'] or r['ai_date'])); med = ds[len(ds) // 2] if ds else None
    root = os.path.join(out, 'Organised Receipts'); rev = os.path.join(out, 'Needs Review'); rows = []; links = {}; used = {}; seen = {}
    try: imgdup = dupes.cached_pairs(work, [(r['id'], os.path.join(work, r['id'] + '.jpg')) for r in recs])      # same receipt scanned twice, found from the pictures
    except Exception as e: imgdup = {}; log(f'(picture duplicate check skipped: {e})')
    byid = {r['id']: r for r in recs}
    F.LEARNED[:] = sorted({c['merchant'] for c in corr_all.values() if c.get('merchant')})        # shops you named: recognised on the next receipts
    for r in recs: decide(r, corr_all.get(r['id'], {}), med)
    catlearn = {}                                                                                 # shop -> the category you chose for it before
    for r in recs:
        c = corr_all.get(r['id'], {})
        if c.get('category') and c['category'] != 'Uncategorised' and r['merchant']: catlearn[r['merchant']] = (c['category'], c.get('subcategory', ''))        # final date / total / shop first, so slips can be matched to their receipts
    pair = match_slips(recs, corr_all); slip_for = {v: k for k, v in pair.items()}
    for r in recs:
        if r['id'] in pair: continue                                     # filed next to its receipt below
        corr = corr_all.get(r['id'], {}); ent = corr.get('entity', entity); flags = decide(r, corr, med)
        cf = [f for f in r['crop_flags'] if f not in ('JOINED', 'DUPLICATE_PIECE', 'ORIENTATION_UNSURE', 'MANUAL_JOIN', 'MANUAL_CROP')]   # pieces the user joined / cut by hand were already checked by the user
        if cf and not corr.get('crop_ok'): flags = ['Check crop'] + flags
        if 'ORIENTATION_UNSURE' in r['crop_flags'] and not corr.get('crop_ok') and 'rotation' not in corr: flags = ['Check rotation'] + flags
        key = (r['merchant'], str(r['date']), r['total']); slip = is_slip(r, corr)
        dup_of = None
        if 'DUPLICATE_PIECE' in r['crop_flags'] and not corr.get('not_duplicate') and not slip:
            tw = piece_twin(r, recs, corr_all)          # the picture check alone often matches unrelated receipts (similar footers / QR codes)
            if tw: flags = flags + ['Possible duplicate']; dup_of = tw
        if r['merchant'] and r['total'] is not None and key in seen and not slip and not corr.get('not_duplicate'): flags = flags + ['Possible duplicate']; dup_of = seen[key]
        if r['id'] in imgdup and not corr.get('not_duplicate'):
            o = byid[imgdup[r['id']][0]]; same = True
            if imgdup[r['id']][1] < 0.95:       # a near-perfect picture match is the same picture whatever was typed; a weaker one must also agree on what was read
                if r['total'] is not None and o['total'] is not None and abs(r['total'] - o['total']) > 0.005: same = False
                if r['date'] and o['date'] and r['date'] != o['date']: same = False
            if same: flags = flags + ['Possible duplicate']; dup_of = dup_of or o['id']; r['notes'] = list(r['notes']) + [f"Looks like the same receipt as {o['id']} (picture match {imgdup[r['id']][1]:.2f})"]
        flags = list(dict.fromkeys(flags))
        if not slip: seen.setdefault(key, r['id'])
        (cat, sub), csrc = catalog.category(r['merchant'], catlearn if r['merchant'] not in catalog.DEFAULTS else None)
        if csrc == 'none' and r.get('doc_kind') == 'bill': (cat, sub), csrc = ('Utilities', r.get('bill_sub') or 'Other bills'), 'suggested'
        if corr.get('category'): cat, sub, csrc = corr['category'], corr.get('subcategory', ''), 'user'
        bill = corr.get('kind') == 'bill' or (corr.get('kind') != 'receipt' and (r.get('doc_kind') == 'bill' or cat == 'Utilities'))   # bills are filed apart from receipts
        tax_tag = '' if corr.get('tax_tag') in (None, '-') else corr['tax_tag']
        d = r['date']; base = (d, cat, sub, r['merchant'], ent); used[base] = used.get(base, 0) + 1
        name = catalog.filename(d, cat, sub, r['merchant'] or 'unknown', used[base]); reason = flags[0] if flags else None
        dup = 'Possible duplicate' in flags and corr.get('not_duplicate') is False   # user looked and confirmed it IS a second scan: set aside, out of totals
        hold = bool(corr.get('hold')) and not dup     # user parked it to decide later: kept in its own folder, out of the totals
        bills = os.path.join(out, 'Utility Bills')
        dest = os.path.join(out, 'Duplicates') if dup else os.path.join(out, 'On Hold') if hold else (os.path.join(bills, 'Needs Review', reason) if bill else os.path.join(rev, reason)) if reason else os.path.join(bills if bill else root, ent, str(d.year), catalog.month_folder(d))
        os.makedirs(dest, exist_ok=True); path = os.path.join(dest, name); shutil.copy2(r['crop_path'], path)
        links[os.path.relpath(path, out)] = dict(id=r['id'], source_scan=r['source_scan'], crop_box=r['box'], source_scans=r.get('sources', [r['source_scan']]), crop_boxes=r.get('boxes', [r['box']]), derived_file=path, entity=ent, merchant=r['merchant'],
                       date=str(d) if d else None, total_myr=r['total'], category=cat, subcategory=sub, category_source=csrc, status=r['status'], review=flags, crop_flags=r['crop_flags'],
                       ocr={'date': str(r['ocr_date']) if r['ocr_date'] else None, 'total': r['ocr_total']},
                       ai={'date': str(r['ai_date']) if r['ai_date'] else None, 'total': r['ai_total'], 'transcripts': r['ai_evidence'], 'model': model},
                       notes=r['notes'], hold=hold, duplicate=dup, doc_no=r['doc_no'], sst_id=r['sst_id'], note='AI/OCR values are suggestions; user corrections in corrections.json always win')
        rows.append(dict(id=r['id'], file=os.path.relpath(path, out), entity=ent, merchant=r['merchant'], date=str(d) if d else None, total_myr=r['total'], category=cat, subcategory=sub, tax_tag=tax_tag, hold=hold, duplicate=dup, card_slip=slip_for.get(r['id']), card_slip_of=None, is_slip=slip, is_bill=bill, dup_of=dup_of if 'Possible duplicate' in flags else None,
                         date_status=r['status']['date'], total_status=r['status']['total'], merchant_status=r['status']['merchant'], review=' / '.join(flags),
                         source_scan=os.path.basename(r['source_scan']), notes=' | '.join(r['notes']), ocr_date=str(r['ocr_date']) if r['ocr_date'] else None,
                         ai_date=str(r['ai_date']) if r['ai_date'] else None, ocr_total=r['ocr_total'], ai_total=r['ai_total'], crop_flags=r['crop_flags'], ai_transcripts=r['ai_evidence']))
    at = {x['id']: i for i, x in enumerate(rows)}
    for sid, rid in sorted(pair.items(), key=lambda kv: -at[kv[1]]):     # each matched slip is stored in ONE picture with its receipt: receipt left, slip right
        r = byid[sid]; inv = rows[at[rid]]; ipath = os.path.join(out, inv['file']); d = r['date']
        if not side_by_side(_img_of(work, byid[rid]), _img_of(work, r), ipath): shutil.copy2(r['crop_path'], os.path.splitext(ipath)[0] + '_card_slip.jpg')
        lk = links.get(inv['file'])
        if lk is not None: lk['card_slip'] = dict(id=sid, source_scan=r['source_scan'], crop_box=r['box'], merchant=r['merchant'], date=str(d) if d else None, total_myr=r['total'],
                                                  note='bank card slip for this receipt, on the right of the same picture; not counted again')
        rows.insert(at[rid] + 1, dict(id=sid, file=inv['file'], entity=inv['entity'], merchant=r['merchant'], date=str(d) if d else None, total_myr=r['total'], category=inv['category'],
                         subcategory=inv['subcategory'], tax_tag='', hold=False, duplicate=False, card_slip=None, card_slip_of=rid, is_slip=True, is_bill=inv.get('is_bill', False),
                         date_status=r['status']['date'], total_status=r['status']['total'], merchant_status=r['status']['merchant'], review='',
                         source_scan=os.path.basename(r['source_scan']), notes=' | '.join(r['notes'] + [f'Card slip for {inv["merchant"]} {inv["date"]} RM {inv["total_myr"]}']), ocr_date=str(r['ocr_date']) if r['ocr_date'] else None,
                         ai_date=str(r['ai_date']) if r['ai_date'] else None, ocr_total=r['ocr_total'], ai_total=r['ai_total'], crop_flags=r['crop_flags'], ai_transcripts=r['ai_evidence']))
    try: _bills_to_folder(work, rows, byid, corr_all)
    except Exception as e: log(f'(bills folder skipped: {e})')
    with open(os.path.join(out, 'index.csv'), 'w', newline='', encoding='utf-8-sig') as f:
        keys = ['id', 'file', 'entity', 'merchant', 'date', 'total_myr', 'category', 'subcategory', 'tax_tag', 'date_status', 'total_status', 'merchant_status', 'review', 'hold', 'duplicate', 'card_slip_of', 'is_bill', 'source_scan', 'notes']
        w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); [w.writerow({k: x[k] for k in keys}) for x in rows]
    json.dump(links, open(os.path.join(work, 'links.json'), 'w'), ensure_ascii=False, indent=1, default=str)   # derived file -> source scans, boxes, readings (one hidden file instead of a .json beside every image)
    json.dump(rows, open(os.path.join(work, 'view.json'), 'w'), ensure_ascii=False, default=str)
    return rows

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--input', required=True); ap.add_argument('--output', required=True)
    ap.add_argument('--entity', default='Personal'); ap.add_argument('--model', default='qwen3.5:9b'); ap.add_argument('--no-ai', action='store_true')
    a = ap.parse_args(); run(a.input, a.output, a.entity, a.model, not a.no_ai)

if __name__ == '__main__': main()
