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
