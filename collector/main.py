"""Bounded concurrent refresh, private atomic cache, and honest stale fallback."""

import argparse
import concurrent.futures
import fcntl
import hmac
import json
import hashlib
import os
import secrets
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

from .credentials import discover, read_json
from .models import recent_models_by_day
from .providers import UsageError, fetch, hidden, number

PROVIDERS = {"codex": "Codex", "claude": "Claude"}
# Scheduling state the widget never reads; kept in the private cache, not published.
INTERNAL = ("credentialFingerprint", "lastAttempt", "nextAttempt", "retryNotBefore")


def atomic_json(path, value, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".usage-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, allow_nan=False)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def private_dir(path):
    """Create, and keep, a directory only this user can read."""
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.stat().st_mode & 0o077:
        path.chmod(0o700)
    return path


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
    """The widget only ever sees usage metadata; refresh bookkeeping stays on disk."""
    return {k: v for k, v in account.items() if k not in INTERNAL}


def refresh_group(group, cached, now, offline=False, force=False, interval=120, key=b""):
    first = group[0]
    # Keyed, so a value written to disk cannot be checked against a guessed token.
    fingerprint = hmac.new(key, json.dumps(sorted(c["secret"] for c in group)).encode(), hashlib.sha256).hexdigest()
    base = {"id": first["id"], "provider": first["provider"], "name": PROVIDERS[first["provider"]],
            "sources": list(dict.fromkeys(c["source"] for c in group)), "windows": [], "history": [],
            "plan": "", "updatedAt": None, "message": "", "note": "",
            "credentialFingerprint": fingerprint, "lastAttempt": now}
    changed = cached and cached.get("credentialFingerprint") != fingerprint
    if cached and not offline:
        hard_backoff = now < cached.get("retryNotBefore", 0)
        cached_result = not changed and now < cached.get("nextAttempt", 0)
        manual_cooldown = now - cached.get("lastAttempt", 0) < 5
        if hard_backoff or (cached_result and (not force or manual_cooldown)):
            return {**cached, "sources": base["sources"]}
    error = UsageError("Offline mode. Showing the last successful check.")
    if not offline:
        # Try freshest tokens first. Client-owned refresh tokens are never consumed.
        for credential in sorted(group, key=lambda c: c.get("expires") or 0, reverse=True):
            try:
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
    retry = {"lastAttempt": now, "credentialFingerprint": fingerprint,
             "retryNotBefore": now + error.retry_after if error.rate_limited else 0}
    if cached and cached.get("updatedAt") and now - cached["updatedAt"] < 86400:
        return {**cached, **retry, "status": "stale", "message": str(error), "nextAttempt": now + error.retry_after,
                "sources": base["sources"]}
    return {**base, **retry, "status": error.status, "message": str(error), "nextAttempt": now + error.retry_after}


def record_history(result, now):
    """Daily peak of the primary window; never imply token counts or spend."""
    today = datetime.fromtimestamp(now).date()
    cutoff = str(today - timedelta(days=6))
    primary = result["windows"][0] if result["windows"] else {}
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
                             "sources": [], "updatedAt": None, "plan": "", "note": ""})
    order = list(PROVIDERS)
    accounts.sort(key=lambda a: order.index(a["provider"]))
    return accounts


def cached_snapshot(cache_path, now):
    """Another collector holds the refresh lock; report its last result instead of queueing."""
    stored = read_json(cache_path).get("accounts", {})
    return {"version": 1, "checkedAt": now, "accounts": finalize(
        [public(a) for a in stored.values() if isinstance(a, dict) and a.get("provider") in PROVIDERS])}


def collect(config, cache_path, offline=False, force=False):
    now = time.time()
    groups = discover(config)
    cache = read_json(cache_path).get("accounts", {})
    accounts = []
    key = fingerprint_key(cache_path.parent)
    interval = max(120, min(900, (number(config.get("refreshInterval")) or 2) * 60))
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(refresh_group, group, cache.get(uid), now, offline, force, interval, key) for uid, group in groups.items()]
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
            result = cached_snapshot(cache_dir / "usage.json", time.time())
        else:
            result = collect(config, cache_dir / "usage.json", args.offline, args.force)
    models = recent_models_by_day()
    for account in result["accounts"]:
        account["modelsByDay"] = models.get(account["provider"], {})
    print(json.dumps(result, allow_nan=False))


if __name__ == "__main__":
    main()
