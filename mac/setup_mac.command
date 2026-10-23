#!/bin/bash
# One-time setup on a Mac. Creates a private Python environment inside this folder (nothing is installed system-wide)
# and puts "Receipt Organizer" in your Applications folder.
cd "$(dirname "$0")/.."
echo "Setting up Receipt Organizer (one time)..."
python3 -m venv .venv || { echo "python3 not found. Install Apple Command Line Tools: run  xcode-select --install"; read -p "Press Enter"; exit 1; }
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements-mac.txt || { echo "Install failed"; read -p "Press Enter"; exit 1; }
echo "Checking Ollama (optional second reader for faded receipts)..."
curl -s localhost:11434/api/tags | grep -q qwen && echo "Ollama found." || echo "Ollama not found: the app still works, faded dates go to 'needs checking'."
bash mac/build_app_mac.sh && echo "Done. Open Receipt Organizer from Applications (in your home folder), Launchpad or Spotlight."
read -p "Press Enter to close"
