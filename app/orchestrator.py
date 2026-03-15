from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Callable

from app.ai import create_llm_client
from app.report import write_docx_report, write_json_report, write_markdown_report
from app.report.to_json import write_raw_text
from app.runtime_paths import REVIEW_PROFILE_ENV, default_output_root, managed_runtime_enabled
from app.review import (
    detect_roles,
    detect_tender_and_bids,
    run_bid_review,
)


@dataclass
class RunArtifacts:
    output_dir: Path
    json_path: Path
    md_path: Path
    docx_path: Path
    raw_output_path: Path | None
    metrics_path: Path | None
    metrics: dict[str, Any]
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
    raw_root = (output_root or "").strip()
    if not raw_root:
        root = default_output_root()
    else:
        candidate = Path(raw_root)
        if managed_runtime_enabled() and not candidate.is_absolute() and raw_root.replace("\\", "/") == "data/output":
            root = default_output_root()
        else:
            root = candidate
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = root / f"run-{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _slugify(name: str) -> str:
    text = re.sub(r"[^\w\-\u4e00-\u9fff]+", "-", name, flags=re.UNICODE).strip("-")
    return text or "bid"


def _emit_pipeline_message(
    message: str,
    *,
    progress_callback: Callable[[str, str], None] | None = None,
    level: str = "agent",
) -> None:
    if progress_callback is not None:
        try:
            progress_callback(message, level)
        except Exception:
            pass
    try:
        print(message, file=sys.stderr, flush=True)
    except (OSError, ValueError):
        # Windowed/frozen desktop builds may expose an invalid stderr handle.
        # Progress delivery to the GUI callback must remain best-effort and non-fatal.
        pass


