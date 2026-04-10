from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.llm.claude_client import ClaudeCallError
from app.llm.prompt_store import render_prompt
from app.review.claude_review import _ask_stage_text_with_empty_output_retry, run_bid_review_with_claude


class _StageClient:
    def __init__(
        self,
        *,
        root: "_CloneableStageClient",
        stage_name: str,
        output: str,
        tool_uses: list[dict[str, Any]],
    ) -> None:
        self._root = root
        self._stage_name = stage_name
        self._output = output
        self._tool_uses = tool_uses
        self.timeout_sec = 120
        self._last_tool_uses: list[dict[str, Any]] = []
        self._last_tool_calls: list[str] = []

    def ask_text(self, prompt: str, *, task_label: str | None = None) -> str:
        self._root.prompts.append((self._stage_name, task_label or "", prompt))
        self._last_tool_uses = list(self._tool_uses)
        self._last_tool_calls = [str(item.get("name", "")) for item in self._tool_uses]
        return self._output

    def ask_json(
        self,
        prompt: str,
        *,
        required_top_keys: list[str] | None = None,
        max_retries: int = 2,
        task_label: str | None = None,
    ) -> dict[str, Any] | list[Any]:
        raise AssertionError("ask_json should not be called in staged test")

    def get_last_tool_calls(self) -> list[str]:
        return list(self._last_tool_calls)

    def get_last_tool_uses(self) -> list[dict[str, Any]]:
        return list(self._last_tool_uses)


class _CloneableStageClient(_StageClient):
    def __init__(self, *, outputs: dict[str, str], tool_uses_map: dict[str, list[dict[str, Any]]]) -> None:
        self.outputs = outputs
        self.tool_uses_map = tool_uses_map
        self.prompts: list[tuple[str, str, str]] = []
        super().__init__(
            root=self,
            stage_name="requirements",
            output=outputs["requirements"],
            tool_uses=tool_uses_map.get("requirements", []),
        )

    def clone_for_parallel_review(self, *, stage_name: str) -> _StageClient:
        return _StageClient(
            root=self,
            stage_name=stage_name,
            output=self.outputs[stage_name],
            tool_uses=self.tool_uses_map.get(stage_name, []),
        )


class _EmptyThenOkClient:
    def __init__(self) -> None:
        self.calls = 0

    def ask_text(self, prompt: str, *, task_label: str | None = None) -> str:
        self.calls += 1
        if self.calls == 1:
            raise ClaudeCallError("Claude SDK 返回空输出。")
        return '{"findings":[],"summary":{"finding_count":0}}'


