from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

import pytest

from app.llm.claude_client import ClaudeCallError
from app.review.claude_review import (
    _apply_docx_stability_guards_from_text,
    _docx_ocr_required_by_default,
    _has_forbidden_write_tool_call,
    _validate_docx_ocr_coverage,
    run_bid_review_with_claude,
)


def _json_result() -> str:
    return json.dumps(
        {
            "requirements": [{"id": "R001", "category": "资格资质", "text": "t", "source": "s"}],
            "findings": [],
            "summary": {"requirement_count": 1, "finding_count": 0},
        },
        ensure_ascii=False,
    )


class _FakeClient:
    def __init__(self, outputs: list[str], tool_uses_seq: list[list[dict[str, Any]]]) -> None:
        self.timeout_sec = 120
        self._outputs = outputs
        self._tool_uses_seq = tool_uses_seq
        self._last_tool_uses: list[dict[str, Any]] = []
        self._last_tool_calls: list[str] = []
        self.ask_text_calls = 0
        self.prompts: list[str] = []

    def ask_text(self, prompt: str, *, task_label: str | None = None) -> str:
        idx = self.ask_text_calls
        self.ask_text_calls += 1
        self.prompts.append(prompt)
        self._last_tool_uses = self._tool_uses_seq[min(idx, len(self._tool_uses_seq) - 1)]
        self._last_tool_calls = [str(x.get("name", "")) for x in self._last_tool_uses]
        return self._outputs[min(idx, len(self._outputs) - 1)]

    def ask_json(
        self,
        prompt: str,
        *,
        required_top_keys: list[str] | None = None,
        max_retries: int = 2,
        task_label: str | None = None,
    ) -> dict[str, Any] | list[Any]:
        raise AssertionError("ask_json should not be called in these tests")

    def get_last_tool_calls(self) -> list[str]:
        return list(self._last_tool_calls)

    def get_last_tool_uses(self) -> list[dict[str, Any]]:
        return list(self._last_tool_uses)


def _mk_tool_uses(extract_dir: Path, *, ocr_inputs: list[str] | None = None, ocr_dir: Path | None = None) -> list[dict[str, Any]]:
    uses: list[dict[str, Any]] = [
        {
            "name": "mcp__document-parser__extract_images_from_word",
            "input": {
                "file_path": str(extract_dir.parent / "bid.docx"),
                "output_dir": str(extract_dir),
            },
        }
    ]
    ocr_input: dict[str, Any] = {}
    if ocr_inputs is not None:
        ocr_input["inputs"] = ocr_inputs
    if ocr_dir is not None:
        ocr_input["input_dir"] = str(ocr_dir)
    uses.append({"name": "mcp__paddle-ocr__ocr_images_in_dir", "input": ocr_input})
    return uses


def test_docx_ocr_required_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BID_REVIEW_DOCX_OCR_REQUIRED", raising=False)
    assert _docx_ocr_required_by_default() is True
    monkeypatch.setenv("BID_REVIEW_DOCX_OCR_REQUIRED", "0")
    assert _docx_ocr_required_by_default() is False


def test_validate_docx_ocr_coverage_pass_and_fail(tmp_path: Path) -> None:
    extract_dir = tmp_path / "images"
    extract_dir.mkdir(parents=True, exist_ok=True)
    img1 = extract_dir / "1.png"
    img2 = extract_dir / "2.jpg"
    img1.write_bytes(b"a")
    img2.write_bytes(b"b")

    ok, detail = _validate_docx_ocr_coverage(
        _mk_tool_uses(extract_dir, ocr_dir=extract_dir),
        bid_path=tmp_path / "bid.docx",
    )
    assert ok is True
    assert "全量覆盖" in detail

    bad, detail_bad = _validate_docx_ocr_coverage(
        _mk_tool_uses(extract_dir, ocr_inputs=[str(img1)]),
        bid_path=tmp_path / "bid.docx",
    )
    assert bad is False
    assert "缺少1张" in detail_bad


def test_validate_docx_ocr_coverage_fallback_to_docx_media_count(tmp_path: Path) -> None:
    bid_docx = tmp_path / "bid.docx"
    with zipfile.ZipFile(bid_docx, "w") as zf:
        zf.writestr("word/document.xml", "<w:document></w:document>")
        zf.writestr("word/media/image1.png", "a")
        zf.writestr("word/media/image2.jpg", "b")

    ocr_dir = tmp_path / "ocr"
    ocr_dir.mkdir(parents=True, exist_ok=True)
    (ocr_dir / "i1.png").write_bytes(b"a")
    (ocr_dir / "i2.jpg").write_bytes(b"b")

    uses = [
        {
            "name": "mcp__document-parser__extract_images_from_word",
            "input": {"file_path": str(bid_docx)},
        },
        {
            "name": "mcp__paddle-ocr__ocr_images_in_dir",
            "input": {"input_dir": str(ocr_dir)},
        },
    ]
    ok, detail = _validate_docx_ocr_coverage(uses, bid_path=bid_docx)
    assert ok is True
    assert "Word内嵌图片共2张" in detail

    (ocr_dir / "i2.jpg").unlink()
    bad, detail_bad = _validate_docx_ocr_coverage(uses, bid_path=bid_docx)
    assert bad is False
    assert "存在未覆盖图片" in detail_bad


