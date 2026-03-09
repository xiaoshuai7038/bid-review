from __future__ import annotations

from pathlib import Path

from app.gui_launcher import _project_root


def test_project_root_finds_repo_root(tmp_path: Path) -> None:
    project_root = tmp_path / "repo"
    target = project_root / "dist" / "BidReviewDesktopLauncher"
    (project_root / "app" / "gui").mkdir(parents=True)
    (project_root / "app" / "gui" / "main.py").write_text("", encoding="utf-8")
    (project_root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    target.mkdir(parents=True)

    assert _project_root(target) == project_root
