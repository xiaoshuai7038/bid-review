from __future__ import annotations

import os
import json
from pathlib import Path

from PySide6.QtCore import QUrl

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.gui.app import create_application
from app.gui.window import MainWindow, MultiFileDropCard, SingleFileDropCard


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

    assert window.windowTitle() == "Bid Review Desktop"
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

    page.default_backend.setCurrentText("opencode")
    app.processEvents()
    assert page.backend_stack.currentIndex() == 1
    assert page.backend_section_title.text() == "OpenCode 默认配置"

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
    assert page.model_edit.text() == "ark-code-latest"
    page.backend_combo.setCurrentText("opencode")
    app.processEvents()
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
