from __future__ import annotations

from PySide6.QtGui import QColor, QPalette


COLORS = {
    "window": "#08111A",
    "window_alt": "#0D1722",
    "panel": "#101A27",
    "card": "#132131",
    "card_alt": "#182A3E",
    "stroke": "#27415A",
    "text": "#F2F7FB",
    "muted": "#90A7BE",
    "accent": "#7EB8E8",
    "accent_hover": "#95C8F0",
    "accent_pressed": "#5EA4DA",
    "success": "#59C899",
    "warning": "#E3B16A",
    "danger": "#EC7B87",
}


def build_palette() -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(COLORS["window"]))
    palette.setColor(QPalette.WindowText, QColor(COLORS["text"]))
    palette.setColor(QPalette.Base, QColor(COLORS["panel"]))
    palette.setColor(QPalette.AlternateBase, QColor(COLORS["card"]))
    palette.setColor(QPalette.ToolTipBase, QColor(COLORS["card_alt"]))
    palette.setColor(QPalette.ToolTipText, QColor(COLORS["text"]))
    palette.setColor(QPalette.Text, QColor(COLORS["text"]))
    palette.setColor(QPalette.Button, QColor(COLORS["card"]))
    palette.setColor(QPalette.ButtonText, QColor(COLORS["text"]))
    palette.setColor(QPalette.BrightText, QColor("#FFFFFF"))
    palette.setColor(QPalette.Highlight, QColor(COLORS["accent"]))
    palette.setColor(QPalette.HighlightedText, QColor("#02111F"))
    return palette


def build_stylesheet() -> str:
    c = COLORS
    return f"""
    QWidget {{
        color: {c["text"]};
        font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI Variable Text", "Segoe UI", "SimHei";
        background: transparent;
    }}

    QMainWindow#RootWindow {{
        background: qlineargradient(
            x1:0, y1:0, x2:1, y2:1,
            stop:0 {c["window"]},
            stop:0.55 {c["window_alt"]},
            stop:1 #0A1420
        );
    }}

    QFrame#NavPanel {{
        background: rgba(9, 18, 28, 0.92);
        border-right: 1px solid {c["stroke"]};
    }}

    QFrame#TopBar {{
        background: rgba(16, 27, 40, 0.78);
        border: 1px solid rgba(126, 184, 232, 0.16);
        border-radius: 18px;
    }}

    QFrame[surface="card"] {{
        background: rgba(17, 29, 43, 0.9);
        border: 1px solid rgba(126, 184, 232, 0.12);
        border-radius: 22px;
    }}

    QFrame[surface="hero"] {{
        background: qlineargradient(
            x1:0, y1:0, x2:1, y2:1,
            stop:0 rgba(18, 33, 49, 0.95),
            stop:0.5 rgba(18, 48, 71, 0.90),
            stop:1 rgba(13, 28, 44, 0.95)
        );
        border: 1px solid rgba(126, 184, 232, 0.25);
        border-radius: 28px;
    }}

    QLabel#PageTitle {{
        font-size: 26px;
        font-weight: 700;
        color: #F6FAFD;
    }}

    QLabel#HeroTitle {{
        font-size: 30px;
        font-weight: 700;
        color: #F6FAFD;
    }}

    QLabel#SectionTitle {{
        font-size: 16px;
        font-weight: 700;
        color: #EAF2F8;
    }}

    QLabel#StatValue {{
        font-size: 26px;
        font-weight: 700;
    }}

    QLabel#MutedLabel {{
        color: {c["muted"]};
        font-size: 12px;
    }}

    QLabel#Badge {{
        background: rgba(126, 184, 232, 0.14);
        border: 1px solid rgba(126, 184, 232, 0.25);
        border-radius: 11px;
        padding: 4px 10px;
        color: #CAE4F8;
    }}

    QPushButton {{
        background: rgba(19, 33, 49, 0.96);
        border: 1px solid rgba(126, 184, 232, 0.16);
        border-radius: 14px;
        padding: 10px 16px;
        color: {c["text"]};
    }}

    QPushButton:hover {{
        border-color: rgba(126, 184, 232, 0.30);
        background: rgba(24, 43, 64, 0.98);
    }}

    QPushButton:pressed {{
        background: rgba(14, 23, 35, 0.98);
    }}

    QPushButton[kind="primary"] {{
        background: {c["accent"]};
        color: #02111F;
        border: none;
        font-weight: 700;
    }}

    QPushButton[kind="primary"]:hover {{
        background: {c["accent_hover"]};
    }}

    QPushButton[kind="primary"]:pressed {{
        background: {c["accent_pressed"]};
    }}

    QPushButton[kind="ghost"] {{
        background: rgba(12, 20, 31, 0.5);
    }}

    QPushButton[nav="true"] {{
        text-align: left;
        padding: 12px 16px;
        border-radius: 16px;
        border: none;
        background: transparent;
        color: {c["muted"]};
        font-weight: 600;
    }}

    QPushButton[nav="true"]:hover {{
        background: rgba(126, 184, 232, 0.08);
        color: {c["text"]};
    }}

    QPushButton[nav="true"]:checked {{
        background: rgba(126, 184, 232, 0.16);
        color: #F6FAFD;
    }}

    QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QListWidget, QTableWidget, QSpinBox {{
        background: rgba(10, 18, 28, 0.82);
        border: 1px solid rgba(126, 184, 232, 0.14);
        border-radius: 16px;
        padding: 8px 10px;
        selection-background-color: rgba(126, 184, 232, 0.35);
        selection-color: #F8FCFF;
    }}

    QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus {{
        border-color: rgba(126, 184, 232, 0.34);
    }}

    QListWidget::item {{
        padding: 8px;
        border-radius: 10px;
        margin: 2px 0;
    }}

    QListWidget::item:selected {{
        background: rgba(126, 184, 232, 0.16);
    }}

    QTableWidget {{
        gridline-color: rgba(126, 184, 232, 0.10);
        alternate-background-color: rgba(14, 23, 35, 0.55);
    }}

    QHeaderView::section {{
        background: rgba(22, 36, 52, 0.95);
        border: none;
        border-bottom: 1px solid rgba(126, 184, 232, 0.14);
        padding: 10px;
        font-weight: 700;
    }}

    QScrollBar:vertical {{
        width: 12px;
        background: transparent;
        margin: 2px;
    }}

    QScrollBar::handle:vertical {{
        min-height: 28px;
        border-radius: 6px;
        background: rgba(126, 184, 232, 0.20);
    }}

    QScrollBar::handle:vertical:hover {{
        background: rgba(126, 184, 232, 0.34);
    }}

    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        border: none;
        background: transparent;
        height: 0px;
    }}

    QSplitter::handle {{
        background: rgba(126, 184, 232, 0.08);
    }}
    """
