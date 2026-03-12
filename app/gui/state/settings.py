from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
from typing import Any

from PySide6.QtCore import QStandardPaths

from app.runtime_paths import (
    default_output_root,
    default_settings_path,
    ensure_runtime_root_writable,
    is_frozen,
    runtime_root as shared_runtime_root,
    runtime_root_status as shared_runtime_root_status,
    workspace_root as shared_workspace_root,
)


def runtime_root() -> Path:
    return shared_runtime_root()


def workspace_root() -> Path:
    return shared_workspace_root()


def runtime_root_status() -> dict[str, str | bool]:
    return shared_runtime_root_status()


def _default_output_dir() -> str:
    return str(default_output_root())


def _settings_path() -> Path:
    override = os.getenv("BID_REVIEW_GUI_SETTINGS_PATH")
    if override:
        return Path(override).expanduser().resolve()
    if is_frozen():
        return default_settings_path()
    base = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
    root = Path(base) if base else Path.home() / ".bid-review-desktop"
    return root / "settings.json"


@dataclass
class DesktopSettings:
    default_backend: str = "claude"
    default_output_dir: str = field(default_factory=_default_output_dir)
    # Legacy shared model field kept for backward compatibility with older settings files.
    default_model: str = ""
    claude_default_model: str = field(default_factory=lambda: os.getenv("ANTHROPIC_MODEL", ""))
    opencode_default_model: str = field(default_factory=lambda: os.getenv("BID_REVIEW_OPENCODE_MODEL", ""))
    default_progress_level: str = "agent"
    default_timeout_sec: int = 1800
    default_effort: str = "low"
    default_review_profile: str = "thorough"
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
        legacy_model = str(data.get("default_model", "") or "").strip()
        if legacy_model:
            payload.setdefault("claude_default_model", legacy_model)
            payload.setdefault("opencode_default_model", legacy_model)
        return cls(**payload)

    def model_for_backend(self, backend: str) -> str:
        normalized = (backend or "claude").strip().lower()
        if normalized == "opencode":
            return (self.opencode_default_model or self.default_model or "").strip()
        return (self.claude_default_model or self.default_model or "").strip()


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
        if is_frozen():
            ensure_runtime_root_writable()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2), encoding="utf-8")

