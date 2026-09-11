#!/usr/bin/env python3
"""Render docs/screenshot.png: the bar pill and the popout it opens, on real usage.

The registry preview card overlays the plugin's own name on this image, so a
screenshot that still carries an older name reads as a different plugin. Keep it
regenerated whenever the bar or the popout changes.

Unlike scripts/preview.py this runs the collector without `--demo`, so the output
holds the real percentages, plan tiers, and per-model token totals of whoever runs
it. That is what makes it a useful screenshot, and what to look at before
committing one.
"""
import os
import selectors
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

repo = Path(__file__).resolve().parents[1]
dms = Path(os.environ.get("DMS_QML_ROOT", "/usr/share/quickshell/dms"))
target = repo / "docs/screenshot.png"
with tempfile.TemporaryDirectory(prefix="dms-ai-capture-") as staging:
    staging = Path(staging)
    rendered = staging / "screenshot.png"
    for path in dms.iterdir():
        if path.is_dir():
            (staging / path.name).symlink_to(path)
    (staging / "Plugin").symlink_to(repo)
    shutil.copyfile(repo / "tests/capture.qml", staging / "shell.qml")
    # Keep Theme/Settings singleton initialization isolated from the live desktop,
    # so the capture always lands on the stock dank theme.
    config = staging / "config"
    config.mkdir()
    env = {**os.environ, "XDG_CONFIG_HOME": str(config), "XDG_CACHE_HOME": str(staging / "cache"),
           "XDG_STATE_HOME": str(staging / "state"), "QT_QPA_PLATFORM": "offscreen",
           "DMS_SOCKET": "", "NIRI_SOCKET": "", "HYPRLAND_INSTANCE_SIGNATURE": "",
           "QT_QUICK_BACKEND": "software", "AI_USAGE_CAPTURE_OUT": str(rendered)}
    process = subprocess.Popen(["quickshell", "-p", str(staging), "--no-color"], env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    logs = b""
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if rendered.exists():
                    break
                if not selector.select(timeout=1):
                    continue
                chunk = os.read(process.stdout.fileno(), 65536)
                if not chunk:
                    break
                logs += chunk
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        process.stdout.close()
    if not rendered.exists():
        print(logs.decode(errors="replace"))
        raise SystemExit("Capture failed; inspect the log above.")
    shutil.copyfile(rendered, target)
print("Wrote", target, "- check it for anything you would rather not publish.")
