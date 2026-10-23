"""Turn each crop upright using the local vision model. Tested on 30 real crops: three separate chunks per receipt agreed every time and matched
what a person sees. OCR keyword scoring (segment.upright) stays as the fallback when Ollama is not available."""
import base64, json, urllib.request
import cv2

PROMPT = ('This image is a part of a printed shop receipt. Is the printed text upside down (rotated 180 degrees), so that you would have to turn the picture around to read it? '
          'Answer JSON only: {"upside_down": true or false}')

def _ask(img, model):
    ok, buf = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 90])
    body = {"model": model, "stream": False, "think": False, "format": "json", "options": {"temperature": 0},
            "messages": [{"role": "user", "content": PROMPT, "images": [base64.b64encode(buf.tobytes()).decode()]}]}
    try:
        r = json.load(urllib.request.urlopen(urllib.request.Request("http://localhost:11434/api/chat", json.dumps(body).encode(), {"Content-Type": "application/json"}), timeout=120))
        return bool(json.loads(r["message"]["content"]).get("upside_down"))
    except Exception:
        return None

def _chunks(im):
    H, W = im.shape[:2]; ch = int(min(H * 0.30, W * 1.3)); out = []
    for y in (0.0, 0.35, 0.70):
        c = im[int(y * H):int(y * H) + ch]; k = 900 / max(c.shape[:2])
        out.append(cv2.resize(c, None, fx=k, fy=k, interpolation=cv2.INTER_AREA))
    return out

def upside_down(img, model):
    """-> (True/False/None, votes). Two chunks first; the third only if they disagree."""
    ch = _chunks(img); v = [_ask(ch[0], model), _ask(ch[1], model)]
    if None in v: return None, v
    if v[0] != v[1]:
        v.append(_ask(ch[2], model))
        if v[2] is None: return None, v
    return sum(v) * 2 > len(v), v

def fix(img, model):
    """-> (image, note). note: 'ai' (turned/kept by vision model), 'ai-uncertain' (votes disagreed), or 'ocr' (no AI available)."""
    r, v = upside_down(img, model)
    if r is None: return img, 'ocr'
    out = cv2.rotate(img, cv2.ROTATE_180) if r else img
    return out, ('ai' if len(set(v)) == 1 else 'ai-uncertain')
