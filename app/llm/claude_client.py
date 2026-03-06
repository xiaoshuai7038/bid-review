from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import sys
import threading
import time
from typing import Any

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
    # 去掉 markdown 代码块包装。
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    # 先尝试整体解析。
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # 再从文本中截取首个 JSON 对象/数组。
    match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", cleaned)
    if not match:
        raise ClaudeCallError(f"未找到 JSON 结构，原始输出: {text[:500]}")
    return json.loads(match.group(1))


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
    progress_level: str = "agent"  # agent|basic|normal|detailed|events|raw
    workspace: str | None = None
    mcp_config: str | None = None
    _last_tool_calls: list[str] = field(default_factory=list, init=False, repr=False)
    _last_tool_uses: list[dict[str, Any]] = field(default_factory=list, init=False, repr=False)

    def _resolve_claude_bin(self) -> str:
        if self.claude_bin:
            return self.claude_bin
        env_bin = os.getenv("CLAUDE_BIN")
        if env_bin:
            self.claude_bin = env_bin
            return env_bin
        for cand in ("claude", "claude.cmd"):
            found = shutil.which(cand)
            if found:
                self.claude_bin = found
                return found
        # 常见 Windows npm 全局路径兜底。
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
        print(message, file=sys.stderr, flush=True)

    @staticmethod
    def _short_text(text: str, limit: int = 120) -> str:
        if len(text) <= limit:
            # 如果原始文本已经足够短，直接返回（先检查避免不必要的replace/strip）
            if "\n" not in text:
                return text.strip()
        one_line = text.replace("\n", " ").strip()
        if len(one_line) <= limit:
            return one_line
        return one_line[:limit] + "..."

    @staticmethod
    def _infer_phase_from_tool(tool_name: str, tool_input: Any) -> Phase:
        name = (tool_name or "").lower()
        # 避免不必要的json.dumps，直接从对象中提取关键字进行匹配
        inp_lower = ""
        if isinstance(tool_input, dict):
            # 只检查字典中的关键字符串值，避免序列化整个大对象
            for v in tool_input.values():
                if isinstance(v, str):
                    inp_lower += " " + v.lower()
        elif isinstance(tool_input, str):
            inp_lower = tool_input.lower()
        else:
            # 只有当上述方法不行时才fallback到json.dumps
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

    def _report_phase_completion(self, phase: str, phase_started_ts: float, hint: str, phase_tool_count_val: int) -> None:
        """提取阶段完成报告的公共逻辑，避免重复代码"""
        phase_elapsed = int(time.time() - phase_started_ts)
        hint = hint or f"调用工具 {phase_tool_count_val} 次"
        self._emit_progress(
            f"[agent] 阶段成果：{phase}（{phase_elapsed}s，{hint}）",
            level="agent",
        )

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

    def ask_text(self, prompt: str, *, task_label: str | None = None) -> str:
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
            raise ClaudeCallError("Claude 子进程管道初始化失败。")

        stdout_queue: "queue.Queue[str | None]" = queue.Queue()
        stderr_queue: "queue.Queue[str | None]" = queue.Queue()
        stdout_thread = threading.Thread(
            target=self._reader_thread, args=(proc.stdout, stdout_queue), daemon=True
        )
        stderr_thread = threading.Thread(
            target=self._reader_thread, args=(proc.stderr, stderr_queue), daemon=True
        )
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
                raise ClaudeCallError(f"Claude 调用超时（>{self.timeout_sec}s）")

            # 读取 stdout 事件行。
            line: str | None = None
            try:
                line = stdout_queue.get(timeout=1)
            except queue.Empty:
                pass

            if line is None:
                # reader 结束标记
                stdout_done = True
            elif line is not None:
                raw_line = line.rstrip("\n")
                raw_lines.append(raw_line)

                # 只在需要时解析 JSON（raw/events 模式直接输出不解析）
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
                        # 轻量级检查避免完整解析
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
                                        # 使用 Phase enum 的 rank 方法，避免重复字典查找
                                        if current_phase_obj and phase_obj.rank() < current_phase_obj.rank():
                                            phase_obj = current_phase_obj
                                            phase_str = str(phase_obj)

                                        if phase_str != current_phase:
                                            if current_phase:
                                                self._report_phase_completion(
                                                    current_phase, phase_started_ts, phase_result_hint, phase_tool_count
                                                )
                                            current_phase = phase_str
                                            current_phase_obj = phase_obj
                                            phase_started_ts = time.time()
                                            phase_tool_count = 0
                                            phase_result_hint = ""
                                            next_step = phase_obj.next_hint()
                                            self._emit_progress(
                                                f"[agent] 当前阶段：{phase_str}；下一步：{next_step}",
                                                level="agent",
                                            )
                                        phase_tool_count += 1
                                    self._emit_progress(
                                        f"[claude] 调用工具 #{tool_count}: {tool_name}",
                                        level="normal",
                                    )
                                    if self.progress_level == "detailed":
                                        try:
                                            input_text = json.dumps(
                                                tool_input, ensure_ascii=False, separators=(",", ":")
                                            )
                                        except Exception:
                                            input_text = str(tool_input)
                                        self._emit_progress(
                                            f"[claude] 工具参数: {input_text}",
                                            level="detailed",
                                        )
                                elif item_type == "thinking":
                                    if self.progress_level == "detailed":
                                        thinking = str(item.get("thinking") or "")
                                        # 过滤“时间不够/时间有限”类无效抱怨，避免污染日志。
                                        if re.search(r"时间\s*(不够|不足|有限|来不及)", thinking):
                                            continue
                                        if thinking:
                                            self._emit_progress(
                                                f"[claude] thinking: {thinking}",
                                                level="detailed",
                                            )
                                elif item_type == "text":
                                    text = (item.get("text") or "").strip()
                                    if text:
                                        text_chunks.append(text)
                                        if self.progress_level == "agent" and current_phase and not phase_result_hint:
                                            phase_result_hint = f"收到输出片段：{self._short_text(text, 80)}"
                                        if self.progress_level == "detailed":
                                            self._emit_progress(
                                                f"[claude] 输出片段: {text}",
                                                level="detailed",
                                            )
                                        elif not first_text_logged:
                                            preview = text.replace("\n", " ")[:80]
                                            self._emit_progress(
                                                f"[claude] 收到输出片段: {preview}",
                                                level="normal",
                                            )
                                            first_text_logged = True
                    elif event_type == "result":
                        final_result = str(event.get("result") or "").strip()
                        duration_ms = event.get("duration_ms")
                        cost = event.get("total_cost_usd")
                        duration_str = (
                            f"{(float(duration_ms) / 1000):.1f}s"
                            if isinstance(duration_ms, (int, float))
                            else "unknown"
                        )
                        cost_str = f"${float(cost):.4f}" if isinstance(cost, (int, float)) else "n/a"
                        if self.progress_level == "agent":
                            if current_phase:
                                self._report_phase_completion(
                                    current_phase, phase_started_ts, phase_result_hint, phase_tool_count
                                )
                            self._emit_progress(
                                f"[agent] {label}：已完成，用时={duration_str}，cost={cost_str}",
                                level="basic",
                            )
                            preview = self._short_text(final_result, 120)
                            if preview:
                                self._emit_progress(f"[agent] 输出摘要：{preview}", level="agent")
                        else:
                            self._emit_progress(
                                f"[claude] 完成，用时={duration_str}，cost={cost_str}",
                                level="basic",
                            )
                        if self.progress_level == "detailed":
                            turns = event.get("num_turns")
                            stop_reason = event.get("stop_reason")
                            self._emit_progress(
                                f"[claude] 结果详情: turns={turns}, stop_reason={stop_reason}",
                                level="detailed",
                            )

            # 持续收集 stderr
            stderr_drained, stderr_flag = self._drain_queue_nowait(stderr_queue)
            stderr_lines.extend(stderr_drained)
            if stderr_flag:
                stderr_done = True

            # 心跳日志
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
                    self._emit_progress(f"[claude] 仍在处理... 已等待 {elapsed}s", level="basic")
                last_heartbeat = now

            # 结束条件
            if stdout_done and stderr_done and proc.poll() is not None:
                break

        return_code = proc.wait(timeout=5)
        stderr_text = "".join(stderr_lines).strip()

        if return_code != 0:
            fallback_text = "\n".join(raw_lines).strip()
            raise ClaudeCallError(
                f"Claude 调用失败(return={return_code}): {stderr_text or fallback_text}"
            )

        out = final_result or "\n".join(text_chunks).strip() or "\n".join(raw_lines).strip()
        if not out:
            raise ClaudeCallError("Claude 返回空输出。")
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
                    missing = [k for k in required_top_keys if k not in data]
                    if missing:
                        raise ClaudeCallError(f"缺少字段: {missing}")
                return data
            except Exception as exc:  # noqa: BLE001
                last_error = f"{type(exc).__name__}: {exc}"
        raise ClaudeCallError(f"JSON解析失败: {last_error}")

    def available(self) -> bool:
        try:
            proc = subprocess.run(
                [self._resolve_claude_bin(), "--version"],
                capture_output=True,
                text=True,
                timeout=20,
            )
        except Exception:  # noqa: BLE001
            return False
        return proc.returncode == 0


def compact_text_for_prompt(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    head = text[: int(max_chars * 0.65)]
    tail = text[-int(max_chars * 0.35) :]
    return f"{head}\n\n...[TRUNCATED]...\n\n{tail}"


def prompt_safe_path(path: str) -> str:
    return str(Path(path)).replace("\\", "/")
