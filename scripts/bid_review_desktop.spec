from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files


project_root = Path.cwd()
datas = collect_data_files("app")
pyside_datas, pyside_binaries, pyside_hidden = collect_all("PySide6")
shiboken_datas, shiboken_binaries, shiboken_hidden = collect_all("shiboken6")
datas += pyside_datas + shiboken_datas

a = Analysis(
    [str(project_root / "app" / "gui" / "main.py")],
    pathex=[str(project_root)],
    binaries=[*pyside_binaries, *shiboken_binaries],
    datas=datas,
    hiddenimports=[
        "app.gui.app",
        "app.gui.window",
        "app.gui.services.review_runner",
        "app.gui.services.report_loader",
        "app.gui.state.settings",
        *pyside_hidden,
        *shiboken_hidden,
    ],
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
    name="BidReviewDesktopStandalone",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="BidReviewDesktopStandalone",
)
