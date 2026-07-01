#!/usr/bin/env bash
# ============================================================================
#  build_installer.sh — builds the shareable Windows installer
#  "GoogleResultClicker-Setup.exe" ON THIS LINUX MACHINE, using Wine.
#
#  The end result is ONE clickable file:
#      installer-output/GoogleResultClicker-Setup.exe
#  Hand that to anyone on Windows. They double-click it, click through a normal
#  install wizard, and get a Start Menu / Desktop shortcut. No Python, no pip,
#  nothing to configure — the only requirement on their PC is Google Chrome.
#
#  HOW IT WORKS (all automatic, no Windows PC needed):
#    1. Creates a private Wine "Windows" sandbox (does not touch your system).
#    2. Downloads + silently installs Windows Python inside it.
#    3. pip-installs the app's dependencies + PyInstaller.
#    4. PyInstaller bundles interactive_clicker.py -> GoogleResultClicker.exe.
#    5. Downloads + silently installs Inno Setup inside Wine.
#    6. Inno Setup compiles installer.iss -> GoogleResultClicker-Setup.exe.
#
#  PREREQUISITE (one time): Wine must be installed. If it isn't, run:
#      sudo dnf install -y wine
#
#  USAGE:
#      ./build_installer.sh
#  Re-running is safe: the Wine sandbox + downloads are cached and reused.
# ============================================================================

set -euo pipefail

# --- Config -----------------------------------------------------------------
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export WINEPREFIX="${WINEPREFIX:-$HOME/.wine-clicker}"
export WINEARCH=win64
export WINEDEBUG="${WINEDEBUG:--all}"          # quiet Wine's chatter
CACHE_DIR="$PROJECT_DIR/.build-cache"

PY_VER="3.12.7"
PY_EXE="python-${PY_VER}-amd64.exe"
PY_URL="https://www.python.org/ftp/python/${PY_VER}/${PY_EXE}"
PY_WIN="C:\\Python312\\python.exe"

INNO_EXE="innosetup-latest.exe"
INNO_URL="https://jrsoftware.org/download.php/is.exe"   # stable redirect -> newest Inno Setup 6
ISCC_WIN="C:\\Program Files (x86)\\Inno Setup 6\\ISCC.exe"

step() { printf '\n\033[1;36m==== %s\033[0m\n' "$*"; }
die()  { printf '\n\033[1;31m[ERROR] %s\033[0m\n' "$*" >&2; exit 1; }

cd "$PROJECT_DIR"
mkdir -p "$CACHE_DIR"

# --- 0. Prerequisite: Wine --------------------------------------------------
command -v wine >/dev/null 2>&1 || die "Wine is not installed. Run:  sudo dnf install -y wine   then re-run this script."
step "Using $(wine --version)"

# --- 1. Wine sandbox --------------------------------------------------------
if [ ! -d "$WINEPREFIX" ]; then
  step "Creating Wine sandbox at $WINEPREFIX (first run only, ~1 min)"
  wineboot --init >/dev/null 2>&1 || true
  wineserver -w
fi

# --- 2. Windows Python ------------------------------------------------------
if [ ! -f "$WINEPREFIX/drive_c/Python312/python.exe" ]; then
  step "Downloading Windows Python $PY_VER"
  [ -f "$CACHE_DIR/$PY_EXE" ] || curl -fL --retry 3 -o "$CACHE_DIR/$PY_EXE" "$PY_URL"
  step "Installing Python into the Wine sandbox (silent)"
  wine "$CACHE_DIR/$PY_EXE" /quiet InstallAllUsers=1 PrependPath=1 Include_test=0 \
       Include_launcher=0 SimpleInstall=1 TargetDir=C:\\Python312 || true
  wineserver -w
  [ -f "$WINEPREFIX/drive_c/Python312/python.exe" ] || die "Python did not install correctly inside Wine."
fi

# --- 3. Python dependencies + PyInstaller -----------------------------------
step "Installing app dependencies + PyInstaller inside Wine"
wine "$PY_WIN" -m pip install --upgrade pip >/dev/null
wine "$PY_WIN" -m pip install -r requirements.txt pyinstaller

# --- 4. Build the .exe ------------------------------------------------------
step "Building GoogleResultClicker.exe with PyInstaller"
rm -rf build dist
wine "$PY_WIN" -m PyInstaller --noconfirm --clean clicker.spec
[ -f "dist/GoogleResultClicker.exe" ] || die "PyInstaller did not produce dist/GoogleResultClicker.exe"

# --- 5. Inno Setup ----------------------------------------------------------
if [ ! -f "$WINEPREFIX/drive_c/Program Files (x86)/Inno Setup 6/ISCC.exe" ]; then
  step "Downloading Inno Setup (latest)"
  [ -f "$CACHE_DIR/$INNO_EXE" ] || curl -fL --retry 3 -o "$CACHE_DIR/$INNO_EXE" "$INNO_URL"
  step "Installing Inno Setup into the Wine sandbox (silent)"
  wine "$CACHE_DIR/$INNO_EXE" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- || true
  wineserver -w
  [ -f "$WINEPREFIX/drive_c/Program Files (x86)/Inno Setup 6/ISCC.exe" ] || die "Inno Setup did not install correctly inside Wine."
fi

# --- 6. Compile the installer ----------------------------------------------
step "Compiling the installer with Inno Setup"
wine "$ISCC_WIN" installer.iss
[ -f "installer-output/GoogleResultClicker-Setup.exe" ] || die "Inno Setup did not produce the installer."

# --- Done -------------------------------------------------------------------
step "DONE!"
printf '\nYour shareable Windows installer is here:\n\n    %s\n\n' \
  "$PROJECT_DIR/installer-output/GoogleResultClicker-Setup.exe"
printf 'Copy that single .exe to any Windows PC and double-click to install.\n'
printf '(The target PC only needs Google Chrome installed.)\n\n'
