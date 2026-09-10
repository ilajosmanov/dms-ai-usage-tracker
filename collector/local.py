"""Usage a client already fetched, read from that client's own on-disk state.

Reusing a client capture avoids a duplicate provider request. Native Claude
collection uses the stricter account-bound reader in `claude.py`; the legacy reader
here remains available for older local-state consumers.

Each reader returns the payload in that provider's own API shape and hands it to the
same `providers.parse_*`, so there is one normalizer rather than two that can drift.
A reading is dated when the *client* fetched it, never `now`: the widget must not
present someone else's reading as a check of its own.
"""

import json
import os
import time
from pathlib import Path

from .jsonfile import read_json
from .providers import UsageError, number, parse_claude, parse_codex, timestamp
from .stores import claude_config, roots

# The client that owns each provider's local state, named as `credentials.discover`
# labels it. A client's state describes the account *it* is signed into, so it may
# only ever answer for the group holding that client's own credential — otherwise a
# second account discovered through another client would inherit these numbers.
OWNERS = {"codex": "Codex", "claude": "Claude Code"}

# Codex records a fresh snapshot on every turn, so the newest one is always near the
# end of a rollout, and only the newest few rollouts can hold it.
MAX_TAIL_BYTES = 128 * 1024
MAX_ROLLOUTS = 4
# Enough day directories to cover the span above without listing the whole history.
MAX_DAYS = 2
# A day, matching the oldest reading the collector will publish from any source. This
# only has to avoid being the tighter of the two bounds; `main` decides what counts as
# fresh enough to show.
MAX_ROLLOUT_AGE = 86400


def _tail(path, limit=MAX_TAIL_BYTES):
    """Records from the last `limit` bytes of a JSONL file, partial lines dropped."""
    try:
        with path.open("rb") as stream:
            size = stream.seek(0, os.SEEK_END)
            if size > limit:
                stream.seek(size - limit)
                stream.readline()  # discard the record this offset landed inside
            else:
                stream.seek(0)
            found = []
            for raw in stream:
                try:
                    value = json.loads(raw)
                except (ValueError, UnicodeError):
                    continue
                if isinstance(value, dict):
                    found.append(value)
            return found
    except OSError:
        return []


def _rollouts(home, now):
    """Codex session logs, newest first, and only ones new enough to matter.

    Codex files rollouts under `sessions/YYYY/MM/DD`, and those names sort in the
    order they were written, so only the newest day directories are opened: a tree
    holding a year of sessions costs no more to read than one holding a week. A layout
    without those directories is walked whole, as it was before they existed.
    """
    root = roots(home)["codex"] / "sessions"
    try:
        days = sorted((day for day in root.glob("*/*/*") if day.is_dir()), reverse=True)
        found = [(path.stat().st_mtime, path) for place in (days[:MAX_DAYS] or [root])
                 for path in place.rglob("rollout-*.jsonl")
                 if path.is_file() and path.stat().st_mtime >= now - MAX_ROLLOUT_AGE]
    except OSError:
        return []
    found.sort(reverse=True)
    return [path for _, path in found[:MAX_ROLLOUTS]]


def _codex_window(item):
    """One window, in the shape the Codex API reports it."""
    if not isinstance(item, dict):
        return None
    minutes = number(item.get("window_minutes"))
    return {"used_percent": item.get("used_percent"),
            "limit_window_seconds": minutes * 60 if minutes else None,
            "reset_at": item.get("resets_at")}


def _codex(home, now):
    """Codex writes a `rate_limits` snapshot into each turn it logs.

    Newest wins across rollouts rather than newest file, because a session left open
    in another terminal can be touched after the one that actually ran a turn.
    """
    best = None
    for path in _rollouts(home, now):
        for record in _tail(path):
            payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
            limits = payload.get("rate_limits")
            fetched = timestamp(record.get("timestamp"))
            if payload.get("type") != "token_count" or not isinstance(limits, dict) or not fetched:
                continue
            if not best or fetched > best[0]:
                best = (fetched, limits)
    if not best:
        return None
    fetched, limits = best
    return fetched, {"plan_type": limits.get("plan_type"),
                     "rate_limit": {key: value for key, value in
                                    (("primary_window", _codex_window(limits.get("primary"))),
                                     ("secondary_window", _codex_window(limits.get("secondary"))))
                                    if value}}


def _claude(home, now):
    """Claude Code keeps the whole usage body it last fetched in its global config.

    It refreshes that copy at most every five minutes and reads it back as good for
    an hour, so this is the same reading Claude Code is showing itself. The older
    `usage-cache.json` is still read for installs that predate the move.
    """
    stored = read_json(claude_config(home)).get("cachedUsageUtilization")
    if isinstance(stored, dict) and isinstance(stored.get("utilization"), dict):
        fetched = number(stored.get("fetchedAtMs"))
        if fetched:
            return fetched / 1000, stored["utilization"]
    legacy = read_json(roots(home)["claude"] / "usage-cache.json")
    if isinstance(legacy.get("data"), dict) and number(legacy.get("cached_at")):
        return number(legacy["cached_at"]), legacy["data"]
    return None


READERS = {"codex": (_codex, parse_codex), "claude": (_claude, parse_claude)}


def read(provider, sources, home=None, now=None):
    """The owning client's own last reading, normalized, or None if there isn't one.

    Never raises and never touches the network: a client's state file is best-effort
    input, so anything unreadable or unrecognized simply means "no local reading" and
    leaves the caller to ask the provider itself.
    """
    now = time.time() if now is None else now
    if OWNERS.get(provider) not in (sources or []):
        return None
    reader, parse = READERS[provider]
    try:
        found = reader(Path(home) if home else None, now)
        if not found:
            return None
        fetched, payload = found
        # A client clock ahead of ours would otherwise date a reading in the future
        # and look permanently fresh.
        return {"data": parse(payload), "fetchedAt": min(fetched, now), "origin": OWNERS[provider]}
    except (UsageError, OSError, ValueError, TypeError, KeyError, AttributeError):
        return None
