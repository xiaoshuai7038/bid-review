from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from app.runtime_paths import (
    CLAUDE_CONFIG_DIR_ENV,
    OPENCODE_DATA_DIR_ENV,
    REVIEW_PROFILE_ENV,
    RUNTIME_ROOT_ENV,
    default_runtime_host_path,
    default_claude_config_dir,
    default_opencode_data_dir,
    is_frozen,
    managed_runtime_enabled,
    opencode_data_directory_enabled,
    runtime_root,
)

DEFAULT_OCR_BACKEND_URL = "https://u372299-h9rw-37d89577.westd.seetacloud.com:8443"


def _python_command() -> str:
    return str(Path(sys.executable).resolve())


def _mcp_server_command(server_name: str) -> tuple[str, list[str]]:
    if is_frozen():
        host_path = default_runtime_host_path()
        if host_path is None:
            raise RuntimeError("冻结态未找到桌面 runtime host 路径。")
        return str(host_path), ["--server", server_name]
    if server_name == "document-parser":
        return _python_command(), ["-m", "app.mcp_servers.document_parser_server"]
    if server_name == "paddle-ocr":
        return _python_command(), ["-m", "app.mcp_servers.paddle_ocr_server"]
    raise ValueError(f"未知的 MCP server: {server_name}")


def build_project_mcp_servers(workspace: str | None) -> dict[str, Any]:
    cwd = str(Path(workspace or Path.cwd()).resolve())
    document_parser_command, document_parser_args = _mcp_server_command("document-parser")
    paddle_ocr_command, paddle_ocr_args = _mcp_server_command("paddle-ocr")
    env_base = {
        "PYTHONIOENCODING": "utf-8",
    }
    review_profile = os.getenv(REVIEW_PROFILE_ENV, "").strip()
    if review_profile:
        env_base[REVIEW_PROFILE_ENV] = review_profile
    if managed_runtime_enabled():
        env_base[RUNTIME_ROOT_ENV] = str(runtime_root())
        claude_config_dir = default_claude_config_dir()
        if claude_config_dir is not None:
            env_base[CLAUDE_CONFIG_DIR_ENV] = str(claude_config_dir)
        opencode_data_dir = default_opencode_data_dir()
        if opencode_data_directory_enabled() and opencode_data_dir is not None:
            env_base[OPENCODE_DATA_DIR_ENV] = str(opencode_data_dir)
    return {
        "document-parser": {
            "command": document_parser_command,
            "args": document_parser_args,
            "env": env_base,
            "cwd": cwd,
            "timeout": 600,
        },
        "paddle-ocr": {
            "command": paddle_ocr_command,
            "args": paddle_ocr_args,
            "env": {
                **env_base,
                "OCRMCP_BACKEND_URL": os.getenv("OCRMCP_BACKEND_URL", DEFAULT_OCR_BACKEND_URL),
                "OCRMCP_API_KEY": os.getenv("OCRMCP_API_KEY", ""),
                "OCRMCP_CHUNK_SIZE": os.getenv("OCRMCP_CHUNK_SIZE", "16"),
                "OCRMCP_TIMEOUT_SECONDS": os.getenv("OCRMCP_TIMEOUT_SECONDS", "600"),
            },
            "cwd": cwd,
            "timeout": 1200,
        },
    }


def build_project_mcp_config_json(workspace: str | None) -> str:
    return json.dumps({"mcpServers": build_project_mcp_servers(workspace)}, ensure_ascii=False)
