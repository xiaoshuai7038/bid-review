from __future__ import annotations

from pathlib import Path
import subprocess


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_create_agent_worktree_script_supports_dry_run(tmp_path: Path) -> None:
    script = _repo_root() / "scripts" / "create-agent-worktree.ps1"
    completed = subprocess.run(
        [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-Name",
            "demo-agent",
            "-RootDir",
            str(tmp_path / "worktrees"),
            "-DryRun",
        ],
        cwd=str(_repo_root()),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert completed.returncode == 0
    assert "mode: dry-run" in completed.stdout
    assert "agent-env.ps1" in completed.stdout
    assert "run_context_root:" in completed.stdout
