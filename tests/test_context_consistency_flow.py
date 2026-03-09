from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.llm.prompt_store import render_prompt
from app.review.claude_review import (
    _apply_docx_stability_guards_from_text,
    _ensure_context_consistency_requirement,
    run_bid_review_with_claude,
)


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


def test_review_main_prompt_requires_subject_baseline_and_global_consistency() -> None:
    prompt = render_prompt(
        "review_main.md",
        workspace_dir="D:/code/docs",
        tender_stem="招标文件",
        bid_stem="投标文件",
        tender_path="D:/code/docs/招标文件.pdf",
        bid_path="D:/code/docs/投标文件.docx",
        user_instruction="无",
        instruction="无",
    )
    assert "先建立“主体基线”" in prompt
    assert "同一主体跨全文取值一致性" in prompt
    assert "至少写出两处冲突位置和关键原文" in prompt


def test_review_second_pass_prompt_requires_subject_conflict_recheck() -> None:
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
    assert "同一主体跨全文取值不一致" in prompt
    assert "至少写出两处冲突位置和关键原文" in prompt


def test_context_requirement_fallback_keeps_structural_guard() -> None:
    report = {
        "requirements": [{"id": "R001", "category": "响应格式", "text": "投标文件应按格式填写", "source": "s"}],
        "findings": [],
        "summary": {},
    }
    guarded = _ensure_context_consistency_requirement(report)
    added = guarded["requirements"][-1]
    assert added["category"] == "主体一致性"
    assert "主体基线" in added["text"]
    assert "全文范围内保持取值一致" in added["text"]


def test_run_bid_review_default_path_keeps_model_subject_finding(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("BID_REVIEW_ENABLE_SECOND_PASS", "0")
    monkeypatch.setenv("BID_REVIEW_DOCX_OCR_REQUIRED", "0")
    monkeypatch.delenv("BID_REVIEW_ENABLE_LOCAL_SEMANTIC_GUARDS", raising=False)

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

    assert len(report["findings"]) == 1
    assert report["findings"][0]["issue"].startswith("投标人名称前后不一致")
    assert "封面第1页" in report["findings"][0]["bid_evidence"]
    assert "分项报价表第18页" in report["findings"][0]["bid_evidence"]


def test_run_bid_review_can_opt_in_local_semantic_fallbacks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("BID_REVIEW_ENABLE_SECOND_PASS", "0")
    monkeypatch.setenv("BID_REVIEW_DOCX_OCR_REQUIRED", "0")
    monkeypatch.setenv("BID_REVIEW_ENABLE_LOCAL_SEMANTIC_GUARDS", "1")
    monkeypatch.setattr(
        "app.review.claude_review._extract_docx_text",
        lambda _path: "招标人：示例招标方有限公司\n投标函\n投标人：示例招标方有限公司（盖公章）",
    )

    client = _FakeClient(
        json.dumps(
            {
                "requirements": [
                    {"id": "R001", "category": "主体一致性", "text": "主体一致性校验", "source": "s"}
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

    assert any("投标函落款处投标人名称误写为招标人名称" in f["issue"] for f in report["findings"])
    assert _apply_docx_stability_guards_from_text(
        {
            "requirements": [{"id": "R001", "category": "主体一致性", "text": "主体一致性校验", "source": "s"}],
            "findings": [],
            "summary": {},
        },
        "招标人：示例招标方有限公司\n投标函\n投标人：示例招标方有限公司（盖公章）",
    )["findings"]
