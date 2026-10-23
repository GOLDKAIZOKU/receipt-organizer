import cv2, numpy as np, re, datetime
from collections import Counter
from . import ocr_backend as ob
# ---------- merchant directory (from user's table; aliases tolerate OCR noise) ----------
MERCH=[("MR.DIY",r"M\s*R\W{0,2}\s*D\W{0,2}\s*[I1l]\W{0,2}\s*Y|ME\s*D\W*[I1]\W*Y",),("Yang Claypot",r"YANG\s*CLAY\s*POT|CLAYPOT"),("Pantai Selamat",r"PANTAI\s*SELAMAT"),("ACE Hardware",r"\bACE\b.{0,30}HARDWARE|GIANT ACE"),("Bel Pasto Pizza",r"BEL\s*PASTO"),
("Xiao Li Jia",r"XIAO\s*L[I1]\s*J[I1]A|小李家"),("Chong Qing Impression",r"CHONG\s*QING|重庆印象"),("Sushi Mentai",r"SUSH[I1]\s*MENTA[I1]"),("KFC",r"\bKFC\b"),
("Bistro Fiore",r"B[I1]STRO\s*F[I1]ORE"),("Cempedak Bay",r"CEMPEDAK\s*BAY"),("Bingxue",r"B[I1]NGXUE|冰雪"),
("AEON Big",r"AEON\s*B[I1]G"),("AEON",r"\bAEON\b"),("Wheat Mart",r"W[HN]EAT\s*MART"),("Jaya Grocer",r"JAYA\s*GROCER"),("NSK Grocer",r"NSK\s*GROCER"),
("Village Grocer",r"V[I1]LLAGE\s*GROCER"),("Oriental Mart",r"OR[I1]ENTAL\s*MART"),("Pantai Selamat",r"PANTA[I1]\s*SELAMAT"),("Bilabila Mart",r"B[I1]LAB[I1]LA"),
("99 Speedmart",r"99\s*SPEED"),("Tunas Manja",r"TUNAS\s*MANJA"),("Shell",r"SHELL|BANGSAR PETROL|JET GOMBAK"),("Petron",r"PETRON"),("Petronas",r"PETRONAS"),("Caltex",r"CALTEX"),
("United Tyre Service",r"UNITED\s*TYRE"),("OptiSaver",r"OPT[I1]SAVER"),("Galaxy Sports",r"GAL[AI]XY\s*SPORTS|GALAXXY"),("Adidas",r"ADIDAS"),("Apple",r"APPLE\s*(MALAYSIA|THE EXCHANGE)"),
("TNB",r"TENAGA|\bTNB\b"),("PAIP",r"\bPAIP\b"),("Gula Cakery",r"GULA\s*CAKERY"),("Nando's",r"NANDO"),("Burger King/Cosmo",r"COSMO RESTAURANTS|BURGER\s*K"),("LH Foodcraft",r"LH\s*FOODCRAFT"),("Adaptis (card slip)",r"ADAPT[I1]S"),
("Guardian",r"GUARD[I1]AN\s*(HEALTH|PHARM|MALAYS|\(?M\))|^\s*GUARD[I1]AN\s*$"),("Watsons",r"WATSON'?S"),("Caring Pharmacy",r"CAR[I1]NG\s*PHARM"),("Big Pharmacy",r"\bB[I1]G\s*PHARM"),("Alpro Pharmacy",r"ALPRO"),("AA Pharmacy",r"\bAA\s*PHARM"),("Health Lane",r"HEALTH\s*LANE"),("Sunway Pharmacy",r"SUNWAY\s*PHARM"),
("Pet Lovers Centre",r"PET\s*LOVERS"),("Pets Wonderland",r"PETS?\s*WONDERLAND"),("Petsmore",r"PETSMORE"),("Pet World",r"PET\s*WORLD"),("Veterinary Clinic",r"VETER[I1]NAR|\bVET(S)?\s*(CLINIC|HOSP|CENTRE|CENTER)|KLINIK\s*HAIWAN"),("Pet Shop",r"PET\s*(SHOP|STORE|MART)|KEDAI\s*HAIWAN"),("Pharmacy",r"PHARMACY|FARMASI")]
MON={'JAN':1,'FEB':2,'MAR':3,'APR':4,'MAY':5,'MEI':5,'JUN':6,'JUL':7,'AUG':8,'AU6':8,'AUGUST':8,'OGO':8,'SEP':9,'SEPT':9,'OCT':10,'OKT':10,'NOV':11,'DEC':12,'DIS':12}
AMT=r"(?<![\d.])(\d{1,3}(?:,\d{3})+|\d{1,6})[.,]\s?(\d{2})(?!\d)"
def ocr_variants(img):
    """Several differently-processed readings of the same receipt; fields are voted across them."""
    g=cv2.cvtColor(img,cv2.COLOR_BGR2GRAY); T=lambda v: ob.text(cv2.cvtColor(v,cv2.COLOR_GRAY2BGR))
    c=cv2.createCLAHE(3.0,(8,8)).apply(g); u=cv2.resize(g,None,fx=1.5,fy=1.5,interpolation=cv2.INTER_CUBIC)
    b=cv2.adaptiveThreshold(cv2.GaussianBlur(u,(0,0),1.0),255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,cv2.THRESH_BINARY,35,11)
    return [T(g),T(c),T(cv2.createCLAHE(3.0,(8,8)).apply(u)),T(b)]
