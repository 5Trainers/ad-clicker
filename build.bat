@echo off
REM ===================================================================
REM  build.bat - builds GoogleResultClicker.exe on Windows.
REM
REM  Run this ONCE on a Windows PC that has Python 3 installed. It sets
REM  up an isolated build environment, installs every dependency, and
REM  produces a single .exe in the "dist" folder. After that, the .exe
REM  runs on any Windows PC with NO Python required.
REM
REM  Just double-click this file, or run it from a command prompt.
REM ===================================================================

setlocal
cd /d "%~dp0"

echo.
echo ==== Google Result Clicker - Windows build ====
echo.

REM --- Locate Python ---------------------------------------------------
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo [ERROR] Python 3 was not found on this PC.
    echo         Install it from https://www.python.org/downloads/windows/
    echo         and TICK "Add python.exe to PATH" during setup, then re-run
    echo         this build.bat. ^(Python is only needed to BUILD the exe;
    echo         the finished exe does not need it.^)
    echo.
    pause
    exit /b 1
)
echo Using Python: %PY%
%PY% --version

REM --- Create an isolated build virtual environment --------------------
echo.
echo [1/4] Creating build environment...
%PY% -m venv build-venv
if errorlevel 1 (
    echo [ERROR] Could not create the virtual environment.
    pause
    exit /b 1
)
call "build-venv\Scripts\activate.bat"

REM --- Install dependencies + PyInstaller ------------------------------
echo.
echo [2/4] Installing dependencies ^(this may take a minute^)...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 (
    echo [ERROR] Dependency installation failed. Check your internet connection.
    pause
    exit /b 1
)

REM --- Build the exe ---------------------------------------------------
echo.
echo [3/4] Building GoogleResultClicker.exe...
pyinstaller --noconfirm --clean clicker.spec
if errorlevel 1 (
    echo [ERROR] The build failed. See the messages above.
    pause
    exit /b 1
)

REM --- Done ------------------------------------------------------------
echo.
echo [4/4] Done!
echo.
echo   Your program is here:  dist\GoogleResultClicker.exe
echo.
echo   Copy that single .exe anywhere and double-click to run.
echo   NOTE: the target PC must have Google Chrome installed.
echo.
pause
endlocal
