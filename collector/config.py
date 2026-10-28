"""Locate shell configuration on Dux and older DMS installations."""

import os
from pathlib import Path


def shell_config_dir():
    base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    current = base / "dms"
    legacy = base / "DankMaterialShell"
    # Dux is authoritative when both exist; fresh installs use its new path.
    return current if current.exists() or not legacy.exists() else legacy
