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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from collector import activity, local
from collector.credentials import discover
from collector.jsonfile import atomic_json, private_dir
from collector.main import collect, fingerprint_key, public, record_history, refresh_group
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


    def test_claude_carries_the_services_own_verdict_on_each_window(self):
        result = parse_claude({"limits": [
            {"kind": "session", "percent": 3, "severity": "normal", "is_active": False},
            {"kind": "weekly_all", "percent": 76, "severity": "warning", "is_active": False},
            {"kind": "weekly_scoped", "percent": 97, "severity": "critical", "is_active": True,
             "scope": {"model": {"display_name": "Fable"}}}]})
        self.assertEqual([(w["severity"], w["active"]) for w in result["windows"]],
                         [("normal", False), ("warning", False), ("critical", True)])

    def test_a_provider_that_reports_no_verdict_still_gets_a_usable_window(self):
        """Codex sends neither flag, and the panel must not have to guess their type."""
        codex = parse_codex({"rate_limit": {"primary_window": {
            "used_percent": 20, "limit_window_seconds": 18000, "reset_at": 1900000000}}})
        legacy = parse_claude({"five_hour": {"utilization": 40}})
        for windows in (codex["windows"], legacy["windows"]):
            self.assertEqual(windows[0]["severity"], "")
            self.assertIs(windows[0]["active"], False)

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

    def test_retry_after_preserves_long_waits_and_http_dates(self):
        from email.utils import formatdate
        import urllib.error
        now = time.time()
        for retry in ("7200", formatdate(now + 7200, usegmt=True)):
            opener = unittest.mock.Mock()
            opener.open.side_effect = urllib.error.HTTPError(
                "https://chatgpt.com/backend-api/wham/usage", 429, "Rate limited",
                {"Retry-After": retry}, None)
            with patch("collector.providers.urllib.request.build_opener", return_value=opener):
                with self.assertRaises(UsageError) as caught:
                    request("https://chatgpt.com/backend-api/wham/usage", {})
            self.assertGreater(caught.exception.retry_after, 7100)
            self.assertTrue(caught.exception.rate_limited)

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
        # An empty home, so nothing here can read the developer's own client state
        # and every test decides for itself what usage exists.
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.home = Path(folder.name)
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def refresh(self, *arguments, **options):
        return refresh_group(*arguments, home=self.home, **options)

    def test_snapshot_never_contains_secret(self):
        with patch("collector.main.fetch", return_value=self.data):
            result = self.refresh(self.group, None, self.now)
        self.assertNotIn("private-token", json.dumps(result))
        self.assertEqual(result["status"], "ok")

    def test_stored_fingerprint_is_not_a_bare_hash_of_the_token(self):
        """Anyone reading the cache must not be able to confirm a guessed token."""
        bare = hashlib.sha256(json.dumps(["private-token"]).encode()).hexdigest()
        with patch("collector.main.fetch", return_value=self.data):
            result = self.refresh(self.group, None, self.now, key=b"install-key")
        self.assertNotEqual(result["credentialFingerprint"], bare)
        with patch("collector.main.fetch", return_value=self.data):
            other = self.refresh(self.group, None, self.now, key=b"another-install")
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
                result = collect({}, path, home=self.home)
            published = json.dumps(result)
            for field in ("credentialFingerprint", "lastAttempt", "nextAttempt", "retryNotBefore"):
                self.assertNotIn(field, published, f"{field} is private scheduling state")
            self.assertIn("credentialFingerprint", path.read_text(), "the cache still needs it to detect a new login")
            self.assertEqual(result["accounts"][0]["windows"][0]["used"], 37)

    def test_network_error_retains_explicitly_stale_values(self):
        with patch("collector.main.fetch", return_value=self.data):
            cached = self.refresh(self.group, None, self.now)
        with patch("collector.main.fetch", side_effect=UsageError("Offline")):
            stale = self.refresh(self.group, cached, self.now + 121)
        self.assertEqual(stale["status"], "stale")
        self.assertEqual(stale["updatedAt"], self.now)
        self.assertEqual(stale["windows"][0]["used"], 37)

    def test_expired_cache_is_not_presented_as_usage(self):
        with patch("collector.main.fetch", side_effect=UsageError("Offline")):
            result = self.refresh(self.group, {"updatedAt": self.now - 90000, "windows": self.data["windows"]}, self.now)
        self.assertEqual(result["windows"], [])
        self.assertEqual(result["status"], "error")

    def test_cache_and_backoff_avoid_duplicate_network_calls(self):
        with patch("collector.main.fetch", return_value=self.data) as fetch:
            cached = self.refresh(self.group, None, self.now)
            self.refresh(self.group, cached, self.now + 60)
            self.assertEqual(fetch.call_count, 1)
        with patch("collector.main.fetch", side_effect=UsageError("Rate limit", retry_after=600)) as fetch:
            error = self.refresh(self.group, None, self.now)
            self.refresh(self.group, error, self.now + 300)
            self.assertEqual(fetch.call_count, 1)

    def test_auth_fallback_uses_same_account_other_client(self):
        with patch("collector.main.fetch", side_effect=[UsageError("Expired", "auth"), self.data]) as fetch:
            result = self.refresh(self.group + [{**self.group[0], "source": "pi"}], None, self.now)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(fetch.call_count, 2)

    def test_new_login_does_not_reuse_cached_sign_in_error(self):
        with patch("collector.main.fetch", side_effect=UsageError("Expired", "auth")):
            cached = self.refresh(self.group, None, self.now)
        signed_in = [{**self.group[0], "secret": "new-login-token"}]
        with patch("collector.main.fetch", return_value=self.data) as fetch:
            result = self.refresh(signed_in, cached, self.now + 1)
        self.assertEqual(result["status"], "ok", "A new login must bypass the old token's cached auth error")
        self.assertEqual(fetch.call_count, 1)

    def test_manual_refresh_bypasses_normal_cache_but_not_click_cooldown(self):
        with patch("collector.main.fetch", return_value=self.data) as fetch:
            cached = self.refresh(self.group, None, self.now)
            self.refresh(self.group, cached, self.now + 1, force=True)
            self.assertEqual(fetch.call_count, 1)
            self.refresh(self.group, cached, self.now + 6, force=True)
            self.assertEqual(fetch.call_count, 2)

    def test_manual_refresh_and_new_login_respect_provider_rate_limit(self):
        with patch("collector.main.fetch", side_effect=UsageError("Slow down", retry_after=600, rate_limited=True)):
            cached = self.refresh(self.group, None, self.now)
        with patch("collector.main.fetch", return_value=self.data) as fetch:
            self.refresh(self.group, cached, self.now + 6, force=True)
            fresh_login = [{**self.group[0], "secret": "new-login-token"}]
            self.refresh(fresh_login, cached, self.now + 6, force=True)
            fetch.assert_not_called()

    def test_a_rate_limited_account_publishes_when_the_wait_lifts(self):
        """The refusal above is correct but invisible; the panel has to be able to explain it."""
        with patch("collector.main.fetch", side_effect=UsageError("Slow down", retry_after=600, rate_limited=True)):
            limited = self.refresh(self.group, None, self.now)
        self.assertEqual(public(limited)["retryAt"], self.now + 600)
        with patch("collector.main.fetch", return_value=self.data):
            recovered = self.refresh(self.group, limited, self.now + 601)
        self.assertEqual(recovered["status"], "ok")
        self.assertEqual(public(recovered)["retryAt"], 0, "a successful check leaves no wait to announce")

    def test_an_ordinary_failure_is_not_reported_as_a_provider_backoff(self):
        with patch("collector.main.fetch", side_effect=UsageError("Could not reach the provider.", retry_after=10)):
            offline = self.refresh(self.group, None, self.now)
        self.assertEqual(public(offline)["retryAt"], 0, "a manual refresh can still shorten this one")

    def test_a_cache_written_before_retry_at_existed_still_counts_down(self):
        legacy = {"id": "codex-x", "provider": "codex", "status": "stale", "retryNotBefore": self.now + 600}
        self.assertEqual(public(legacy)["retryAt"], self.now + 600)

    def test_local_poll_keeps_configured_api_interval(self):
        with patch("collector.main.fetch", return_value=self.data) as fetch:
            cached = self.refresh(self.group, None, self.now, interval=900)
            for seconds in range(5, 900, 5):
                cached = self.refresh(self.group, cached, self.now + seconds, interval=900)
            self.assertEqual(fetch.call_count, 1)

    def test_resume_from_suspend_recovers_without_a_manual_refresh(self):
        """The first poll after waking races the network coming back; the next one must not be gated."""
        with patch("collector.main.fetch", return_value=self.data):
            cached = self.refresh(self.group, None, self.now)
        resume = self.now + 7 * 3600
        with patch("collector.main.fetch", side_effect=UsageError("Could not reach the provider.", retry_after=10)):
            missed = self.refresh(self.group, cached, resume)
        self.assertEqual(missed["status"], "stale")
        with patch("collector.main.fetch", return_value=self.data) as fetch:
            recovered = self.refresh(self.group, missed, resume + 30)
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

    def test_history_tracks_the_shortest_window_not_the_fullest_one(self):
        """The panel headlines whichever window is fullest; the sparkline must not.

        A five-hour peak and a weekly peak are different quantities, so following
        the headline would make `comparable` discard the week every time it moved.
        """
        yesterday = str(datetime.fromtimestamp(self.now).date() - timedelta(days=1))
        peaks = [{"date": yesterday, "value": 40, "window": "five_hour", "duration": 18000}]
        windows = [{"id": "seven_day", "used": 97, "duration": 604800},
                   {"id": "five_hour", "used": 3, "duration": 18000}]
        for order in (windows, list(reversed(windows))):
            result = record_history({"windows": order, "history": list(peaks)}, self.now)
            today = [x for x in result["history"] if x["date"] != yesterday][0]
            self.assertEqual(today["value"], 3, "the fuller weekly window must not enter a 5-hour series")
            self.assertEqual(len(result["history"]), 2, "yesterday's 5-hour peak survives")

    def test_unchanged_usage_does_not_rewrite_the_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cache.json"
            with patch("collector.main.discover", return_value={"codex-test": self.group}), \
                 patch("collector.main.fetch", return_value=self.data):
                collect({}, path, home=self.home)
                written = path.read_bytes()
                with patch("collector.main.atomic_json") as write:
                    collect({}, path, home=self.home)
                    write.assert_not_called()
            self.assertEqual(path.read_bytes(), written)

    def test_no_credentials_gives_two_connection_states(self):
        with tempfile.TemporaryDirectory() as folder, patch("collector.main.discover", return_value={}):
            result = collect({}, Path(folder) / "cache.json", home=self.home)
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
                result = collect({}, path, home=self.home)
            self.assertEqual(result["accounts"][0]["windows"], [])


