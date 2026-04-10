# AGENTS.md

## Purpose
- This repository runs bid/tender compliance review by delegating analysis to Claude SDK runtime or OpenCode runtime.
- Local code is responsible for orchestration and report export (`json`/`markdown`/`docx`), not rule reasoning.

## Environment
- Python: `>=3.10`
- Dependency/tooling: `uv`
- Authentication/runtime dependency: configure the required Claude/OpenCode credentials for the backend you use.

## Canonical Run Commands
- Sync env:
  - `uv sync`
- Show CLI help:
  - `uv run python -m app.main --help`
- Default harness suite:
  - `uv run python scripts/run_harness.py --output-dir "tmp/harness-full"`
- Triage an existing run:
  - `uv run python scripts/triage_run.py "data/output/run-*/"`
- Main pipeline (PowerShell example):
  - `uv run python -m app.main --input "<tender>" --input "<bid>" --output-dir "data/output"`
- Wrapper script:
  - `.\run-review.ps1 -Input "<tender>","<bid>" -OutputDir "data/output"`

## Recommended Workflow
- Use `$feature-delivery-loop` for scoped feature work, refactors, migrations, or other long-horizon implementation tasks.
- Use `$python-regression-fix-loop` for confirmed regressions that require minimal, compatibility-preserving fixes.
- For long tasks, prefer a workspace-local task folder such as `tasks/<task-slug>/` with:
  - `contract.md`: task-specific Success Contract and source of truth
  - `plan.md`: milestone plan mapped to `Done When`
  - `status.md`: current progress, validations, and blockers
- Treat task-tracking files as working notes by default; do not commit them unless the user explicitly asks.

## Project Layout
- `app/main.py`: CLI argument parsing and top-level execution.
- `app/orchestrator.py`: role detection, batch orchestration, artifact generation.
- `app/review/claude_review.py`: Claude-driven review and role detection calls.
- `app/llm/`: Claude client + prompts.
- `app/llm/prompts/`: prompt templates (`role_detect*`, `review_*`, `json_api_wrapper`).
- `app/report/`: report exporters.
- `app/harness/`: repo-native harness runner logic.
- `docs/`: stable repository docs (`index`, `architecture`, `runtime-boundaries`, `harness`, `debugging`, `agent-workspaces`).
- `harness/cases/`: machine-readable harness case definitions.
- `harness/fixtures/`: offline sample run fixtures for triage and harness regression.
- `data/output/`: run artifacts (`run-<timestamp>`), git-ignored.

## Change Rules For Agents
- Make minimal, scoped changes; avoid cross-module refactors unless requested.
- Keep CLI flags backward-compatible when possible.
- If changing prompt contract or output fields, update both:
  - prompt files under `app/llm/prompts/`
  - report/orchestration code paths consuming those fields.
- Do not commit generated artifacts (`data/output`, logs, temp files).

## Repo Review Gates
- Pause before changing CLI entry behavior or argument contracts in `app/main.py`.
- Pause before changing prompt contracts, output fields, or report structure across:
  - `app/llm/prompts/`
  - `app/orchestrator.py`
  - `app/report/`
- Pause before changing Claude/OpenCode invocation behavior, retry flow, timeout handling, or tool-call guardrails in:
  - `app/review/claude_review.py`
  - related client code under `app/llm/`
- Pause before adding a new production dependency, changing artifact filenames, or changing the expected contents of exported reports.

## Validation Checklist
- Always run:
  - `uv run python -m app.main --help`
- For repo-native harness changes:
  - `uv run python scripts/run_harness.py --output-dir "tmp/harness-full"`
- Run tests when available:
  - `uv run pytest -q`
- If a task `contract.md` defines `Done When`, map each item to explicit validation before considering the task complete.
- If report generation logic is changed, perform one local smoke run and verify:
  - `review_result.json`
  - `review_report.md`
  - `review_report.docx`
  - `batch_summary.json`
- If backend compatibility is affected, validate the impacted Claude and/or OpenCode paths instead of assuming shared behavior.

## Debugging Notes
- On failures, inspect run directory under `data/output/run-*`.
- For harness failures, inspect `tmp/harness-runs/run-*` or the explicit `--output-dir` and open `run_manifest.json`.
- Prefer `uv run python scripts/triage_run.py "<run-dir-or-manifest>"` before manually opening every artifact.
- `claude_raw_output.txt` is the primary source for parsing/format issues (unless `--no-raw-output` is used).
- For role detection problems, start from `app/orchestrator.py` branching around manual/auto role selection.

## Docs
- Stable repo docs entrypoint:
  - `docs/index.md`

## Out Of Scope
- Re-implementing bid review reasoning locally (must stay Claude-driven).
- Hardcoding project-specific business rules in Python unless explicitly requested.
