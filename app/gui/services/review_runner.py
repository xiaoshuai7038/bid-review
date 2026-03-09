from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QThread, Signal

from app.gui.services.report_loader import BatchReviewData, load_batch_result
from app.gui.state.settings import workspace_root
from app.orchestrator import run_pipeline


@dataclass
class ReviewRunRequest:
    tender_path: str
    bid_paths: list[str]
    backend: str = "claude"
    output_dir: str = ""
    model: str = ""
    opencode_model: str = ""
    claude_bin: str = ""
    opencode_bin: str = ""
    opencode_provider: str = "volcengine"
    opencode_api_url: str = ""
    opencode_api_key: str = ""
    progress_level: str = "agent"
    timeout_sec: int = 1800
    effort: str = "low"
    instruction: str = ""
    user_instruction: str = ""
    save_raw_output: bool = True
    workspace: str = field(default_factory=lambda: str(workspace_root()))

    def validate(self) -> None:
        if not self.tender_path:
            raise ValueError("请先选择招标文件。")
        if not self.bid_paths:
            raise ValueError("请至少选择一份投标文件。")
        if self.backend not in {"claude", "opencode"}:
            raise ValueError("后端仅支持 claude 或 opencode。")
        if not self.output_dir:
            raise ValueError("请指定输出目录。")


def _append_if_value(args: list[str], flag: str, value: str) -> None:
    if value and value.strip():
        args.extend([flag, value.strip()])


def build_cli_arguments(request: ReviewRunRequest) -> list[str]:
    args = ["-m", "app.main", "--backend", request.backend, "--tender", request.tender_path]
    for bid_path in request.bid_paths:
        args.extend(["--bid", bid_path])
    args.extend(["--output-dir", request.output_dir])
    args.extend(["--progress-level", request.progress_level])
    args.extend(["--timeout-sec", str(request.timeout_sec)])
    args.extend(["--effort", request.effort])
    _append_if_value(args, "--model", request.model)
    _append_if_value(args, "--opencode-model", request.opencode_model)
    _append_if_value(args, "--instruction", request.instruction)
    _append_if_value(args, "--user-instruction", request.user_instruction)
    _append_if_value(args, "--claude-bin", request.claude_bin)
    _append_if_value(args, "--opencode-bin", request.opencode_bin)
    _append_if_value(args, "--opencode-provider", request.opencode_provider)
    _append_if_value(args, "--opencode-api-url", request.opencode_api_url)
    _append_if_value(args, "--opencode-api-key", request.opencode_api_key)
    if not request.save_raw_output:
        args.append("--no-raw-output")
    return args


class ReviewWorker(QThread):
    progress = Signal(str, str)
    failed = Signal(str)
    completed = Signal(object)

    def __init__(self, request: ReviewRunRequest, parent: object | None = None) -> None:
        super().__init__(parent)
        self.request = request

    def run(self) -> None:
        try:
            self.request.validate()
            artifacts = run_pipeline(
                inputs=[],
                output_root=self.request.output_dir,
                tender_path=self.request.tender_path,
                bid_paths=self.request.bid_paths,
                backend=self.request.backend,
                claude_bin=self.request.claude_bin or None,
                opencode_bin=self.request.opencode_bin or None,
                model=self.request.model or None,
                opencode_model=self.request.opencode_model or None,
                effort=self.request.effort,
                show_progress=True,
                progress_level=self.request.progress_level,
                timeout_sec=self.request.timeout_sec,
                extra_instruction=self.request.instruction,
                user_instruction=self.request.user_instruction,
                opencode_api_key=self.request.opencode_api_key or None,
                opencode_api_url=self.request.opencode_api_url or None,
                opencode_provider=self.request.opencode_provider or "volcengine",
                save_raw_output=self.request.save_raw_output,
                workspace=self.request.workspace,
                progress_callback=self._emit_progress,
            )
            result: BatchReviewData = load_batch_result(artifacts.batch_summary_path)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
            return
        self.completed.emit(result)

    def _emit_progress(self, message: str, level: str) -> None:
        self.progress.emit(message, level)

