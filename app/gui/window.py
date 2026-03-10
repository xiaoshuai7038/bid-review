from __future__ import annotations

from pathlib import Path
import os

from PySide6.QtCore import QDateTime, Qt, Signal, QUrl
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
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QScrollArea,
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
from app.gui.state import DesktopSettings, SettingsStore, runtime_root


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


def _pin_form_field_height(widget: QWidget, min_height: int = 40) -> None:
    widget.setMinimumHeight(min_height)
    widget.setSizePolicy(widget.sizePolicy().horizontalPolicy(), QSizePolicy.Fixed)


def _configure_form_layout(form: QFormLayout) -> None:
    form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
    form.setRowWrapPolicy(QFormLayout.DontWrapRows)
    form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    form.setFormAlignment(Qt.AlignTop)
    form.setHorizontalSpacing(14)
    form.setVerticalSpacing(12)


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
        self.path_label = QLabel("拖入文件或点击浏览")
        self.path_label.setWordWrap(True)

        action_row = QHBoxLayout()
        self.browse_button = QPushButton("浏览文件")
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

    def dragEnterEvent(self, event) -> None:  # type: ignore[override]
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # type: ignore[override]
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if local and Path(local).is_file():
                self.set_file(local)
                break
        event.acceptProposedAction()

    def browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择文件")
        if path:
            self.set_file(path)

    def set_file(self, path: str) -> None:
        self._path = str(Path(path).expanduser().resolve())
        self.path_label.setText(self._path)
        self.hint_label.setText(_basename(self._path))

    def clear(self) -> None:
        self._path = ""
        self.path_label.setText("拖入文件或点击浏览")
        self.hint_label.setText(self._hint)

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
        self._refresh_count()

    def dragEnterEvent(self, event) -> None:  # type: ignore[override]
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # type: ignore[override]
        self.add_paths([url.toLocalFile() for url in event.mimeData().urls()])
        event.acceptProposedAction()

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
        badge = QLabel("Windows Desktop Review Suite")
        badge.setObjectName("Badge")
        title = QLabel("面向招投标审查链路的桌面工作台")
        title.setObjectName("HeroTitle")
        title.setWordWrap(True)
        desc = QLabel(
            "用桌面端承接现有 CLI 审查能力：拖入文件、配置后端、查看进度、回看报告，"
            "维持原有输出契约和批量审查路径。"
        )
        desc.setWordWrap(True)
        desc.setObjectName("MutedLabel")
        action_row = QHBoxLayout()
        self.new_button = QPushButton("新建审查任务")
        self.new_button.setProperty("kind", "primary")
        self.open_recent_button = QPushButton("打开最近结果")
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

        self.hero_cards = [StatCard("双后端"), StatCard("批量审查"), StatCard("报告出口")]
        self.hero_cards[0].set_value("Claude / OpenCode", "沿用现有后端切换")
        self.hero_cards[1].set_value("1 + N", "1 份招标文件 + 多份投标文件")
        self.hero_cards[2].set_value("JSON / MD / DOCX", "保留 batch_summary.json")
        for card in self.hero_cards:
            right.addWidget(card)
        right.addStretch(1)

        hero_layout.addLayout(left, 3)
        hero_layout.addLayout(right, 2)

        recent = SurfaceFrame("card")
        recent_layout = QVBoxLayout(recent)
        recent_layout.setContentsMargins(24, 20, 24, 20)
        recent_layout.setSpacing(10)
        recent_title = QLabel("最近一次运行")
        recent_title.setObjectName("SectionTitle")
        self.recent_path = QLabel("暂无可用运行记录")
        self.recent_path.setWordWrap(True)
        self.recent_meta = QLabel("完成一次审查后，这里会显示最新产物入口。")
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
            self.recent_meta.setText("完成一次审查后，这里会显示最新产物入口。")
            return
        self.recent_path.setText(str(result.batch_summary_path))
        self.recent_meta.setText(
            f"招标文件：{_basename(result.tender_path)} | 投标文件数：{len(result.runs)} | 最近运行目录：{result.output_dir}"
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

        left = QWidget()
        left.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(18)

        file_row = QHBoxLayout()
        file_row.setSpacing(18)
        self.tender_card = SingleFileDropCard("招标文件", "仅 1 份，用于建立硬性要求与评审基线")
        self.bid_card = MultiFileDropCard("投标文件", "支持 1..N 份投标文件批量审查")
        file_row.addWidget(self.tender_card, 1)
        file_row.addWidget(self.bid_card, 1)

        config_card = SurfaceFrame("card")
        config_layout = QVBoxLayout(config_card)
        config_layout.setContentsMargins(24, 20, 24, 20)
        config_layout.setSpacing(16)
        config_title = QLabel("审查配置")
        config_title.setObjectName("SectionTitle")

        self.backend_combo = QComboBox()
        self.backend_combo.addItems(["claude", "opencode"])
        self.model_edit = QLineEdit()
        self.model_edit.setPlaceholderText("可选，覆盖默认模型")
        self.progress_combo = QComboBox()
        self.progress_combo.addItems(["agent", "basic", "normal", "detailed", "events", "raw"])
        self.output_dir_edit = QLineEdit()
        self.output_dir_button = QPushButton("浏览")
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(60, 7200)
        self.timeout_spin.setSingleStep(60)
        self.effort_combo = QComboBox()
        self.effort_combo.addItems(["low", "medium", "high"])
        self.save_raw_checkbox = QCheckBox("保存原始输出（claude_raw_output.txt）")
        self.save_raw_checkbox.setChecked(True)

        form = QFormLayout()
        _configure_form_layout(form)

        _pin_form_field_height(self.backend_combo)
        _pin_form_field_height(self.model_edit)
        _pin_form_field_height(self.progress_combo)
        _pin_form_field_height(self.output_dir_edit)
        _pin_form_field_height(self.timeout_spin)
        _pin_form_field_height(self.effort_combo)
        self.output_dir_button.setMinimumHeight(40)
        self.output_dir_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        form.addRow("后端", self.backend_combo)
        form.addRow("模型", self.model_edit)
        form.addRow("进度级别", self.progress_combo)

        output_row = QHBoxLayout()
        output_row.setContentsMargins(0, 0, 0, 0)
        output_row.setSpacing(8)
        output_row.addWidget(self.output_dir_edit, 1)
        output_row.addWidget(self.output_dir_button)
        output_wrap = QWidget()
        output_wrap.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        output_wrap.setMinimumHeight(40)
        output_wrap.setLayout(output_row)
        form.addRow("输出目录", output_wrap)
        form.addRow("超时（秒）", self.timeout_spin)
        form.addRow("Claude effort", self.effort_combo)

        config_layout.addWidget(config_title)
        config_layout.addLayout(form)
        config_layout.addWidget(self.save_raw_checkbox)

        instruction_card = SurfaceFrame("card")
        instruction_layout = QVBoxLayout(instruction_card)
        instruction_layout.setContentsMargins(24, 20, 24, 20)
        instruction_layout.setSpacing(12)
        instruction_title = QLabel("任务补充说明")
        instruction_title.setObjectName("SectionTitle")
        instruction_note = QLabel("这里传入的是现有 CLI 的 `--instruction` 与 `--user-instruction`。")
        instruction_note.setObjectName("MutedLabel")
        self.instruction_edit = QPlainTextEdit()
        self.instruction_edit.setMinimumHeight(78)
        self.instruction_edit.setPlaceholderText("附加任务指令")
        self.user_instruction_edit = QPlainTextEdit()
        self.user_instruction_edit.setMinimumHeight(78)
        self.user_instruction_edit.setPlaceholderText("用户个人指令")
        instruction_layout.addWidget(instruction_title)
        instruction_layout.addWidget(instruction_note)
        instruction_layout.addWidget(self.instruction_edit)
        instruction_layout.addWidget(self.user_instruction_edit)

        action_card = SurfaceFrame("card")
        action_layout = QVBoxLayout(action_card)
        action_layout.setContentsMargins(24, 20, 24, 20)
        action_layout.setSpacing(12)
        self.command_hint = QLabel("GUI 直接复用 `run_pipeline`，不会替换现有 CLI 链路。")
        self.command_hint.setObjectName("MutedLabel")
        action_row = QHBoxLayout()
        self.run_button = QPushButton("开始审查")
        self.run_button.setProperty("kind", "primary")
        self.open_output_button = QPushButton("打开输出目录")
        self.open_output_button.setProperty("kind", "ghost")
        action_row.addWidget(self.run_button)
        action_row.addWidget(self.open_output_button)
        action_row.addStretch(1)
        action_layout.addWidget(self.command_hint)
        action_layout.addLayout(action_row)

        left_layout.addLayout(file_row)
        left_layout.addWidget(config_card)
        left_layout.addWidget(instruction_card)
        left_layout.addWidget(action_card)
        left_layout.addStretch(1)

        self.left_scroll = QScrollArea()
        self.left_scroll.setWidgetResizable(True)
        self.left_scroll.setFrameShape(QFrame.NoFrame)
        self.left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.left_scroll.setWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(18)

        status_card = SurfaceFrame("card")
        status_layout = QGridLayout(status_card)
        status_layout.setContentsMargins(24, 20, 24, 20)
        status_layout.setHorizontalSpacing(18)
        status_layout.setVerticalSpacing(10)
        status_title = QLabel("运行状态")
        status_title.setObjectName("SectionTitle")
        self.stage_value = QLabel("等待启动")
        self.current_bid_value = QLabel("未开始")
        self.result_value = QLabel("就绪")
        self.stage_value.setWordWrap(True)
        self.current_bid_value.setWordWrap(True)
        self.result_value.setWordWrap(True)
        status_layout.addWidget(status_title, 0, 0, 1, 2)
        status_layout.addWidget(QLabel("当前阶段"), 1, 0)
        status_layout.addWidget(self.stage_value, 1, 1)
        status_layout.addWidget(QLabel("当前投标"), 2, 0)
        status_layout.addWidget(self.current_bid_value, 2, 1)
        status_layout.addWidget(QLabel("任务状态"), 3, 0)
        status_layout.addWidget(self.result_value, 3, 1)

        timeline_card = SurfaceFrame("card")
        timeline_layout = QVBoxLayout(timeline_card)
        timeline_layout.setContentsMargins(24, 20, 24, 20)
        timeline_layout.setSpacing(12)
        timeline_title = QLabel("进度时间线")
        timeline_title.setObjectName("SectionTitle")
        self.timeline_list = QListWidget()
        timeline_layout.addWidget(timeline_title)
        timeline_layout.addWidget(self.timeline_list, 1)

        log_card = SurfaceFrame("card")
        log_layout = QVBoxLayout(log_card)
        log_layout.setContentsMargins(24, 20, 24, 20)
        log_layout.setSpacing(12)
        log_title = QLabel("运行日志")
        log_title.setObjectName("SectionTitle")
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.document().setMaximumBlockCount(3000)
        log_layout.addWidget(log_title)
        log_layout.addWidget(self.log_view, 1)

        right_layout.addWidget(status_card)
        right_layout.addWidget(timeline_card, 1)
        right_layout.addWidget(log_card, 2)

        splitter.addWidget(self.left_scroll)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 4)
        splitter.setSizes([900, 700])

        root.addWidget(splitter, 1)

        self.output_dir_button.clicked.connect(self._browse_output_dir)
        self.open_output_button.clicked.connect(self._open_output_dir)
        self.backend_combo.currentTextChanged.connect(self._on_backend_changed)

    def load_settings(self, settings: DesktopSettings) -> None:
        self._backend_model_defaults = {
            "claude": settings.model_for_backend("claude"),
            "opencode": settings.model_for_backend("opencode"),
        }
        backend = settings.default_backend or "claude"
        self._last_model_backend = backend
        self.backend_combo.blockSignals(True)
        self.backend_combo.setCurrentText(backend)
        self.backend_combo.blockSignals(False)
        self.model_edit.setText(self._backend_model_defaults.get(backend, ""))
        self._update_model_placeholder(backend)
        self.progress_combo.setCurrentText(settings.default_progress_level or "agent")
        self.output_dir_edit.setText(settings.default_output_dir)
        self.timeout_spin.setValue(settings.default_timeout_sec or 1800)
        self.effort_combo.setCurrentText(settings.default_effort or "low")
        self.instruction_edit.setPlainText(settings.default_instruction)
        self.user_instruction_edit.setPlainText(settings.default_user_instruction)

    def build_request(self, settings: DesktopSettings, session_api_key: str = "") -> ReviewRunRequest:
        return ReviewRunRequest(
            tender_path=self.tender_card.file_path(),
            bid_paths=self.bid_card.paths(),
            backend=self.backend_combo.currentText().strip(),
            output_dir=self.output_dir_edit.text().strip(),
            model=self.model_edit.text().strip(),
            claude_bin=settings.claude_bin.strip(),
            opencode_bin=settings.opencode_bin.strip(),
            opencode_provider=settings.opencode_provider.strip() or "volcengine",
            opencode_api_url=settings.opencode_api_url.strip(),
            opencode_api_key=session_api_key.strip(),
            progress_level=self.progress_combo.currentText().strip(),
            timeout_sec=self.timeout_spin.value(),
            effort=self.effort_combo.currentText().strip(),
            instruction=self.instruction_edit.toPlainText().strip(),
            user_instruction=self.user_instruction_edit.toPlainText().strip(),
            save_raw_output=self.save_raw_checkbox.isChecked(),
        )

    def clear_progress(self) -> None:
        self.log_view.clear()
        self.timeline_list.clear()
        self.stage_value.setText("等待启动")
        self.current_bid_value.setText("未开始")
        self.result_value.setText("就绪")

    def append_progress(self, message: str, level: str) -> None:
        timestamp = QDateTime.currentDateTime().toString("HH:mm:ss")
        self.log_view.appendPlainText(f"[{timestamp}] {message}")
        if message.startswith("[pipeline]") or message.startswith("[agent]") or level in {"basic", "agent"}:
            self.timeline_list.addItem(f"{timestamp}  {message}")
            self.timeline_list.scrollToBottom()
        self._update_status(message)

    def set_running(self, running: bool) -> None:
        self.run_button.setEnabled(not running)
        self.run_button.setText("审查进行中..." if running else "开始审查")
        self.result_value.setText("运行中" if running else self.result_value.text())

    def _update_status(self, message: str) -> None:
        if "自动识别招标/投标文件角色" in message:
            self.stage_value.setText("正在识别文件角色")
        elif "角色识别完成" in message:
            self.stage_value.setText("角色识别完成")
        elif "开始审查" in message:
            self.stage_value.setText("正在执行逐份审查")
            self.current_bid_value.setText(message.split(":", 1)[-1].strip())
            self.result_value.setText("运行中")
        elif "完成审查" in message:
            self.stage_value.setText("已生成本轮报告")
        elif "会话已建立" in message:
            self.stage_value.setText("后端会话已建立")
        elif message.startswith("[agent]"):
            self.stage_value.setText(message.replace("[agent]", "", 1).strip())

    def _browse_output_dir(self) -> None:
        current = self.output_dir_edit.text().strip() or os.getcwd()
        path = QFileDialog.getExistingDirectory(self, "选择输出目录", current)
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
            self.model_edit.setPlaceholderText("可选，覆盖 OpenCode 默认模型")
            return
        self.model_edit.setPlaceholderText("可选，覆盖 Claude SDK 默认模型")


class ResultsPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._result: BatchReviewData | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        meta = SurfaceFrame("card")
        meta_layout = QVBoxLayout(meta)
        meta_layout.setContentsMargins(24, 20, 24, 20)
        meta_layout.setSpacing(8)
        meta_title = QLabel("当前结果集")
        meta_title.setObjectName("SectionTitle")
        self.tender_label = QLabel("尚未加载结果")
        self.tender_label.setWordWrap(True)
        self.role_label = QLabel("")
        self.role_label.setObjectName("MutedLabel")
        meta_layout.addWidget(meta_title)
        meta_layout.addWidget(self.tender_label)
        meta_layout.addWidget(self.role_label)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(18)
        self.requirement_card = StatCard("硬性要求")
        self.non_compliant_card = StatCard("不符合项")
        self.risk_card = StatCard("风险项")
        self.manual_card = StatCard("需人工复核")
        for card in [self.requirement_card, self.non_compliant_card, self.risk_card, self.manual_card]:
            stats_row.addWidget(card)

        control = SurfaceFrame("card")
        control_layout = QHBoxLayout(control)
        control_layout.setContentsMargins(24, 20, 24, 20)
        control_layout.setSpacing(12)
        self.run_combo = QComboBox()
        self.run_combo.setMinimumWidth(360)
        self.open_output_button = QPushButton("打开输出目录")
        self.open_json_button = QPushButton("打开 JSON")
        self.open_md_button = QPushButton("打开 Markdown")
        self.open_docx_button = QPushButton("打开 DOCX")
        self.open_batch_button = QPushButton("打开 batch_summary")
        for button in [
            self.open_output_button,
            self.open_json_button,
            self.open_md_button,
            self.open_docx_button,
            self.open_batch_button,
        ]:
            button.setProperty("kind", "ghost")
        control_layout.addWidget(QLabel("投标结果"))
        control_layout.addWidget(self.run_combo)
        control_layout.addStretch(1)
        control_layout.addWidget(self.open_output_button)
        control_layout.addWidget(self.open_json_button)
        control_layout.addWidget(self.open_md_button)
        control_layout.addWidget(self.open_docx_button)
        control_layout.addWidget(self.open_batch_button)

        table_card = SurfaceFrame("card")
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(24, 20, 24, 20)
        table_layout.setSpacing(12)
        table_title = QLabel("发现项明细")
        table_title.setObjectName("SectionTitle")
        self.findings_table = QTableWidget(0, 7)
        self.findings_table.setHorizontalHeaderLabels(
            ["ID", "条款ID", "结论", "问题", "招标证据", "投标证据", "建议"]
        )
        self.findings_table.setAlternatingRowColors(True)
        self.findings_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.findings_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        header = self.findings_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        for index in [3, 4, 5, 6]:
            header.setSectionResizeMode(index, QHeaderView.Stretch)
        table_layout.addWidget(table_title)
        table_layout.addWidget(self.findings_table, 1)

        layout.addWidget(meta)
        layout.addLayout(stats_row)
        layout.addWidget(control)
        layout.addWidget(table_card, 1)

        self.run_combo.currentIndexChanged.connect(self._show_run)
        self.open_output_button.clicked.connect(self._open_output)
        self.open_json_button.clicked.connect(self._open_json)
        self.open_md_button.clicked.connect(self._open_md)
        self.open_docx_button.clicked.connect(self._open_docx)
        self.open_batch_button.clicked.connect(self._open_batch)

    def set_result(self, result: BatchReviewData | None) -> None:
        self._result = result
        self.run_combo.blockSignals(True)
        self.run_combo.clear()
        self.findings_table.setRowCount(0)
        if result is None or not result.runs:
            self.tender_label.setText("尚未加载结果")
            self.role_label.setText("")
            self.run_combo.blockSignals(False)
            return
        self.tender_label.setText(f"招标文件：{result.tender_path}")
        self.role_label.setText(
            f"角色识别：{result.role_reasoning or 'manual'} | 运行目录：{result.output_dir}"
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
        self.requirement_card.set_value(str(summary.get("requirement_count", 0)), _basename(run.bid_path))
        self.non_compliant_card.set_value(str(summary.get("non_compliant_count", 0)), "需整改")
        self.risk_card.set_value(str(summary.get("risk_count", 0)), "需关注")
        self.manual_card.set_value(str(summary.get("needs_manual_count", 0)), "待人工确认")

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
                if col_index == 2:
                    status = str(finding.get("status", ""))
                    if status == "non_compliant":
                        item.setForeground(QColor("#EC7B87"))
                    elif status == "risk":
                        item.setForeground(QColor("#E3B16A"))
                    elif status == "needs_manual":
                        item.setForeground(QColor("#7EB8E8"))
                self.findings_table.setItem(row_index, col_index, item)
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
        toolchain_title = QLabel("工具链与默认行为")
        toolchain_title.setObjectName("SectionTitle")

        self.default_backend = QComboBox()
        self.default_backend.addItems(["claude", "opencode"])
        self.default_progress = QComboBox()
        self.default_progress.addItems(["agent", "basic", "normal", "detailed", "events", "raw"])
        self.default_timeout = QSpinBox()
        self.default_timeout.setRange(60, 7200)
        self.default_timeout.setSingleStep(60)
        self.output_dir = QLineEdit()
        self.common_output_dir_row = self._path_row(self.output_dir, self._browse_output_dir)

        self.claude_default_model = QLineEdit()
        self.claude_default_model.setPlaceholderText("Claude SDK 默认读取 ANTHROPIC_MODEL")
        self.default_effort = QComboBox()
        self.default_effort.addItems(["low", "medium", "high"])
        self.claude_sdk_base_url = QLineEdit()
        self.claude_sdk_base_url.setPlaceholderText("https://ark.cn-beijing.volces.com/api/coding")
        self.claude_sdk_auth_token = QLineEdit()
        self.claude_sdk_auth_token.setEchoMode(QLineEdit.Password)
        self.claude_sdk_auth_token.setPlaceholderText("仅当前窗口会话使用，不写入 settings.json")
        self.claude_bin = QLineEdit()

        self.opencode_default_model = QLineEdit()
        self.opencode_default_model.setPlaceholderText("OpenCode 默认模型")
        self.opencode_bin = QLineEdit()
        self.opencode_provider = QLineEdit()
        self.opencode_api_url = QLineEdit()
        self.opencode_api_key = QLineEdit()
        self.opencode_api_key.setEchoMode(QLineEdit.Password)
        self.opencode_api_key.setPlaceholderText("仅当前窗口会话使用，不写入 settings.json")

        common_form = QFormLayout()
        _configure_form_layout(common_form)
        _pin_form_field_height(self.default_backend)
        _pin_form_field_height(self.default_progress)
        _pin_form_field_height(self.default_timeout)
        _pin_form_field_height(self.output_dir)
        common_title = QLabel("通用默认项")
        common_title.setObjectName("SectionTitle")
        common_form.addRow("默认后端", self.default_backend)
        common_form.addRow("默认进度级别", self.default_progress)
        common_form.addRow("默认超时（秒）", self.default_timeout)
        common_form.addRow("默认输出目录", self.common_output_dir_row)

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
        _pin_form_field_height(self.claude_sdk_base_url)
        _pin_form_field_height(self.claude_sdk_auth_token)
        _pin_form_field_height(self.claude_bin)
        claude_form.addRow("Claude 模型", self.claude_default_model)
        claude_form.addRow("Claude SDK base-url", self.claude_sdk_base_url)
        claude_form.addRow("Claude SDK auth-token", self.claude_sdk_auth_token)
        claude_form.addRow("默认 Claude effort", self.default_effort)
        claude_layout.addLayout(claude_form)

        self.claude_advanced_toggle = QPushButton("高级可选")
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
        claude_advanced_form.addRow("Claude CLI 路径", self._path_row(self.claude_bin, self._browse_claude_bin))
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
        opencode_form.addRow("OpenCode 模型", self.opencode_default_model)
        opencode_form.addRow("OpenCode 路径", self._path_row(self.opencode_bin, self._browse_opencode_bin))
        opencode_form.addRow("OpenCode provider", self.opencode_provider)
        opencode_form.addRow("OpenCode api-url", self.opencode_api_url)
        opencode_form.addRow("OpenCode api-key", self.opencode_api_key)
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

        instruction_card = SurfaceFrame("card")
        instruction_layout = QVBoxLayout(instruction_card)
        instruction_layout.setContentsMargins(24, 20, 24, 20)
        instruction_layout.setSpacing(12)
        instruction_title = QLabel("默认补充指令")
        instruction_title.setObjectName("SectionTitle")
        self.default_instruction = QPlainTextEdit()
        self.default_instruction.setMinimumHeight(120)
        self.default_instruction.setPlaceholderText("默认 --instruction")
        self.default_user_instruction = QPlainTextEdit()
        self.default_user_instruction.setMinimumHeight(120)
        self.default_user_instruction.setPlaceholderText("默认 --user-instruction")
        instruction_layout.addWidget(instruction_title)
        instruction_layout.addWidget(self.default_instruction)
        instruction_layout.addWidget(self.default_user_instruction)

        action_row = QHBoxLayout()
        self.save_button = QPushButton("保存设置")
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
        self.default_backend.currentTextChanged.connect(self._apply_backend_mode)
        self.claude_advanced_toggle.toggled.connect(self._toggle_claude_advanced)

    def load_settings(
        self,
        settings: DesktopSettings,
        session_api_key: str = "",
        session_claude_auth_token: str = "",
    ) -> None:
        backend = settings.default_backend or "claude"
        self.default_backend.blockSignals(True)
        self.default_backend.setCurrentText(backend)
        self.default_backend.blockSignals(False)
        self.claude_default_model.setText(settings.model_for_backend("claude"))
        self.opencode_default_model.setText(settings.model_for_backend("opencode"))
        self.claude_sdk_base_url.setText(settings.claude_sdk_base_url)
        self.claude_sdk_auth_token.setText(session_claude_auth_token)
        self.default_progress.setCurrentText(settings.default_progress_level or "agent")
        self.default_timeout.setValue(settings.default_timeout_sec or 1800)
        self.default_effort.setCurrentText(settings.default_effort or "low")
        self.output_dir.setText(settings.default_output_dir)
        self.claude_bin.setText(settings.claude_bin)
        self.opencode_bin.setText(settings.opencode_bin)
        self.opencode_provider.setText(settings.opencode_provider or "volcengine")
        self.opencode_api_url.setText(settings.opencode_api_url)
        self.opencode_api_key.setText(session_api_key)
        self.default_instruction.setPlainText(settings.default_instruction)
        self.default_user_instruction.setPlainText(settings.default_user_instruction)
        self._apply_backend_mode(backend)

    def snapshot(self, previous: DesktopSettings) -> DesktopSettings:
        backend = self.default_backend.currentText().strip()
        claude_model = self.claude_default_model.text().strip()
        opencode_model = self.opencode_default_model.text().strip()
        return DesktopSettings(
            default_backend=backend,
            default_output_dir=self.output_dir.text().strip(),
            default_model=claude_model if backend == "claude" else opencode_model,
            claude_default_model=claude_model,
            opencode_default_model=opencode_model,
            default_progress_level=self.default_progress.currentText().strip(),
            default_timeout_sec=self.default_timeout.value(),
            default_effort=self.default_effort.currentText().strip(),
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
            self.backend_section_title.setText("OpenCode 默认配置")
            self.backend_stack.setCurrentIndex(1)
            self.guidance.setText("OpenCode provider 与 api-url 会保存到本地设置；api-key 只保留在当前窗口内存。")
            return

        self.backend_section_title.setText("Claude 默认配置")
        self.backend_stack.setCurrentIndex(0)
        self.guidance.setText("Claude SDK base-url 会保存到本地设置；Claude auth-token 只保留在当前窗口内存。")

    def _toggle_claude_advanced(self, checked: bool) -> None:
        self.claude_advanced_panel.setVisible(bool(checked))

    def _path_row(self, line_edit: QLineEdit, browse_callback) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        button = QPushButton("浏览")
        button.setMinimumHeight(40)
        button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        button.clicked.connect(browse_callback)
        layout.addWidget(line_edit, 1)
        layout.addWidget(button)
        row.setMinimumHeight(40)
        row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        return row

    def _browse_output_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择输出目录", self.output_dir.text().strip() or os.getcwd())
        if path:
            self.output_dir.setText(str(Path(path).resolve()))

    def _browse_claude_bin(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择 Claude 可执行文件", self.claude_bin.text().strip() or os.getcwd())
        if path:
            self.claude_bin.setText(str(Path(path).resolve()))

    def _browse_opencode_bin(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择 OpenCode 可执行文件", self.opencode_bin.text().strip() or os.getcwd())
        if path:
            self.opencode_bin.setText(str(Path(path).resolve()))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("RootWindow")
        self.setWindowTitle("Bid Review Desktop")
        self.resize(1560, 980)
        self.setMinimumSize(1320, 820)
        self._worker: ReviewWorker | None = None

        self.store = SettingsStore()
        self.settings = self.store.load()
        self.session_claude_auth_token = os.getenv("ANTHROPIC_AUTH_TOKEN") or os.getenv("ANTHROPIC_API_KEY", "")
        self.session_api_key = os.getenv("BID_REVIEW_OPENCODE_API_KEY") or os.getenv("OPENCODE_API_KEY", "")
        self.current_result: BatchReviewData | None = None

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
        title = QLabel("Bid Review Desktop")
        title.setObjectName("SectionTitle")
        subtitle = QLabel("Windows 质感的桌面审查工作台")
        subtitle.setObjectName("MutedLabel")
        subtitle.setWordWrap(True)
        brand_layout.addWidget(icon_label)
        brand_layout.addWidget(title)
        brand_layout.addWidget(subtitle)
        layout.addWidget(brand)

        self.nav_buttons: list[QPushButton] = []
        for index, label in enumerate(["首页", "新建审查", "结果查看", "设置"]):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setProperty("nav", "true")
            button.clicked.connect(lambda checked=False, idx=index: self._set_current_page(idx))
            self.nav_buttons.append(button)
            layout.addWidget(button)

        layout.addStretch(1)
        footer = QLabel("保留现有 CLI 链路与输出契约")
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
            0: ("首页", "查看最近运行、快速进入新建审查任务。"),
            1: ("新建审查任务", "配置招标文件、投标文件和后端参数，直接启动现有审查管线。"),
            2: ("结果查看", "基于现有导出文件加载 summary、findings 与产物入口。"),
            3: ("设置", "保存默认输出路径、后端路径和 OpenCode 高级参数。"),
        }
        title, subtitle = page_meta.get(index, ("Bid Review Desktop", ""))
        self.stack.setCurrentIndex(index)
        self.page_title.setText(title)
        self.page_subtitle.setText(subtitle)
        for idx, button in enumerate(self.nav_buttons):
            button.setChecked(idx == index)

    def _save_settings(self) -> None:
        self.settings = self.settings_page.snapshot(self.settings)
        self.session_api_key = self.settings_page.session_api_key()
        self.session_claude_auth_token = self.settings_page.session_claude_auth_token()
        self._apply_claude_sdk_env()
        self.store.save(self.settings)
        self.review_page.load_settings(self.settings)
        self.status_badge.setText("设置已保存")
        QMessageBox.information(self, "设置已保存", "桌面端默认配置已更新。")

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
            QMessageBox.information(self, "暂无结果", "还没有可用的 batch_summary.json。")
            return
        self.results_page.set_result(self.current_result)
        self._set_current_page(2)

    def _start_review(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(self, "任务运行中", "当前已有审查任务在执行。")
            return
        try:
            request = self.review_page.build_request(self.settings, self.session_api_key)
            request.validate()
        except Exception as exc:  # noqa: BLE001
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
        self.review_page.append_progress(f"[desktop] {message}", "basic")
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
            self.store.save(self.settings)
            self._set_current_page(2)
        self._worker = None
