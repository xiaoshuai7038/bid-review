from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from app.harness.triage import render_summary, summarize_target


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_summarize_sample_harness_run() -> None:
    root = _repo_root() / "harness" / "fixtures" / "sample-harness-run"

    summary = summarize_target(root)

    assert summary["kind"] == "harness"
    assert summary["failed_count"] == 1
    assert summary["failed_cases"] == ["gui-smoke"]
    assert summary["missing_artifact_count"] == 0
    text = render_summary(summary, output_format="text")
    assert "kind: harness" in text
    assert "gui-smoke" in text


def test_summarize_sample_review_run_and_cli_json_output() -> None:
    root = _repo_root() / "harness" / "fixtures" / "sample-review-run"

    summary = summarize_target(root)

    assert summary["kind"] == "review"
    assert summary["backend"] == "claude"
    assert summary["bid_count"] == 1
    assert summary["missing_artifact_count"] == 1

    completed = subprocess.run(
        [sys.executable, "scripts/triage_run.py", str(root), "--format", "json"],
        cwd=str(_repo_root()),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["kind"] == "review"
    assert payload["missing_artifact_count"] == 1
