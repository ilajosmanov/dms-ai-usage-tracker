import hashlib
import json
import os
import sqlite3
import tempfile
import time
import unittest
import unittest.mock
import urllib.error
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from collector.credentials import discover
from collector.main import atomic_json, collect, fingerprint_key, private_dir, record_history, refresh_group
from collector.models import recent_models_by_day
from collector.providers import UsageError, parse_claude, parse_codex, request, window


class ProviderTests(unittest.TestCase):
    def test_codex_preserves_actual_primary_duration(self):
        result = parse_codex({"plan_type": "pro", "rate_limit": {"primary_window": {
            "used_percent": 89, "limit_window_seconds": 604800, "reset_at": 1900000000}},
            "additional_rate_limits": [{"metered_feature": "spark", "limit_name": "Spark", "rate_limit": {
                "primary_window": {"used_percent": 0, "limit_window_seconds": 18000, "reset_at": 1900000000}}}]})
        self.assertEqual(result["windows"][0]["label"], "7-day window")
        self.assertEqual(len(result["windows"]), 1, "Codex Spark quota buckets must stay hidden")

    def test_claude_null_model_limits_are_not_zero(self):
        result = parse_claude({"five_hour": {"utilization": 0, "resets_at": "2026-09-05T12:00:00Z"},
                               "seven_day": None, "seven_day_sonnet": None})
        self.assertEqual(len(result["windows"]), 1)
        self.assertEqual(result["windows"][0]["used"], 0)

    def test_claude_ignores_nimbus_quill_but_keeps_real_fable_limit(self):
        result = parse_claude({
            "five_hour": {"utilization": 4},
            "nimbus_quill": {"utilization": 0, "resets_at": None},
            "limits": [{"kind": "weekly_scoped", "percent": 12, "resets_at": "2026-09-12T12:00:00Z",
                        "scope": {"model": {"display_name": "Fable"}}}],
        })
        self.assertEqual([window["label"] for window in result["windows"]], ["5-hour window", "Fable · 7 days"])


    def test_claude_window_order_does_not_follow_response_key_order(self):
        five, seven = {"utilization": 10}, {"utilization": 90}
        for data in ({"five_hour": five, "seven_day": seven}, {"seven_day": seven, "five_hour": five}):
            result = parse_claude(data)
            self.assertEqual([w["id"] for w in result["windows"]], ["five_hour", "seven_day"],
                             "the primary window must not depend on the provider's JSON key order")

    def test_unreachable_network_retries_sooner_than_a_provider_fault(self):
        """A link that is not up yet must not inherit the provider backoff."""
        for raised in (urllib.error.URLError("unreachable"), TimeoutError(), OSError()):
            opener = unittest.mock.Mock()
            opener.open.side_effect = raised
            with patch("collector.providers.urllib.request.build_opener", return_value=opener):
                with self.assertRaises(UsageError) as caught:
                    request("https://chatgpt.com/backend-api/wham/usage", {})
            self.assertLessEqual(caught.exception.retry_after, 15)
            self.assertFalse(caught.exception.rate_limited)

    def test_unavailable_or_nonfinite_is_never_zero(self):
        for value in (None, "NaN", "Infinity", True, -1, "junk"):
            self.assertIsNone(window("test", "Test", value, None, 1))
        for parse in (parse_codex, parse_claude):
            with self.assertRaises(UsageError):
                parse({})



