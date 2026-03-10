from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import sys
from typing import Any

from PySide6.QtCore import QStandardPaths


def runtime_root() -> Path:
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            return Path(meipass).resolve()
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]


def workspace_root() -> Path:
    override = os.getenv("BID_REVIEW_GUI_WORKSPACE")
    if override:
        return Path(override).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return runtime_root()


def _default_output_dir() -> str:
    if getattr(sys, "frozen", False):
        documents = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
        base = Path(documents or Path.home() / "Documents") / "BidReview" / "output"
        return str(base.resolve())
    return str((workspace_root() / "data" / "output").resolve())


def _settings_path() -> Path:
    override = os.getenv("BID_REVIEW_GUI_SETTINGS_PATH")
    if override:
        return Path(override).expanduser().resolve()
    base = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
    root = Path(base) if base else Path.home() / ".bid-review-desktop"
    return root / "settings.json"


@dataclass
class DesktopSettings:
    default_backend: str = "claude"
    default_output_dir: str = field(default_factory=_default_output_dir)
    default_model: str = field(default_factory=lambda: os.getenv("ANTHROPIC_MODEL", ""))
    default_progress_level: str = "agent"
    default_timeout_sec: int = 1800
    default_effort: str = "low"
    default_instruction: str = ""
    default_user_instruction: str = ""
    claude_sdk_base_url: str = field(default_factory=lambda: os.getenv("ANTHROPIC_BASE_URL", ""))
    claude_bin: str = field(default_factory=lambda: os.getenv("CLAUDE_BIN", ""))
    opencode_bin: str = field(default_factory=lambda: os.getenv("OPENCODE_BIN", ""))
    opencode_provider: str = field(default_factory=lambda: os.getenv("BID_REVIEW_OPENCODE_PROVIDER", "volcengine"))
    opencode_api_url: str = field(default_factory=lambda: os.getenv("BID_REVIEW_OPENCODE_API_URL", ""))
    last_batch_summary: str = ""
    last_output_dir: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DesktopSettings":
        known = {field.name for field in cls.__dataclass_fields__.values()}
        payload = {k: v for k, v in data.items() if k in known}
        return cls(**payload)


class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or _settings_path()

    def load(self) -> DesktopSettings:
        if not self.path.exists():
            return DesktopSettings()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return DesktopSettings()
        if not isinstance(raw, dict):
            return DesktopSettings()
        return DesktopSettings.from_dict(raw)

    def save(self, settings: DesktopSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2), encoding="utf-8")

