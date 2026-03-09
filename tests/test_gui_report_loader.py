from __future__ import annotations

import json
from pathlib import Path

from app.gui.services.report_loader import load_batch_result


def test_load_batch_result_reads_review_reports(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-20260309-000001"
    bid_dir = run_dir / "bid-001-demo"
    bid_dir.mkdir(parents=True)
    review_json = bid_dir / "review_report.json"
    review_json.write_text(
        json.dumps(
            {
                "summary": {
                    "requirement_count": 12,
                    "non_compliant_count": 1,
                    "risk_count": 2,
                    "needs_manual_count": 3,
                },
                "findings": [{"id": "F-1", "status": "risk", "issue": "示例"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    batch_summary = run_dir / "batch_summary.json"
    batch_summary.write_text(
        json.dumps(
            {
                "tender_path": r"D:\docs\tender.pdf",
                "role_reasoning": "manual",
                "runs": [
                    {
                        "bid_path": r"D:\docs\bid-a.docx",
                        "output_dir": str(bid_dir),
                        "json": str(review_json),
                        "markdown": str(bid_dir / "review_report.md"),
                        "docx": str(bid_dir / "review_report.docx"),
                        "claude_raw": str(bid_dir / "claude_raw_output.txt"),
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = load_batch_result(batch_summary)

    assert result.tender_path == r"D:\docs\tender.pdf"
    assert len(result.runs) == 1
    assert result.runs[0].summary["risk_count"] == 2
    assert result.runs[0].report["findings"][0]["id"] == "F-1"

