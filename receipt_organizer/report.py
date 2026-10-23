"""Spending summary as a PDF: totals, by category, by month, top shops, utility bills, and the full list.
The page is written as HTML and printed to PDF by Google Chrome (headless, its own temporary profile, nothing is uploaded).
Only confirmed receipts and bills are counted; ones still to check, on hold, duplicates and matched card slips are left out (and said so)."""
import html, os, subprocess, tempfile, time, datetime, collections, shutil, pathlib
from . import sysdeps

L = {
 'zh': dict(title='支出总结', period='期间', owner='归属', all='全部', made='制作日期', total='总支出', n='张单据 / 账单', avg='平均每月', months='个月',
            bycat='按分类', bymonth='按月份', table='分类 × 月份', top='花最多的商家', bills='水电 / 地税账单', list='全部明细', date='日期', shop='商家',
            cat='分类', amt='金额 (RM)', share='占比', visits='次数', place='地点', type='类型', sum='合计', none='这个期间没有已确认的单据。',
            left=lambda n, a: f'另有 {n} 张还没确认、搁置或可能重复,共 RM {a:,.2f},没有算进来。', nodate='没有日期', page='页'),
 'en': dict(title='Spending summary', period='Period', owner='Owner', all='All', made='Made on', total='Total spent', n='receipts / bills', avg='Average per month', months='months',
            bycat='By category', bymonth='By month', table='Category × month', top='Top shops', bills='Utility bills', list='Full list', date='Date', shop='Shop',
            cat='Category', amt='Amount (RM)', share='Share', visits='Visits', place='Property', type='Type', sum='Total', none='No confirmed receipts in this period.',
            left=lambda n, a: f'{n} more are still to check, on hold or possible duplicates (RM {a:,.2f}); they are not included.', nodate='No date', page='Page'),
}
CAT_ZH = {'Household & maintenance': '家居维修', 'Food & beverages': '餐饮', 'Groceries': '杂货', 'Transport': '交通', 'Health & medical': '医疗',
          'Medicine': '药品', 'Pets': '宠物', 'Hotel & accommodation': '酒店住宿', 'Shopping': '购物', 'Utilities': '水电账单', 'Education': '教育',
          'Office & business': '办公', 'Uncategorised': '未分类'}
SUB_ZH = {'Electricity': '电费', 'Water': '水费', 'Sewerage': '排污', 'Internet & phone': '网络 / 电话', 'TV & streaming': '电视', 'Gas': '煤气',
          'Assessment & land tax': '地税 / 门牌税', 'Other bills': '其他账单', 'Hardware & supplies': '五金用品', 'Repairs & maintenance': '维修',
          'Furniture & fittings': '家具', 'Dining out': '外食', 'Drinks & desserts': '饮料甜品', 'Food & household essentials': '食品日用品', 'Fuel': '油费',
          'Tyres & vehicle maintenance': '轮胎保养', 'Parking & tolls': '停车 / 过路费', 'Public transport': '公共交通', 'Eyewear': '眼镜', 'Clinic & doctor': '诊所',
          'Dental': '牙科', 'Hospital': '医院', 'Pharmacy': '药房', 'Pharmacy & medicine': '药房 / 药品', 'Vitamins & supplements': '保健品', 'Medical supplies': '医疗用品',
          'Pet food & supplies': '宠物用品', 'Vet & pet clinic': '兽医', 'Grooming & boarding': '美容 / 寄养', 'Hotel': '酒店', 'Homestay & Airbnb': '民宿', 'Resort': '度假村',
          'Clothing & footwear': '服装鞋子', 'Sportswear & equipment': '运动用品', 'Electronics & accessories': '电子产品', 'Books & stationery': '书籍文具',
          'Courses & fees': '课程学费', 'Office supplies': '办公用品', 'Equipment': '设备', 'Services & subscriptions': '服务 / 订阅'}