def header_variants(img):
    """Faded shop names: re-read only the top of the receipt with the background flattened and the contrast stretched."""
    h=img.shape[0]; top=img[:max(int(h*.22),200)]
    g=cv2.cvtColor(top,cv2.COLOR_BGR2GRAY); bg=cv2.GaussianBlur(g,(0,0),25)
    flat=cv2.normalize(cv2.divide(g,bg,scale=255),None,0,255,cv2.NORM_MINMAX)          # remove the printed watermark/background shading
    dark=np.clip((flat.astype(np.float32)/255)**3*255,0,255).astype(np.uint8)           # push faint grey ink darker
    up=cv2.resize(dark,None,fx=2.0,fy=2.0,interpolation=cv2.INTER_CUBIC)
    c=cv2.createCLAHE(4.0,(8,8)).apply(g)
    T=lambda v: ob.text(cv2.cvtColor(v,cv2.COLOR_GRAY2BGR))
    return [T(flat),T(dark),T(up),T(cv2.resize(c,None,fx=2.0,fy=2.0,interpolation=cv2.INTER_CUBIC))]
def clean_digits(t): return t.translate(str.maketrans({'O':'0','o':'0','D':'0','I':'1','l':'1','|':'1','S':'5','B':'8','Z':'2'}))
def fuzzy_mon(ch):
    ch=ch.upper().translate(str.maketrans({'5':'S','0':'O','1':'I','8':'B','6':'G','4':'A'}))
    if ch in MON: return MON[ch]
    c=[m for m in MON if len(m)==3 and len(ch)==3 and sum(a!=b for a,b in zip(m,ch))==1]
    return MON[c[0]] if len(c)==1 else None
