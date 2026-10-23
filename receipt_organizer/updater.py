"""One-click updates from GitHub Releases.
Mac (runs from its own folder with a private Python): the program files are replaced, the old ones are kept as a backup.
Windows (packaged app): the new version is unpacked, a small helper waits for the app to close, copies it over and starts it again.
Your receipts, settings and corrections are stored elsewhere and are never touched by an update."""
import json, os, re, shutil, subprocess, sys, tempfile, threading, time, urllib.request, zipfile
from . import __version__, REPO, sysdeps

PKG = os.path.dirname(os.path.abspath(__file__))
FROZEN = getattr(sys, 'frozen', False)
STATE = dict(checked=None, latest=None, notes='', asset=None, page=None, error=None, busy=False, step='', ready=False)

def _v(s): return tuple(int(x) for x in re.findall(r'\d+', s or '')[:3]) or (0,)
def newer(a, b): return _v(a) > _v(b)

def asset_name(tag):
    v = tag.lstrip('v')
    return f'ReceiptOrganizer-Windows-{v}.zip' if sysdeps.WIN else f'ReceiptOrganizer-Mac-{v}.zip'

def check(force=False):
    """Ask GitHub for the latest release (at most once an hour unless forced). Never raises."""
    if not force and STATE['checked'] and time.time() - STATE['checked'] < 3600: return info()
    try:
        req = urllib.request.Request(f'https://api.github.com/repos/{REPO}/releases/latest', headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'ReceiptOrganizer'})
        r = json.load(urllib.request.urlopen(req, timeout=8)); tag = r.get('tag_name', '')
        want = asset_name(tag); a = next((x for x in r.get('assets', []) if x.get('name') == want), None)
        STATE.update(checked=time.time(), latest=tag.lstrip('v'), notes=(r.get('body') or '')[:2000], asset=a and a.get('browser_download_url'), page=r.get('html_url'), error=None)
    except Exception as e:
        STATE.update(checked=time.time(), error=str(e))
    return info()

def info():
    return dict(current=__version__, latest=STATE['latest'], available=bool(STATE['latest'] and newer(STATE['latest'], __version__) and STATE['asset']),
                notes=STATE['notes'], page=STATE['page'], error=STATE['error'], busy=STATE['busy'], step=STATE['step'], ready=STATE['ready'],
                can_auto=FROZEN and sysdeps.WIN or (not FROZEN and os.path.exists(os.path.join(PKG, 'ui', 'index.html'))))

def _download(url, dst):
    req = urllib.request.Request(url, headers={'User-Agent': 'ReceiptOrganizer'})
    with urllib.request.urlopen(req, timeout=60) as r, open(dst, 'wb') as f: shutil.copyfileobj(r, f)

def _apply_source(zp, tmp):
    """Mac / running from source: replace the receipt_organizer folder; keep the old one as a backup."""
    with zipfile.ZipFile(zp) as z: z.extractall(tmp)
    new = next((os.path.join(d, 'receipt_organizer') for d, ds, _ in os.walk(tmp) if 'receipt_organizer' in ds and os.path.exists(os.path.join(d, 'receipt_organizer', '__init__.py'))), None)
    if not new: raise ValueError('The download does not contain the program.')
    root = os.path.dirname(PKG); bak = os.path.join(sysdeps.APPDIR, 'backups', f'program-{__version__}-{time.strftime("%Y%m%d-%H%M%S")}')
    os.makedirs(os.path.dirname(bak), exist_ok=True); shutil.copytree(PKG, bak, ignore=shutil.ignore_patterns('__pycache__'))
    STATE['step'] = 'installing'
    for name in os.listdir(new):                       # copy over, file by file (the running program keeps working until restart)
        s, d = os.path.join(new, name), os.path.join(PKG, name)
        if os.path.isdir(s): shutil.copytree(s, d, dirs_exist_ok=True)
        else: shutil.copy2(s, d)
    top = os.path.dirname(new)
    for extra in ('requirements-mac.txt', 'mac', 'README.md'):
        s = os.path.join(top, extra)
        if os.path.isdir(s): shutil.copytree(s, os.path.join(root, extra), dirs_exist_ok=True)
        elif os.path.exists(s): shutil.copy2(s, os.path.join(root, extra))
    req = os.path.join(root, 'requirements-mac.txt')
    if sysdeps.MAC and os.path.exists(req):             # new libraries, if a version needs them
        STATE['step'] = 'libraries'
        subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', '-r', req], capture_output=True, timeout=900)

def _apply_windows(zp, tmp):
    """Packaged Windows app: unpack, then a helper copies it over once this app has closed (a running .exe cannot be replaced)."""
    with zipfile.ZipFile(zp) as z: z.extractall(tmp)
    exe = next((os.path.join(d, 'ReceiptOrganizer.exe') for d, _, fs in os.walk(tmp) if 'ReceiptOrganizer.exe' in fs), None)
    if not exe: raise ValueError('The download does not contain ReceiptOrganizer.exe.')
    src = os.path.dirname(exe); dst = os.path.dirname(sys.executable)
    bat = os.path.join(tmp, 'update.bat')
    open(bat, 'w', encoding='mbcs' if sysdeps.WIN else 'utf-8').write(
        '@echo off\r\n'
        f':wait\r\ntasklist /FI "PID eq {os.getpid()}" | find "{os.getpid()}" >nul && (timeout /t 1 /nobreak >nul & goto wait)\r\n'
        f'robocopy "{src}" "{dst}" /MIR /R:3 /W:1 /NFL /NDL /NJH /NJS >nul\r\n'
        f'start "" "{os.path.join(dst, "ReceiptOrganizer.exe")}"\r\n')
    STATE['bat'] = bat

def start():
    """Download and install the latest version in the background; the page polls info()."""
    if STATE['busy']: return info()
    if not (STATE['asset'] and STATE['latest'] and newer(STATE['latest'], __version__)): check(force=True)
    if not STATE['asset']: raise ValueError('No new version to install.')
    STATE.update(busy=True, step='downloading', error=None, ready=False)
    def go():
        try:
            tmp = tempfile.mkdtemp(prefix='ro_update_'); zp = os.path.join(tmp, 'update.zip'); _download(STATE['asset'], zp)
            STATE['step'] = 'unpacking'
            if FROZEN and sysdeps.WIN: _apply_windows(zp, os.path.join(tmp, 'new'))
            else: _apply_source(zp, os.path.join(tmp, 'new'))
            STATE.update(step='done', ready=True)
        except Exception as e: STATE.update(error=str(e), step='failed')
        STATE['busy'] = False
    threading.Thread(target=go, daemon=True).start()
    return info()

def restart():
    """Close and open again with the new version."""
    if FROZEN and sysdeps.WIN and STATE.get('bat'):
        subprocess.Popen(['cmd', '/c', STATE['bat']], creationflags=0x00000008 | sysdeps.NO_WINDOW)   # DETACHED_PROCESS
    elif sysdeps.MAC:
        app = os.path.expanduser('~/Applications/Receipt Organizer.app')
        cmd = f'sleep 1; open "{app}"' if os.path.exists(app) else f'sleep 1; cd "{os.path.dirname(PKG)}" && "{sys.executable}" -m receipt_organizer.gui'
        subprocess.Popen(['/bin/sh', '-c', cmd], start_new_session=True)
    else:
        subprocess.Popen([sys.executable, '-m', 'receipt_organizer.gui'], cwd=os.path.dirname(PKG))
    threading.Timer(0.5, lambda: os._exit(0)).start()
