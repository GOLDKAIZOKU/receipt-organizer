"""Export for the accountant: plain CSV + Excel, grouped by entity and month.

This is a generic layout. It is NOT an import file for any specific accounting package (e.g. UBS):
the accountant's own import format has to be confirmed before we produce one.
Rows that still need the user's confirmation are kept apart so they are never mistaken for final figures.
"""
import csv, os, json, time
from collections import defaultdict

COLS = ['Entity', 'Date', 'Merchant', 'Category', 'Subcategory', 'Total (RM)', 'Tax tag (to confirm)', 'Status', 'Needs checking because', 'Receipt file']
REASON = {'Check rotation': 'rotation not certain', 'Check crop': 'crop may be wrong', 'Date missing': 'date not readable',
          'Confirm date': 'date not certain', 'Confirm merchant': 'merchant name not certain', 'Confirm total': 'two readers disagree on the total', 'Possible duplicate': 'may be a duplicate scan'}


def _fmt_date(d):
    if not d: return ''
    y, m, dd = d.split('-'); return f'{dd}/{m}/{y}'                       # D/M/Y, the Malaysian convention


def _row(r):
    why = '; '.join(REASON.get(x, x) for x in (r.get('review') or '').split(' / ') if x)
    return [r.get('entity', ''), _fmt_date(r.get('date')), r.get('merchant') or '', r.get('category') or '', r.get('subcategory') or '',
            None if r.get('total_myr') is None else round(float(r['total_myr']), 2), r.get('tax_tag') or '', 'Card slip (matched)' if r.get('card_slip_of') else 'Duplicate' if r.get('duplicate') else 'On hold' if r.get('hold') else 'To check' if r.get('review') else 'Confirmed', why, r.get('file') or '']


def build(out, log=print):
    out = os.path.abspath(out); vp = os.path.join(out, '.work', 'view.json')
    if not os.path.exists(vp): raise FileNotFoundError('No results yet in this folder.')
    rows = json.load(open(vp)); dest = os.path.join(out, 'For Accountant', time.strftime('%Y%m%d_%H%M%S')); os.makedirs(dest)
    by = defaultdict(list)
    for r in rows: by[r.get('entity', 'Personal')].append(r)
    made = []
    # one flat CSV with everything (UTF-8 with BOM so Excel opens it correctly)
    p = os.path.join(dest, 'all_receipts.csv')
    with open(p, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f); w.writerow(COLS)
        for r in sorted(rows, key=lambda r: (r.get('entity', ''), r.get('date') or '9999', r.get('merchant') or '')): w.writerow(_row(r))
    made.append(p)
    try: import openpyxl; from openpyxl.styles import Font, PatternFill, Alignment
    except ImportError: log('openpyxl is not installed, so only the CSV was written.'); return dest, made
    for ent, rs in by.items():
        wb = openpyxl.Workbook(); summ = wb.active; summ.title = 'Summary'
        rs_all = rs; rs = [r for r in rs if not r.get('duplicate') and not r.get('card_slip_of')]; dups = [r for r in rs_all if r.get('duplicate')]; slips = [r for r in rs_all if r.get('card_slip_of')]   # confirmed second scans: listed, never counted
        ok = [r for r in rs if not r.get('review') and not r.get('hold')]; chk = [r for r in rs if r.get('review') or r.get('hold')]
        months = defaultdict(list)
        bills_ok = [r for r in ok if r.get('is_bill')]
        msum = defaultdict(list)                                # summary: receipts AND utility bills; month sheets: receipts only (bills get their own sheet)
        for r in ok:
            msum[(r.get('date') or '')[:7]].append(r)
            if not r.get('is_bill'): months[(r.get('date') or '')[:7]].append(r)
        head = Font(bold=True); fill = PatternFill('solid', fgColor='DDE7EA')

        def sheet(title, items):
            ws = wb.create_sheet(title[:31]); ws.append(COLS)
            for c in ws[1]: c.font = head; c.fill = fill
            for r in sorted(items, key=lambda r: (r.get('date') or '9999', r.get('merchant') or '')): ws.append(_row(r))
            n = ws.max_row
            if n > 1:
                ws.append(['', '', '', '', 'Total', f'=SUM(F2:F{n})']); ws.cell(ws.max_row, 5).font = head; ws.cell(ws.max_row, 6).font = head
            for col, wd in zip('ABCDEFGHIJ', (16, 12, 28, 26, 26, 14, 22, 11, 34, 60)): ws.column_dimensions[col].width = wd
            for row in ws.iter_rows(min_row=2, min_col=6, max_col=6):
                for c in row: c.number_format = '#,##0.00'
            ws.freeze_panes = 'A2'; return ws
        # summary: confirmed receipts only, month x category
        cats = sorted({(r.get('category') or 'Uncategorised') for r in ok}); ms = sorted(msum)
        summ.append([f'{ent}: confirmed receipts only (RM)']); summ['A1'].font = Font(bold=True, size=13); summ.append([])
        summ.append(['Month'] + cats + ['Total']);
        for c in summ[3]: c.font = head; c.fill = fill
        for m in ms:
            vals = [sum(float(r['total_myr']) for r in msum[m] if (r.get('category') or 'Uncategorised') == c and r.get('total_myr') is not None) for c in cats]
            summ.append([m or 'No date'] + [round(v, 2) for v in vals] + [round(sum(vals), 2)])
        for row in summ.iter_rows(min_row=4):
            for c in row[1:]: c.number_format = '#,##0.00'
        summ.append([]); summ.append([f'{len(chk)} receipt(s) still need checking and are NOT included above: see the "To check" sheet.'])
        summ.column_dimensions['A'].width = 16
        for m in ms:
            if months.get(m): sheet(m or 'No date', months[m])
        if bills_ok: sheet('Utility bills', bills_ok)
        if dups: sheet('Duplicates (not counted)', dups)
        if slips: sheet('Card slips (not counted)', slips)
        if chk: ws = sheet('To check', chk)
        safe = ''.join(c if c.isalnum() or c in '-_ ' else '_' for c in ent).strip() or 'entity'
        p = os.path.join(dest, f'{safe}_receipts.xlsx'); wb.save(p); made.append(p)
    open(os.path.join(dest, 'README.txt'), 'w', encoding='utf-8').write(
        'Receipts exported for the accountant.\n- Dates are D/M/Y. Amounts are in RM as read from the receipt.\n'
        '- "Confirmed" rows had no open question. "To check" rows still need a person to look at the receipt image.\n'
        '- Receipt file = the image path relative to the results folder.\n'
        '- Tax tag = the user\'s own label (e.g. a personal tax-relief heading). It is a note for the accountant, not a tax ruling or a claim.\n- This is a general-purpose list. It is not an import file for any accounting software, and it is not a tax or compliance statement.\n')
    return dest, made


if __name__ == '__main__':
    import sys; d, m = build(sys.argv[1]); print(d); print('\n'.join(m))