def find_dates(text):
    out=[]
    for line in text.splitlines():
        L=line.strip()
        up=L.upper()
        for m in re.finditer(r'(?<!\d)(\d{1,2})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{2,4})(?!\d)',L):
            d,mo,y=[int(x) for x in m.groups()]
            out.append(('num',d,mo,y,line))
        for m in re.finditer(r'(?<!\d)(20\d{2})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{1,2})(?!\d)',L):
            y,mo,d=[int(x) for x in m.groups()]
            if len(m.group(3))==1: out.append(('clipped',d,mo,y,line)); continue   # e.g. 2026/09/2 - never confirm
            out.append(('iso',d,mo,y,line))
        for m in re.finditer(r'(?<![\d:])(\d{1,2})(?:ST|ND|RD|TH)?[\s\-/.,]{0,3}([A-Z0-9]{3}[A-Z]{0,6})[\s\-/.,\']{0,3}(20\d{2}|\d{2})(?![\d:])',up):   # 29AUG2026, 07-Oct-26, 15 Sept 2026
            g=m.group(2); mon=fuzzy_mon(g) or (fuzzy_mon(g[:3]) if g.isalpha() and len(g)>4 else None)
            if mon: out.append(('txt',int(m.group(1)),mon,int(m.group(3)),line))
        for m in re.finditer(r'(?<![A-Z])([A-Z]{3,9})\.?[\s\-]{0,2}(\d{1,2})(?:ST|ND|RD|TH)?,?[\s\-/.,]{0,3}(20\d{2})(?!\d)',up):          # Sep 15, 2026
            g=m.group(1); mon=fuzzy_mon(g) if len(g)<=4 else (MON.get(g) or fuzzy_mon(g[:3]))
            if mon: out.append(('txt',int(m.group(2)),mon,int(m.group(3)),line))
    return out
def valid(y,mo,d):
    if y<100: y+=2000
    if not(2025<=y<=2027): return None
    try: return datetime.date(y,mo,d)
    except: return None
SKIP=re.compile(r'EXPIR|EXP\b|RETURN|DUE|VALID|PRINT\s*ON|PRINTED|BEFORE|UNTIL|LAST DATE|START DATE',re.I)
def pick_date(texts, merchant):
    cnt=Counter(); ev={}; clipped=False
    for t in texts:
        for kind,a,b,c,line in find_dates(t):
            if kind=='clipped': clipped=True; continue
            if SKIP.search(line) and not re.search(r'ORDER',line,re.I): continue
            if kind in('iso','txt'): cands=[valid(c,b,a)]
            elif merchant and 'Medi' in merchant: cands=[valid(c,a,b)]
            else:
                cands=[valid(c,b,a)]
                if cands[0] is None: cands=[valid(c,a,b)]
            for dt in cands:
                if dt: cnt[dt]+=1; ev.setdefault(dt,line.strip()[:60])
    if not cnt: return None,0.0,None,['date clipped by scan edge - rescan needed' if clipped else 'date not readable']
    notes=[]
    dt,n=cnt.most_common(1)[0]; conf=round(n/sum(cnt.values()),2)
    for other in cnt:
        if other!=dt and (other.day,other.month)==(dt.day,dt.month) and other.year!=dt.year:
            conf=min(conf,0.4); notes.append(f'year conflict on receipt: {dt.year} vs {other.year}')
    if clipped: conf=min(conf,0.4); notes.append('another date on this receipt is clipped')
    return dt,conf,ev[dt],notes
TOTK=[(r'JUMLAH\s*(PERLU\s*)?(DI\s*)?BAYAR|JUMLAH\s*(BIL|KESELURUHAN|BESAR)|AMOUNT\s*DUE|TOTAL\s*AMOUNT\s*DUE|JUMLAH\s*BAYARAN',5),(r'\bAMAUN\b(?!\s*(CUKAI|SST|ASAS))',3),(r'GRAND\s*TOTAL',5),(r'NET\s*TOTAL',5),(r'TOTAL\s*\(?(RM|MYR)\)?',5),(r'TOTAL\s*AFTER',4),(r'TOTAL\s*SALES',3),(r'\bTOTAL\b',3),(r'AMOUNT\s*PAID|AMOUNT\b',2),(r'MASTER|CARD|VISA',1)]
BADT=re.compile(r'SUB\s*-?\s*TOTAL|TOTAL\s*(QTY|DISC|TENDER)|TOTAL\s*ITEM',re.I)
NOTAMT=re.compile(r'SAVING|SAVED|DISC|REBATE|CHANGE|ROUND|\\bTAX\\b|\\bSST\\b|\\bGST\\b|VOUCHER|POINT',re.I)   # amounts on these lines are never the total
def amounts(line):
    r=[]
    for m in re.finditer(AMT,line):
        try: r.append(float(m.group(1).replace(',','')+'.'+m.group(2)))
        except: pass
    for m in re.finditer(r'RM\s?(\d{1,6})[.,](\d)(?![\d.,])',line,re.I):            # "RM 31.7" printed with one decimal
        try: r.append(float(m.group(1)+'.'+m.group(2)+'0'))
        except: pass
    return r
