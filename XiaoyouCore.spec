# -*- mode: python ; coding: utf-8 -*-


from pathlib import Path


extra_datas = []
try:
    import llama_cpp
    llama_cpp_dir = Path(llama_cpp.__file__).resolve().parent
    llama_cpp_lib_dir = llama_cpp_dir / "lib"
    if llama_cpp_lib_dir.exists():
        extra_datas.append((str(llama_cpp_lib_dir), "llama_cpp/lib"))
except Exception:
    pass

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('clients\\frontend\\Aveline_UI\\dist', 'static'), ('architecture.svg', 'assets'), ('.env.example', '.'), ('ref_audio', 'ref_audio'), ('config/yaml', 'config/yaml'), *extra_datas],
    hiddenimports=['main', 'uvicorn', 'fastapi', 'core', 'routers', 'pystray', 'PIL', 'tkinter', 'webview', 'clr_loader', 'pythonnet'],
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
    [],
    exclude_binaries=True,
    name='XiaoyouCore',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='XiaoyouCore',
)
