from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.harness.task_docs import TaskDocScaffoldRequest, scaffold_task_docs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scaffold task tracking docs for a repo-local long-running task.")
    parser.add_argument("task_dir", type=str, help="Target task directory, usually under tasks/<task-slug>.")
    parser.add_argument("--goal", required=True, type=str, help="High-level task goal used to seed the templates.")
    parser.add_argument(
        "--source-request",
        type=str,
        default="",
        help="Optional source request summary. Defaults to the goal text.",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite any existing task files.")
    parser.add_argument("--skip-check", action="store_true", help="Skip running scripts/check_task_docs.py after scaffold.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    task_dir = Path(args.task_dir).expanduser().resolve()
    request = TaskDocScaffoldRequest(
        task_dir=task_dir,
        goal=str(args.goal).strip(),
        source_request=str(args.source_request or args.goal).strip(),
        workspace=REPO_ROOT,
    )
    if not request.goal:
        parser.error("--goal 不能为空。")

    written = scaffold_task_docs(request, force=bool(args.force))
    for path in written:
        print(path)

    if args.skip_check:
        return 0

    check_cmd = [sys.executable, str(REPO_ROOT / "scripts" / "check_task_docs.py"), str(task_dir)]
    completed = subprocess.run(check_cmd, cwd=str(REPO_ROOT), check=False)
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
