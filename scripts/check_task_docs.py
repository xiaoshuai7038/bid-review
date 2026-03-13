from __future__ import annotations

import re
import sys
from pathlib import Path


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _require(text: str, needle: str, issues: list[str], label: str) -> None:
    if needle not in text:
        issues.append(f"{label}: missing `{needle}`")


def _require_pattern(text: str, pattern: str, issues: list[str], label: str, desc: str) -> None:
    if re.search(pattern, text, flags=re.MULTILINE) is None:
        issues.append(f"{label}: missing {desc}")


def _check_contract(path: Path, issues: list[str]) -> None:
    text = _read(path)
    label = path.name
    for needle in [
        "Goal:",
        "Desired Effect:",
        "Non-goals:",
        "Deliverables:",
        "Done When:",
        "Validation:",
        "Review Gates:",
    ]:
        _require(text, needle, issues, label)
    _require_pattern(text, r"\bCHG-\d+\b", issues, label, "change-unit IDs like CHG-1")
    _require_pattern(text, r"\bDW-\d+\b", issues, label, "done-when IDs like DW-1")
    _require(text, "Traceability:", issues, label)


def _check_plan(path: Path, issues: list[str]) -> None:
    text = _read(path)
    label = path.name
    _require(text, "Source of truth:", issues, label)
    _require(text, "Goal summary:", issues, label)
    _require_pattern(text, r"^##\s*M\d+", issues, label, "milestone headings like `## M1`")
    _require_pattern(text, r"\bCHG-\d+\b", issues, label, "change-unit references")
    _require(text, "Acceptance:", issues, label)


def _check_status(path: Path, issues: list[str]) -> None:
    text = _read(path)
    label = path.name
    for needle in [
        "Status:",
        "Current phase:",
        "Document self-check gate status:",
        "Latest update:",
        "Change-unit status:",
        "Validation log:",
    ]:
        _require(text, needle, issues, label)


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    if len(argv) != 1:
        print("usage: python scripts/check_task_docs.py <task-dir>", file=sys.stderr)
        return 2
    task_dir = Path(argv[0]).expanduser().resolve()
    if not task_dir.exists() or not task_dir.is_dir():
        print(f"[FAIL] task dir not found: {task_dir}", file=sys.stderr)
        return 1

    contract = task_dir / "contract.md"
    plan = task_dir / "plan.md"
    status = task_dir / "status.md"
    issues: list[str] = []
    for path in (contract, plan, status):
        if not path.exists():
            issues.append(f"missing file: {path.name}")
    if not issues:
        _check_contract(contract, issues)
        _check_plan(plan, issues)
        _check_status(status, issues)

    if issues:
        print("[FAIL]")
        for issue in issues:
            print(f"- {issue}")
        return 1
    print(f"[OK] {task_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