def test_stage_prompts_split_requirements_main_context_and_semantic_roles() -> None:
    requirements_prompt = render_prompt(
        "review_requirements.md",
        workspace_dir="D:/code/docs",
        tender_stem="招标文件",
        tender_path="D:/code/docs/招标文件.pdf",
        user_instruction="无",
        instruction="无",
        tender_document_map="- 总页数: 100",
        minimum_requirement_count="10",
    )
    main_prompt = render_prompt(
        "review_findings_main.md",
        workspace_dir="D:/code/docs",
        tender_stem="招标文件",
        bid_stem="投标文件",
        tender_path="D:/code/docs/招标文件.pdf",
        bid_path="D:/code/docs/投标文件.docx",
        user_instruction="无",
        instruction="无",
        tender_document_map="- 总页数: 100",
        bid_document_map="- 模板块: 10",
        requirements_json="[]",
        preprocessed_ocr_note="无",
    )
    context_prompt = render_prompt(
        "review_findings_context.md",
        workspace_dir="D:/code/docs",
        tender_stem="招标文件",
        bid_stem="投标文件",
        tender_path="D:/code/docs/招标文件.pdf",
        bid_path="D:/code/docs/投标文件.docx",
        user_instruction="无",
        instruction="无",
        tender_document_map="- 总页数: 100",
        bid_document_map="- 模板块: 10",
        requirements_json="[]",
        preprocessed_ocr_note="无",
    )
    semantic_prompt = render_prompt(
        "review_findings_semantic.md",
        workspace_dir="D:/code/docs",
        tender_stem="招标文件",
        bid_stem="投标文件",
        tender_path="D:/code/docs/招标文件.pdf",
        bid_path="D:/code/docs/投标文件.docx",
        user_instruction="无",
        instruction="无",
        tender_document_map="- 总页数: 100",
        bid_document_map="- 模板块: 10",
        requirements_json="[]",
        preprocessed_ocr_note="无",
    )

    assert "不要审查投标文件，不要输出 findings" in requirements_prompt
    assert "受控运行目录" in requirements_prompt
    assert "禁止使用 Bash 做目录扫描" in requirements_prompt
    assert "严格边界" in main_prompt
    assert "禁止再次调用" in main_prompt
    assert "受控运行目录" in main_prompt
    assert "禁止使用 Bash 做目录扫描" in main_prompt
    assert "本阶段必须覆盖两类问题" in context_prompt
    assert "仅仅是字段语义类型错误" in context_prompt
    assert "受控运行目录" in context_prompt
    assert "禁止使用 Bash 做目录扫描" in context_prompt
    assert "字段标题和值的语义类型是否匹配" in semantic_prompt
    assert "如果字段期待“公司名”，实际也填了“公司名”，只是公司错了" in semantic_prompt
    assert "受控运行目录" in semantic_prompt
    assert "禁止使用 Bash 做目录扫描" in semantic_prompt


def test_stage_empty_output_retries_with_explicit_json_instruction() -> None:
    client = _EmptyThenOkClient()

    raw, attempts = _ask_stage_text_with_empty_output_retry(
        client,
        "原始提示词",
        task_label="字段语义类型校验",
        required_top_keys=["findings", "summary"],
    )

    assert attempts == 2
    assert client.calls == 2
    assert '"findings"' in raw


