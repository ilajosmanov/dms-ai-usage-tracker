"""Regression coverage for fresh Dux installs and legacy settings."""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from collector.main import main


class ConfigTests(unittest.TestCase):
    def test_collector_reads_dux_settings_in_preference_to_legacy(self):
        self.check_collector({"dms": 17, "DankMaterialShell": 9}, 17)

    def test_collector_reads_legacy_settings_when_dux_directory_is_absent(self):
        self.check_collector({"DankMaterialShell": 9}, 9)

    def test_empty_dux_settings_do_not_resurrect_old_settings(self):
        self.check_collector({"dms": None, "DankMaterialShell": 9}, None)

    def check_collector(self, directories, expected):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, interval in directories.items():
                directory = root / name
                directory.mkdir()
                if interval is not None:
                    (directory / "plugin_settings.json").write_text(json.dumps({
                        "aiUsage": {"refreshInterval": interval}}))
            with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(root),
                                         "XDG_CACHE_HOME": str(root / "cache")}), \
                    patch.object(sys, "argv", ["get-ai-usage", "--offline"]), \
                    patch("collector.main.collect", return_value={"accounts": []}) as collect, \
                    patch("collector.main.activity.scan", return_value={}), \
                    contextlib.redirect_stdout(io.StringIO()):
                main()
            expected_config = {} if expected is None else {"refreshInterval": expected}
            self.assertEqual(collect.call_args.args[0], expected_config)

    def test_installer_uses_dux_on_a_fresh_install_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "dms"
            config.mkdir()
            settings = {"barConfigs": [{"enabled": True, "rightWidgets": ["clock"]}]}
            settings_path = config / "settings.json"
            settings_path.write_text(json.dumps(settings))
            repo = Path(__file__).resolve().parents[1]
            env = {**os.environ, "XDG_CONFIG_HOME": str(root), "PATH": ""}
            for _ in range(2):
                result = subprocess.run([sys.executable, str(repo / "scripts/install.py")],
                                        env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((config / "plugins/aiUsage").resolve(), repo)
            widgets = json.loads(settings_path.read_text())["barConfigs"][0]["rightWidgets"]
            self.assertEqual(widgets, [{"id": "aiUsage", "enabled": True}, "clock"])
            backups = list(config.glob("settings.before-ai-usage-*.json"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(json.loads(backups[0].read_text()), settings)
            self.assertFalse((root / "DankMaterialShell").exists())

    def test_installer_scans_before_enabling_and_waits_for_discovery(self):
        self.check_activation(fail=False)

    def test_installer_reports_activation_failure(self):
        self.check_activation(fail=True)

    def check_activation(self, fail):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binary = root / "dms"
            # Simulate asynchronous shell discovery without touching the desktop.
            binary.write_text(f"#!{sys.executable}\n" + """
import os, sys
from pathlib import Path
log = Path(os.environ['XDG_CONFIG_HOME']) / 'calls'
args = ' '.join(sys.argv[1:])
previous = log.read_text() if log.exists() else ''
with log.open('a') as stream:
    stream.write(args + '\\n')
if args == 'ipc call plugin-scan scan':
    print('SCAN_TRIGGERED: 0 known before debounce')
elif args == 'ipc call plugins enable aiUsage':
    if os.environ['FAIL_ACTIVATION'] == '1':
        print('PLUGIN_ENABLE_FAILED: aiUsage')
    elif previous.count('plugins enable') < 1:
        print('PLUGIN_NOT_FOUND: aiUsage')
    else:
        print('PLUGIN_ENABLE_SUCCESS: aiUsage')
else:
    sys.exit(2)
""")
            binary.chmod(0o700)
            config = root / "config"
            config.mkdir()
            repo = Path(__file__).resolve().parents[1]
            result = subprocess.run([sys.executable, str(repo / "scripts/install.py"), "--no-bar"],
                                    env={**os.environ, "PATH": str(root),
                                         "XDG_CONFIG_HOME": str(config),
                                         "FAIL_ACTIVATION": str(int(fail))},
                                    capture_output=True, text=True)
            calls = (config / "calls").read_text().splitlines()
            self.assertEqual(calls[0], "ipc call plugin-scan scan")
            if fail:
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("activation failed", result.stderr)
                self.assertNotIn("Installation complete", result.stdout)
            else:
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(calls.count("ipc call plugins enable aiUsage"), 2)
                self.assertIn("PLUGIN_ENABLE_SUCCESS", result.stdout)
