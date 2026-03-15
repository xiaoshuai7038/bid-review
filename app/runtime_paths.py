from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path


RUNTIME_ROOT_ENV = "BID_REVIEW_RUNTIME_ROOT"
CLAUDE_CONFIG_DIR_ENV = "CLAUDE_CONFIG_DIR"
CLAUDE_CODE_GIT_BASH_PATH_ENV = "CLAUDE_CODE_GIT_BASH_PATH"
OPENCODE_DATA_DIR_ENV = "BID_REVIEW_OPENCODE_DATA_DIR"
OPENCODE_ENABLE_DATA_DIR_ENV = "BID_REVIEW_ENABLE_OPENCODE_DATA_DIRECTORY"
RUNTIME_HOST_PATH_ENV = "BID_REVIEW_RUNTIME_HOST"
RUN_CONTEXT_DIR_ENV = "BID_REVIEW_RUN_CONTEXT_DIR"
REVIEW_PROFILE_ENV = "BID_REVIEW_REVIEW_PROFILE"
RUNTIME_HOST_EXE_NAME = "BidReviewRuntimeHost.exe"
PORTABLE_GIT_DIRNAME = "git"
NODEJS_DIRNAME = "nodejs"
OPENCODE_RUNTIME_DIRNAME = "opencode"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_root() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def bundle_internal_root() -> Path | None:
    if not is_frozen():
        return None
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        return Path(meipass).resolve()
    return (app_root() / "_internal").resolve()


def workspace_root() -> Path:
    override = os.getenv("BID_REVIEW_GUI_WORKSPACE")
    if override:
        return Path(override).expanduser().resolve()
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return app_root()


def managed_runtime_enabled() -> bool:
    return bool(os.getenv(RUNTIME_ROOT_ENV)) or is_frozen()


def runtime_root() -> Path:
    override = os.getenv(RUNTIME_ROOT_ENV)
    if override:
        return Path(override).expanduser().resolve()
    if is_frozen():
        return (app_root() / "runtime").resolve()
    return (workspace_root() / ".runtime").resolve()


def runtime_subdir(*parts: str) -> Path:
    base = runtime_root()
    for part in parts:
        base = base / part
    return base


def _probe_dir_writable(path: Path) -> bool:
    probe_name = f".write-probe-{os.getpid()}"
    probe_path = path / probe_name
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe_path.write_text("ok", encoding="utf-8")
        probe_path.unlink(missing_ok=True)
        return True
    except Exception:
        try:
            probe_path.unlink(missing_ok=True)
        except Exception:
            pass
        return False


def dir_is_writable(path: Path) -> bool:
    return _probe_dir_writable(path)


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_runtime_root_writable() -> Path:
    root = runtime_root()
    if _probe_dir_writable(root):
        return root
    raise RuntimeError(
        f"运行目录不可写：{root}。请将程序移动到可写目录，或显式设置 {RUNTIME_ROOT_ENV}。"
    )


def runtime_root_status() -> dict[str, str | bool]:
    root = runtime_root()
    return {
        "managed": managed_runtime_enabled(),
        "root": str(root),
        "writable": _probe_dir_writable(root) if managed_runtime_enabled() else True,
    }


def default_output_root() -> Path:
    if managed_runtime_enabled():
        return runtime_subdir("output")
    return (workspace_root() / "data" / "output").resolve()


def default_review_cache_root() -> Path:
    if managed_runtime_enabled():
        return runtime_subdir("cache", "review-artifacts")
    return (workspace_root() / "data" / "cache" / "review-artifacts").resolve()


def default_settings_path() -> Path:
    if managed_runtime_enabled():
        return runtime_subdir("settings", "settings.json")
    return Path()


def default_document_parser_temp_root() -> Path | None:
    if not managed_runtime_enabled():
        return None
    return runtime_subdir("tmp", "document-parser")


def default_ocr_temp_root() -> Path | None:
    if not managed_runtime_enabled():
        return None
    return runtime_subdir("tmp", "ocr")


def default_claude_config_dir() -> Path | None:
    explicit = os.getenv(CLAUDE_CONFIG_DIR_ENV)
    if explicit:
        return Path(explicit).expanduser().resolve()
    if not managed_runtime_enabled():
        return None
    return runtime_subdir("third-party", "claude")


