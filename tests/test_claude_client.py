from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace

from app.llm.claude_client import ClaudeCallError, _contains_timeout, _exception_detail
from app.llm.claude_client import ClaudeClient, _patch_sdk_windows_hidden_cli_spawn


def test_exception_detail_unwraps_exception_group() -> None:
    exc = ExceptionGroup(
        "wrapper",
        [
            ClaudeCallError(
                "API Error: 400 {\"error\":{\"message\":\"invalid value: `document`\"}}"
            )
        ],
    )

    detail = _exception_detail(exc)

    assert "invalid value: `document`" in detail


def test_contains_timeout_detects_nested_timeout() -> None:
    exc = ExceptionGroup("wrapper", [TimeoutError()])

    assert _contains_timeout(exc) is True


def test_exception_detail_falls_back_to_exception_type_name_when_empty() -> None:
    exc = TimeoutError()

    assert _exception_detail(exc) == "TimeoutError"


def test_resolved_cli_path_prefers_packaged_bundled_cli(monkeypatch, tmp_path: Path) -> None:
    bundled_cli = tmp_path / "claude.exe"
    bundled_cli.write_text("stub", encoding="utf-8")
    client = ClaudeClient(show_progress=False)

    monkeypatch.setattr("app.llm.claude_client.default_claude_bundled_cli_path", lambda: bundled_cli.resolve())
    monkeypatch.setattr("app.llm.claude_client.shutil.which", lambda _name: None)

    assert client._resolved_cli_path() == str(bundled_cli.resolve())


def test_build_options_passes_resolved_cli_path(monkeypatch, tmp_path: Path) -> None:
    bundled_cli = tmp_path / "claude.exe"
    bundled_cli.write_text("stub", encoding="utf-8")
    captured: dict[str, object] = {}

    class FakeClaudeAgentOptions:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    client = ClaudeClient(show_progress=False)
    monkeypatch.setattr(ClaudeClient, "_resolved_cli_path", lambda self: str(bundled_cli.resolve()))

    client._build_options({"ClaudeAgentOptions": FakeClaudeAgentOptions}, lambda _line: None)

    assert captured["cli_path"] == str(bundled_cli.resolve())


def test_build_sdk_env_includes_detected_git_bash_on_windows(monkeypatch, tmp_path: Path) -> None:
    git_bash = tmp_path / "bash.exe"
    git_bash.write_text("stub", encoding="utf-8")
    client = ClaudeClient(show_progress=False)

    monkeypatch.setattr("app.llm.claude_client.os.name", "nt")
    monkeypatch.setattr(ClaudeClient, "_git_bash_path", lambda self: git_bash.resolve())

    env = client._build_sdk_env()

    assert env["CLAUDE_CODE_GIT_BASH_PATH"] == str(git_bash.resolve())


def test_build_sdk_env_preserves_explicit_git_bash_env(monkeypatch, tmp_path: Path) -> None:
    explicit_bash = tmp_path / "explicit-bash.exe"
    detected_bash = tmp_path / "detected-bash.exe"
    explicit_bash.write_text("stub", encoding="utf-8")
    detected_bash.write_text("stub", encoding="utf-8")
    client = ClaudeClient(show_progress=False)

    monkeypatch.setenv("CLAUDE_CODE_GIT_BASH_PATH", str(explicit_bash.resolve()))
    monkeypatch.setattr("app.llm.claude_client.os.name", "nt")
    monkeypatch.setattr(ClaudeClient, "_git_bash_path", lambda self: detected_bash.resolve())

    env = client._build_sdk_env()

    assert env["CLAUDE_CODE_GIT_BASH_PATH"] == str(explicit_bash.resolve())


def test_unavailable_reason_reports_missing_git_bash_on_windows(monkeypatch) -> None:
    client = ClaudeClient(show_progress=False)

    monkeypatch.setattr("app.llm.claude_client.os.name", "nt")
    monkeypatch.setattr(ClaudeClient, "_load_sdk", lambda self: {})
    monkeypatch.setattr(ClaudeClient, "_resolved_cli_path", lambda self: "D:/claude.exe")
    monkeypatch.setattr(ClaudeClient, "_git_bash_path", lambda self: None)
    monkeypatch.delenv("CLAUDE_CODE_GIT_BASH_PATH", raising=False)

    reason = client.unavailable_reason()

    assert reason is not None
    assert "git-bash" in reason.lower()