MON = {'zh': ['1月', '2月', '3月', '4月', '5月', '6月', '7月', '8月', '9月', '10月', '11月', '12月'],
       'en': ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']}

def e(s): return html.escape(str(s if s is not None else ''))
def money(a): return f'{a:,.2f}'

def counted(r): return not (r.get('review') or r.get('hold') or r.get('duplicate') or r.get('card_slip_of'))

def pick(rows, entity, start, end):
    """-> (counted rows in the period, rows left out in the period)"""
    inn = lambda r: (not entity or r.get('entity') == entity) and r.get('date') and (not start or r['date'][:7] >= start) and (not end or r['date'][:7] <= end)
    sel = [r for r in rows if inn(r)]
    return [r for r in sel if counted(r) and r.get('total_myr') is not None], [r for r in sel if not counted(r) and not r.get('card_slip_of')]

def hbars(items, total, w=640):
    """Horizontal bars, one hue; label left, value right."""
    if not items: return ''
    top = max(v for _, v in items) or 1; rowh = 26; lw = 150; vw = 150; bw = w - lw - vw - 10; out = []
    for i, (k, v) in enumerate(items):
        y = i * rowh; bl = max(2, bw * v / top)
        out.append(f'<text x="{lw-8}" y="{y+17}" text-anchor="end" class="lab">{e(k)}</text>'
                   f'<rect x="{lw}" y="{y+5}" width="{bl:.1f}" height="16" rx="3" class="bar"/>'
                   f'<text x="{lw+bl+6:.1f}" y="{y+17}" class="val">RM {money(v)}  ·  {100*v/total:.0f}%</text>')
    return f'<svg viewBox="0 0 {w} {len(items)*rowh+4}" width="100%">{"".join(out)}</svg>'

def vbars(items, w=640, h=200):
    if not items: return ''
    top = max(v for _, v in items) or 1; n = len(items); gap = 14; bw = min(90, (w - 40 - gap * n) / n); out = []
    x0 = 24 + max(0, (w - 24 - n * (bw + gap)) / 2)
    for i, (k, v) in enumerate(items):
        x = x0 + i * (bw + gap); bh = max(2, (h - 46) * v / top); y = h - 24 - bh
        out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{bh:.1f}" rx="3" class="bar"/>'
                   f'<text x="{x+bw/2:.1f}" y="{y-5:.1f}" text-anchor="middle" class="val sm">{v:,.0f}</text>'
                   f'<text x="{x+bw/2:.1f}" y="{h-8}" text-anchor="middle" class="lab sm">{e(k)}</text>')
    return f'<svg viewBox="0 0 {w} {h}" width="100%"><line x1="24" y1="{h-24}" x2="{w}" y2="{h-24}" class="axis"/>{"".join(out)}</svg>'

