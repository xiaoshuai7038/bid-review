from __future__ import annotations

import os
import json
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QSizePolicy

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.gui.app import create_application
from app.gui.services import BatchReviewData, ReviewRunData
from app.gui.window import FindingsTableDelegate, MainWindow, MultiFileDropCard, SingleFileDropCard


def _set_combo_to_value(combo, value: str) -> None:
    index = combo.findData(value)
    assert index >= 0
    combo.setCurrentIndex(index)


def _send_mouse_wheel(widget) -> None:
    center = widget.rect().center()
    event = QWheelEvent(
        QPointF(center),
        QPointF(widget.mapToGlobal(center)),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.NoButton,
        Qt.NoModifier,
        Qt.ScrollUpdate,
        False,
    )
    QApplication.sendEvent(widget, event)


def test_main_window_boots_with_saved_settings(tmp_path: Path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "default_backend": "claude",
                "default_output_dir": str(tmp_path / "output"),
                "default_progress_level": "agent",
                "default_timeout_sec": 1800,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BID_REVIEW_GUI_SETTINGS_PATH", str(settings_path))

    app = create_application([])
    window = MainWindow()

    assert app.applicationName() == "标书审查工作台"
    assert app.applicationDisplayName() == "标书审查工作台"
    assert window.windowTitle() == "标书审查工作台"
    assert window.review_page.output_dir_edit.text() == str(tmp_path / "output")
    window.close()
    app.quit()


def test_main_window_applies_claude_sdk_env_from_settings(tmp_path: Path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "default_backend": "claude",
                "default_output_dir": str(tmp_path / "output"),
                "claude_default_model": "ark-code-latest",
                "opencode_default_model": "DeepSeek-V3.2",
                "claude_sdk_base_url": "https://ark.cn-beijing.volces.com/api/coding",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BID_REVIEW_GUI_SETTINGS_PATH", str(settings_path))
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "token-from-env")

    app = create_application([])
    window = MainWindow()

    assert os.environ["ANTHROPIC_BASE_URL"] == "https://ark.cn-beijing.volces.com/api/coding"
    assert os.environ["ANTHROPIC_MODEL"] == "ark-code-latest"
    assert os.environ["ANTHROPIC_AUTH_TOKEN"] == "token-from-env"
    assert os.environ["ANTHROPIC_API_KEY"] == "token-from-env"
    assert window.settings_page.claude_sdk_base_url.text() == "https://ark.cn-beijing.volces.com/api/coding"
    assert window.settings_page.claude_sdk_auth_token.text() == "token-from-env"
    assert window.review_page.model_edit.text() == "ark-code-latest"

    window.close()
    app.quit()


def test_review_page_form_controls_keep_usable_height(tmp_path: Path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "default_backend": "claude",
                "default_output_dir": str(tmp_path / "output"),
                "claude_default_model": "ark-code-latest",
                "opencode_default_model": "DeepSeek-V3.2",
                "default_progress_level": "agent",
                "default_timeout_sec": 1800,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BID_REVIEW_GUI_SETTINGS_PATH", str(settings_path))

    app = create_application([])
    window = MainWindow()
    window.resize(1560, 980)
    window.show()
    window._set_current_page(1)
    app.processEvents()

    page = window.review_page
    assert page.run_button.isVisible()
    assert page.open_output_button.isVisible()
    assert page.run_button.isEnabled()
    assert page.backend_combo.height() >= 34
    assert page.backend_combo.currentText() == "Claude 引擎"
    assert page.backend_combo.currentData() == "claude"
    assert page.model_edit.height() >= 34
    assert page.model_edit.text() == "ark-code-latest"
    assert page.progress_combo.height() >= 34
    assert page.progress_combo.currentText() == "简洁（推荐）"
    assert page.progress_combo.currentData() == "agent"
    assert page.output_dir_edit.height() >= 34
    assert page.timeout_spin.height() >= 34
    assert page.effort_combo.height() >= 34
    assert page.effort_combo.currentText() == "快速"
    assert page.effort_combo.currentData() == "low"
    assert page.instruction_edit.height() < 160
    assert page.user_instruction_edit.height() < 160
    assert page.left_scroll.widget() is not None
    assert page.status_card.minimumHeight() == 176
    assert page.status_card.maximumHeight() == 176
    assert page.timeline_card.minimumHeight() >= 170
    assert page.log_card.minimumHeight() >= 220
    assert page.activity_splitter.count() == 2

    window.close()
    app.quit()


def test_settings_page_form_controls_keep_usable_height(tmp_path: Path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "default_backend": "claude",
                "default_output_dir": str(tmp_path / "output"),
                "claude_default_model": "ark-code-latest",
                "opencode_default_model": "DeepSeek-V3.2",
                "claude_sdk_base_url": "https://ark.cn-beijing.volces.com/api/coding",
                "default_progress_level": "agent",
                "default_timeout_sec": 1800,
                "opencode_provider": "volcengine",
                "opencode_api_url": "https://example.invalid/v1",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BID_REVIEW_GUI_SETTINGS_PATH", str(settings_path))

    app = create_application([])
    window = MainWindow()
    window.resize(1560, 980)
    window.show()
    window._set_current_page(3)
    app.processEvents()

    page = window.settings_page
    assert page.default_backend.height() >= 34
    assert page.default_backend.currentText() == "Claude 引擎"
    assert page.default_backend.currentData() == "claude"
    assert page.default_progress.currentText() == "简洁（推荐）"
    assert page.default_progress.currentData() == "agent"
    assert page.claude_default_model.height() >= 34
    assert page.opencode_default_model.height() >= 34
    assert page.claude_sdk_base_url.height() >= 34
    assert page.claude_sdk_auth_token.height() >= 34
    assert page.default_progress.height() >= 34
    assert page.default_timeout.height() >= 34
    assert page.default_effort.height() >= 34
    assert page.default_effort.currentText() == "快速"
    assert page.default_effort.currentData() == "low"
    assert page.output_dir.height() >= 34
    assert not page.claude_advanced_panel.isVisible()
    assert page.opencode_bin.height() >= 34
    assert page.opencode_provider.height() >= 34
    assert page.opencode_api_url.height() >= 34
    assert page.opencode_api_key.height() >= 34
    assert page.scroll.widget() is not None
    assert page.backend_stack.currentIndex() == 0

    page.claude_advanced_toggle.click()
    app.processEvents()
    assert page.claude_advanced_panel.isVisible()
    assert page.claude_bin.height() >= 34

    _set_combo_to_value(page.default_backend, "opencode")
    app.processEvents()
    assert page.backend_stack.currentIndex() == 1
    assert page.backend_section_title.text() == "OpenCode 默认设置"

    window.close()
    app.quit()


def test_config_dropdowns_ignore_mouse_wheel_changes(tmp_path: Path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "default_backend": "claude",
                "default_output_dir": str(tmp_path / "output"),
                "default_progress_level": "agent",
                "default_timeout_sec": 1800,
                "default_effort": "medium",
                "default_review_profile": "balanced",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BID_REVIEW_GUI_SETTINGS_PATH", str(settings_path))

    app = create_application([])
    window = MainWindow()
    window.show()
    window._set_current_page(1)
    app.processEvents()

    review_page = window.review_page

    review_backend_before = review_page.backend_combo.currentData()
    review_timeout_before = review_page.timeout_spin.value()

    review_page.backend_combo.setFocus()
    review_page.timeout_spin.setFocus()

    _send_mouse_wheel(review_page.backend_combo)
    _send_mouse_wheel(review_page.timeout_spin)
    app.processEvents()

    assert review_page.backend_combo.currentData() == review_backend_before
    assert review_page.timeout_spin.value() == review_timeout_before

    window._set_current_page(3)
    app.processEvents()

    settings_page = window.settings_page
    settings_progress_before = settings_page.default_progress.currentData()
    settings_timeout_before = settings_page.default_timeout.value()

    settings_page.default_progress.setFocus()
    settings_page.default_timeout.setFocus()

    _send_mouse_wheel(settings_page.default_progress)
    _send_mouse_wheel(settings_page.default_timeout)
    app.processEvents()

    assert settings_page.default_progress.currentData() == settings_progress_before
    assert settings_page.default_timeout.value() == settings_timeout_before

    window.close()
    app.quit()


def test_custom_timeout_from_saved_settings_stays_selectable(tmp_path: Path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "default_backend": "claude",
                "default_output_dir": str(tmp_path / "output"),
                "default_timeout_sec": 1020,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BID_REVIEW_GUI_SETTINGS_PATH", str(settings_path))

    app = create_application([])
    window = MainWindow()
    window.show()
    app.processEvents()

    assert window.review_page.timeout_spin.value() == 1020
    assert window.settings_page.default_timeout.value() == 1020
    assert window.review_page.timeout_spin.currentData() == 1020
    assert window.settings_page.default_timeout.currentData() == 1020

    window.close()
    app.quit()


def test_review_page_switches_default_model_with_backend(tmp_path: Path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "default_backend": "claude",
                "default_output_dir": str(tmp_path / "output"),
                "claude_default_model": "ark-code-latest",
                "opencode_default_model": "DeepSeek-V3.2",
                "default_progress_level": "agent",
                "default_timeout_sec": 1800,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BID_REVIEW_GUI_SETTINGS_PATH", str(settings_path))

    app = create_application([])
    window = MainWindow()
    window.show()
    window._set_current_page(1)
    app.processEvents()

    page = window.review_page
    assert page.backend_combo.currentText() == "Claude 引擎"
    assert page.backend_combo.currentData() == "claude"
    assert page.model_edit.text() == "ark-code-latest"
    _set_combo_to_value(page.backend_combo, "opencode")
    app.processEvents()
    assert page.backend_combo.currentText() == "OpenCode 引擎"
    assert page.backend_combo.currentData() == "opencode"
    assert page.model_edit.text() == "DeepSeek-V3.2"

    window.close()
    app.quit()


def test_progress_level_combo_uses_chinese_labels_but_keeps_internal_values(tmp_path: Path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "default_backend": "claude",
                "default_output_dir": str(tmp_path / "output"),
                "default_progress_level": "detailed",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BID_REVIEW_GUI_SETTINGS_PATH", str(settings_path))

    app = create_application([])
    window = MainWindow()
    window.show()
    window._set_current_page(1)
    app.processEvents()

    review_page = window.review_page
    settings_page = window.settings_page
    assert review_page.progress_combo.currentText() == "查看详细步骤"
    assert review_page.progress_combo.currentData() == "detailed"
    assert settings_page.default_progress.currentText() == "查看详细步骤"
    assert settings_page.default_progress.currentData() == "detailed"

    window.close()
    app.quit()


def test_effort_combo_uses_chinese_labels_but_keeps_internal_values(tmp_path: Path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "default_backend": "claude",
                "default_output_dir": str(tmp_path / "output"),
                "default_effort": "high",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BID_REVIEW_GUI_SETTINGS_PATH", str(settings_path))

    app = create_application([])
    window = MainWindow()
    window.show()
    window._set_current_page(1)
    app.processEvents()

    review_page = window.review_page
    settings_page = window.settings_page
    assert review_page.effort_combo.currentText() == "仔细"
    assert review_page.effort_combo.currentData() == "high"
    assert settings_page.default_effort.currentText() == "仔细"
    assert settings_page.default_effort.currentData() == "high"

    window.close()
    app.quit()


def test_review_page_instruction_editors_auto_grow_with_content(tmp_path: Path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "default_backend": "claude",
                "default_output_dir": str(tmp_path / "output"),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BID_REVIEW_GUI_SETTINGS_PATH", str(settings_path))

    app = create_application([])
    window = MainWindow()
    window.show()
    window._set_current_page(1)
    app.processEvents()

    page = window.review_page
    initial_height = page.instruction_edit.height()
    page.instruction_edit.setPlainText("\n".join([f"第{i}行说明" for i in range(1, 7)]))
    app.processEvents()
    grown_height = page.instruction_edit.height()

    assert initial_height < grown_height
    assert grown_height <= 220

    window.close()
    app.quit()


def test_review_page_long_agent_message_stays_compact_in_status_panel(tmp_path: Path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "default_backend": "claude",
                "default_output_dir": str(tmp_path / "output"),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BID_REVIEW_GUI_SETTINGS_PATH", str(settings_path))

    app = create_application([])
    window = MainWindow()
    window.resize(1560, 980)
    window.show()
    window._set_current_page(1)
    app.processEvents()

    page = window.review_page
    long_message = (
        "[agent] 当前阶段：提取硬性要求；下一步：继续核对投标文件中的模板字段、"
        "开标一览表、分项报价表、投标保证金交纳证明、基本账户开户证明和偏离表，"
        "并输出所有明确不符合项和需人工复核项。"
    )
    page.append_progress(long_message, "agent")
    app.processEvents()

    assert page.stage_value.height() <= 28
    assert page.stage_note_value.height() <= 24
    assert "下一步" in page.stage_note_value.text()
    assert page.stage_note_value.toolTip()

    window.close()
    app.quit()


def test_review_page_stage_result_list_is_collapsed_into_short_status_note(tmp_path: Path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "default_backend": "claude",
                "default_output_dir": str(tmp_path / "output"),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BID_REVIEW_GUI_SETTINGS_PATH", str(settings_path))

    app = create_application([])
    window = MainWindow()
    window.resize(1560, 980)
    window.show()
    window._set_current_page(1)
    app.processEvents()

    page = window.review_page
    long_stage_result = (
        "[审查引擎] 阶段成果：我需要至少16条，已经超过16条。"
        "现在开始按类别整理：1. 投标人资格；2. 营业执照；3. 项目负责人社保；"
        "4. 行贿记录；5. 黑名单限制；6. 不接受分包；7. 不允许联合体；"
        "8. 投标保证金；9. 财务要求；10. 业绩要求；11. 体系认证；"
        "12. 签字盖章；13. 开标一览表；14. 分项报价表；15. 偏离表；16. 质保期。"
    )
    page.append_progress(long_stage_result, "agent")
    app.processEvents()

    assert page.stage_note_value.height() <= 24
    assert page.stage_note_value.text() == "阶段成果已更新，详见下方详细记录。"
    assert page.stage_note_value.toolTip()
    assert "1. 投标人资格" in page.log_view.toPlainText()

    window.close()
    app.quit()


def test_results_page_uses_user_friendly_labels(tmp_path: Path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "default_backend": "claude",
                "default_output_dir": str(tmp_path / "output"),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BID_REVIEW_GUI_SETTINGS_PATH", str(settings_path))

    app = create_application([])
    window = MainWindow()
    window.show()
    window._set_current_page(2)
    app.processEvents()

    page = window.results_page
    assert window.page_title.text() == "查看结果"
    assert window.page_subtitle.isVisible() is False
    assert page.tender_label.text() == "尚未加载审查结果"
    assert page.open_output_button.text() == "打开结果目录"
    assert page.open_json_button.text() == "打开结构化结果"
    assert page.open_md_button.text() == "打开文本报告"
    assert page.open_docx_button.text() == "打开 Word 报告"
    assert page.open_batch_button.text() == "打开批量汇总"
    assert page.summary_card.isVisible()
    assert page.run_combo.maximumWidth() == 460
    assert isinstance(page.findings_table.itemDelegate(), FindingsTableDelegate)
    headers = [page.findings_table.horizontalHeaderItem(i).text() for i in range(page.findings_table.columnCount())]
    assert headers == ["编号", "条款编号", "结论", "问题说明", "招标依据", "投标依据", "处理建议"]

    window.close()
    app.quit()


def test_results_page_findings_table_reflows_rows_and_top_aligns_text(tmp_path: Path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "default_backend": "claude",
                "default_output_dir": str(tmp_path / "output"),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BID_REVIEW_GUI_SETTINGS_PATH", str(settings_path))

    report = {
        "summary": {
            "requirement_count": 2,
            "non_compliant_count": 1,
            "risk_count": 1,
            "needs_manual_count": 0,
        },
        "findings": [
            {
                "id": "F001",
                "requirement_id": "R003",
                "status": "non_compliant",
                "issue": "投标文件未提供项目负责人近一年本企业缴纳的社保证明。",
                "tender_evidence": "招标文件第10页 L31：项目负责人具有近一年本企业缴纳的社保证明。",
                "bid_evidence": "投标文件《项目实施团队人员配置》L4-L6：项目负责人-张春艳，社保证明未提供。",
                "recommendation": "立即补充项目负责人近一年社保证明。"
            },
            {
                "id": "F002",
                "requirement_id": "R004",
                "status": "risk",
                "issue": "投标文件未提供中国裁判文书网查询截图。该问题说明文本更长，用来触发行高重算。",
                "tender_evidence": "招标文件第10页 L32-L34：投标人及其法定代表人、主要负责人截至目前三年内无行贿行为记录的中国裁判文书网上查询结果截图。",
                "bid_evidence": "投标文件《关于行贿等黑名单行为的专项承诺函》L1-L4：仅作出承诺，未附查询结果截图。",
                "recommendation": "立即登录中国裁判文书网，查询并截取完整结果页面作为附件。"
            },
        ],
    }
    run = ReviewRunData(
        bid_path=str(tmp_path / "投标文件.docx"),
        output_dir=tmp_path,
        json_path=tmp_path / "review_report.json",
        markdown_path=tmp_path / "review_report.md",
        docx_path=tmp_path / "review_report.docx",
        raw_output_path=None,
        summary=report["summary"],
        report=report,
    )
    batch = BatchReviewData(
        tender_path=str(tmp_path / "招标文件.pdf"),
        role_reasoning="manual",
        output_dir=tmp_path,
        batch_summary_path=tmp_path / "batch_summary.json",
        runs=[run],
    )

    app = create_application([])
    window = MainWindow()
    window.resize(1600, 980)
    window.show()
    window.results_page.set_result(batch)
    window._set_current_page(2)
    app.processEvents()

    page = window.results_page
    first_height = page.findings_table.rowHeight(0)
    second_height = page.findings_table.rowHeight(1)
    assert first_height > 0
    assert second_height >= first_height
    assert page.findings_table.item(0, 3).textAlignment() & Qt.AlignTop
    assert page.findings_table.item(0, 4).textAlignment() & Qt.AlignTop
    wide_height = second_height

    window.resize(1240, 900)
    app.processEvents()
    app.processEvents()

    narrow_height = page.findings_table.rowHeight(1)
    assert narrow_height >= wide_height

    window.close()
    app.quit()


def test_single_file_drop_card_handles_windows_explorer_urls(tmp_path: Path) -> None:
    file_path = tmp_path / "招标文件.pdf"
    file_path.write_text("demo", encoding="utf-8")

    app = create_application([])
    card = SingleFileDropCard("招标文件", "hint")

    handled = card._handle_drop_urls([QUrl.fromLocalFile(str(file_path))])

    assert handled is True
    assert card.file_path() == str(file_path.resolve())
    assert card.acceptDrops() is True
    assert card.path_label.acceptDrops() is True
    assert card.browse_button.acceptDrops() is True
    card.close()
    app.quit()


def test_multi_file_drop_card_handles_windows_explorer_urls(tmp_path: Path) -> None:
    file_a = tmp_path / "投标文件1.docx"
    file_b = tmp_path / "投标文件2.docx"
    file_a.write_text("a", encoding="utf-8")
    file_b.write_text("b", encoding="utf-8")

    app = create_application([])
    card = MultiFileDropCard("投标文件", "hint")

    handled = card._handle_drop_urls(
        [
            QUrl.fromLocalFile(str(file_a)),
            QUrl.fromLocalFile(str(file_b)),
        ]
    )

    assert handled is True
    assert card.paths() == [str(file_a.resolve()), str(file_b.resolve())]
    assert card.acceptDrops() is True
    assert card.list_widget.acceptDrops() is True
    assert card.list_widget.viewport().acceptDrops() is True
    assert card.add_button.acceptDrops() is True
    card.close()
    app.quit()


def test_single_file_drop_card_long_filename_does_not_expose_full_text_inline(tmp_path: Path) -> None:
    long_name = (
        "内蒙古昆明卷烟有限责任公司2025年度卷包机组新增扫码功能部署实施（ZQ）项目"
        "2025年度卷包机组新增扫码功能部署实施（ZQ）项目.pdf"
    )
    file_path = tmp_path / long_name
    file_path.write_text("demo", encoding="utf-8")

    app = create_application([])
    card = SingleFileDropCard("招标文件", "hint")
    card.resize(360, 320)
    card.show()
    app.processEvents()

    card.set_file(str(file_path))
    app.processEvents()

    assert card.hint_label.toolTip() == long_name
    assert card.path_label.toolTip() == str(file_path.resolve())
    assert card.hint_label.wordWrap() is True
    assert card.path_label.wordWrap() is True
    assert card.hint_label.sizePolicy().horizontalPolicy() == QSizePolicy.Ignored
    assert card.path_label.sizePolicy().horizontalPolicy() == QSizePolicy.Ignored

    card.close()
    app.quit()


def test_review_page_routes_viewport_drop_to_target_cards(tmp_path: Path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "default_backend": "claude",
                "default_output_dir": str(tmp_path / "output"),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BID_REVIEW_GUI_SETTINGS_PATH", str(settings_path))

    app = create_application([])
    window = MainWindow()
    window.resize(1560, 980)
    window.show()
    window._set_current_page(1)
    app.processEvents()

    page = window.review_page
    viewport = page.left_scroll.viewport()
    tender_point = page.left_scroll.widget().mapTo(viewport, page.tender_card.geometry().center())
    bid_point = page.left_scroll.widget().mapTo(viewport, page.bid_card.geometry().center())

    assert page._drop_target_for_viewport_pos(tender_point) is page.tender_card
    assert page._drop_target_for_viewport_pos(bid_point) is page.bid_card

    window.close()
    app.quit()


def test_review_page_file_cards_stack_on_narrow_width_with_long_tender_name(tmp_path: Path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "default_backend": "claude",
                "default_output_dir": str(tmp_path / "output"),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BID_REVIEW_GUI_SETTINGS_PATH", str(settings_path))

    tender_name = (
        "内蒙古昆明卷烟有限责任公司2025年度卷包机组新增扫码功能部署实施（ZQ）项目"
        "2025年度卷包机组新增扫码功能部署实施（ZQ）项目.pdf"
    )
    tender_file = tmp_path / tender_name
    bid_file = tmp_path / "投标文件.docx"
    tender_file.write_text("tender", encoding="utf-8")
    bid_file.write_text("bid", encoding="utf-8")

    app = create_application([])
    window = MainWindow()
    window.resize(1180, 900)
    window.show()
    window._set_current_page(1)
    app.processEvents()

    page = window.review_page
    page.tender_card.set_file(str(tender_file))
    page.bid_card.add_paths([str(bid_file)])
    app.processEvents()

    content = page.left_scroll.widget()
    assert content is not None
    assert page._file_cards_stacked is True
    assert page.bid_card.geometry().top() > page.tender_card.geometry().bottom()
    assert abs(page.bid_card.geometry().left() - page.tender_card.geometry().left()) <= 1
    assert page.tender_card.geometry().right() <= content.rect().right()
    assert page.bid_card.geometry().right() <= content.rect().right()

    window.close()
    app.quit()


def test_review_page_file_cards_stay_two_column_on_wide_width_with_long_tender_name(tmp_path: Path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "default_backend": "claude",
                "default_output_dir": str(tmp_path / "output"),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BID_REVIEW_GUI_SETTINGS_PATH", str(settings_path))

    tender_name = (
        "内蒙古昆明卷烟有限责任公司2025年度卷包机组新增扫码功能部署实施（ZQ）项目"
        "2025年度卷包机组新增扫码功能部署实施（ZQ）项目.pdf"
    )
    tender_file = tmp_path / tender_name
    bid_file = tmp_path / "投标文件.docx"
    tender_file.write_text("tender", encoding="utf-8")
    bid_file.write_text("bid", encoding="utf-8")

    app = create_application([])
    window = MainWindow()
    window.resize(1560, 980)
    window.show()
    window._set_current_page(1)
    app.processEvents()

    page = window.review_page
    page.tender_card.set_file(str(tender_file))
    page.bid_card.add_paths([str(bid_file)])
    app.processEvents()

    assert page._file_cards_stacked is False
    assert page.bid_card.geometry().left() > page.tender_card.geometry().right()

    window.close()
    app.quit()


def test_review_page_handles_drop_on_viewport_for_tender_and_bid(tmp_path: Path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "default_backend": "claude",
                "default_output_dir": str(tmp_path / "output"),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    tender_file = tmp_path / "招标文件.pdf"
    bid_file = tmp_path / "投标文件.docx"
    tender_file.write_text("tender", encoding="utf-8")
    bid_file.write_text("bid", encoding="utf-8")
    monkeypatch.setenv("BID_REVIEW_GUI_SETTINGS_PATH", str(settings_path))

    app = create_application([])
    window = MainWindow()
    window.resize(1560, 980)
    window.show()
    window._set_current_page(1)
    app.processEvents()

    page = window.review_page
    viewport = page.left_scroll.viewport()
    tender_point = page.left_scroll.widget().mapTo(viewport, page.tender_card.geometry().center())
    bid_point = page.left_scroll.widget().mapTo(viewport, page.bid_card.geometry().center())

    assert page._handle_drop_on_viewport([QUrl.fromLocalFile(str(tender_file))], tender_point) is True
    assert page.tender_card.file_path() == str(tender_file.resolve())

    assert page._handle_drop_on_viewport([QUrl.fromLocalFile(str(bid_file))], bid_point) is True
    assert page.bid_card.paths() == [str(bid_file.resolve())]

    window.close()
    app.quit()


def test_main_window_start_automation_review_populates_form_and_starts(tmp_path: Path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "default_backend": "claude",
                "default_output_dir": str(tmp_path / "output"),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BID_REVIEW_GUI_SETTINGS_PATH", str(settings_path))

    tender_file = tmp_path / "招标文件.pdf"
    bid_file = tmp_path / "投标文件.docx"
    tender_file.write_text("tender", encoding="utf-8")
    bid_file.write_text("bid", encoding="utf-8")

    app = create_application([])
    window = MainWindow()
    window.show()
    app.processEvents()

    called: dict[str, bool] = {"started": False}
    monkeypatch.setattr(window, "_start_review", lambda: called.__setitem__("started", True))

    request = SimpleNamespace(
        backend="opencode",
        tender_path=str(tender_file),
        bid_paths=[str(bid_file)],
        output_dir=str(tmp_path / "review-output"),
        screenshot=str(tmp_path / "review.png"),
        model="DeepSeek-V3.2",
        review_profile="fast",
        timeout_sec=2400,
    )

    window.start_automation_review(request, app)
    app.processEvents()

    assert window.stack.currentIndex() == 1
    assert window.review_page.tender_card.file_path() == str(tender_file.resolve())
    assert window.review_page.bid_card.paths() == [str(bid_file.resolve())]
    assert window.review_page.backend_combo.currentData() == "opencode"
    assert window.review_page.model_edit.text() == "DeepSeek-V3.2"
    assert window.review_page.output_dir_edit.text() == str((tmp_path / "review-output").resolve())
    assert window.review_page.review_profile_combo.currentData() == "fast"
    assert window.review_page.timeout_spin.value() == 2400
    assert called["started"] is True

    window.close()
    app.quit()
