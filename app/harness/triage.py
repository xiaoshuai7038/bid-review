from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON payload must be an object: {path}")
    return payload


def _resolve_path(root: Path, raw: str | None) -> Path | None:
    text = str(raw or "").strip()
    if not text:
        return None
    candidate = Path(text).expanduser()
    if candidate.is_absolute():
        return candidate.resolve(strict=False)
    return (root / candidate).resolve(strict=False)


def _summarize_harness_run(root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    results = manifest.get("results", [])
    case_summaries: list[dict[str, Any]] = []
    issues: list[str] = []
    missing_artifact_count = 0

    for item in results if isinstance(results, list) else []:
        if not isinstance(item, dict):
            continue
        output_dir = _resolve_path(root, str(item.get("output_dir", "") or ""))
        stdout_path = _resolve_path(root, str(item.get("stdout_path", "") or ""))
        stderr_path = _resolve_path(root, str(item.get("stderr_path", "") or ""))
        result_path = _resolve_path(root, str(item.get("result_path", "") or ""))
        artifact_checks = {
            "output_dir": bool(output_dir and output_dir.exists()),
            "stdout": bool(stdout_path and stdout_path.exists()),
            "stderr": bool(stderr_path and stderr_path.exists()),
            "result": bool(result_path and result_path.exists()),
        }
        missing = [label for label, ok in artifact_checks.items() if not ok]
        missing_artifact_count += len(missing)
        if missing:
            issues.append(f"case `{item.get('name', 'unknown')}` missing artifacts: {', '.join(missing)}")
        if not item.get("success", False):
            failed_checks = [
                f"{check.get('kind')}={check.get('expected')}"
                for check in item.get("checks", [])
                if isinstance(check, dict) and not bool(check.get("ok"))
            ]
            if failed_checks:
                issues.append(f"case `{item.get('name', 'unknown')}` failed checks: {', '.join(failed_checks)}")
        case_summaries.append(
            {
                "name": str(item.get("name", "") or ""),
                "status": "passed" if bool(item.get("success")) else "failed",
                "exit_code": int(item.get("exit_code", 0) or 0),
                "duration_ms": int(item.get("duration_ms", 0) or 0),
                "output_dir": str(output_dir) if output_dir is not None else "",
                "result_path": str(result_path) if result_path is not None else "",
                "missing_artifacts": missing,
            }
        )

    failed_cases = [case["name"] for case in case_summaries if case["status"] != "passed"]
    return {
        "kind": "harness",
        "path": str(root),
        "status": "completed" if bool(manifest.get("success", False)) else "failed",
        "manifest_path": str((root / "run_manifest.json").resolve()),
        "run_id": str(manifest.get("run_id", "") or root.name),
        "case_count": len(case_summaries),
        "passed_count": int(manifest.get("passed_count", len(case_summaries) - len(failed_cases)) or 0),
        "failed_count": int(manifest.get("failed_count", len(failed_cases)) or 0),
        "duration_ms": int(manifest.get("duration_ms", 0) or 0),
        "selected_cases": [str(item) for item in manifest.get("selected_cases", []) if str(item).strip()],
        "failed_cases": failed_cases,
        "missing_artifact_count": missing_artifact_count,
        "cases": case_summaries,
        "issues": issues,
    }


def _summarize_review_run(root: Path, manifest: dict[str, Any] | None, batch_summary: dict[str, Any] | None) -> dict[str, Any]:
    runs_source = []
    if isinstance(batch_summary, dict):
        runs_source = batch_summary.get("runs", [])
    elif isinstance(manifest, dict):
        runs_source = manifest.get("runs", [])

    run_summaries: list[dict[str, Any]] = []
    issues: list[str] = []
    missing_artifact_count = 0

    for index, item in enumerate(runs_source if isinstance(runs_source, list) else [], start=1):
        if not isinstance(item, dict):
            continue
        bid_path = str(item.get("bid_path", "") or "")
        json_path = _resolve_path(root, str(item.get("json", "") or item.get("json_path", "") or ""))
        markdown_path = _resolve_path(root, str(item.get("markdown", "") or item.get("md_path", "") or ""))
        docx_path = _resolve_path(root, str(item.get("docx", "") or item.get("docx_path", "") or ""))
        raw_path = _resolve_path(root, str(item.get("claude_raw", "") or item.get("raw_output_path", "") or ""))
        metrics_path = _resolve_path(root, str(item.get("run_metrics", "") or item.get("metrics_path", "") or ""))
        output_dir = _resolve_path(root, str(item.get("output_dir", "") or ""))
        artifact_checks = {
            "json": bool(json_path and json_path.exists()),
            "markdown": bool(markdown_path and markdown_path.exists()),
            "docx": bool(docx_path and docx_path.exists()),
            "raw_output": bool(raw_path and raw_path.exists()) if raw_path is not None else False,
            "run_metrics": bool(metrics_path and metrics_path.exists()) if metrics_path is not None else False,
        }
        missing = [label for label, ok in artifact_checks.items() if not ok]
        missing_artifact_count += len(missing)
        if missing:
            issues.append(f"run `{Path(bid_path).name or index}` missing artifacts: {', '.join(missing)}")
        summary = item.get("summary", {})
        run_status = str(item.get("status", "completed") or "completed")
        if run_status != "completed":
            issues.append(f"run `{Path(bid_path).name or index}` status={run_status}")
        run_summaries.append(
            {
                "index": index,
                "bid_path": bid_path,
                "status": run_status,
                "output_dir": str(output_dir) if output_dir is not None else "",
                "requirement_count": int((summary or {}).get("requirement_count", 0) or 0),
                "finding_count": int((summary or {}).get("finding_count", 0) or 0),
                "missing_artifacts": missing,
                "raw_output_path": str(raw_path) if raw_path is not None else "",
                "metrics_path": str(metrics_path) if metrics_path is not None else "",
            }
        )

    backend_info = manifest.get("backend", {}) if isinstance(manifest, dict) else {}
    selection = manifest.get("selection", {}) if isinstance(manifest, dict) else {}
    status = str((manifest or {}).get("status", "") or ("completed" if batch_summary else "unknown"))
    failed_stage = str((manifest or {}).get("failed_stage", "") or "")
    error_info = (manifest or {}).get("error", {}) if isinstance(manifest, dict) else {}
    if failed_stage:
        issues.append(f"run failed_stage={failed_stage}")
    if isinstance(error_info, dict) and error_info.get("message"):
        issues.append(f"error: {error_info.get('message')}")

    return {
        "kind": "review",
        "path": str(root),
        "status": status,
        "manifest_path": str((root / "run_manifest.json").resolve()) if (root / "run_manifest.json").exists() else "",
        "batch_summary_path": str((root / "batch_summary.json").resolve()) if (root / "batch_summary.json").exists() else "",
        "run_id": str((manifest or {}).get("run_id", "") or root.name),
        "backend": str(backend_info.get("selected_backend", backend_info.get("requested_backend", "")) or ""),
        "model": str(backend_info.get("model", backend_info.get("opencode_model", "")) or ""),
        "review_profile": str(backend_info.get("review_profile", "") or ""),
        "role_reasoning": str((batch_summary or {}).get("role_reasoning", selection.get("role_reasoning", "")) or ""),
        "tender_path": str((batch_summary or {}).get("tender_path", selection.get("tender_path", "")) or ""),
        "bid_count": int((batch_summary or {}).get("bid_count", len(run_summaries)) or len(run_summaries)),
        "failed_stage": failed_stage,
        "missing_artifact_count": missing_artifact_count,
        "runs": run_summaries,
        "issues": issues,
    }


def summarize_target(target: Path | str) -> dict[str, Any]:
    raw_target = Path(target).expanduser().resolve()
    root = raw_target.parent if raw_target.is_file() else raw_target
    manifest_path = root / "run_manifest.json"
    summary_path = root / "batch_summary.json"
    manifest = _load_json(manifest_path) if manifest_path.exists() else None
    batch_summary = _load_json(summary_path) if summary_path.exists() else None

    manifest_kind = str((manifest or {}).get("kind", "") or "")
    if manifest_kind == "harness" or (manifest and "selected_cases" in manifest and "results" in manifest):
        return _summarize_harness_run(root, manifest or {})
    if manifest_kind == "review" or batch_summary is not None:
        return _summarize_review_run(root, manifest, batch_summary)
    raise FileNotFoundError(f"Unable to determine harness/review run type from: {root}")


def render_summary(summary: dict[str, Any], *, output_format: str) -> str:
    if output_format == "json":
        return json.dumps(summary, ensure_ascii=False, indent=2)

    lines = [
        f"kind: {summary.get('kind', '')}",
        f"path: {summary.get('path', '')}",
        f"status: {summary.get('status', '')}",
    ]
    if summary.get("manifest_path"):
        lines.append(f"manifest_path: {summary.get('manifest_path', '')}")

    if summary.get("kind") == "harness":
        lines.extend(
            [
                f"case_count: {summary.get('case_count', 0)}",
                f"failed_count: {summary.get('failed_count', 0)}",
                f"missing_artifact_count: {summary.get('missing_artifact_count', 0)}",
            ]
        )
        failed_cases = summary.get("failed_cases", [])
        if failed_cases:
            lines.append("failed_cases:")
            for name in failed_cases:
                lines.append(f"- {name}")
    else:
        lines.extend(
            [
                f"backend: {summary.get('backend', '')}",
                f"review_profile: {summary.get('review_profile', '')}",
                f"role_reasoning: {summary.get('role_reasoning', '')}",
                f"bid_count: {summary.get('bid_count', 0)}",
                f"failed_stage: {summary.get('failed_stage', 'none') or 'none'}",
                f"missing_artifact_count: {summary.get('missing_artifact_count', 0)}",
            ]
        )

    issues = summary.get("issues", [])
    if issues:
        lines.append("issues:")
        for issue in issues:
            lines.append(f"- {issue}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Summarize a harness run or review run directory.")
    parser.add_argument("target", type=str, help="Run directory, run_manifest.json, or batch_summary.json to inspect.")
    parser.add_argument("--format", choices=["text", "json"], default="text", help="Output format.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    summary = summarize_target(args.target)
    print(render_summary(summary, output_format=args.format))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
