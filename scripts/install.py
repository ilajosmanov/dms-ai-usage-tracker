#!/usr/bin/env python3
"""Install a development symlink and add AI Usage to the first enabled DankBar."""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

repo = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo))
from collector.main import atomic_json

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--no-bar", action="store_true", help="Install only; select the widget in DMS settings yourself.")
args = parser.parse_args()
config = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "DankMaterialShell"
target = config / "plugins/aiUsage"
target.parent.mkdir(parents=True, exist_ok=True)
if target.is_symlink() and target.resolve() == repo:
    print("Plugin is already linked.")
elif target.exists() or target.is_symlink():
    raise SystemExit(f"Existing installation at {target}; preserved. Move it aside before installing this checkout.")
else:
    target.symlink_to(repo, target_is_directory=True)
    print("Linked", target, "→", repo)

settings_path = config / "settings.json"
if not args.no_bar and settings_path.is_file():
    raw = settings_path.read_bytes()
    settings = json.loads(raw)
    bars = settings.get("barConfigs", [])
    bar = next((b for b in bars if b.get("enabled", True)), None)
    if bar is None:
        print("No enabled bar found. Add AI Usage in DMS settings.")
    else:
        def widget_id(widget):
            return widget.get("id") if isinstance(widget, dict) else widget
        present = any(widget_id(w) == "aiUsage" for side in ("leftWidgets", "centerWidgets", "rightWidgets") for w in bar.get(side, []))
        if not present:
            backup = settings_path.with_name("settings.before-ai-usage-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".json")
            shutil.copy2(settings_path, backup)
            bar.setdefault("rightWidgets", []).insert(0, {"id": "aiUsage", "enabled": True})
            if settings_path.read_bytes() != raw:
                raise SystemExit("Settings changed during installation. Plugin linked; run installer again to add it to the bar.")
            atomic_json(settings_path, settings, settings_path.stat().st_mode & 0o777)
            print("Added to", bar.get("name", "DankBar"), "· settings backup:", backup)

if shutil.which("dms"):
    for command in (["dms", "ipc", "call", "plugin-scan", "rescan", "aiUsage"],
                    ["dms", "ipc", "call", "plugins", "enable", "aiUsage"]):
        result = subprocess.run(command, text=True, capture_output=True, timeout=10)
        for _ in range(5):
            if "PLUGIN_NOT_FOUND" not in result.stdout:
                break
            time.sleep(0.2)
            result = subprocess.run(command, text=True, capture_output=True, timeout=10)
        print(result.stdout.strip() or result.stderr.strip())
print("If the widget is not visible yet, enable AI Usage in DMS Settings → Plugins and add it under DankBar widgets.")
