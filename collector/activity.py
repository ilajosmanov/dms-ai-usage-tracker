"""Local session activity: which models ran this week, and how many tokens they moved.

Read-only and incremental. Session logs are append-only, so a file already scanned is
re-read only from the byte where the previous scan stopped; Codex keeps a running
session total, so only its head and tail are ever needed. Message content is never read.
"""

import json
import os
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timedelta

from .jsonfile import atomic_json, read_json
from .providers import hidden
from .stores import roots

WINDOW_DAYS = 7
MAX_HEAD_BYTES = 64 * 1024
MAX_TAIL_BYTES = 256 * 1024
# Per store, per run, newest file first: one busy client cannot starve the others, and a
# first scan of a long history finishes over the next few polls rather than blocking one.
MAX_SCAN_BYTES = 96 * 1024 * 1024
MAX_MODELS = 8


def display_name(model):
    model = str(model or "").strip()
    if not model or model == "<synthetic>" or hidden("codex", model):
        return ""
    if "/" in model:
        model = model.rsplit("/", 1)[-1]
    parts = model.split("-")
    if parts[0].casefold() == "gpt":
        return "GPT-" + parts[1] + (" " + " ".join(word.title() for word in parts[2:]) if len(parts) > 2 else "")
    if parts[0].casefold() == "claude":
        return "Claude " + " ".join(word.title() for word in parts[1:])
    return model


def day_of(value, fallback):
    """Convert client timestamps to the same local YYYY-MM-DD keys as usage history."""
    try:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            seconds = value / 1000 if value > 10_000_000_000 else value
            return str(datetime.fromtimestamp(seconds).date())
        if isinstance(value, str) and value.strip():
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone()
            return str(parsed.date())
    except (OverflowError, OSError, ValueError):
        pass
    return str(datetime.fromtimestamp(fallback).date())


def _count(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0 else 0


def _add(days, day, name, tokens):
    bucket = days.setdefault(day, {})
    bucket[name] = bucket.get(name, 0) + tokens


def _claude_turn(record):
    """Anthropic reports each turn on its own; a cache read is still a token read."""
    message = record.get("message") if isinstance(record.get("message"), dict) else {}
    usage = message.get("usage") if isinstance(message.get("usage"), dict) else {}
    tokens = sum(_count(usage.get(field)) for field in
                 ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens"))
    return message.get("model"), tokens, record.get("timestamp")


def _codex_client_turn(record):
    """pi and OMP share one per-message shape."""
    message = record.get("message") if isinstance(record.get("message"), dict) else {}
    usage = message.get("usage") if isinstance(message.get("usage"), dict) else {}
    tokens = _count(usage.get("totalTokens")) or sum(
        _count(usage.get(field)) for field in ("input", "output", "cacheRead", "cacheWrite"))
    return message.get("model"), tokens, record.get("timestamp") or message.get("timestamp")


READERS = {"claude": _claude_turn, "turns": _codex_client_turn}


def _records(stream, start):
    """Yield each complete record and the offset just past it."""
    stream.seek(start)
    offset = start
    for raw in stream:
        if not raw.endswith(b"\n"):
            break  # a record still being written; resume before it on the next scan
        offset += len(raw)
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeError):
            continue
        if isinstance(value, dict):
            yield value, offset


def scan_turns(path, kind, start, days):
    """Fold every turn after `start` into `days`; return the new offset and bytes read."""
    read = READERS[kind]
    offset = start
    try:
        fallback = path.stat().st_mtime
        with path.open("rb") as stream:
            for record, offset in _records(stream, start):
                model, tokens, stamp = read(record)
                name = display_name(model)
                if not name or not tokens:
                    continue
                # OMP and pi also host non-Codex providers; keep only the Codex family.
                if kind == "turns" and not (name.startswith("GPT-") or name.startswith("o")):
                    continue
                _add(days, day_of(stamp, fallback), name, tokens)
    except OSError:
        return start, 0
    return offset, offset - start


def scan_codex(path, days):
    """Codex logs a running session total, so its head and tail are the whole story."""
    try:
        fallback = path.stat().st_mtime
        with path.open("rb") as stream:
            size = stream.seek(0, os.SEEK_END)
            model, stamp, total = "", None, 0
            for record, offset in _records(stream, 0):
                payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
                if record.get("type") == "turn_context":
                    model = payload.get("model") or model
                if offset > MAX_HEAD_BYTES and model:
                    break
            start = max(0, size - MAX_TAIL_BYTES)
            if start:
                stream.seek(start)
                stream.readline()  # discard a partial record
                start = stream.tell()
            for record, _ in _records(stream, start):
                payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
                if record.get("type") == "turn_context":
                    model = payload.get("model") or model
                if payload.get("type") != "token_count":
                    continue
                info = payload.get("info") if isinstance(payload.get("info"), dict) else {}
                running = info.get("total_token_usage") if isinstance(info.get("total_token_usage"), dict) else {}
                if _count(running.get("total_tokens")):
                    total, stamp = _count(running.get("total_tokens")), record.get("timestamp")
    except OSError:
        return 0
    name = display_name(model)
    if name and total:
        _add(days, day_of(stamp, fallback), name, total)
    return min(size, MAX_HEAD_BYTES) + min(size, MAX_TAIL_BYTES)


def scan_opencode(path, days, cutoff, now):
    """opencode keeps per-session totals in SQLite; no log walking needed."""
    if not path.is_file():
        return
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)) as connection:
            rows = connection.execute(
                "SELECT model, tokens_input, tokens_output, tokens_reasoning, tokens_cache_read, "
                "tokens_cache_write, time_updated FROM session WHERE model IS NOT NULL AND time_updated >= ?",
                (int(cutoff * 1000),))
            for raw, *counts in rows:
                updated = counts.pop()
                try:
                    model = json.loads(raw) if isinstance(raw, str) else raw
                except ValueError:
                    model = raw
                if isinstance(model, dict):
                    if model.get("providerID") not in ("openai", "openai-codex"):
                        continue
                    model = model.get("id", "")
                name, tokens = display_name(model), sum(_count(value) for value in counts)
                if name and tokens:
                    _add(days, day_of(updated, now), name, tokens)
    except (OSError, sqlite3.Error):
        return


