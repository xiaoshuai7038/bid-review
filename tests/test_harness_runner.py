from __future__ import annotations

import json
from pathlib import Path
import sys

from app.harness.runner import load_cases, main, run_case


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_load_cases_reads_json_specs(tmp_path: Path) -> None:
    cases_dir = tmp_path / "cases"
    cases_dir.mkdir()
    (cases_dir / "alpha.json").write_text(
        json.dumps(
            {
                "name": "alpha",
                "command": [sys.executable, "-c", "print('alpha')"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (cases_dir / "beta.json").write_text(
        json.dumps(
            {
                "name": "beta",
                "command": [sys.executable, "-c", "print('beta')"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    cases = load_cases(cases_dir)

    assert [case["name"] for case in cases] == ["alpha", "beta"]
    assert all(Path(case["_path"]).exists() for case in cases)


def test_run_case_executes_command_and_checks_expected_files(tmp_path: Path) -> None:
    case = {
        "name": "emit-file",
        "description": "Create a file and print a marker.",
        "command": [
            sys.executable,
            "-c",
            "import os; from pathlib import Path; Path(os.environ['TARGET_FILE']).write_text('ok', encoding='utf-8'); print('hello harness')",
        ],
        "env": {
            "TARGET_FILE": "{output_dir}/made.txt",
        },
        "assertions": {
            "exit_code": 0,
            "stdout_contains": ["hello harness"],
            "files_exist": ["{output_dir}/made.txt"],
        },
    }

    result = run_case(case, workspace=tmp_path, output_root=tmp_path / "results")

    assert result["success"] is True
    assert result["duration_ms"] >= 0
    assert result["started_at"]
    assert result["completed_at"]
    assert Path(result["stdout_path"]).read_text(encoding="utf-8").strip() == "hello harness"
    assert Path(result["stderr_path"]).read_text(encoding="utf-8") == ""
    assert Path(result["output_dir"], "made.txt").exists()
    assert Path(result["result_path"]).exists()


def test_main_filters_requested_cases_and_writes_manifest_metadata(tmp_path: Path) -> None:
    cases_dir = tmp_path / "cases"
    cases_dir.mkdir()
    for name in ("alpha", "beta"):
        (cases_dir / f"{name}.json").write_text(
            json.dumps(
                {
                    "name": name,
                    "command": [sys.executable, "-c", f"print('{name}')"],
                    "assertions": {"exit_code": 0, "stdout_contains": [name]},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    output_dir = tmp_path / "harness-output"
    status = main(
        [
            "--cases-dir",
            str(cases_dir),
            "--output-dir",
            str(output_dir),
            "--case",
            "beta",
            "--workspace",
            str(tmp_path),
        ]
    )

    assert status == 0
    manifest = json.loads((output_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["kind"] == "harness"
    assert manifest["selected_cases"] == ["beta"]
    assert manifest["case_count"] == 1
    assert manifest["failed_count"] == 0
    assert len(manifest["results"]) == 1
    assert manifest["results"][0]["name"] == "beta"


def test_repo_default_cases_cover_expected_suite() -> None:
    cases = load_cases(_repo_root() / "harness" / "cases")
    names = {case["name"] for case in cases}

    assert {
        "cli-help",
        "gui-smoke",
        "triage-harness-fixture",
        "triage-review-fixture",
        "task-doc-scaffold",
        "agent-worktree-dry-run",
    }.issubset(names)
