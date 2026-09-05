#!/usr/bin/env python3
"""Render native QML screenshots against installed DMS components, offscreen."""
import os
import shutil
import subprocess
import tempfile
import selectors
import time
from pathlib import Path

repo = Path(__file__).resolve().parents[1]
dms = Path(os.environ.get("DMS_QML_ROOT", "/usr/share/quickshell/dms"))
output = repo / "screenshots"
output.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(prefix="dms-ai-preview-") as staging:
    staging = Path(staging)
    rendered = staging / "rendered"
    rendered.mkdir()
    expected = {name + ".png" for name in ("codex", "claude", "accounts", "missing", "stale", "narrow", "light", "bar", "vertical", "bar_codex", "bar_claude", "bar_over", "bar_idle", "bar_missing", "bar_light")}
    for path in dms.iterdir():
        if path.is_dir():
            (staging / path.name).symlink_to(path)
    (staging / "Plugin").symlink_to(repo)
    shutil.copyfile(repo / "tests/preview.qml", staging / "shell.qml")
    # Keep Theme/Settings singleton initialization isolated from the live desktop.
    config = staging / "config"
    config.mkdir()
    env = {**os.environ, "XDG_CONFIG_HOME": str(config), "XDG_CACHE_HOME": str(staging / "cache"),
           "XDG_STATE_HOME": str(staging / "state"), "QT_QPA_PLATFORM": "offscreen",
           "DMS_SOCKET": "", "NIRI_SOCKET": "", "HYPRLAND_INSTANCE_SIGNATURE": "",
           "QT_QUICK_BACKEND": "software", "AI_USAGE_PREVIEW_OUT": str(rendered)}
    process = subprocess.Popen(["quickshell", "-p", str(staging), "--no-color"], env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    complete = False
    logs = b""
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if expected.issubset({p.name for p in rendered.iterdir()}):
                    complete = True
                    break
                if not selector.select(timeout=1):
                    continue
                chunk = os.read(process.stdout.fileno(), 65536)
                if not chunk:
                    break
                logs += chunk
                if b"AI_USAGE_PREVIEW_COMPLETE" in logs:
                    complete = True
                    break
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        process.stdout.close()
    print(logs.decode(errors="replace"))
    if not complete or any(x in logs for x in (b"ReferenceError", b"TypeError", b"Error:", b"Unable to assign", b"ERROR")):
        raise SystemExit("QML preview failed; inspect the log above.")
    for name in expected:
        shutil.copyfile(rendered / name, output / name)
    print(f"Rendered {len(expected)} native QML states to", output)
