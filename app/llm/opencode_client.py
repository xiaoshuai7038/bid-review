from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
import sys
import threading
import time
from typing import Any

from app.llm.claude_client import ProgressLevel, extract_json_payload
from app.llm.prompt_store import render_prompt


class OpenCodeCallError(RuntimeError):
    pass


@dataclass
class OpenCodeClient:
    opencode_bin: str | None = None
    model: str | None = None
    timeout_sec: int = 240
    show_progress: bool = True
    progress_heartbeat_sec: int = 20
    progress_level: str = "agent"  # agent|basic|normal|detailed|events|raw
    workspace: str | None = None
    agent: str | None = None
    api_key: str | None = None
    api_url: str | None = None
    provider_id: str = "volcengine"
    mcp_config: str | None = None
    _last_tool_calls: list[str] = field(default_factory=list, init=False, repr=False)
    _last_tool_uses: list[dict[str, Any]] = field(default_factory=list, init=False, repr=False)

    def _resolve_opencode_bin(self) -> str:
        if self.opencode_bin:
            return self.opencode_bin
        env_bin = os.getenv("OPENCODE_BIN")
        if env_bin:
            self.opencode_bin = env_bin
            return env_bin
        for cand in ("opencode", "opencode.cmd"):
            found = shutil.which(cand)
            if found:
                self.opencode_bin = found
                return found
        userprofile = os.getenv("USERPROFILE", "")
        fallback = Path(userprofile) / "AppData" / "Roaming" / "npm" / "opencode.cmd"
        self.opencode_bin = str(fallback)
        return self.opencode_bin

    def _resolve_model(self) -> str | None:
        model = (self.model or "").strip()
        if not model:
            return None
        if "/" in model:
            return model
        provider = (self.provider_id or "").strip()
        return f"{provider}/{model}" if provider else model

    def _resolve_claude_mcp_dir(self) -> Path:
        configured = os.getenv("BID_REVIEW_CLAUDE_MCP_DIR")
        if configured:
            return Path(configured).expanduser()
        return Path.home() / ".claude" / "mcp"

    def _project_allowed_mcp_servers(self) -> set[str]:
        workspace = Path(self.workspace).resolve(strict=False) if self.workspace else Path.cwd()
        settings_path = workspace / ".claude" / "settings.local.json"
        if not settings_path.exists():
            return set()
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return set()
        permissions = data.get("permissions")
        if not isinstance(permissions, dict):
            return set()
        allow_rules = permissions.get("allow")
        if not isinstance(allow_rules, list):
            return set()
        servers: set[str] = set()
        for item in allow_rules:
            text = str(item or "").strip()
            match = re.match(r"^mcp__([^_]+(?:-[^_]+)*)__", text)
            if match:
                servers.add(match.group(1))
        return servers

    @staticmethod
    def _json_dict_or_none(raw_text: str) -> dict[str, Any] | None:
        text = (raw_text or "").strip()
        if not text:
            return None
        try:
            data = json.loads(text)
        except Exception:  # noqa: BLE001
            return None
        return data if isinstance(data, dict) else None

    def _load_json_config_source(self, source: str | None) -> tuple[dict[str, Any] | None, Path | None]:
        raw = (source or "").strip()
        if not raw:
            return None, None
        candidate = Path(raw).expanduser()
        if candidate.exists() and candidate.is_file():
            try:
                text = candidate.read_text(encoding="utf-8")
            except Exception:  # noqa: BLE001
                return None, candidate
            return self._json_dict_or_none(text), candidate
        return self._json_dict_or_none(raw), None

    @staticmethod
    def _normalize_opencode_mcp_entry(entry: dict[str, Any]) -> dict[str, Any] | None:
        normalized = dict(entry)
        command = normalized.get("command")
        if isinstance(command, str):
            normalized["command"] = [command]
        elif isinstance(command, list):
            normalized["command"] = [str(x) for x in command if str(x or "").strip()]
        else:
            return None
        if not normalized["command"]:
            return None
        normalized.setdefault("type", "local")
        normalized.setdefault("enabled", True)
        environment = normalized.get("environment")
        if isinstance(environment, dict):
            normalized["environment"] = {
                str(k): str(v) for k, v in environment.items() if v is not None
            }
        elif "environment" in normalized:
            normalized.pop("environment", None)
        return normalized

    @staticmethod
    def _convert_claude_mcp_entry(entry: dict[str, Any]) -> dict[str, Any] | None:
        command = str(entry.get("command") or "").strip()
        if not command:
            return None
        args_raw = entry.get("args")
        args = [str(x) for x in args_raw] if isinstance(args_raw, list) else []
        converted: dict[str, Any] = {
            "type": "local",
            "enabled": True,
            "command": [command, *args],
        }
        env_raw = entry.get("env")
        if isinstance(env_raw, dict) and env_raw:
            converted["environment"] = {
                str(k): str(v) for k, v in env_raw.items() if v is not None
            }
        timeout_raw = entry.get("timeout")
        if isinstance(timeout_raw, (int, float)) and timeout_raw > 0:
            converted["timeout"] = int(timeout_raw if timeout_raw >= 1000 else timeout_raw * 1000)
        return converted

    def _load_mcp_from_explicit_config(self) -> dict[str, Any]:
        data, source_path = self._load_json_config_source(self.mcp_config)
        if not data:
            return {}
        if isinstance(data.get("mcp"), dict):
            out: dict[str, Any] = {}
            for name, entry in data["mcp"].items():
                if not isinstance(entry, dict):
                    continue
                normalized = self._normalize_opencode_mcp_entry(entry)
                if normalized:
                    out[str(name)] = normalized
            return out
        if isinstance(data.get("mcpServers"), dict):
            out = {}
            for name, entry in data["mcpServers"].items():
                if not isinstance(entry, dict):
                    continue
                converted = self._convert_claude_mcp_entry(entry)
                if converted:
                    out[str(name)] = converted
            return out
        if source_path and source_path.suffix.lower() == ".json":
            converted = self._convert_claude_mcp_entry(data)
            if converted:
                return {source_path.stem: converted}
        return {}

    def _discover_claude_mcp_servers(self) -> dict[str, Any]:
        mcp_dir = self._resolve_claude_mcp_dir()
        if not mcp_dir.exists() or not mcp_dir.is_dir():
            return {}
        allowed_servers = self._project_allowed_mcp_servers()
        discovered: dict[str, Any] = {}
        for path in sorted(mcp_dir.glob("*.json")):
            server_name = path.stem
            if allowed_servers and server_name not in allowed_servers:
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            if not isinstance(data, dict):
                continue
            converted = self._convert_claude_mcp_entry(data)
            if converted:
                discovered[server_name] = converted
        return discovered

    def _build_mcp_section(self) -> dict[str, Any]:
        explicit = self._load_mcp_from_explicit_config()
        discovered = self._discover_claude_mcp_servers()
        if not explicit and not discovered:
            return {}
        return {**discovered, **explicit}

    def _build_runtime_env(self) -> dict[str, str]:
        env = dict(os.environ)
        provider = (self.provider_id or "").strip()
        model = self._resolve_model()
        model_name = ""
        if model and "/" in model:
            maybe_provider, model_name = model.split("/", 1)
            if not provider:
                provider = maybe_provider.strip()
        elif model:
            model_name = model
        provider = provider or "ark"

        mcp_section = self._build_mcp_section()
        need_inline_config = bool(self.api_key or self.api_url or mcp_section)
        if not need_inline_config:
            return env

        provider_cfg: dict[str, Any] = {
            "npm": "@ai-sdk/openai-compatible",
            "name": provider,
        }
        options: dict[str, Any] = {}
        if self.api_url:
            options["baseURL"] = self.api_url
        if self.api_key:
            env_key_name = "BID_REVIEW_OPENCODE_API_KEY"
            env[env_key_name] = self.api_key
            options["apiKey"] = f"{{env:{env_key_name}}}"
        if options:
            provider_cfg["options"] = options
        if model_name:
            provider_cfg["models"] = {model_name: {"name": model_name}}

        config_obj = self._json_dict_or_none(env.get("OPENCODE_CONFIG_CONTENT", "")) or {}
        config_obj.setdefault("$schema", "https://opencode.ai/config.json")
        if self.api_key or self.api_url:
            provider_section = config_obj.get("provider")
            if not isinstance(provider_section, dict):
                provider_section = {}
                config_obj["provider"] = provider_section
            provider_section[provider] = provider_cfg
        if mcp_section:
            mcp_config = config_obj.get("mcp")
            if not isinstance(mcp_config, dict):
                mcp_config = {}
                config_obj["mcp"] = mcp_config
            mcp_config.update(mcp_section)
        env["OPENCODE_CONFIG_CONTENT"] = json.dumps(config_obj, ensure_ascii=False)
        return env

    def _base_cmd(self) -> list[str]:
        cmd = [self._resolve_opencode_bin(), "run", "--format", "json"]
        model = self._resolve_model()
        if model:
            cmd.extend(["--model", model])
        if self.agent:
            cmd.extend(["--agent", self.agent])
        if self.workspace:
            cmd.extend(["--dir", self.workspace])
        return cmd

    def _prompt_cmd(self, prompt: str) -> list[str]:
        cmd = self._base_cmd()
        cmd.append(prompt)
        return cmd

    @staticmethod
    def _extract_error_message(event: dict[str, Any]) -> str:
        error = event.get("error")
        if isinstance(error, dict):
            data = error.get("data")
            if isinstance(data, dict):
                message = str(data.get("message") or "").strip()
                if message:
                    return message
            message = str(error.get("message") or "").strip()
            if message:
                return message
            name = str(error.get("name") or "").strip()
            if name:
                return name
        return "未知错误"

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
        cmd = self._prompt_cmd(prompt)
        env = self._build_runtime_env()
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=self.workspace or None,
            env=env,
            bufsize=1,
        )

        if proc.stdout is None or proc.stderr is None:
            proc.kill()
            raise OpenCodeCallError("OpenCode 子进程管道初始化失败。")

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

        start_ts = time.time()
        last_heartbeat = start_ts
        raw_lines: list[str] = []
        stderr_lines: list[str] = []
        stdout_done = False
        stderr_done = False
        text_chunks: list[str] = []
        tool_calls: list[str] = []
        tool_uses: list[dict[str, Any]] = []
        first_text_logged = False
        label = (task_label or "审查任务").strip()
        if self.progress_level == "agent":
            self._emit_progress(f"[agent] {label}：已提交到 OpenCode，开始处理", level="agent")

        while True:
            now = time.time()
            if now - start_ts > self.timeout_sec:
                proc.kill()
                raise OpenCodeCallError(f"OpenCode 调用超时（>{self.timeout_sec}s）")

            got_stdout_item = False
            line: str | None = None
            try:
                line = stdout_queue.get(timeout=1)
                got_stdout_item = True
            except queue.Empty:
                got_stdout_item = False

            if got_stdout_item and line is None:
                stdout_done = True
            elif got_stdout_item and line is not None:
                raw_line = line.rstrip("\n")
                raw_lines.append(raw_line)
                event: dict[str, Any] | None = None
                try:
                    parsed = json.loads(raw_line)
                    if isinstance(parsed, dict):
                        event = parsed
                except Exception:
                    if self.progress_level == "raw":
                        self._emit_progress(raw_line, level="raw")
                    elif self.progress_level == "events":
                        self._emit_progress(raw_line, level="events")

                if event:
                    event_type = str(event.get("type", "")).lower()
                    if self.progress_level == "events":
                        self._emit_progress(raw_line, level="events")
                    if event_type == "error":
                        try:
                            proc.kill()
                        except Exception:  # noqa: BLE001
                            pass
                        raise OpenCodeCallError(
                            f"OpenCode 返回错误事件: {self._extract_error_message(event)}"
                        )
                    part = event.get("part", {})
                    if not isinstance(part, dict):
                        part = {}
                    if event_type == "tool_use":
                        tool_name = str(part.get("tool", "tool"))
                        state = part.get("state", {})
                        if not isinstance(state, dict):
                            state = {}
                        tool_input = state.get("input")
                        tool_calls.append(tool_name)
                        tool_uses.append({"name": tool_name, "input": tool_input})
                        self._emit_progress(
                            f"[opencode] 调用工具 #{len(tool_calls)}: {tool_name}",
                            level="normal",
                        )
                        if self.progress_level == "detailed":
                            try:
                                input_text = json.dumps(tool_input, ensure_ascii=False, separators=(",", ":"))
                            except Exception:
                                input_text = str(tool_input)
                            self._emit_progress(f"[opencode] 工具参数: {input_text}", level="detailed")
                    elif event_type == "text":
                        text = str(part.get("text") or "").strip()
                        if text:
                            text_chunks.append(text)
                            if self.progress_level == "detailed":
                                self._emit_progress(f"[opencode] 输出片段: {text}", level="detailed")
                            elif not first_text_logged:
                                preview = text.replace("\n", " ")[:80]
                                self._emit_progress(f"[opencode] 收到输出片段: {preview}", level="normal")
                                first_text_logged = True
                    elif event_type == "step_finish" and self.progress_level == "agent":
                        reason = str(part.get("reason", "") or "stop")
                        self._emit_progress(f"[agent] {label}：步骤完成，reason={reason}", level="agent")

            stderr_drained, stderr_flag = self._drain_queue_nowait(stderr_queue)
            stderr_lines.extend(stderr_drained)
            if stderr_flag:
                stderr_done = True

            if now - last_heartbeat >= self.progress_heartbeat_sec:
                elapsed = int(now - start_ts)
                if self.progress_level == "agent":
                    self._emit_progress(f"[agent] 进行中：OpenCode 处理中（已用时 {elapsed}s）", level="agent")
                else:
                    self._emit_progress(f"[opencode] 仍在处理... 已等待 {elapsed}s", level="basic")
                last_heartbeat = now

            if stdout_done and stderr_done and proc.poll() is not None:
                break

        return_code = proc.wait(timeout=5)
        stderr_text = "".join(stderr_lines).strip()
        if return_code != 0:
            fallback_text = "\n".join(raw_lines).strip()
            raise OpenCodeCallError(
                f"OpenCode 调用失败(return={return_code}): {stderr_text or fallback_text}"
            )

        out = "\n".join(text_chunks).strip() or "\n".join(raw_lines).strip()
        if not out:
            raise OpenCodeCallError("OpenCode 返回空输出。")
        self._last_tool_calls = tool_calls
        self._last_tool_uses = tool_uses
        return out

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
                        raise OpenCodeCallError(f"缺少字段: {missing}")
                return data
            except Exception as exc:  # noqa: BLE001
                last_error = f"{type(exc).__name__}: {exc}"
        raise OpenCodeCallError(f"JSON解析失败: {last_error}")

    def get_last_tool_calls(self) -> list[str]:
        return list(self._last_tool_calls)

    def get_last_tool_uses(self) -> list[dict[str, Any]]:
        return list(self._last_tool_uses)

    def available(self) -> bool:
        try:
            proc = subprocess.run(
                [self._resolve_opencode_bin(), "--version"],
                capture_output=True,
                text=True,
                timeout=20,
            )
        except Exception:  # noqa: BLE001
            return False
        return proc.returncode == 0
