from __future__ import annotations

from app.mcp_servers import paddle_ocr_server as server


def test_extract_clean_ocr_text_removes_metadata_lines_and_inline_tokens() -> None:
    raw = (
        "/root/jobs/ocr/page_0001.png\n"
        "min\n"
        "general\n"
        "投标人：示例科技有限公司\n"
        "/root/tree/0/1 min/general/Paragraph 法定代表人：张三"
    )

    assert server._extract_clean_ocr_text(raw) == "投标人：示例科技有限公司\n法定代表人：张三"


def test_extract_clean_ocr_text_flattens_structured_payload_without_metadata() -> None:
    raw = {
        "type": "min/general/Document",
        "path": "/root/doc/0",
        "children": [
            {"type": "min/general/Paragraph", "path": "/root/doc/0/0", "text": "第一段正文"},
            {"type": "min/general/Paragraph", "path": "/root/doc/0/1", "content": "第二段正文"},
        ],
    }

    assert server._extract_clean_ocr_text(raw) == "第一段正文\n第二段正文"


def test_batch_ocr_images_prefers_client_source_path_and_sanitizes_text(monkeypatch, tmp_path) -> None:
    image_path = tmp_path / "page_0001.png"
    image_path.write_bytes(b"fake-image")

    payload = {
        "results": [
            {
                "source_path": "/root/uploads/page_0001.png",
                "success": True,
                "text": {
                    "type": "min/general/Document",
                    "path": "/root/doc/0",
                    "children": [
                        {"text": "投标函"},
                        {"text": "/root/doc/0/1 min/general/Paragraph 投标人：示例科技有限公司"},
                    ],
                },
                "elapsed_ms": 123,
            }
        ]
    }

    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return payload

    class _FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs

        def __enter__(self) -> "_FakeClient":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def post(self, url: str, *, data=None, files=None):
            assert url.endswith("/v1/ocr/images")
            assert data is not None
            assert files is not None
            return _FakeResponse()

    monkeypatch.setattr(server.httpx, "Client", _FakeClient)

    result = server._batch_ocr_images([image_path])

    assert result["summary"] == {"total_files": 1, "succeeded": 1, "failed": 0}
    assert result["results"][0]["source_path"] == str(image_path)
    assert result["results"][0]["text"] == "投标函\n投标人：示例科技有限公司"
