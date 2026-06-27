# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('assets/launcher.html', 'assets'),
        ('assets/html2canvas.min.js', 'assets'),
        ('assets/images', 'assets/images'),
        ('assets/covers', 'assets/covers'),
        ('assets/GameRaterLogo.png', 'assets'),
        ('assets/GameRaterLogo.ico', 'assets'),
        ('assets/games.csv', 'assets'),
        ('.venv/Lib/site-packages/playwright_stealth/js', 'playwright_stealth/js'),
    ],
    hiddenimports=[
        'playwright_stealth',
        'playwright.async_api',
        'playwright._impl._driver',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='GameRater',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon='assets/GameRaterLogo.ico',
)
