from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_generate_user_manual_creates_docx_and_screenshots(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    output_dir = tmp_path / "manual-output"
    env = os.environ.copy()
    env.setdefault("QT_QPA_PLATFORM", "offscreen")

    completed = subprocess.run(
        [sys.executable, "scripts/generate_user_manual.py", "--output-dir", str(output_dir)],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    manifest_path = output_dir / "manual_manifest.json"
    assert manifest_path.exists(), completed.stdout + completed.stderr
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    docx_path = Path(payload["docx"])
    screenshots = {name: Path(path) for name, path in payload["screenshots"].items()}

    assert docx_path.exists()
    assert docx_path.suffix.lower() == ".docx"
    assert docx_path.stat().st_size > 0
    assert set(screenshots) == {"home", "settings", "review", "results"}
    for path in screenshots.values():
        assert path.exists()
        assert path.suffix.lower() == ".png"
        assert path.stat().st_size > 0
