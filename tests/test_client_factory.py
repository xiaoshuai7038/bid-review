from __future__ import annotations

from app.llm.client_factory import create_llm_client
from app.llm.claude_client import ClaudeClient
from app.llm.opencode_client import OpenCodeClient


def test_backend_switch_create_claude_client() -> None:
    backend, client = create_llm_client(
        backend="claude",
        claude_bin="claude",
        opencode_bin=None,
        model="claude-model",
        opencode_model=None,
        effort="low",
        show_progress=False,
        progress_level="basic",
        timeout_sec=10,
        workspace="D:/code/bidreview",
        mcp_config=None,
        opencode_api_key=None,
        opencode_api_url=None,
        opencode_provider="ark",
    )
    assert backend == "claude"
    assert isinstance(client, ClaudeClient)
    assert client.model == "claude-model"


def test_backend_switch_create_opencode_client() -> None:
    backend, client = create_llm_client(
        backend="opencode",
        claude_bin=None,
        opencode_bin="opencode",
        model="common-model",
        opencode_model="DeepSeek-V3.2",
        effort="low",
        show_progress=False,
        progress_level="basic",
        timeout_sec=10,
        workspace="D:/code/bidreview",
        mcp_config=None,
        opencode_api_key="secret",
        opencode_api_url="https://ark.cn-beijing.volces.com/api/coding/v3",
        opencode_provider="ark",
    )
    assert backend == "opencode"
    assert isinstance(client, OpenCodeClient)
    assert client.model == "common-model"
    assert client.api_url == "https://ark.cn-beijing.volces.com/api/coding/v3"
    assert client.mcp_config is None


def test_opencode_model_falls_back_to_env_default(monkeypatch) -> None:
    monkeypatch.setenv("BID_REVIEW_OPENCODE_MODEL", "env-model")
    backend, client = create_llm_client(
        backend="opencode",
        claude_bin=None,
        opencode_bin="opencode",
        model=None,
        opencode_model=None,
        effort="low",
        show_progress=False,
        progress_level="basic",
        timeout_sec=10,
        workspace="D:/code/bidreview",
        mcp_config=None,
        opencode_api_key=None,
        opencode_api_url=None,
        opencode_provider="ark",
    )
    assert backend == "opencode"
    assert isinstance(client, OpenCodeClient)
    assert client.model == "env-model"


def test_opencode_client_receives_mcp_config() -> None:
    backend, client = create_llm_client(
        backend="opencode",
        claude_bin=None,
        opencode_bin="opencode",
        model=None,
        opencode_model="DeepSeek-V3.2",
        effort="low",
        show_progress=False,
        progress_level="basic",
        timeout_sec=10,
        workspace="D:/code/bidreview",
        mcp_config='{"mcpServers":{"document-parser":{"command":"python","args":["parser.py"]}}}',
        opencode_api_key=None,
        opencode_api_url=None,
        opencode_provider="ark",
    )
    assert backend == "opencode"
    assert isinstance(client, OpenCodeClient)
    assert client.mcp_config is not None
