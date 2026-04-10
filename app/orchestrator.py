from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import sys
from typing import Any, Callable
from uuid import uuid4

from app.ai import create_llm_client
from app.ai.mcp.project_config import build_project_mcp_config_json
from app.report import write_docx_report, write_json_report, write_markdown_report
from app.report.to_json import write_raw_text
from app.runtime_paths import (
    REVIEW_PROFILE_ENV,
    default_output_root,
    default_run_context_root,
    ensure_dir,
    managed_runtime_enabled,
)
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


@dataclass
class ReviewRunContext:
    root: Path
    path_map: dict[str, str]


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


def _resolve_input_paths(paths: list[str] | None) -> list[str]:
    resolved: list[str] = []
    seen: set[str] = set()
    for raw in paths or []:
        text = str(raw or "").strip()
        if not text:
            continue
        path = str(Path(text).expanduser().resolve())
        if path in seen:
            continue
        seen.add(path)
        resolved.append(path)
    return resolved


def _link_or_copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        if target.exists():
            target.unlink()
        os.link(source, target)
        return
    except OSError:
        pass
    shutil.copy2(source, target)


def _build_review_run_context(file_paths: list[str]) -> ReviewRunContext | None:
    if not file_paths:
        return None
    context_base = ensure_dir(default_run_context_root())
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    context_root = ensure_dir(context_base / f"run-{stamp}-{uuid4().hex[:8]}")
    path_map: dict[str, str] = {}
    for index, raw in enumerate(file_paths, start=1):
        source = Path(raw).expanduser().resolve()
        source_text = str(source)
        if not source.exists() or not source.is_file():
            path_map[source_text] = source_text
            continue
        target = (context_root / "inputs" / f"{index:03d}" / source.name).resolve()
        _link_or_copy_file(source, target)
        path_map[source_text] = str(target)
    return ReviewRunContext(root=context_root, path_map=path_map)


def _now_iso(value: datetime | None = None) -> str:
    return (value or datetime.now()).isoformat(timespec="seconds")


