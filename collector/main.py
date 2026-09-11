"""Bounded concurrent refresh, private atomic cache, and honest stale fallback."""

import argparse
import concurrent.futures
import fcntl
import hmac
import json
import hashlib
import os
import secrets
import time
from datetime import datetime, timedelta
from pathlib import Path

from . import activity, local, claude
from .credentials import discover
from .jsonfile import atomic_json, private_dir, read_json
from .providers import UsageError, fetch, hidden, number

PROVIDERS = {"codex": "Codex", "claude": "Claude"}
# Scheduling state the widget never reads; kept in the private cache, not published.
INTERNAL = ("credentialFingerprint", "lastAttempt", "nextAttempt", "retryNotBefore")
# Past this, a reading is history rather than usage, whoever took it. A day-old
# percentage against a five-hour window is not a smaller truth, it is a wrong one.
MAX_AGE = 86400


def fingerprint_key(directory):
    """A per-install random key, so the stored fingerprint is not a bare hash of a live token."""
    path = directory / "fingerprint.key"
    try:
        key = path.read_bytes()
        if len(key) == 32:
            return key
    except OSError:
        pass
    key = secrets.token_bytes(32)
    try:
        private_dir(directory)
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "wb") as stream:
            stream.write(key)
    except OSError:
        pass
    return key


def public(account):
    """The widget only ever sees usage metadata; refresh bookkeeping stays on disk.

    A cache written by an earlier version is missing whatever has been added since,
    so every path that serves one fills the gaps from `base` before publishing.

    The one exception is a provider backoff. It is the only wait a manual refresh
    cannot shorten, so the panel is given the moment it lifts — otherwise every
    click looks like a broken button. Published from `retryNotBefore` rather than
    stored twice, so it is right for caches written before it existed.
    """
    return {**{k: v for k, v in account.items() if k not in INTERNAL},
            "retryAt": account.get("retryNotBefore") or 0}


def taken_at(account):
    """When a reading was taken, as a number even when it was never taken at all."""
    return (account or {}).get("updatedAt") or 0


