"""Second reader for faded/uncertain lines using YOUR local Ollama (http://localhost:11434 only).
It TRANSCRIBES tight line crops; code (not the model) parses and validates. Output is a suggestion, never an authority."""
import base64, json, re, time, urllib.request
import cv2
from . import ocr_backend as ob

URL = "http://localhost:11434/api/chat"
PROMPT = ("Transcribe the single line of text printed in this image exactly as printed. Do not interpret or guess. "
          'If a character is too faded to read, write ? for it. Return JSON: {"text": "..."}')
DATEHINT = re.compile(r'\d{1,2}\s*[/\-.]\s*\d{1,2}|20\d\d|[A-Z0-9]{3}\s*20\d\d|DATE|TIME|[AP]M|\d{1,2}:\d{2}|ORDER', re.I)
TOTHINT = re.compile(r'TOTAL|GRAND|NET|AMOUNT|CARD|\bRM\b|PAID|CASH|TENDER|DUE', re.I)

def available(model):
    try:
        r = json.load(urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3))
        return any(m['name'].startswith(model.split(':')[0]) and m['name'] == model for m in r.get('models', []))
    except Exception:
        return False

def _crop(img, y0, y1, margin=0.6):
    H, W = img.shape[:2]; h = max(y1 - y0, 18); a = int(max(0, y0 - margin * h)); b = int(min(H, y1 + margin * h))
    k = max(1.0, 1400 / W); c = cv2.resize(img[a:b], None, fx=k, fy=k, interpolation=cv2.INTER_CUBIC)
    g = cv2.createCLAHE(2.0, (8, 8)).apply(cv2.cvtColor(c, cv2.COLOR_BGR2GRAY))
    return c, g

def transcribe(image, model):
    ok, buf = cv2.imencode('.png', image)
    body = {"model": model, "stream": False, "think": False, "format": "json", "options": {"temperature": 0},
            "messages": [{"role": "user", "content": PROMPT, "images": [base64.b64encode(buf.tobytes()).decode()]}]}
    for _ in range(3):
        try:
            r = json.load(urllib.request.urlopen(urllib.request.Request(URL, json.dumps(body).encode(), {"Content-Type": "application/json"}), timeout=120))
            return str(json.loads(r["message"]["content"]).get("text", ""))
        except Exception:
            time.sleep(1)
    return None

def read_candidate_lines(img, model, want_date, want_total, maxd=6, maxt=5):
    """Returns {'date': [text...], 'total': [text...]} transcripts of the candidate lines (colour + contrast variants)."""
    H = img.shape[0]; rs = ob.rows(img); out = {'date': [], 'total': []}
    if want_date:
        dc = [r for r in rs if r['y0'] < .55 * H and (DATEHINT.search(r['text']) or r['conf'] < .6)]
        if len(dc) < 2: dc += [r for r in rs if r['y0'] < .45 * H and r not in dc][:maxd]
        for r in dc[:maxd]:
            for im in _crop(img, r['y0'], r['y1']):
                t = transcribe(im, model)
                if t: out['date'].append(t)
    if want_total:
        tc = [r for r in rs if r['y0'] > .25 * H and TOTHINT.search(r['text'])]
        for r in tc[-maxt:]:
            for im in _crop(img, r['y0'], r['y1']):
                t = transcribe(im, model)
                if t: out['total'].append(t)
    return out
