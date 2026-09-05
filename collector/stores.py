"""Where each supported client keeps its data. Adding a client is one edit here."""

import os
from pathlib import Path


def roots(home=None):
    """Per-client base directories, honoring each client's own environment override."""
    home = Path(home) if home else Path.home()
    return {
        "codex": Path(os.environ.get("CODEX_HOME", str(home / ".codex"))),
        "claude": Path(os.environ.get("CLAUDE_CONFIG_DIR", str(home / ".claude"))),
        "pi": Path(os.environ.get("PI_CODING_AGENT_DIR", str(home / ".pi/agent"))),
        "omp": home / ".omp/agent",
        "opencode": Path(os.environ.get("XDG_DATA_HOME", str(home / ".local/share"))) / "opencode",
    }
