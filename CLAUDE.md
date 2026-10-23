# Notes for whoever works on this next

Receipt Organizer: a desktop app (Python, local web page in a native window via pywebview) that cuts receipts out of scanned pages,
reads shop/date/total, and files them. The owner speaks Chinese; reply in Chinese, keep the interface bilingual (Chinese strings in
`ui/index.html`, English through the `EN_STR` / `EN_RE` tables at the bottom of that file).

## Layout
- `receipt_organizer/app.py` reading pipeline (`run`, `read_fields`, `decide`) and `finalize` (applies `corrections.json`, files copies, writes `.work/view.json`). `upgrade_readings` re-reads older records in the background when the app opens (bump `FIELDSV` / `SLIPV` when reading rules improve).
- `fields.py` merchant / date / total / card slip / utility bill rules. `catalog.py` categories. `bills.py` utility bills -> user's bills folder by type/property/year (learns account numbers). `report.py` PDF summary (headless Chrome/Edge). `export.py` Excel.
- `ui.py` local HTTP server (127.0.0.1, token) + JSON API; `ui/index.html` the whole interface. `gui.py` window + `--selftest`.
- `sysdeps.py` everything Mac/Windows-specific. `ocr_backend.py` Apple Vision (Mac), Windows.Media.Ocr (Windows), Tesseract fallback.
- `updater.py` one-click update from GitHub Releases (Mac: replaces source files; Windows: helper .bat swaps the packaged folder).

## Rules
- Never modify the user's original scans. Never delete user data: deletions go to `.work/deleted.json`, old outputs to `.work/superseded/`.
- User corrections (`corrections.json`) always win over OCR/AI.
- Mac runs Python 3.9 (system): no `match`, no `X | Y` type syntax.
- Nothing personal in this public repo (no names, paths, emails, sample receipts). The bills folder path lives in the user's settings, not in code.

## Releasing a new version (Mac and Windows together)
1. Set `__version__` in `receipt_organizer/__init__.py`, add a `## x.y.z` section to `CHANGELOG.md`.
2. `git commit` and `git push` to `main`.
3. `.github/workflows/release.yml` sees a version with no Release yet, builds + self-tests the Windows exe and the Mac package and publishes the Release; installed apps offer the update.