ITEMLINE=re.compile(r'(?<!\d)(\d{1,3})\s*[xX]\s*(\d{1,5})[.,](\d{2})\s+(\d{1,6})[.,](\d{2})(?!\d)')
def item_sum(texts):
    """Sum of the item lines printed as '<qty>x<unit price>  <line amount>' in the best reading, or None when fewer than 3 such lines were read.
    A line only counts when qty x unit price equals its own line amount, so a misread digit drops that line instead of corrupting the sum."""
    best=None
    for t in texts:
        tot=0.0; n=0
        for m in ITEMLINE.finditer(t):
            q=int(m.group(1)); u=float(m.group(2)+'.'+m.group(3)); a=float(m.group(4)+'.'+m.group(5))
            if abs(q*u-a)<0.015: tot+=a; n+=1
        if n>=3 and (best is None or n>best[0]): best=(n,round(tot,2))
    return best
def total_from_items(texts, tot):
    """If the item lines add up to an amount that is printed on a subtotal/total/payment line, that is the total (a faded first digit cannot fool it).
    Returns (total, note) or None."""
    b=item_sum(texts)
    if not b: return None
    n,sm=b
    if tot is not None and abs(tot-sm)<0.015: return None
    key=re.compile(r'TOTAL|MASTER|VISA|CARD|AMOUNT',re.I)        # a SUBTOTAL line does not count: with tax or service charge the total is rightly higher than the items
    seen=any(abs(a-sm)<0.015 for t in texts for ln in t.splitlines() if key.search(ln) and not BADT.search(ln) for a in amounts(ln))
    if seen: return sm, f'Total taken from the sum of {n} item lines ({sm:.2f}), which is printed on a total/payment line (not a subtotal)'
    return None
def pick_total(texts):
    sc=Counter(); ev={}
    for t in texts:
        lines=t.splitlines()
        for i,line in enumerate(lines):
            if BADT.search(line): continue
            for pat,w in TOTK:
                if re.search(pat,line,re.I):
                    am=amounts(line) or (amounts(lines[i+1]) if i+1<len(lines) and not NOTAMT.search(lines[i+1]) else [])
                    if not am: am=amounts(lines[i-1]) if i>0 and not NOTAMT.search(lines[i-1]) else []
                    for a in am[-2:] if w<5 else am[-1:]:
                        if 0<a<100000: sc[a]+=w; ev.setdefault(a,line.strip()[:60])
                    break
    if not sc:                                                                     # no total line read: the amount paid by card / cash, else the subtotal (low confidence: shown for checking)
        for t in texts:
            for l in t.splitlines():
                if re.search(r'MASTER|VISA|DEBIT|CREDIT|\bCASH\b|TUNAI|E-?WALLET|TNG|GRABPAY|BOOST|DUITNOW|QR\s*PAY|PAID',l,re.I) and not NOTAMT.search(l):
                    for a in amounts(l)[-1:]:
                        if 0<a<100000: sc[a]+=2; ev.setdefault(a,l.strip()[:60])
                if re.search(r'SUB\s*-?\s*TOTAL',l,re.I):
                    for a in amounts(l)[-1:]:
                        if 0<a<100000: sc[a]+=1; ev.setdefault(a,l.strip()[:60])
        if not sc: return None,0.0,None
        a,_s=sc.most_common(1)[0]; return a,0.4,ev[a]
    saved={x for t in texts for l in t.splitlines() if re.search(r'SAVING|SAVED|DISCOUNT|SPEC\.?\s*DISC',l,re.I) for x in amounts(l)}
    if len(sc)>1:
        for x in saved: sc.pop(x,None) if len(sc)>1 else None
    a,s=sc.most_common(1)[0]; tot=sum(sc.values())
    return a,round(s/tot,2),ev[a]