def build_html(rows, entity=None, start=None, end=None, lang='zh'):
    T = L[lang]; zh = lang == 'zh'
    catn = lambda c: (CAT_ZH.get(c, c) if zh else c) or ('未分类' if zh else 'Uncategorised')
    subn = lambda s: (SUB_ZH.get(s, s) if zh else s)
    ym = lambda k: (f'{k[:4]}年{int(k[5:])}月' if zh else f'{MON["en"][int(k[5:])-1]} {k[:4]}') if k else T['nodate']
    use, left = pick(rows, entity, start, end)
    tot = sum(r['total_myr'] for r in use)
    months = sorted({r['date'][:7] for r in use})
    span = (f'{ym(start or (months[0] if months else ""))} – {ym(end or (months[-1] if months else ""))}')
    bycat = collections.Counter(); bymon = collections.Counter(); cm = collections.defaultdict(collections.Counter); shops = collections.defaultdict(lambda: [0.0, 0])
    for r in use:
        c = catn(r.get('category')); m = r['date'][:7]; a = r['total_myr']
        bycat[c] += a; bymon[m] += a; cm[c][m] += a
        if not r.get('is_bill'): s = shops[r.get('merchant') or '?']; s[0] += a; s[1] += 1
    nmon = max(1, len(months))
    css = """
    @page{size:A4;margin:16mm 14mm 16mm}
    body{font:10.5pt/1.45 "PingFang SC","Helvetica Neue",-apple-system,sans-serif;color:#1e2a31;margin:0}
    h1{font-size:22pt;margin:0 0 2pt}h2{font-size:13pt;margin:18pt 0 6pt;padding-bottom:3pt;border-bottom:1.5pt solid #0e6b75;break-after:avoid}
    .meta{color:#667482;margin-bottom:12pt}.kpis{display:flex;gap:10pt;margin:6pt 0 4pt}
    .kpi{flex:1;border:1px solid #dde2e0;border-radius:8pt;padding:9pt 11pt}.kpi b{display:block;font-size:17pt;font-variant-numeric:tabular-nums}.kpi span{color:#667482;font-size:9pt}
    .note{color:#a86a10;font-size:9pt;margin:6pt 0}
    table{width:100%;border-collapse:collapse;font-size:9pt;font-variant-numeric:tabular-nums}th,td{padding:4pt 6pt;border-bottom:1px solid #e6eaea;text-align:left;vertical-align:top}
    th{color:#667482;font-weight:600;background:#f4f6f5}td.n,th.n{text-align:right;white-space:nowrap}tr.tot td{font-weight:700;border-top:1.5px solid #1e2a31}
    tr{break-inside:avoid}thead{display:table-header-group}.wide{font-size:8pt}.wide td,.wide th{padding:3pt 4pt}
    svg .bar{fill:#0e6b75}svg .lab{font-size:11px;fill:#1e2a31}svg .val{font-size:11px;fill:#667482}svg .sm{font-size:10px}svg .axis{stroke:#c9d0cf}
    .mh{background:#eef3f3;font-weight:700}.sec{break-inside:avoid}
    """
    h = [f'<!doctype html><html lang="{"zh-CN" if zh else "en"}"><head><meta charset="utf-8"><title>{e(T["title"])}</title><style>{css}</style></head><body>',
         f'<h1>{e(T["title"])}</h1><div class="meta">{e(T["owner"])}: <b>{e(entity or T["all"])}</b> &nbsp;·&nbsp; {e(T["period"])}: <b>{e(span)}</b> &nbsp;·&nbsp; {e(T["made"])}: {datetime.date.today().strftime("%d/%m/%Y")}</div>']
    if not use:
        h.append(f'<p>{e(T["none"])}</p>')
    else:
        h.append(f'<div class="kpis"><div class="kpi"><span>{e(T["total"])}</span><b>RM {money(tot)}</b></div><div class="kpi"><span>{e(T["n"])}</span><b>{len(use)}</b></div>'
                 f'<div class="kpi"><span>{e(T["avg"])} ({nmon} {e(T["months"])})</span><b>RM {money(tot/nmon)}</b></div></div>')
    if left: h.append(f'<div class="note">{e(T["left"](len(left), sum(r.get("total_myr") or 0 for r in left)))}</div>')
    if use:
        h.append(f'<div class="sec"><h2>{e(T["bycat"])}</h2>{hbars(bycat.most_common(), tot)}</div>')
        h.append(f'<div class="sec"><h2>{e(T["bymonth"])}</h2>{vbars([(ym(m), bymon[m]) for m in months])}</div>')
        # category x month
        cats = [c for c, _ in bycat.most_common()]; wide = len(months) > 7
        h.append(f'<div class="sec"><h2>{e(T["table"])}</h2><table class="{"wide" if wide else ""}"><thead><tr><th>{e(T["cat"])}</th>' + ''.join(f'<th class="n">{e(ym(m))}</th>' for m in months) + f'<th class="n">{e(T["sum"])}</th></tr></thead><tbody>')
        for c in cats: h.append(f'<tr><td>{e(c)}</td>' + ''.join(f'<td class="n">{money(cm[c][m]) if cm[c][m] else "–"}</td>' for m in months) + f'<td class="n"><b>{money(bycat[c])}</b></td></tr>')
        h.append('<tr class="tot"><td>' + e(T['sum']) + '</td>' + ''.join(f'<td class="n">{money(bymon[m])}</td>' for m in months) + f'<td class="n">{money(tot)}</td></tr></tbody></table></div>')
        # top shops
        top = sorted(shops.items(), key=lambda kv: -kv[1][0])[:10]
        if top:
            h.append(f'<div class="sec"><h2>{e(T["top"])}</h2><table><thead><tr><th>{e(T["shop"])}</th><th class="n">{e(T["visits"])}</th><th class="n">{e(T["amt"])}</th><th class="n">{e(T["share"])}</th></tr></thead><tbody>')
            for k, (a, n) in top: h.append(f'<tr><td>{e(k)}</td><td class="n">{n}</td><td class="n">{money(a)}</td><td class="n">{100*a/tot:.1f}%</td></tr>')
            h.append('</tbody></table></div>')
        # bills by type and property
        bl = [r for r in use if r.get('is_bill')]
        if bl:
            bm = sorted({r['date'][:7] for r in bl}); grid = collections.defaultdict(collections.Counter)
            for r in bl: grid[(subn(r.get('subcategory') or ''), r.get('drive_prop') or '–')][r['date'][:7]] += r['total_myr']
            wide = len(bm) > 7
            h.append(f'<div class="sec"><h2>{e(T["bills"])}</h2><table class="{"wide" if wide else ""}"><thead><tr><th>{e(T["type"])}</th><th>{e(T["place"])}</th>' + ''.join(f'<th class="n">{e(ym(m))}</th>' for m in bm) + f'<th class="n">{e(T["sum"])}</th></tr></thead><tbody>')
            for (t, p) in sorted(grid): h.append(f'<tr><td>{e(t)}</td><td>{e(p)}</td>' + ''.join(f'<td class="n">{money(grid[(t,p)][m]) if grid[(t,p)][m] else "–"}</td>' for m in bm) + f'<td class="n"><b>{money(sum(grid[(t,p)].values()))}</b></td></tr>')
            h.append('</tbody></table></div>')
        # full list
        h.append(f'<h2 style="break-before:page">{e(T["list"])}</h2><table><thead><tr><th>{e(T["date"])}</th><th>{e(T["shop"])}</th><th>{e(T["cat"])}</th>' + ('' if entity else f'<th>{e(T["owner"])}</th>') + f'<th class="n">{e(T["amt"])}</th></tr></thead><tbody>')
        for m in months:
            mr = sorted((r for r in use if r['date'][:7] == m), key=lambda r: (r['date'], r.get('merchant') or ''))
            h.append(f'<tr class="mh"><td colspan="{4 if entity else 5}">{e(ym(m))} — RM {money(sum(r["total_myr"] for r in mr))}</td></tr>')
            for r in mr:
                d = r['date']; c = catn(r.get('category')) + (f' · {subn(r.get("subcategory"))}' if r.get('subcategory') and r.get('subcategory') not in ('Needs category',) else '')
                h.append(f'<tr><td>{d[8:]}/{d[5:7]}/{d[:4]}</td><td>{e(r.get("merchant") or "?")}</td><td>{e(c)}</td>' + ('' if entity else f'<td>{e(r.get("entity"))}</td>') + f'<td class="n">{money(r["total_myr"])}</td></tr>')
        h.append(f'<tr class="tot"><td colspan="{3 if entity else 4}">{e(T["sum"])}</td><td class="n">{money(tot)}</td></tr></tbody></table>')
    h.append('</body></html>')
    return '\n'.join(h)

