from __future__ import annotations

import importlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable

import anyio

from app.llm.prompt_store import render_prompt
from app.runtime_paths import (
    CLAUDE_CONFIG_DIR_ENV,
    CLAUDE_CODE_GIT_BASH_PATH_ENV,
    RUNTIME_ROOT_ENV,
    default_claude_bundled_cli_path,
    default_claude_config_dir,
    default_git_bash_path,
    managed_runtime_enabled,
    runtime_root,
)


class ClaudeCallError(RuntimeError):
    pass


class ProgressLevel(str, Enum):
    BASIC = "basic"
    AGENT = "agent"
    NORMAL = "normal"
    DETAILED = "detailed"
    EVENTS = "events"
    RAW = "raw"

    def rank(self) -> int:
        return {
            ProgressLevel.BASIC: 0,
            ProgressLevel.AGENT: 1,
            ProgressLevel.NORMAL: 2,
            ProgressLevel.DETAILED: 3,
            ProgressLevel.EVENTS: 4,
            ProgressLevel.RAW: 5,
        }[self]


class Phase(str, Enum):
    LOCATE_FILES = "定位与确认输入文件"
    READ_DOCS = "读取文档内容"
    EXTRACT_REQS = "提取硬性要求"
    REVIEW = "逐条比对审查"
    GENERATE_REPORT = "整理并生成报告"
    ANALYSIS = "执行分析步骤"

    def next_hint(self) -> str:
        return {
            Phase.LOCATE_FILES: "读取文档内容",
            Phase.READ_DOCS: "提取硬性要求",
            Phase.EXTRACT_REQS: "逐条比对审查",
            Phase.REVIEW: "整理并生成报告",
            Phase.GENERATE_REPORT: "返回最终审查结果",
            Phase.ANALYSIS: "继续推进审查流程",
        }.get(self, "继续推进审查流程")

    def rank(self) -> int:
        return {
            Phase.LOCATE_FILES: 1,
            Phase.READ_DOCS: 2,
            Phase.EXTRACT_REQS: 3,
            Phase.REVIEW: 4,
            Phase.GENERATE_REPORT: 5,
            Phase.ANALYSIS: 2,
        }.get(self, 2)


def extract_json_payload(text: str) -> Any:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", cleaned)
    if not match:
        raise ClaudeCallError(f"未找到 JSON 结构，原始输出: {text[:500]}")
    return json.loads(match.group(1))


def _exception_detail(exc: BaseException) -> str:
    if isinstance(exc, BaseExceptionGroup):
        details = [_exception_detail(sub) for sub in exc.exceptions]
        details = [detail for detail in details if detail]
        return " | ".join(details)
    detail = str(exc).strip()
    return detail or type(exc).__name__


def _contains_timeout(exc: BaseException) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    if isinstance(exc, BaseExceptionGroup):
        return any(_contains_timeout(sub) for sub in exc.exceptions)
    return False


def _looks_like_claude_cli_command(command: Any) -> bool:
    if isinstance(command, (list, tuple)) and command:
        executable = str(command[0] or "").strip().lower()
    else:
        executable = str(command or "").strip().lower()
    return executable.endswith("claude.exe") or executable.endswith("\\claude") or executable.endswith("/claude")


def _patch_sdk_windows_hidden_cli_spawn() -> None:
    if os.name != "nt":
        return
    try:
        transport_module = importlib.import_module("claude_agent_sdk._internal.transport.subprocess_cli")
    except Exception:
        return
    anyio_module = getattr(transport_module, "anyio", None)
    if anyio_module is None:
        return
    original_open_process = getattr(anyio_module, "open_process", None)
    if original_open_process is None or getattr(original_open_process, "_bidreview_hide_console_patch", False):
        return

    async def _open_process_hidden(*args, **kwargs):
        command = args[0] if args else kwargs.get("command")
        if _looks_like_claude_cli_command(command):
            creationflags = int(kwargs.get("creationflags", 0) or 0)
            creationflags |= int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
            kwargs["creationflags"] = creationflags
            if kwargs.get("startupinfo") is None and hasattr(subprocess, "STARTUPINFO"):
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
                startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
                kwargs["startupinfo"] = startupinfo
        return await original_open_process(*args, **kwargs)

    setattr(_open_process_hidden, "_bidreview_hide_console_patch", True)
    setattr(_open_process_hidden, "_bidreview_original_open_process", original_open_process)
    anyio_module.open_process = _open_process_hidden


