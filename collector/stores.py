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


def claude_config(home=None):
    """Claude Code's own global config file.

    It is the one client file that does not live under the client's directory:
    `CLAUDE_CONFIG_DIR` moves the file itself, and without it the file sits beside
    `~/.claude`, not inside it.
    """
    home = Path(home) if home else Path.home()
    return Path(os.environ.get("CLAUDE_CONFIG_DIR", str(home))) / ".claude.json"


def claude_profile(config, home=None):
    """Resolve the credential and config files as one native Claude profile."""
    default = roots(home)["claude"] / ".credentials.json"
    auth = Path(config.get("claudeAuthFile") or default).expanduser().absolute()
    custom = auth != default.expanduser().absolute()
    directory = str(auth.parent) if custom else os.environ.get("CLAUDE_CONFIG_DIR", "")
    state = auth.parent / ".claude.json" if custom else claude_config(home)
    return {"authFile": str(auth), "configFile": str(state.absolute()), "configDir": directory}
