from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


@dataclass
class ReviewRunData:
    bid_path: str
    output_dir: Path
    json_path: Path
    markdown_path: Path
    docx_path: Path
    raw_output_path: Path | None
    summary: dict[str, Any]
    report: dict[str, Any]


@dataclass
class BatchReviewData:
    tender_path: str
    role_reasoning: str
    output_dir: Path
    batch_summary_path: Path
    runs: list[ReviewRunData]


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _resolve_optional_path(raw_value: Any) -> Path:
    raw = str(raw_value or "").strip()
    if not raw:
        return Path("")
    return Path(raw).expanduser().resolve()


def load_batch_result(batch_summary_path: str | Path) -> BatchReviewData:
    summary_path = Path(batch_summary_path).expanduser().resolve()
    summary = _read_json(summary_path)
    runs: list[ReviewRunData] = []
    for item in summary.get("runs", []) or []:
        if not isinstance(item, dict):
            continue
        json_path = _resolve_optional_path(item.get("json"))
        report = _read_json(json_path) if str(json_path) and json_path.exists() and json_path.is_file() else {}
        raw_output = item.get("claude_raw")
        runs.append(
            ReviewRunData(
                bid_path=str(item.get("bid_path", "")),
                output_dir=_resolve_optional_path(item.get("output_dir")),
                json_path=json_path,
                markdown_path=_resolve_optional_path(item.get("markdown")),
                docx_path=_resolve_optional_path(item.get("docx")),
                raw_output_path=_resolve_optional_path(raw_output) if raw_output else None,
                summary=report.get("summary", item.get("summary", {}) or {}),
                report=report,
            )
        )
    return BatchReviewData(
        tender_path=str(summary.get("tender_path", "")),
        role_reasoning=str(summary.get("role_reasoning", "")),
        output_dir=summary_path.parent,
        batch_summary_path=summary_path,
        runs=runs,
    )


def find_latest_batch_summary(output_root: str | Path) -> Path | None:
    root = Path(output_root).expanduser()
    if not root.exists():
        return None
    candidates = sorted(root.glob("run-*/batch_summary.json"))
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime)
    return candidates[-1].resolve()