class StateTests(unittest.TestCase):
    def setUp(self):
        self.group = [{"id": "codex-test", "provider": "codex", "source": "Codex", "secret": "private-token", "expires": 1}]
        self.data = {"windows": [{"id": "primary", "label": "5-hour window", "used": 37, "duration": 18000, "resetAt": 1900000000}], "plan": "pro"}
        self.now = time.time()

    def test_snapshot_never_contains_secret(self):
        with patch("collector.main.fetch", return_value=self.data):
            result = refresh_group(self.group, None, self.now)
        self.assertNotIn("private-token", json.dumps(result))
        self.assertEqual(result["status"], "ok")

    def test_stored_fingerprint_is_not_a_bare_hash_of_the_token(self):
        """Anyone reading the cache must not be able to confirm a guessed token."""
        bare = hashlib.sha256(json.dumps(["private-token"]).encode()).hexdigest()
        with patch("collector.main.fetch", return_value=self.data):
            result = refresh_group(self.group, None, self.now, key=b"install-key")
        self.assertNotEqual(result["credentialFingerprint"], bare)
        with patch("collector.main.fetch", return_value=self.data):
            other = refresh_group(self.group, None, self.now, key=b"another-install")
        self.assertNotEqual(result["credentialFingerprint"], other["credentialFingerprint"])

    def test_install_key_is_private_and_stable(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder) / "cache"
            key = fingerprint_key(directory)
            self.assertEqual(len(key), 32)
            self.assertEqual(fingerprint_key(directory), key, "a rotated key would refresh on every poll")
            self.assertEqual((directory / "fingerprint.key").stat().st_mode & 0o777, 0o600)
            self.assertEqual(directory.stat().st_mode & 0o777, 0o700)

    def test_refresh_bookkeeping_is_never_published_to_the_widget(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cache.json"
            with patch("collector.main.discover", return_value={"codex-test": self.group}), \
                 patch("collector.main.fetch", return_value=self.data):
                result = collect({}, path)
            published = json.dumps(result)
            for field in ("credentialFingerprint", "lastAttempt", "nextAttempt", "retryNotBefore"):
                self.assertNotIn(field, published, f"{field} is private scheduling state")
            self.assertIn("credentialFingerprint", path.read_text(), "the cache still needs it to detect a new login")
            self.assertEqual(result["accounts"][0]["windows"][0]["used"], 37)

    def test_network_error_retains_explicitly_stale_values(self):
        with patch("collector.main.fetch", return_value=self.data):
            cached = refresh_group(self.group, None, self.now)
        with patch("collector.main.fetch", side_effect=UsageError("Offline")):
            stale = refresh_group(self.group, cached, self.now + 121)
        self.assertEqual(stale["status"], "stale")
        self.assertEqual(stale["updatedAt"], self.now)
        self.assertEqual(stale["windows"][0]["used"], 37)

    def test_expired_cache_is_not_presented_as_usage(self):
        with patch("collector.main.fetch", side_effect=UsageError("Offline")):
            result = refresh_group(self.group, {"updatedAt": self.now - 90000, "windows": self.data["windows"]}, self.now)
        self.assertEqual(result["windows"], [])
        self.assertEqual(result["status"], "error")

    def test_cache_and_backoff_avoid_duplicate_network_calls(self):
        with patch("collector.main.fetch", return_value=self.data) as fetch:
            cached = refresh_group(self.group, None, self.now)
            refresh_group(self.group, cached, self.now + 60)
            self.assertEqual(fetch.call_count, 1)
        with patch("collector.main.fetch", side_effect=UsageError("Rate limit", retry_after=600)) as fetch:
            error = refresh_group(self.group, None, self.now)
            refresh_group(self.group, error, self.now + 300)
            self.assertEqual(fetch.call_count, 1)

    def test_auth_fallback_uses_same_account_other_client(self):
        with patch("collector.main.fetch", side_effect=[UsageError("Expired", "auth"), self.data]) as fetch:
            result = refresh_group(self.group + [{**self.group[0], "source": "pi"}], None, self.now)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(fetch.call_count, 2)

    def test_new_login_does_not_reuse_cached_sign_in_error(self):
        with patch("collector.main.fetch", side_effect=UsageError("Expired", "auth")):
            cached = refresh_group(self.group, None, self.now)
        signed_in = [{**self.group[0], "secret": "new-login-token"}]
        with patch("collector.main.fetch", return_value=self.data) as fetch:
            result = refresh_group(signed_in, cached, self.now + 1)
        self.assertEqual(result["status"], "ok", "A new login must bypass the old token's cached auth error")
        self.assertEqual(fetch.call_count, 1)

    def test_manual_refresh_bypasses_normal_cache_but_not_click_cooldown(self):
        with patch("collector.main.fetch", return_value=self.data) as fetch:
            cached = refresh_group(self.group, None, self.now)
            refresh_group(self.group, cached, self.now + 1, force=True)
            self.assertEqual(fetch.call_count, 1)
            refresh_group(self.group, cached, self.now + 6, force=True)
            self.assertEqual(fetch.call_count, 2)

    def test_manual_refresh_and_new_login_respect_provider_rate_limit(self):
        with patch("collector.main.fetch", side_effect=UsageError("Slow down", retry_after=600, rate_limited=True)):
            cached = refresh_group(self.group, None, self.now)
        with patch("collector.main.fetch", return_value=self.data) as fetch:
            refresh_group(self.group, cached, self.now + 6, force=True)
            fresh_login = [{**self.group[0], "secret": "new-login-token"}]
            refresh_group(fresh_login, cached, self.now + 6, force=True)
            fetch.assert_not_called()

    def test_local_poll_keeps_configured_api_interval(self):
        with patch("collector.main.fetch", return_value=self.data) as fetch:
            cached = refresh_group(self.group, None, self.now, interval=900)
            for seconds in range(5, 900, 5):
                cached = refresh_group(self.group, cached, self.now + seconds, interval=900)
            self.assertEqual(fetch.call_count, 1)

    def test_resume_from_suspend_recovers_without_a_manual_refresh(self):
        """The first poll after waking races the network coming back; the next one must not be gated."""
        with patch("collector.main.fetch", return_value=self.data):
            cached = refresh_group(self.group, None, self.now)
        resume = self.now + 7 * 3600
        with patch("collector.main.fetch", side_effect=UsageError("Could not reach the provider.", retry_after=10)):
            missed = refresh_group(self.group, cached, resume)
        self.assertEqual(missed["status"], "stale")
        with patch("collector.main.fetch", return_value=self.data) as fetch:
            recovered = refresh_group(self.group, missed, resume + 30)
            fetch.assert_called_once()
        self.assertEqual(recovered["status"], "ok")
        self.assertEqual(recovered["updatedAt"], resume + 30)

    def test_history_survives_a_renamed_window_but_never_mixes_lengths(self):
        yesterday = str(datetime.fromtimestamp(self.now).date() - timedelta(days=1))
        peaks = [{"date": yesterday, "value": 40, "window": "five_hour", "duration": 18000}]
        renamed = record_history({"windows": [{"id": "5h", "used": 10, "duration": 18000}], "history": peaks}, self.now)
        self.assertEqual(len(renamed["history"]), 2, "a renamed window of the same length keeps its peaks")
        regrouped = record_history({"windows": [{"id": "7d", "used": 10, "duration": 604800}], "history": peaks}, self.now)
        self.assertEqual(len(regrouped["history"]), 1, "peaks from a different window length are not comparable")

    def test_unchanged_usage_does_not_rewrite_the_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cache.json"
            with patch("collector.main.discover", return_value={"codex-test": self.group}), \
                 patch("collector.main.fetch", return_value=self.data):
                collect({}, path)
                written = path.read_bytes()
                with patch("collector.main.atomic_json") as write:
                    collect({}, path)
                    write.assert_not_called()
            self.assertEqual(path.read_bytes(), written)

    def test_no_credentials_gives_two_connection_states(self):
        with tempfile.TemporaryDirectory() as folder, patch("collector.main.discover", return_value={}):
            result = collect({}, Path(folder) / "cache.json")
        self.assertEqual([a["provider"] for a in result["accounts"]], ["codex", "claude"])
        self.assertTrue(all(a["status"] == "missing" for a in result["accounts"]))

    def test_existing_cache_directory_is_tightened(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder) / "cache"
            directory.mkdir(mode=0o755)
            self.assertEqual(private_dir(directory).stat().st_mode & 0o777, 0o700)

    def test_private_atomic_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cache.json"
            atomic_json(path, {"v": 1})
            atomic_json(path, {"v": 2})
            self.assertEqual(json.loads(path.read_text()), {"v": 2})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_account_switch_never_reuses_previous_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cache.json"
            atomic_json(path, {"accounts": {"old-account": {"updatedAt": self.now, "windows": self.data["windows"]}}})
            with patch("collector.main.discover", return_value={"codex-test": self.group}), patch("collector.main.fetch", side_effect=UsageError("Expired", "auth")):
                result = collect({}, path)
            self.assertEqual(result["accounts"][0]["windows"], [])


class CredentialTests(unittest.TestCase):
    def test_header_unsafe_credentials_are_skipped(self):
        """Both the token and the account id travel in request headers."""
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True):
            home = Path(folder)
            (home / ".codex").mkdir()
            for tokens in ({"access_token": "bad\r\nX-Injected: 1", "account_id": "a"},
                           {"access_token": "good-token", "account_id": "b\r\nX-Injected: 1"}):
                (home / ".codex/auth.json").write_text(json.dumps({"tokens": tokens}))
                for group in discover({}, home).values():
                    for credential in group:
                        self.assertNotIn("\r", credential["secret"] + credential["account"])
                        self.assertNotIn("\n", credential["secret"] + credential["account"])

    def test_identity_survives_a_rotated_opaque_token(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True):
            home = Path(folder)
            (home / ".claude").mkdir()

            def identities(token):
                (home / ".claude/.credentials.json").write_text(json.dumps(
                    {"claudeAiOauth": {"accessToken": token, "refreshToken": "r", "expiresAt": 1}}))
                return list(discover({}, home))

            self.assertEqual(identities("sk-ant-oat01-first"), identities("sk-ant-oat01-second"),
                             "a rotated token must not orphan the account's cached history")

    def test_client_dedup_and_omp_sqlite(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True):
            home = Path(folder)
            def write(path, data):
                target = home / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(data))
            write(".codex/auth.json", {"tokens": {"access_token": "codex-token", "account_id": "same-account"}})
            write(".pi/agent/auth.json", {"openai-codex": {"type": "oauth", "access": "pi-token", "accountId": "same-account"}})
            write(".local/share/opencode/auth.json", {"openai": {"type": "api", "key": "do-not-use-api-for-subscription"}})
            db = home / ".omp/agent/agent.db"
            db.parent.mkdir(parents=True)
            with closing(sqlite3.connect(db)) as conn:
                conn.execute("CREATE TABLE auth_credentials (id INTEGER, provider TEXT, credential_type TEXT, data TEXT, disabled_cause TEXT)")
                conn.execute("INSERT INTO auth_credentials VALUES (1,'openai-codex','oauth',?,NULL)", (json.dumps({"access": "omp-token", "accountId": "other-account"}),))
                conn.execute("INSERT INTO auth_credentials VALUES (2,'openai-codex','oauth',?,'disabled')", (json.dumps({"access": "disabled"}),))
                conn.execute("INSERT INTO auth_credentials VALUES (3,'openai-codex','api',?,NULL)", (json.dumps({"key": "do-not-use-api-key"}),))
                conn.commit()
            before = db.read_bytes()
            result = discover({}, home)
            self.assertEqual(db.read_bytes(), before)
            self.assertEqual(len(result), 2)
            codex = next(g for g in result.values() if g[0]["provider"] == "codex")
            self.assertEqual(len(codex), 2)
            self.assertFalse(any("do-not-use" in c["secret"] for g in result.values() for c in g))


