# Receipt Organizer · 单据整理

Scan your receipts, invoices and utility bills; the app cuts out each one, reads the shop, date and total, and files them by owner / year / month.
Everything runs on your own computer. Nothing is uploaded.

扫描单据、发票和水电账单，App 会自动切出每一张，读出商家、日期和金额，按 归属 / 年 / 月 整理好。全部在你自己的电脑上处理，不会上传。

## What it does · 功能

- Cuts several receipts out of one scanned page, straightens them, joins long receipts (or re-crop by hand)
- Reads shop / date / total (Apple Vision on Mac, Windows OCR on Windows; optional local AI through [Ollama](https://ollama.com) for faded receipts)
- Asks you only about what it is unsure of; learns shop names and categories from your corrections
- Bank card slips are paired with their receipts and not counted twice; duplicate scans are flagged, with delete and undo
- Utility bills (electricity, water, phone, land tax …) are recognised and copied into your own bills folder by type / property / year
- PDF spending summary to share, and Excel export for the accountant
- Chinese / English interface

## Install · 安装

**Windows**
1. Download `ReceiptOrganizer-Windows-x.y.z.zip` from [Releases](../../releases/latest).
2. Unzip it, e.g. to `C:\ReceiptOrganizer`, and double-click `ReceiptOrganizer.exe`.
   Windows may warn that the app is unknown: click *More info* → *Run anyway* (the app is not code-signed).

**Mac**
1. Download `ReceiptOrganizer-Mac-x.y.z.zip` from [Releases](../../releases/latest) and unzip it to a folder you keep (e.g. your home folder).
2. Double-click `mac/setup_mac.command` once (right-click → Open if macOS blocks it). It puts *Receipt Organizer* in your Applications folder.

## Updates · 更新

The app checks GitHub when it opens. When a new version is out it shows **New version … · Update**; click it, then **Restart**.
Mac and Windows get the same version at the same time. Your receipts, settings and corrections are stored outside the program and are never changed by an update.

App 打开时会检查 GitHub。有新版本会提示「有新版本 · 更新」，点一下，再点「重新启动」就好。Mac 和 Windows 同时更新。你的单据、设置和更正都存在程序以外的地方，更新不会动到。

## Where your data lives · 资料存放位置

| | Mac | Windows |
|---|---|---|
| Results (your organised receipts) | the folder you choose (default `~/Receipt Organizer`) | the folder you choose |
| Settings, learned bills, log | `~/Library/Application Support/ReceiptOrganizer` | `%APPDATA%\ReceiptOrganizer` |

## Publishing a new version (for the maintainer)

1. Change the code, set `__version__` in `receipt_organizer/__init__.py` (e.g. `1.0.1`) and add a `## 1.0.1` section to `CHANGELOG.md`.
2. Commit, then tag and push: `git tag v1.0.1 && git push --tags`.
3. GitHub Actions builds and tests the Windows app and the Mac package and publishes the Release. Every installed app then offers the update.

Run from source: `pip install -r requirements-mac.txt` (or `requirements-windows.txt`), then `python run_app.py`.
