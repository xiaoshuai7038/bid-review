from __future__ import annotations

import json

from app.llm.project_mcp import DEFAULT_OCR_BACKEND_URL, build_project_mcp_config_json, build_project_mcp_servers


def test_build_project_mcp_servers_contains_document_parser_and_ocr() -> None:
    servers = build_project_mcp_servers("D:/code/bidreview")

    assert "document-parser" in servers
    assert "paddle-ocr" in servers
    assert servers["document-parser"]["args"] == ["-m", "app.mcp_servers.document_parser_server"]
    assert servers["paddle-ocr"]["args"] == ["-m", "app.mcp_servers.paddle_ocr_server"]
    assert servers["paddle-ocr"]["env"]["OCRMCP_BACKEND_URL"] == DEFAULT_OCR_BACKEND_URL


def test_build_project_mcp_config_json_wraps_mcp_servers() -> None:
    raw = build_project_mcp_config_json("D:/code/bidreview")
    data = json.loads(raw)

    assert "mcpServers" in data
    assert "document-parser" in data["mcpServers"]
    assert "paddle-ocr" in data["mcpServers"]
