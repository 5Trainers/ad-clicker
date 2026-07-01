# PyInstaller spec for interactive_clicker.py -> a single Windows .exe.
# Built by build_installer.sh (or manually:  pyinstaller clicker.spec)
#
# The resulting dist\GoogleResultClicker.exe bundles Python, Selenium, tkinter,
# and everything else. The target PC needs NO Python. It DOES need Google Chrome
# installed (Selenium drives a real Chrome window); chromedriver is fetched
# automatically at first run.

block_cipher = None

a = Analysis(
    ['interactive_clicker.py'],
    pathex=[],
    binaries=[],
    datas=[],
    # webdriver-manager pulls these in indirectly; list them so nothing is
    # dropped by PyInstaller's static analysis.
    hiddenimports=[
        'selenium',
        'webdriver_manager',
        'webdriver_manager.chrome',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='GoogleResultClicker',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    # console=True keeps a terminal window so you can see log output / errors.
    # The tkinter GUI still opens on top of it. Set to False for a windowed-only
    # build (harder to debug if something goes wrong).
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
