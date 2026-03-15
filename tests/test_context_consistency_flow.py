from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.llm.prompt_store import render_prompt
from app.review.claude_review import _collect_tender_outline, _parse_review_report_from_raw, run_bid_review_with_claude


class _FakeClient:
    def __init__(self, output: str, tool_uses: list[dict[str, Any]] | None = None) -> None:
        self.timeout_sec = 120
        self._output = output
        self._tool_uses = tool_uses or [{"name": "Read", "input": {"path": "x"}}]
        self.prompts: list[str] = []

    def ask_text(self, prompt: str, *, task_label: str | None = None) -> str:
        self.prompts.append(prompt)
        return self._output

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
        return [str(x.get("name", "")) for x in self._tool_uses]

    def get_last_tool_uses(self) -> list[dict[str, Any]]:
        return list(self._tool_uses)

    def repair_json_text(
        self,
        raw_text: str,
        *,
        required_top_keys: list[str] | None = None,
        parse_error: str = "",
        task_label: str | None = None,
    ) -> dict[str, Any] | list[Any]:
        raise AssertionError("repair_json_text should not be called in this test")


class _SeqClient:
    def __init__(self, outputs: list[str], tool_uses: list[dict[str, Any]] | None = None) -> None:
        self.timeout_sec = 120
        self._outputs = outputs
        self._tool_uses = tool_uses or [{"name": "Read", "input": {"path": "x"}}]
        self.prompts: list[str] = []
        self.ask_text_calls = 0

    def ask_text(self, prompt: str, *, task_label: str | None = None) -> str:
        self.prompts.append(prompt)
        idx = min(self.ask_text_calls, len(self._outputs) - 1)
        self.ask_text_calls += 1
        return self._outputs[idx]

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
        return [str(x.get("name", "")) for x in self._tool_uses]

    def get_last_tool_uses(self) -> list[dict[str, Any]]:
        return list(self._tool_uses)

    def repair_json_text(
        self,
        raw_text: str,
        *,
        required_top_keys: list[str] | None = None,
        parse_error: str = "",
        task_label: str | None = None,
    ) -> dict[str, Any] | list[Any]:
        raise AssertionError("repair_json_text should not be called in these tests")


class _RepairingClient(_FakeClient):
    def __init__(self, repaired: dict[str, Any]) -> None:
        super().__init__("unused")
        self.repaired = repaired
        self.repair_calls = 0

    def repair_json_text(
        self,
        raw_text: str,
        *,
        required_top_keys: list[str] | None = None,
        parse_error: str = "",
        task_label: str | None = None,
    ) -> dict[str, Any] | list[Any]:
        self.repair_calls += 1
        return self.repaired


def test_review_main_prompt_requires_field_level_template_checks() -> None:
    prompt = render_prompt(
        "review_main.md",
        workspace_dir="D:/code/docs",
        tender_stem="招标文件",
        bid_stem="投标文件",
        tender_path="D:/code/docs/招标文件.pdf",
        bid_path="D:/code/docs/投标文件.docx",
        user_instruction="无",
        instruction="无",
        tender_document_map="- 总页数: 100",
        bid_document_map="- 检测到的正文/模板块数量: 10",
        minimum_requirement_count="10",
    )
    assert "先建立“主体基线”" in prompt
    assert "字段标签和值类型一致性" in prompt
    assert "模板字段完整性/字段角色一致性" in prompt
    assert "不得用“需人工核验主体一致性/项目信息一致性”替代" in prompt
    assert "投标保证金交纳证明、基本账户开户证明" in prompt


def test_review_second_pass_prompt_requires_field_level_retry() -> None:
    prompt = render_prompt(
        "review_second_pass.md",
        workspace_dir="D:/code/docs",
        tender_stem="招标文件",
        bid_stem="投标文件",
        tender_path="D:/code/docs/招标文件.pdf",
        bid_path="D:/code/docs/投标文件.docx",
        user_instruction="无",
        initial_json="{}",
    )
    assert "- 招标文件: D:/code/docs/招标文件.pdf" in prompt
    assert "- 投标文件: D:/code/docs/投标文件.docx" in prompt
    assert "第六章模板字段角色不匹配" in prompt
    assert "必须重新回到对应模板文书和字段位置核对" in prompt
    assert "禁止只输出“需人工核验”概括项" in prompt