def test_run_bid_review_uses_staged_parallel_sessions_and_merges_findings(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("BID_REVIEW_ENABLE_SECOND_PASS", "0")
    monkeypatch.setenv("BID_REVIEW_DOCX_OCR_REQUIRED", "0")
    monkeypatch.setenv("BID_REVIEW_ENFORCE_COMPLETION_GATE", "0")

    tender_path = tmp_path / "tender.pdf"
    bid_path = tmp_path / "bid.pdf"
    tender_path.write_bytes(b"%PDF-1.4")
    bid_path.write_bytes(b"%PDF-1.4")

    requirements_output = json.dumps(
        {
            "requirements": [
                {
                    "id": "REQ-A",
                    "category": "资格资质",
                    "text": "投标人应提供有效营业执照。",
                    "source": "招标文件第1页 L1-L2：营业执照有效。",
                },
                {
                    "id": "REQ-B",
                    "category": "响应格式",
                    "text": "投标函抬头应填写招标人名称。",
                    "source": "招标文件第2页 L1-L2：投标函抬头应填写招标人名称。",
                },
            ],
            "summary": {
                "requirement_count": 2,
                "review_scope": {
                    "tender_total_pages_seen": 2,
                    "tender_sections_reviewed": ["第二章 投标人须知", "第六章 投标文件格式"],
                    "completion_check_passed": True,
                },
            },
        },
        ensure_ascii=False,
    )
    compliance_output = json.dumps(
        {
            "findings": [
                {
                    "requirement_id": "R001",
                    "status": "non_compliant",
                    "issue": "投标文件未提供有效营业执照。",
                    "tender_evidence": "招标文件第1页 L1-L2：营业执照有效。",
                    "bid_evidence": "投标文件第3页 L1-L2：营业执照字段为空。",
                    "recommendation": "补充有效营业执照并重新核对有效期。",
                }
            ],
            "summary": {
                "finding_count": 1,
                "review_scope": {
                    "tender_total_pages_seen": 2,
                    "tender_sections_reviewed": ["第二章 投标人须知"],
                    "bid_sections_reviewed": ["资格审查申请书"],
                    "docx_image_count_seen": 0,
                    "docx_ocr_completed": True,
                    "completion_check_passed": True,
                },
            },
        },
        ensure_ascii=False,
    )
    context_output = json.dumps(
        {
            "findings": [
                {
                    "requirement_id": "",
                    "status": "non_compliant",
                    "issue": "投标函抬头将招标人名称误填为投标人名称，主体位置错位。",
                    "tender_evidence": "招标文件第2页 L1-L2：投标函抬头应填写招标人名称。",
                    "bid_evidence": "投标文件第5页 L1-L2：致：北京创联致信科技有限公司。",
                    "recommendation": "将投标函抬头更正为招标人名称，并复核同类模板抬头字段。",
                }
            ],
            "summary": {
                "finding_count": 1,
                "review_scope": {
                    "tender_total_pages_seen": 2,
                    "tender_sections_reviewed": ["第六章 投标文件格式"],
                    "bid_sections_reviewed": ["投标函"],
                    "docx_image_count_seen": 0,
                    "docx_ocr_completed": True,
                    "completion_check_passed": True,
                },
            },
        },
        ensure_ascii=False,
    )
    semantic_output = json.dumps(
        {
            "findings": [
                {
                    "requirement_id": "R002",
                    "status": "non_compliant",
                    "issue": "字段“开户银行”应填写银行机构名称，但实际值“北京创联致信科技有限公司”为企业名称，字段标签和值类型不匹配。",
                    "tender_evidence": "招标文件第2页 L3-L4：开户银行应按模板填写。",
                    "bid_evidence": "投标文件第6页 L1-L2：开户银行：北京创联致信科技有限公司。",
                    "recommendation": "将开户银行字段更正为实际银行机构名称，并逐项复核账户类字段语义。",
                }
            ],
            "summary": {
                "finding_count": 1,
                "review_scope": {
                    "tender_total_pages_seen": 2,
                    "tender_sections_reviewed": ["第六章 投标文件格式"],
                    "bid_sections_reviewed": ["投标保证金交纳证明"],
                    "docx_image_count_seen": 0,
                    "docx_ocr_completed": True,
                    "completion_check_passed": True,
                },
            },
        },
        ensure_ascii=False,
    )

    outputs = {
        "requirements": requirements_output,
        "compliance": compliance_output,
        "context": context_output,
        "semantic": semantic_output,
    }
    tool_uses_map = {
        "requirements": [
            {
                "name": "mcp__document-parser__read_pdf_pages",
                "input": {"file_path": str(tender_path), "start_page": 1, "end_page": 2},
            }
        ],
        "compliance": [
            {
                "name": "mcp__document-parser__read_pdf_pages",
                "input": {"file_path": str(bid_path), "start_page": 3, "end_page": 3},
            }
        ],
        "context": [
            {
                "name": "mcp__document-parser__search_pdf_text",
                "input": {"file_path": str(bid_path), "query": "投标函"},
            }
        ],
        "semantic": [
            {
                "name": "mcp__document-parser__search_pdf_text",
                "input": {"file_path": str(bid_path), "query": "开户银行"},
            }
        ],
    }
    client = _CloneableStageClient(outputs=outputs, tool_uses_map=tool_uses_map)

    report, raw = run_bid_review_with_claude(
        tender_path=str(tender_path),
        bid_path=str(bid_path),
        client=client,
        extra_instruction="",
        user_instruction="",
    )

    assert len(report["findings"]) == 3
    assert "[REQUIREMENTS_STAGE]" in raw
    assert "[COMPLIANCE_STAGE]" in raw
    assert "[CONTEXT_STAGE]" in raw
    assert "[SEMANTIC_STAGE]" in raw
    assert "[SECOND_PASS]\nSKIPPED_BY_DEFAULT" in raw

    context_finding = next(item for item in report["findings"] if "主体位置错位" in item["issue"])
    assert context_finding["requirement_id"] in {"R001", "R002"}
    assert {stage for stage, _, _ in client.prompts} == {"requirements", "compliance", "context", "semantic"}


def test_staged_docx_review_reuses_preprocessed_ocr_across_parallel_branches(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("BID_REVIEW_ENABLE_SECOND_PASS", "0")
    monkeypatch.setenv("BID_REVIEW_DOCX_OCR_REQUIRED", "1")
    monkeypatch.setenv("BID_REVIEW_ENFORCE_COMPLETION_GATE", "0")

    tender_path = tmp_path / "tender.pdf"
    bid_path = tmp_path / "bid.docx"
    tender_path.write_bytes(b"%PDF-1.4")
    bid_path.write_bytes(b"docx-placeholder")

    monkeypatch.setattr(
        "app.review.claude_review._preprocess_docx_ocr_for_stages",
        lambda **_kwargs: {
            "enabled": True,
            "completed": True,
            "image_count": 2,
            "output_dir": "D:/code/bidreview/dist/BidReviewDesktop/runtime/tmp/document-parser/fake-docx",
            "summary": {"succeeded": 2, "failed": 0},
            "metrics": {"remote_batch_count": 1},
            "preview_lines": ["  - D:/code/bidreview/dist/BidReviewDesktop/runtime/tmp/document-parser/fake-docx/001.png: 营业执照"],
            "duration_ms": 12,
        },
    )

    requirements_output = json.dumps(
        {
            "requirements": [
                {"id": "REQ-A", "category": "响应格式", "text": "投标函抬头应填写招标人名称。", "source": "s"}
            ],
            "summary": {"requirement_count": 1, "review_scope": {"tender_total_pages_seen": 1, "tender_sections_reviewed": ["第六章"], "completion_check_passed": True}},
        },
        ensure_ascii=False,
    )
    stage_output = json.dumps(
        {
            "findings": [],
            "summary": {
                "finding_count": 0,
                "review_scope": {
                    "tender_total_pages_seen": 1,
                    "tender_sections_reviewed": ["第六章"],
                    "bid_sections_reviewed": ["投标函"],
                    "docx_image_count_seen": 0,
                    "docx_ocr_completed": True,
                    "completion_check_passed": True,
                },
            },
        },
        ensure_ascii=False,
    )
    outputs = {
        "requirements": requirements_output,
        "compliance": stage_output,
        "context": stage_output,
        "semantic": stage_output,
    }
    tool_uses_map = {
        "requirements": [{"name": "mcp__document-parser__read_pdf_pages", "input": {"file_path": str(tender_path), "start_page": 1, "end_page": 1}}],
        "compliance": [{"name": "mcp__document-parser__read_word", "input": {"file_path": str(bid_path)}}],
        "context": [{"name": "mcp__document-parser__search_word_text", "input": {"file_path": str(bid_path), "query": "投标函"}}],
        "semantic": [{"name": "mcp__document-parser__search_word_text", "input": {"file_path": str(bid_path), "query": "开户银行"}}],
    }
    client = _CloneableStageClient(outputs=outputs, tool_uses_map=tool_uses_map)

    report, _ = run_bid_review_with_claude(
        tender_path=str(tender_path),
        bid_path=str(bid_path),
        client=client,
        extra_instruction="",
        user_instruction="",
    )

    assert report["summary"]["review_scope"]["docx_image_count_seen"] == 2
    assert report["summary"]["review_scope"]["docx_ocr_completed"] is True
    assert len(client.prompts) == 4
    stage_prompts = {stage: prompt for stage, _, prompt in client.prompts if stage != "requirements"}
    assert all("禁止再次调用 `document-parser.extract_images_from_word`" in prompt for prompt in stage_prompts.values())
    assert all("runtime/tmp/document-parser/fake-docx" in prompt for prompt in stage_prompts.values())
