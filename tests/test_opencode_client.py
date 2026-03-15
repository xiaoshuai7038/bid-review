from __future__ import annotations

import io
import json
import subprocess
import time
from pathlib import Path

import pytest

from app.llm.opencode_client import OpenCodeCallError, OpenCodeClient


class _FakeBridgeStdin:
    def __init__(self) -> None:
        self.buffer = io.StringIO()
        self.closed = False

    def write(self, text: str) -> int:
        return self.buffer.write(text)

    def close(self) -> None:
        self.closed = True

    def getvalue(self) -> str:
        return self.buffer.getvalue()


def test_opencode_legacy_command_construction_and_inline_config() -> None:
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
    assert config["permission"] == "allow"
    assert "data" not in config


def test_opencode_sdk_bridge_command_uses_local_node_and_bridge(monkeypatch: pytest.MonkeyPatch) -> None:
    client = OpenCodeClient(
        model="DeepSeek-V3.2",
        workspace="D:/code/bidreview",
        provider_id="ark",
        show_progress=False,
    )

    monkeypatch.setattr(client, "_resolve_node_bin", lambda: "node")
    monkeypatch.setattr(client, "_bridge_script_path", lambda: Path("D:/code/bidreview/scripts/opencode_sdk_bridge.mjs"))

    assert client._build_bridge_cmd() == [
        "node",
        str(Path("D:/code/bidreview/scripts/opencode_sdk_bridge.mjs")),
    ]


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


def test_opencode_ask_text_uses_sdk_bridge_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    stdin = _FakeBridgeStdin()

    class _FakePopen:
        def __init__(self, cmd, **kwargs) -> None:
            captured["cmd"] = list(cmd)
            captured["kwargs"] = kwargs
            self.stdin = stdin
            self.stdout = io.StringIO(
                '{"type":"text","part":{"text":"{\\"ok\\":true}"}}\n'
                '{"type":"usage","usage":{"input_tokens":11,"output_tokens":7,"cache_read_input_tokens":3}}\n'
                '{"type":"result","result":{"text":"{\\"ok\\":true}","usage":{"input_tokens":11,"output_tokens":7,"cache_read_input_tokens":3}}}\n'
            )
            self.stderr = io.StringIO("")

        def poll(self) -> int:
            return 0

        def wait(self, timeout=None) -> int:
            return 0

        def kill(self) -> None:
            captured["killed"] = True

    monkeypatch.setattr("app.llm.opencode_client.subprocess.Popen", _FakePopen)
    monkeypatch.setattr(OpenCodeClient, "_resolve_node_bin", lambda self: "node")
    monkeypatch.setattr(
        OpenCodeClient,
        "_bridge_script_path",
        lambda self: Path("D:/code/bidreview/scripts/opencode_sdk_bridge.mjs"),
    )

    client = OpenCodeClient(
        model="DeepSeek-V3.2",
        workspace="D:/code/bidreview",
        provider_id="ark",
        show_progress=False,
    )

    out = client.ask_text("请输出JSON")
    assert out == '{"ok":true}'
    assert captured["cmd"] == [
        "node",
        str(Path("D:/code/bidreview/scripts/opencode_sdk_bridge.mjs")),
    ]
    assert captured["kwargs"]["creationflags"] == int(getattr(subprocess, "CREATE_NO_WINDOW", 0) or 0)
    assert captured["kwargs"]["startupinfo"] is not None
    payload = json.loads(stdin.getvalue())
    assert payload["action"] == "prompt"
    assert payload["prompt"] == "请输出JSON"
    assert payload["directory"] == "D:/code/bidreview"
    assert payload["model"] == {"providerID": "ark", "modelID": "DeepSeek-V3.2"}
    assert client.get_last_usage_summary()["input_tokens"] == 11
    assert client.get_last_usage_summary()["output_tokens"] == 7
    assert client.get_last_usage_summary()["cache_read_input_tokens"] == 3


def test_opencode_ask_text_uses_legacy_cli_when_explicit_binary(monkeypatch: pytest.MonkeyPatch) -> None:
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
    assert captured["kwargs"]["creationflags"] == int(getattr(subprocess, "CREATE_NO_WINDOW", 0) or 0)
    assert captured["kwargs"]["startupinfo"] is not None


