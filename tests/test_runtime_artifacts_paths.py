from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from app.gui.services.review_runner import ReviewRunRequest
from app.gui.state.settings import DesktopSettings, SettingsStore, _settings_path
from app.llm.claude_client import ClaudeClient
from app.llm.opencode_client import OpenCodeClient
from app.llm.project_mcp import build_project_mcp_servers
from app.mcp_servers.document_parser_server import _extract_images_from_word
from app.mcp_servers.paddle_ocr_server import _managed_ocr_mkdtemp
from app.runtime_paths import (
    CLAUDE_CODE_GIT_BASH_PATH_ENV,
    RUNTIME_ROOT_ENV,
    default_bundled_node_exe,
    default_bundled_node_root,
    default_bundled_opencode_runtime_root,
    default_git_bash_path,
    default_portable_git_root,
)


def _create_minimal_docx(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("word/document.xml", "<w:document></w:document>")
        zf.writestr("word/media/image1.png", b"fake-image")


def test_desktop_settings_default_output_dir_uses_runtime_root_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    monkeypatch.setenv(RUNTIME_ROOT_ENV, str(runtime_root))

    settings = DesktopSettings()

    assert settings.default_output_dir == str((runtime_root / "output").resolve())


def test_settings_path_uses_runtime_root_when_frozen(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    monkeypatch.setenv(RUNTIME_ROOT_ENV, str(runtime_root))
    monkeypatch.setattr("app.gui.state.settings.is_frozen", lambda: True)

    assert _settings_path() == (runtime_root / "settings" / "settings.json").resolve()


def test_settings_store_save_raises_when_runtime_root_not_writable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime"
    monkeypatch.setenv(RUNTIME_ROOT_ENV, str(runtime_root))
    monkeypatch.setattr("app.gui.state.settings.is_frozen", lambda: True)
    monkeypatch.setattr("app.gui.state.settings.ensure_runtime_root_writable", lambda: (_ for _ in ()).throw(RuntimeError("运行目录不可写")))

    store = SettingsStore(runtime_root / "settings" / "settings.json")
    with pytest.raises(RuntimeError, match="运行目录不可写"):
        store.save(DesktopSettings())


def test_review_request_validate_rejects_unwritable_output_dir_when_frozen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.gui.services.review_runner.is_frozen", lambda: True)
    monkeypatch.setattr("app.gui.services.review_runner.dir_is_writable", lambda _path: False)

    request = ReviewRunRequest(
        tender_path="D:/docs/tender.pdf",
        bid_paths=["D:/docs/bid.docx"],
        output_dir="D:/readonly/output",
    )

    with pytest.raises(ValueError, match="结果保存位置不可写"):
        request.validate()


def test_document_parser_extract_images_defaults_under_runtime_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime"
    bid_docx = tmp_path / "bid.docx"
    _create_minimal_docx(bid_docx)
    monkeypatch.setenv(RUNTIME_ROOT_ENV, str(runtime_root))

    result = _extract_images_from_word(str(bid_docx))

    output_dir = Path(str(result["output_dir"]))
    assert output_dir.parent == (runtime_root / "tmp" / "document-parser").resolve()
    assert result["image_count"] == 1


def test_paddle_ocr_temp_dirs_default_under_runtime_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime"
    monkeypatch.setenv(RUNTIME_ROOT_ENV, str(runtime_root))

    temp_dir = _managed_ocr_mkdtemp("ocr_pdf_pages_")
    try:
        assert temp_dir.parent == (runtime_root / "tmp" / "ocr").resolve()
    finally:
        if temp_dir.exists():
            for child in temp_dir.iterdir():
                if child.is_file():
                    child.unlink()
            temp_dir.rmdir()


def test_project_mcp_servers_include_runtime_related_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    monkeypatch.setenv(RUNTIME_ROOT_ENV, str(runtime_root))

    servers = build_project_mcp_servers("D:/code/bidreview")

    assert servers["document-parser"]["env"][RUNTIME_ROOT_ENV] == str(runtime_root.resolve())
    assert "CLAUDE_CONFIG_DIR" in servers["document-parser"]["env"]
    assert "BID_REVIEW_OPENCODE_DATA_DIR" not in servers["document-parser"]["env"]


def test_claude_client_sdk_env_includes_runtime_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    monkeypatch.setenv(RUNTIME_ROOT_ENV, str(runtime_root))

    client = ClaudeClient(show_progress=False)
    env = client._build_sdk_env()

    assert env[RUNTIME_ROOT_ENV] == str(runtime_root.resolve())
    assert env["CLAUDE_CONFIG_DIR"] == str((runtime_root / "third-party" / "claude").resolve())


def test_default_git_bash_path_prefers_explicit_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    git_bash = tmp_path / "bash.exe"
    git_bash.write_text("stub", encoding="utf-8")
    monkeypatch.setattr("app.runtime_paths.os.name", "nt")
    monkeypatch.setenv(CLAUDE_CODE_GIT_BASH_PATH_ENV, str(git_bash))

    assert default_git_bash_path() == git_bash.resolve()


def test_default_portable_git_root_uses_bundled_directory_when_frozen(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bundle_root = tmp_path / "bundle"
    portable_git_root = bundle_root / "third-party" / "git"
    portable_git_root.mkdir(parents=True)
    monkeypatch.setattr("app.runtime_paths.is_frozen", lambda: True)
    monkeypatch.setattr("app.runtime_paths.app_root", lambda: bundle_root.resolve())

    assert default_portable_git_root() == portable_git_root.resolve()


def test_default_git_bash_path_prefers_bundled_portable_git_when_frozen(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bundle_root = tmp_path / "bundle"
    bundled_bash = bundle_root / "third-party" / "git" / "bin" / "bash.exe"
    bundled_bash.parent.mkdir(parents=True)
    bundled_bash.write_text("stub", encoding="utf-8")
    path_bash = tmp_path / "system-bash.exe"
    path_bash.write_text("stub", encoding="utf-8")

    monkeypatch.setattr("app.runtime_paths.os.name", "nt")
    monkeypatch.setattr("app.runtime_paths.is_frozen", lambda: True)
    monkeypatch.setattr("app.runtime_paths.app_root", lambda: bundle_root.resolve())
    monkeypatch.delenv(CLAUDE_CODE_GIT_BASH_PATH_ENV, raising=False)
    monkeypatch.setattr("app.runtime_paths.shutil.which", lambda name: str(path_bash.resolve()) if name == "bash" else None)

    assert default_git_bash_path() == bundled_bash.resolve()


def test_default_bundled_node_root_uses_third_party_directory_when_frozen(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bundle_root = tmp_path / "bundle"
    node_root = bundle_root / "third-party" / "nodejs"
    node_root.mkdir(parents=True)
    monkeypatch.setattr("app.runtime_paths.is_frozen", lambda: True)
    monkeypatch.setattr("app.runtime_paths.app_root", lambda: bundle_root.resolve())

    assert default_bundled_node_root() == node_root.resolve()


def test_default_bundled_node_exe_uses_node_executable_when_frozen(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bundle_root = tmp_path / "bundle"
    node_exe = bundle_root / "third-party" / "nodejs" / "node.exe"
    node_exe.parent.mkdir(parents=True)
    node_exe.write_text("stub", encoding="utf-8")
    monkeypatch.setattr("app.runtime_paths.is_frozen", lambda: True)
    monkeypatch.setattr("app.runtime_paths.app_root", lambda: bundle_root.resolve())
    monkeypatch.setattr("app.runtime_paths.os.name", "nt")

    assert default_bundled_node_exe() == node_exe.resolve()


def test_default_bundled_opencode_runtime_root_uses_third_party_directory_when_frozen(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bundle_root = tmp_path / "bundle"
    opencode_root = bundle_root / "third-party" / "opencode"
    opencode_root.mkdir(parents=True)
    monkeypatch.setattr("app.runtime_paths.is_frozen", lambda: True)
    monkeypatch.setattr("app.runtime_paths.app_root", lambda: bundle_root.resolve())

    assert default_bundled_opencode_runtime_root() == opencode_root.resolve()


def test_opencode_runtime_env_includes_data_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    monkeypatch.setenv(RUNTIME_ROOT_ENV, str(runtime_root))

    client = OpenCodeClient(
        opencode_bin="opencode",
        model="DeepSeek-V3.2",
        workspace="D:/code/bidreview",
        provider_id="ark",
        show_progress=False,
    )
    env = client._build_runtime_env()
    config = json.loads(env["OPENCODE_CONFIG_CONTENT"])

    assert env[RUNTIME_ROOT_ENV] == str(runtime_root.resolve())
    assert "BID_REVIEW_OPENCODE_DATA_DIR" not in env
    assert "data" not in config


def test_opencode_runtime_env_can_enable_experimental_data_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime"
    monkeypatch.setenv(RUNTIME_ROOT_ENV, str(runtime_root))
    monkeypatch.setenv("BID_REVIEW_ENABLE_OPENCODE_DATA_DIRECTORY", "1")

    client = OpenCodeClient(
        opencode_bin="opencode",
        model="DeepSeek-V3.2",
        workspace="D:/code/bidreview",
        provider_id="ark",
        show_progress=False,
    )
    env = client._build_runtime_env()
    config = json.loads(env["OPENCODE_CONFIG_CONTENT"])

    assert env["BID_REVIEW_OPENCODE_DATA_DIR"] == str((runtime_root / "third-party" / "opencode" / "data").resolve())
    assert config["data"]["directory"] == str((runtime_root / "third-party" / "opencode" / "data").resolve())
