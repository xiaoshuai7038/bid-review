from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from app.runtime_paths import bundle_internal_root


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bid Review Desktop runtime host")
    parser.add_argument(
        "--server",
        choices=["document-parser", "paddle-ocr"],
        required=True,
        help="启动指定的项目内置 MCP server。",
    )
    return parser


def _restore_frozen_bundle_root() -> None:
    bundle_root = bundle_internal_root()
    if bundle_root is None:
        return

    current_path_items = [item for item in os.environ.get("PATH", "").split(os.pathsep) if item]
    root_text = str(bundle_root)
    if any(item.lower() == root_text.lower() for item in current_path_items):
        return
    os.environ["PATH"] = os.pathsep.join([root_text, *current_path_items])


def _run_server(server_name: str) -> int:
    if server_name == "document-parser":
        from app.mcp_servers.document_parser_server import main as server_main
    elif server_name == "paddle-ocr":
        from app.mcp_servers.paddle_ocr_server import main as server_main
    else:  # pragma: no cover
        raise ValueError(f"未知的 server: {server_name}")
    server_main()
    return 0


def main(argv: list[str] | None = None) -> int:
    _restore_frozen_bundle_root()
    parser = build_parser()
    args = parser.parse_args(argv)
    return _run_server(args.server)


if __name__ == "__main__":
    raise SystemExit(main())