LEARNED=[]          # shop names the user typed in corrections; set by app.finalize, so a shop corrected once is recognised next time
COMPANY=re.compile(r"\b(SDN\.?\s*BHD|SDN\b|BERHAD|ENTERPRISES?|TRADING|RESTAURANTS?|RESTORAN|\bPLT\b|MARKETING|HOLDINGS|CORPORATION|FOODS?\s+MALAYSIA)\b",re.I)
NOTSHOP=re.compile(r"^\W*(ITEM|QTY|PRICE|TABLE|PHONE|FHONE|TEL|FAX|LICENSEE|SOLD\s*TO|ST\s*NO|POS\b|CASHIER|DATE|TIME|INVOICE|RECEIPT|ORDER|BILL\b|TAX\s*INVOICE|SIMPLIFIED|WELCOME|THANK|COMPANY\s*NO|REG|GST|SST|CO\.?\s*NO|BRN)|LINGKARAN|JALAN|\bJLN\b|LORONG|TAMAN|PERSIARAN|MID\s*VALLEY|KUALA LUMPUR|SELANGOR|PAHANG|\b\d{5}\b|@|WWW|HTTP|\.COM",re.I)
def _squash(s): return re.sub(r'[^A-Z0-9\u4e00-\u9fff]','',(s or '').upper())
def _company(l):
    n=re.sub(r"\(?\b\d{3,}[\w\-]*\)?|\bSDN\.?\s*BHD\.?|\bSDN\b|\bBERHAD\b|\(M\)|\bBHD\b","",l)
    return re.sub(r"\s{2,}"," ",n).strip(" .,-:")[:40]
def pick_merchant(texts):
    blob="\n".join(texts); head="\n".join("\n".join(t.splitlines()[:14]) for t in texts)
    for name,pat in MERCH:
        if re.search(pat,head,re.I): return name,'header'
    for name,pat in MERCH:
        if re.search(pat,blob,re.I): return name,'body'
    hs=_squash(head)
    for n in sorted(LEARNED,key=len,reverse=True):                                  # a shop the user named before
        q=_squash(n)
        if len(q)>=5 and q in hs: return n,'learned'
    for t in texts[:2]:                                                               # the company line ("GERBANG ALAF RESTAURANTS SDN BHD")
        for l in t.splitlines()[:12]:
            if COMPANY.search(l) and not NOTSHOP.search(_company(l)) and len(re.findall('[A-Za-z]',_company(l)))>=4: return _company(l),'company'
    for l in texts[0].splitlines()[:8]:
        l=l.strip()
        if len(re.findall('[\u4e00-\u9fff]',l))>=2 and not re.search(r'\d',l): return l[:40],'unmatched-first-line'     # a Chinese shop name
    # fallback: first line with letters
    for l in texts[0].splitlines()[:8]:
        l=l.strip()
        if re.search(r'SST|REG\.?\s*NO|GST|TEL|PHONE|INVOICE|RECEIPT|\d{5,}|SDN|SEN\s*BH|BH[DE]\b|PLEASE|\bLOT\b|J[AE]LAN|\bJLN\b|TAMAN|LORONG|PERSIARAN|BANDAR|KUALA|PETALING|SELANGOR|WILAYAH|\bNO\.?\s*\d|SCAN|QR|WWW|HTTP|\.HTML|\.COM|/',l,re.I) or NOTSHOP.search(l): continue
        if len(re.findall('[A-Za-z]',l))>=5: return l[:40],'unmatched-first-line'
    return None,None
def doc_no(texts):
    for t in texts:
        m=re.search(r'(INVOICE|INV|RECEIPT|BILL)\s*(NO|#|NUMBER)?\s*[:.]?\s*([A-Z0-9\-/]{5,24})',t,re.I)
        if m and re.search(r'\d',m.group(3)): return m.group(3)
    return None
