from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import ctypes


def _project_root(start: Path) -> Path | None:
    for candidate in [start, *start.parents]:
        if (candidate / "pyproject.toml").exists() and (candidate / "app" / "gui" / "main.py").exists():
            return candidate
    return None


def _message_box(text: str, title: str = "Bid Review Desktop") -> None:
    try:
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x10)
    except Exception:
        print(f"{title}: {text}", file=sys.stderr)


def main() -> int:
    start = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
    project_root = _project_root(start)
    if project_root is None:
        _message_box("未能定位项目根目录，请将 EXE 保留在仓库 dist 目录中使用。")
        return 1

    pythonw = project_root / ".venv" / "Scripts" / "pythonw.exe"
    python = project_root / ".venv" / "Scripts" / "python.exe"
    interpreter = pythonw if pythonw.exists() else python
    if not interpreter.exists():
        _message_box("未找到项目 .venv，请先在仓库根目录执行 uv sync --extra dev。")
        return 1

    cmd = [str(interpreter), "-m", "app.gui.main", *sys.argv[1:]]
    completed = subprocess.run(cmd, cwd=project_root, check=False)
    return int(completed.returncode or 0)


if __name__ == "__main__":
    raise SystemExit(main())

