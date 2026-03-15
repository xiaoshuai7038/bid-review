from __future__ import annotations

from app.gui.main import build_parser


def test_gui_main_parser_accepts_automation_review_args() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "--automation-backend",
            "opencode",
            "--automation-tender",
            r"D:\docs\tender.pdf",
            "--automation-bid",
            r"D:\docs\bid.docx",
            "--automation-output-dir",
            r"D:\output",
            "--automation-model",
            "DeepSeek-V3.2",
            "--automation-review-profile",
            "fast",
            "--automation-timeout-sec",
            "2400",
            "--screenshot",
            r"D:\output\gui-review.png",
        ]
    )

    assert args.automation_backend == "opencode"
    assert args.automation_tender == r"D:\docs\tender.pdf"
    assert args.automation_bid == [r"D:\docs\bid.docx"]
    assert args.automation_output_dir == r"D:\output"
    assert args.automation_model == "DeepSeek-V3.2"
    assert args.automation_review_profile == "fast"
    assert args.automation_timeout_sec == 2400
    assert args.screenshot == r"D:\output\gui-review.png"