class ModelTests(unittest.TestCase):
    def test_recent_models_are_grouped_by_session_day(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True):
            home = Path(folder)
            now = time.time()
            today = str(datetime.fromtimestamp(now).date())
            yesterday = str(datetime.fromtimestamp(now).date() - timedelta(days=1))

            def session(path, rows, age=0):
                target = home / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
                os.utime(target, (now - age, now - age))

            session(".codex/sessions/current.jsonl", [
                {"type": "turn_context", "timestamp": datetime.fromtimestamp(now).astimezone().isoformat(),
                 "payload": {"model": "gpt-5.6-sol"}},
                {"type": "turn_context", "payload": {"model": "gpt-5.3-codex-spark"}},
            ])
            session(".omp/agent/sessions/current.jsonl", [
                {"timestamp": datetime.fromtimestamp(now - 86400).astimezone().isoformat(),
                 "model": "openai-codex/gpt-6-astra"}
            ])
            session(".pi/agent/sessions/current.jsonl", [{"message": {"model": "gpt-5.6-terra"}}])
            session(".claude/projects/current.jsonl", [
                {"message": {"model": "claude-opus-5"}},
                {"message": {"model": "<synthetic>"}},
            ])
            session(".claude/projects/old.jsonl", [{"message": {"model": "claude-fable-5"}}], 8 * 86400)
            opencode = home / ".local/share/opencode/opencode.db"
            opencode.parent.mkdir(parents=True)
            with closing(sqlite3.connect(opencode)) as connection:
                connection.execute("CREATE TABLE session (model TEXT, time_updated INTEGER)")
                connection.execute("INSERT INTO session VALUES (?, ?)",
                                   (json.dumps({"id": "gpt-5.6-luna", "providerID": "openai"}), int(now * 1000)))
                connection.execute("INSERT INTO session VALUES (?, ?)",
                                   (json.dumps({"id": "claude-opus-5", "providerID": "anthropic"}), int(now * 1000)))
                connection.commit()

            self.assertEqual(recent_models_by_day(home, now), {
                "codex": {
                    today: ["GPT-5.6 Sol", "GPT-5.6 Terra", "GPT-5.6 Luna"],
                    yesterday: ["GPT-6 Astra"],
                },
                "claude": {today: ["Claude Opus 5"]},
            })


if __name__ == "__main__":
    unittest.main()