def test_run_bid_review_retries_when_review_completion_gate_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("BID_REVIEW_ENABLE_SECOND_PASS", "0")
    monkeypatch.setenv("BID_REVIEW_DOCX_OCR_REQUIRED", "0")
    monkeypatch.setattr(
        "app.review.claude_review._collect_tender_outline",
        lambda _path: {
            "total_pages": 50,
            "sections": [{"title": "第二章 投标人须知", "page_no": 7}, {"title": "第五章 技术标准和要求", "page_no": 30}, {"title": "第六章 投标文件格式", "page_no": 40}],
            "relevant_sections": ["第二章 投标人须知", "第五章 技术标准和要求", "第六章 投标文件格式"],
        },
    )
    monkeypatch.setattr(
        "app.review.claude_review._collect_bid_outline",
        lambda _path: {
            "sections": ["投标函", "开标一览表", "分项报价表", "投标保证金交纳证明", "资格审查申请书", "技术条款偏离表"],
            "template_sections": ["投标函", "开标一览表", "分项报价表", "投标保证金交纳证明", "资格审查申请书", "技术条款偏离表"],
            "docx_image_count": 2,
        },
    )

    incomplete = json.dumps(
        {
            "requirements": [
                {"id": "R001", "category": "响应格式", "text": "投标文件应按格式填写", "source": "s"}
            ],
            "findings": [],
            "summary": {
                "requirement_count": 1,
                "finding_count": 0,
                "review_scope": {
                    "tender_total_pages_seen": 10,
                    "tender_sections_reviewed": ["第二章 投标人须知"],
                    "bid_sections_reviewed": ["投标函"],
                    "docx_image_count_seen": 0,
                    "docx_ocr_completed": False,
                    "completion_check_passed": False,
                },
            },
        },
        ensure_ascii=False,
    )
    complete = json.dumps(
        {
            "requirements": [
                {"id": "R001", "category": "资格资质", "text": "营业执照等资格材料必须齐全", "source": "s"},
                {"id": "R002", "category": "响应格式", "text": "投标函抬头必须填写招标人名称", "source": "s"},
                {"id": "R003", "category": "响应格式", "text": "开标一览表需完整填写", "source": "s"},
                {"id": "R004", "category": "响应格式", "text": "分项报价表需完整填写", "source": "s"},
                {"id": "R005", "category": "响应格式", "text": "投标保证金交纳证明需完整填写", "source": "s"},
                {"id": "R006", "category": "响应格式", "text": "基本账户证明需完整填写", "source": "s"},
            ],
            "findings": [],
            "summary": {
                "requirement_count": 6,
                "finding_count": 0,
                "review_scope": {
                    "tender_total_pages_seen": 50,
                    "tender_sections_reviewed": ["第二章 投标人须知", "第五章 技术标准和要求", "第六章 投标文件格式"],
                    "bid_sections_reviewed": ["投标函", "开标一览表", "分项报价表", "投标保证金交纳证明", "资格审查申请书", "技术条款偏离表"],
                    "docx_image_count_seen": 2,
                    "docx_ocr_completed": True,
                    "completion_check_passed": True,
                },
            },
        },
        ensure_ascii=False,
    )

    client = _SeqClient([incomplete, complete])
    report, raw = run_bid_review_with_claude(
        tender_path=str(tmp_path / "tender.pdf"),
        bid_path=str(tmp_path / "bid.docx"),
        client=client,
        extra_instruction="",
        user_instruction="",
    )

    assert client.ask_text_calls == 2
    assert "[COMPLETION_RETRY]" in raw
    assert len(report["requirements"]) == 6


