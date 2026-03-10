from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


DEFAULT_OCR_BACKEND_URL = "https://u372299-h9rw-37d89577.westd.seetacloud.com:8443"


def _python_command() -> str:
    return str(Path(sys.executable).resolve())


def build_project_mcp_servers(workspace: str | None) -> dict[str, Any]:
    cwd = str(Path(workspace or Path.cwd()).resolve())
    env_base = {
        "PYTHONIOENCODING": "utf-8",
    }
    return {
        "document-parser": {
            "command": _python_command(),
            "args": ["-m", "app.mcp_servers.document_parser_server"],
            "env": env_base,
            "cwd": cwd,
            "timeout": 600,
        },
        "paddle-ocr": {
            "command": _python_command(),
            "args": ["-m", "app.mcp_servers.paddle_ocr_server"],
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