def sst(texts):
    for t in texts:
        m=re.search(r'SST\s*(ID|NO|REG)?\s*[:.]?\s*([A-Z]\d{2}[\-\s]\d{4}[\-\s]\d{8})',t,re.I)
        if m: return re.sub(r'\s','',m.group(2))
    return None

def subtotal_of(texts):
    v=[a for t in texts for l in t.splitlines() if re.search(r'SUB\s*-?\s*TOTAL',l,re.I) for a in amounts(l)]
    return max(v) if v else None
def repair_total(tot,texts):
    """If the picked total is below the subtotal (e.g. 2.05 for 72.05), look for a total-like amount in a sane range above it.
    Returns (value, note). The result is only ever a suggestion."""
    sub=subtotal_of(texts)
    if sub is None or tot is None or tot>=sub-0.5: return tot,None
    if tot>=0.8*sub: return tot,f'total {tot} is a little below subtotal {sub} (discount?)'   # your receipts: these were all discounts, never misreads
    c=Counter()
    for t in texts:
        for l in t.splitlines():
            if re.search(r'TOTAL|AMOUNT|NETT?|CARD|MASTER|VISA|PAYMENT|DUE',l,re.I) and not re.search(r'SUB\s*-?\s*TOTAL',l,re.I):
                for a in amounts(l):
                    if sub-0.5<=a<=sub*1.30: c[a]+=1
    if c: return c.most_common(1)[0][0],f'total {tot} was below subtotal {sub}; replaced by {c.most_common(1)[0][0]} (confirm)'
    return tot,f'total {tot} is below subtotal {sub} - probable misread'


# ---------- card terminal slips (bank charge slips) ----------
# On a bank slip the bank's name is printed at the top and the SHOP's name is on the line(s) right below it.
BANKS = r"PUBL[I1]C\s*BANK|MAYBANK|MALAYAN\s*BANKING|\bC[I1]MB\b|\bRHB\b|HONG\s*LEONG|\bAM\s*BANK|AMBANK|BANK\s*[I1]SLAM|\bUOB\b|\bOCBC\b|\bHSBC\b|STANDARD\s*CHARTERED|ALL[I1]ANCE\s*BANK|\bAFF[I1]N\b|\bBSN\b|BANK\s*RAKYAT|AGROBANK|MBSB|ADAPT[I1]S|\bGHL\b|\bREVENUE\s*MONSTER|\bKIPLE\b|\bIPAY88\b|FIUU|RAZER\s*MERCHANT"
SLIPKW = r"APPROVAL\s*CODE|APPR\s*CODE|\bTID\b|\bMID\b|BATCH\s*N|TRACE\s*N|\bRREF|CUSTOMER\s*COPY|CARDHOLDER|NO\s*PIN\s*REQUIRED|NO\s*SIGNATURE|ENTRY\s*(MODE|TYPE)|CONTACTLESS|\bAID\s*[:.]?\s*A0"
_NOTNAME = r"^\W*$|SALE\b|VOID|SETTLEMENT|BATCH|\bTID\b|\bMID\b|HOST|INVOICE|TRACE|DATE|TIME|CARD|VISA|MASTER|AMEX|UNIONPAY|MYDEBIT|CUSTOMER|MERCHANT\s*COPY|^[\d\W]+$|^\W*BANK\W*$"
_ADDRESS = r"^\W*\d+\s*[,&\-]|\bJ(A)?LA?N\b|\bJLN\b|\bLRG\b|LORONG|TAMAN|\bTMN\b|\bLOT\b|PERSIARAN|\b\d{5}\b"
def card_slip(texts):
    """-> (True/False, shop name or None). A slip has a bank / terminal name near the top and at least two slip words."""
    for t in texts:
        L = [l.strip() for l in t.splitlines() if l.strip()]
        kw = len({m.group(0).upper() for m in re.finditer(SLIPKW, t, re.I)})
        bi = next((i for i, l in enumerate(L[:8]) if re.search(BANKS, l, re.I)), None)
        if kw < 2 or bi is None: continue          # a shop receipt can print card details too; a slip has the bank's name at the top
        start = bi + 1
        for l in L[start:start + 4]:
            c, src = pick_merchant([l])
            if src in ('header', 'body'): return True, c                       # e.g. "99 SPEED MART-1201-A" -> 99 Speedmart
            if re.search(BANKS, l, re.I) or re.search(_NOTNAME, l, re.I) or re.search(_ADDRESS, l, re.I) or len(re.findall('[A-Za-z]', l)) < 3: continue
            name = re.sub(r'\s+', ' ', l).strip(' .,:-')[:40]
            canon, src = pick_merchant([name])          # e.g. a slip from "MR DIY" -> the directory name MR.DIY
            return True, (canon if src in ('header', 'body') else name.title() if name.isupper() else name)
        return True, None
    return False, None


