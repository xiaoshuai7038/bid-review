from __future__ import annotations

from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_docs_index_and_harness_docs_exist() -> None:
    root = _repo_root()

    docs_index = root / "docs" / "index.md"
    harness_doc = root / "docs" / "harness.md"
    architecture_doc = root / "docs" / "architecture.md"
    runtime_doc = root / "docs" / "runtime-boundaries.md"
    debugging_doc = root / "docs" / "debugging.md"
    workspaces_doc = root / "docs" / "agent-workspaces.md"

    assert docs_index.exists()
    assert harness_doc.exists()
    assert architecture_doc.exists()
    assert runtime_doc.exists()
    assert debugging_doc.exists()
    assert workspaces_doc.exists()

    index_text = docs_index.read_text(encoding="utf-8")
    harness_text = harness_doc.read_text(encoding="utf-8")
    assert "./architecture.md" in index_text
    assert "./runtime-boundaries.md" in index_text
    assert "./harness.md" in index_text
    assert "./debugging.md" in index_text
    assert "./agent-workspaces.md" in index_text
    assert "scripts/run_harness.py" in harness_text
    assert "scripts/triage_run.py" in harness_text


def test_readme_agents_and_ci_reference_harness_entrypoints() -> None:
    root = _repo_root()

    readme_text = (root / "README.md").read_text(encoding="utf-8")
    agents_text = (root / "AGENTS.md").read_text(encoding="utf-8")
    ci_text = (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "docs/index.md" in readme_text
    assert "scripts/run_harness.py" in readme_text
    assert "scripts/triage_run.py" in readme_text
    assert "docs/index.md" in agents_text
    assert "scripts/run_harness.py" in agents_text
    assert "scripts/triage_run.py" in agents_text
    assert "uv run python -m app.main --help" in ci_text
    assert "uv run python scripts/run_harness.py --output-dir tmp/ci-harness" in ci_text
