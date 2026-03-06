from __future__ import annotations

import pytest

from app import orchestrator


class _UnavailableClient:
    def available(self) -> bool:
        return False


def _pipeline_kwargs(tmp_path) -> dict:
    return {
        "inputs": [],
        "output_root": str(tmp_path),
        "tender_path": "D:/docs/tender.pdf",
        "bid_paths": ["D:/docs/bid.docx"],
        "claude_bin": None,
        "model": None,
        "effort": "low",
        "show_progress": False,
        "progress_level": "basic",
        "timeout_sec": 30,
        "extra_instruction": "",
        "user_instruction": "",
        "mcp_config": None,
        "save_raw_output": False,
    }


def test_opencode_missing_binary_shows_clear_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(
        orchestrator,
        "create_llm_client",
        lambda **kwargs: ("opencode", _UnavailableClient()),
    )
    with pytest.raises(RuntimeError, match="未检测到可用的 opencode CLI"):
        orchestrator.run_pipeline(backend="opencode", **_pipeline_kwargs(tmp_path))


def test_claude_unavailable_error_message_unchanged(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(
        orchestrator,
        "create_llm_client",
        lambda **kwargs: ("claude", _UnavailableClient()),
    )
    with pytest.raises(RuntimeError, match="未检测到可用的 claude CLI，请先安装并登录。"):
        orchestrator.run_pipeline(**_pipeline_kwargs(tmp_path))

