from __future__ import annotations

from app.llm.claude_client import ClaudeClient
from app.review.claude_review import (
    _CLAUDE_SDK_REVIEW_TOOL_ALLOWLIST,
    _prefer_claude_sdk_review_tools,
)


def test_sdk_review_tool_allowlist_excludes_builtin_read() -> None:
    assert "Read" not in _CLAUDE_SDK_REVIEW_TOOL_ALLOWLIST
    assert "document-parser.read_pdf" in _CLAUDE_SDK_REVIEW_TOOL_ALLOWLIST
    assert "document-parser.read_word" in _CLAUDE_SDK_REVIEW_TOOL_ALLOWLIST


def test_prefer_claude_sdk_review_tools_is_scoped() -> None:
    client = ClaudeClient(tools="default")

    with _prefer_claude_sdk_review_tools(client):
        assert client.tools == _CLAUDE_SDK_REVIEW_TOOL_ALLOWLIST

    assert client.tools == "default"