def test_ask_json_repairs_invalid_json_before_retrying_original_prompt(monkeypatch) -> None:
    client = ClaudeClient(show_progress=False)
    responses = iter(
        [
            '{"requirements":[{"id":"R001","text":"a" "source":"b"}],"findings":[],"summary":{}}',
            '{"requirements":[{"id":"R001","text":"a","source":"b"}],"findings":[],"summary":{}}',
        ]
    )

    monkeypatch.setattr(ClaudeClient, "ask_text", lambda self, prompt, task_label=None: next(responses))

    data = client.ask_json(
        "返回审查结果",
        required_top_keys=["requirements", "findings", "summary"],
        max_retries=0,
        task_label="单测",
    )

    assert isinstance(data, dict)
    assert list(data.keys()) == ["requirements", "findings", "summary"]


def test_repair_json_text_requires_top_keys(monkeypatch) -> None:
    client = ClaudeClient(show_progress=False)

    monkeypatch.setattr(ClaudeClient, "ask_text", lambda self, prompt, task_label=None: '{"foo": 1}')

    try:
        client.repair_json_text(
            '{"foo": 1}',
            required_top_keys=["requirements", "findings", "summary"],
            parse_error="JSONDecodeError: broken",
            task_label="单测",
        )
    except ClaudeCallError as exc:
        assert "缺少字段" in str(exc)
    else:
        raise AssertionError("repair_json_text should enforce required top keys")


def test_patch_sdk_windows_hidden_cli_spawn_injects_hidden_process_flags(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def _fake_open_process(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return object()

    fake_anyio = SimpleNamespace(open_process=_fake_open_process)
    fake_module = SimpleNamespace(anyio=fake_anyio)

    monkeypatch.setattr("app.llm.claude_client.os.name", "nt")
    monkeypatch.setattr("app.llm.claude_client.importlib.import_module", lambda _name: fake_module)

    _patch_sdk_windows_hidden_cli_spawn()
    patched = fake_anyio.open_process

    assert getattr(patched, "_bidreview_hide_console_patch", False) is True

    import anyio

    anyio.run(patched, ["C:/tool/claude.exe", "-v"])

    kwargs = captured["kwargs"]
    assert int(kwargs["creationflags"]) != 0
    assert kwargs["startupinfo"] is not None


def test_patch_sdk_windows_hidden_cli_spawn_is_idempotent(monkeypatch) -> None:
    async def _fake_open_process(*args, **kwargs):
        return object()

    fake_anyio = SimpleNamespace(open_process=_fake_open_process)
    fake_module = SimpleNamespace(anyio=fake_anyio)

    monkeypatch.setattr("app.llm.claude_client.os.name", "nt")
    monkeypatch.setattr("app.llm.claude_client.importlib.import_module", lambda _name: fake_module)

    _patch_sdk_windows_hidden_cli_spawn()
    first = fake_anyio.open_process
    _patch_sdk_windows_hidden_cli_spawn()
    second = fake_anyio.open_process

    assert first is second


def test_claude_emit_progress_tolerates_invalid_stderr_handle(monkeypatch) -> None:
    seen: list[tuple[str, str]] = []

    class _BrokenStderr(io.TextIOBase):
        def write(self, s: str) -> int:  # noqa: ANN001
            raise OSError(22, "Invalid argument")

        def flush(self) -> None:
            raise OSError(22, "Invalid argument")

    monkeypatch.setattr("app.llm.claude_client.sys.stderr", _BrokenStderr())

    client = ClaudeClient(show_progress=True, progress_level="basic", progress_callback=lambda message, level: seen.append((message, level)))
    client._emit_progress("[agent] hello", "basic")

    assert seen == [("[agent] hello", "basic")]
