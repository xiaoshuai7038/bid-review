from __future__ import annotations

import io
import json
import time
from pathlib import Path

import pytest

from app.llm.opencode_client import OpenCodeCallError, OpenCodeClient


def test_opencode_command_construction_and_inline_config() -> None:
    client = OpenCodeClient(
        opencode_bin="opencode",
        model="DeepSeek-V3.2",
        workspace="D:/code/bidreview",
        provider_id="ark",
        api_key="k-test",
        api_url="https://ark.cn-beijing.volces.com/api/coding/v3",
        show_progress=False,
    )

    cmd = client._base_cmd()
    assert cmd == [
        "opencode",
        "run",
        "--format",
        "json",
        "--model",
        "ark/DeepSeek-V3.2",
        "--dir",
        "D:/code/bidreview",
    ]

    env = client._build_runtime_env()
    assert "OPENCODE_CONFIG_CONTENT" in env
    config = json.loads(env["OPENCODE_CONFIG_CONTENT"])
    provider_cfg = config["provider"]["ark"]
    assert provider_cfg["options"]["baseURL"] == "https://ark.cn-beijing.volces.com/api/coding/v3"
    assert provider_cfg["options"]["apiKey"] == "{env:BID_REVIEW_OPENCODE_API_KEY}"
    assert provider_cfg["models"]["DeepSeek-V3.2"]["name"] == "DeepSeek-V3.2"
    assert env["BID_REVIEW_OPENCODE_API_KEY"] == "k-test"


def test_opencode_parse_invalid_json_output_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    client = OpenCodeClient(show_progress=False)
    monkeypatch.setattr(client, "ask_text", lambda *args, **kwargs: "not-json")
    with pytest.raises(OpenCodeCallError, match="JSON解析失败"):
        client.ask_json("仅用于测试", required_top_keys=["requirements"], max_retries=0)


def test_opencode_base_cmd_omits_model_when_unspecified() -> None:
    client = OpenCodeClient(
        opencode_bin="opencode",
        model=None,
        workspace="D:/code/bidreview",
        provider_id="ark",
        show_progress=False,
    )

    assert client._base_cmd() == [
        "opencode",
        "run",
        "--format",
        "json",
        "--dir",
        "D:/code/bidreview",
    ]