def _write_run_manifest(output_dir: Path, manifest: dict[str, Any]) -> Path:
    path = output_dir / "run_manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


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
    input_paths_abs = _resolve_input_paths(inputs)
    bid_paths_abs = _resolve_input_paths(bid_paths)
    tender_path_abs = str(Path(tender_path).expanduser().resolve()) if tender_path else None
    explicit_context_paths = _resolve_input_paths(
        [*input_paths_abs, *bid_paths_abs, *([tender_path_abs] if tender_path_abs else [])]
    )
    run_context = _build_review_run_context(explicit_context_paths)
    effective_workspace = str(run_context.root) if run_context is not None else resolved_workspace
    effective_mcp_config = mcp_config or build_project_mcp_config_json(resolved_workspace)
    started_at = datetime.now()
    manifest: dict[str, Any] = {
        "kind": "review",
        "schema_version": 1,
        "run_id": output_dir.name,
        "output_dir": str(output_dir),
        "started_at": _now_iso(started_at),
        "completed_at": "",
        "status": "running",
        "failed_stage": "",
        "error": None,
        "backend": {
            "requested_backend": backend,
            "selected_backend": "",
            "model": model or "",
            "opencode_model": opencode_model or "",
            "effort": effort,
            "review_profile": review_profile,
            "timeout_sec": timeout_sec,
            "show_progress": show_progress,
            "progress_level": progress_level,
        },
        "runtime": {
            "requested_workspace": resolved_workspace,
            "effective_workspace": effective_workspace,
            "run_context_root": str(run_context.root) if run_context is not None else "",
            "managed_runtime_enabled": managed_runtime_enabled(),
            "mcp_config_source": "explicit" if mcp_config else "project-default",
        },
        "inputs": {
            "requested_inputs": input_paths_abs,
            "explicit_tender_path": tender_path_abs or "",
            "explicit_bid_paths": bid_paths_abs,
            "run_context_path_map": dict(run_context.path_map) if run_context is not None else {},
        },
        "selection": {
            "role_reasoning": "",
            "tender_path": "",
            "bid_paths": [],
        },
        "runs": [],
    }
    current_stage = "client_setup"
    current_run_record: dict[str, Any] | None = None

    def finalize_manifest(*, status: str, failed_stage: str = "", error: Exception | None = None) -> None:
        manifest["status"] = status
        manifest["failed_stage"] = failed_stage
        manifest["completed_at"] = _now_iso()
        if error is not None:
            manifest["error"] = {
                "type": error.__class__.__name__,
                "message": str(error),
            }
            if current_run_record is not None and current_run_record.get("status") == "running":
                current_run_record["status"] = "failed"
                current_run_record["error"] = manifest["error"]
        _write_run_manifest(output_dir, manifest)

    previous_review_profile = os.getenv(REVIEW_PROFILE_ENV)
    os.environ[REVIEW_PROFILE_ENV] = review_profile
    try:
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
                workspace=effective_workspace,
                mcp_config=effective_mcp_config,
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

        manifest["backend"]["selected_backend"] = selected_backend
        if run_context is not None:
            _emit_pipeline_message(
                f"[pipeline] 已启用隔离运行目录：{run_context.root}",
                progress_callback=progress_callback,
                level="basic",
            )

        current_stage = "availability_check"
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

        def to_context_path(path: str | None) -> str | None:
            if path is None:
                return None
            return run_context.path_map.get(path, path) if run_context is not None else path

        def to_source_path(path: str | None) -> str | None:
            if path is None or run_context is None:
                return path
            for original, isolated in run_context.path_map.items():
                if isolated == path:
                    return original
            return path

        inputs_ctx = [str(to_context_path(path)) for path in input_paths_abs]
        bid_paths_ctx = [str(to_context_path(path)) for path in bid_paths_abs]
        tender_ctx = str(to_context_path(tender_path_abs)) if tender_path_abs else None
        current_stage = "role_resolution"

        if tender_ctx and bid_paths_ctx:
            tender_abs = tender_ctx
            bids_abs = bid_paths_ctx
            role_reasoning = "manual"
            _emit_pipeline_message(
                f"[pipeline] backend={selected_backend}，使用手动指定的招投标角色。",
                progress_callback=progress_callback,
            )
        elif tender_ctx and inputs_ctx:
            tender_abs = tender_ctx
            bids_abs = list(inputs_ctx)
            bids_abs = [x for x in bids_abs if x != tender_abs]
            role_reasoning = "manual+tender"
            _emit_pipeline_message(
                f"[pipeline] backend={selected_backend}，使用手动指定的招标文件，自动收集投标文件。",
                progress_callback=progress_callback,
            )
        elif tender_ctx and not bid_paths_ctx:
            raise ValueError("已指定 --tender 时，请至少提供一个 --bid。")
        elif bid_paths_ctx and not tender_ctx:
            raise ValueError("已指定 --bid 时，请同时指定 --tender。")
        else:
            if len(inputs_ctx) < 2:
                raise ValueError("自动识别模式下至少需要两个文件。")
            _emit_pipeline_message(
                f"[pipeline] backend={selected_backend}，正在自动识别招标/投标文件角色...",
                progress_callback=progress_callback,
            )
            if len(inputs_ctx) == 2:
                tender_abs, bid_abs, role_reasoning = detect_roles(inputs_ctx, client)
                bids_abs = [bid_abs]
            else:
                tender_abs, bids_abs, role_reasoning = detect_tender_and_bids(inputs_ctx, client)
            _emit_pipeline_message(
                f"[pipeline] 角色识别完成：招标文件={Path(to_source_path(tender_abs) or tender_abs).name}，投标文件数={len(bids_abs)}",
                progress_callback=progress_callback,
            )

        bids_abs = list(dict.fromkeys(bids_abs))
        bids_abs = [x for x in bids_abs if x != tender_abs]
        if not bids_abs:
            raise ValueError("未识别到投标文件。")
        tender_source_abs = str(to_source_path(tender_abs) or tender_abs)
        bids_source_abs = [str(to_source_path(path) or path) for path in bids_abs]
        manifest["selection"] = {
            "role_reasoning": role_reasoning,
            "tender_path": tender_source_abs,
            "bid_paths": bids_source_abs,
        }

        runs: list[RunArtifacts] = []
        multi = len(bids_abs) > 1
        current_stage = "review"
        for idx, (bid_abs, bid_source_abs) in enumerate(zip(bids_abs, bids_source_abs), start=1):
            if multi:
                run_subdir = output_dir / f"bid-{idx:03d}-{_slugify(Path(bid_source_abs).stem)[:40]}"
                run_subdir.mkdir(parents=True, exist_ok=True)
            else:
                run_subdir = output_dir

            current_run_record = {
                "index": idx,
                "bid_path": bid_source_abs,
                "tender_path": tender_source_abs,
                "isolated_bid_path": bid_abs,
                "isolated_tender_path": tender_abs,
                "status": "running",
                "output_dir": str(run_subdir),
                "json": "",
                "markdown": "",
                "docx": "",
                "claude_raw": "",
                "run_metrics": "",
                "summary": {},
            }
            manifest["runs"].append(current_run_record)

            _emit_pipeline_message(
                f"[pipeline] 开始审查 {idx}/{len(bids_abs)}: {Path(bid_source_abs).name}",
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
            current_stage = "report_export"
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
            current_run_record.update(
                {
                    "status": "completed",
                    "json": str(json_path),
                    "markdown": str(md_path),
                    "docx": str(docx_path),
                    "claude_raw": str(raw_path) if raw_path else "",
                    "run_metrics": str(metrics_path) if metrics_path else "",
                    "summary": report.get("summary", {}),
                }
            )
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
                    tender_path=tender_source_abs,
                    bid_path=bid_source_abs,
                )
            )
            _emit_pipeline_message(
                f"[pipeline] 完成审查 {idx}/{len(bids_abs)}: {Path(bid_source_abs).name}",
                progress_callback=progress_callback,
            )
            current_stage = "review"
            current_run_record = None

        current_stage = "summary_write"
        summary_obj = {
            "tender_path": tender_source_abs,
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
        finalize_manifest(status="completed")

        return BatchArtifacts(
            output_dir=output_dir,
            tender_path=tender_source_abs,
            role_reasoning=role_reasoning,
            runs=runs,
            batch_summary_path=batch_summary_path,
        )
    except Exception as exc:
        finalize_manifest(status="failed", failed_stage=current_stage, error=exc)
        raise
