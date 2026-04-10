from __future__ import annotations

import json
from pathlib import Path

from app.orchestrator import run_pipeline


class _FakeClient:
    def __init__(self) -> None:
        self._last_review_metrics = {}

    def available(self) -> bool:
        return True


def test_run_pipeline_uses_isolated_review_context_but_keeps_original_paths(
    monkeypatch,
    tmp_path: Path,
) -> None:
    context_root = tmp_path / "review-context"
    monkeypatch.setenv("BID_REVIEW_RUN_CONTEXT_DIR", str(context_root))

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    tender_path = source_dir / "招标文件.pdf"
    bid_path = source_dir / "投标文件.docx"
    tender_path.write_bytes(b"%PDF-1.4 isolated tender")
    bid_path.write_text("isolated bid", encoding="utf-8")

    fake_client = _FakeClient()
    create_calls: list[dict[str, object]] = []
    captured_review_paths: dict[str, str] = {}

    def _fake_create_llm_client(**kwargs):
        create_calls.append(kwargs)
        return "claude", fake_client

    def _fake_run_bid_review(**kwargs):
        captured_review_paths["tender_path"] = str(kwargs["tender_path"])
        captured_review_paths["bid_path"] = str(kwargs["bid_path"])
        return (
            {
                "requirements": [],
                "findings": [],
                "summary": {"requirement_count": 0, "finding_count": 0},
            },
            "raw-output",
        )

    def _fake_json_writer(report: dict, output_dir: Path) -> Path:
        path = output_dir / "review_result.json"
        path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
        return path

    def _fake_md_writer(report: dict, output_dir: Path) -> Path:
        path = output_dir / "review_report.md"
        path.write_text("ok", encoding="utf-8")
        return path

    def _fake_docx_writer(report: dict, output_dir: Path) -> Path:
        path = output_dir / "review_report.docx"
        path.write_text("ok", encoding="utf-8")
        return path

    def _fake_raw_writer(raw: str, output_dir: Path) -> Path:
        path = output_dir / "claude_raw_output.txt"
        path.write_text(raw, encoding="utf-8")
        return path

    monkeypatch.setattr("app.orchestrator.create_llm_client", _fake_create_llm_client)
    monkeypatch.setattr("app.orchestrator.run_bid_review", _fake_run_bid_review)
    monkeypatch.setattr("app.orchestrator.write_json_report", _fake_json_writer)
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
        workspace=str(Path.cwd()),
    )

    assert len(create_calls) == 1
    isolated_workspace = Path(str(create_calls[0]["workspace"])).resolve()
    assert isolated_workspace.is_relative_to(context_root.resolve())

    isolated_tender = Path(captured_review_paths["tender_path"]).resolve()
    isolated_bid = Path(captured_review_paths["bid_path"]).resolve()
    assert isolated_tender.is_relative_to(isolated_workspace)
    assert isolated_bid.is_relative_to(isolated_workspace)
    assert isolated_tender != tender_path.resolve()
    assert isolated_bid != bid_path.resolve()
    assert isolated_tender.read_bytes() == tender_path.read_bytes()
    assert isolated_bid.read_text(encoding="utf-8") == bid_path.read_text(encoding="utf-8")

    assert artifacts.tender_path == str(tender_path.resolve())
    assert artifacts.runs[0].bid_path == str(bid_path.resolve())

    summary = json.loads(artifacts.batch_summary_path.read_text(encoding="utf-8"))
    assert summary["tender_path"] == str(tender_path.resolve())
    assert summary["runs"][0]["bid_path"] == str(bid_path.resolve())
