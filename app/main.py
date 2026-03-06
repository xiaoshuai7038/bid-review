from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from app.orchestrator import run_pipeline


def _read_instruction(arg_val: str | None) -> str:
    if not arg_val:
        return ""
    p = Path(arg_val)
    if p.exists() and p.is_file():
        return p.read_text(encoding="utf-8", errors="ignore")
    return arg_val


def _merge_non_empty(parts: list[str]) -> str:
    return "\n\n".join([p.strip() for p in parts if p and p.strip()])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="将招标/投标文件交给 Claude CLI 执行标书审查并输出报告。"
    )
    parser.add_argument(
        "--input",
        action="append",
        default=[],
        help="输入文件路径，可重复传入。若不指定 --tender/--bid，会由 Claude 自动识别角色（支持1招标+N投标）。",
    )
    parser.add_argument("--tender", type=str, default=None, help="招标文件路径。")
    parser.add_argument("--bid", action="append", default=[], help="投标文件路径，可重复传入多个。")
    parser.add_argument("--output-dir", type=str, default="data/output", help="输出目录根路径。")
    parser.add_argument(
        "--claude-bin",
        type=str,
        default=None,
        help="可选，claude 可执行文件路径（例如 C:/Users/<you>/AppData/Roaming/npm/claude.cmd）。",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="可选，覆盖 Claude CLI 默认模型配置。",
    )
    parser.add_argument(
        "--effort",
        type=str,
        default="low",
        choices=["low", "medium", "high"],
        help="Claude 推理强度。",
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="关闭调用 Claude CLI 时的实时进度输出。",
    )
    parser.add_argument(
        "--progress-level",
        type=str,
        default="agent",
        choices=["agent", "basic", "normal", "detailed", "events", "raw"],
        help="进度输出详细度：agent=阶段化进度(推荐)，basic=心跳/完成，normal=工具调用，detailed=完整中间片段，events=原始事件(过滤delta碎片)，raw=原始事件全量透传。",
    )
    parser.add_argument("--timeout-sec", type=int, default=1800, help="单次 Claude 调用超时时间（秒）。")
    parser.add_argument(
        "--instruction",
        type=str,
        default="",
        help="附加任务指令文本，或指向一个文本文件路径。",
    )
    parser.add_argument(
        "--user-instruction",
        type=str,
        default="",
        help="用户个人指令文本，或指向一个文本文件路径。会与系统提示词一起传给 Claude。",
    )
    parser.add_argument(
        "--mcp-config",
        type=str,
        default=None,
        help="可选，传给 claude --mcp-config 的配置文件或JSON字符串。",
    )
    parser.add_argument(
        "--no-raw-output",
        action="store_true",
        help="不保存 claude_raw_output.txt（默认会保存，便于排查）。",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    instruction = _read_instruction(args.instruction)
    user_instruction_cli = _read_instruction(args.user_instruction)
    user_instruction_env = _read_instruction(os.getenv("BID_REVIEW_USER_INSTRUCTION", ""))
    user_instruction = _merge_non_empty([user_instruction_env, user_instruction_cli])
    try:
        artifacts = run_pipeline(
            inputs=args.input,
            output_root=args.output_dir,
            tender_path=args.tender,
            bid_paths=args.bid,
            claude_bin=args.claude_bin,
            model=args.model,
            effort=args.effort,
            show_progress=not args.no_progress,
            progress_level=args.progress_level,
            timeout_sec=args.timeout_sec,
            extra_instruction=instruction,
            user_instruction=user_instruction,
            mcp_config=args.mcp_config,
            save_raw_output=not args.no_raw_output,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    print("=== Bid Review Completed ===")
    print(f"tender: {artifacts.tender_path}")
    print(f"role_reasoning: {artifacts.role_reasoning}")
    print(f"output_dir: {artifacts.output_dir}")
    print(f"batch_summary: {artifacts.batch_summary_path}")
    print(f"bid_count: {len(artifacts.runs)}")
    for idx, run in enumerate(artifacts.runs, start=1):
        print(f"[{idx}] bid: {run.bid_path}")
        print(f"    json: {run.json_path}")
        print(f"    markdown: {run.md_path}")
        print(f"    docx: {run.docx_path}")
        print(f"    claude_raw: {run.raw_output_path if run.raw_output_path else 'disabled'}")
        print(f"    summary: {json.dumps(run.report.get('summary', {}), ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
