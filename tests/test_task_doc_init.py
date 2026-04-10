from __future__ import annotations

from pathlib import Path
import subprocess
import sys


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_init_task_docs_scaffolds_all_files_and_runs_check(tmp_path: Path) -> None:
    task_dir = tmp_path / "sample-task"

    completed = subprocess.run(
        [sys.executable, "scripts/init_task_docs.py", str(task_dir), "--goal", "Scaffold sample task"],
        cwd=str(_repo_root()),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert completed.returncode == 0
    for name in ("contract.md", "plan.md", "status.md", "prompt.md", "implement.md", "documentation.md"):
        assert (task_dir / name).exists()
    assert "[OK]" in completed.stdout or "[OK]" in completed.stderr
