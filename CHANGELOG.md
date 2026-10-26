# Changes

## 1.0.13
- Mac: which way up a piece is now comes from the direction the characters run (Apple Vision reads text even upside down or sideways, so the old "how much can be read" test could not tell). Sideways pages and upside-down slips are now turned correctly on Mac too.

## 1.0.12
- Pages scanned turned sideways (90 degrees) are now turned upright: when the lines look like they might run top to bottom, the piece is read in all four directions and the best one is kept.
- A receipt and a card slip touching end to end, with the slip upside down, are cut into two pieces (the slip turned the right way), so they are paired and shown side by side.

## 1.0.11
- IMPORTANT fix: importing a new folder of scans now ADDS to the receipts already in the results folder instead of replacing them (the list is backed up before every import). Re-importing the same scan file only replaces that file's pieces.
- Each receipt keeps the owner it was imported with.

## 1.0.10
- Receipts scanned at a slant (up to 45 degrees) are straightened automatically, and the extra white border is trimmed.
- New buttons under the picture: Straighten (automatic), and fine turns of 1 and 5 degrees.

## 1.0.9
- Card slips pair with their receipt even when a date was misread: same amount and similar shop name, up to a week apart.
- New button "Link card slip… / Link receipt…" to pair them by hand when the automatic pairing does not find them.

## 1.0.8
- A receipt and its bank card slip are saved as ONE picture (receipt left, slip right) in the organised folder, instead of two files.

## 1.0.7
- A receipt and its bank card slip are shown side by side in the picture area; click either to enlarge it without leaving the page.

## 1.0.6
- Far fewer false "possible duplicate" warnings: a piece that only looks similar at the bottom is flagged only when its other copy (same amount and day) is really there, and that copy is shown next to it. A receipt and its bank card slip are paired, not treated as duplicates.

## 1.0.5
- Possible duplicates: the copies are shown side by side in the picture area, each with Enlarge and Delete.

## 1.0.4
- Possible duplicates: all copies are shown side by side, large, and you choose which to keep or delete (can be undone).

## 1.0.3
- Dates: just type the digits (13102026 or 131026); the slashes appear by themselves.

## 1.0.2
- The update check no longer stops working when GitHub's hourly limit for your internet connection is reached.

## 1.0.1
- Receipt pictures now show when the scanned file names contain spaces or other special characters.
- If macOS blocks the bills folder, the app keeps working and Settings explains how to allow access.

## 1.0.0
- First version on GitHub, for Mac and Windows.
- Reads receipts and utility bills, files them by owner / year / month, joins long receipts, re-crop, card slips paired with their receipts, duplicate detection with delete and undo.
- Utility bills saved to your own bills folder by type / property / year.
- PDF spending summary and Excel export.
- One-click updates inside the app.