class LocalStateTests(unittest.TestCase):
    """Readings a client already paid for, taken from that client's own files."""

    def setUp(self):
        self.now = time.time()
        self.group = [{"id": "codex-test", "provider": "codex", "source": "Codex", "secret": "token", "expires": 1}]
        self.claude_group = [{"id": "claude-test", "provider": "claude", "source": "Claude Code", "secret": "token", "expires": 1}]
        self.data = {"windows": [{"id": "primary", "label": "5-hour window", "used": 37, "duration": 18000, "resetAt": 1900000000}], "plan": "pro"}
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.home = Path(folder.name)
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    # Exactly what Codex logs on a turn, trimmed to the fields that carry usage.
    LIMITS = {"limit_id": "codex", "limit_name": None,
              "primary": {"used_percent": 41.0, "window_minutes": 10080, "resets_at": 1789374681},
              "secondary": None, "credits": {"has_credits": False, "unlimited": False, "balance": "0"},
              "individual_limit": None, "spend_control_reached": None, "plan_type": "pro",
              "rate_limit_reached_type": None}

    def rollout(self, age=60, limits=None, name="rollout-test.jsonl", extra=None):
        path = self.home / ".codex/sessions/2026/09/08" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.fromtimestamp(self.now - age, timezone.utc).isoformat().replace("+00:00", "Z")
        rows = [{"timestamp": stamp, "ordinal": 1, "type": "event_msg",
                 "payload": {"type": "token_count", "rate_limits": limits or self.LIMITS}}]
        path.write_text("\n".join(json.dumps(row) for row in (extra or []) + rows) + "\n")
        os.utime(path, (self.now - age, self.now - age))
        return path

    def claude_state(self, age=60, payload=None):
        path = self.home / ".claude.json"
        path.write_text(json.dumps({"oauthAccount": {"accountUuid": "account-uuid"}, "cachedUsageUtilization": {
            "fetchedAtMs": (self.now - age) * 1000, "accountUuid": "account-uuid",
            "utilization": payload or {"five_hour": {"utilization": 12.0, "resets_at": "2026-09-08T13:10:00Z"},
                                       "seven_day": {"utilization": 3.0, "resets_at": "2026-09-12T07:00:00Z"}}}}))
        return path

    def refresh(self, *arguments, **options):
        return refresh_group(*arguments, home=self.home, **options)

    def established(self, group=None, age=600):
        """A cache entry the provider has already confirmed, as a running install has."""
        with patch("collector.main.fetch", return_value=self.data):
            return self.refresh(group or self.group, None, self.now - age)

    def test_a_running_client_answers_instead_of_the_provider(self):
        """The whole point: the quota is per account, so one of us must not spend it twice."""
        self.rollout(age=60)
        with patch("collector.main.fetch", return_value=self.data) as fetch:
            result = self.refresh(self.group, self.established(), self.now)
        fetch.assert_not_called()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["origin"], "Codex")
        self.assertEqual(result["windows"][0]["used"], 41.0)

    def test_a_reading_is_dated_when_the_client_took_it_not_when_we_read_it(self):
        self.rollout(age=95)
        with patch("collector.main.fetch", return_value=self.data):
            result = self.refresh(self.group, self.established(), self.now)
        self.assertAlmostEqual(result["updatedAt"], self.now - 95, delta=1)

    def test_the_newest_reading_wins_across_open_sessions(self):
        self.rollout(age=900, name="rollout-old.jsonl")
        self.rollout(age=30, name="rollout-new.jsonl",
                     limits={**self.LIMITS, "primary": {"used_percent": 44.0, "window_minutes": 10080,
                                                        "resets_at": 1789374681}})
        with patch("collector.main.fetch", return_value=self.data):
            result = self.refresh(self.group, self.established(), self.now)
        self.assertEqual(result["windows"][0]["used"], 44.0)

    def test_client_state_only_answers_for_that_clients_own_account(self):
        """A second account found through another client must never inherit these numbers."""
        self.rollout(age=60)
        other = [{**self.group[0], "id": "codex-other", "source": "opencode"}]
        with patch("collector.main.fetch", return_value=self.data) as fetch:
            result = self.refresh(other, None, self.now)
        fetch.assert_called_once()
        self.assertEqual(result["origin"], "")
        self.assertEqual(result["windows"][0]["used"], 37)

    def test_a_rate_limited_provider_still_serves_a_newer_client_reading(self):
        """The case that started this: saved usage went stale while Codex kept checking."""
        with patch("collector.main.fetch", return_value=self.data):
            checked = self.refresh(self.group, None, self.now - 2300)
        with patch("collector.main.fetch", side_effect=UsageError(
                "Provider rate limited this check. Retrying later.", retry_after=3600, rate_limited=True)):
            limited = self.refresh(self.group, checked, self.now - 1760)
        self.assertEqual(limited["windows"][0]["used"], 37, "before the fix, that is all there was to show")
        self.rollout(age=300)
        with patch("collector.main.fetch", return_value=self.data) as fetch:
            result = self.refresh(self.group, limited, self.now)
        fetch.assert_not_called()
        self.assertEqual(result["windows"][0]["used"], 41.0, "a five-minute reading beats a forty-minute one")
        self.assertAlmostEqual(result["updatedAt"], self.now - 300, delta=1)
        self.assertEqual(result["status"], "stale", "it is still not a check of our own")
        self.assertEqual(public(result)["retryAt"], self.now - 1760 + 3600,
                         "reading a file cannot clear a provider backoff")
        self.assertIn("rate limited", result["message"])

    def test_client_state_never_outranks_a_reading_we_took_ourselves(self):
        self.rollout(age=600)
        with patch("collector.main.fetch", return_value=self.data):
            ours = self.refresh(self.group, None, self.now - 60, interval=120)
        with patch("collector.main.fetch", return_value=self.data) as fetch:
            result = self.refresh(self.group, ours, self.now, interval=120)
        fetch.assert_not_called()
        self.assertEqual(result["windows"][0]["used"], 37, "our own newer reading stands")

    def test_a_session_tree_without_date_directories_is_still_read(self):
        """Only the newest day directories are opened; a flat tree has none to pick."""
        flat = self.home / ".codex/sessions"
        flat.mkdir(parents=True)
        stamp = datetime.fromtimestamp(self.now - 60, timezone.utc).isoformat().replace("+00:00", "Z")
        path = flat / "rollout-flat.jsonl"
        path.write_text(json.dumps({"timestamp": stamp, "type": "event_msg", "payload": {
            "type": "token_count", "rate_limits": self.LIMITS}}) + "\n")
        os.utime(path, (self.now - 60, self.now - 60))
        reading = local.read("codex", ["Codex"], self.home, self.now)
        self.assertEqual(reading["data"]["windows"][0]["used"], 41.0)

    def test_only_the_newest_day_directories_are_opened(self):
        """The bound is on directories, so a year of sessions costs what a week does."""
        self.rollout(age=60)
        for day in ("2026/09/07", "2024/01/01"):
            older = self.home / ".codex/sessions" / day
            older.mkdir(parents=True)
            path = older / "rollout-older.jsonl"
            path.write_text("{}\n")
            os.utime(path, (self.now - 60, self.now - 60))
        opened = {path.parent.name for path in local._rollouts(self.home, self.now)}
        self.assertEqual(opened, {"08", "07"}, "a third day back is never even listed")
        self.assertEqual(local.MAX_DAYS, 2)

    def test_an_explicit_refresh_still_asks_the_provider(self):
        """A button that only ever re-reads a file is a button that does nothing."""
        self.rollout(age=30)
        with patch("collector.main.fetch", return_value=self.data) as fetch:
            polled = self.refresh(self.group, self.established(), self.now)
            fetch.assert_not_called()
            result = self.refresh(self.group, polled, self.now + 6, force=True)
        fetch.assert_called_once()
        self.assertEqual(result["windows"][0]["used"], 37)
        self.assertEqual(result["origin"], "")

    def test_a_failed_refresh_leaves_a_current_client_reading_alone(self):
        """The check failed, not the column: there is nothing here to warn about."""
        self.rollout(age=30)
        with patch("collector.main.fetch", side_effect=UsageError(
                "Provider rate limited this check.", retry_after=3600, rate_limited=True)):
            result = self.refresh(self.group, self.established(), self.now, force=True)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["message"], "")
        self.assertEqual(result["windows"][0]["used"], 41.0)
        self.assertEqual(public(result)["retryAt"], self.now + 3600, "the backoff is still recorded")

    def test_client_state_too_old_is_not_presented_as_usage(self):
        """Held to the same day-old limit as our own cache; a stale percentage is a wrong one."""
        self.rollout(age=90000)
        with patch("collector.main.fetch", side_effect=UsageError("Rate limited", rate_limited=True)):
            result = self.refresh(self.group, None, self.now)
        self.assertEqual(result["windows"], [])
        self.assertEqual(result["origin"], "")

    def test_the_publishing_limit_holds_whatever_the_reader_hands_over(self):
        """Pinned here too, so the rule does not rest on the file scan's own cutoff."""
        ancient = {"data": {"windows": [{"id": "primary", "label": "5-hour window", "used": 4,
                                         "duration": 18000, "resetAt": 1900000000}], "plan": "pro"},
                   "fetchedAt": self.now - 86401, "origin": "Codex"}
        with patch("collector.main.local.read", return_value=ancient), \
             patch("collector.main.fetch", side_effect=UsageError("Rate limited", rate_limited=True)):
            result = self.refresh(self.group, None, self.now)
        self.assertEqual(result["windows"], [])
        self.assertEqual(result["origin"], "")

    def test_a_client_clock_ahead_cannot_make_a_reading_permanently_fresh(self):
        self.rollout(age=-4000)
        with patch("collector.main.fetch", return_value=self.data):
            result = self.refresh(self.group, None, self.now, interval=120)
        self.assertLessEqual(result["updatedAt"], self.now, "a reading is never dated in the future")

    def test_an_account_not_yet_seen_is_confirmed_against_the_provider_first(self):
        """A client's files name no account, so one reading has to establish whose it is."""
        self.rollout(age=30)
        with patch("collector.main.fetch", return_value=self.data) as fetch:
            result = self.refresh(self.group, None, self.now)
        fetch.assert_called_once()
        self.assertEqual(result["origin"], "")
        with patch("collector.main.fetch", return_value=self.data) as fetch:
            self.refresh(self.group, result, self.now + 1)
        fetch.assert_not_called()

    def test_a_client_rotating_its_own_token_is_not_an_account_change(self):
        """Clients rotate tokens on their own schedule; it changes no account at all."""
        self.rollout(age=60)
        rotated = [{**self.group[0], "secret": "the-same-account-refreshed"}]
        with patch("collector.main.fetch", return_value=self.data) as fetch:
            result = self.refresh(rotated, self.established(), self.now)
        fetch.assert_not_called()
        self.assertEqual(result["origin"], "Codex", "a refreshed token must not disable local reading")
        self.assertEqual(result["windows"][0]["used"], 41.0)

    def test_offline_mode_still_reads_what_the_clients_already_hold(self):
        """No network call was ever needed for this, so --offline is not a reason to skip it."""
        self.rollout(age=45)
        with patch("collector.main.fetch", side_effect=AssertionError("offline must not call out")):
            result = self.refresh(self.group, None, self.now, offline=True)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["windows"][0]["used"], 41.0)

    def test_unusable_client_state_falls_back_to_the_provider(self):
        for rows in ([], [{"type": "event_msg", "payload": {"type": "token_count"}}],
                     [{"type": "event_msg", "payload": {"type": "token_count", "rate_limits": {}}}]):
            path = self.home / ".codex/sessions/2026/09/08/rollout-test.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("".join(json.dumps(row) + "\n" for row in rows) + "not json at all\n")
            os.utime(path, (self.now - 60, self.now - 60))
            with patch("collector.main.fetch", return_value=self.data) as fetch:
                result = self.refresh(self.group, None, self.now)
            fetch.assert_called_once()
            self.assertEqual(result["windows"][0]["used"], 37)

    def test_a_partly_written_record_does_not_lose_the_one_before_it(self):
        self.rollout(age=60)
        path = self.home / ".codex/sessions/2026/09/08/rollout-test.jsonl"
        with path.open("a") as stream:
            stream.write('{"timestamp": "2026-09-08T00:00:00Z", "payload": {"type": "token_')
        os.utime(path, (self.now - 60, self.now - 60))
        reading = local.read("codex", ["Codex"], self.home, self.now)
        self.assertEqual(reading["data"]["windows"][0]["used"], 41.0)

    def test_codex_reads_the_same_numbers_from_its_log_as_from_its_api(self):
        """One normalizer for both, so the two paths cannot drift into different answers."""
        from_log = local.read("codex", ["Codex"], self.home, self.now) if self.rollout() else None
        from_api = parse_codex({"plan_type": "pro", "rate_limit": {"primary_window": {
            "used_percent": 41.0, "limit_window_seconds": 604800, "reset_at": 1789374681}}})
        self.assertEqual(from_log["data"]["windows"], from_api["windows"])
        self.assertEqual(from_log["data"]["plan"], from_api["plan"])

    def test_claude_reads_the_usage_body_its_client_already_fetched(self):
        path = self.claude_state(age=90)
        group = [{**self.claude_group[0], "account": "account-uuid:", "configFile": str(path)}]
        with patch("collector.main.claude.fetch") as fetch:
            result = self.refresh(group, None, self.now)
        fetch.assert_not_called()
        self.assertEqual(result["origin"], "Claude Code")
        self.assertEqual([w["label"] for w in result["windows"]], ["5-hour window", "7-day window"])
        self.assertEqual(result["windows"][0]["used"], 12.0)

    def test_claude_falls_back_to_the_cache_file_older_installs_wrote(self):
        legacy = self.home / ".claude/usage-cache.json"
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text(json.dumps({"cached_at": self.now - 100, "identity": "irrelevant",
                                      "data": {"five_hour": {"utilization": 9.0, "resets_at": "2026-09-08T13:10:00Z"}}}))
        reading = local.read("claude", ["Claude Code"], self.home, self.now)
        self.assertEqual(reading["data"]["windows"][0]["used"], 9.0)
        self.assertEqual(reading["origin"], "Claude Code")

    def test_the_current_config_copy_is_preferred_over_the_older_file(self):
        self.claude_state(age=30)
        legacy = self.home / ".claude/usage-cache.json"
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text(json.dumps({"cached_at": self.now - 40, "data": {"five_hour": {"utilization": 99.0}}}))
        reading = local.read("claude", ["Claude Code"], self.home, self.now)
        self.assertEqual(reading["data"]["windows"][0]["used"], 12.0)

    def test_one_providers_state_never_answers_for_the_other(self):
        self.rollout(age=30)
        self.claude_state(age=30)
        self.assertIsNone(local.read("claude", ["Codex"], self.home, self.now))
        self.assertIsNone(local.read("codex", ["Claude Code"], self.home, self.now))

    def test_a_poll_on_unchanged_client_state_leaves_the_cache_alone(self):
        """Every thirty seconds forever, so an unchanged reading must not touch the disk."""
        self.rollout(age=60)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cache.json"
            with patch("collector.main.discover", return_value={"codex-test": self.group}), \
                 patch("collector.main.fetch", return_value=self.data):
                collect({}, path, home=self.home)
                written = path.read_bytes()
                with patch("collector.main.atomic_json") as write:
                    collect({}, path, home=self.home)
                    write.assert_not_called()
            self.assertEqual(path.read_bytes(), written)

    def test_a_relocated_client_directory_is_still_read(self):
        """CLAUDE_CONFIG_DIR moves the config file itself; CODEX_HOME moves a directory."""
        moved = self.home / "elsewhere"
        (moved / "sessions/2026/09/08").mkdir(parents=True)
        (moved / ".claude.json").write_text(json.dumps({"cachedUsageUtilization": {
            "fetchedAtMs": (self.now - 60) * 1000, "utilization": {"five_hour": {"utilization": 22.0}}}}))
        stamp = datetime.fromtimestamp(self.now - 60, timezone.utc).isoformat().replace("+00:00", "Z")
        rollout = moved / "sessions/2026/09/08/rollout-moved.jsonl"
        rollout.write_text(json.dumps({"timestamp": stamp, "type": "event_msg", "payload": {
            "type": "token_count", "rate_limits": self.LIMITS}}) + "\n")
        os.utime(rollout, (self.now - 60, self.now - 60))
        with patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(moved), "CODEX_HOME": str(moved)}):
            claude = local.read("claude", ["Claude Code"], self.home, self.now)
            codex = local.read("codex", ["Codex"], self.home, self.now)
        self.assertEqual(claude["data"]["windows"][0]["used"], 22.0)
        self.assertEqual(codex["data"]["windows"][0]["used"], 41.0)

    def test_a_local_reading_never_leaks_scheduling_state_to_the_widget(self):
        self.rollout(age=60)
        with patch("collector.main.fetch", return_value=self.data):
            published = json.dumps(public(self.refresh(self.group, None, self.now)))
        for field in ("credentialFingerprint", "lastAttempt", "nextAttempt", "retryNotBefore"):
            self.assertNotIn(field, published)
        self.assertIn("Codex", published, "the panel still has to be able to say where it came from")


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


