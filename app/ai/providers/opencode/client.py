from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
import sys
import threading
import time
from typing import Any, Callable

from app.ai.core.json_output import extract_json_payload
from app.ai.core.progress import ProgressLevel
from app.ai.prompts.store import render_prompt
from app.runtime_paths import (
    OPENCODE_DATA_DIR_ENV,
    RUNTIME_ROOT_ENV,
    default_bundled_node_exe,
    default_bundled_opencode_runtime_root,
    default_opencode_data_dir,
    managed_runtime_enabled,
    opencode_data_directory_enabled,
    runtime_root,
)


LOCAL_OPENCODE_API_KEY_ENV = "BID_REVIEW_OPENCODE_API_KEY"
NODE_BIN_ENV = "BID_REVIEW_NODE_BIN"
OPENCODE_CONFIG_CONTENT_ENV = "OPENCODE_CONFIG_CONTENT"
OPENCODE_RUNTIME_ROOT_ENV = "BID_REVIEW_OPENCODE_RUNTIME_ROOT"
OPENCODE_BIN_PATH_ENV = "OPENCODE_BIN_PATH"


class OpenCodeCallError(RuntimeError):
    pass


def _compact_text_for_prompt(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    head = text[: int(max_chars * 0.65)]
    tail = text[-int(max_chars * 0.35) :]
    return f"{head}\n\n...[TRUNCATED]...\n\n{tail}"


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
    runtime_data_dir: str | None = None
    progress_callback: Callable[[str, str], None] | None = None
    _last_tool_calls: list[str] = field(default_factory=list, init=False, repr=False)
    _last_tool_uses: list[dict[str, Any]] = field(default_factory=list, init=False, repr=False)
    _last_usage_summary: dict[str, Any] = field(default_factory=dict, init=False, repr=False)
    _last_unavailable_reason: str | None = field(default=None, init=False, repr=False)

    def _repo_root(self) -> Path:
        return Path(__file__).resolve().parents[4]

    def _runtime_root_path(self) -> Path:
        bundled = default_bundled_opencode_runtime_root()
        if bundled is not None:
            return bundled
        return self._repo_root()

    def _bridge_script_path(self) -> Path:
        bundled = default_bundled_opencode_runtime_root()
        if bundled is not None:
            return bundled / "bridge" / "opencode_sdk_bridge.mjs"
        return self._repo_root() / "app" / "ai" / "providers" / "opencode" / "bridge" / "opencode_sdk_bridge.mjs"

    def _node_modules_bin_dir(self) -> Path:
        return self._runtime_root_path() / "node_modules" / ".bin"

    def _local_opencode_bin_path(self) -> Path:
        bin_name = "opencode.cmd" if os.name == "nt" else "opencode"
        return self._node_modules_bin_dir() / bin_name

    def _runtime_binary_candidates(self) -> list[Path]:
        root = self._runtime_root_path() / "node_modules"
        exe_name = "opencode.exe" if os.name == "nt" else "opencode"
        if os.name == "nt":
            package_names = [
                "opencode-windows-x64",
                "opencode-windows-x64-baseline",
                "opencode-windows-arm64",
            ]
        else:
            package_names = [
                "opencode-linux-x64",
                "opencode-linux-arm64",
                "opencode-darwin-x64",
                "opencode-darwin-arm64",
            ]
        return [(root / package / "bin" / exe_name) for package in package_names]

    def _resolved_runtime_binary_path(self) -> Path | None:
        for candidate in self._runtime_binary_candidates():
            if candidate.exists() and candidate.is_file():
                return candidate.resolve()
        return None

    def _resolve_node_bin(self) -> str | None:
        explicit = (os.getenv(NODE_BIN_ENV) or "").strip()
        if explicit:
            candidate = Path(explicit).expanduser().resolve(strict=False)
            if candidate.exists() and candidate.is_file():
                return str(candidate)
            return None
        bundled = default_bundled_node_exe()
        if bundled is not None:
            return str(bundled)
        return shutil.which("node")

    def _use_legacy_cli(self) -> bool:
        return bool((self.opencode_bin or "").strip())

    def _resolved_model_parts(self) -> tuple[str | None, str | None]:
        model = self._resolve_model()
        if not model:
            return None, None
        if "/" in model:
            provider, model_name = model.split("/", 1)
            return provider.strip() or None, model_name.strip() or None
        provider = (self.provider_id or "").strip()
        return provider or None, model

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

    def _sdk_provider_runtime_options(self) -> dict[str, Any]:
        chunk_timeout_ms = max(int(max(self.timeout_sec, 1) * 1000), 600000)
        return {
            "timeout": False,
            "chunkTimeout": chunk_timeout_ms,
            "maxRetries": 4,
        }

    def _sdk_bridge_retry_count(self) -> int:
        if self.timeout_sec >= 3600:
            return 4
        if self.timeout_sec >= 1800:
            return 3
        if self.timeout_sec >= 900:
            return 2
        return 1

    @staticmethod
    def _hidden_windows_subprocess_kwargs() -> dict[str, Any]:
        if os.name != "nt":
            return {}
        kwargs: dict[str, Any] = {}
        creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0) or 0)
        if creationflags:
            kwargs["creationflags"] = creationflags
        if hasattr(subprocess, "STARTUPINFO"):
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= int(getattr(subprocess, "STARTF_USESHOWWINDOW", 0) or 0)
            startupinfo.wShowWindow = int(getattr(subprocess, "SW_HIDE", 0) or 0)
            kwargs["startupinfo"] = startupinfo
        return kwargs

    def _build_runtime_env(self, *, force_provider_options: bool = False) -> dict[str, str]:
        env = dict(os.environ)
        managed_runtime = managed_runtime_enabled()
        if managed_runtime:
            env[RUNTIME_ROOT_ENV] = str(runtime_root())
        api_key = self.api_key or env.get(LOCAL_OPENCODE_API_KEY_ENV) or env.get("OPENCODE_API_KEY")
        if api_key:
            env[LOCAL_OPENCODE_API_KEY_ENV] = api_key
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
        need_inline_config = bool(self.api_key or self.api_url or mcp_section or force_provider_options)
        if not need_inline_config:
            data_dir = default_opencode_data_dir()
            if managed_runtime and opencode_data_directory_enabled() and data_dir is not None:
                env[OPENCODE_DATA_DIR_ENV] = str(data_dir)
            return env

        provider_cfg: dict[str, Any] = {
            "npm": "@ai-sdk/openai-compatible",
            "name": provider,
        }
        options: dict[str, Any] = {}
        if force_provider_options:
            options.update(self._sdk_provider_runtime_options())
        if self.api_url:
            options["baseURL"] = self.api_url
        if api_key:
            options["apiKey"] = f"{{env:{LOCAL_OPENCODE_API_KEY_ENV}}}"
        if options:
            provider_cfg["options"] = options
        if model_name:
            provider_cfg["models"] = {model_name: {"name": model_name}}

        config_obj = self._json_dict_or_none(env.get(OPENCODE_CONFIG_CONTENT_ENV, "")) or {}
        config_obj.setdefault("$schema", "https://opencode.ai/config.json")
        config_obj.setdefault("permission", "allow")
        if force_provider_options or self.api_key or self.api_url:
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
        data_dir = default_opencode_data_dir()
        if managed_runtime and opencode_data_directory_enabled() and data_dir is not None:
            data_section = config_obj.get("data")
            if not isinstance(data_section, dict):
                data_section = {}
                config_obj["data"] = data_section
            data_section["directory"] = str(data_dir)
            env[OPENCODE_DATA_DIR_ENV] = str(data_dir)
        if self.runtime_data_dir:
            runtime_home = Path(self.runtime_data_dir).resolve(strict=False)
            local_appdata = runtime_home / "AppData" / "Local"
            roaming_appdata = runtime_home / "AppData" / "Roaming"
            xdg_data_home = runtime_home / ".local" / "share"
            local_appdata.mkdir(parents=True, exist_ok=True)
            roaming_appdata.mkdir(parents=True, exist_ok=True)
            xdg_data_home.mkdir(parents=True, exist_ok=True)
            env["HOME"] = str(runtime_home)
            env["USERPROFILE"] = str(runtime_home)
            env["LOCALAPPDATA"] = str(local_appdata)
            env["APPDATA"] = str(roaming_appdata)
            env["XDG_DATA_HOME"] = str(xdg_data_home)
        env[OPENCODE_CONFIG_CONTENT_ENV] = json.dumps(config_obj, ensure_ascii=False)
        return env

    def clone_for_parallel_review(self, *, stage_name: str) -> "OpenCodeClient":
        stage_root = self._repo_root() / "tmp" / "opencode-stage-runtimes"
        stage_root.mkdir(parents=True, exist_ok=True)
        safe_stage = re.sub(r"[^a-zA-Z0-9_-]+", "-", stage_name).strip("-") or "stage"
        runtime_dir = tempfile.mkdtemp(prefix=f"{safe_stage}-", dir=str(stage_root))
        return OpenCodeClient(
            opencode_bin=self.opencode_bin,
            model=self.model,
            timeout_sec=self.timeout_sec,
            show_progress=self.show_progress,
            progress_heartbeat_sec=self.progress_heartbeat_sec,
            progress_level=self.progress_level,
            workspace=self.workspace,
            agent=self.agent,
            api_key=self.api_key,
            api_url=self.api_url,
            provider_id=self.provider_id,
            mcp_config=self.mcp_config,
            runtime_data_dir=runtime_dir,
            progress_callback=self.progress_callback,
        )

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
    def _prepend_path_entry(env: dict[str, str], path_entry: Path | None) -> dict[str, str]:
        if path_entry is None:
            return env
        entry = str(path_entry)
        if not entry:
            return env
        parts = [item for item in env.get("PATH", "").split(os.pathsep) if item]
        if not any(item.lower() == entry.lower() for item in parts):
            env["PATH"] = os.pathsep.join([entry, *parts])
        return env

    def _build_bridge_env(self) -> dict[str, str]:
        env = self._build_runtime_env(force_provider_options=True)
        env[OPENCODE_RUNTIME_ROOT_ENV] = str(self._runtime_root_path())
        runtime_binary = self._resolved_runtime_binary_path()
        if runtime_binary is not None:
            env[OPENCODE_BIN_PATH_ENV] = str(runtime_binary)
            env = self._prepend_path_entry(env, runtime_binary.parent)
        return self._prepend_path_entry(env, self._node_modules_bin_dir())

    def _build_bridge_cmd(self) -> list[str]:
        node_bin = self._resolve_node_bin()
        bridge_script = self._bridge_script_path()
        if node_bin is None:
            raise OpenCodeCallError("未检测到可用的 Node.js 运行时。")
        if not bridge_script.exists():
            raise OpenCodeCallError(f"未找到 OpenCode SDK bridge 脚本：{bridge_script}")
        return [node_bin, str(bridge_script)]

    def _build_bridge_payload(
        self,
        *,
        action: str,
        prompt: str | None = None,
        task_label: str | None = None,
    ) -> dict[str, Any]:
        provider, model_name = self._resolved_model_parts()
        payload: dict[str, Any] = {
            "action": action,
            "directory": self.workspace or str(Path.cwd().resolve()),
            "startupTimeoutMs": min(max(int(self.timeout_sec * 250), 5000), 30000),
        }
        if action == "prompt":
            payload["prompt"] = prompt or ""
            if task_label:
                payload["taskLabel"] = task_label
            if self.agent:
                payload["agent"] = self.agent
            if provider and model_name:
                payload["model"] = {
                    "providerID": provider,
                    "modelID": model_name,
                }
        return payload

    @staticmethod
    def _is_retryable_sdk_error(message: str) -> bool:
        text = (message or "").strip().lower()
        if not text:
            return False
        retryable_markers = (
            "fetch failed",
            "networkerror",
            "network error",
            "econnreset",
            "etimedout",
            "timeout",
            "socket hang up",
            "connection reset",
            "server exited with code",
        )
        return any(marker in text for marker in retryable_markers)

    @staticmethod
    def _merge_usage_summary(current: dict[str, Any], incoming: Any) -> dict[str, Any]:
        merged = dict(current)
        if not isinstance(incoming, dict):
            return merged
        normalized: dict[str, int] = {}
        if any(key in incoming for key in ("input_tokens", "output_tokens", "cache_read_input_tokens")):
            for key in (
                "input_tokens",
                "output_tokens",
                "cache_read_input_tokens",
                "cache_write_input_tokens",
                "reasoning_tokens",
                "total_tokens",
            ):
                value = incoming.get(key)
                if isinstance(value, (int, float)):
                    normalized[key] = int(value)
        else:
            tokens = incoming.get("tokens", incoming)
            if isinstance(tokens, dict):
                cache = tokens.get("cache", {})
                if not isinstance(cache, dict):
                    cache = {}
                mapping = {
                    "input_tokens": tokens.get("input"),
                    "output_tokens": tokens.get("output"),
                    "cache_read_input_tokens": cache.get("read"),
                    "cache_write_input_tokens": cache.get("write"),
                    "reasoning_tokens": tokens.get("reasoning"),
                    "total_tokens": tokens.get("total"),
                }
                for key, value in mapping.items():
                    if isinstance(value, (int, float)):
                        normalized[key] = int(value)
        for key, value in normalized.items():
            merged[key] = max(int(merged.get(key, 0) or 0), value)
        return merged

    @staticmethod
    def _extract_error_message(event: dict[str, Any]) -> str:
        error = event.get("error")
        if isinstance(error, str):
            return error.strip() or "未知错误"
        if isinstance(error, dict):
            data = error.get("data")
            if isinstance(data, dict):
                message = str(data.get("message") or "").strip()
                if message:
                    return message
                detail = str(data.get("detail") or "").strip()
                if detail:
                    return detail
            message = str(error.get("message") or "").strip()
            if message:
                return message
            detail = str(error.get("detail") or "").strip()
            if detail:
                return detail
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
        if self.progress_callback is not None:
            try:
                self.progress_callback(message, level)
            except Exception:
                pass
        try:
            print(message, file=sys.stderr, flush=True)
        except (OSError, ValueError):
            # Windowed/frozen desktop builds may not expose a valid stderr handle.
            # Progress delivery to callbacks must remain non-fatal.
            pass

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

    def _run_sdk_healthcheck(self) -> str | None:
        node_bin = self._resolve_node_bin()
        bridge_script = self._bridge_script_path()
        if node_bin is None:
            return "未检测到可用的 Node.js 运行时。请先安装 Node.js，并在仓库根目录执行 `npm install`。"
        if not bridge_script.exists():
            return f"未找到 OpenCode SDK bridge 脚本：{bridge_script}"
        if not (self._runtime_root_path() / "node_modules" / "@opencode-ai" / "sdk").exists():
            return f"未检测到 OpenCode SDK 包目录：{self._runtime_root_path() / 'node_modules' / '@opencode-ai' / 'sdk'}"
        if not (self._runtime_root_path() / "node_modules" / "opencode-ai").exists():
            return f"未检测到 OpenCode runtime 包目录：{self._runtime_root_path() / 'node_modules' / 'opencode-ai'}"
        if not self._local_opencode_bin_path().exists():
            return f"未检测到本地 OpenCode 可执行包装器：{self._local_opencode_bin_path()}"

        try:
            completed = subprocess.run(
                [node_bin, str(bridge_script)],
                input=json.dumps(self._build_bridge_payload(action="healthcheck"), ensure_ascii=False),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=self._runtime_root_path(),
                env=self._build_bridge_env(),
                timeout=min(max(self.timeout_sec, 20), 60),
                **self._hidden_windows_subprocess_kwargs(),
            )
        except subprocess.TimeoutExpired:
            return "OpenCode SDK healthcheck 超时，请检查本地 `npm install` 是否完整，以及本地 OpenCode runtime 是否可启动。"
        except Exception as exc:  # noqa: BLE001
            return f"OpenCode SDK healthcheck 失败: {exc}"

        parsed_lines: list[dict[str, Any]] = []
        for line in completed.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except Exception:
                continue
            if isinstance(item, dict):
                parsed_lines.append(item)

        if completed.returncode == 0:
            for item in reversed(parsed_lines):
                if item.get("type") == "healthcheck" and item.get("ok") is True:
                    return None

        for item in reversed(parsed_lines):
            if item.get("type") == "error":
                return self._extract_error_message(item)

        detail = (completed.stderr or completed.stdout or "").strip()
        return detail or "OpenCode SDK runtime 不可用。请先在仓库根目录执行 `npm install`。"

    def _ask_text_via_sdk_bridge(self, prompt: str, *, task_label: str | None = None) -> str:
        retry_count = self._sdk_bridge_retry_count()
        overall_deadline = time.time() + max(self.timeout_sec, 60)
        last_exc: OpenCodeCallError | None = None
        for attempt in range(retry_count + 1):
            remaining_total = max(int(overall_deadline - time.time()), 0)
            if remaining_total <= 0:
                break
            self._last_tool_calls = []
            self._last_tool_uses = []
            self._last_usage_summary = {}
            cmd = self._build_bridge_cmd()
            env = self._build_bridge_env()
            payload = self._build_bridge_payload(action="prompt", prompt=prompt, task_label=task_label)
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=self._runtime_root_path(),
                env=env,
                bufsize=1,
                **self._hidden_windows_subprocess_kwargs(),
            )

            if proc.stdout is None or proc.stderr is None or proc.stdin is None:
                proc.kill()
                raise OpenCodeCallError("OpenCode SDK bridge 子进程管道初始化失败。")

            proc.stdin.write(json.dumps(payload, ensure_ascii=False))
            proc.stdin.close()

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
            attempt_timeout_sec = max(30, min(self.timeout_sec, remaining_total))
            attempt_deadline = start_ts + attempt_timeout_sec
            raw_lines: list[str] = []
            stderr_lines: list[str] = []
            stdout_done = False
            stderr_done = False
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
            label = (task_label or "审查任务").strip()
            if self.progress_level == "agent":
                self._emit_progress(f"[agent] {label}：已提交到 OpenCode SDK runtime，开始处理", level="agent")

            try:
                while True:
                    now = time.time()
                    if now > attempt_deadline:
                        proc.kill()
                        raise OpenCodeCallError(f"OpenCode SDK 调用超时（>{attempt_timeout_sec}s）")

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
                                    f"OpenCode SDK 返回错误事件: {self._extract_error_message(event)}"
                                )
                            if event_type == "tool_use":
                                part = event.get("part", {})
                                if not isinstance(part, dict):
                                    part = {}
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
                                        input_text_preview = json.dumps(
                                            tool_input, ensure_ascii=False, separators=(",", ":")
                                        )
                                    except Exception:
                                        input_text_preview = str(tool_input)
                                    self._emit_progress(
                                        f"[opencode] 工具参数: {input_text_preview}",
                                        level="detailed",
                                    )
                            elif event_type == "text":
                                part = event.get("part", {})
                                if not isinstance(part, dict):
                                    part = {}
                                text = str(part.get("text") or "")
                                if text:
                                    text_chunks.append(text)
                                    if self.progress_level == "detailed":
                                        self._emit_progress(f"[opencode] 输出片段: {text}", level="detailed")
                                    elif not first_text_logged:
                                        preview = text.replace("\n", " ")[:80]
                                        self._emit_progress(f"[opencode] 收到输出片段: {preview}", level="normal")
                                        first_text_logged = True
                            elif event_type == "step_finish":
                                part = event.get("part", {})
                                if not isinstance(part, dict):
                                    part = {}
                                usage_summary = self._merge_usage_summary(usage_summary, part.get("tokens", {}))
                                if self.progress_level == "agent":
                                    reason = str(part.get("reason") or "stop")
                                    self._emit_progress(f"[agent] {label}：步骤完成，reason={reason}", level="agent")
                            elif event_type == "usage":
                                usage_summary = self._merge_usage_summary(usage_summary, event.get("usage", {}))
                            elif event_type == "result":
                                result = event.get("result", {})
                                if isinstance(result, dict):
                                    final_result = str(result.get("text") or "").strip()
                                    usage_summary = self._merge_usage_summary(usage_summary, result.get("usage", {}))
                                elif isinstance(result, str):
                                    final_result = result.strip()

                    stderr_drained, stderr_flag = self._drain_queue_nowait(stderr_queue)
                    stderr_lines.extend(stderr_drained)
                    if stderr_flag:
                        stderr_done = True

                    if now - last_heartbeat >= self.progress_heartbeat_sec:
                        elapsed = int(now - start_ts)
                        if self.progress_level == "agent":
                            self._emit_progress(f"[agent] 进行中：OpenCode SDK 处理中（已用时 {elapsed}s）", level="agent")
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
                        f"OpenCode SDK 调用失败(return={return_code}): {stderr_text or fallback_text}"
                    )

                out = final_result or "".join(text_chunks).strip() or "\n".join(raw_lines).strip()
                if not out:
                    raise OpenCodeCallError("OpenCode SDK 返回空输出。")
                self._last_tool_calls = tool_calls
                self._last_tool_uses = tool_uses
                self._last_usage_summary = usage_summary
                return out
            except OpenCodeCallError as exc:
                last_exc = exc
                if attempt >= retry_count or not self._is_retryable_sdk_error(str(exc)):
                    raise
                if self.show_progress:
                    self._emit_progress(
                        f"[opencode] 检测到可重试错误，第 {attempt + 1}/{retry_count} 次重试：{exc}",
                        level="basic",
                    )
                time.sleep(min(3 * (attempt + 1), 10))
        if last_exc is not None:
            raise last_exc
        raise OpenCodeCallError("OpenCode SDK 调用失败。")

    def ask_text(self, prompt: str, *, task_label: str | None = None) -> str:
        self._last_tool_calls = []
        self._last_tool_uses = []
        self._last_usage_summary = {}
        self._last_unavailable_reason = None
        if not self._use_legacy_cli():
            return self._ask_text_via_sdk_bridge(prompt, task_label=task_label)
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
            **self._hidden_windows_subprocess_kwargs(),
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
                data = extract_json_payload(raw, required_top_keys=required_top_keys)
                if isinstance(data, dict):
                    missing = [k for k in required_top_keys if k not in data]
                    if missing:
                        raise OpenCodeCallError(f"缺少字段: {missing}")
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
        raise OpenCodeCallError(f"JSON解析失败: {last_error}")

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
            f"{_compact_text_for_prompt(raw_text, 16000)}"
        )
        repaired_raw = self.ask_text(
            repair_prompt,
            task_label=(f"{task_label}(JSON修复)" if task_label else "JSON修复"),
        )
        data = extract_json_payload(repaired_raw, required_top_keys=required_top_keys)
        if isinstance(data, dict):
            missing = [k for k in required_top_keys if k not in data]
            if missing:
                raise OpenCodeCallError(f"缺少字段: {missing}")
        return data

    def get_last_tool_calls(self) -> list[str]:
        return list(self._last_tool_calls)

    def get_last_tool_uses(self) -> list[dict[str, Any]]:
        return list(self._last_tool_uses)

    def get_last_usage_summary(self) -> dict[str, Any]:
        return dict(self._last_usage_summary)

    def unavailable_reason(self) -> str | None:
        if self._use_legacy_cli():
            resolved = self._resolve_opencode_bin()
            if not resolved:
                self._last_unavailable_reason = (
                    f"显式指定的 opencode legacy CLI 不可用：{self._legacy_opencode_label()}"
                )
                return self._last_unavailable_reason
            try:
                proc = subprocess.run(
                    [resolved, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=20,
                    **self._hidden_windows_subprocess_kwargs(),
                )
            except Exception as exc:  # noqa: BLE001
                self._last_unavailable_reason = (
                    f"显式指定的 opencode legacy CLI 无法执行：{self._legacy_opencode_label()} ({exc})"
                )
                return self._last_unavailable_reason
            if proc.returncode != 0:
                detail = (proc.stderr or proc.stdout or "").strip()
                self._last_unavailable_reason = (
                    f"显式指定的 opencode legacy CLI 校验失败：{detail or self._legacy_opencode_label()}"
                )
                return self._last_unavailable_reason
            self._last_unavailable_reason = None
            return None

        self._last_unavailable_reason = self._run_sdk_healthcheck()
        return self._last_unavailable_reason

    def available(self) -> bool:
        return self.unavailable_reason() is None