def run_pipeline(
    *,
    inputs: list[str],
    output_root: str | None,
    tender_path: str | None,
    bid_paths: list[str] | None,
    backend: str = "claude",
    claude_bin: str | None,
    opencode_bin: str | None = None,
    model: str | None,
    opencode_model: str | None = None,
    effort: str,
    review_profile: str = "thorough",
    show_progress: bool,
    progress_level: str,
    timeout_sec: int,
    extra_instruction: str,
    user_instruction: str,
    mcp_config: str | None = None,
    opencode_api_key: str | None = None,
    opencode_api_url: str | None = None,
    opencode_provider: str = "volcengine",
    save_raw_output: bool = True,
    workspace: str | None = None,
    progress_callback: Callable[[str, str], None] | None = None,
) -> BatchArtifacts:
    bid_paths = bid_paths or []
    if not inputs and not (tender_path and bid_paths):
        raise ValueError("至少提供 --input 文件列表，或显式指定 --tender 与一个或多个 --bid。")

    output_dir = _resolve_output_dir(output_root)
    resolved_workspace = workspace or str(Path.cwd())
    previous_review_profile = os.getenv(REVIEW_PROFILE_ENV)
    os.environ[REVIEW_PROFILE_ENV] = review_profile
    try:
        selected_backend, client = create_llm_client(
            backend=backend,
            claude_bin=claude_bin,
            opencode_bin=opencode_bin,
            model=model,
            opencode_model=opencode_model,
            effort=effort,
            show_progress=show_progress,
            progress_level=progress_level,
            timeout_sec=timeout_sec,
            workspace=resolved_workspace,
            mcp_config=mcp_config,
            opencode_api_key=opencode_api_key,
            opencode_api_url=opencode_api_url,
            opencode_provider=opencode_provider,
            progress_callback=progress_callback,
        )
    finally:
        if previous_review_profile is None:
            os.environ.pop(REVIEW_PROFILE_ENV, None)
        else:
            os.environ[REVIEW_PROFILE_ENV] = previous_review_profile
    if not client.available():
        if selected_backend == "claude":
            unavailable_reason = getattr(client, "unavailable_reason", None)
            if callable(unavailable_reason):
                detail = unavailable_reason()
                if detail:
                    raise RuntimeError(detail)
            raise RuntimeError(
                "未检测到可用的 Claude SDK 运行时。请先执行 `uv sync` 安装依赖，并配置 ANTHROPIC_AUTH_TOKEN/ANTHROPIC_API_KEY。"
            )
        unavailable_reason = getattr(client, "unavailable_reason", None)
        if callable(unavailable_reason):
            detail = unavailable_reason()
            if detail:
                raise RuntimeError(detail)
        raise RuntimeError(
            "未检测到可用的 OpenCode SDK 运行时。请先在仓库根目录执行 `npm install` 安装本地 runtime，或显式传入 --opencode-bin 使用 legacy CLI。"
        )

    if tender_path and bid_paths:
        tender_abs = str(Path(tender_path).resolve())
        bids_abs = [str(Path(x).resolve()) for x in bid_paths]
        role_reasoning = "manual"
        _emit_pipeline_message(
            f"[pipeline] backend={selected_backend}，使用手动指定的招投标角色。",
            progress_callback=progress_callback,
        )
    elif tender_path and inputs:
        tender_abs = str(Path(tender_path).resolve())
        bids_abs = [str(Path(x).resolve()) for x in inputs]
        bids_abs = [x for x in bids_abs if x != tender_abs]
        role_reasoning = "manual+tender"
        _emit_pipeline_message(
            f"[pipeline] backend={selected_backend}，使用手动指定的招标文件，自动收集投标文件。",
            progress_callback=progress_callback,
        )
    elif tender_path and not bid_paths:
        raise ValueError("已指定 --tender 时，请至少提供一个 --bid。")
    elif bid_paths and not tender_path:
        raise ValueError("已指定 --bid 时，请同时指定 --tender。")
    else:
        if len(inputs) < 2:
            raise ValueError("自动识别模式下至少需要两个文件。")
        _emit_pipeline_message(
            f"[pipeline] backend={selected_backend}，正在自动识别招标/投标文件角色...",
            progress_callback=progress_callback,
        )
        if len(inputs) == 2:
            tender_abs, bid_abs, role_reasoning = detect_roles(inputs, client)
            bids_abs = [bid_abs]
        else:
            tender_abs, bids_abs, role_reasoning = detect_tender_and_bids(inputs, client)
        _emit_pipeline_message(
            f"[pipeline] 角色识别完成：招标文件={Path(tender_abs).name}，投标文件数={len(bids_abs)}",
            progress_callback=progress_callback,
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

        _emit_pipeline_message(
            f"[pipeline] 开始审查 {idx}/{len(bids_abs)}: {Path(bid_abs).name}",
            progress_callback=progress_callback,
        )
        report, raw = run_bid_review(
            tender_path=tender_abs,
            bid_path=bid_abs,
            client=client,
            extra_instruction=extra_instruction,
            user_instruction=user_instruction,
            review_profile=review_profile,
        )
        json_path = write_json_report(report, run_subdir)
        md_path = write_markdown_report(report, run_subdir)
        docx_path = write_docx_report(report, run_subdir)
        run_metrics = getattr(client, "_last_review_metrics", {}) or {}
        metrics_path: Path | None = None
        if isinstance(run_metrics, dict) and run_metrics:
            metrics_path = run_subdir / "run_metrics.json"
            metrics_path.write_text(json.dumps(run_metrics, ensure_ascii=False, indent=2), encoding="utf-8")
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
                metrics_path=metrics_path,
                metrics=run_metrics if isinstance(run_metrics, dict) else {},
                report=report,
                role_reasoning=role_reasoning,
                tender_path=tender_abs,
                bid_path=bid_abs,
            )
        )
        _emit_pipeline_message(
            f"[pipeline] 完成审查 {idx}/{len(bids_abs)}: {Path(bid_abs).name}",
            progress_callback=progress_callback,
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
                "run_metrics": str(r.metrics_path) if r.metrics_path else None,
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
