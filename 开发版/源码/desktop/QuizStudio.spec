# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['E:/桌面映射/Java/QuizStudio答题系统/desktop/app.py'],
    pathex=['E:/桌面映射/Java/QuizStudio答题系统'],
    binaries=[],
    datas=[('E:/桌面映射/Java/QuizStudio答题系统/index.html', '.'), ('E:/桌面映射/Java/QuizStudio答题系统/quiz_studio.db', '.'), ('E:/桌面映射/Java/QuizStudio答题系统/desktop/quiz_studio_llm.json', '.'), ('E:/桌面映射/Java/QuizStudio答题系统/desktop/quiz_studio_ide.json', '.'), ('E:/桌面映射/Java/QuizStudio答题系统/desktop/icon.ico', '.')],
    hiddenimports=['server'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='QuizStudio',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['E:/桌面映射/Java/QuizStudio答题系统/desktop/icon.ico'],
)
