from __future__ import annotations

from app.gui.services.review_runner import ReviewRunRequest, build_cli_arguments


def test_build_cli_arguments_preserves_cli_contract() -> None:
    request = ReviewRunRequest(
        tender_path=r"D:\docs\tender.pdf",
        bid_paths=[r"D:\docs\bid-a.docx", r"D:\docs\bid-b.docx"],
        backend="opencode",
        output_dir=r"D:\output",
        model="DeepSeek-V3.2",
        claude_bin=r"C:\tools\claude.cmd",
        opencode_bin=r"C:\tools\opencode.exe",
        opencode_provider="volcengine",
        opencode_api_url="https://example.invalid/v1",
        opencode_api_key="secret",
        progress_level="detailed",
        timeout_sec=2400,
        effort="high",
        instruction="附加指令",
        user_instruction="用户偏好",
        save_raw_output=False,
    )

    args = build_cli_arguments(request)

    assert args[:2] == ["-m", "app.main"]
    assert args.count("--bid") == 2
    assert "--backend" in args
    assert "--tender" in args
    assert "--output-dir" in args
    assert "--progress-level" in args
    assert "--opencode-api-key" in args
    assert "--no-raw-output" in args

