from __future__ import annotations

from app.llm.claude_client import ClaudeCallError, _contains_timeout, _exception_detail


def test_exception_detail_unwraps_exception_group() -> None:
    exc = ExceptionGroup(
        "wrapper",
        [
            ClaudeCallError(
                "API Error: 400 {\"error\":{\"message\":\"invalid value: `document`\"}}"
            )
        ],
    )

    detail = _exception_detail(exc)

    assert "invalid value: `document`" in detail


def test_contains_timeout_detects_nested_timeout() -> None:
    exc = ExceptionGroup("wrapper", [TimeoutError()])

    assert _contains_timeout(exc) is True


def test_exception_detail_falls_back_to_exception_type_name_when_empty() -> None:
    exc = TimeoutError()

    assert _exception_detail(exc) == "TimeoutError"
