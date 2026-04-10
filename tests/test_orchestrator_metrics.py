from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.orchestrator import run_pipeline


class _FakeClient:
    def __init__(self) -> None:
        self._last_review_metrics = {}

    def available(self) -> bool:
        return True


def _seed_pipeline(monkeypatch: pytest.MonkeyPatch, fake_client: _FakeClient, *, raise_review: bool = False) -> None:
    monkeypatch.setattr(
        "app.orchestrator.create_llm_client",
        lambda **kwargs: ("claude", fake_client),
    )

    def _fake_review(**kwargs):
        if raise_review:
            raise RuntimeError("review exploded")
        return (
            {
                "requirements": [],
                "findings": [],
                "summary": {"requirement_count": 0, "finding_count": 0},
            },
            "raw-output",
        )

    monkeypatch.setattr("app.orchestrator.run_bid_review", _fake_review)

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


def test_run_pipeline_writes_run_metrics_and_manifest_on_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    tender_path = tmp_path / "tender.pdf"
    bid_path = tmp_path / "bid.docx"
    tender_path.write_bytes(b"%PDF-1.4")
    bid_path.write_text("demo", encoding="utf-8")

    fake_client = _FakeClient()
    _seed_pipeline(monkeypatch, fake_client)

    artifacts = run_pipeline(
        inputs=[],
        output_root=str(tmp_path / "output"),
        tender_path=str(tender_path),
        bid_paths=[str(bid_path)],
        backend="claude",
        claude_bin=None,
        opencode_bin=None,
        model="demo-model",
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
    manifest_path = artifacts.output_dir / "run_manifest.json"
    assert metrics_path.exists()
    assert manifest_path.exists()

    metrics_payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert metrics_payload["review_profile"] == "thorough"
    assert manifest_payload["kind"] == "review"
    assert manifest_payload["status"] == "completed"
    assert manifest_payload["backend"]["selected_backend"] == "claude"
    assert manifest_payload["backend"]["model"] == "demo-model"
    assert manifest_payload["selection"]["role_reasoning"] == "manual"
    assert manifest_payload["selection"]["tender_path"] == str(tender_path.resolve())
    assert manifest_payload["selection"]["bid_paths"] == [str(bid_path.resolve())]
    assert manifest_payload["runs"][0]["status"] == "completed"


def test_run_pipeline_writes_failed_manifest_when_review_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    tender_path = tmp_path / "tender.pdf"
    bid_path = tmp_path / "bid.docx"
    tender_path.write_bytes(b"%PDF-1.4")
    bid_path.write_text("demo", encoding="utf-8")

    fake_client = _FakeClient()
    _seed_pipeline(monkeypatch, fake_client, raise_review=True)

    with pytest.raises(RuntimeError, match="review exploded"):
        run_pipeline(
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

    run_dirs = list((tmp_path / "output").glob("run-*"))
    assert len(run_dirs) == 1
    manifest_payload = json.loads((run_dirs[0] / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest_payload["kind"] == "review"
    assert manifest_payload["status"] == "failed"
    assert manifest_payload["failed_stage"] == "review"
    assert manifest_payload["error"]["message"] == "review exploded"
    assert manifest_payload["runs"][0]["status"] == "failed"
