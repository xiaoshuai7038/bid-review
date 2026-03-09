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

    search_roots = [
        Path(getattr(sys, "_MEIPASS", "")),
        Path(sys.executable).resolve().parent / "_internal",
        Path(sys.executable).resolve().parent,
    ]
    seen: set[str] = set()
    for root in search_roots:
        if not root or not root.exists():
            continue
        for candidate in [
            root,
            root / "PySide6",
            root / "shiboken6",
            root / "PySide6" / "plugins",
            root / "PySide6" / "plugins" / "platforms",
        ]:
            if not candidate.exists():
                continue
            path_text = str(candidate.resolve())
            if path_text in seen:
                continue
            seen.add(path_text)
            try:
                os.add_dll_directory(path_text)
            except (AttributeError, FileNotFoundError, OSError):
                pass
    if seen:
        os.environ["PATH"] = os.pathsep.join([*seen, os.environ.get("PATH", "")])


def main(argv: list[str] | None = None) -> int:
    _bootstrap_frozen_qt_runtime()

    from PySide6.QtCore import QTimer

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
