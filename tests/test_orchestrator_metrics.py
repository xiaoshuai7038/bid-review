from __future__ import annotations

import json
from pathlib import Path

from app.orchestrator import run_pipeline


class _FakeClient:
    def __init__(self) -> None:
        self._last_review_metrics = {}

    def available(self) -> bool:
        return True


def test_run_pipeline_writes_run_metrics_json(monkeypatch, tmp_path: Path) -> None:
    tender_path = tmp_path / "tender.pdf"
    bid_path = tmp_path / "bid.docx"
    tender_path.write_bytes(b"%PDF-1.4")
    bid_path.write_text("demo", encoding="utf-8")

    fake_client = _FakeClient()

    monkeypatch.setattr(
        "app.orchestrator.create_llm_client",
        lambda **kwargs: ("claude", fake_client),
    )
    monkeypatch.setattr(
        "app.orchestrator.run_bid_review",
        lambda **kwargs: (
            {
                "requirements": [],
                "findings": [],
                "summary": {"requirement_count": 0, "finding_count": 0},
            },
            "raw-output",
        ),
    )

    def _fake_json_writer(report: dict, output_dir: Path) -> Path:
        path = output_dir / "review_result.json"
        path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
        fake_client._last_review_metrics = {"review_profile": "thorough", "prepare": {"duration_ms": 10}}
        return path

    monkeypatch.setattr("app.orchestrator.write_json_report", _fake_json_writer)

    def _fake_md_writer(report: dict, output_dir: Path) -> Path:
        path = output_dir / "review_report.md"
        path.write_text("x", encoding="utf-8")
        return path

    def _fake_docx_writer(report: dict, output_dir: Path) -> Path:
        path = output_dir / "review_report.docx"
        path.write_text("x", encoding="utf-8")
        return path

    def _fake_raw_writer(raw: str, output_dir: Path) -> Path:
        path = output_dir / "claude_raw_output.txt"
        path.write_text(raw, encoding="utf-8")
        return path

    monkeypatch.setattr("app.orchestrator.write_markdown_report", _fake_md_writer)
    monkeypatch.setattr("app.orchestrator.write_docx_report", _fake_docx_writer)
    monkeypatch.setattr("app.orchestrator.write_raw_text", _fake_raw_writer)

    artifacts = run_pipeline(
        inputs=[],
        output_root=str(tmp_path / "output"),
        tender_path=str(tender_path),
        bid_paths=[str(bid_path)],
        backend="claude",
        claude_bin=None,
        opencode_bin=None,
        model=None,
        opencode_model=None,
        effort="low",
        review_profile="thorough",
        show_progress=False,
        progress_level="agent",
        timeout_sec=60,
        extra_instruction="",
        user_instruction="",
        save_raw_output=True,
    )

    metrics_path = artifacts.output_dir / "run_metrics.json"
    assert metrics_path.exists()
    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert payload["review_profile"] == "thorough"
