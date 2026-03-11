from pathlib import Path

import PySide6
from PyInstaller.utils.hooks import collect_data_files


project_root = Path.cwd()
datas = collect_data_files("app")
pyside_root = Path(PySide6.__file__).resolve().parent
shiboken_root = pyside_root.parent / "shiboken6"
for source, destination in [
    (pyside_root / "__init__.py", "PySide6"),
    (pyside_root / "_config.py", "PySide6"),
    (pyside_root / "_git_pyside_version.py", "PySide6"),
    (pyside_root / "__feature__.pyi", "PySide6"),
    (pyside_root / "py.typed", "PySide6"),
    (shiboken_root / "__init__.py", "shiboken6"),
    (shiboken_root / "_config.py", "shiboken6"),
    (shiboken_root / "_git_shiboken_module_version.py", "shiboken6"),
    (shiboken_root / "py.typed", "shiboken6"),
]:
    if source.exists():
        datas.append((str(source), destination))
binaries = [
    (str(pyside_root / "pyside6.abi3.dll"), "PySide6"),
]
if (pyside_root / "pyside6qml.abi3.dll").exists():
    binaries.append((str(pyside_root / "pyside6qml.abi3.dll"), "PySide6"))
for source, destination in [
    (pyside_root / "concrt140.dll", "PySide6"),
    (pyside_root / "msvcp140_codecvt_ids.dll", "PySide6"),
    (shiboken_root / "concrt140.dll", "shiboken6"),
    (shiboken_root / "msvcp140_codecvt_ids.dll", "shiboken6"),
]:
    if source.exists():
        binaries.append((str(source), destination))

a = Analysis(
    [str(project_root / "app" / "gui" / "main.py")],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    module_collection_mode={
        "PySide6": "pyz+py",
        "shiboken6": "pyz+py",
    },
    hiddenimports=[
        "app.gui.app",
        "app.gui.window",
        "app.gui.services.review_runner",
        "app.gui.services.report_loader",
        "app.gui.state.settings",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(project_root / "scripts" / "bundle_qt_patch.py")],
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
    name="BidReviewDesktop",
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
    name="BidReviewDesktop",
)
