from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_PLUGIN_DIR = Path(__file__).resolve().parent


def install(**kwargs) -> None:
    """Called by AZ after the plugin is placed in usr/plugins/.

    Installs the plugin package (and its dependencies: httpx, dirtyjson)
    into the AZ framework runtime so `import cortex_plugin` works.
    """
    _pip_install_editable()


def uninstall(**kwargs) -> None:
    """Called by AZ before the plugin directory is deleted."""
    _pip_uninstall()


def pre_update(**kwargs) -> None:
    """Called by AZ immediately before pulling new plugin code.

    Nothing to do — pip install after the update (next install() call)
    will upgrade the package in place.
    """


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pip_install_editable() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-e", str(_PLUGIN_DIR)],
        check=False,
        text=True,
        capture_output=True,
        timeout=120,
    )
    if result.returncode == 0:
        logger.info("agent-zero-cortex: pip install succeeded")
    else:
        output = (result.stderr or result.stdout or "pip install failed").strip()
        logger.warning("agent-zero-cortex: pip install failed: %s", output)


def _pip_uninstall() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "pip", "uninstall", "-y", "agent-zero-cortex"],
        check=False,
        text=True,
        capture_output=True,
        timeout=60,
    )
    if result.returncode == 0:
        logger.info("agent-zero-cortex: pip uninstall succeeded")
    else:
        output = (result.stderr or result.stdout or "pip uninstall failed").strip()
        logger.warning("agent-zero-cortex: pip uninstall failed: %s", output)
