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
_REQUIREMENTS_FILE = _PLUGIN_DIR / "requirements.txt"


def _is_installed() -> bool:
    return importlib.util.find_spec("cortex_plugin") is not None


def ensure_dependencies() -> None:
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

        # uv installs deps from requirements.txt but cortex_plugin itself is not a
        # pip-installable package — it lives in src/ inside the plugin directory.
        # Add src/ to sys.path so it is importable in the current process.
        src_dir = str(_PLUGIN_DIR / "src")
        if src_dir not in sys.path:
            sys.path.insert(0, src_dir)

        importlib.invalidate_caches()

        if not _is_installed():
            raise RuntimeError(
                "cortex_plugin is still unavailable after installing requirements"
            )

        _CHECKED = True


def _install() -> None:
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError(
            "agent-zero-cortex requires 'uv' to install dependencies; 'uv' not found on PATH"
        )
    if not _REQUIREMENTS_FILE.is_file():
        raise RuntimeError(
            f"agent-zero-cortex requirements.txt not found at {_REQUIREMENTS_FILE}"
        )

    result = subprocess.run(
        [uv, "pip", "install", "--python", sys.executable, "-r", str(_REQUIREMENTS_FILE)],
        cwd=str(_PLUGIN_DIR),
        capture_output=True,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace") if result.stderr else ""
        raise RuntimeError(f"agent-zero-cortex dependency install failed: {stderr}")
