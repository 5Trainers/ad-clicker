# Keyword Search & Click

A small cross-platform (Linux / Windows / macOS) Python tool that searches a
keyword on Google and lets you click an organic search result multiple times.

## Requirements

- Python 3.8+
- Google Chrome installed (the matching driver is downloaded automatically)

## Setup

```bash
# 1. (recommended) create a virtual environment
python -m venv venv

# Linux / macOS:
source venv/bin/activate
# Windows (PowerShell):
venv\Scripts\Activate.ps1

# 2. install dependencies
pip install -r requirements.txt
```

## Usage

`interactive_clicker.py` opens Google, runs your search, then overlays a blue
**"Click ×N"** box on whichever result you hover. Clicking that box opens that
link **N times** (default 10), each in a new tab, so the results page stays put.

```bash
# search, then hover results and click the box
python interactive_clicker.py "python tutorials"

# click the chosen link 5 times instead of 10
python interactive_clicker.py "news" --times 5

# wait 3 seconds between each click (default is 5)
python interactive_clicker.py "news" --delay 3

# open Google and type the search yourself
python interactive_clicker.py
```

Run it with a **visible** browser (no headless) — you drive it by hand. Close
the browser window to quit.

## Shareable Windows installer (recommended)

For distribution, this project produces a single **`GoogleResultClicker-Setup.exe`**
installer. You share that one file; the recipient double-clicks it, clicks through
a normal install wizard, and gets a Start Menu (and optional Desktop) shortcut.
**No Python, no `pip`, nothing to configure** — the only requirement on their PC is
**Google Chrome**.

### Build the installer on Linux (no Windows PC needed)

The installer is built right here on Linux using [Wine](https://www.winehq.org/):

```bash
# one time only:
sudo dnf install -y wine

# build it (downloads Windows Python + Inno Setup into a private sandbox,
# bundles the app, and compiles the installer — all automatic):
./build_installer.sh
```

The finished installer lands in **`installer-output/GoogleResultClicker-Setup.exe`** —
a single file you copy to any Windows PC and double-click to install.

### Build the installer on a Windows PC (alternative)

If you're on Windows instead:

1. Install [Python 3](https://www.python.org/downloads/windows/) (tick *"Add
   python.exe to PATH"*) and [Inno Setup 6](https://jrsoftware.org/isdl.php).
2. `pip install -r requirements.txt pyinstaller`, then
   `pyinstaller --noconfirm --clean clicker.spec` to produce
   `dist\GoogleResultClicker.exe`.
3. Open **`installer.iss`** in Inno Setup and click **Compile**. The finished
   installer lands in **`installer-output\GoogleResultClicker-Setup.exe`**.

## Notes & limitations

- **Google discourages automated queries.** You may hit a consent page (handled
  automatically) or a CAPTCHA. If a CAPTCHA appears, run **without** `--headless`
  and solve it by hand.
- This clicks **organic** results only — it does not interact with ads/sponsored
  links.
- If you need reliable, ToS-compliant search programmatically, use the
  **Google Custom Search JSON API** or a service like **SerpAPI** instead of
  driving a browser. Ask and I'll wire that up.
