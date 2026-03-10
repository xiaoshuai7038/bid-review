from __future__ import annotations

import importlib.util
import json
import os
import re
import queue
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable

import anyio

from app.llm.prompt_store import render_prompt


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
    mcp_config: str | None = None
    progress_callback: Callable[[str, str], None] | None = None
    _last_tool_calls: list[str] = field(default_factory=list, init=False, repr=False)
    _last_tool_uses: list[dict[str, Any]] = field(default_factory=list, init=False, repr=False)

    def _resolve_claude_bin(self) -> str:
        if self.claude_bin:
            return str(Path(self.claude_bin).expanduser())
        bundled = self._bundled_cli_path()
        if bundled is not None:
            self.claude_bin = str(bundled)
            return self.claude_bin
        env_bin = os.getenv("CLAUDE_BIN")
        if env_bin:
            self.claude_bin = env_bin
            return env_bin
        for candidate in ("claude", "claude.cmd"):
            found = shutil.which(candidate)
            if found:
                self.claude_bin = found
                return found
        userprofile = os.getenv("USERPROFILE", "")
        fallback = Path(userprofile) / "AppData" / "Roaming" / "npm" / "claude.cmd"
        self.claude_bin = str(fallback)
        return self.claude_bin

    def _base_cmd(self, output_format: str = "text") -> list[str]:
        cmd = [
            self._resolve_claude_bin(),
            "--agent",
            self.agent,
            "--print",
            "--output-format",
            output_format,
            "--no-session-persistence",
            "--permission-mode",
            "dontAsk",
            "--dangerously-skip-permissions",
        ]
        if self.model:
            cmd.extend(["--model", self.model])
        if self.effort:
            cmd.extend(["--effort", self.effort])
        if self.tools:
            cmd.extend(["--tools", self.tools])
        if self.workspace:
            cmd.extend(["--add-dir", self.workspace])
        if self.mcp_config:
            cmd.extend(["--mcp-config", self.mcp_config])
        if output_format == "stream-json":
            cmd.append("--include-partial-messages")
        return cmd

    @staticmethod
    def _reader_thread(stream: Any, out_queue: "queue.Queue[str | None]") -> None:
        try:
            for line in iter(stream.readline, ""):
                out_queue.put(line)
        finally:
            out_queue.put(None)

    @staticmethod
    def _drain_queue_nowait(src_queue: "queue.Queue[str | None]") -> tuple[list[str], bool]:
        lines: list[str] = []
        done = False
        while True:
            try:
                item = src_queue.get_nowait()
            except queue.Empty:
                break
            if item is None:
                done = True
            else:
                lines.append(item)
        return lines, done

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
        package_dir = self._sdk_package_dir()
        if package_dir is None:
            return None
        cli_name = "claude.exe" if os.name == "nt" else "claude"
        bundled = package_dir / "_bundled" / cli_name
        if bundled.exists() and bundled.is_file():
            return bundled
        return None

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

    def _build_sdk_env(self) -> dict[str, str]:
        env: dict[str, str] = {}

        for name in ("ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY"):
            value = os.getenv(name)
            if value:
                env[name] = value

        if "ANTHROPIC_API_KEY" not in env and "ANTHROPIC_AUTH_TOKEN" in env:
            env["ANTHROPIC_API_KEY"] = env["ANTHROPIC_AUTH_TOKEN"]

        return env

    def _build_tools_option(self) -> Any:
        tools = (self.tools or "").strip()
        if not tools:
            return None
        if tools == "default":
            return {"type": "preset", "preset": "claude_code"}
        parsed = [item.strip() for item in tools.split(",") if item.strip()]
        return parsed or None

    def _build_options(self, sdk: dict[str, Any], stderr_callback: Callable[[str], None]) -> Any:
        ClaudeAgentOptions = sdk["ClaudeAgentOptions"]
        extra_args: dict[str, str | None] = {}
        if self.agent:
            extra_args["agent"] = self.agent

        mcp_servers: dict[str, Any] | str | Path
        if self.mcp_config:
            mcp_servers = self.mcp_config
        else:
            mcp_servers = {}

        return ClaudeAgentOptions(
            tools=self._build_tools_option(),
            model=self._resolve_model(),
            effort=self.effort or None,
            cwd=self.workspace or None,
            add_dirs=[self.workspace] if self.workspace else [],
            cli_path=self.claude_bin or None,
            permission_mode="bypassPermissions",
            mcp_servers=mcp_servers,
            include_partial_messages=self.progress_level in {"raw", "events"},
            extra_args=extra_args,
            env=self._build_sdk_env(),
            stderr=stderr_callback,
        )

    def ask_text(self, prompt: str, *, task_label: str | None = None) -> str:
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

        stderr_lines: list[str] = []

        def on_stderr(line: str) -> None:
            text = (line or "").rstrip()
            if text:
                stderr_lines.append(text)

        options = self._build_options(sdk, on_stderr)

        text_chunks: list[str] = []
        tool_calls: list[str] = []
        tool_uses: list[dict[str, Any]] = []
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
        return out

    def _ask_text_via_cli(self, prompt: str, *, task_label: str | None = None) -> str:
        self._last_tool_calls = []
        self._last_tool_uses = []
        cmd = self._base_cmd("stream-json")
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=self.workspace or None,
            bufsize=1,
        )

        if proc.stdin is None or proc.stdout is None or proc.stderr is None:
            proc.kill()
            raise ClaudeCallError("Claude CLI 子进程管道初始化失败。")

        stdout_queue: "queue.Queue[str | None]" = queue.Queue()
        stderr_queue: "queue.Queue[str | None]" = queue.Queue()
        stdout_thread = threading.Thread(target=self._reader_thread, args=(proc.stdout, stdout_queue), daemon=True)
        stderr_thread = threading.Thread(target=self._reader_thread, args=(proc.stderr, stderr_queue), daemon=True)
        stdout_thread.start()
        stderr_thread.start()

        proc.stdin.write(prompt)
        proc.stdin.close()

        start_ts = time.time()
        last_heartbeat = start_ts
        raw_lines: list[str] = []
        stderr_lines: list[str] = []
        stdout_done = False
        stderr_done = False
        final_result = ""
        text_chunks: list[str] = []
        tool_count = 0
        tool_calls: list[str] = []
        tool_uses: list[dict[str, Any]] = []
        first_text_logged = False
        current_phase = ""
        current_phase_obj: Phase | None = None
        phase_started_ts = start_ts
        phase_tool_count = 0
        phase_result_hint = ""
        label = (task_label or "审查任务").strip()
        needs_json_parsing = self.progress_level not in {"raw", "events"}

        if self.progress_level == "agent":
            self._emit_progress(f"[agent] {label}：已提交，开始处理", level="agent")
            self._emit_progress(
                "[agent] 思路：先识别文件角色，再提取硬性要求，然后逐条比对，最后整理报告",
                level="agent",
            )

        while True:
            now = time.time()
            if now - start_ts > self.timeout_sec:
                proc.kill()
                raise ClaudeCallError(f"Claude CLI 调用超时（>{self.timeout_sec}s）")

            line: str | None = None
            try:
                line = stdout_queue.get(timeout=1)
            except queue.Empty:
                pass

            if line is None:
                stdout_done = True
            elif line is not None:
                raw_line = line.rstrip("\n")
                raw_lines.append(raw_line)
                event = None
                if needs_json_parsing:
                    try:
                        event = json.loads(raw_line)
                    except Exception:
                        pass
                else:
                    if self.progress_level == "raw":
                        self._emit_progress(raw_line, level="raw")
                    elif self.progress_level == "events":
                        if '"type":"stream_event"' not in raw_line or '"content_block_delta"' not in raw_line:
                            self._emit_progress(raw_line, level="events")

                if isinstance(event, dict):
                    event_type = event.get("type")
                    if event_type == "system" and event.get("subtype") == "init":
                        model_name = event.get("model", "")
                        session_id = event.get("session_id", "")
                        if self.progress_level == "agent":
                            self._emit_progress(
                                f"[agent] 会话已建立：session={session_id} model={model_name}",
                                level="agent",
                            )
                        else:
                            self._emit_progress(
                                f"[claude] 已启动 session={session_id} model={model_name}",
                                level="basic",
                            )
                    elif event_type == "assistant":
                        msg = event.get("message", {})
                        contents = msg.get("content", [])
                        if isinstance(contents, list):
                            for item in contents:
                                if not isinstance(item, dict):
                                    continue
                                item_type = item.get("type")
                                if item_type == "tool_use":
                                    tool_count += 1
                                    tool_name = item.get("name", "tool")
                                    tool_calls.append(str(tool_name))
                                    tool_input = item.get("input")
                                    tool_uses.append({"name": str(tool_name), "input": tool_input})
                                    phase_obj = self._infer_phase_from_tool(tool_name, tool_input)
                                    phase_str = str(phase_obj)
                                    if self.progress_level == "agent":
                                        if current_phase_obj and phase_obj.rank() < current_phase_obj.rank():
                                            phase_obj = current_phase_obj
                                            phase_str = str(phase_obj)
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
                                        f"[claude] 调用工具 #{tool_count}: {tool_name}",
                                        level="normal",
                                    )
                                elif item_type == "text":
                                    text = str(item.get("text") or "").strip()
                                    if not text:
                                        continue
                                    text_chunks.append(text)
                                    if self.progress_level == "agent" and current_phase and not phase_result_hint:
                                        phase_result_hint = f"收到输出片段：{self._short_text(text, 80)}"
                                    elif not first_text_logged:
                                        self._emit_progress(
                                            f"[claude] 收到输出片段: {self._short_text(text, 80)}",
                                            level="normal",
                                        )
                                        first_text_logged = True
                    elif event_type == "result":
                        subtype = str(event.get("subtype", "") or "")
                        if subtype == "success":
                            result = event.get("result")
                            if isinstance(result, str):
                                final_result = result.strip()
                        elif subtype == "error":
                            raise ClaudeCallError(str(event.get("result") or event.get("error") or "Claude CLI 返回错误结果。"))

            stderr_now, stderr_finished = self._drain_queue_nowait(stderr_queue)
            if stderr_now:
                stderr_lines.extend([line.rstrip("\n") for line in stderr_now if line is not None])
            if stderr_finished:
                stderr_done = True

            if now - last_heartbeat >= self.progress_heartbeat_sec:
                elapsed = int(now - start_ts)
                if self.progress_level == "agent":
                    if current_phase:
                        self._emit_progress(f"[agent] 进行中：{current_phase}（已用时 {elapsed}s）", level="agent")
                    else:
                        self._emit_progress(f"[agent] 进行中：等待模型响应（已用时 {elapsed}s）", level="agent")
                else:
                    self._emit_progress(f"[claude] 仍在处理... 已等待 {elapsed}s", level="basic")
                last_heartbeat = now

            if stdout_done and stderr_done:
                break

        returncode = proc.wait(timeout=5)
        stderr_text = "\n".join([line for line in stderr_lines if line.strip()]).strip()
        if returncode != 0:
            raise ClaudeCallError(stderr_text or f"Claude CLI 退出码异常: {returncode}")

        out = final_result or "\n".join(text_chunks).strip()
        if not out:
            raise ClaudeCallError(stderr_text or "Claude CLI 返回空输出。")

        self._last_tool_calls = tool_calls
        self._last_tool_uses = tool_uses
        return out

    def get_last_tool_calls(self) -> list[str]:
        return list(self._last_tool_calls)

    def get_last_tool_uses(self) -> list[dict[str, Any]]:
        return list(self._last_tool_uses)

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
                if isinstance(data, dict):
                    missing = [key for key in required_top_keys if key not in data]
                    if missing:
                        raise ClaudeCallError(f"缺少字段: {missing}")
                return data
            except Exception as exc:  # noqa: BLE001
                last_error = f"{type(exc).__name__}: {exc}"
        raise ClaudeCallError(f"JSON解析失败: {last_error}")

    def available(self) -> bool:
        try:
            self._load_sdk()
        except ClaudeCallError:
            return False
        if self.claude_bin:
            return Path(self.claude_bin).expanduser().is_file()
        if self._bundled_cli_path() is not None:
            return True
        return shutil.which("claude") is not None


def compact_text_for_prompt(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    head = text[: int(max_chars * 0.65)]
    tail = text[-int(max_chars * 0.35) :]
    return f"{head}\n\n...[TRUNCATED]...\n\n{tail}"


def prompt_safe_path(path: str) -> str:
    return str(Path(path)).replace("\\", "/")
