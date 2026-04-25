# PyInstaller spec for youtube-scrape CLI (run from repo root).
# Rational: one-folder bundle keeps dynamic Camoufox paths easier than one-file.

block_cipher = None

a = Analysis(
    ["packaging/pyinstaller_entry.py"],
    pathex=["src"],
    binaries=[],
    datas=[],
    hiddenimports=[
        "camoufox",
        "camoufox.async_api",
        "playwright",
        "playwright.async_api",
        "typer",
        "pydantic",
        "pydantic_settings",
        "httpx",
        "defusedxml",
        "defusedxml.ElementTree",
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
    [],
    exclude_binaries=True,
    name="youtube-scrape",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="youtube-scrape",
)
