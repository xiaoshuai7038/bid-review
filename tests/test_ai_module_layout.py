from __future__ import annotations

from app.ai import create_llm_client, render_prompt
from app.ai.mcp.project_config import build_project_mcp_config_json
from app.review.workflows import detect_roles, run_bid_review


def test_ai_canonical_entrypoints_are_importable() -> None:
    assert callable(create_llm_client)
    assert callable(render_prompt)
    assert callable(build_project_mcp_config_json)
    assert callable(detect_roles)
    assert callable(run_bid_review)


def test_llm_shims_reexport_canonical_objects() -> None:
    from app.ai import create_llm_client as canonical_factory
    from app.ai.prompts.store import render_prompt as canonical_render_prompt
    from app.llm import create_llm_client as legacy_factory
    from app.llm.prompt_store import render_prompt as legacy_render_prompt

    assert legacy_factory is canonical_factory
    assert legacy_render_prompt is canonical_render_prompt
