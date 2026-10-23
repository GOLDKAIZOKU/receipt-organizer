"""Everything that differs between Mac and Windows lives here: where settings are kept, opening a file or folder,
the folder picker, and file names with non-English characters for OpenCV on Windows."""
import os, sys, subprocess

MAC, WIN = sys.platform == 'darwin', sys.platform.startswith('win')

def appdir():
    """Settings, learned bills, logs. Not inside the program folder, so updates never touch them."""
    if MAC: d = os.path.expanduser('~/Library/Application Support/ReceiptOrganizer')
    elif WIN: d = os.path.join(os.environ.get('APPDATA') or os.path.expanduser('~'), 'ReceiptOrganizer')
    else: d = os.path.join(os.environ.get('XDG_CONFIG_HOME') or os.path.expanduser('~/.config'), 'ReceiptOrganizer')
    return d

APPDIR = appdir()
CFG = os.path.join(APPDIR, 'config.json')
ENT_FILE = os.path.join(APPDIR, 'entities.txt')

def open_path(p):
    """Show a file or folder in Finder / Explorer / the default app."""
    try:
        if MAC: subprocess.run(['open', p])
        elif WIN: os.startfile(p)        # noqa: works on Windows only
        else: subprocess.run(['xdg-open', p])
    except Exception: pass

PICKER = None     # set by the window (gui.py): a native folder dialog that works on both systems
def pick_folder(prompt='Choose a folder'):
    if PICKER:
        try: return PICKER(prompt)
        except Exception: pass
    if MAC:
        try:
            r = subprocess.run(['osascript', '-e', f'POSIX path of (choose folder with prompt "{prompt}")'], capture_output=True, text=True, timeout=300)
            return r.stdout.strip() or None
        except Exception: return None
    if WIN:
        ps = ('Add-Type -AssemblyName System.Windows.Forms; $d = New-Object System.Windows.Forms.FolderBrowserDialog; '
              f'$d.Description = "{prompt}"; if ($d.ShowDialog() -eq "OK") {{ $d.SelectedPath }}')
        try:
            r = subprocess.run(['powershell', '-NoProfile', '-STA', '-Command', ps], capture_output=True, text=True, timeout=300, creationflags=0x08000000)
            return r.stdout.strip() or None
        except Exception: return None
    return None

NO_WINDOW = 0x08000000 if WIN else 0     # subprocess flag: no black console window flashing up on Windows

def fix_opencv_paths():
    """OpenCV on Windows cannot open paths with Chinese (or other non-English) characters. Route reads/writes through numpy."""
    if not WIN: return
    import cv2, numpy as np
    if getattr(cv2, '_ro_patched', False): return
    _read, _write = cv2.imread, cv2.imwrite
    def imread(path, flags=cv2.IMREAD_COLOR):
        try:
            data = np.fromfile(path, dtype=np.uint8)
            return cv2.imdecode(data, flags) if data.size else None
        except Exception: return _read(path, flags)
    def imwrite(path, img, params=None):
        try:
            ok, buf = cv2.imencode(os.path.splitext(path)[1] or '.jpg', img, params or [])
            if ok: buf.tofile(path)
            return ok
        except Exception: return _write(path, img, params or [])
    cv2.imread, cv2.imwrite, cv2._ro_patched = imread, imwrite, True
