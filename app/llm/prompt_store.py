from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path


_PLACEHOLDER_RE = re.compile(r"\{\{([a-zA-Z_][a-zA-Z0-9_]*)\}\}")


def _default_prompts_dir() -> Path:
    return Path(__file__).resolve().parent / "prompts"


def get_prompts_dir() -> Path:
    custom = os.getenv("BID_REVIEW_PROMPTS_DIR")
    if custom:
        return Path(custom).resolve()
    return _default_prompts_dir()


@lru_cache(maxsize=256)
def get_prompt_text(name: str) -> str:
    path = get_prompts_dir() / name
    if not path.exists():
        raise FileNotFoundError(f"提示词模板不存在: {path}")
    return path.read_text(encoding="utf-8")


def render_prompt(name: str, **kwargs: str) -> str:
    template = get_prompt_text(name)
    missing: set[str] = set()

    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in kwargs:
            missing.add(key)
            return match.group(0)
        return str(kwargs[key])

    rendered = _PLACEHOLDER_RE.sub(repl, template)
    if missing:
        keys = ", ".join(sorted(missing))
        raise ValueError(f"提示词模板变量缺失: {keys}; template={name}")
    return rendered

