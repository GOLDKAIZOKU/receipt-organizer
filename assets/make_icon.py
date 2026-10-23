"""Draws the app icon (teal tile, paper receipt with a highlighted line and a check) and writes AppIcon.iconset/ + icon.png."""
from PIL import Image, ImageDraw
import os, sys
S = 2048
def tile(S):
    bg = Image.new('RGBA', (S, S), (0, 0, 0, 0)); d = ImageDraw.Draw(bg)
    m = int(S * .055); d.rounded_rectangle((m, m, S - m, S - m), radius=int(S * .225), fill=(14, 107, 117, 255))
    # receipt: slightly narrow sheet with a zigzag bottom edge
    L, R, T, B = int(S * .27), int(S * .73), int(S * .17), int(S * .80); n = 9; w = (R - L) / n; zz = int(S * .035)
    pts = [(L, T), (R, T), (R, B)]
    for i in range(n): pts += [(R - w * (i + .5), B + zz), (R - w * (i + 1), B)]
    sh = Image.new('RGBA', (S, S), (0, 0, 0, 0)); ImageDraw.Draw(sh).polygon([(x + S * .01, y + S * .018) for x, y in pts], fill=(0, 0, 0, 70)); bg = Image.alpha_composite(bg, sh); d = ImageDraw.Draw(bg)
    d.polygon(pts, fill=(243, 245, 242, 255))
    ink = (30, 42, 49, 255); soft = (181, 190, 195, 255); x0 = L + int(S * .05); x1 = R - int(S * .05); h = int(S * .026)
    d.rounded_rectangle((x0, T + int(S * .07), x0 + int((x1 - x0) * .62), T + int(S * .07) + h * 1.5), radius=h, fill=ink)      # merchant line
    y = T + int(S * .17)
    for k, wd in enumerate((.9, .75, .85)):
        d.rounded_rectangle((x0, y, x0 + int((x1 - x0) * wd), y + h), radius=h // 2, fill=soft); y += int(S * .062)
    d.rectangle((x0 - int(S * .015), y - int(S * .008), x1 + int(S * .015), y + int(S * .052)), fill=(242, 209, 75, 255))          # highlighter band
    d.rounded_rectangle((x0, y + int(S * .012), x0 + int((x1 - x0) * .42), y + int(S * .012) + h), radius=h // 2, fill=ink)
    d.rounded_rectangle((x1 - int((x1 - x0) * .26), y + int(S * .012), x1, y + int(S * .012) + h), radius=h // 2, fill=ink)
    y += int(S * .105)
    d.rounded_rectangle((x0, y, x0 + int((x1 - x0) * .7), y + h), radius=h // 2, fill=soft)
    # check badge
    cx, cy, r = int(S * .70), int(S * .73), int(S * .135)
    d.ellipse((cx - r - int(S * .012), cy - r - int(S * .012), cx + r + int(S * .012), cy + r + int(S * .012)), fill=(14, 107, 117, 255))
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(47, 125, 91, 255))
    d.line([(cx - r * .45, cy + r * .02), (cx - r * .1, cy + r * .38), (cx + r * .5, cy - r * .32)], fill=(255, 255, 255, 255), width=int(S * .036), joint='curve')
    for q in [(cx - r * .45, cy + r * .02), (cx + r * .5, cy - r * .32)]: d.ellipse((q[0] - S * .018, q[1] - S * .018, q[0] + S * .018, q[1] + S * .018), fill=(255, 255, 255, 255))
    return bg
here = os.path.dirname(os.path.abspath(__file__)); big = tile(S)
big.resize((1024, 1024), Image.LANCZOS).save(os.path.join(here, 'icon.png'))
d = os.path.join(here, 'AppIcon.iconset'); os.makedirs(d, exist_ok=True)
for sz in (16, 32, 128, 256, 512):
    big.resize((sz, sz), Image.LANCZOS).save(os.path.join(d, f'icon_{sz}x{sz}.png'))
    big.resize((sz * 2, sz * 2), Image.LANCZOS).save(os.path.join(d, f'icon_{sz}x{sz}@2x.png'))
print('ok')