def test_opencode_ask_text_sends_prompt_as_message_arg(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class _FakePopen:
        def __init__(self, cmd, **kwargs) -> None:
            captured["cmd"] = list(cmd)
            captured["kwargs"] = kwargs
            self.stdout = io.StringIO(
                '{"type":"text","part":{"text":"{\\"ok\\":true}"}}\n'
                '{"type":"step_finish","part":{"reason":"stop"}}\n'
            )
            self.stderr = io.StringIO("")

        def poll(self) -> int:
            return 0

        def wait(self, timeout=None) -> int:
            return 0

        def kill(self) -> None:
            captured["killed"] = True

    monkeypatch.setattr("app.llm.opencode_client.subprocess.Popen", _FakePopen)

    client = OpenCodeClient(
        opencode_bin="opencode",
        model="DeepSeek-V3.2",
        workspace="D:/code/bidreview",
        provider_id="ark",
        show_progress=False,
    )

    out = client.ask_text("请输出JSON")
    assert out == '{"ok":true}'
    assert captured["cmd"] == [
        "opencode",
        "run",
        "--format",
        "json",
        "--model",
        "ark/DeepSeek-V3.2",
        "--dir",
        "D:/code/bidreview",
        "请输出JSON",
    ]


def test_opencode_ask_text_raises_on_error_event(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakePopen:
        def __init__(self, cmd, **kwargs) -> None:
            self.stdout = io.StringIO(
                '{"type":"error","error":{"name":"UnknownError","data":{"message":"Model not found: ark/DeepSeek-V3.2."}}}\n'
            )
            self.stderr = io.StringIO("")

        def poll(self) -> int:
            return 0

        def wait(self, timeout=None) -> int:
            return 0

        def kill(self) -> None:
            return None

    monkeypatch.setattr("app.llm.opencode_client.subprocess.Popen", _FakePopen)

    client = OpenCodeClient(
        opencode_bin="opencode",
        model="DeepSeek-V3.2",
        workspace="D:/code/bidreview",
        provider_id="ark",
        show_progress=False,
    )

    with pytest.raises(OpenCodeCallError, match="Model not found: ark/DeepSeek-V3.2."):
        client.ask_text("请输出JSON")


def test_opencode_ask_text_waits_for_delayed_first_stdout_line(monkeypatch: pytest.MonkeyPatch) -> None:
    stdout_stream = object()
    stderr_stream = object()

    class _FakePopen:
        def __init__(self, cmd, **kwargs) -> None:
            self.stdout = stdout_stream
            self.stderr = stderr_stream

        def poll(self) -> int | None:
            return 0

        def wait(self, timeout=None) -> int:
            return 0

        def kill(self) -> None:
            return None

    def _fake_reader_thread(stream, out_queue) -> None:
        time.sleep(1.2)
        if stream is stdout_stream:
            out_queue.put('{"type":"text","part":{"text":"delayed"}}\n')
        out_queue.put(None)

    monkeypatch.setattr("app.llm.opencode_client.subprocess.Popen", _FakePopen)
    monkeypatch.setattr(OpenCodeClient, "_reader_thread", staticmethod(_fake_reader_thread))

    client = OpenCodeClient(
        opencode_bin="opencode",
        model=None,
        workspace="D:/code/bidreview",
        provider_id="ark",
        show_progress=False,
    )

    assert client.ask_text("请输出JSON") == "delayed"


def test_opencode_build_runtime_env_converts_claude_mcp_config() -> None:
    client = OpenCodeClient(
        opencode_bin="opencode",
        model="DeepSeek-V3.2",
        workspace="D:/code/bidreview",
        provider_id="ark",
        mcp_config=json.dumps(
            {
                "mcpServers": {
                    "document-parser": {
                        "command": "python",
                        "args": ["parser.py"],
                        "env": {"PYTHONPATH": "D:/python"},
                        "timeout": 300,
                    }
                }
            },
            ensure_ascii=False,
        ),
        show_progress=False,
    )

    env = client._build_runtime_env()
    config = json.loads(env["OPENCODE_CONFIG_CONTENT"])
    server_cfg = config["mcp"]["document-parser"]
    assert server_cfg["type"] == "local"
    assert server_cfg["enabled"] is True
    assert server_cfg["command"] == ["python", "parser.py"]
    assert server_cfg["environment"]["PYTHONPATH"] == "D:/python"
    assert server_cfg["timeout"] == 300000


def test_opencode_build_runtime_env_discovers_claude_mcp_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    project_claude_dir = workspace / ".claude"
    project_claude_dir.mkdir()
    (project_claude_dir / "settings.local.json").write_text(
        json.dumps(
            {
                "permissions": {
                    "allow": [
                        "mcp__document-parser__extract_images_from_word",
                    ]
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    mcp_dir = tmp_path / "claude-mcp"
    mcp_dir.mkdir()
    (mcp_dir / "document-parser.json").write_text(
        json.dumps(
            {
                "command": "python",
                "args": ["parser.py"],
                "env": {"PYTHONPATH": "D:/python"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (mcp_dir / "unused.json").write_text(
        json.dumps(
            {
                "command": "python",
                "args": ["unused.py"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("BID_REVIEW_CLAUDE_MCP_DIR", str(mcp_dir))

    client = OpenCodeClient(
        opencode_bin="opencode",
        model="DeepSeek-V3.2",
        workspace=str(workspace),
        provider_id="ark",
        show_progress=False,
    )

    env = client._build_runtime_env()
    config = json.loads(env["OPENCODE_CONFIG_CONTENT"])
    assert sorted(config["mcp"].keys()) == ["document-parser"]
    assert config["mcp"]["document-parser"]["command"] == ["python", "parser.py"]
