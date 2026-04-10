from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any


SCHEMA_VERSION = 1


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run repository-defined harness cases and collect a manifest.")
    parser.add_argument(
        "--cases-dir",
        type=str,
        default=str((repo_root() / "harness" / "cases").resolve()),
        help="Directory containing harness case JSON files.",
    )
    parser.add_argument(
        "--case",
        action="append",
        default=[],
        help="Run only the named case. Can be passed multiple times.",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="",
        help="Directory where harness run outputs and the run manifest will be written.",
    )
    parser.add_argument(
        "--workspace",
        type=str,
        default=str(repo_root()),
        help="Workspace root used for case command execution.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available cases and exit.",
    )
    return parser


def _default_output_dir(workspace: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return (workspace / "tmp" / "harness-runs" / f"run-{stamp}").resolve()


def _now_iso(value: datetime | None = None) -> str:
    return (value or datetime.now()).isoformat(timespec="seconds")


def _substitute(value: Any, context: dict[str, str]) -> Any:
    if isinstance(value, str):
        return value.format(**context)
    if isinstance(value, list):
        return [_substitute(item, context) for item in value]
    if isinstance(value, dict):
        return {str(key): _substitute(item, context) for key, item in value.items()}
    return value


def load_cases(cases_dir: Path | str) -> list[dict[str, Any]]:
    root = Path(cases_dir).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"Harness cases directory not found: {root}")
    cases: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"Harness case must be a JSON object: {path}")
        name = str(data.get("name", "") or "").strip()
        if not name:
            raise ValueError(f"Harness case missing `name`: {path}")
        command = data.get("command")
        if not isinstance(command, list) or not all(isinstance(item, str) and item.strip() for item in command):
            raise ValueError(f"Harness case `{name}` must define a non-empty string command list.")
        case = dict(data)
        case["name"] = name
        case["_path"] = str(path)
        cases.append(case)
    return cases


def run_case(case: dict[str, Any], *, workspace: Path | str, output_root: Path | str) -> dict[str, Any]:
    workspace_path = Path(workspace).expanduser().resolve()
    output_root_path = Path(output_root).expanduser().resolve()
    case_name = str(case["name"])
    case_output_dir = (output_root_path / case_name).resolve()
    case_output_dir.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now()

    context = {
        "workspace": str(workspace_path),
        "output_dir": str(case_output_dir),
        "case_name": case_name,
        "python": sys.executable,
    }
    command = _substitute(case["command"], context)
    cwd = Path(str(_substitute(case.get("cwd", "{workspace}"), context))).expanduser().resolve()
    env = os.environ.copy()
    case_env = _substitute(case.get("env", {}), context)
    if isinstance(case_env, dict):
        env.update({str(key): str(value) for key, value in case_env.items()})

    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    completed_at = datetime.now()
    duration_ms = int((completed_at - started_at).total_seconds() * 1000)

    stdout_path = case_output_dir / "stdout.txt"
    stderr_path = case_output_dir / "stderr.txt"
    stdout_path.write_text(completed.stdout, encoding="utf-8")
    stderr_path.write_text(completed.stderr, encoding="utf-8")

    substituted_assertions = _substitute(case.get("assertions", {}), context)
    checks: list[dict[str, Any]] = []

    expected_exit = substituted_assertions.get("exit_code")
    if expected_exit is not None:
        ok = int(completed.returncode) == int(expected_exit)
        checks.append(
            {
                "kind": "exit_code",
                "expected": int(expected_exit),
                "actual": int(completed.returncode),
                "ok": ok,
            }
        )

    for snippet in substituted_assertions.get("stdout_contains", []):
        text = str(snippet)
        checks.append(
            {
                "kind": "stdout_contains",
                "expected": text,
                "ok": text in completed.stdout,
            }
        )

    for snippet in substituted_assertions.get("stderr_contains", []):
        text = str(snippet)
        checks.append(
            {
                "kind": "stderr_contains",
                "expected": text,
                "ok": text in completed.stderr,
            }
        )

    for raw_path in substituted_assertions.get("files_exist", []):
        target = Path(str(raw_path)).expanduser().resolve()
        checks.append(
            {
                "kind": "files_exist",
                "expected": str(target),
                "ok": target.exists(),
            }
        )

    success = all(check["ok"] for check in checks)
    result = {
        "name": case_name,
        "description": str(case.get("description", "") or "").strip(),
        "source": str(case.get("_path", "") or ""),
        "success": success,
        "command": command,
        "cwd": str(cwd),
        "exit_code": int(completed.returncode),
        "started_at": _now_iso(started_at),
        "completed_at": _now_iso(completed_at),
        "duration_ms": duration_ms,
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "output_dir": str(case_output_dir),
        "checks": checks,
    }
    result_path = case_output_dir / "result.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    result["result_path"] = str(result_path)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    workspace = Path(args.workspace).expanduser().resolve()
    cases = load_cases(args.cases_dir)

    if args.list:
        for case in cases:
            print(case["name"])
        return 0

    selected_names = [str(item).strip() for item in args.case if str(item).strip()]
    if selected_names:
        names_set = set(selected_names)
        selected_cases = [case for case in cases if case["name"] in names_set]
        missing = [name for name in selected_names if name not in {case["name"] for case in selected_cases}]
        if missing:
            parser.error(f"Unknown harness case(s): {', '.join(missing)}")
    else:
        selected_cases = cases

    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else _default_output_dir(workspace)
    output_dir.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now()

    results = [run_case(case, workspace=workspace, output_root=output_dir) for case in selected_cases]
    success = all(result["success"] for result in results)
    completed_at = datetime.now()
    duration_ms = int((completed_at - started_at).total_seconds() * 1000)
    failed_count = sum(1 for result in results if not result["success"])
    manifest = {
        "kind": "harness",
        "schema_version": SCHEMA_VERSION,
        "run_id": output_dir.name,
        "workspace": str(workspace),
        "cases_dir": str(Path(args.cases_dir).expanduser().resolve()),
        "output_dir": str(output_dir),
        "selected_cases": [case["name"] for case in selected_cases],
        "case_count": len(results),
        "passed_count": len(results) - failed_count,
        "failed_count": failed_count,
        "started_at": _now_iso(started_at),
        "completed_at": _now_iso(completed_at),
        "duration_ms": duration_ms,
        "success": success,
        "results": results,
    }
    manifest_path = output_dir / "run_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    for result in results:
        status = "PASS" if result["success"] else "FAIL"
        print(f"[{status}] {result['name']} -> {result['output_dir']}")
    print(f"manifest: {manifest_path}")
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