def default_claude_bundled_cli_path() -> Path | None:
    bundle_root = bundle_internal_root()
    if bundle_root is None:
        return None
    cli_name = "claude.exe" if os.name == "nt" else "claude"
    candidate = (bundle_root / "claude_agent_sdk" / "_bundled" / cli_name).resolve()
    if candidate.exists() and candidate.is_file():
        return candidate
    return None


def default_runtime_host_path() -> Path | None:
    explicit = os.getenv(RUNTIME_HOST_PATH_ENV)
    if explicit:
        return Path(explicit).expanduser().resolve()
    if not is_frozen():
        return None
    return (app_root() / RUNTIME_HOST_EXE_NAME).resolve()


def default_portable_git_root() -> Path | None:
    if not is_frozen():
        return None
    candidate = (app_root() / "third-party" / PORTABLE_GIT_DIRNAME).resolve()
    if candidate.exists() and candidate.is_dir():
        return candidate
    return None


def default_bundled_node_root() -> Path | None:
    if not is_frozen():
        return None
    candidate = (app_root() / "third-party" / NODEJS_DIRNAME).resolve()
    if candidate.exists() and candidate.is_dir():
        return candidate
    return None


def default_bundled_node_exe() -> Path | None:
    node_root = default_bundled_node_root()
    if node_root is None:
        return None
    exe_name = "node.exe" if os.name == "nt" else "node"
    candidate = (node_root / exe_name).resolve()
    if candidate.exists() and candidate.is_file():
        return candidate
    return None


def default_bundled_opencode_runtime_root() -> Path | None:
    if not is_frozen():
        return None
    candidate = (app_root() / "third-party" / OPENCODE_RUNTIME_DIRNAME).resolve()
    if candidate.exists() and candidate.is_dir():
        return candidate
    return None


def _add_git_root_candidates(candidates: list[Path], seen: set[str], git_root: Path | None) -> None:
    if git_root is None:
        return
    for path in [
        git_root / "bin" / "bash.exe",
        git_root / "usr" / "bin" / "bash.exe",
    ]:
        try:
            resolved = path.expanduser().resolve(strict=False)
        except Exception:
            continue
        key = str(resolved).lower()
        if key in seen:
            continue
        seen.add(key)
        candidates.append(resolved)


def _candidate_git_bash_paths() -> list[Path]:
    candidates: list[Path] = []
    seen: set[str] = set()

    def add(path: Path | None) -> None:
        if path is None:
            return
        try:
            resolved = path.expanduser().resolve(strict=False)
        except Exception:
            return
        key = str(resolved).lower()
        if key in seen:
            return
        seen.add(key)
        candidates.append(resolved)

    explicit = (os.getenv(CLAUDE_CODE_GIT_BASH_PATH_ENV) or "").strip()
    if explicit:
        add(Path(explicit))

    _add_git_root_candidates(candidates, seen, default_portable_git_root())

    bash_in_path = shutil.which("bash")
    if bash_in_path:
        add(Path(bash_in_path))

    git_in_path = shutil.which("git")
    if git_in_path:
        git_path = Path(git_in_path)
        add(git_path.parent / "bash.exe")
        add(git_path.parent.parent / "bin" / "bash.exe")
        add(git_path.parent.parent / "usr" / "bin" / "bash.exe")

    for env_name in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)", "LocalAppData"):
        base = (os.getenv(env_name) or "").strip()
        if not base:
            continue
        root = Path(base)
        if env_name == "LocalAppData":
            _add_git_root_candidates(candidates, seen, root / "Programs" / "Git")
            continue
        _add_git_root_candidates(candidates, seen, root / "Git")

    return candidates


def default_git_bash_path() -> Path | None:
    if os.name != "nt":
        return None
    for candidate in _candidate_git_bash_paths():
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def default_opencode_data_dir() -> Path | None:
    explicit = os.getenv(OPENCODE_DATA_DIR_ENV)
    if explicit:
        return Path(explicit).expanduser().resolve()
    if not managed_runtime_enabled():
        return None
    return runtime_subdir("third-party", "opencode", "data")


def opencode_data_directory_enabled() -> bool:
    return os.getenv(OPENCODE_ENABLE_DATA_DIR_ENV, "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def temp_fallback_root() -> Path:
    return Path(tempfile.gettempdir()).resolve()
