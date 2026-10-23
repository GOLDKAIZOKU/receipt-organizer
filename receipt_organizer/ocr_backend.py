"""OCR backend. macOS: Apple Vision. Windows: the OCR built into Windows 10/11. Both need no extra install; Tesseract is the last fallback.
Everything runs on this computer; nothing is uploaded."""
import sys, re
import cv2, numpy as np

def _vision_lines(img):
    import Vision, Quartz
    from Foundation import NSData
    ok, buf = cv2.imencode('.png', img)
    data = NSData.dataWithBytes_length_(buf.tobytes(), len(buf))
    src = Quartz.CGImageSourceCreateWithData(data, None)
    cg = Quartz.CGImageSourceCreateImageAtIndex(src, 0, None)
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    req.setUsesLanguageCorrection_(False)
    h = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(cg, None)
    h.performRequests_error_([req], None)
    H, W = img.shape[:2]; out = []
    for o in (req.results() or []):
        c = o.topCandidates_(1)[0]; bb = o.boundingBox()
        out.append(dict(x0=bb.origin.x * W, x1=(bb.origin.x + bb.size.width) * W,
                        y0=(1 - bb.origin.y - bb.size.height) * H, y1=(1 - bb.origin.y) * H,
                        text=str(c.string()), conf=float(c.confidence())))
    return out

def _tess_lines(img):
    import pytesseract
    from pytesseract import Output
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    d = pytesseract.image_to_data(g, config='--psm 6', output_type=Output.DICT)
    L = {}
    for i, t in enumerate(d['text']):
        if not t.strip(): continue
        k = (d['block_num'][i], d['par_num'][i], d['line_num'][i])
        x, y, w, h = d['left'][i], d['top'][i], d['width'][i], d['height'][i]
        e = L.setdefault(k, dict(x0=x, x1=x + w, y0=y, y1=y + h, t=[], c=[]))
        e['x0'] = min(e['x0'], x); e['x1'] = max(e['x1'], x + w); e['y0'] = min(e['y0'], y); e['y1'] = max(e['y1'], y + h)
        e['t'].append(t); e['c'].append(max(float(d['conf'][i]), 0) / 100)
    return [dict(x0=e['x0'], x1=e['x1'], y0=e['y0'], y1=e['y1'], text=' '.join(e['t']), conf=sum(e['c']) / len(e['c'])) for e in L.values()]

_WIN = {}
def _win_lines(img):
    """Windows.Media.Ocr (built into Windows 10/11). Uses the languages installed in Windows; English is always there."""
    import asyncio
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.graphics.imaging import SoftwareBitmap, BitmapPixelFormat, BitmapAlphaMode
    from winrt.windows.storage.streams import DataWriter
    if 'eng' not in _WIN:
        e = OcrEngine.try_create_from_user_profile_languages()
        if e is None:
            from winrt.windows.globalization import Language
            e = OcrEngine.try_create_from_language(Language('en-US'))
        _WIN['eng'] = e
    eng = _WIN['eng']; H, W = img.shape[:2]; k = 1.0
    mx = getattr(OcrEngine, 'max_image_dimension', 10000) or 10000
    if max(H, W) > mx: k = mx / max(H, W)
    if min(H, W) * k < 40: k = max(k, 40 / max(1, min(H, W)))
    im = cv2.resize(img, None, fx=k, fy=k, interpolation=cv2.INTER_AREA if k < 1 else cv2.INTER_CUBIC) if k != 1.0 else img
    bgra = cv2.cvtColor(im, cv2.COLOR_BGR2BGRA if im.ndim == 3 else cv2.COLOR_GRAY2BGRA); h, w = bgra.shape[:2]
    dw = DataWriter(); dw.write_bytes(bgra.tobytes())
    sb = SoftwareBitmap.create_copy_from_buffer(dw.detach_buffer(), BitmapPixelFormat.BGRA8, w, h, BitmapAlphaMode.PREMULTIPLIED)
    async def go(): return await eng.recognize_async(sb)
    res = asyncio.run(go()); out = []
    for ln in res.lines:
        ws = list(ln.words)
        if not ws: continue
        rs = [x.bounding_rect for x in ws]
        out.append(dict(x0=min(r.x for r in rs) / k, x1=max(r.x + r.width for r in rs) / k, y0=min(r.y for r in rs) / k, y1=max(r.y + r.height for r in rs) / k,
                        text=str(ln.text), conf=0.9))          # Windows OCR gives no confidence per line
    return out

_impl = None
def _pick():
    global _impl
    if _impl: return _impl
    if sys.platform == 'darwin':
        try:
            import Vision, Quartz  # noqa
            _impl = ('apple-vision', _vision_lines); return _impl
        except ImportError:
            pass
    if sys.platform.startswith('win'):
        try:
            from winrt.windows.media.ocr import OcrEngine  # noqa
            _impl = ('windows-ocr', _win_lines); return _impl
        except ImportError:
            pass
    try:
        import pytesseract; pytesseract.get_tesseract_version()
        _impl = ('tesseract', _tess_lines); return _impl
    except Exception:
        raise RuntimeError('No OCR engine found: on Mac run setup_mac.command; on Windows use the downloaded app (it includes Windows OCR support).')

def engine(): return _pick()[0]

TALL = 3.0     # taller than this many widths = a long receipt: read it in slices (the engines lose accuracy on very tall pictures)
def lines(img):
    """[{x0,x1,y0,y1,text,conf}] sorted top to bottom."""
    fn = _pick()[1]; H, W = img.shape[:2]
    if H <= TALL * W: return sorted(fn(img), key=lambda e: (e['y0'], e['x0']))
    th = int(2.2 * W); ov = int(0.2 * th); step = th - ov; out = []; s = 0
    while True:
        e = min(H, s + th); last = e >= H
        lo = s + (ov // 2 if s > 0 else 0); hi = e if last else e - ov // 2
        for l in fn(img[s:e]):
            cy = (l['y0'] + l['y1']) / 2 + s
            if lo <= cy < hi or (last and cy >= lo): out.append(dict(l, y0=l['y0'] + s, y1=l['y1'] + s))
        if last: break
        s += step
    return sorted(out, key=lambda e: (e['y0'], e['x0']))

def rows(img):
    """Group fragments on the same visual row into one row (e.g. 'TOTAL' + 'RM106.24')."""
    ls = lines(img); out = []
    for l in ls:
        cy = (l['y0'] + l['y1']) / 2; h = max(l['y1'] - l['y0'], 1)
        for r in out:
            if abs(cy - r['cy']) < 0.6 * max(h, r['h']):
                r['parts'].append(l); r['cy'] = (r['cy'] + cy) / 2; r['h'] = max(r['h'], h); break
        else:
            out.append(dict(cy=cy, h=h, parts=[l]))
    res = []
    for r in out:
        ps = sorted(r['parts'], key=lambda p: p['x0'])
        res.append(dict(y0=min(p['y0'] for p in ps), y1=max(p['y1'] for p in ps), x0=ps[0]['x0'], x1=max(p['x1'] for p in ps),
                        text=' '.join(p['text'] for p in ps), conf=min(p['conf'] for p in ps)))
    return sorted(res, key=lambda r: r['y0'])

def text(img):
    return '\n'.join(r['text'] for r in rows(img))
