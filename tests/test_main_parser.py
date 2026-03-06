from __future__ import annotations

from pathlib import Path

from app.main import _read_instruction, build_parser


def test_opencode_api_url_defaults_to_none(monkeypatch) -> None:
    monkeypatch.delenv("BID_REVIEW_OPENCODE_API_URL", raising=False)
    parser = build_parser()
    args = parser.parse_args([])
    assert args.opencode_api_url is None


def test_opencode_provider_defaults_to_volcengine(monkeypatch) -> None:
    monkeypatch.delenv("BID_REVIEW_OPENCODE_PROVIDER", raising=False)
    parser = build_parser()
    args = parser.parse_args([])
    assert args.opencode_provider == "volcengine"


def test_read_instruction_loads_file_content(tmp_path: Path) -> None:
    instruction_path = tmp_path / "instruction.txt"
    instruction_path.write_text("优先检查资格项", encoding="utf-8")

    assert _read_instruction(str(instruction_path)) == "优先检查资格项"
