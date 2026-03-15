from __future__ import annotations

import io
import pytest

from app import orchestrator


class _UnavailableClient:
    def available(self) -> bool:
        return False

    def unavailable_reason(self) -> str | None:
        return None


class _UnavailableClaudeClientWithReason(_UnavailableClient):
    def unavailable_reason(self) -> str | None:
        return "Claude Code on Windows requires git-bash."


class _UnavailableOpenCodeClientWithReason(_UnavailableClient):
    def unavailable_reason(self) -> str | None:
        return "未检测到仓库内 OpenCode runtime。请先执行 npm install。"


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
    with pytest.raises(RuntimeError, match="未检测到可用的 OpenCode SDK 运行时"):
        orchestrator.run_pipeline(backend="opencode", **_pipeline_kwargs(tmp_path))


def test_opencode_unavailable_error_uses_specific_reason(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(
        orchestrator,
        "create_llm_client",
        lambda **kwargs: ("opencode", _UnavailableOpenCodeClientWithReason()),
    )
    with pytest.raises(RuntimeError, match="npm install"):
        orchestrator.run_pipeline(backend="opencode", **_pipeline_kwargs(tmp_path))


def test_claude_unavailable_error_message_mentions_sdk(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(
        orchestrator,
        "create_llm_client",
        lambda **kwargs: ("claude", _UnavailableClient()),
    )
    with pytest.raises(RuntimeError, match="未检测到可用的 Claude SDK 运行时"):
        orchestrator.run_pipeline(**_pipeline_kwargs(tmp_path))


def test_claude_unavailable_error_uses_specific_reason(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(
        orchestrator,
        "create_llm_client",
        lambda **kwargs: ("claude", _UnavailableClaudeClientWithReason()),
    )
    with pytest.raises(RuntimeError, match="git-bash"):
        orchestrator.run_pipeline(**_pipeline_kwargs(tmp_path))


def test_emit_pipeline_message_tolerates_invalid_stderr_handle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[str, str]] = []

    class _BrokenStderr(io.TextIOBase):
        def write(self, s: str) -> int:  # noqa: ANN001
            raise OSError(22, "Invalid argument")

        def flush(self) -> None:
            raise OSError(22, "Invalid argument")

    monkeypatch.setattr(orchestrator.sys, "stderr", _BrokenStderr())

    orchestrator._emit_pipeline_message(
        "[pipeline] test message",
        progress_callback=lambda message, level: seen.append((message, level)),
        level="basic",
    )

    assert seen == [("[pipeline] test message", "basic")]

