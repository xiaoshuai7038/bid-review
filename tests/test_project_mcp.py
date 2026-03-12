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


def test_build_project_mcp_servers_use_runtime_host_when_frozen(monkeypatch, tmp_path) -> None:
    runtime_host = (tmp_path / "BidReviewRuntimeHost.exe").resolve()
    monkeypatch.setattr("app.llm.project_mcp.is_frozen", lambda: True)
    monkeypatch.setattr("app.llm.project_mcp.default_runtime_host_path", lambda: runtime_host)

    servers = build_project_mcp_servers("D:/code/bidreview")

    assert servers["document-parser"]["command"] == str(runtime_host)
    assert servers["document-parser"]["args"] == ["--server", "document-parser"]
    assert servers["paddle-ocr"]["command"] == str(runtime_host)
    assert servers["paddle-ocr"]["args"] == ["--server", "paddle-ocr"]


def test_build_project_mcp_config_json_wraps_mcp_servers() -> None:
    raw = build_project_mcp_config_json("D:/code/bidreview")
    data = json.loads(raw)

    assert "mcpServers" in data
    assert "document-parser" in data["mcpServers"]
    assert "paddle-ocr" in data["mcpServers"]
