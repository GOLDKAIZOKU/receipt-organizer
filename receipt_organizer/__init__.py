__version__ = '1.0.1'
REPO = 'GOLDKAIZOKU/receipt-organizer'      # where new versions are published (GitHub Releases)

try:
    from . import sysdeps as _s
    _s.fix_opencv_paths()
except Exception:
    pass