def test_opencode_ask_text_raises_on_error_event(monkeypatch: pytest.MonkeyPatch) -> None:
    stdin = _FakeBridgeStdin()

    class _FakePopen:
        def __init__(self, cmd, **kwargs) -> None:
            self.stdin = stdin
            self.stdout = io.StringIO(
                '{"type":"error","error":{"message":"Model not found: ark/DeepSeek-V3.2."}}\n'
            )
            self.stderr = io.StringIO("")

        def poll(self) -> int:
            return 0

        def wait(self, timeout=None) -> int:
            return 0

        def kill(self) -> None:
            return None

    monkeypatch.setattr("app.llm.opencode_client.subprocess.Popen", _FakePopen)
    monkeypatch.setattr(OpenCodeClient, "_resolve_node_bin", lambda self: "node")
    monkeypatch.setattr(
        OpenCodeClient,
        "_bridge_script_path",
        lambda self: Path("D:/code/bidreview/scripts/opencode_sdk_bridge.mjs"),
    )

    client = OpenCodeClient(
        model="DeepSeek-V3.2",
        workspace="D:/code/bidreview",
        provider_id="ark",
        show_progress=False,
    )

    with pytest.raises(OpenCodeCallError, match="Model not found: ark/DeepSeek-V3.2."):
        client.ask_text("请输出JSON")


def test_opencode_sdk_bridge_retries_retryable_fetch_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    events = [
        io.StringIO('{"type":"error","error":{"message":"fetch failed"}}\n'),
        io.StringIO(
            '{"type":"text","part":{"text":"retry-ok"}}\n'
            '{"type":"result","result":{"text":"retry-ok","usage":{"input_tokens":5,"output_tokens":2}}}\n'
        ),
    ]
    stdin_streams: list[_FakeBridgeStdin] = []

    class _FakePopen:
        def __init__(self, cmd, **kwargs) -> None:
            self.stdin = _FakeBridgeStdin()
            stdin_streams.append(self.stdin)
            self.stdout = events.pop(0)
            self.stderr = io.StringIO("")

        def poll(self) -> int:
            return 0

        def wait(self, timeout=None) -> int:
            return 0

        def kill(self) -> None:
            return None

    monkeypatch.setattr("app.llm.opencode_client.subprocess.Popen", _FakePopen)
    monkeypatch.setattr(OpenCodeClient, "_resolve_node_bin", lambda self: "node")
    monkeypatch.setattr(
        OpenCodeClient,
        "_bridge_script_path",
        lambda self: Path("D:/code/bidreview/scripts/opencode_sdk_bridge.mjs"),
    )

    client = OpenCodeClient(
        model="DeepSeek-V3.2",
        workspace="D:/code/bidreview",
        provider_id="ark",
        show_progress=False,
    )

    assert client.ask_text("请输出JSON") == "retry-ok"
    assert len(stdin_streams) == 2
    assert client.get_last_usage_summary()["input_tokens"] == 5
    assert client.get_last_usage_summary()["output_tokens"] == 2


def test_opencode_sdk_bridge_uses_extended_retry_budget_for_long_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = [
        io.StringIO('{"type":"error","error":{"message":"fetch failed"}}\n'),
        io.StringIO('{"type":"error","error":{"message":"fetch failed"}}\n'),
        io.StringIO('{"type":"error","error":{"message":"fetch failed"}}\n'),
        io.StringIO('{"type":"error","error":{"message":"fetch failed"}}\n'),
        io.StringIO(
            '{"type":"text","part":{"text":"retry-ok"}}\n'
            '{"type":"result","result":{"text":"retry-ok","usage":{"input_tokens":8,"output_tokens":3}}}\n'
        ),
    ]
    stdin_streams: list[_FakeBridgeStdin] = []

    class _FakePopen:
        def __init__(self, cmd, **kwargs) -> None:
            self.stdin = _FakeBridgeStdin()
            stdin_streams.append(self.stdin)
            self.stdout = events.pop(0)
            self.stderr = io.StringIO("")

        def poll(self) -> int:
            return 0

        def wait(self, timeout=None) -> int:
            return 0

        def kill(self) -> None:
            return None

    monkeypatch.setattr("app.llm.opencode_client.subprocess.Popen", _FakePopen)
    monkeypatch.setattr("app.llm.opencode_client.time.sleep", lambda _seconds: None)
    monkeypatch.setattr(OpenCodeClient, "_resolve_node_bin", lambda self: "node")
    monkeypatch.setattr(
        OpenCodeClient,
        "_bridge_script_path",
        lambda self: Path("D:/code/bidreview/scripts/opencode_sdk_bridge.mjs"),
    )

    client = OpenCodeClient(
        model="DeepSeek-V3.2",
        workspace="D:/code/bidreview",
        provider_id="ark",
        timeout_sec=3600,
        show_progress=False,
    )

    assert client.ask_text("请输出JSON") == "retry-ok"
    assert len(stdin_streams) == 5
    assert client.get_last_usage_summary()["input_tokens"] == 8
    assert client.get_last_usage_summary()["output_tokens"] == 3


