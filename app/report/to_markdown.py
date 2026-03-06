from __future__ import annotations

from pathlib import Path
from typing import Any


def _safe(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("\n", " ").replace("|", "\\|").strip()


def _status_zh(status: Any) -> str:
    mapping = {
        "non_compliant": "不符合",
        "risk": "风险",
        "needs_manual": "需人工复核",
    }
    return mapping.get(str(status or "").strip(), str(status or "").strip())


def build_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    requirements = report.get("requirements", []) or []
    findings = report.get("findings", []) or []

    lines: list[str] = []
    lines.append("# 标书审查报告")
    lines.append("")
    lines.append("## 概览")
    lines.append("")
    lines.append(f"- 硬性要求数: {summary.get('requirement_count', len(requirements))}")
    lines.append(f"- 不符合项数: {summary.get('non_compliant_count', '')}")
    lines.append(f"- 风险项数: {summary.get('risk_count', '')}")
    lines.append(f"- 需人工复核数: {summary.get('needs_manual_count', '')}")
    lines.append(f"- 总发现数: {summary.get('finding_count', len(findings))}")
    lines.append("")

    lines.append("## 发现项明细")
    lines.append("")
    lines.append("| ID | 条款ID | 结论 | 问题 | 招标证据 | 投标证据 | 建议 |")
    lines.append("|---|---|---|---|---|---|---|")
    if findings:
        for f in findings:
            lines.append(
                "| "
                + " | ".join(
                    [
                        _safe(f.get("id")),
                        _safe(f.get("requirement_id")),
                        _safe(_status_zh(f.get("status"))),
                        _safe(f.get("issue")),
                        _safe(f.get("tender_evidence")),
                        _safe(f.get("bid_evidence")),
                        _safe(f.get("recommendation")),
                    ]
                )
                + " |"
            )
    else:
        lines.append("| - | - | - | 未返回发现项 | - | - | - |")
    lines.append("")

    lines.append("## 硬性要求清单")
    lines.append("")
    lines.append("| 条款ID | 类别 | 内容 | 来源 |")
    lines.append("|---|---|---|---|")
    if requirements:
        for r in requirements:
            lines.append(
                "| "
                + " | ".join(
                    [
                        _safe(r.get("id")),
                        _safe(r.get("category", "")),
                        _safe(r.get("text")),
                        _safe(r.get("source")),
                    ]
                )
                + " |"
            )
    else:
        lines.append("| - | - | 未返回硬性要求 | - |")
    lines.append("")
    return "\n".join(lines)


def write_markdown_report(report: dict[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    out = output_dir / "review_report.md"
    out.write_text(build_markdown(report), encoding="utf-8")
    return out
