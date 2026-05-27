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

        # uv editable installs register via a .pth file which is only processed at
        # interpreter startup — not mid-process. Add src/ to sys.path directly so
        # the package is importable in the current process without a restart.
        src_dir = str(_PLUGIN_DIR / "src")
        if src_dir not in sys.path:
            sys.path.insert(0, src_dir)

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

    result = subprocess.run(
        [uv, "pip", "install", "--python", sys.executable, "-e", str(_PLUGIN_DIR)],
        cwd=str(_PLUGIN_DIR),
        capture_output=True,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace") if result.stderr else ""
        raise RuntimeError(f"agent-zero-cortex self-install failed: {stderr}")
