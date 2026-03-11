from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bid Review Desktop GUI")
    parser.add_argument("--smoke-test", action="store_true", help="启动 GUI 后自动保存截图并退出。")
    parser.add_argument("--screenshot", type=str, default="", help="可选，搭配 --smoke-test 保存窗口截图。")
    return parser


def _bootstrap_frozen_qt_runtime() -> None:
    if not getattr(sys, "frozen", False):
        return

    bundle_root = Path(getattr(sys, "_MEIPASS", "") or Path(sys.executable).resolve().parent / "_internal").resolve()
    preferred_paths = [
        bundle_root / "PySide6",
        bundle_root / "shiboken6",
        bundle_root / "PySide6" / "plugins",
        bundle_root / "PySide6" / "plugins" / "platforms",
    ]

    current_path_items = [item for item in os.environ.get("PATH", "").split(os.pathsep) if item]
    filtered_path_items: list[str] = []
    for item in current_path_items:
        try:
            if Path(item).resolve() == bundle_root:
                continue
        except OSError:
            pass
        filtered_path_items.append(item)

    merged: list[str] = []
    seen: set[str] = set()
    for item in [*(str(path) for path in preferred_paths if path.exists()), *filtered_path_items]:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    os.environ["PATH"] = os.pathsep.join(merged)

    pyqt_root = bundle_root / "PySide6"
    if pyqt_root.exists():
        os.environ["QT_PLUGIN_PATH"] = str((pyqt_root / "plugins").resolve())
        os.environ["QML2_IMPORT_PATH"] = str((pyqt_root / "qml").resolve())


def _restore_frozen_runtime_root() -> None:
    if not getattr(sys, "frozen", False):
        return

    bundle_root = Path(getattr(sys, "_MEIPASS", "") or Path(sys.executable).resolve().parent / "_internal").resolve()
    current_path_items = [item for item in os.environ.get("PATH", "").split(os.pathsep) if item]
    root_text = str(bundle_root)
    if any(item.lower() == root_text.lower() for item in current_path_items):
        return
    os.environ["PATH"] = os.pathsep.join([root_text, *current_path_items])


def main(argv: list[str] | None = None) -> int:
    _bootstrap_frozen_qt_runtime()

    from PySide6.QtCore import QTimer

    _restore_frozen_runtime_root()

    from app.gui.app import create_application
    from app.gui.window import MainWindow

    parser = build_parser()
    args = parser.parse_args(argv)

    app = create_application()
    window = MainWindow()
    window.show()

    if args.smoke_test:

        def finish() -> None:
            if args.screenshot:
                target = Path(args.screenshot).expanduser().resolve()
                target.parent.mkdir(parents=True, exist_ok=True)
                window.grab().save(str(target))
            app.quit()

        QTimer.singleShot(900, finish)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