@dataclass
class ClaudeClient:
    claude_bin: str | None = None
    model: str | None = None
    effort: str = "low"
    agent: str = "general-purpose"
    tools: str = "default"
    timeout_sec: int = 240
    show_progress: bool = True
    progress_heartbeat_sec: int = 20
    progress_level: str = "agent"
    workspace: str | None = None
    mcp_config: Any = None
    progress_callback: Callable[[str, str], None] | None = None
    _last_tool_calls: list[str] = field(default_factory=list, init=False, repr=False)
    _last_tool_uses: list[dict[str, Any]] = field(default_factory=list, init=False, repr=False)
    _last_usage_summary: dict[str, Any] = field(default_factory=dict, init=False, repr=False)

    def _emit_progress(self, message: str, level: str = "normal") -> None:
        if not self.show_progress:
            return
        if self.progress_level in {"raw", "events"} and level != self.progress_level:
            return
        if self.progress_level == "agent" and level not in {"agent", "basic"}:
            return
        try:
            conf_level = ProgressLevel(self.progress_level)
            req_level = ProgressLevel(level)
            if conf_level.rank() < req_level.rank():
                return
        except ValueError:
            pass
        if self.progress_callback is not None:
            try:
                self.progress_callback(message, level)
            except Exception:
                pass
        print(message, file=sys.stderr, flush=True)

    @staticmethod
    def _short_text(text: str, limit: int = 120) -> str:
        if len(text) <= limit and "\n" not in text:
            return text.strip()
        one_line = text.replace("\n", " ").strip()
        if len(one_line) <= limit:
            return one_line
        return one_line[:limit] + "..."

    @staticmethod
    def _infer_phase_from_tool(tool_name: str, tool_input: Any) -> Phase:
        name = (tool_name or "").lower()
        inp_lower = ""
        if isinstance(tool_input, dict):
            for value in tool_input.values():
                if isinstance(value, str):
                    inp_lower += " " + value.lower()
        elif isinstance(tool_input, str):
            inp_lower = tool_input.lower()
        else:
            try:
                inp_lower = json.dumps(tool_input, ensure_ascii=False).lower()
            except Exception:
                inp_lower = str(tool_input).lower()

        if any(k in inp_lower for k in ["ls ", "find ", "glob", "目录", "path", "文件列表"]):
            return Phase.LOCATE_FILES
        if name == "read" or any(k in inp_lower for k in ["read", "extract", ".pdf", ".docx", "章节", "chapter"]):
            return Phase.READ_DOCS
        if any(k in inp_lower for k in ["requirement", "硬性", "条款", "资格", "投标人须知"]):
            return Phase.EXTRACT_REQS
        if any(k in inp_lower for k in ["compare", "review", "check", "compliance", "偏离", "核对"]):
            return Phase.REVIEW
        if any(k in inp_lower for k in ["json", "report", "write", "output", "markdown", "docx"]):
            return Phase.GENERATE_REPORT
        return Phase.ANALYSIS

    def _report_phase_completion(
        self,
        phase: str,
        phase_started_ts: float,
        hint: str,
        phase_tool_count_val: int,
    ) -> None:
        phase_elapsed = int(time.time() - phase_started_ts)
        phase_hint = hint or f"调用工具 {phase_tool_count_val} 次"
        self._emit_progress(
            f"[agent] 阶段成果：{phase}（{phase_elapsed}s，{phase_hint}）",
            level="agent",
        )

    def _sdk_package_dir(self) -> Path | None:
        spec = importlib.util.find_spec("claude_agent_sdk")
        if spec is None or not spec.submodule_search_locations:
            return None
        return Path(next(iter(spec.submodule_search_locations)))

    def _bundled_cli_path(self) -> Path | None:
        frozen_bundled = default_claude_bundled_cli_path()
        if frozen_bundled is not None:
            return frozen_bundled
        package_dir = self._sdk_package_dir()
        if package_dir is None:
            return None
        cli_name = "claude.exe" if os.name == "nt" else "claude"
        bundled = package_dir / "_bundled" / cli_name
        if bundled.exists() and bundled.is_file():
            return bundled
        return None

    def _resolved_cli_path(self) -> str | None:
        if self.claude_bin:
            candidate = Path(self.claude_bin).expanduser().resolve()
            if candidate.exists() and candidate.is_file():
                return str(candidate)
            return None
        bundled = self._bundled_cli_path()
        if bundled is not None:
            return str(bundled)
        return shutil.which("claude")

    def _load_sdk(self) -> dict[str, Any]:
        try:
            from claude_agent_sdk import (
                AssistantMessage,
                ClaudeAgentOptions,
                ResultMessage,
                SystemMessage,
                TaskNotificationMessage,
                TaskProgressMessage,
                TextBlock,
                ThinkingBlock,
                ToolUseBlock,
                query,
            )
            from claude_agent_sdk.types import StreamEvent
        except Exception as exc:  # noqa: BLE001
            raise ClaudeCallError(
                "未安装或无法导入 claude-agent-sdk，请先执行 `uv sync` 安装项目依赖。"
            ) from exc
        _patch_sdk_windows_hidden_cli_spawn()
        return {
            "AssistantMessage": AssistantMessage,
            "ClaudeAgentOptions": ClaudeAgentOptions,
            "ResultMessage": ResultMessage,
            "StreamEvent": StreamEvent,
            "SystemMessage": SystemMessage,
            "TaskNotificationMessage": TaskNotificationMessage,
            "TaskProgressMessage": TaskProgressMessage,
            "TextBlock": TextBlock,
            "ThinkingBlock": ThinkingBlock,
            "ToolUseBlock": ToolUseBlock,
            "query": query,
        }

    def _resolve_model(self) -> str | None:
        explicit = (self.model or "").strip()
        if explicit:
            return explicit
        env_model = (os.getenv("ANTHROPIC_MODEL") or "").strip()
        return env_model or None

    def _git_bash_path(self) -> Path | None:
        if os.name != "nt":
            return None
        return default_git_bash_path()

    def _missing_runtime_requirement(self) -> str | None:
        try:
            self._load_sdk()
        except ClaudeCallError as exc:
            return str(exc)

        if self._resolved_cli_path() is None:
            return (
                "未检测到可用的 Claude SDK 运行时。请先执行 `uv sync` 安装依赖，"
                "并配置 ANTHROPIC_AUTH_TOKEN/ANTHROPIC_API_KEY。"
            )

        if os.name != "nt":
            return None

        explicit_git_bash = (os.getenv(CLAUDE_CODE_GIT_BASH_PATH_ENV) or "").strip()
        if explicit_git_bash:
            path_obj = Path(explicit_git_bash).expanduser().resolve(strict=False)
            if path_obj.exists() and path_obj.is_file():
                return None
            return (
                f"Claude Code 在 Windows 上需要 Git Bash，但环境变量 {CLAUDE_CODE_GIT_BASH_PATH_ENV} "
                f"指向的文件不存在：{path_obj}"
            )

        if self._git_bash_path() is not None:
            return None

        return (
            "Claude Code on Windows requires git-bash (https://git-scm.com/downloads/win). "
            "Please install Git for Windows, or set environment variable "
            f"{CLAUDE_CODE_GIT_BASH_PATH_ENV}=C:\\Program Files\\Git\\bin\\bash.exe"
        )

    def unavailable_reason(self) -> str | None:
        return self._missing_runtime_requirement()

    def _build_sdk_env(self) -> dict[str, str]:
        env: dict[str, str] = {}

        for name in (
            "ANTHROPIC_BASE_URL",
            "ANTHROPIC_MODEL",
            "ANTHROPIC_AUTH_TOKEN",
            "ANTHROPIC_API_KEY",
            CLAUDE_CODE_GIT_BASH_PATH_ENV,
        ):
            value = os.getenv(name)
            if value:
                env[name] = value

        if "ANTHROPIC_API_KEY" not in env and "ANTHROPIC_AUTH_TOKEN" in env:
            env["ANTHROPIC_API_KEY"] = env["ANTHROPIC_AUTH_TOKEN"]

        if managed_runtime_enabled():
            env[RUNTIME_ROOT_ENV] = str(runtime_root())
            claude_config_dir = default_claude_config_dir()
            if claude_config_dir is not None:
                env[CLAUDE_CONFIG_DIR_ENV] = str(claude_config_dir)

        git_bash_path = self._git_bash_path()
        if git_bash_path is not None and CLAUDE_CODE_GIT_BASH_PATH_ENV not in env:
            env[CLAUDE_CODE_GIT_BASH_PATH_ENV] = str(git_bash_path)

        return env

    def _build_tools_option(self) -> Any:
        tools = (self.tools or "").strip()
        if not tools:
            return None
        if tools == "default":
            return {"type": "preset", "preset": "claude_code"}
        parsed = [item.strip() for item in tools.split(",") if item.strip()]
        return parsed or None

    def _sdk_mcp_servers(self) -> dict[str, Any] | str | Path:
        if not self.mcp_config:
            return {}
        if isinstance(self.mcp_config, dict):
            return dict(self.mcp_config.get("mcpServers", self.mcp_config))
        raw = str(self.mcp_config).strip()
        if not raw:
            return {}
        candidate = Path(raw).expanduser()
        if candidate.exists() and candidate.is_file():
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
            except Exception:
                return candidate
            if isinstance(data, dict):
                return dict(data.get("mcpServers", data))
            return candidate
        try:
            data = json.loads(raw)
        except Exception:
            return raw
        if isinstance(data, dict):
            return dict(data.get("mcpServers", data))
        return raw

    def _build_options(self, sdk: dict[str, Any], stderr_callback: Callable[[str], None]) -> Any:
        ClaudeAgentOptions = sdk["ClaudeAgentOptions"]
        extra_args: dict[str, str | None] = {}
        if self.agent:
            extra_args["agent"] = self.agent

        return ClaudeAgentOptions(
            tools=self._build_tools_option(),
            model=self._resolve_model(),
            effort=self.effort or None,
            cwd=self.workspace or None,
            add_dirs=[self.workspace] if self.workspace else [],
            cli_path=self._resolved_cli_path(),
            permission_mode="bypassPermissions",
            mcp_servers=self._sdk_mcp_servers(),
            include_partial_messages=self.progress_level in {"raw", "events"},
            extra_args=extra_args,
            env=self._build_sdk_env(),
            stderr=stderr_callback,
        )

    def ask_text(self, prompt: str, *, task_label: str | None = None) -> str:
        missing_requirement = self._missing_runtime_requirement()
        if missing_requirement:
            raise ClaudeCallError(missing_requirement)
        try:
            return anyio.run(self._ask_text_async, prompt, task_label)
        except ClaudeCallError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ClaudeCallError(str(exc)) from exc

    async def _ask_text_async(self, prompt: str, task_label: str | None) -> str:
        sdk = self._load_sdk()
        AssistantMessage = sdk["AssistantMessage"]
        ResultMessage = sdk["ResultMessage"]
        StreamEvent = sdk["StreamEvent"]
        SystemMessage = sdk["SystemMessage"]
        TaskNotificationMessage = sdk["TaskNotificationMessage"]
        TaskProgressMessage = sdk["TaskProgressMessage"]
        TextBlock = sdk["TextBlock"]
        ThinkingBlock = sdk["ThinkingBlock"]
        ToolUseBlock = sdk["ToolUseBlock"]
        query = sdk["query"]

        self._last_tool_calls = []
        self._last_tool_uses = []
        self._last_usage_summary = {}

        stderr_lines: list[str] = []

        def on_stderr(line: str) -> None:
            text = (line or "").rstrip()
            if text:
                stderr_lines.append(text)

        options = self._build_options(sdk, on_stderr)

        text_chunks: list[str] = []
        tool_calls: list[str] = []
        tool_uses: list[dict[str, Any]] = []
        usage_summary: dict[str, Any] = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_input_tokens": 0,
        }
        final_result = ""
        first_text_logged = False
        tool_count = 0
        current_phase = ""
        current_phase_obj: Phase | None = None
        phase_started_ts = time.time()
        phase_tool_count = 0
        phase_result_hint = ""
        label = (task_label or "审查任务").strip()
        start_ts = time.time()
        last_heartbeat = start_ts

        send_stream, receive_stream = anyio.create_memory_object_stream[tuple[str, Any]](100)

        async def producer() -> None:
            try:
                async for message in query(prompt=prompt, options=options):
                    await send_stream.send(("message", message))
            except Exception as exc:  # noqa: BLE001
                await send_stream.send(("error", exc))
            finally:
                await send_stream.aclose()

        if self.progress_level == "agent":
            self._emit_progress(f"[agent] {label}：已提交，开始处理", level="agent")
            self._emit_progress(
                "[agent] 思路：先识别文件角色，再提取硬性要求，然后逐条比对，最后整理报告",
                level="agent",
            )

        try:
            async with anyio.create_task_group() as task_group:
                task_group.start_soon(producer)
                with anyio.fail_after(self.timeout_sec):
                    while True:
                        item: tuple[str, Any] | None = None
                        with anyio.move_on_after(1):
                            try:
                                item = await receive_stream.receive()
                            except anyio.EndOfStream:
                                item = None

                        now = time.time()
                        if item is None:
                            if now - last_heartbeat >= self.progress_heartbeat_sec:
                                elapsed = int(now - start_ts)
                                if self.progress_level == "agent":
                                    if current_phase:
                                        self._emit_progress(
                                            f"[agent] 进行中：{current_phase}（已用时 {elapsed}s）",
                                            level="agent",
                                        )
                                    else:
                                        self._emit_progress(
                                            f"[agent] 进行中：等待模型响应（已用时 {elapsed}s）",
                                            level="agent",
                                        )
                                else:
                                    self._emit_progress(
                                        f"[claude-sdk] 仍在处理... 已等待 {elapsed}s",
                                        level="basic",
                                    )
                                last_heartbeat = now
                            if send_stream.statistics().open_send_streams == 0:
                                break
                            continue

                        kind, payload = item
                        if kind == "error":
                            raise payload

                        message = payload
                        if isinstance(message, TaskProgressMessage) and self.progress_level == "agent":
                            description = getattr(message, "description", "").strip()
                            if description:
                                self._emit_progress(f"[agent] 进行中：{description}", level="agent")
                        elif isinstance(message, TaskNotificationMessage) and self.progress_level == "agent":
                            summary = getattr(message, "summary", "").strip()
                            if summary:
                                self._emit_progress(f"[agent] 任务通知：{summary}", level="agent")
                        elif isinstance(message, SystemMessage):
                            if getattr(message, "subtype", "") == "init":
                                data = getattr(message, "data", {}) or {}
                                model_name = data.get("model", "")
                                session_id = data.get("session_id", "")
                                if self.progress_level == "agent":
                                    self._emit_progress(
                                        f"[agent] 会话已建立：session={session_id} model={model_name}",
                                        level="agent",
                                    )
                                else:
                                    self._emit_progress(
                                        f"[claude-sdk] 已启动 session={session_id} model={model_name}",
                                        level="basic",
                                    )
                        elif isinstance(message, AssistantMessage):
                            for item_block in getattr(message, "content", []):
                                if isinstance(item_block, ToolUseBlock):
                                    tool_count += 1
                                    tool_name = item_block.name
                                    tool_input = item_block.input
                                    tool_calls.append(str(tool_name))
                                    tool_uses.append({"name": str(tool_name), "input": tool_input})
                                    phase_obj = self._infer_phase_from_tool(tool_name, tool_input)
                                    phase_str = phase_obj.value

                                    if self.progress_level == "agent":
                                        if current_phase_obj and phase_obj.rank() < current_phase_obj.rank():
                                            phase_obj = current_phase_obj
                                            phase_str = phase_obj.value

                                        if phase_str != current_phase:
                                            if current_phase:
                                                self._report_phase_completion(
                                                    current_phase,
                                                    phase_started_ts,
                                                    phase_result_hint,
                                                    phase_tool_count,
                                                )
                                            current_phase = phase_str
                                            current_phase_obj = phase_obj
                                            phase_started_ts = time.time()
                                            phase_tool_count = 0
                                            phase_result_hint = ""
                                            self._emit_progress(
                                                f"[agent] 当前阶段：{phase_str}；下一步：{phase_obj.next_hint()}",
                                                level="agent",
                                            )
                                        phase_tool_count += 1
                                    self._emit_progress(
                                        f"[claude-sdk] 调用工具 #{tool_count}: {tool_name}",
                                        level="normal",
                                    )
                                    if self.progress_level == "detailed":
                                        input_text = json.dumps(tool_input, ensure_ascii=False, separators=(",", ":"))
                                        self._emit_progress(
                                            f"[claude-sdk] 工具参数: {input_text}",
                                            level="detailed",
                                        )
                                elif isinstance(item_block, ThinkingBlock):
                                    if self.progress_level == "detailed":
                                        thinking = str(item_block.thinking or "")
                                        if thinking and not re.search(r"时间\s*(不够|不足|有限|来不及)", thinking):
                                            self._emit_progress(
                                                f"[claude-sdk] thinking: {thinking}",
                                                level="detailed",
                                            )
                                elif isinstance(item_block, TextBlock):
                                    text = (item_block.text or "").strip()
                                    if not text:
                                        continue
                                    text_chunks.append(text)
                                    if self.progress_level == "agent" and current_phase and not phase_result_hint:
                                        phase_result_hint = f"收到输出片段：{self._short_text(text, 80)}"
                                    if self.progress_level == "detailed":
                                        self._emit_progress(
                                            f"[claude-sdk] 输出片段: {text}",
                                            level="detailed",
                                        )
                                    elif not first_text_logged:
                                        self._emit_progress(
                                            f"[claude-sdk] 收到输出片段: {self._short_text(text, 80)}",
                                            level="normal",
                                        )
                                        first_text_logged = True
                        elif isinstance(message, StreamEvent):
                            if isinstance(message.event, dict):
                                msg_obj = message.event.get("message")
                                if isinstance(msg_obj, dict):
                                    usage = msg_obj.get("usage")
                                    if isinstance(usage, dict):
                                        for key in ("input_tokens", "output_tokens", "cache_read_input_tokens"):
                                            value = usage.get(key)
                                            if isinstance(value, (int, float)):
                                                usage_summary[key] = max(int(value), int(usage_summary.get(key, 0) or 0))
                                usage = message.event.get("usage")
                                if isinstance(usage, dict):
                                    for key in ("input_tokens", "output_tokens", "cache_read_input_tokens"):
                                        value = usage.get(key)
                                        if isinstance(value, (int, float)):
                                            usage_summary[key] = max(int(value), int(usage_summary.get(key, 0) or 0))
                            raw_line = json.dumps(
                                {
                                    "type": "stream_event",
                                    "session_id": message.session_id,
                                    "event": message.event,
                                },
                                ensure_ascii=False,
                            )
                            if self.progress_level == "raw":
                                self._emit_progress(raw_line, level="raw")
                            elif self.progress_level == "events":
                                event_type = ""
                                if isinstance(message.event, dict):
                                    event_type = str(message.event.get("type", ""))
                                if event_type != "content_block_delta":
                                    self._emit_progress(raw_line, level="events")
                        elif isinstance(message, ResultMessage):
                            final_result = str(message.result or "").strip()
                            duration_ms = getattr(message, "duration_ms", None)
                            cost = getattr(message, "total_cost_usd", None)
                            duration_str = (
                                f"{(float(duration_ms) / 1000):.1f}s"
                                if isinstance(duration_ms, (int, float))
                                else "unknown"
                            )
                            cost_str = f"${float(cost):.4f}" if isinstance(cost, (int, float)) else "n/a"
                            if getattr(message, "is_error", False):
                                raise ClaudeCallError(final_result or "Claude SDK 返回错误结果。")
                            if self.progress_level == "agent":
                                if current_phase:
                                    self._report_phase_completion(
                                        current_phase,
                                        phase_started_ts,
                                        phase_result_hint,
                                        phase_tool_count,
                                    )
                                self._emit_progress(
                                    f"[agent] {label}：已完成，用时={duration_str}，cost={cost_str}",
                                    level="basic",
                                )
                                preview = self._short_text(final_result or " ".join(text_chunks), 120)
                                if preview:
                                    self._emit_progress(f"[agent] 输出摘要：{preview}", level="agent")
                            else:
                                self._emit_progress(
                                    f"[claude-sdk] 完成，用时={duration_str}，cost={cost_str}",
                                    level="basic",
                                )
                            if self.progress_level == "detailed":
                                self._emit_progress(
                                    f"[claude-sdk] 结果详情: turns={message.num_turns}, stop_reason={message.stop_reason}",
                                    level="detailed",
                                )

                        if now - last_heartbeat >= self.progress_heartbeat_sec:
                            last_heartbeat = now
        except TimeoutError as exc:
            raise ClaudeCallError(f"Claude 调用超时（>{self.timeout_sec}s）") from exc
        except ClaudeCallError:
            raise
        except Exception as exc:  # noqa: BLE001
            stderr_text = "\n".join(stderr_lines).strip()
            if _contains_timeout(exc):
                raise ClaudeCallError(f"Claude 调用超时（>{self.timeout_sec}s）") from exc
            detail = stderr_text or _exception_detail(exc)
            raise ClaudeCallError(f"Claude SDK 调用失败: {detail}") from exc

        out = final_result or "\n".join(text_chunks).strip()
        if not out:
            stderr_text = "\n".join(stderr_lines).strip()
            if stderr_text:
                raise ClaudeCallError(f"Claude SDK 返回空输出: {stderr_text}")
            raise ClaudeCallError("Claude SDK 返回空输出。")

        self._last_tool_calls = tool_calls
        self._last_tool_uses = tool_uses
        self._last_usage_summary = usage_summary
        return out

    def get_last_tool_calls(self) -> list[str]:
        return list(self._last_tool_calls)

    def get_last_tool_uses(self) -> list[dict[str, Any]]:
        return list(self._last_tool_uses)

    def get_last_usage_summary(self) -> dict[str, Any]:
        return dict(self._last_usage_summary)

    def ask_json(
        self,
        prompt: str,
        *,
        required_top_keys: list[str] | None = None,
        max_retries: int = 2,
        task_label: str | None = None,
    ) -> dict[str, Any] | list[Any]:
        required_top_keys = required_top_keys or []
        try:
            full_prompt = render_prompt("json_api_wrapper.md", task_prompt=prompt)
        except Exception:
            full_prompt = (
                "你是JSON API。只输出一个JSON对象或JSON数组，不要markdown，不要解释，不要前后缀。\n"
                "如果无法完成，输出 {\"error\": \"...\"}。\n\n"
                f"{prompt}"
            )
        last_error = ""
        for _ in range(max_retries + 1):
            raw = self.ask_text(full_prompt, task_label=task_label)
            try:
                data = extract_json_payload(raw)
                self._validate_json_top_keys(data, required_top_keys)
                return data
            except Exception as exc:  # noqa: BLE001
                last_error = f"{type(exc).__name__}: {exc}"
                try:
                    data = self.repair_json_text(
                        raw,
                        required_top_keys=required_top_keys,
                        parse_error=last_error,
                        task_label=task_label,
                    )
                    return data
                except Exception as repair_exc:  # noqa: BLE001
                    last_error = f"{last_error}; repair_failed={type(repair_exc).__name__}: {repair_exc}"
        raise ClaudeCallError(f"JSON解析失败: {last_error}")

    def repair_json_text(
        self,
        raw_text: str,
        *,
        required_top_keys: list[str] | None = None,
        parse_error: str = "",
        task_label: str | None = None,
    ) -> dict[str, Any] | list[Any]:
        required_top_keys = required_top_keys or []
        required_keys_text = "、".join(required_top_keys) if required_top_keys else "无强制字段要求"
        repair_prompt = (
            "下面是一段本应为合法JSON的模型输出，但它当前不是严格合法的JSON。\n"
            "请在不改变原始语义的前提下，将它修复成一个严格合法的JSON对象或JSON数组。\n"
            "要求：\n"
            "1. 只输出JSON，不要markdown，不要解释，不要前后缀。\n"
            "2. 不要删减已有字段，除非该字段本身语法残缺到无法保留。\n"
            f"3. 若输出为JSON对象，必须包含这些顶层字段：{required_keys_text}。\n"
            "4. 保留中文内容与证据文本，不要擅自改写业务含义。\n\n"
            f"[解析错误]\n{parse_error or '未提供'}\n\n"
            "[待修复原文]\n"
            f"{compact_text_for_prompt(raw_text, 16000)}"
        )
        repaired_raw = self.ask_text(
            repair_prompt,
            task_label=(f"{task_label}(JSON修复)" if task_label else "JSON修复"),
        )
        data = extract_json_payload(repaired_raw)
        self._validate_json_top_keys(data, required_top_keys)
        return data

    @staticmethod
    def _validate_json_top_keys(data: Any, required_top_keys: list[str]) -> None:
        if isinstance(data, dict):
            missing = [key for key in required_top_keys if key not in data]
            if missing:
                raise ClaudeCallError(f"缺少字段: {missing}")

    def available(self) -> bool:
        return self._missing_runtime_requirement() is None


def compact_text_for_prompt(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    head = text[: int(max_chars * 0.65)]
    tail = text[-int(max_chars * 0.35) :]
    return f"{head}\n\n...[TRUNCATED]...\n\n{tail}"


def prompt_safe_path(path: str) -> str:
    return str(Path(path)).replace("\\", "/")