CHROMES = ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', '~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
           '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge', '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser',
           '/Applications/Chromium.app/Contents/MacOS/Chromium',
           r'%ProgramFiles%\Google\Chrome\Application\chrome.exe', r'%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe',
           r'%LocalAppData%\Google\Chrome\Application\chrome.exe', r'%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe',
           r'%ProgramFiles%\Microsoft\Edge\Application\msedge.exe']        # Windows always has Edge
def find_chrome():
    for c in CHROMES:
        c = os.path.expandvars(os.path.expanduser(c))
        if os.path.exists(c): return c
    return shutil.which('google-chrome') or shutil.which('chromium')

def to_pdf(html_path, pdf_path, chrome=None):
    """Print the page to PDF with headless Chrome in its own throw-away profile (does not touch your open Chrome). -> True/False"""
    chrome = chrome or find_chrome()
    if not chrome: return False
    prof = tempfile.mkdtemp(prefix='ro_chrome_')
    try:
        subprocess.run([chrome, '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check', '--disable-background-networking', '--disable-component-update', '--disable-sync', '--disable-extensions', '--disable-default-apps', '--metrics-recording-only', f'--user-data-dir={prof}',
                        '--no-pdf-header-footer', f'--print-to-pdf={pdf_path}', pathlib.Path(os.path.abspath(html_path)).as_uri()],
                       capture_output=True, timeout=90, creationflags=sysdeps.NO_WINDOW)
        return os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 1000
    except Exception: return False
    finally: shutil.rmtree(prof, ignore_errors=True)

def make(out, rows, entity=None, start=None, end=None, lang='zh'):
    """-> (path, is_pdf). Saved under <results folder>/Reports/."""
    d = os.path.join(out, 'Reports'); os.makedirs(d, exist_ok=True)
    tag = '_'.join(x for x in [(entity or ('全部' if lang == 'zh' else 'All')).replace('/', '-'), start or '', end or ''] if x)
    base = os.path.join(d, f'{"支出总结" if lang == "zh" else "Spending summary"} {tag} {time.strftime("%Y%m%d-%H%M")}')
    hp = base + '.html'; open(hp, 'w', encoding='utf-8').write(build_html(rows, entity, start, end, lang))
    if to_pdf(hp, base + '.pdf'): os.remove(hp); return base + '.pdf', True
    return hp, False
