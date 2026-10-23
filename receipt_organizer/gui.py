"""The app window (Mac: WKWebView, Windows: Edge WebView2) around the local interface. No browser tab, no terminal.
   --selftest   check that everything the app needs is present, write the result to selftest.txt and exit (used by the automatic builds)."""
import os, sys
from . import ui, sysdeps, __version__

def _log_to_file():
    """The packaged Windows app has no console: keep messages in a log next to the settings."""
    if getattr(sys, 'frozen', False) or sys.stdout is None:
        os.makedirs(sysdeps.APPDIR, exist_ok=True)
        f = open(os.path.join(sysdeps.APPDIR, 'app.log'), 'a', encoding='utf-8', buffering=1)
        sys.stdout = sys.stderr = f

def selftest(out_file):
    lines = [f'version {__version__}', f'python {sys.version.split()[0]}', f'platform {sys.platform}']; ok = True
    optional = set(filter(None, os.environ.get('RO_SELFTEST_OPTIONAL', '').split(',')))   # e.g. 'ocr' on build servers without OCR languages
    def step(name, fn):
        nonlocal ok
        try: lines.append(f'OK   {name}: {fn()}')
        except Exception as e:
            if name in optional: lines.append(f'WARN {name}: {type(e).__name__}: {e}')
            else: ok = False; lines.append(f'FAIL {name}: {type(e).__name__}: {e}')
    import numpy as np, cv2
    from . import ocr_backend as ob, app, report, export, bills, fields  # noqa
    step('opencv', lambda: cv2.__version__)
    def ocr():
        img = np.full((160, 700, 3), 255, np.uint8)
        cv2.putText(img, 'TOTAL RM 12.50', (20, 100), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 0), 4)
        t = ob.text(img); assert '12' in t, f'read {t!r}'; return f'{ob.engine()} read {t!r}'
    step('ocr', ocr)
    step('webview', lambda: __import__('webview').__version__ if hasattr(__import__('webview'), '__version__') else 'imported')
    step('report html', lambda: len(report.build_html([dict(entity='A', date='2026-01-05', merchant='Shop', total_myr=10.0, category='Groceries', subcategory='', review='')])))
    step('excel', lambda: __import__('openpyxl').__version__)
    step('pdf maker', lambda: report.find_chrome() or 'none found (reports open as web page)')
    lines.append('RESULT ' + ('PASS' if ok else 'FAIL'))
    open(out_file, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
    return ok

def main():
    if '--selftest' in sys.argv:
        out = sys.argv[sys.argv.index('--selftest') + 1] if len(sys.argv) > sys.argv.index('--selftest') + 1 else 'selftest.txt'
        sys.exit(0 if selftest(out) else 1)
    _log_to_file()
    import webview
    out = os.environ.get('RECEIPT_ORGANIZER_DIR') or ui.remembered() or os.path.expanduser('~/Receipt Organizer')
    if not os.path.isdir(out): out = os.path.expanduser('~/Receipt Organizer')
    port = ui.serve(out)
    win = webview.create_window(f'Receipt Organizer {__version__}', f'http://127.0.0.1:{port}/', width=1280, height=840, min_size=(900, 600))
    def picker(prompt):
        kind = getattr(getattr(webview, 'FileDialog', None), 'FOLDER', None) or getattr(webview, 'FOLDER_DIALOG')
        r = win.create_file_dialog(kind)
        return (r[0] if isinstance(r, (list, tuple)) else r) if r else None
    sysdeps.PICKER = picker
    webview.start()

if __name__ == '__main__': main()