def test_opencode_sdk_bridge_does_not_retry_non_retryable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakePopen:
        def __init__(self, cmd, **kwargs) -> None:
            self.stdin = _FakeBridgeStdin()
            self.stdout = io.StringIO('{"type":"error","error":{"message":"permission denied"}}\n')
            self.stderr = io.StringIO("")

        def poll(self) -> int:
            return 0

        def wait(self, timeout=None) -> int:
            return 0

        def kill(self) -> None:
            return None

    monkeypatch.setattr("app.llm.opencode_client.subprocess.Popen", _FakePopen)
    monkeypatch.setattr(OpenCodeClient, "_resolve_node_bin", lambda self: "node")
    monkeypatch.setattr(
        OpenCodeClient,
        "_bridge_script_path",
        lambda self: Path("D:/code/bidreview/scripts/opencode_sdk_bridge.mjs"),
    )

    client = OpenCodeClient(
        model="DeepSeek-V3.2",
        workspace="D:/code/bidreview",
        provider_id="ark",
        show_progress=False,
    )

    with pytest.raises(OpenCodeCallError, match="permission denied"):
        client.ask_text("请输出JSON")


def test_opencode_ask_text_waits_for_delayed_first_stdout_line(monkeypatch: pytest.MonkeyPatch) -> None:
    stdout_stream = object()
    stderr_stream = object()
    stdin = _FakeBridgeStdin()

    class _FakePopen:
        def __init__(self, cmd, **kwargs) -> None:
            self.stdin = stdin
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
            out_queue.put('{"type":"result","result":{"text":"delayed"}}\n')
        out_queue.put(None)

    monkeypatch.setattr("app.llm.opencode_client.subprocess.Popen", _FakePopen)
    monkeypatch.setattr(OpenCodeClient, "_reader_thread", staticmethod(_fake_reader_thread))
    monkeypatch.setattr(OpenCodeClient, "_resolve_node_bin", lambda self: "node")
    monkeypatch.setattr(
        OpenCodeClient,
        "_bridge_script_path",
        lambda self: Path("D:/code/bidreview/scripts/opencode_sdk_bridge.mjs"),
    )

    client = OpenCodeClient(
        model=None,
        workspace="D:/code/bidreview",
        provider_id="ark",
        show_progress=False,
    )

    assert client.ask_text("请输出JSON") == "delayed"


def test_opencode_build_runtime_env_converts_claude_mcp_config() -> None:
    client = OpenCodeClient(
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
        model="DeepSeek-V3.2",
        workspace=str(workspace),
        provider_id="ark",
        show_progress=False,
    )

    env = client._build_runtime_env()
    config = json.loads(env["OPENCODE_CONFIG_CONTENT"])
    assert sorted(config["mcp"].keys()) == ["document-parser"]
    assert config["mcp"]["document-parser"]["command"] == ["python", "parser.py"]


def test_opencode_available_uses_sdk_healthcheck_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    client = OpenCodeClient(show_progress=False)
    monkeypatch.setattr(client, "_run_sdk_healthcheck", lambda: None)
    assert client.available() is True
    assert client.unavailable_reason() is None


def test_opencode_available_uses_legacy_cli_when_explicit_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout="1.2.25", stderr="")

    import subprocess

    monkeypatch.setattr("app.llm.opencode_client.subprocess.run", _fake_run)

    client = OpenCodeClient(opencode_bin="opencode", show_progress=False)
    assert client.available() is True


def test_opencode_clone_for_parallel_review_uses_isolated_runtime_data_dir(tmp_path: Path) -> None:
    client = OpenCodeClient(
        model="DeepSeek-V3.2",
        workspace="D:/code/bidreview",
        provider_id="ark",
        show_progress=False,
    )

    clone_a = client.clone_for_parallel_review(stage_name="compliance")
    clone_b = client.clone_for_parallel_review(stage_name="context")

    assert clone_a.runtime_data_dir
    assert clone_b.runtime_data_dir
    assert clone_a.runtime_data_dir != clone_b.runtime_data_dir
    assert Path(clone_a.runtime_data_dir).exists()
    assert Path(clone_b.runtime_data_dir).exists()