def refresh_group(group, cached, now, offline=False, force=False, interval=120, key=b"", home=None):
    first = group[0]
    native = first["provider"] == "claude"
    if native:
        interval = max(claude.MIN_INTERVAL, interval)
        if cached and (not first.get("account") or now - taken_at(cached) >= MAX_AGE):
            cached = {**cached, "windows": [], "history": [], "updatedAt": None,
                      "status": "error", "message": "No recent verified Claude usage is available."}
        elif cached and cached.get("status") == "ok" and now - taken_at(cached) >= interval:
            cached = {**cached, "status": "stale", "message": "Claude's last reading is no longer current."}
    # Keyed, so a value written to disk cannot be checked against a guessed token.
    fingerprint = hmac.new(key, json.dumps(sorted(c["secret"] for c in group)).encode(), hashlib.sha256).hexdigest()
    base = {"id": first["id"], "provider": first["provider"], "name": PROVIDERS[first["provider"]],
            "sources": list(dict.fromkeys(c["source"] for c in group)), "windows": [], "history": [],
            "plan": "", "updatedAt": None, "message": "", "note": "", "origin": "",
            "credentialFingerprint": fingerprint, "lastAttempt": now}
    changed = cached and cached.get("credentialFingerprint") != fingerprint

    def adopt(reading, status="ok"):
        """Publish what the client fetched, dated when the client fetched it.

        Reading a file is not a check, so it neither advances the schedule's idea of
        the last attempt nor clears a provider backoff that is already running. The
        next check is due an interval after the *reading*, not after this poll: a
        reading that has not changed then produces a record that has not changed
        either, and the cache is left alone.
        """
        held = cached or {}
        return record_history({**base, **reading["data"], "status": status,
                               "origin": reading["origin"], "updatedAt": reading["fetchedAt"],
                               "lastAttempt": held.get("lastAttempt", 0),
                               "nextAttempt": reading["fetchedAt"] + interval,
                               "retryNotBefore": held.get("retryNotBefore", 0),
                               "message": held.get("message", "") if status != "ok" else "",
                               "history": held.get("history", [])}, now)

    reading = claude.read(first, now) if native else local.read(first["provider"], base["sources"], home, now)
    if reading and now - reading["fetchedAt"] >= MAX_AGE:
        reading = None  # history rather than usage, exactly like an expired cache
    current = bool(reading) and now - reading["fetchedAt"] < interval
    # Claude's reader verifies the capture's account identity itself. Codex's local
    # logs need a previous provider check to establish which account they belong to.
    # `changed` is deliberately not consulted here — it also fires when a client
    # rotates its own token, which happens routinely and changes no account at all.
    confirmed = native or taken_at(cached) > 0

    def newest(against):
        """Whichever reading is actually the most recent, ours or the client's."""
        if reading and reading["fetchedAt"] > taken_at(against):
            return adopt(reading, "ok" if current else "stale")
        return None

    # Reusing a current client reading avoids a duplicate provider request.
    # An explicit refresh still initiates collection.
    if current and confirmed and not force:
        reused = newest(cached)
        if reused:
            return reused
    if cached and not offline:
        hard_backoff = now < cached.get("retryNotBefore", 0)
        cached_result = not changed and now < cached.get("nextAttempt", 0)
        manual_cooldown = now - cached.get("lastAttempt", 0) < 5
        if hard_backoff or (cached_result and (not force or manual_cooldown)):
            # Waiting does not mean showing the older of two readings we already hold.
            return newest(cached) or {**base, **cached, "sources": base["sources"]}
    error = UsageError("Offline mode. Showing the last successful check.")
    if not offline:
        # Try freshest tokens first. Client-owned refresh tokens are never consumed.
        for credential in sorted(group, key=lambda c: c.get("expires") or 0, reverse=True):
            try:
                if native:
                    checked = claude.fetch(credential, interval)
                    result = adopt(checked)
                    # Claude may have renewed its credential while fetching. Notice
                    # that rotation now so the next local poll does not fetch again.
                    token = claude.current_token(first)
                    result["credentialFingerprint"] = hmac.new(key, json.dumps([token]).encode(), hashlib.sha256).hexdigest()
                    result.update(lastAttempt=now, nextAttempt=max(now + 5, checked["fetchedAt"] + interval), retryNotBefore=0)
                    return result
                data = fetch(credential)
                result = {**base, **data, "status": "ok", "updatedAt": now, "nextAttempt": now + interval,
                          "history": (cached or {}).get("history", [])}
                return record_history(result, now)
            except UsageError as exc:
                error = exc
                if exc.status != "auth":
                    break
            except (ValueError, TypeError, KeyError, AttributeError):
                error = UsageError("Provider response format changed. Check for a plugin update.")
                break
    # Only an HTTP provider can declare its own wait, and that one is honored
    # whole. Claude answers through a subprocess, so no failure of its own ever
    # carries a 429 or a Retry-After, and `nextAttempt` alone does not bound it:
    # manual refresh is allowed to skip that, which spends a real service request
    # every five seconds for as long as the button is pressed. So a failed native
    # check earns a hold of the collector's own floor -- long enough to stop a
    # hammer, short enough that a refresh still helps someone who just fixed the
    # cause, and published as `retryAt`, so the panel says why it is waiting
    # rather than leaving a button that looks broken.
    #
    # An `auth` failure is never held. The fix for one is a sign-in, and checking
    # that the sign-in worked is the first thing anyone does after it.
    held = (error.retry_after if error.rate_limited
            else min(error.retry_after, claude.MIN_INTERVAL)
            if native and error.status != "auth" else 0)
    schedule = {"lastAttempt": now, "credentialFingerprint": fingerprint,
                "nextAttempt": now + error.retry_after,
                "retryNotBefore": now + held if held else 0}
    if native:
        # Renewal can succeed while usage retrieval fails. Record the rotated token
        # even then, otherwise the next poll mistakes it for a new login and retries.
        schedule["credentialFingerprint"] = hmac.new(key, json.dumps([claude.current_token(first)]).encode(), hashlib.sha256).hexdigest()
        if not claude.account_matches(first):
            cached = None
        # A failed control response can still leave a newer account-bound capture.
        reading = claude.read(first, time.time())
        if reading and time.time() - reading["fetchedAt"] >= MAX_AGE:
            reading = None
        current = bool(reading) and time.time() - reading["fetchedAt"] < interval
    if current:
        # A current client reading is a good column. The check that just failed is
        # then only a scheduling fact, and not something to warn anyone about.
        return {**adopt(reading), **schedule}
    failed = {**schedule, "status": "stale", "message": str(error)}
    chosen = newest(cached)
    if chosen:
        return {**chosen, **failed}
    if taken_at(cached) and now - taken_at(cached) < MAX_AGE:
        return {**base, **cached, **failed, "sources": base["sources"]}
    return {**base, **failed, "status": error.status}


def tracked_window(windows):
    """History follows one window for its whole life, so it follows the shortest one.

    Deliberately not the headline window the panel shows. That one is whichever
    meter is fullest and is meant to move between polls; a sparkline that switched
    between a five-hour peak and a weekly one would be charting two different
    quantities, and `comparable` would discard the week's peaks every time it moved.
    """
    known = [w for w in windows if w.get("duration") is not None]
    if known:
        return min(known, key=lambda w: w["duration"])
    return windows[0] if windows else {}


