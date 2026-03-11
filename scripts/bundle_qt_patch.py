from __future__ import annotations

import os
from pathlib import Path
import sys

import _pyi_rth_utils
from _pyi_rth_utils import qt as _qt_rth_utils


_original_prepend = _pyi_rth_utils.prepend_path_to_environment_variable
_bundle_root = Path(getattr(sys, "_MEIPASS", "")).resolve()


def _safe_prepend(path: str, variable_name: str) -> None:
    try:
        resolved = Path(path).resolve()
    except OSError:
        resolved = None

    # Avoid placing the bundle root itself on PATH. In our onedir layout this
    # causes Windows to resolve CRT/api-ms shim DLLs from `_internal` before the
    # PySide6 package directory, which then breaks `PySide6.QtCore` import.
    if variable_name == "PATH" and resolved == _bundle_root:
        return
    _original_prepend(path, variable_name)


_pyi_rth_utils.prepend_path_to_environment_variable = _safe_prepend


def _skip_embedded_qt_conf(*args, **kwargs) -> None:
    return


_qt_rth_utils.create_embedded_qt_conf = _skip_embedded_qt_conf

# Pre-register the PySide6-related directories that the frozen app actually
# needs, so the subsequent official PyInstaller PySide6 hook can import QtCore
# without depending on the bundle root being present on PATH.
for candidate in [
    _bundle_root / "PySide6",
    _bundle_root / "shiboken6",
    _bundle_root / "PySide6" / "plugins",
    _bundle_root / "PySide6" / "plugins" / "platforms",
]:
    if candidate.exists():
        _original_prepend(str(candidate), "PATH")
