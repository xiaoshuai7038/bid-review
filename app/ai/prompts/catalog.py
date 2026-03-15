from __future__ import annotations

from pathlib import Path


def resolve_prompt_path(templates_root: Path, name: str) -> Path:
    candidates = []
    if name == "json_api_wrapper.md":
        candidates.append(templates_root / "shared" / name)
    elif name.startswith("role_detect_"):
        candidates.append(templates_root / "role_detection" / name)
    elif name.startswith("review_"):
        candidates.append(templates_root / "review" / name)
    candidates.append(templates_root / name)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]