# ---------- utility bills (electricity, water, phone, land / assessment tax ...) ----------
BILLS = [  # (pattern, shop name, Utilities subcategory)
 (r"TENAGA\s*NASIONAL|\bTNB\b|BIL\s*ELEKTRIK", "TNB", "Electricity"),
 (r"AIR\s*SELANGOR|PENGURUSAN\s*AIR\s*SELANGOR", "Air Selangor", "Water"),
 (r"PENGURUSAN\s*AIR\s*PAHANG|\bPAIP\b", "PAIP", "Water"),
 (r"RANHILL|\bSAJ\b|AIR\s*KELANTAN|SYARIKAT\s*AIR|LEMBAGA\s*AIR|\bSAINS\b|PBA\s*HOLDINGS|BIL\s*AIR", None, "Water"),
 (r"INDAH\s*WATER|\bIWK\b", "Indah Water", "Sewerage"),
 (r"\bUNIFI\b|TELEKOM\s*MALAYSIA|\bTM\s*(NET|UNIFI)", "Unifi", "Internet & phone"),
 (r"\bMAXIS\b|HOTLINK", "Maxis", "Internet & phone"), (r"CELCOM", "CelcomDigi", "Internet & phone"), (r"\bDIGI\b", "CelcomDigi", "Internet & phone"),
 (r"U\s*MOBILE", "U Mobile", "Internet & phone"), (r"TIME\s*DOTCOM|\bTIME\s*FIBRE", "TIME", "Internet & phone"), (r"\bASTRO\b", "Astro", "TV & streaming"),
 (r"GAS\s*MALAYSIA", "Gas Malaysia", "Gas"),
 (r"CUKAI\s*TANAH|HASIL\s*TANAH|PEJABAT\s*TANAH", "Cukai Tanah (land tax)", "Assessment & land tax"),
 (r"CUKAI\s*(PINTU|TAKSIRAN)|MAJLIS\s*(BANDARAYA|PERBANDARAN|DAERAH)|\bDBKL\b|DEWAN\s*BANDARAYA", "Cukai Taksiran (assessment)", "Assessment & land tax"),
]
BILLWORDS = r"NO\.?\s*AKAUN|ACCOUNT\s*N(O|UMBER)|TARIKH\s*BIL|BILL\s*DATE|JUMLAH\s*(PERLU\s*DI\s*BAYAR|BIL)|AMOUNT\s*DUE|TEMPOH\s*BIL|BILLING\s*PERIOD|BAYARAN\s*SEBELUM|PAY\s*BEFORE|TUNGGAKAN|NO\.?\s*BIL\b|BIL\s*(SEMASA|DIGITAL|CUKAI)"
def utility_bill(texts):
    """-> (True/False, shop name or None, subcategory or None). A bill names a utility / council, or has at least two bill words."""
    blob = "\n".join(texts); words = len({m.group(0).upper() for m in re.finditer(BILLWORDS, blob, re.I)})
    for pat, name, sub in BILLS:
        if re.search(pat, blob, re.I) and (words >= 1 or name in ('TNB', 'Indah Water', 'Cukai Tanah (land tax)', 'Cukai Taksiran (assessment)')): return True, name, sub
    if words >= 2: return True, None, 'Other bills'
    return False, None, None