class ActivityTests(unittest.TestCase):
    def setUp(self):
        self.now = time.time()
        self.today = str(datetime.fromtimestamp(self.now).date())
        self.yesterday = str(datetime.fromtimestamp(self.now).date() - timedelta(days=1))

    def write(self, home, path, rows, age=0):
        target = home / path
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a") as stream:
            for row in rows:
                stream.write(json.dumps(row) + "\n")
        os.utime(target, (self.now - age, self.now - age))
        return target

    def claude_turn(self, model, stamp, tokens):
        """Split `tokens` across the four fields Anthropic reports, summing to exactly `tokens`."""
        parts = {"input_tokens": tokens // 4, "cache_read_input_tokens": tokens // 2,
                 "cache_creation_input_tokens": tokens // 8}
        parts["output_tokens"] = tokens - sum(parts.values())
        return {"timestamp": stamp, "message": {"model": model, "usage": parts}}

    def test_weekly_tokens_are_totalled_per_model_and_provider(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True):
            home = Path(folder)
            iso = datetime.fromtimestamp(self.now).astimezone().isoformat()
            self.write(home, ".claude/projects/a.jsonl", [
                self.claude_turn("claude-opus-5", iso, 1000),
                self.claude_turn("claude-opus-5", iso, 2000),
                self.claude_turn("claude-fable-5", iso, 400),
                self.claude_turn("<synthetic>", iso, 9999),
            ])
            self.write(home, ".codex/sessions/s.jsonl", [
                {"type": "turn_context", "payload": {"model": "gpt-5.6-sol"}},
                {"timestamp": iso, "payload": {"type": "token_count", "info": {
                    "total_token_usage": {"total_tokens": 500}}}},
                {"timestamp": iso, "payload": {"type": "token_count", "info": {
                    "total_token_usage": {"total_tokens": 5000}}}},
            ])
            self.write(home, ".omp/agent/sessions/s.jsonl", [
                {"timestamp": iso, "message": {"model": "openai-codex/gpt-6-astra",
                                               "usage": {"totalTokens": 750}}},
                {"timestamp": iso, "message": {"model": "claude-opus-5", "usage": {"totalTokens": 99999}}},
            ])
            result = activity.scan(home / "cache/activity.json", home, self.now)
        self.assertEqual(result["claude"], [{"name": "Claude Opus 5", "tokens": 3000},
                                            {"name": "Claude Fable 5", "tokens": 400}])
        self.assertEqual(result["codex"], [{"name": "GPT-5.6 Sol", "tokens": 5000},
                                           {"name": "GPT-6 Astra", "tokens": 750}],
                         "Codex reports a running session total, and OMP hosts other providers too")

    def test_appended_turns_are_read_without_recounting_the_file(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True):
            home = Path(folder)
            cache = home / "cache/activity.json"
            iso = datetime.fromtimestamp(self.now).astimezone().isoformat()
            path = self.write(home, ".claude/projects/a.jsonl", [self.claude_turn("claude-opus-5", iso, 1000)])
            self.assertEqual(activity.scan(cache, home, self.now)["claude"][0]["tokens"], 1000)
            with patch("collector.activity.scan_turns", side_effect=AssertionError("unchanged file rescanned")):
                self.assertEqual(activity.scan(cache, home, self.now)["claude"][0]["tokens"], 1000)
            self.write(home, ".claude/projects/a.jsonl", [self.claude_turn("claude-opus-5", iso, 500)])
            os.utime(path, (self.now + 1, self.now + 1))
            self.assertEqual(activity.scan(cache, home, self.now)["claude"][0]["tokens"], 1500)

    def test_partial_trailing_record_is_reread_when_complete(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True):
            home = Path(folder)
            cache = home / "cache/activity.json"
            iso = datetime.fromtimestamp(self.now).astimezone().isoformat()
            path = self.write(home, ".claude/projects/a.jsonl", [self.claude_turn("claude-opus-5", iso, 1000)])
            partial = json.dumps(self.claude_turn("claude-opus-5", iso, 800))
            with path.open("a") as stream:
                stream.write(partial[:40])
            os.utime(path, (self.now + 1, self.now + 1))
            self.assertEqual(activity.scan(cache, home, self.now)["claude"][0]["tokens"], 1000)
            with path.open("a") as stream:
                stream.write(partial[40:] + "\n")
            os.utime(path, (self.now + 2, self.now + 2))
            self.assertEqual(activity.scan(cache, home, self.now)["claude"][0]["tokens"], 1800,
                             "a record still being written must be counted once, after it is complete")

    def test_only_the_last_seven_days_count(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True):
            home = Path(folder)
            recent = datetime.fromtimestamp(self.now).astimezone().isoformat()
            old = datetime.fromtimestamp(self.now - 30 * 86400).astimezone().isoformat()
            self.write(home, ".claude/projects/a.jsonl", [self.claude_turn("claude-opus-5", recent, 1000),
                                                          self.claude_turn("claude-opus-5", old, 5000)])
            self.write(home, ".claude/projects/stale.jsonl", [self.claude_turn("claude-opus-5", recent, 7000)],
                       age=30 * 86400)
            result = activity.scan(home / "cache/activity.json", home, self.now)
        self.assertEqual(result["claude"], [{"name": "Claude Opus 5", "tokens": 1000}])

    def test_a_zero_budget_reports_without_touching_any_log(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True):
            home = Path(folder)
            cache = home / "cache/activity.json"
            iso = datetime.fromtimestamp(self.now).astimezone().isoformat()
            self.write(home, ".claude/projects/a.jsonl", [self.claude_turn("claude-opus-5", iso, 1000)])
            activity.scan(cache, home, self.now)
            with patch("collector.activity.scan_turns", side_effect=AssertionError("log opened")):
                result = activity.scan(cache, home, self.now, budget=0)
        self.assertEqual(result["claude"], [{"name": "Claude Opus 5", "tokens": 1000}])

    def test_scan_state_is_private(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True):
            home = Path(folder)
            cache = home / "cache/activity.json"
            activity.scan(cache, home, self.now)
            self.assertEqual(cache.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
