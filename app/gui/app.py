from __future__ import annotations

import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from app.gui.theme import build_palette, build_stylesheet


def _preferred_font() -> QFont:
    candidates = [
        "Microsoft YaHei UI",
        "Microsoft YaHei",
        "Segoe UI Variable Text",
        "Segoe UI",
        "SimHei",
    ]
    for family in candidates:
        font = QFont(family, 10)
        if font.exactMatch():
            return font
    return QFont("", 10)


def create_application(argv: list[str] | None = None) -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(argv or sys.argv)

    app.setApplicationName("标书审查工作台")
    app.setApplicationDisplayName("标书审查工作台")
    app.setOrganizationName("BidReview")
    app.setStyle("Fusion")
    app.setFont(_preferred_font())
    app.setPalette(build_palette())
    app.setStyleSheet(build_stylesheet())
    return app
