from __future__ import annotations

from pathlib import Path
import os
import re
from dataclasses import dataclass

from PySide6.QtCore import QDateTime, QEvent, QPoint, QSize, QTimer, Qt, Signal, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QScrollArea,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QHeaderView,
    QSizePolicy,
)

from app.gui.services import (
    BatchReviewData,
    ReviewRunData,
    ReviewRunRequest,
    ReviewWorker,
    find_latest_batch_summary,
    load_batch_result,
)
from app.gui.state import DesktopSettings, SettingsStore, runtime_root, runtime_root_status


def _open_local_path(path: str | Path | None) -> bool:
    if not path:
        return False
    target = Path(path).expanduser()
    if not target.exists():
        return False
    return QDesktopServices.openUrl(QUrl.fromLocalFile(str(target.resolve())))


def _asset_path(name: str) -> Path:
    return runtime_root() / "app" / "gui" / "assets" / name


def _basename(path: str) -> str:
    return Path(path).name if path else "未选择"


def _status_text(status: str) -> str:
    mapping = {
        "non_compliant": "不符合",
        "risk": "风险",
        "needs_manual": "需人工复核",
    }
    return mapping.get(status, status or "")


PROGRESS_LEVEL_ITEMS: list[tuple[str, str]] = [
    ("简洁（推荐）", "agent"),
    ("只看开始和结束", "basic"),
    ("查看主要步骤", "normal"),
    ("查看详细步骤", "detailed"),
    ("尽量多看过程", "events"),
    ("全部过程都显示", "raw"),
]

EFFORT_ITEMS: list[tuple[str, str]] = [
    ("快速", "low"),
    ("标准", "medium"),
    ("仔细", "high"),
]

REVIEW_PROFILE_ITEMS: list[tuple[str, str]] = [
    ("速度优先", "fast"),
    ("平衡", "balanced"),
    ("完整性优先", "thorough"),
]

APP_DISPLAY_NAME = "标书审查工作台"
FILE_CARDS_STACK_THRESHOLD = 620

BACKEND_ITEMS: list[tuple[str, str]] = [
    ("Claude 引擎", "claude"),
    ("OpenCode 引擎", "opencode"),
]

TIMEOUT_SECONDS_OPTIONS: tuple[int, ...] = (
    60,
    120,
    180,
    300,
    *range(600, 3601, 300),
    4500,
    5400,
    7200,
)


def _pin_form_field_height(widget: QWidget, min_height: int = 40) -> None:
    widget.setMinimumHeight(min_height)
    widget.setSizePolicy(widget.sizePolicy().horizontalPolicy(), QSizePolicy.Fixed)


def _allow_label_to_shrink(label: QLabel, *, word_wrap: bool) -> None:
    label.setWordWrap(word_wrap)
    label.setMinimumWidth(0)
    label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)


def _configure_form_layout(form: QFormLayout) -> None:
    form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
    form.setRowWrapPolicy(QFormLayout.DontWrapRows)
    form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    form.setFormAlignment(Qt.AlignTop)
    form.setHorizontalSpacing(14)
    form.setVerticalSpacing(12)


def _populate_progress_level_combo(combo: QComboBox) -> None:
    combo.clear()
    for label, value in PROGRESS_LEVEL_ITEMS:
        combo.addItem(label, value)


def _populate_backend_combo(combo: QComboBox) -> None:
    combo.clear()
    for label, value in BACKEND_ITEMS:
        combo.addItem(label, value)


def _populate_effort_combo(combo: QComboBox) -> None:
    combo.clear()
    for label, value in EFFORT_ITEMS:
        combo.addItem(label, value)


def _populate_review_profile_combo(combo: QComboBox) -> None:
    combo.clear()
    for label, value in REVIEW_PROFILE_ITEMS:
        combo.addItem(label, value)


def _set_combo_value(combo: QComboBox, value: str) -> None:
    target = (value or "").strip()
    for index in range(combo.count()):
        if str(combo.itemData(index) or "").strip() == target:
            combo.setCurrentIndex(index)
            return
    if combo.count() > 0:
        combo.setCurrentIndex(0)


def _combo_value(combo: QComboBox) -> str:
    data = combo.currentData()
    if data is not None:
        return str(data).strip()
    return combo.currentText().strip()


def _normalize_timeout_seconds(value: object, *, default: int = 1800) -> int:
    try:
        seconds = int(value or default)
    except (TypeError, ValueError):
        seconds = default
    return max(60, min(7200, seconds))


def _timeout_label(seconds: int) -> str:
    normalized = _normalize_timeout_seconds(seconds)
    total_minutes, remainder = divmod(normalized, 60)
    if remainder:
        return f"{normalized} 秒"
    if total_minutes < 60:
        duration_text = f"{total_minutes} 分钟"
    else:
        hours, minutes = divmod(total_minutes, 60)
        duration_text = f"{hours} 小时" if minutes == 0 else f"{hours} 小时 {minutes} 分钟"
    suffix = "，推荐" if normalized == 1800 else ""
    return f"{normalized} 秒（{duration_text}{suffix}）"


class DropdownOnlyComboBox(QComboBox):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMaxVisibleItems(12)

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        event.ignore()


class TimeoutComboBox(DropdownOnlyComboBox):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        for seconds in TIMEOUT_SECONDS_OPTIONS:
            self.addItem(_timeout_label(seconds), seconds)
        self.setValue(1800)

    def _find_or_insert_value(self, seconds: int) -> int:
        for index in range(self.count()):
            item_seconds = _normalize_timeout_seconds(self.itemData(index), default=seconds)
            if item_seconds == seconds:
                return index
            if item_seconds > seconds:
                self.insertItem(index, _timeout_label(seconds), seconds)
                return index
        self.addItem(_timeout_label(seconds), seconds)
        return self.count() - 1

    def setValue(self, seconds: int) -> None:
        normalized = _normalize_timeout_seconds(seconds)
        index = self._find_or_insert_value(normalized)
        self.setCurrentIndex(index)

    def value(self) -> int:
        return _normalize_timeout_seconds(self.currentData())


def _role_reasoning_text(reasoning: str) -> str:
    raw = (reasoning or "").strip()
    normalized = raw.lower()
    mapping = {
        "manual": "手动指定招标文件和投标文件",
        "manual+tender": "手动指定招标文件，系统自动收集投标文件",
    }
    if not raw:
        return "未记录"
    if normalized in mapping:
        return mapping[normalized]
    if any("\u4e00" <= char <= "\u9fff" for char in raw):
        return raw
    return f"自动识别（{raw}）"


def _friendly_progress_message(message: str) -> str:
    display = message
    replacements = {
        "[pipeline]": "[流程]",
        "[agent]": "[审查引擎]",
        "[desktop]": "[工作台]",
        "backend=claude": "审查引擎=Claude",
        "backend=opencode": "审查引擎=OpenCode",
        "run_pipeline": "现有审查流程",
    }
    for raw, friendly in replacements.items():
        display = display.replace(raw, friendly)
    return display


def _collapse_progress_text(message: str, *, limit: int = 120) -> str:
    text = re.sub(r"\s+", " ", str(message or "")).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def _compact_status_detail(
    text: str,
    *,
    limit: int = 88,
    fallback: str = "详情见下方详细记录。",
) -> str:
    raw = str(text or "").strip()
    normalized = re.sub(r"\s+", " ", raw).strip()
    if not normalized:
        return fallback
    looks_like_list = (
        "\n" in raw
        or re.search(r"(?:^|\s)(?:\d+[\.、]|[-*•])", raw) is not None
        or normalized.count("；") >= 2
    )
    if looks_like_list and len(normalized) > 40:
        return fallback
    if len(normalized) <= limit:
        return normalized
    return f"{_collapse_progress_text(normalized, limit=limit - 10)} 详见下方详细记录。"


def _extract_local_file_paths_from_urls(urls: list[QUrl]) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for url in urls:
        local = url.toLocalFile()
        if not local:
            continue
        candidate = Path(local).expanduser().resolve()
        if not candidate.is_file():
            continue
        normalized = str(candidate)
        if normalized in seen:
            continue
        seen.add(normalized)
        paths.append(normalized)
    return paths


def _enable_drop_passthrough(container: QWidget, *widgets: QWidget) -> None:
    for widget in widgets:
        widget.setAcceptDrops(True)
        widget.installEventFilter(container)


class AutoResizingPlainTextEdit(QPlainTextEdit):
    def __init__(
        self,
        *,
        min_rows: int = 2,
        max_rows: int = 8,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._min_rows = min_rows
        self._max_rows = max(max_rows, min_rows)
        self.document().documentLayout().documentSizeChanged.connect(self._update_height)
        self.textChanged.connect(self._update_height)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._update_height()

    def _update_height(self, *args) -> None:  # noqa: ANN002
        metrics = self.fontMetrics()
        row_height = metrics.lineSpacing()
        margins = self.contentsMargins()
        document_margin = int(self.document().documentMargin() * 2)
        frame = self.frameWidth() * 2
        padding = 20
        block_count = max(1, self.document().blockCount())
        visible_rows = max(self._min_rows, min(self._max_rows, block_count))
        target_height = (
            visible_rows * row_height
            + document_margin
            + frame
            + margins.top()
            + margins.bottom()
            + padding
        )
        self.setFixedHeight(target_height)
        if block_count > self._max_rows:
            self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        else:
            self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)


