from __future__ import annotations

import os
import json
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.gui.app import create_application
from app.gui.window import MainWindow


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
    assert page.backend_combo.height() >= 34
    assert page.model_edit.height() >= 34
    assert page.model_edit.text() == "ark-code-latest"
    assert page.progress_combo.height() >= 34
    assert page.progress_combo.currentText() == "简洁（推荐）"
    assert page.progress_combo.currentData() == "agent"
    assert page.output_dir_edit.height() >= 34
    assert page.timeout_spin.height() >= 34
    assert page.effort_combo.height() >= 34
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
