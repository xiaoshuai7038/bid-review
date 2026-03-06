from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import re
import sys
from typing import Any

from app.llm import ClaudeClient
from app.report import write_docx_report, write_json_report, write_markdown_report
from app.report.to_json import write_raw_text
from app.review import (
    detect_roles_with_claude,
    detect_tender_and_bids_with_claude,
    run_bid_review_with_claude,
)


@dataclass
class RunArtifacts:
    output_dir: Path
    json_path: Path
    md_path: Path
    docx_path: Path
    raw_output_path: Path | None
    report: dict[str, Any]
    role_reasoning: str
    tender_path: str
    bid_path: str


@dataclass
class BatchArtifacts:
    output_dir: Path
    tender_path: str
    role_reasoning: str
    runs: list[RunArtifacts]
    batch_summary_path: Path


def _resolve_output_dir(output_root: str | None) -> Path:
    root = Path(output_root or "data/output")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = root / f"run-{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _slugify(name: str) -> str:
    text = re.sub(r"[^\w\-\u4e00-\u9fff]+", "-", name, flags=re.UNICODE).strip("-")
    return text or "bid"


def run_pipeline(
    *,
    inputs: list[str],
    output_root: str | None,
    tender_path: str | None,
    bid_paths: list[str] | None,
    claude_bin: str | None,
    model: str | None,
    effort: str,
    show_progress: bool,
    progress_level: str,
    timeout_sec: int,
    extra_instruction: str,
    user_instruction: str,
    mcp_config: str | None = None,
    save_raw_output: bool = True,
) -> BatchArtifacts:
    bid_paths = bid_paths or []
    if not inputs and not (tender_path and bid_paths):
        raise ValueError("至少提供 --input 文件列表，或显式指定 --tender 与一个或多个 --bid。")

    output_dir = _resolve_output_dir(output_root)
    workspace = str(Path.cwd())
    client = ClaudeClient(
        claude_bin=claude_bin,
        model=model,
        effort=effort,
        show_progress=show_progress,
        progress_level=progress_level,
        timeout_sec=timeout_sec,
        workspace=workspace,
        mcp_config=mcp_config,
    )
    if not client.available():
        raise RuntimeError("未检测到可用的 claude CLI，请先安装并登录。")

    if tender_path and bid_paths:
        tender_abs = str(Path(tender_path).resolve())
        bids_abs = [str(Path(x).resolve()) for x in bid_paths]
        role_reasoning = "manual"
        print("[pipeline] 使用手动指定的招投标角色。", file=sys.stderr, flush=True)
    elif tender_path and inputs:
        tender_abs = str(Path(tender_path).resolve())
        bids_abs = [str(Path(x).resolve()) for x in inputs]
        bids_abs = [x for x in bids_abs if x != tender_abs]
        role_reasoning = "manual+tender"
        print("[pipeline] 使用手动指定的招标文件，自动收集投标文件。", file=sys.stderr, flush=True)
    elif tender_path and not bid_paths:
        raise ValueError("已指定 --tender 时，请至少提供一个 --bid。")
    elif bid_paths and not tender_path:
        raise ValueError("已指定 --bid 时，请同时指定 --tender。")
    else:
        if len(inputs) < 2:
            raise ValueError("自动识别模式下至少需要两个文件。")
        print("[pipeline] 正在自动识别招标/投标文件角色...", file=sys.stderr, flush=True)
        if len(inputs) == 2:
            tender_abs, bid_abs, role_reasoning = detect_roles_with_claude(inputs, client)
            bids_abs = [bid_abs]
        else:
            tender_abs, bids_abs, role_reasoning = detect_tender_and_bids_with_claude(inputs, client)
        print(
            f"[pipeline] 角色识别完成：招标文件={Path(tender_abs).name}，投标文件数={len(bids_abs)}",
            file=sys.stderr,
            flush=True,
        )

    bids_abs = list(dict.fromkeys(bids_abs))
    bids_abs = [x for x in bids_abs if x != tender_abs]
    if not bids_abs:
        raise ValueError("未识别到投标文件。")

    runs: list[RunArtifacts] = []
    multi = len(bids_abs) > 1
    for idx, bid_abs in enumerate(bids_abs, start=1):
        if multi:
            run_subdir = output_dir / f"bid-{idx:03d}-{_slugify(Path(bid_abs).stem)[:40]}"
            run_subdir.mkdir(parents=True, exist_ok=True)
        else:
            run_subdir = output_dir

        print(
            f"[pipeline] 开始审查 {idx}/{len(bids_abs)}: {Path(bid_abs).name}",
            file=sys.stderr,
            flush=True,
        )
        report, raw = run_bid_review_with_claude(
            tender_path=tender_abs,
            bid_path=bid_abs,
            client=client,
            extra_instruction=extra_instruction,
            user_instruction=user_instruction,
        )
        json_path = write_json_report(report, run_subdir)
        md_path = write_markdown_report(report, run_subdir)
        docx_path = write_docx_report(report, run_subdir)
        raw_path: Path | None = None
        if save_raw_output:
            raw_path = write_raw_text(raw, run_subdir)
        runs.append(
            RunArtifacts(
                output_dir=run_subdir,
                json_path=json_path,
                md_path=md_path,
                docx_path=docx_path,
                raw_output_path=raw_path,
                report=report,
                role_reasoning=role_reasoning,
                tender_path=tender_abs,
                bid_path=bid_abs,
            )
        )
        print(
            f"[pipeline] 完成审查 {idx}/{len(bids_abs)}: {Path(bid_abs).name}",
            file=sys.stderr,
            flush=True,
        )

    summary_obj = {
        "tender_path": tender_abs,
        "bid_count": len(runs),
        "role_reasoning": role_reasoning,
        "runs": [
            {
                "bid_path": r.bid_path,
                "output_dir": str(r.output_dir),
                "json": str(r.json_path),
                "markdown": str(r.md_path),
                "docx": str(r.docx_path),
                "claude_raw": str(r.raw_output_path) if r.raw_output_path else None,
                "summary": r.report.get("summary", {}),
            }
            for r in runs
        ],
    }
    batch_summary_path = output_dir / "batch_summary.json"
    batch_summary_path.write_text(json.dumps(summary_obj, ensure_ascii=False, indent=2), encoding="utf-8")

    return BatchArtifacts(
        output_dir=output_dir,
        tender_path=tender_abs,
        role_reasoning=role_reasoning,
        runs=runs,
        batch_summary_path=batch_summary_path,
    )
