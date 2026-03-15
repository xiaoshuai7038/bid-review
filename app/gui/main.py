from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from dataclasses import dataclass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bid Review Desktop GUI")
    parser.add_argument("--smoke-test", action="store_true", help="启动 GUI 后自动保存截图并退出。")
    parser.add_argument("--screenshot", type=str, default="", help="可选，搭配 --smoke-test 保存窗口截图。")
    parser.add_argument("--automation-backend", choices=["claude", "opencode"], default="", help="可选，启用 GUI 自动化真实审查时使用的后端。")
    parser.add_argument("--automation-tender", type=str, default="", help="可选，GUI 自动化真实审查使用的招标文件路径。")
    parser.add_argument("--automation-bid", action="append", default=[], help="可选，GUI 自动化真实审查使用的投标文件路径，可重复传入。")
    parser.add_argument("--automation-output-dir", type=str, default="", help="可选，GUI 自动化真实审查使用的输出目录。")
    parser.add_argument("--automation-model", type=str, default="", help="可选，GUI 自动化真实审查使用的临时模型名。")
    parser.add_argument("--automation-review-profile", choices=["fast", "balanced", "thorough"], default="", help="可选，GUI 自动化真实审查使用的 review profile。")
    parser.add_argument("--automation-timeout-sec", type=int, default=0, help="可选，GUI 自动化真实审查使用的超时时间。")
    return parser


@dataclass
class GuiAutomationRequest:
    backend: str
    tender_path: str
    bid_paths: list[str]
    output_dir: str
    screenshot: str = ""
    model: str = ""
    review_profile: str = ""
    timeout_sec: int = 0


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
    automation_request: GuiAutomationRequest | None = None
    if args.automation_backend or args.automation_tender or args.automation_bid or args.automation_output_dir:
        if not (args.automation_backend and args.automation_tender and args.automation_bid and args.automation_output_dir):
            parser.error("启用 GUI 自动化真实审查时，必须同时提供 --automation-backend、--automation-tender、至少一个 --automation-bid 和 --automation-output-dir。")
        automation_request = GuiAutomationRequest(
            backend=args.automation_backend,
            tender_path=args.automation_tender,
            bid_paths=list(args.automation_bid),
            output_dir=args.automation_output_dir,
            screenshot=args.screenshot or "",
            model=args.automation_model,
            review_profile=args.automation_review_profile,
            timeout_sec=int(args.automation_timeout_sec or 0),
        )

    app = create_application()
    window = MainWindow()
    window.show()

    if automation_request is not None:

        def start_automation() -> None:
            window.start_automation_review(automation_request, app)

        QTimer.singleShot(0, start_automation)

    elif args.smoke_test:

        def finish() -> None:
            exit_code = 0
            if args.screenshot:
                target = Path(args.screenshot).expanduser().resolve()
                target.parent.mkdir(parents=True, exist_ok=True)
                app.processEvents()
                window.repaint()
                app.processEvents()
                saved = window.grab().save(str(target))
                if not saved or not target.exists():
                    exit_code = 1
            app.exit(exit_code)

        QTimer.singleShot(1500, finish)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