def sources(home=None):
    base = roots(home)
    return [("claude", "claude", base["claude"] / "projects"),
            ("codex", "codex", base["codex"] / "sessions"),
            ("codex", "turns", base["pi"] / "sessions"),
            ("codex", "turns", base["omp"] / "sessions")]


def _in_window(root, cutoff):
    try:
        found = [(path.stat().st_mtime, path) for path in root.rglob("*.jsonl")
                 if path.is_file() and path.stat().st_mtime >= cutoff]
    except OSError:
        return []
    found.sort(key=lambda item: item[0], reverse=True)
    return [path for _, path in found]


def scan(cache_path, home=None, now=None, budget=MAX_SCAN_BYTES):
    """Weekly token totals per model and provider, reusing everything already scanned.

    The budget is per store; a zero budget aggregates the stored scan without opening
    a single log.
    """
    now = time.time() if now is None else now
    cutoff = now - WINDOW_DAYS * 86400
    today = datetime.fromtimestamp(now).date()
    window = {str(today - timedelta(days=offset)) for offset in range(WINDOW_DAYS)}
    earliest = min(window)
    stored = read_json(cache_path).get("files", {})
    stored = stored if isinstance(stored, dict) else {}
    files = {}

    for provider, kind, root in sources(home):
        spent = 0
        for path in _in_window(root, cutoff):
            key = str(path)
            entry = stored.get(key) if isinstance(stored.get(key), dict) else None
            try:
                status = path.stat()
            except OSError:
                continue
            unchanged = entry and entry.get("size") == status.st_size and entry.get("mtime") == status.st_mtime
            if unchanged or spent >= budget:
                if entry:
                    files[key] = entry  # keep what is known; anything new lands on a later poll
                continue
            if kind == "codex":
                days, offset = {}, status.st_size
                spent += scan_codex(path, days)
            else:
                resume, days = 0, {}
                if entry and entry.get("offset") and status.st_size > entry.get("size", 0):
                    # Append-only: keep the earlier tally and read only what was added.
                    resume = entry["offset"]
                    days = {day: dict(models) for day, models in (entry.get("days") or {}).items()
                            if isinstance(models, dict)}
                offset, read = scan_turns(path, kind, resume, days)
                spent += read
            files[key] = {"provider": provider, "mtime": status.st_mtime, "size": status.st_size,
                          "offset": offset, "days": {d: v for d, v in days.items() if d >= earliest}}

    totals = {"codex": {}, "claude": {}}

    def fold(provider, days):
        for day, models in (days or {}).items():
            if day not in window or not isinstance(models, dict):
                continue
            for name, tokens in models.items():
                totals[provider][name] = totals[provider].get(name, 0) + _count(tokens)

    for entry in files.values():
        if entry.get("provider") in totals:
            fold(entry["provider"], entry.get("days"))
    opencode = {}
    scan_opencode(roots(home)["opencode"] / "opencode.db", opencode, cutoff, now)
    fold("codex", opencode)

    if budget:
        atomic_json(cache_path, {"version": 1, "files": files})
    return {provider: [{"name": name, "tokens": tokens}
                       for name, tokens in sorted(models.items(), key=lambda item: -item[1])[:MAX_MODELS]]
            for provider, models in totals.items()}