class SurfaceFrame(QFrame):
    def __init__(self, surface: str = "card", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("surface", surface)


class StatCard(SurfaceFrame):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__("card", parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(6)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("MutedLabel")
        self.value_label = QLabel("0")
        self.value_label.setObjectName("StatValue")
        self.note_label = QLabel("")
        self.note_label.setObjectName("MutedLabel")
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.note_label)
        layout.addStretch(1)

    def set_value(self, value: str, note: str = "") -> None:
        self.value_label.setText(value)
        self.note_label.setText(note)


class CompactStatCard(SurfaceFrame):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__("card", parent)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(4)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("MutedLabel")
        self.value_label = QLabel("0")
        self.value_label.setObjectName("StatValue")
        self.note_label = QLabel("")
        self.note_label.setObjectName("MutedLabel")
        self.note_label.setWordWrap(True)
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.note_label)

    def set_value(self, value: str, note: str = "", *, tooltip: str | None = None) -> None:
        self.value_label.setText(value)
        self.note_label.setText(note)
        if tooltip:
            self.note_label.setToolTip(tooltip)
        else:
            self.note_label.setToolTip(note)


class FindingsTableDelegate(QStyledItemDelegate):
    HORIZONTAL_PADDING = 12
    VERTICAL_PADDING = 14

    def sizeHint(self, option, index) -> QSize:  # type: ignore[override]
        base = super().sizeHint(option, index)
        text = str(index.data(Qt.DisplayRole) or "").strip()
        if not text:
            return base

        table = self.parent()
        available_width = option.rect.width()
        if available_width <= 0 and isinstance(table, QTableWidget):
            available_width = table.columnWidth(index.column())
        available_width = max(40, available_width - self.HORIZONTAL_PADDING)
        content_rect = option.fontMetrics.boundingRect(
            0,
            0,
            available_width,
            10000,
            Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignTop,
            text,
        )
        return QSize(
            max(base.width(), content_rect.width() + self.HORIZONTAL_PADDING),
            max(base.height(), content_rect.height() + self.VERTICAL_PADDING),
        )


