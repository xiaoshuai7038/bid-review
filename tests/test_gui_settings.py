from __future__ import annotations

from pathlib import Path

from app.gui.state.settings import DesktopSettings, SettingsStore


def test_settings_store_round_trip(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    store = SettingsStore(settings_path)
    settings = DesktopSettings(
        default_backend="opencode",
        default_output_dir=r"D:\output",
        default_model="DeepSeek-V3.2",
        default_progress_level="normal",
        default_timeout_sec=2400,
        default_effort="medium",
        default_instruction="附加任务",
        default_user_instruction="个人偏好",
        claude_bin=r"C:\tools\claude.cmd",
        opencode_bin=r"C:\tools\opencode.exe",
        opencode_provider="volcengine",
        opencode_api_url="https://example.invalid/v1",
        last_batch_summary=r"D:\output\run-1\batch_summary.json",
        last_output_dir=r"D:\output\run-1",
    )

    store.save(settings)
    loaded = store.load()

    assert loaded == settings

