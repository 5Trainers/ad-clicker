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

## Notes & limitations

- **Google discourages automated queries.** You may hit a consent page (handled
  automatically) or a CAPTCHA. If a CAPTCHA appears, run **without** `--headless`
  and solve it by hand.
- This clicks **organic** results only — it does not interact with ads/sponsored
  links.
- If you need reliable, ToS-compliant search programmatically, use the
  **Google Custom Search JSON API** or a service like **SerpAPI** instead of
  driving a browser. Ask and I'll wire that up.
