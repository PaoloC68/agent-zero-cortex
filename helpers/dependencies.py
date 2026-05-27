from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import threading
from pathlib import Path

_LOCK = threading.Lock()
_CHECKED = False
_PLUGIN_DIR = Path(__file__).resolve().parent.parent  # helpers/ -> plugin root


def _is_installed() -> bool:
    return importlib.util.find_spec("cortex_plugin") is not None


def ensure_dependencies() -> None:
    """Install the cortex_plugin package into the running venv if not already present.

    Mirrors the pattern used by the telegram plugin (_telegram_integration/helpers/dependencies.py).
    Called at import time from each extension file so the package self-installs on first
    use after a container recreate, without touching any Agent Zero files.
    """
    global _CHECKED

    if _CHECKED and _is_installed():
        return

    with _LOCK:
        if _CHECKED and _is_installed():
            return
        if _is_installed():
            _CHECKED = True
            return

        _install()
        importlib.invalidate_caches()

        if not _is_installed():
            raise RuntimeError(
                "cortex_plugin is still unavailable after installation attempt"
            )

        _CHECKED = True


def _install() -> None:
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError(
            "agent-zero-cortex requires 'uv' to self-install; 'uv' not found on PATH"
        )

    pyproject = _PLUGIN_DIR / "pyproject.toml"
    if not pyproject.is_file():
        raise RuntimeError(
            f"agent-zero-cortex pyproject.toml not found at {pyproject}"
        )

    try:
        subprocess.check_call(
            [uv, "pip", "install", "--python", sys.executable, "-e", str(_PLUGIN_DIR)],
            cwd=str(_PLUGIN_DIR),
            capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode(errors="replace") if e.stderr else ""
        raise RuntimeError(f"agent-zero-cortex self-install failed: {stderr}") from e