def record_history(result, now):
    """Daily peak of the tracked window; never imply token counts or spend."""
    today = datetime.fromtimestamp(now).date()
    cutoff = str(today - timedelta(days=6))
    primary = tracked_window(result["windows"])
    key, span, value = primary.get("id", ""), primary.get("duration"), primary.get("used")
    if value is None:
        return result

    def comparable(entry):
        # Compare on the window's length rather than its id: an id can change with the
        # provider's response shape, but a 5-hour peak is only ever a 5-hour peak.
        if span is not None and entry.get("duration") is not None:
            return entry["duration"] == span
        return entry.get("window") == key

    history = [x for x in result.get("history", []) if isinstance(x, dict)
               and isinstance(x.get("value"), (int, float)) and str(x.get("date", "")) >= cutoff
               and comparable(x)]
    existing = next((x for x in history if x["date"] == str(today)), None)
    if existing:
        existing["value"] = max(value, existing["value"])
    else:
        history.append({"date": str(today), "value": value, "window": key, "duration": span})
    return {**result, "history": history}


def finalize(accounts):
    """Label every account, stand in for anything unconnected, and order by provider."""
    for account in accounts:
        provider = account.get("provider")
        account["windows"] = [window for window in account.get("windows", [])
                              if not hidden(provider, window.get("id", ""), window.get("label", ""))]
    for provider, name in PROVIDERS.items():
        matches = [a for a in accounts if a.get("provider") == provider]
        for i, account in enumerate(matches):
            account["label"] = " + ".join(account.get("sources") or []) + (f" · account {i + 1}" if len(matches) > 1 else "")
        if not matches:
            message = {
                "codex": "Sign in with ChatGPT in Codex, pi, OMP, or opencode.",
                "claude": "Sign in to Claude Code to connect your subscription."
            }[provider]
            accounts.append({"id": provider, "provider": provider, "name": name, "label": "Not connected",
                             "status": "missing", "message": message, "windows": [], "history": [],
                             "sources": [], "updatedAt": None, "plan": "", "note": "", "origin": "",
                             "retryAt": 0})
    order = list(PROVIDERS)
    accounts.sort(key=lambda a: order.index(a["provider"]))
    return accounts


def cached_snapshot(cache_path, now):
    """Another collector holds the refresh lock; report its last result instead of queueing."""
    stored = read_json(cache_path).get("accounts", {})
    return {"version": 1, "checkedAt": now, "accounts": finalize(
        [public(a) for a in stored.values() if isinstance(a, dict) and a.get("provider") in PROVIDERS])}


def collect(config, cache_path, offline=False, force=False, home=None):
    now = time.time()
    groups = discover(config, home)
    cache = read_json(cache_path).get("accounts", {})
    accounts = []
    key = fingerprint_key(cache_path.parent)
    interval = max(120, min(1800, (number(config.get("refreshInterval")) or 2) * 60))
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(refresh_group, group, cache.get(uid), now, offline, force, interval, key, home)
                   for uid, group in groups.items()]
        for future in futures:
            accounts.append(future.result())
    finalize(accounts)
    if not offline:
        stored = {"accounts": {a["id"]: a for a in accounts if a["status"] != "missing"}}
        # The widget poll is a credential check; only touch the disk on a real change.
        if stored != read_json(cache_path):
            atomic_json(cache_path, stored)
    return {"version": 1, "checkedAt": now, "accounts": [public(a) for a in accounts]}


def main():
    parser = argparse.ArgumentParser(description="Read subscription limits; emits sanitized JSON, never credentials.")
    parser.add_argument("--config", help="Optional JSON config, paths only; no raw secrets.")
    parser.add_argument("--force", action="store_true", help="Refresh now; respects a five-second cooldown and provider rate limits.")
    parser.add_argument("--offline", action="store_true", help="Read cached usage without network calls.")
    parser.add_argument("--demo", action="store_true", help="Emit clearly marked example data without reading credentials.")
    args = parser.parse_args()
    if args.demo:
        from .demo import snapshot
        print(json.dumps(snapshot()))
        return
    config = read_json(args.config) if args.config else read_json(Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "DankMaterialShell/plugin_settings.json").get("aiUsage", {})
    cache_dir = private_dir(Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "dms-ai-usage")
    with (cache_dir / "refresh.lock").open("a") as lock:
        os.chmod(cache_dir / "refresh.lock", 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            # Another collector owns the scan; read its findings instead of repeating them.
            result = cached_snapshot(cache_dir / "usage.json", time.time())
            models = activity.scan(cache_dir / "activity.json", budget=0)
        else:
            result = collect(config, cache_dir / "usage.json", args.offline, args.force)
            models = activity.scan(cache_dir / "activity.json")
    for account in result["accounts"]:
        account["models"] = models.get(account["provider"], [])
    print(json.dumps(result, allow_nan=False))


if __name__ == "__main__":
    main()
