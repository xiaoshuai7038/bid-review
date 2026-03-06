# AGENTS.md

## Purpose
- This repository runs bid/tender compliance review by delegating analysis to local `claude` CLI.
- Local code is responsible for orchestration and report export (`json`/`markdown`/`docx`), not rule reasoning.

## Environment
- Python: `>=3.10`
- Dependency/tooling: `uv`
- External runtime dependency: local `claude` CLI must be installed and authenticated.

## Canonical Run Commands
- Sync env:
  - `uv sync`
- Show CLI help:
  - `uv run python -m app.main --help`
- Main pipeline (PowerShell example):
  - `uv run python -m app.main --input "<tender>" --input "<bid>" --output-dir "data/output"`
- Wrapper script:
  - `.\run-review.ps1 -Input "<tender>","<bid>" -OutputDir "data/output"`

## Project Layout
- `app/main.py`: CLI argument parsing and top-level execution.
- `app/orchestrator.py`: role detection, batch orchestration, artifact generation.
- `app/review/claude_review.py`: Claude-driven review and role detection calls.
- `app/llm/`: Claude client + prompts.
- `app/llm/prompts/`: prompt templates (`role_detect*`, `review_*`, `json_api_wrapper`).
- `app/report/`: report exporters.
- `data/output/`: run artifacts (`run-<timestamp>`), git-ignored.

## Change Rules For Agents
- Make minimal, scoped changes; avoid cross-module refactors unless requested.
- Keep CLI flags backward-compatible when possible.
- If changing prompt contract or output fields, update both:
  - prompt files under `app/llm/prompts/`
  - report/orchestration code paths consuming those fields.
- Do not commit generated artifacts (`data/output`, logs, temp files).

## Validation Checklist
- Always run:
  - `uv run python -m app.main --help`
- Run tests when available:
  - `uv run pytest -q`
- If report generation logic is changed, perform one local smoke run and verify:
  - `review_result.json`
  - `review_report.md`
  - `review_report.docx`
  - `batch_summary.json`

## Debugging Notes
- On failures, inspect run directory under `data/output/run-*`.
- `claude_raw_output.txt` is the primary source for parsing/format issues (unless `--no-raw-output` is used).
- For role detection problems, start from `app/orchestrator.py` branching around manual/auto role selection.

## Out Of Scope
- Re-implementing bid review reasoning locally (must stay Claude-driven).
- Hardcoding project-specific business rules in Python unless explicitly requested.
