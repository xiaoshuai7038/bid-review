from __future__ import annotations

import os
from typing import Any, Literal, Protocol, runtime_checkable

from app.llm.claude_client import ClaudeClient
from app.llm.opencode_client import OpenCodeClient

BackendName = Literal["claude", "opencode"]


@runtime_checkable
class LLMClient(Protocol):
    timeout_sec: int

    def ask_text(self, prompt: str, *, task_label: str | None = None) -> str: ...
    def ask_json(
        self,
        prompt: str,
        *,
        required_top_keys: list[str] | None = None,
        max_retries: int = 2,
        task_label: str | None = None,
    ) -> dict[str, Any] | list[Any]: ...
    def get_last_tool_calls(self) -> list[str]: ...
    def get_last_tool_uses(self) -> list[dict[str, Any]]: ...
    def available(self) -> bool: ...


def normalize_backend(backend: str | None) -> BackendName:
    raw = (backend or "claude").strip().lower()
    if raw not in {"claude", "opencode"}:
        raise ValueError(f"不支持的后端: {backend}（仅支持 claude/opencode）")
    return raw  # type: ignore[return-value]


def create_llm_client(
    *,
    backend: str | None,
    claude_bin: str | None,
    opencode_bin: str | None,
    model: str | None,
    opencode_model: str | None,
    effort: str,
    show_progress: bool,
    progress_level: str,
    timeout_sec: int,
    workspace: str | None,
    mcp_config: str | None,
    opencode_api_key: str | None,
    opencode_api_url: str | None,
    opencode_provider: str,
) -> tuple[BackendName, LLMClient]:
    selected = normalize_backend(backend)
    if selected == "claude":
        return selected, ClaudeClient(
            claude_bin=claude_bin,
            model=model,
            effort=effort,
            show_progress=show_progress,
            progress_level=progress_level,
            timeout_sec=timeout_sec,
            workspace=workspace,
            mcp_config=mcp_config,
        )

    resolved_model = opencode_model or model or os.getenv("BID_REVIEW_OPENCODE_MODEL")
    return selected, OpenCodeClient(
        opencode_bin=opencode_bin,
        model=resolved_model,
        show_progress=show_progress,
        progress_level=progress_level,
        timeout_sec=timeout_sec,
        workspace=workspace,
        mcp_config=mcp_config,
        api_key=opencode_api_key,
        api_url=opencode_api_url,
        provider_id=opencode_provider,
    )