class SingleFileDropCard(SurfaceFrame):
    def __init__(self, title: str, hint: str, parent: QWidget | None = None) -> None:
        super().__init__("card", parent)
        self._path = ""
        self._hint = hint
        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        title_label = QLabel(title)
        title_label.setObjectName("SectionTitle")
        self.hint_label = QLabel(hint)
        self.hint_label.setObjectName("MutedLabel")
        _allow_label_to_shrink(self.hint_label, word_wrap=True)
        self.path_label = QLabel("拖入文件或点击选择")
        _allow_label_to_shrink(self.path_label, word_wrap=True)

        action_row = QHBoxLayout()
        self.browse_button = QPushButton("选择文件")
        self.browse_button.setProperty("kind", "primary")
        self.clear_button = QPushButton("清空")
        self.clear_button.setProperty("kind", "ghost")
        action_row.addWidget(self.browse_button)
        action_row.addWidget(self.clear_button)
        action_row.addStretch(1)

        layout.addWidget(title_label)
        layout.addWidget(self.hint_label)
        layout.addWidget(self.path_label)
        layout.addLayout(action_row)

        self.browse_button.clicked.connect(self.browse)
        self.clear_button.clicked.connect(self.clear)
        _enable_drop_passthrough(
            self,
            title_label,
            self.hint_label,
            self.path_label,
            self.browse_button,
            self.clear_button,
        )

    def dragEnterEvent(self, event) -> None:  # type: ignore[override]
        if _extract_local_file_paths_from_urls(event.mimeData().urls()):
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # type: ignore[override]
        if _extract_local_file_paths_from_urls(event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # type: ignore[override]
        if self._handle_drop_urls(event.mimeData().urls()):
            event.acceptProposedAction()

    def eventFilter(self, watched: object, event: object) -> bool:
        if isinstance(watched, QWidget) and hasattr(event, "type"):
            event_type = event.type()
            if event_type in {QEvent.DragEnter, QEvent.DragMove} and hasattr(event, "mimeData"):
                if _extract_local_file_paths_from_urls(event.mimeData().urls()):
                    event.acceptProposedAction()
                    return True
            if event_type == QEvent.Drop and hasattr(event, "mimeData"):
                if self._handle_drop_urls(event.mimeData().urls()):
                    event.acceptProposedAction()
                    return True
        return super().eventFilter(watched, event)

    def _handle_drop_urls(self, urls: list[QUrl]) -> bool:
        paths = _extract_local_file_paths_from_urls(urls)
        if not paths:
            return False
        self.set_file(paths[0])
        return True

    def browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择文件")
        if path:
            self.set_file(path)

    def set_file(self, path: str) -> None:
        self._path = str(Path(path).expanduser().resolve())
        self.path_label.setText(self._path)
        self.path_label.setToolTip(self._path)
        basename = _basename(self._path)
        self.hint_label.setText(basename)
        self.hint_label.setToolTip(basename)

    def clear(self) -> None:
        self._path = ""
        self.path_label.setText("拖入文件或点击选择")
        self.path_label.setToolTip("")
        self.hint_label.setText(self._hint)
        self.hint_label.setToolTip("")

    def file_path(self) -> str:
        return self._path


class MultiFileDropCard(SurfaceFrame):
    def __init__(self, title: str, hint: str, parent: QWidget | None = None) -> None:
        super().__init__("card", parent)
        self._hint = hint
        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        title_label = QLabel(title)
        title_label.setObjectName("SectionTitle")
        self.count_label = QLabel(hint)
        self.count_label.setObjectName("MutedLabel")
        _allow_label_to_shrink(self.count_label, word_wrap=True)
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)

        action_row = QHBoxLayout()
        self.add_button = QPushButton("添加文件")
        self.add_button.setProperty("kind", "primary")
        self.remove_button = QPushButton("移除所选")
        self.remove_button.setProperty("kind", "ghost")
        self.clear_button = QPushButton("全部清空")
        self.clear_button.setProperty("kind", "ghost")
        action_row.addWidget(self.add_button)
        action_row.addWidget(self.remove_button)
        action_row.addWidget(self.clear_button)
        action_row.addStretch(1)

        layout.addWidget(title_label)
        layout.addWidget(self.count_label)
        layout.addWidget(self.list_widget, 1)
        layout.addLayout(action_row)

        self.add_button.clicked.connect(self.browse)
        self.remove_button.clicked.connect(self.remove_selected)
        self.clear_button.clicked.connect(self.clear)
        _enable_drop_passthrough(
            self,
            title_label,
            self.count_label,
            self.list_widget,
            self.list_widget.viewport(),
            self.add_button,
            self.remove_button,
            self.clear_button,
        )
        self._refresh_count()

    def dragEnterEvent(self, event) -> None:  # type: ignore[override]
        if _extract_local_file_paths_from_urls(event.mimeData().urls()):
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # type: ignore[override]
        if _extract_local_file_paths_from_urls(event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # type: ignore[override]
        if self._handle_drop_urls(event.mimeData().urls()):
            event.acceptProposedAction()

    def eventFilter(self, watched: object, event: object) -> bool:
        if isinstance(watched, QWidget) and hasattr(event, "type"):
            event_type = event.type()
            if event_type in {QEvent.DragEnter, QEvent.DragMove} and hasattr(event, "mimeData"):
                if _extract_local_file_paths_from_urls(event.mimeData().urls()):
                    event.acceptProposedAction()
                    return True
            if event_type == QEvent.Drop and hasattr(event, "mimeData"):
                if self._handle_drop_urls(event.mimeData().urls()):
                    event.acceptProposedAction()
                    return True
        return super().eventFilter(watched, event)

    def _handle_drop_urls(self, urls: list[QUrl]) -> bool:
        paths = _extract_local_file_paths_from_urls(urls)
        if not paths:
            return False
        self.add_paths(paths)
        return True

    def browse(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "选择投标文件")
        self.add_paths(paths)

    def add_paths(self, paths: list[str]) -> None:
        existing = {self.list_widget.item(i).data(Qt.UserRole) for i in range(self.list_widget.count())}
        for path in paths:
            if not path:
                continue
            resolved = str(Path(path).expanduser().resolve())
            if resolved in existing or not Path(resolved).is_file():
                continue
            item = QListWidgetItem(_basename(resolved))
            item.setData(Qt.UserRole, resolved)
            item.setToolTip(resolved)
            self.list_widget.addItem(item)
            existing.add(resolved)
        self._refresh_count()

    def set_paths(self, paths: list[str]) -> None:
        self.list_widget.clear()
        self.add_paths(paths)

    def clear(self) -> None:
        self.list_widget.clear()
        self._refresh_count()

    def remove_selected(self) -> None:
        for item in self.list_widget.selectedItems():
            row = self.list_widget.row(item)
            self.list_widget.takeItem(row)
        self._refresh_count()

    def paths(self) -> list[str]:
        return [str(self.list_widget.item(i).data(Qt.UserRole) or "") for i in range(self.list_widget.count())]

    def _refresh_count(self) -> None:
        count = self.list_widget.count()
        self.count_label.setText(self._hint if count == 0 else f"已选择 {count} 份投标文件")


class HomePage(QWidget):
    new_review_requested = Signal()
    open_recent_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        hero = SurfaceFrame("hero")
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(30, 28, 30, 28)
        hero_layout.setSpacing(24)

        left = QVBoxLayout()
        left.setSpacing(12)
        badge = QLabel("招投标文件审查")
        badge.setObjectName("Badge")
        title = QLabel("面向招投标业务的标书审查工作台")
        title.setObjectName("HeroTitle")
        title.setWordWrap(True)
        desc = QLabel(
            "在桌面端完成选文件、设置审查方式、跟踪进度和查看报告，"
            "全程沿用现有审查流程与导出结果。"
        )
        desc.setWordWrap(True)
        desc.setObjectName("MutedLabel")
        action_row = QHBoxLayout()
        self.new_button = QPushButton("新建审查")
        self.new_button.setProperty("kind", "primary")
        self.open_recent_button = QPushButton("查看最近结果")
        self.open_recent_button.setProperty("kind", "ghost")
        action_row.addWidget(self.new_button)
        action_row.addWidget(self.open_recent_button)
        action_row.addStretch(1)
        left.addWidget(badge)
        left.addWidget(title)
        left.addWidget(desc)
        left.addLayout(action_row)
        left.addStretch(1)

        right = QVBoxLayout()
        right.setSpacing(12)
        icon_label = QLabel()
        pixmap = QIcon(str(_asset_path("brand_mark.svg"))).pixmap(96, 96)
        icon_label.setPixmap(pixmap if not pixmap.isNull() else QPixmap())
        right.addWidget(icon_label, 0, Qt.AlignLeft)

        self.hero_cards = [StatCard("审查引擎"), StatCard("批量处理"), StatCard("结果查看")]
        self.hero_cards[0].set_value("Claude / OpenCode", "可切换两种审查引擎")
        self.hero_cards[1].set_value("1 份招标 + 多份投标", "一次可检查多份投标文件")
        self.hero_cards[2].set_value("结构化结果 + 报告", "支持打开批量汇总和单份报告")
        for card in self.hero_cards:
            right.addWidget(card)
        right.addStretch(1)

        hero_layout.addLayout(left, 3)
        hero_layout.addLayout(right, 2)

        recent = SurfaceFrame("card")
        recent_layout = QVBoxLayout(recent)
        recent_layout.setContentsMargins(24, 20, 24, 20)
        recent_layout.setSpacing(10)
        recent_title = QLabel("最近一次审查")
        recent_title.setObjectName("SectionTitle")
        self.recent_path = QLabel("暂无可用运行记录")
        self.recent_path.setWordWrap(True)
        self.recent_meta = QLabel("完成一次审查后，这里会显示最近结果入口。")
        self.recent_meta.setObjectName("MutedLabel")
        recent_open_row = QHBoxLayout()
        self.recent_open_button = QPushButton("查看最近结果")
        self.recent_open_button.setProperty("kind", "ghost")
        recent_open_row.addWidget(self.recent_open_button)
        recent_open_row.addStretch(1)
        recent_layout.addWidget(recent_title)
        recent_layout.addWidget(self.recent_path)
        recent_layout.addWidget(self.recent_meta)
        recent_layout.addLayout(recent_open_row)

        layout.addWidget(hero)
        layout.addWidget(recent)
        layout.addStretch(1)

        self.new_button.clicked.connect(self.new_review_requested.emit)
        self.open_recent_button.clicked.connect(self.open_recent_requested.emit)
        self.recent_open_button.clicked.connect(self.open_recent_requested.emit)

    def set_recent(self, result: BatchReviewData | None) -> None:
        if result is None or not result.runs:
            self.recent_path.setText("暂无可用运行记录")
            self.recent_meta.setText("完成一次审查后，这里会显示最近结果入口。")
            return
        self.recent_path.setText(str(result.batch_summary_path))
        self.recent_meta.setText(
            f"招标文件：{_basename(result.tender_path)} | 投标文件：{len(result.runs)} 份 | 结果目录：{result.output_dir}"
        )


class ReviewPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._backend_model_defaults = {"claude": "", "opencode": ""}
        self._last_model_backend = "claude"
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(18)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)

        left_container = QWidget()
        left_container_layout = QVBoxLayout(left_container)
        left_container_layout.setContentsMargins(0, 0, 0, 0)
        left_container_layout.setSpacing(18)

        top_actions = SurfaceFrame("card")
        top_actions_layout = QVBoxLayout(top_actions)
        top_actions_layout.setContentsMargins(24, 18, 24, 18)
        top_actions_layout.setSpacing(12)
        self.command_hint = QLabel("确认文件和参数后，即可开始审查。")
        self.command_hint.setObjectName("MutedLabel")
        self.run_button = QPushButton("开始审查")
        self.run_button.setProperty("kind", "primary")
        self.open_output_button = QPushButton("打开结果目录")
        self.open_output_button.setProperty("kind", "ghost")
        top_action_row = QHBoxLayout()
        top_action_row.addWidget(self.run_button)
        top_action_row.addWidget(self.open_output_button)
        top_action_row.addStretch(1)
        top_actions_layout.addWidget(self.command_hint)
        top_actions_layout.addLayout(top_action_row)

        left = QWidget()
        left.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(18)

        self.tender_card = SingleFileDropCard("招标文件", "仅需 1 份，用于提取招标要求和评审基线")
        self.bid_card = MultiFileDropCard("投标文件", "支持同时审查 1 份或多份投标文件")
        self.file_cards = QWidget()
        self.file_cards_layout = QGridLayout(self.file_cards)
        self.file_cards_layout.setContentsMargins(0, 0, 0, 0)
        self.file_cards_layout.setHorizontalSpacing(18)
        self.file_cards_layout.setVerticalSpacing(18)
        self._file_cards_stacked = False
        self._set_file_cards_stacked(False, force=True)

        config_card = SurfaceFrame("card")
        config_layout = QVBoxLayout(config_card)
        config_layout.setContentsMargins(24, 20, 24, 20)
        config_layout.setSpacing(16)
        config_title = QLabel("本次审查设置")
        config_title.setObjectName("SectionTitle")

        self.backend_combo = DropdownOnlyComboBox()
        _populate_backend_combo(self.backend_combo)
        self.model_edit = QLineEdit()
        self.model_edit.setPlaceholderText("可选，临时指定本次使用的 Claude 模型")
        self.progress_combo = DropdownOnlyComboBox()
        _populate_progress_level_combo(self.progress_combo)
        self.output_dir_edit = QLineEdit()
        self.output_dir_button = QPushButton("选择")
        self.timeout_spin = TimeoutComboBox()
        self.effort_combo = DropdownOnlyComboBox()
        _populate_effort_combo(self.effort_combo)
        self.review_profile_combo = DropdownOnlyComboBox()
        _populate_review_profile_combo(self.review_profile_combo)
        self.save_raw_checkbox = QCheckBox("保留原始运行记录（便于排查问题）")
        self.save_raw_checkbox.setChecked(True)

        form = QFormLayout()
        _configure_form_layout(form)

        _pin_form_field_height(self.backend_combo)
        _pin_form_field_height(self.model_edit)
        _pin_form_field_height(self.progress_combo)
        _pin_form_field_height(self.output_dir_edit)
        _pin_form_field_height(self.timeout_spin)
        _pin_form_field_height(self.effort_combo)
        _pin_form_field_height(self.review_profile_combo)
        self.output_dir_button.setMinimumHeight(40)
        self.output_dir_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        form.addRow("审查引擎", self.backend_combo)
        form.addRow("模型名称（可选）", self.model_edit)
        form.addRow("过程显示", self.progress_combo)

        output_row = QHBoxLayout()
        output_row.setContentsMargins(0, 0, 0, 0)
        output_row.setSpacing(8)
        output_row.addWidget(self.output_dir_edit, 1)
        output_row.addWidget(self.output_dir_button)
        output_wrap = QWidget()
        output_wrap.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        output_wrap.setMinimumHeight(40)
        output_wrap.setLayout(output_row)
        form.addRow("结果保存位置", output_wrap)
        form.addRow("超时时间（秒）", self.timeout_spin)
        form.addRow("审查仔细程度", self.effort_combo)
        form.addRow("审查策略", self.review_profile_combo)

        config_layout.addWidget(config_title)
        config_layout.addLayout(form)
        config_layout.addWidget(self.save_raw_checkbox)

        instruction_card = SurfaceFrame("card")
        instruction_layout = QVBoxLayout(instruction_card)
        instruction_layout.setContentsMargins(24, 20, 24, 20)
        instruction_layout.setSpacing(12)
        instruction_title = QLabel("补充说明")
        instruction_title.setObjectName("SectionTitle")
        instruction_note = QLabel("这些说明会追加到本次审查中，用来表达关注重点和个人偏好。")
        instruction_note.setObjectName("MutedLabel")
        self.instruction_edit = AutoResizingPlainTextEdit(min_rows=2, max_rows=8)
        self.instruction_edit.setPlaceholderText("补充本次关注重点，例如优先检查资格条件")
        self.user_instruction_edit = AutoResizingPlainTextEdit(min_rows=2, max_rows=8)
        self.user_instruction_edit.setPlaceholderText("补充个人偏好，例如证据需附原文片段")
        instruction_layout.addWidget(instruction_title)
        instruction_layout.addWidget(instruction_note)
        instruction_layout.addWidget(self.instruction_edit)
        instruction_layout.addWidget(self.user_instruction_edit)

        action_card = SurfaceFrame("card")
        action_layout = QVBoxLayout(action_card)
        action_layout.setContentsMargins(24, 20, 24, 20)
        action_layout.setSpacing(12)
        bottom_hint = QLabel("桌面端沿用现有审查流程和导出结果，不改变命令行链路。")
        bottom_hint.setObjectName("MutedLabel")
        action_layout.addWidget(bottom_hint)

        left_layout.addWidget(self.file_cards)
        left_layout.addWidget(config_card)
        left_layout.addWidget(instruction_card)
        left_layout.addWidget(action_card)
        left_layout.addStretch(1)

        self.left_scroll = QScrollArea()
        self.left_scroll.setWidgetResizable(True)
        self.left_scroll.setFrameShape(QFrame.NoFrame)
        self.left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.left_scroll.setWidget(left)
        self.left_scroll.viewport().setAcceptDrops(True)
        self.left_scroll.viewport().installEventFilter(self)
        left_container_layout.addWidget(top_actions)
        left_container_layout.addWidget(self.left_scroll, 1)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(18)

        self.status_card = SurfaceFrame("card")
        self.status_card.setFixedHeight(176)
        status_layout = QGridLayout(self.status_card)
        status_layout.setContentsMargins(24, 20, 24, 20)
        status_layout.setHorizontalSpacing(18)
        status_layout.setVerticalSpacing(6)
        status_title = QLabel("执行状态")
        status_title.setObjectName("SectionTitle")
        self.stage_value = QLabel("等待开始")
        self.stage_note_value = QLabel("等待第一条进度消息")
        self.current_bid_value = QLabel("未开始")
        self.result_value = QLabel("就绪")
        self.stage_value.setWordWrap(False)
        self.stage_note_value.setObjectName("MutedLabel")
        self.stage_note_value.setWordWrap(False)
        self.current_bid_value.setWordWrap(False)
        self.result_value.setWordWrap(False)
        self.stage_value.setMaximumHeight(28)
        self.stage_note_value.setMaximumHeight(24)
        self.current_bid_value.setMaximumHeight(24)
        self.result_value.setMaximumHeight(28)
        self.stage_value.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.stage_note_value.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.current_bid_value.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.result_value.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        status_layout.addWidget(status_title, 0, 0, 1, 2)
        status_layout.addWidget(QLabel("当前阶段"), 1, 0)
        status_layout.addWidget(self.stage_value, 1, 1)
        status_layout.addWidget(QLabel("阶段说明"), 2, 0)
        status_layout.addWidget(self.stage_note_value, 2, 1)
        status_layout.addWidget(QLabel("当前投标文件"), 3, 0)
        status_layout.addWidget(self.current_bid_value, 3, 1)
        status_layout.addWidget(QLabel("任务状态"), 4, 0)
        status_layout.addWidget(self.result_value, 4, 1)

        self.timeline_card = SurfaceFrame("card")
        self.timeline_card.setMinimumHeight(170)
        timeline_layout = QVBoxLayout(self.timeline_card)
        timeline_layout.setContentsMargins(24, 20, 24, 20)
        timeline_layout.setSpacing(12)
        timeline_title = QLabel("处理进度")
        timeline_title.setObjectName("SectionTitle")
        self.timeline_list = QListWidget()
        self.timeline_list.setUniformItemSizes(True)
        timeline_layout.addWidget(timeline_title)
        timeline_layout.addWidget(self.timeline_list, 1)

        self.log_card = SurfaceFrame("card")
        self.log_card.setMinimumHeight(220)
        log_layout = QVBoxLayout(self.log_card)
        log_layout.setContentsMargins(24, 20, 24, 20)
        log_layout.setSpacing(12)
        log_title = QLabel("详细记录")
        log_title.setObjectName("SectionTitle")
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.document().setMaximumBlockCount(3000)
        log_layout.addWidget(log_title)
        log_layout.addWidget(self.log_view, 1)

        self.activity_splitter = QSplitter(Qt.Vertical)
        self.activity_splitter.setChildrenCollapsible(False)
        self.activity_splitter.addWidget(self.timeline_card)
        self.activity_splitter.addWidget(self.log_card)
        self.activity_splitter.setStretchFactor(0, 1)
        self.activity_splitter.setStretchFactor(1, 2)
        self.activity_splitter.setSizes([240, 360])

        right_layout.addWidget(self.status_card, 0)
        right_layout.addWidget(self.activity_splitter, 1)

        splitter.addWidget(left_container)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 4)
        splitter.setSizes([900, 700])

        root.addWidget(splitter, 1)

        self.output_dir_button.clicked.connect(self._browse_output_dir)
        self.open_output_button.clicked.connect(self._open_output_dir)
        self.backend_combo.currentIndexChanged.connect(lambda _index: self._on_backend_changed(_combo_value(self.backend_combo)))

    def eventFilter(self, watched: object, event: object) -> bool:
        if watched is self.left_scroll.viewport() and hasattr(event, "type"):
            event_type = event.type()
            if event_type == QEvent.Resize:
                self._update_file_cards_layout()
            if event_type in {QEvent.DragEnter, QEvent.DragMove} and hasattr(event, "mimeData"):
                point = self._event_point(event)
                if point is not None and self._drop_target_for_viewport_pos(point) is not None:
                    if _extract_local_file_paths_from_urls(event.mimeData().urls()):
                        event.acceptProposedAction()
                        return True
            if event_type == QEvent.Drop and hasattr(event, "mimeData"):
                point = self._event_point(event)
                if point is not None and self._handle_drop_on_viewport(event.mimeData().urls(), point):
                    event.acceptProposedAction()
                    return True
        return super().eventFilter(watched, event)

    def _drop_target_for_viewport_pos(self, point: QPoint) -> SingleFileDropCard | MultiFileDropCard | None:
        content = self.left_scroll.widget()
        if content is None:
            return None
        content_point = content.mapFrom(self.left_scroll.viewport(), point)
        for card in (self.tender_card, self.bid_card):
            if card.geometry().contains(content_point):
                return card
        return None

    def _handle_drop_on_viewport(self, urls: list[QUrl], point: QPoint) -> bool:
        target = self._drop_target_for_viewport_pos(point)
        if target is None:
            return False
        if target is self.tender_card:
            return self.tender_card._handle_drop_urls(urls)
        if target is self.bid_card:
            return self.bid_card._handle_drop_urls(urls)
        return False

    @staticmethod
    def _event_point(event: object) -> QPoint | None:
        if hasattr(event, "position"):
            return event.position().toPoint()
        if hasattr(event, "pos"):
            return event.pos()
        return None

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self._update_file_cards_layout()

    def _available_file_cards_width(self) -> int:
        viewport = self.left_scroll.viewport()
        if viewport is not None:
            return max(0, viewport.width())
        return max(0, self.width())

    def _update_file_cards_layout(self) -> None:
        self._set_file_cards_stacked(self._available_file_cards_width() < FILE_CARDS_STACK_THRESHOLD)

    def _set_file_cards_stacked(self, stacked: bool, *, force: bool = False) -> None:
        if not force and stacked == self._file_cards_stacked:
            return
        self.file_cards_layout.removeWidget(self.tender_card)
        self.file_cards_layout.removeWidget(self.bid_card)
        self.file_cards_layout.setColumnStretch(0, 0)
        self.file_cards_layout.setColumnStretch(1, 0)
        self.file_cards_layout.setRowStretch(0, 0)
        self.file_cards_layout.setRowStretch(1, 0)
        self.file_cards_layout.addWidget(self.tender_card, 0, 0)
        if stacked:
            self.file_cards_layout.addWidget(self.bid_card, 1, 0)
            self.file_cards_layout.setColumnStretch(0, 1)
        else:
            self.file_cards_layout.addWidget(self.bid_card, 0, 1)
            self.file_cards_layout.setColumnStretch(0, 1)
            self.file_cards_layout.setColumnStretch(1, 1)
        self._file_cards_stacked = stacked

    def load_settings(self, settings: DesktopSettings) -> None:
        self._backend_model_defaults = {
            "claude": settings.model_for_backend("claude"),
            "opencode": settings.model_for_backend("opencode"),
        }
        backend = settings.default_backend or "claude"
        self._last_model_backend = backend
        self.backend_combo.blockSignals(True)
        _set_combo_value(self.backend_combo, backend)
        self.backend_combo.blockSignals(False)
        self.model_edit.setText(self._backend_model_defaults.get(backend, ""))
        self._update_model_placeholder(backend)
        _set_combo_value(self.progress_combo, settings.default_progress_level or "agent")
        self.output_dir_edit.setText(settings.default_output_dir)
        self.timeout_spin.setValue(settings.default_timeout_sec or 1800)
        _set_combo_value(self.effort_combo, settings.default_effort or "low")
        _set_combo_value(self.review_profile_combo, settings.default_review_profile or "thorough")
        self.instruction_edit.setPlainText(settings.default_instruction)
        self.user_instruction_edit.setPlainText(settings.default_user_instruction)

    def build_request(self, settings: DesktopSettings, session_api_key: str = "") -> ReviewRunRequest:
        return ReviewRunRequest(
            tender_path=self.tender_card.file_path(),
            bid_paths=self.bid_card.paths(),
            backend=_combo_value(self.backend_combo),
            output_dir=self.output_dir_edit.text().strip(),
            model=self.model_edit.text().strip(),
            claude_bin=settings.claude_bin.strip(),
            opencode_bin=settings.opencode_bin.strip(),
            opencode_provider=settings.opencode_provider.strip() or "volcengine",
            opencode_api_url=settings.opencode_api_url.strip(),
            opencode_api_key=session_api_key.strip(),
            progress_level=_combo_value(self.progress_combo),
            timeout_sec=self.timeout_spin.value(),
            effort=_combo_value(self.effort_combo),
            review_profile=_combo_value(self.review_profile_combo),
            instruction=self.instruction_edit.toPlainText().strip(),
            user_instruction=self.user_instruction_edit.toPlainText().strip(),
            save_raw_output=self.save_raw_checkbox.isChecked(),
        )

    def clear_progress(self) -> None:
        self.log_view.clear()
        self.timeline_list.clear()
        self._set_stage_text("等待开始")
        self._set_stage_note("等待第一条进度消息")
        self._set_current_bid_text("未开始")
        self._set_result_text("就绪")

    def append_progress(self, message: str, level: str) -> None:
        timestamp = QDateTime.currentDateTime().toString("HH:mm:ss")
        display_message = _friendly_progress_message(message)
        self.log_view.appendPlainText(f"[{timestamp}] {display_message}")
        if message.startswith("[pipeline]") or message.startswith("[agent]") or level in {"basic", "agent"}:
            self.timeline_list.addItem(f"{timestamp}  {display_message}")
            self.timeline_list.scrollToBottom()
        self._update_status(display_message)

    def set_running(self, running: bool) -> None:
        self.run_button.setEnabled(not running)
        self.run_button.setText("审查进行中..." if running else "开始审查")
        if running:
            self._set_result_text("运行中")

    def _set_stage_text(self, text: str, *, tooltip: str | None = None) -> None:
        display = _collapse_progress_text(text, limit=56)
        self.stage_value.setText(display)
        self.stage_value.setToolTip(tooltip or text)

    def _set_stage_note(self, text: str, *, tooltip: str | None = None) -> None:
        display = _collapse_progress_text(text, limit=80)
        self.stage_note_value.setText(display)
        self.stage_note_value.setToolTip(tooltip or text)

    def _set_current_bid_text(self, text: str, *, tooltip: str | None = None) -> None:
        display = _collapse_progress_text(text, limit=72)
        self.current_bid_value.setText(display)
        self.current_bid_value.setToolTip(tooltip or text)

    def _set_result_text(self, text: str, *, tooltip: str | None = None) -> None:
        display = _collapse_progress_text(text, limit=32)
        self.result_value.setText(display)
        self.result_value.setToolTip(tooltip or text)

    def _update_status(self, message: str) -> None:
        raw = (message or "").strip()
        if "自动识别招标/投标文件角色" in raw:
            self._set_stage_text("正在识别文件类型")
            self._set_stage_note("准备确认招标文件和投标文件角色。")
            return
        if "角色识别完成" in raw:
            self._set_stage_text("文件识别完成")
            self._set_stage_note("已确认本次任务的招标文件和投标文件。")
            return
        if "开始审查" in raw:
            self._set_stage_text("正在逐份审查")
            self._set_stage_note("已进入逐份审查阶段。")
            self._set_current_bid_text(raw.split(":", 1)[-1].strip())
            self._set_result_text("运行中")
            return
        if "完成审查" in raw:
            self._set_stage_text("本轮报告已生成")
            self._set_stage_note("当前投标文件的报告已写入输出目录。")
            return
        if "会话已建立" in raw:
            self._set_stage_text("审查引擎已就绪")
            self._set_stage_note(raw)
            return
        if raw.startswith("[审查引擎] 当前阶段："):
            body = raw.replace("[审查引擎] 当前阶段：", "", 1).strip()
            phase, sep, next_hint = body.partition("；下一步：")
            self._set_stage_text(phase.strip() or "正在审查", tooltip=body)
            if sep and next_hint.strip():
                self._set_stage_note(f"下一步：{next_hint.strip()}", tooltip=body)
            else:
                self._set_stage_note("继续推进当前审查阶段。", tooltip=body)
            return
        if raw.startswith("[审查引擎] 进行中："):
            body = raw.replace("[审查引擎] 进行中：", "", 1).strip()
            self._set_stage_note(
                _compact_status_detail(body, fallback="正在处理细节步骤，详见下方详细记录。"),
                tooltip=body,
            )
            return
        if raw.startswith("[审查引擎] 阶段成果："):
            body = raw.replace("[审查引擎] 阶段成果：", "", 1).strip()
            self._set_stage_note(
                _compact_status_detail(body, fallback="阶段成果已更新，详见下方详细记录。"),
                tooltip=body,
            )
            return
        if raw.startswith("[审查引擎] 输出摘要："):
            body = raw.replace("[审查引擎] 输出摘要：", "", 1).strip()
            summary = _compact_status_detail(body, fallback="输出摘要较长，详见下方详细记录。")
            self._set_stage_note(f"输出摘要：{summary}", tooltip=body)
            return
        if raw.startswith("[工作台] 当前运行目录根："):
            self._set_stage_note(raw.replace("[工作台] ", "", 1), tooltip=raw)

    def _browse_output_dir(self) -> None:
        current = self.output_dir_edit.text().strip() or os.getcwd()
        path = QFileDialog.getExistingDirectory(self, "选择结果保存位置", current)
        if path:
            self.output_dir_edit.setText(str(Path(path).resolve()))

    def _open_output_dir(self) -> None:
        _open_local_path(self.output_dir_edit.text().strip())

    def _on_backend_changed(self, backend: str) -> None:
        backend = (backend or "claude").strip().lower()
        previous_backend = self._last_model_backend
        current_model = self.model_edit.text().strip()
        previous_default = self._backend_model_defaults.get(previous_backend, "").strip()
        if not current_model or current_model == previous_default:
            self.model_edit.setText(self._backend_model_defaults.get(backend, ""))
        self._update_model_placeholder(backend)
        self._last_model_backend = backend

    def _update_model_placeholder(self, backend: str) -> None:
        if (backend or "claude").strip().lower() == "opencode":
            self.model_edit.setPlaceholderText("可选，临时指定本次使用的 OpenCode 模型")
            return
        self.model_edit.setPlaceholderText("可选，临时指定本次使用的 Claude 模型")


class ResultsPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._result: BatchReviewData | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        self.summary_card = SurfaceFrame("card")
        summary_layout = QVBoxLayout(self.summary_card)
        summary_layout.setContentsMargins(24, 18, 24, 18)
        summary_layout.setSpacing(12)
        summary_title = QLabel("当前审查结果与概况")
        summary_title.setObjectName("SectionTitle")
        self.tender_label = QLabel("尚未加载审查结果")
        self.tender_label.setWordWrap(True)
        self.role_label = QLabel("")
        self.role_label.setObjectName("MutedLabel")
        summary_layout.addWidget(summary_title)
        summary_layout.addWidget(self.tender_label)
        summary_layout.addWidget(self.role_label)

        self.summary_stats = QWidget()
        stats_row = QHBoxLayout(self.summary_stats)
        stats_row.setContentsMargins(0, 0, 0, 0)
        stats_row.setSpacing(12)
        self.requirement_card = CompactStatCard("招标要求")
        self.non_compliant_card = CompactStatCard("不符合项")
        self.risk_card = CompactStatCard("风险项")
        self.manual_card = CompactStatCard("待人工确认")
        for card in [self.requirement_card, self.non_compliant_card, self.risk_card, self.manual_card]:
            stats_row.addWidget(card)
        summary_layout.addWidget(self.summary_stats)

        control_layout = QHBoxLayout()
        control_layout.setContentsMargins(0, 0, 0, 0)
        control_layout.setSpacing(10)
        control_label = QLabel("投标文件")
        control_label.setObjectName("MutedLabel")
        self.run_combo = DropdownOnlyComboBox()
        self.run_combo.setMinimumWidth(360)
        self.run_combo.setMaximumWidth(460)
        self.open_output_button = QPushButton("打开结果目录")
        self.open_json_button = QPushButton("打开结构化结果")
        self.open_md_button = QPushButton("打开文本报告")
        self.open_docx_button = QPushButton("打开 Word 报告")
        self.open_batch_button = QPushButton("打开批量汇总")
        for button in [
            self.open_output_button,
            self.open_json_button,
            self.open_md_button,
            self.open_docx_button,
            self.open_batch_button,
        ]:
            button.setProperty("kind", "ghost")
            button.setMinimumHeight(40)
        control_layout.addWidget(control_label)
        control_layout.addWidget(self.run_combo)
        control_layout.addStretch(1)
        control_layout.addWidget(self.open_output_button)
        control_layout.addWidget(self.open_json_button)
        control_layout.addWidget(self.open_md_button)
        control_layout.addWidget(self.open_docx_button)
        control_layout.addWidget(self.open_batch_button)
        summary_layout.addLayout(control_layout)

        table_card = SurfaceFrame("card")
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(20, 18, 20, 18)
        table_layout.setSpacing(10)
        table_title = QLabel("问题与建议明细")
        table_title.setObjectName("SectionTitle")
        self.findings_table = QTableWidget(0, 7)
        self.findings_table.setHorizontalHeaderLabels(
            ["编号", "条款编号", "结论", "问题说明", "招标依据", "投标依据", "处理建议"]
        )
        self.findings_table.setAlternatingRowColors(True)
        self.findings_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.findings_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.findings_table.setWordWrap(True)
        self.findings_table.setTextElideMode(Qt.ElideNone)
        self.findings_table.setItemDelegate(FindingsTableDelegate(self.findings_table))
        self.findings_table.verticalHeader().setDefaultAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.findings_table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self._row_resize_pending = False
        header = self.findings_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        for index in [3, 4, 5, 6]:
            header.setSectionResizeMode(index, QHeaderView.Stretch)
        header.sectionResized.connect(self._schedule_findings_row_resize)
        table_layout.addWidget(table_title)
        table_layout.addWidget(self.findings_table, 1)

        layout.addWidget(self.summary_card)
        layout.addWidget(table_card, 1)

        self.run_combo.currentIndexChanged.connect(self._show_run)
        self.open_output_button.clicked.connect(self._open_output)
        self.open_json_button.clicked.connect(self._open_json)
        self.open_md_button.clicked.connect(self._open_md)
        self.open_docx_button.clicked.connect(self._open_docx)
        self.open_batch_button.clicked.connect(self._open_batch)

    def _set_tender_summary_text(self, text: str) -> None:
        display = _collapse_progress_text(text, limit=160)
        self.tender_label.setText(display)
        self.tender_label.setToolTip(text)

    def _set_role_summary_text(self, text: str) -> None:
        display = _collapse_progress_text(text, limit=180)
        self.role_label.setText(display)
        self.role_label.setToolTip(text)

    def set_result(self, result: BatchReviewData | None) -> None:
        self._result = result
        self.run_combo.blockSignals(True)
        self.run_combo.clear()
        self.findings_table.setRowCount(0)
        if result is None or not result.runs:
            self._set_tender_summary_text("尚未加载审查结果")
            self._set_role_summary_text("")
            self.run_combo.blockSignals(False)
            return
        self._set_tender_summary_text(f"招标文件：{result.tender_path}")
        self._set_role_summary_text(
            f"文件识别方式：{_role_reasoning_text(result.role_reasoning or 'manual')} | 结果目录：{result.output_dir}"
        )
        for idx, run in enumerate(result.runs, start=1):
            self.run_combo.addItem(f"{idx}. {_basename(run.bid_path)}", run)
        self.run_combo.blockSignals(False)
        self.run_combo.setCurrentIndex(0)
        self._show_run(0)

    def _current_run(self) -> ReviewRunData | None:
        data = self.run_combo.currentData()
        return data if isinstance(data, ReviewRunData) else None

    def _show_run(self, index: int) -> None:
        if index < 0:
            return
        run = self._current_run()
        if run is None:
            return
        summary = run.report.get("summary", run.summary) or {}
        bid_name = _basename(run.bid_path)
        self.requirement_card.set_value(
            str(summary.get("requirement_count", 0)),
            _collapse_progress_text(bid_name, limit=24),
            tooltip=bid_name,
        )
        self.non_compliant_card.set_value(str(summary.get("non_compliant_count", 0)), "需尽快整改")
        self.risk_card.set_value(str(summary.get("risk_count", 0)), "重点关注")
        self.manual_card.set_value(str(summary.get("needs_manual_count", 0)), "建议复核")

        findings = run.report.get("findings", []) or []
        self.findings_table.setRowCount(len(findings))
        for row_index, finding in enumerate(findings):
            if not isinstance(finding, dict):
                continue
            values = [
                str(finding.get("id", "")),
                str(finding.get("requirement_id", "")),
                _status_text(str(finding.get("status", ""))),
                str(finding.get("issue", "")),
                str(finding.get("tender_evidence", "")),
                str(finding.get("bid_evidence", "")),
                str(finding.get("recommendation", "")),
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col_index in {0, 1, 2}:
                    item.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
                else:
                    item.setTextAlignment(Qt.AlignLeft | Qt.AlignTop)
                if col_index == 2:
                    status = str(finding.get("status", ""))
                    if status == "non_compliant":
                        item.setForeground(QColor("#EC7B87"))
                    elif status == "risk":
                        item.setForeground(QColor("#E3B16A"))
                    elif status == "needs_manual":
                        item.setForeground(QColor("#7EB8E8"))
                self.findings_table.setItem(row_index, col_index, item)
        self._schedule_findings_row_resize()

    def _schedule_findings_row_resize(self, *args) -> None:  # noqa: ANN002
        if self._row_resize_pending:
            return
        self._row_resize_pending = True
        QTimer.singleShot(0, self._apply_findings_row_resize)

    def _apply_findings_row_resize(self) -> None:
        self._row_resize_pending = False
        self.findings_table.resizeRowsToContents()

    def _open_output(self) -> None:
        run = self._current_run()
        _open_local_path(run.output_dir if run else None)

    def _open_json(self) -> None:
        run = self._current_run()
        _open_local_path(run.json_path if run else None)

    def _open_md(self) -> None:
        run = self._current_run()
        _open_local_path(run.markdown_path if run else None)

    def _open_docx(self) -> None:
        run = self._current_run()
        _open_local_path(run.docx_path if run else None)

    def _open_batch(self) -> None:
        _open_local_path(self._result.batch_summary_path if self._result else None)


class SettingsPage(QWidget):
    save_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        content = QWidget()
        content.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(18)

        toolchain = SurfaceFrame("card")
        toolchain_layout = QVBoxLayout(toolchain)
        toolchain_layout.setContentsMargins(24, 20, 24, 20)
        toolchain_layout.setSpacing(16)
        toolchain_title = QLabel("默认审查设置")
        toolchain_title.setObjectName("SectionTitle")

        self.default_backend = DropdownOnlyComboBox()
        _populate_backend_combo(self.default_backend)
        self.default_progress = DropdownOnlyComboBox()
        _populate_progress_level_combo(self.default_progress)
        self.default_timeout = TimeoutComboBox()
        self.output_dir = QLineEdit()
        self.common_output_dir_row = self._path_row(self.output_dir, self._browse_output_dir)

        self.claude_default_model = QLineEdit()
        self.claude_default_model.setPlaceholderText("未填写时使用环境变量中的默认 Claude 模型")
        self.default_effort = DropdownOnlyComboBox()
        _populate_effort_combo(self.default_effort)
        self.default_review_profile = DropdownOnlyComboBox()
        _populate_review_profile_combo(self.default_review_profile)
        self.claude_sdk_base_url = QLineEdit()
        self.claude_sdk_base_url.setPlaceholderText("可选，自定义 Claude 服务地址")
        self.claude_sdk_auth_token = QLineEdit()
        self.claude_sdk_auth_token.setEchoMode(QLineEdit.Password)
        self.claude_sdk_auth_token.setPlaceholderText("仅当前窗口临时使用，不会写入本地设置")
        self.claude_bin = QLineEdit()

        self.opencode_default_model = QLineEdit()
        self.opencode_default_model.setPlaceholderText("未填写时使用 OpenCode 的默认模型")
        self.opencode_bin = QLineEdit()
        self.opencode_provider = QLineEdit()
        self.opencode_api_url = QLineEdit()
        self.opencode_api_key = QLineEdit()
        self.opencode_api_key.setEchoMode(QLineEdit.Password)
        self.opencode_api_key.setPlaceholderText("仅当前窗口临时使用，不会写入本地设置")

        common_form = QFormLayout()
        _configure_form_layout(common_form)
        _pin_form_field_height(self.default_backend)
        _pin_form_field_height(self.default_progress)
        _pin_form_field_height(self.default_timeout)
        _pin_form_field_height(self.output_dir)
        common_title = QLabel("通用默认设置")
        common_title.setObjectName("SectionTitle")
        common_form.addRow("默认审查引擎", self.default_backend)
        common_form.addRow("默认过程显示", self.default_progress)
        common_form.addRow("默认超时时间（秒）", self.default_timeout)
        common_form.addRow("默认结果保存位置", self.common_output_dir_row)

        self.backend_section_title = QLabel("")
        self.backend_section_title.setObjectName("SectionTitle")
        self.backend_stack = QStackedWidget()

        claude_page = QWidget()
        claude_layout = QVBoxLayout(claude_page)
        claude_layout.setContentsMargins(0, 0, 0, 0)
        claude_layout.setSpacing(10)
        claude_form = QFormLayout()
        _configure_form_layout(claude_form)
        _pin_form_field_height(self.claude_default_model)
        _pin_form_field_height(self.default_effort)
        _pin_form_field_height(self.default_review_profile)
        _pin_form_field_height(self.claude_sdk_base_url)
        _pin_form_field_height(self.claude_sdk_auth_token)
        _pin_form_field_height(self.claude_bin)
        claude_form.addRow("默认 Claude 模型", self.claude_default_model)
        claude_form.addRow("Claude 服务地址", self.claude_sdk_base_url)
        claude_form.addRow("Claude 访问凭证", self.claude_sdk_auth_token)
        claude_form.addRow("默认审查仔细程度", self.default_effort)
        claude_form.addRow("默认审查策略", self.default_review_profile)
        claude_layout.addLayout(claude_form)

        self.claude_advanced_toggle = QPushButton("显示高级设置")
        self.claude_advanced_toggle.setCheckable(True)
        self.claude_advanced_toggle.setProperty("kind", "ghost")
        self.claude_advanced_toggle.setChecked(False)

        self.claude_advanced_panel = QWidget()
        self.claude_advanced_panel.setVisible(False)
        claude_advanced_layout = QVBoxLayout(self.claude_advanced_panel)
        claude_advanced_layout.setContentsMargins(0, 0, 0, 0)
        claude_advanced_layout.setSpacing(0)
        claude_advanced_form = QFormLayout()
        _configure_form_layout(claude_advanced_form)
        claude_advanced_form.addRow("Claude 命令行程序路径", self._path_row(self.claude_bin, self._browse_claude_bin))
        claude_advanced_layout.addLayout(claude_advanced_form)

        claude_layout.addWidget(self.claude_advanced_toggle, 0, Qt.AlignLeft)
        claude_layout.addWidget(self.claude_advanced_panel)

        opencode_page = QWidget()
        opencode_layout = QVBoxLayout(opencode_page)
        opencode_layout.setContentsMargins(0, 0, 0, 0)
        opencode_layout.setSpacing(0)
        opencode_form = QFormLayout()
        _configure_form_layout(opencode_form)
        _pin_form_field_height(self.opencode_default_model)
        _pin_form_field_height(self.opencode_bin)
        _pin_form_field_height(self.opencode_provider)
        _pin_form_field_height(self.opencode_api_url)
        _pin_form_field_height(self.opencode_api_key)
        opencode_form.addRow("默认 OpenCode 模型", self.opencode_default_model)
        opencode_form.addRow("OpenCode 程序路径", self._path_row(self.opencode_bin, self._browse_opencode_bin))
        opencode_form.addRow("服务提供方", self.opencode_provider)
        opencode_form.addRow("服务地址", self.opencode_api_url)
        opencode_form.addRow("访问密钥", self.opencode_api_key)
        opencode_layout.addLayout(opencode_form)

        self.backend_stack.addWidget(claude_page)
        self.backend_stack.addWidget(opencode_page)

        toolchain_layout.addWidget(toolchain_title)
        toolchain_layout.addWidget(common_title)
        toolchain_layout.addLayout(common_form)
        toolchain_layout.addWidget(self.backend_section_title)
        toolchain_layout.addWidget(self.backend_stack)

        self.guidance = QLabel("")
        self.guidance.setObjectName("MutedLabel")
        toolchain_layout.addWidget(self.guidance)
        self.runtime_label = QLabel("")
        self.runtime_label.setObjectName("MutedLabel")
        self.runtime_label.setWordWrap(True)
        toolchain_layout.addWidget(self.runtime_label)

        instruction_card = SurfaceFrame("card")
        instruction_layout = QVBoxLayout(instruction_card)
        instruction_layout.setContentsMargins(24, 20, 24, 20)
        instruction_layout.setSpacing(12)
        instruction_title = QLabel("默认补充说明")
        instruction_title.setObjectName("SectionTitle")
        self.default_instruction = QPlainTextEdit()
        self.default_instruction.setMinimumHeight(120)
        self.default_instruction.setPlaceholderText("每次审查默认追加的任务说明")
        self.default_user_instruction = QPlainTextEdit()
        self.default_user_instruction.setMinimumHeight(120)
        self.default_user_instruction.setPlaceholderText("每次审查默认追加的个人偏好说明")
        instruction_layout.addWidget(instruction_title)
        instruction_layout.addWidget(self.default_instruction)
        instruction_layout.addWidget(self.default_user_instruction)

        action_row = QHBoxLayout()
        self.save_button = QPushButton("保存默认设置")
        self.save_button.setProperty("kind", "primary")
        action_row.addWidget(self.save_button)
        action_row.addStretch(1)

        content_layout.addWidget(toolchain)
        content_layout.addWidget(instruction_card)
        content_layout.addLayout(action_row)
        content_layout.addStretch(1)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setWidget(content)

        layout.addWidget(self.scroll, 1)

        self.save_button.clicked.connect(self.save_requested.emit)
        self.default_backend.currentIndexChanged.connect(lambda _index: self._apply_backend_mode(_combo_value(self.default_backend)))
        self.claude_advanced_toggle.toggled.connect(self._toggle_claude_advanced)

    def load_settings(
        self,
        settings: DesktopSettings,
        session_api_key: str = "",
        session_claude_auth_token: str = "",
    ) -> None:
        backend = settings.default_backend or "claude"
        self.default_backend.blockSignals(True)
        _set_combo_value(self.default_backend, backend)
        self.default_backend.blockSignals(False)
        self.claude_default_model.setText(settings.model_for_backend("claude"))
        self.opencode_default_model.setText(settings.model_for_backend("opencode"))
        self.claude_sdk_base_url.setText(settings.claude_sdk_base_url)
        self.claude_sdk_auth_token.setText(session_claude_auth_token)
        _set_combo_value(self.default_progress, settings.default_progress_level or "agent")
        self.default_timeout.setValue(settings.default_timeout_sec or 1800)
        _set_combo_value(self.default_effort, settings.default_effort or "low")
        _set_combo_value(self.default_review_profile, settings.default_review_profile or "thorough")
        self.output_dir.setText(settings.default_output_dir)
        self.claude_bin.setText(settings.claude_bin)
        self.opencode_bin.setText(settings.opencode_bin)
        self.opencode_provider.setText(settings.opencode_provider or "volcengine")
        self.opencode_api_url.setText(settings.opencode_api_url)
        self.opencode_api_key.setText(session_api_key)
        self.default_instruction.setPlainText(settings.default_instruction)
        self.default_user_instruction.setPlainText(settings.default_user_instruction)
        self._apply_backend_mode(backend)
        self._refresh_runtime_notice()

    def snapshot(self, previous: DesktopSettings) -> DesktopSettings:
        backend = _combo_value(self.default_backend)
        claude_model = self.claude_default_model.text().strip()
        opencode_model = self.opencode_default_model.text().strip()
        return DesktopSettings(
            default_backend=backend,
            default_output_dir=self.output_dir.text().strip(),
            default_model=claude_model if backend == "claude" else opencode_model,
            claude_default_model=claude_model,
            opencode_default_model=opencode_model,
            default_progress_level=_combo_value(self.default_progress),
            default_timeout_sec=self.default_timeout.value(),
            default_effort=_combo_value(self.default_effort),
            default_review_profile=_combo_value(self.default_review_profile),
            default_instruction=self.default_instruction.toPlainText().strip(),
            default_user_instruction=self.default_user_instruction.toPlainText().strip(),
            claude_sdk_base_url=self.claude_sdk_base_url.text().strip(),
            claude_bin=self.claude_bin.text().strip(),
            opencode_bin=self.opencode_bin.text().strip(),
            opencode_provider=self.opencode_provider.text().strip() or "volcengine",
            opencode_api_url=self.opencode_api_url.text().strip(),
            last_batch_summary=previous.last_batch_summary,
            last_output_dir=previous.last_output_dir,
        )

    def session_api_key(self) -> str:
        return self.opencode_api_key.text().strip()

    def session_claude_auth_token(self) -> str:
        return self.claude_sdk_auth_token.text().strip()

    def _apply_backend_mode(self, backend: str) -> None:
        normalized = (backend or "claude").strip().lower()
        if normalized == "opencode":
            self.backend_section_title.setText("OpenCode 默认设置")
            self.backend_stack.setCurrentIndex(1)
            self.guidance.setText("这里保存 OpenCode 的默认模型和服务地址；访问密钥只保留在当前窗口。")
            self._refresh_runtime_notice()
            return

        self.backend_section_title.setText("Claude 默认设置")
        self.backend_stack.setCurrentIndex(0)
        self.guidance.setText("这里保存 Claude 的默认模型和服务地址；访问凭证只保留在当前窗口。")
        self._refresh_runtime_notice()

    def _toggle_claude_advanced(self, checked: bool) -> None:
        self.claude_advanced_panel.setVisible(bool(checked))
        self.claude_advanced_toggle.setText("隐藏高级设置" if checked else "显示高级设置")

    def _refresh_runtime_notice(self) -> None:
        info = runtime_root_status()
        root = str(info.get("root", "") or "")
        writable = bool(info.get("writable", False))
        if not bool(info.get("managed", False)):
            self.runtime_label.setText("开发态：默认沿用仓库/系统既有路径。")
            return
        state = "可写" if writable else "不可写"
        self.runtime_label.setText(f"运行目录根：{root}（{state}）")

    def _path_row(self, line_edit: QLineEdit, browse_callback) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        button = QPushButton("选择")
        button.setMinimumHeight(40)
        button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        button.clicked.connect(browse_callback)
        layout.addWidget(line_edit, 1)
        layout.addWidget(button)
        row.setMinimumHeight(40)
        row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        return row

    def _browse_output_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择结果保存位置", self.output_dir.text().strip() or os.getcwd())
        if path:
            self.output_dir.setText(str(Path(path).resolve()))

    def _browse_claude_bin(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择 Claude 程序文件", self.claude_bin.text().strip() or os.getcwd())
        if path:
            self.claude_bin.setText(str(Path(path).resolve()))

    def _browse_opencode_bin(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择 OpenCode 程序文件", self.opencode_bin.text().strip() or os.getcwd())
        if path:
            self.opencode_bin.setText(str(Path(path).resolve()))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("RootWindow")
        self.setWindowTitle(APP_DISPLAY_NAME)
        self.resize(1560, 980)
        self.setMinimumSize(1320, 820)
        self._worker: ReviewWorker | None = None

        self.store = SettingsStore()
        self.settings = self.store.load()
        self.session_claude_auth_token = os.getenv("ANTHROPIC_AUTH_TOKEN") or os.getenv("ANTHROPIC_API_KEY", "")
        self.session_api_key = os.getenv("BID_REVIEW_OPENCODE_API_KEY") or os.getenv("OPENCODE_API_KEY", "")
        self.current_result: BatchReviewData | None = None
        self._automation_request: object | None = None
        self._automation_app = None

        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(22, 22, 22, 22)
        root.setSpacing(18)

        root.addWidget(self._build_nav())
        root.addWidget(self._build_content(), 1)

        self._apply_claude_sdk_env()
        self._apply_settings_to_pages()
        self._load_recent_result()
        self._set_current_page(0)

    def _build_nav(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("NavPanel")
        panel.setFixedWidth(260)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        brand = SurfaceFrame("hero")
        brand_layout = QVBoxLayout(brand)
        brand_layout.setContentsMargins(18, 18, 18, 18)
        brand_layout.setSpacing(10)
        icon_label = QLabel()
        icon_label.setPixmap(QIcon(str(_asset_path("brand_mark.svg"))).pixmap(72, 72))
        title = QLabel(APP_DISPLAY_NAME)
        title.setObjectName("SectionTitle")
        subtitle = QLabel("面向招投标业务的桌面审查工具")
        subtitle.setObjectName("MutedLabel")
        subtitle.setWordWrap(True)
        brand_layout.addWidget(icon_label)
        brand_layout.addWidget(title)
        brand_layout.addWidget(subtitle)
        layout.addWidget(brand)

        self.nav_buttons: list[QPushButton] = []
        for index, label in enumerate(["首页", "新建审查", "查看结果", "默认设置"]):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setProperty("nav", "true")
            button.clicked.connect(lambda checked=False, idx=index: self._set_current_page(idx))
            self.nav_buttons.append(button)
            layout.addWidget(button)

        layout.addStretch(1)
        footer = QLabel("沿用现有审查链路和导出结果")
        footer.setObjectName("MutedLabel")
        footer.setWordWrap(True)
        layout.addWidget(footer)
        return panel

    def _build_content(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        top_bar = QFrame()
        top_bar.setObjectName("TopBar")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(22, 16, 22, 16)
        top_layout.setSpacing(16)
        title_wrap = QVBoxLayout()
        title_wrap.setSpacing(4)
        self.page_title = QLabel("")
        self.page_title.setObjectName("PageTitle")
        self.title_wrap = title_wrap
        self.page_subtitle = QLabel("")
        self.page_subtitle.setObjectName("MutedLabel")
        self.page_subtitle.setWordWrap(True)
        title_wrap.addWidget(self.page_title)
        title_wrap.addWidget(self.page_subtitle)
        self.status_badge = QLabel("就绪")
        self.status_badge.setObjectName("Badge")
        top_layout.addLayout(title_wrap, 1)
        top_layout.addWidget(self.status_badge, 0, Qt.AlignTop)

        self.stack = QStackedWidget()
        self.home_page = HomePage()
        self.review_page = ReviewPage()
        self.results_page = ResultsPage()
        self.settings_page = SettingsPage()
        for page in [self.home_page, self.review_page, self.results_page, self.settings_page]:
            self.stack.addWidget(page)

        layout.addWidget(top_bar)
        layout.addWidget(self.stack, 1)

        self.home_page.new_review_requested.connect(lambda: self._set_current_page(1))
        self.home_page.open_recent_requested.connect(self._open_recent_result)
        self.review_page.run_button.clicked.connect(self._start_review)
        self.settings_page.save_requested.connect(self._save_settings)
        return container

    def _apply_settings_to_pages(self) -> None:
        self.review_page.load_settings(self.settings)
        self.settings_page.load_settings(self.settings, self.session_api_key, self.session_claude_auth_token)

    def _apply_claude_sdk_env(self) -> None:
        env_mapping = {
            "ANTHROPIC_BASE_URL": self.settings.claude_sdk_base_url.strip(),
            "ANTHROPIC_MODEL": self.settings.model_for_backend("claude"),
            "ANTHROPIC_AUTH_TOKEN": self.session_claude_auth_token.strip(),
        }
        for key, value in env_mapping.items():
            if value:
                os.environ[key] = value
            else:
                os.environ.pop(key, None)
        if env_mapping["ANTHROPIC_AUTH_TOKEN"]:
            os.environ["ANTHROPIC_API_KEY"] = env_mapping["ANTHROPIC_AUTH_TOKEN"]
        else:
            os.environ.pop("ANTHROPIC_API_KEY", None)

    def _set_current_page(self, index: int) -> None:
        page_meta = {
            0: ("首页", "查看最近审查结果，快速进入新建审查。"),
            1: ("新建审查", "选择文件并确认参数后，直接启动现有审查流程。"),
            2: ("查看结果", ""),
            3: ("默认设置", "保存默认保存位置、审查引擎和高级连接参数。"),
        }
        title, subtitle = page_meta.get(index, (APP_DISPLAY_NAME, ""))
        self.stack.setCurrentIndex(index)
        self.page_title.setText(title)
        self.page_subtitle.setText(subtitle)
        self.page_subtitle.setVisible(bool(subtitle.strip()))
        self.title_wrap.setSpacing(4 if subtitle.strip() else 0)
        for idx, button in enumerate(self.nav_buttons):
            button.setChecked(idx == index)

    def _save_settings(self) -> None:
        self.settings = self.settings_page.snapshot(self.settings)
        self.session_api_key = self.settings_page.session_api_key()
        self.session_claude_auth_token = self.settings_page.session_claude_auth_token()
        self._apply_claude_sdk_env()
        try:
            self.store.save(self.settings)
        except Exception as exc:  # noqa: BLE001
            self.status_badge.setText("保存失败")
            QMessageBox.critical(self, "默认设置保存失败", str(exc))
            return
        self.review_page.load_settings(self.settings)
        self.status_badge.setText("默认设置已保存")
        QMessageBox.information(self, "默认设置已保存", "工作台默认设置已更新。")

    def _load_recent_result(self) -> None:
        batch_summary = Path(self.settings.last_batch_summary) if self.settings.last_batch_summary else None
        if batch_summary is None or not batch_summary.exists():
            batch_summary = find_latest_batch_summary(self.settings.default_output_dir)
        if batch_summary is None or not batch_summary.exists():
            self.home_page.set_recent(None)
            return
        try:
            self.current_result = load_batch_result(batch_summary)
        except Exception:
            self.home_page.set_recent(None)
            return
        self.home_page.set_recent(self.current_result)
        self.results_page.set_result(self.current_result)

    def _open_recent_result(self) -> None:
        if self.current_result is None:
            QMessageBox.information(self, "暂无结果", "还没有可查看的批量汇总结果。")
            return
        self.results_page.set_result(self.current_result)
        self._set_current_page(2)

    def _start_review(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            if self._automation_request is not None:
                self._finish_automation(False, "当前已有审查任务在执行。")
                return
            QMessageBox.information(self, "任务运行中", "当前已有审查任务在执行。")
            return
        try:
            request = self.review_page.build_request(self.settings, self.session_api_key)
            request.validate()
        except Exception as exc:  # noqa: BLE001
            if self._automation_request is not None:
                self._finish_automation(False, str(exc))
                return
            QMessageBox.warning(self, "无法启动", str(exc))
            return

        self.review_page.clear_progress()
        self.review_page.set_running(True)
        self.status_badge.setText("运行中")
        self._set_current_page(1)
        self._apply_claude_sdk_env()

        self._worker = ReviewWorker(request, self)
        self._worker.progress.connect(self._on_progress)
        self._worker.failed.connect(self._on_failed)
        self._worker.completed.connect(self._on_completed)
        self._worker.start()

    def _on_progress(self, message: str, level: str) -> None:
        self.review_page.append_progress(message, level)

    def _on_failed(self, message: str) -> None:
        self.review_page.set_running(False)
        self.review_page.result_value.setText("失败")
        self.status_badge.setText("失败")
        self.review_page.append_progress(f"[工作台] {message}", "basic")
        if self._automation_request is not None:
            self._finish_automation(False, message)
            self._worker = None
            return
        QMessageBox.critical(self, "审查失败", message)
        self._worker = None

    def _on_completed(self, result: object) -> None:
        self.review_page.set_running(False)
        self.review_page.result_value.setText("已完成")
        self.status_badge.setText("已完成")
        if isinstance(result, BatchReviewData):
            self.current_result = result
            self.results_page.set_result(result)
            self.home_page.set_recent(result)
            self.settings.last_batch_summary = str(result.batch_summary_path)
            self.settings.last_output_dir = str(result.output_dir)
            try:
                self.store.save(self.settings)
            except Exception as exc:  # noqa: BLE001
                self.review_page.append_progress(f"[工作台] 保存最近结果失败：{exc}", "basic")
            self._set_current_page(2)
        if self._automation_request is not None:
            self._finish_automation(True, "")
        self._worker = None

    def start_automation_review(self, automation_request: object, app: object) -> None:
        self._automation_request = automation_request
        self._automation_app = app
        request = automation_request
        self._set_current_page(1)
        self.review_page.tender_card.set_file(str(Path(request.tender_path).expanduser().resolve()))
        self.review_page.bid_card.set_paths(
            [str(Path(path).expanduser().resolve()) for path in request.bid_paths]
        )
        _set_combo_value(self.review_page.backend_combo, str(request.backend))
        if getattr(request, "model", ""):
            self.review_page.model_edit.setText(str(request.model).strip())
        self.review_page.output_dir_edit.setText(str(Path(request.output_dir).expanduser().resolve()))
        if getattr(request, "review_profile", ""):
            _set_combo_value(self.review_page.review_profile_combo, str(request.review_profile))
        if int(getattr(request, "timeout_sec", 0) or 0) > 0:
            self.review_page.timeout_spin.setValue(int(request.timeout_sec))
        self._start_review()

    def _finish_automation(self, success: bool, message: str) -> None:
        if self._automation_request is None or self._automation_app is None:
            return
        exit_code = 0 if success else 1
        screenshot_path = str(getattr(self._automation_request, "screenshot", "") or "").strip()
        if screenshot_path:
            target = Path(screenshot_path).expanduser().resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            self._automation_app.processEvents()
            self.repaint()
            self._automation_app.processEvents()
            saved = self.grab().save(str(target))
            if not saved or not target.exists():
                exit_code = 1
        if not success and message:
            self.review_page.append_progress(f"[工作台][automation] {message}", "basic")
        app = self._automation_app
        self._automation_request = None
        self._automation_app = None
        app.exit(exit_code)