def test_forbidden_write_tool_detects_write() -> None:
    assert _has_forbidden_write_tool_call([{"name": "Write", "input": {"file_path": "x"}}]) is True
    assert _has_forbidden_write_tool_call([{"name": "TodoWrite", "input": {"todos": []}}]) is False


def test_run_bid_review_retries_until_docx_ocr_full_coverage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("BID_REVIEW_DOCX_OCR_REQUIRED", "1")
    monkeypatch.setenv("BID_REVIEW_ENABLE_SECOND_PASS", "0")

    extract_dir = tmp_path / "extract-a"
    extract_dir.mkdir(parents=True, exist_ok=True)
    img1 = extract_dir / "1.png"
    img2 = extract_dir / "2.png"
    img1.write_bytes(b"a")
    img2.write_bytes(b"b")

    partial_uses = _mk_tool_uses(extract_dir, ocr_inputs=[str(img1)])
    full_uses = _mk_tool_uses(extract_dir, ocr_dir=extract_dir)

    client = _FakeClient(
        outputs=[_json_result(), _json_result()],
        tool_uses_seq=[partial_uses, full_uses],
    )

    report, raw = run_bid_review_with_claude(
        tender_path=str(tmp_path / "tender.pdf"),
        bid_path=str(tmp_path / "bid.docx"),
        client=client,
        extra_instruction="",
        user_instruction="",
    )
    assert client.ask_text_calls == 2
    assert report["summary"]["requirement_count"] >= 1
    assert "SKIPPED_BY_DEFAULT" in raw


def test_run_bid_review_raises_when_docx_ocr_still_partial_after_retry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("BID_REVIEW_DOCX_OCR_REQUIRED", "1")
    monkeypatch.setenv("BID_REVIEW_ENABLE_SECOND_PASS", "0")

    extract_dir = tmp_path / "extract-b"
    extract_dir.mkdir(parents=True, exist_ok=True)
    img1 = extract_dir / "1.png"
    img2 = extract_dir / "2.png"
    img1.write_bytes(b"a")
    img2.write_bytes(b"b")

    partial_uses = _mk_tool_uses(extract_dir, ocr_inputs=[str(img1)])
    client = _FakeClient(
        outputs=[_json_result(), _json_result()],
        tool_uses_seq=[partial_uses, partial_uses],
    )

    with pytest.raises(ClaudeCallError, match="Word图片OCR未全量覆盖"):
        run_bid_review_with_claude(
            tender_path=str(tmp_path / "tender.pdf"),
            bid_path=str(tmp_path / "bid.docx"),
            client=client,
            extra_instruction="",
            user_instruction="",
        )


def test_run_bid_review_pdf_keeps_legacy_non_ocr_flow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("BID_REVIEW_ENABLE_SECOND_PASS", "0")

    client = _FakeClient(outputs=[_json_result()], tool_uses_seq=[[{"name": "Read", "input": {"path": "x"}}]])

    report, _ = run_bid_review_with_claude(
        tender_path=str(tmp_path / "tender.pdf"),
        bid_path=str(tmp_path / "bid.pdf"),
        client=client,
        extra_instruction="",
        user_instruction="",
    )
    assert client.ask_text_calls == 1
    assert report["summary"]["requirement_count"] >= 1


def test_run_bid_review_second_pass_prompt_uses_absolute_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("BID_REVIEW_ENABLE_SECOND_PASS", "1")

    client = _FakeClient(
        outputs=[
            _json_result(),
            json.dumps({"additional_findings": []}, ensure_ascii=False),
        ],
        tool_uses_seq=[
            [{"name": "Read", "input": {"path": "x"}}],
            [{"name": "Read", "input": {"path": "x"}}],
        ],
    )

    tender_path = tmp_path / "nested" / "tender.pdf"
    bid_path = tmp_path / "other" / "bid.pdf"
    tender_path.parent.mkdir(parents=True, exist_ok=True)
    bid_path.parent.mkdir(parents=True, exist_ok=True)
    tender_path.write_bytes(b"%PDF-1.4")
    bid_path.write_bytes(b"%PDF-1.4")

    run_bid_review_with_claude(
        tender_path=str(tender_path),
        bid_path=str(bid_path),
        client=client,
        extra_instruction="",
        user_instruction="",
    )

    assert client.ask_text_calls == 2
    second_prompt = client.prompts[1]
    assert f"- 招标文件: {tender_path.resolve()}" in second_prompt
    assert f"- 投标文件: {bid_path.resolve()}" in second_prompt


def test_stability_guards_keep_known_subject_mismatch_pattern() -> None:
    report = {
        "requirements": [
            {"id": "R001", "category": "主体一致性", "text": "主体一致性校验", "source": "s"}
        ],
        "findings": [],
        "summary": {},
    }
    docx_text = "招标人：示例招标方有限公司\n投标函\n投标人：示例招标方有限公司（盖公章）"

    guarded = _apply_docx_stability_guards_from_text(report, docx_text)

    assert any("招标人/采购人" in f["bid_evidence"] for f in guarded["findings"])


def test_stability_guards_keep_known_cover_name_typo_pattern() -> None:
    report = {
        "requirements": [
            {"id": "R001", "category": "主体一致性", "text": "主体一致性校验", "source": "s"}
        ],
        "findings": [],
        "summary": {},
    }
    docx_text = "商务投标文件封面\n投标人：示例科技有限责任司（盖单位公章）"

    guarded = _apply_docx_stability_guards_from_text(report, docx_text)

    assert any("有限责任司" in f["bid_evidence"] for f in guarded["findings"])
