from __future__ import annotations

from dataclasses import dataclass

from app.llm.claude_client import ClaudeClient


class _FakeClaudeAgentOptions:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


@dataclass
class _FakeSystemMessage:
    subtype: str
    data: dict


@dataclass
class _FakeTaskProgressMessage(_FakeSystemMessage):
    description: str = ""


@dataclass
class _FakeTaskNotificationMessage(_FakeSystemMessage):
    summary: str = ""


@dataclass
class _FakeTextBlock:
    text: str


@dataclass
class _FakeThinkingBlock:
    thinking: str
    signature: str = ""


@dataclass
class _FakeToolUseBlock:
    id: str
    name: str
    input: dict


@dataclass
class _FakeAssistantMessage:
    content: list
    model: str


@dataclass
class _FakeStreamEvent:
    uuid: str
    session_id: str
    event: dict
    parent_tool_use_id: str | None = None


@dataclass
class _FakeResultMessage:
    subtype: str
    duration_ms: int
    duration_api_ms: int
    is_error: bool
    num_turns: int
    session_id: str
    stop_reason: str | None = None
    total_cost_usd: float | None = None
    usage: dict | None = None
    result: str | None = None
    structured_output: object = None


def test_build_sdk_env_maps_auth_token_to_api_key(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://example.com")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-test")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "token-123")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    client = ClaudeClient(show_progress=False)
    env = client._build_sdk_env()

    assert env["ANTHROPIC_BASE_URL"] == "https://example.com"
    assert env["ANTHROPIC_MODEL"] == "claude-test"
    assert env["ANTHROPIC_AUTH_TOKEN"] == "token-123"
    assert env["ANTHROPIC_API_KEY"] == "token-123"


def test_ask_text_uses_sdk_and_records_tool_calls(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_query(*, prompt: str, options: object):
        captured["prompt"] = prompt
        captured["options"] = options
        yield _FakeSystemMessage(subtype="init", data={"session_id": "s-1", "model": "claude-x"})
        yield _FakeAssistantMessage(
            content=[
                _FakeToolUseBlock(
                    id="tool-1",
                    name="Read",
                    input={"path": "D:/docs/bid.docx"},
                ),
                _FakeTextBlock(text="中间输出"),
            ],
            model="claude-x",
        )
        yield _FakeResultMessage(
            subtype="success",
            duration_ms=120,
            duration_api_ms=100,
            is_error=False,
            num_turns=1,
            session_id="s-1",
            total_cost_usd=0.01,
            result="最终结果",
        )

    client = ClaudeClient(
        show_progress=False,
        workspace="D:/code/bidreview",
        mcp_config='{"mcpServers":{"demo":{"command":"python","args":["mcp.py"]}}}',
    )

    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "token-123")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-env-model")
    monkeypatch.setattr(
        client,
        "_load_sdk",
        lambda: {
            "AssistantMessage": _FakeAssistantMessage,
            "ClaudeAgentOptions": _FakeClaudeAgentOptions,
            "ResultMessage": _FakeResultMessage,
            "StreamEvent": _FakeStreamEvent,
            "SystemMessage": _FakeSystemMessage,
            "TaskNotificationMessage": _FakeTaskNotificationMessage,
            "TaskProgressMessage": _FakeTaskProgressMessage,
            "TextBlock": _FakeTextBlock,
            "ThinkingBlock": _FakeThinkingBlock,
            "ToolUseBlock": _FakeToolUseBlock,
            "query": fake_query,
        },
    )

    result = client.ask_text("测试提示", task_label="单元测试")

    assert result == "最终结果"
    assert client.get_last_tool_calls() == ["Read"]
    assert client.get_last_tool_uses() == [{"name": "Read", "input": {"path": "D:/docs/bid.docx"}}]

    options = captured["options"]
    assert isinstance(options, _FakeClaudeAgentOptions)
    assert options.model == "claude-env-model"
    assert options.permission_mode == "bypassPermissions"
    assert options.cwd == "D:/code/bidreview"
    assert options.add_dirs == ["D:/code/bidreview"]
    assert options.mcp_servers == '{"mcpServers":{"demo":{"command":"python","args":["mcp.py"]}}}'
    assert options.env["ANTHROPIC_AUTH_TOKEN"] == "token-123"
    assert options.env["ANTHROPIC_API_KEY"] == "token-123"