def test_opencode_runtime_env_uses_isolated_home_when_runtime_data_dir_is_set(tmp_path: Path) -> None:
    runtime_root = tmp_path / "opencode-runtime-home"
    client = OpenCodeClient(
        model="DeepSeek-V3.2",
        workspace="D:/code/bidreview",
        provider_id="ark",
        runtime_data_dir=str(runtime_root),
        show_progress=False,
    )

    env = client._build_runtime_env()
    assert env["HOME"] == str(runtime_root)
    assert env["USERPROFILE"] == str(runtime_root)
    assert env["LOCALAPPDATA"] == str(runtime_root / "AppData" / "Local")
    assert env["APPDATA"] == str(runtime_root / "AppData" / "Roaming")
    assert env["XDG_DATA_HOME"] == str(runtime_root / ".local" / "share")
    config = json.loads(env["OPENCODE_CONFIG_CONTENT"])
    assert "data" not in config


def test_opencode_frozen_runtime_paths_prefer_bundled_resources(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bundle_root = tmp_path / "BidReviewDesktop"
    runtime_root = bundle_root / "third-party" / "opencode"
    bridge_path = runtime_root / "bridge" / "opencode_sdk_bridge.mjs"
    local_bin = runtime_root / "node_modules" / ".bin" / "opencode.cmd"
    node_exe = bundle_root / "third-party" / "nodejs" / "node.exe"
    bridge_path.parent.mkdir(parents=True)
    local_bin.parent.mkdir(parents=True)
    node_exe.parent.mkdir(parents=True)
    bridge_path.write_text("// bridge", encoding="utf-8")
    local_bin.write_text("stub", encoding="utf-8")
    node_exe.write_text("stub", encoding="utf-8")

    monkeypatch.setattr(
        "app.ai.providers.opencode.client.default_bundled_opencode_runtime_root",
        lambda: runtime_root.resolve(),
    )
    monkeypatch.setattr(
        "app.ai.providers.opencode.client.default_bundled_node_exe",
        lambda: node_exe.resolve(),
    )

    client = OpenCodeClient(show_progress=False)

    assert client._runtime_root_path() == runtime_root.resolve()
    assert client._bridge_script_path() == bridge_path.resolve()
    assert client._local_opencode_bin_path() == local_bin.resolve()
    assert client._resolve_node_bin() == str(node_exe.resolve())
    env = client._build_bridge_env()
    assert env["BID_REVIEW_OPENCODE_RUNTIME_ROOT"] == str(runtime_root.resolve())


def test_opencode_build_bridge_env_injects_runtime_binary_and_provider_timeouts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime_root = tmp_path / "BidReviewDesktop" / "third-party" / "opencode"
    local_bin = runtime_root / "node_modules" / ".bin" / "opencode.cmd"
    runtime_binary = runtime_root / "node_modules" / "opencode-windows-x64" / "bin" / "opencode.exe"
    local_bin.parent.mkdir(parents=True)
    runtime_binary.parent.mkdir(parents=True)
    local_bin.write_text("stub", encoding="utf-8")
    runtime_binary.write_text("stub", encoding="utf-8")

    monkeypatch.setattr(
        "app.ai.providers.opencode.client.default_bundled_opencode_runtime_root",
        lambda: runtime_root.resolve(),
    )

    client = OpenCodeClient(
        model="DeepSeek-V3.2",
        provider_id="ark",
        timeout_sec=3600,
        show_progress=False,
    )

    env = client._build_bridge_env()
    config = json.loads(env["OPENCODE_CONFIG_CONTENT"])
    provider_cfg = config["provider"]["ark"]

    assert env["OPENCODE_BIN_PATH"] == str(runtime_binary.resolve())
    assert provider_cfg["options"]["timeout"] is False
    assert provider_cfg["options"]["chunkTimeout"] == 3600000
    assert provider_cfg["options"]["maxRetries"] == 4
    assert provider_cfg["models"]["DeepSeek-V3.2"]["name"] == "DeepSeek-V3.2"


def test_opencode_emit_progress_tolerates_invalid_stderr_handle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[str, str]] = []

    class _BrokenStderr(io.TextIOBase):
        def write(self, s: str) -> int:  # noqa: ANN001
            raise OSError(22, "Invalid argument")

        def flush(self) -> None:
            raise OSError(22, "Invalid argument")

    monkeypatch.setattr("app.llm.opencode_client.sys.stderr", _BrokenStderr())

    client = OpenCodeClient(
        show_progress=True,
        progress_level="basic",
        progress_callback=lambda message, level: seen.append((message, level)),
    )
    client._emit_progress("[agent] hello", "basic")

    assert seen == [("[agent] hello", "basic")]