def test_completion_gate_uses_observed_scope_when_model_scope_is_underreported(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("BID_REVIEW_ENABLE_SECOND_PASS", "0")
    monkeypatch.setenv("BID_REVIEW_DOCX_OCR_REQUIRED", "0")
    monkeypatch.setattr(
        "app.review.claude_review._collect_tender_outline",
        lambda _path: {
            "total_pages": 50,
            "sections": [
                {"title": "第二章 投标人须知", "page_no": 7},
                {"title": "第五章 技术标准和要求", "page_no": 30},
                {"title": "第六章 投标文件格式", "page_no": 40},
            ],
            "relevant_sections": ["第二章 投标人须知", "第五章 技术标准和要求", "第六章 投标文件格式"],
        },
    )
    monkeypatch.setattr(
        "app.review.claude_review._collect_bid_outline",
        lambda _path: {
            "sections": ["投标函", "开标一览表", "分项报价表", "投标保证金交纳证明", "资格审查申请书", "技术条款偏离表"],
            "template_sections": ["投标函", "开标一览表", "分项报价表", "投标保证金交纳证明", "资格审查申请书", "技术条款偏离表"],
            "docx_image_count": 2,
        },
    )
    monkeypatch.setattr(
        "app.review.claude_review.load_or_build_bid_artifact",
        lambda _path: type(
            "Prepared",
            (),
            {
                "data": {
                    "sections": [
                        {"id": "214", "title": "投标函", "lines": []},
                        {"id": "215", "title": "开标一览表", "lines": []},
                    ]
                }
            },
        )(),
    )
    monkeypatch.setattr(
        "app.review.claude_review.extract_or_load_word_image_manifest",
        lambda _path, filter_policy: type(
            "Prepared",
            (),
            {
                "data": {
                    "image_count_raw": 2,
                    "image_count_unique": 2,
                    "image_count_skipped": 0,
                    "image_paths": [],
                }
            },
        )(),
    )

    underreported = json.dumps(
        {
            "requirements": [
                {"id": "R001", "category": "资格资质", "text": "营业执照等资格材料必须齐全", "source": "s"},
                {"id": "R002", "category": "响应格式", "text": "投标函抬头必须填写招标人名称", "source": "s"},
                {"id": "R003", "category": "响应格式", "text": "开标一览表需完整填写", "source": "s"},
                {"id": "R004", "category": "响应格式", "text": "分项报价表需完整填写", "source": "s"},
                {"id": "R005", "category": "响应格式", "text": "投标保证金交纳证明需完整填写", "source": "s"},
                {"id": "R006", "category": "响应格式", "text": "基本账户证明需完整填写", "source": "s"},
            ],
            "findings": [],
            "summary": {
                "requirement_count": 6,
                "finding_count": 0,
                "review_scope": {
                    "tender_total_pages_seen": 10,
                    "tender_sections_reviewed": ["第二章 投标人须知"],
                    "bid_sections_reviewed": ["投标函"],
                    "docx_image_count_seen": 0,
                    "docx_ocr_completed": False,
                    "completion_check_passed": False,
                },
            },
        },
        ensure_ascii=False,
    )

    tool_uses = [
        {
            "name": "mcp__document-parser__read_pdf_pages",
            "input": {"file_path": str(tmp_path / "tender.pdf"), "start_page": 18, "end_page": 50},
        },
        {
            "name": "mcp__document-parser__read_word_section",
            "input": {"file_path": str(tmp_path / "bid.docx"), "section_id": "214"},
        },
        {
            "name": "mcp__document-parser__search_word_text",
            "input": {"file_path": str(tmp_path / "bid.docx"), "query": "投标函|开标一览表"},
        },
        {
            "name": "mcp__document-parser__extract_images_from_word",
            "input": {"file_path": str(tmp_path / "bid.docx"), "output_dir": str(tmp_path / "extract")},
        },
        {
            "name": "mcp__paddle-ocr__ocr_images_in_dir",
            "input": {"dir_path": str(tmp_path / "extract")},
        },
    ]
    client = _FakeClient(underreported, tool_uses=tool_uses)

    report, raw = run_bid_review_with_claude(
        tender_path=str(tmp_path / "tender.pdf"),
        bid_path=str(tmp_path / "bid.docx"),
        client=client,
        extra_instruction="",
        user_instruction="",
    )

    assert "[COMPLETION_RETRY]" not in raw
    review_scope = report["summary"]["review_scope"]
    assert review_scope["tender_total_pages_seen"] >= 50
    assert review_scope["docx_ocr_completed"] is True


def test_completion_gate_allows_small_tail_page_gap_when_key_sections_are_covered() -> None:
    from app.review.claude_review import _evaluate_review_completion

    raw_data = {
        "requirements": [
            {"id": f"R{i:03d}", "category": "响应格式", "text": f"要求{i}", "source": "s"}
            for i in range(1, 11)
        ],
        "summary": {
            "review_scope": {
                "tender_total_pages_seen": 100,
                "tender_sections_reviewed": [
                    "第二章 投标人须知",
                    "投标人须知前附表",
                    "第三章 评标办法",
                    "评标办法前附表",
                    "第五章 技术标准和要求",
                    "第六章 投标文件格式",
                ],
                "bid_sections_reviewed": ["投标函", "开标一览表", "分项报价表", "技术条款偏离表"],
                "docx_image_count_seen": 0,
                "docx_ocr_completed": True,
                "completion_check_passed": False,
            }
        },
    }
    tender_outline = {
        "total_pages": 103,
        "relevant_sections": [
            "第二章 投标人须知",
            "投标人须知前附表",
            "第三章 评标办法",
            "评标办法前附表",
            "第五章 技术标准和要求",
            "第六章 投标文件格式",
        ],
    }
    bid_outline = {
        "template_sections": ["投标函", "开标一览表", "分项报价表", "技术条款偏离表"],
        "docx_image_count": 0,
    }

    reasons = _evaluate_review_completion(
        raw_data,
        tender_outline=tender_outline,
        bid_outline=bid_outline,
        min_requirement_count=6,
        require_word_extract=False,
        ocr_required=False,
    )

    assert reasons == []


def test_completion_gate_still_blocks_large_page_gap_even_when_key_sections_are_covered() -> None:
    from app.review.claude_review import _evaluate_review_completion

    raw_data = {
        "requirements": [
            {"id": f"R{i:03d}", "category": "响应格式", "text": f"要求{i}", "source": "s"}
            for i in range(1, 11)
        ],
        "summary": {
            "review_scope": {
                "tender_total_pages_seen": 90,
                "tender_sections_reviewed": [
                    "第二章 投标人须知",
                    "投标人须知前附表",
                    "第三章 评标办法",
                    "评标办法前附表",
                    "第五章 技术标准和要求",
                    "第六章 投标文件格式",
                ],
                "bid_sections_reviewed": ["投标函", "开标一览表", "分项报价表", "技术条款偏离表"],
                "docx_image_count_seen": 0,
                "docx_ocr_completed": True,
                "completion_check_passed": False,
            }
        },
    }
    tender_outline = {
        "total_pages": 103,
        "relevant_sections": [
            "第二章 投标人须知",
            "投标人须知前附表",
            "第三章 评标办法",
            "评标办法前附表",
            "第五章 技术标准和要求",
            "第六章 投标文件格式",
        ],
    }
    bid_outline = {
        "template_sections": ["投标函", "开标一览表", "分项报价表", "技术条款偏离表"],
        "docx_image_count": 0,
    }

    reasons = _evaluate_review_completion(
        raw_data,
        tender_outline=tender_outline,
        bid_outline=bid_outline,
        min_requirement_count=6,
        require_word_extract=False,
        ocr_required=False,
    )

    assert any("90/103" in reason for reason in reasons)


def test_parse_review_report_from_raw_uses_json_repair_before_full_retry(tmp_path: Path) -> None:
    repaired = {
        "requirements": [{"id": "R001", "category": "响应格式", "text": "投标函应按格式填写", "source": "s"}],
        "findings": [],
        "summary": {"requirement_count": 1, "finding_count": 0},
    }
    client = _RepairingClient(repaired)

    report, raw = _parse_review_report_from_raw(
        raw_output='{"requirements":[{"id":"R001","text":"投标函中"致"字段错误"}],"findings":[],"summary":{}}',
        prompt="ignored",
        client=client,
        backend_name="Claude",
        tender_path=tmp_path / "tender.pdf",
        bid_path=tmp_path / "bid.docx",
    )

    assert client.repair_calls == 1
    assert "[JSON_REPAIRED]" in raw
    assert report["requirements"][0]["text"] == "投标函应按格式填写"


def test_collect_tender_outline_prefers_real_major_chapters_over_toc_noise(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    tender_path = tmp_path / "tender.pdf"
    tender_path.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(
        "app.review.claude_review._build_pdf_line_index",
        lambda _path: [
            {"kind": "pdf", "page_no": 2, "line_no": 1, "section": "", "text": "第二章 投标人须知 ............................................................ 7", "norm": "第二章投标人须知............................................................7"},
            {"kind": "pdf", "page_no": 2, "line_no": 2, "section": "", "text": "九、纪律、监督和列入招标人供应商黑名单的情形 ............................... 28", "norm": "九、纪律、监督和列入招标人供应商黑名单的情形...............................28"},
            {"kind": "pdf", "page_no": 8, "line_no": 1, "section": "", "text": "第二章 投标人须知", "norm": "第二章投标人须知"},
            {"kind": "pdf", "page_no": 9, "line_no": 1, "section": "", "text": "投标人须知前附表", "norm": "投标人须知前附表"},
            {"kind": "pdf", "page_no": 70, "line_no": 1, "section": "", "text": "第五章 技术标准和要求", "norm": "第五章技术标准和要求"},
            {"kind": "pdf", "page_no": 76, "line_no": 1, "section": "", "text": "第六章 投标文件格式", "norm": "第六章投标文件格式"},
        ],
    )

    outline = _collect_tender_outline(tender_path)

    assert "第二章 投标人须知" in outline["relevant_sections"]
    assert "第五章 技术标准和要求" in outline["relevant_sections"]
    assert "第六章 投标文件格式" in outline["relevant_sections"]


def test_run_bid_review_keeps_model_subject_finding_without_local_rewrite(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("BID_REVIEW_ENABLE_SECOND_PASS", "0")
    monkeypatch.setenv("BID_REVIEW_DOCX_OCR_REQUIRED", "0")

    client = _FakeClient(
        json.dumps(
            {
                "requirements": [
                    {
                        "id": "R001",
                        "category": "主体一致性",
                        "text": "投标文件关键主体字段必须先建立主体基线，并在全文范围保持取值一致",
                        "source": "通用校验要求",
                    }
                ],
                "findings": [
                    {
                        "id": "F001",
                        "requirement_id": "R001",
                        "status": "non_compliant",
                        "issue": "投标人名称前后不一致，基线值为悦智人工智能（深圳）有限责任公司，报价表处写为悦智智能（深圳）有限责任公司。",
                        "tender_evidence": "投标文件关键主体字段必须先建立主体基线，并在全文范围保持取值一致。",
                        "bid_evidence": "封面第1页：投标人“悦智人工智能（深圳）有限责任公司”；分项报价表第18页：投标人“悦智智能（深圳）有限责任公司”。",
                        "recommendation": "统一所有投标人名称为营业执照一致的法定全称，并复核所有落款和报价页。",
                    }
                ],
                "summary": {"requirement_count": 1, "finding_count": 1},
            },
            ensure_ascii=False,
        )
    )

    report, _ = run_bid_review_with_claude(
        tender_path=str(tmp_path / "tender.pdf"),
        bid_path=str(tmp_path / "bid.docx"),
        client=client,
        extra_instruction="",
        user_instruction="",
    )

    assert len(report["requirements"]) == 1
    assert len(report["findings"]) == 1
    assert report["findings"][0]["issue"].startswith("投标人名称前后不一致")


def test_run_bid_review_does_not_inject_local_requirements(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("BID_REVIEW_ENABLE_SECOND_PASS", "0")
    monkeypatch.setenv("BID_REVIEW_DOCX_OCR_REQUIRED", "0")
    monkeypatch.setenv("BID_REVIEW_ENFORCE_COMPLETION_GATE", "0")
    monkeypatch.setattr(
        "app.review.claude_review._build_pdf_line_index",
        lambda _path: [
            {"kind": "pdf", "page_no": 76, "line_no": 1, "section": "", "text": "第六章 投标文件格式", "norm": "第六章投标文件格式"},
            {"kind": "pdf", "page_no": 80, "line_no": 1, "section": "", "text": "致：（招标人名称）", "norm": "致招标人名称"},
        ],
    )

    client = _FakeClient(
        json.dumps(
            {
                "requirements": [
                    {"id": "R001", "category": "响应格式", "text": "投标文件应按格式填写", "source": "s"}
                ],
                "findings": [],
                "summary": {"requirement_count": 1, "finding_count": 0},
            },
            ensure_ascii=False,
        )
    )

    report, _ = run_bid_review_with_claude(
        tender_path=str(tmp_path / "tender.pdf"),
        bid_path=str(tmp_path / "bid.docx"),
        client=client,
        extra_instruction="",
        user_instruction="",
    )

    assert len(report["requirements"]) == 1
    assert report["requirements"][0]["text"] == "投标文件应按格式填写"


def test_run_bid_review_does_not_add_local_semantic_findings_even_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("BID_REVIEW_ENABLE_SECOND_PASS", "0")
    monkeypatch.setenv("BID_REVIEW_DOCX_OCR_REQUIRED", "0")
    monkeypatch.setenv("BID_REVIEW_ENABLE_LOCAL_SEMANTIC_GUARDS", "1")
    monkeypatch.setattr(
        "app.review.claude_review._extract_docx_text",
        lambda _path: (
            "投标函\n"
            "致：北京创联致信科技有限公司（招标人名称）\n"
            "开户银行：内蒙古中实工程招标咨询有限责任公司"
        ),
    )

    client = _FakeClient(
        json.dumps(
            {
                "requirements": [
                    {"id": "R001", "category": "响应格式", "text": "投标文件应按格式填写", "source": "s"}
                ],
                "findings": [],
                "summary": {"requirement_count": 1, "finding_count": 0},
            },
            ensure_ascii=False,
        )
    )

    report, _ = run_bid_review_with_claude(
        tender_path=str(tmp_path / "tender.pdf"),
        bid_path=str(tmp_path / "bid.docx"),
        client=client,
        extra_instruction="",
        user_instruction="",
    )

    assert report["findings"] == []


def test_run_bid_review_preserves_model_template_field_finding_verbatim(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("BID_REVIEW_ENABLE_SECOND_PASS", "0")
    monkeypatch.setenv("BID_REVIEW_DOCX_OCR_REQUIRED", "0")

    issue = "字段“开户银行”应填写银行机构名称，当前填写“内蒙古中实工程招标咨询有限责任公司”，实际呈现为单位名称，字段语义不符。"
    client = _FakeClient(
        json.dumps(
            {
                "requirements": [
                    {"id": "R001", "category": "响应格式", "text": "投标保证金与基本账户字段必须准确填写", "source": "s"}
                ],
                "findings": [
                    {
                        "id": "F001",
                        "requirement_id": "R001",
                        "status": "non_compliant",
                        "issue": issue,
                        "tender_evidence": "招标文件第12页 L1-L2：投标保证金必须由投标人的基本账户转出。",
                        "bid_evidence": "投标文件《投标保证金交纳证明》L8-L8：开户银行：内蒙古中实工程招标咨询有限责任公司",
                        "recommendation": "将开户银行更正为开户银行全称或开户支行名称，并同步复核账户名、账号和基本账户证明。",
                    }
                ],
                "summary": {"requirement_count": 1, "finding_count": 1},
            },
            ensure_ascii=False,
        )
    )

    report, _ = run_bid_review_with_claude(
        tender_path=str(tmp_path / "tender.pdf"),
        bid_path=str(tmp_path / "bid.docx"),
        client=client,
        extra_instruction="",
        user_instruction="",
    )

    assert report["findings"][0]["issue"] == issue


def test_run_bid_review_preserves_model_addressee_finding_verbatim(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("BID_REVIEW_ENABLE_SECOND_PASS", "0")
    monkeypatch.setenv("BID_REVIEW_DOCX_OCR_REQUIRED", "0")

    issue = "《投标函》中的收件人/抬头字段“致”应填写招标人名称，当前填写“北京创联致信科技有限公司（招标人名称）”，与文书角色不一致。"
    client = _FakeClient(
        json.dumps(
            {
                "requirements": [
                    {"id": "R001", "category": "响应格式", "text": "投标函中的收件人字段必须填写招标人名称", "source": "s"}
                ],
                "findings": [
                    {
                        "id": "F001",
                        "requirement_id": "R001",
                        "status": "non_compliant",
                        "issue": issue,
                        "tender_evidence": "招标文件第80页 L1-L1：致：（招标人名称）",
                        "bid_evidence": "投标文件《投标函》L2-L2：致：北京创联致信科技有限公司（招标人名称）",
                        "recommendation": "将投标函收件人字段更正为招标人全称。",
                    }
                ],
                "summary": {"requirement_count": 1, "finding_count": 1},
            },
            ensure_ascii=False,
        )
    )

    report, _ = run_bid_review_with_claude(
        tender_path=str(tmp_path / "tender.pdf"),
        bid_path=str(tmp_path / "bid.docx"),
        client=client,
        extra_instruction="",
        user_instruction="",
    )

    assert report["findings"][0]["issue"] == issue
