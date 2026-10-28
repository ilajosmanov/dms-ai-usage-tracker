"""Local session activity: which models ran this week, and how many tokens they moved.

Read-only and incremental. Session logs are append-only, so a file already scanned is
re-read only from the byte where the previous scan stopped; Codex keeps a running
session total, so only its head and tail are needed. Message content is never stored.
"""

import json
import math
import os
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timedelta

from .jsonfile import atomic_json, read_json
from .providers import hidden
from .stores import roots

WINDOW_DAYS = 7
MAX_HEAD_BYTES = 2 * 1024 * 1024
MAX_TAIL_BYTES = 256 * 1024
MAX_RECORD_BYTES = 2 * 1024 * 1024
# Per store, per run, newest file first: one busy client cannot starve the others, and a
# first scan of a long history finishes over the next few polls rather than blocking one.
MAX_SCAN_BYTES = 96 * 1024 * 1024
MAX_MODELS = 8
CACHE_VERSION = 2


def display_name(model):
    model = str(model or "").strip()
    if not model or model == "<synthetic>" or hidden("codex", model):
        return ""
    if "/" in model:
        model = model.rsplit("/", 1)[-1]
    parts = model.split("-")
    if parts[0].casefold() == "gpt" and len(parts) > 1:
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
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return 0
    if isinstance(value, float) and not math.isfinite(value):
        return 0
    return value if value > 0 else 0


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


def _records(stream, start, limit=MAX_SCAN_BYTES):
    """Read bounded records; incomplete lines remain for the next scan."""
    stream.seek(start)
    end = start + limit
    while stream.tell() < end:
        raw = stream.readline(min(MAX_RECORD_BYTES + 1, end - stream.tell()))
        if not raw:
            break
        if not raw.endswith(b"\n"):
            # Discard oversized records in bounded chunks, without loading them whole.
            while len(raw) > MAX_RECORD_BYTES and stream.tell() < end:
                raw = stream.readline(min(MAX_RECORD_BYTES + 1, end - stream.tell()))
                if not raw or raw.endswith(b"\n"):
                    break
            if raw.endswith(b"\n"):
                yield None, stream.tell()
                continue
            break
        if len(raw) > MAX_RECORD_BYTES:
            yield None, stream.tell()
            continue
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeError):
            value = None
        yield value if isinstance(value, dict) else None, stream.tell()


def scan_turns(path, kind, start, days, budget=MAX_SCAN_BYTES):
    """Fold every turn after `start` into `days`; return the new offset and bytes read."""
    read = READERS[kind]
    offset = start
    consumed = 0
    try:
        fallback = path.stat().st_mtime
        with path.open("rb") as stream:
            for record, offset in _records(stream, start, budget):
                if record is None:
                    continue
                model, tokens, stamp = read(record)
                name = display_name(model)
                if not name or not tokens:
                    continue
                # OMP and pi also host non-Codex providers; keep only the Codex family.
                if kind == "turns" and not (name.startswith("GPT-") or name.startswith("o")):
                    continue
                _add(days, day_of(stamp, fallback), name, tokens)
            consumed = stream.tell() - start
    except OSError:
        return offset, offset - start
    return offset, consumed


def scan_codex(path, days):
    """Codex logs a running session total, so its head and tail are the whole story."""
    try:
        fallback = path.stat().st_mtime
        with path.open("rb") as stream:
            size = stream.seek(0, os.SEEK_END)
            model, stamp, total = "", None, 0
            for record, offset in _records(stream, 0, MAX_HEAD_BYTES):
                if record is None:
                    continue
                payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
                if record.get("type") == "turn_context":
                    model = payload.get("model") or model
                    if model:
                        break
            start = max(0, size - MAX_TAIL_BYTES)
            if start:
                stream.seek(start)
                stream.readline()  # discard a partial record
                start = stream.tell()
            for record, _ in _records(stream, start, MAX_TAIL_BYTES):
                if record is None:
                    continue
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
        return None
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
    found = []
    try:
        for path in root.rglob("*.jsonl"):
            try:
                if path.is_file() and path.stat().st_mtime >= cutoff:
                    found.append((path.stat().st_mtime, path))
            except OSError:
                continue
    except OSError:
        pass
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
    cached = read_json(cache_path)
    if cached.get("version") != CACHE_VERSION:
        cached = {}
    stored = cached.get("files", {})
    stored = stored if isinstance(stored, dict) else {}
    files = dict(stored) if budget <= 0 else {}

    for provider, kind, root in sources(home) if budget > 0 else []:
        spent = 0
        for path in _in_window(root, cutoff):
            key = str(path)
            entry = stored.get(key) if isinstance(stored.get(key), dict) else None
            try:
                status = path.stat()
            except OSError:
                continue
            if entry and (not isinstance(entry.get("offset"), int)
                          or not isinstance(entry.get("size"), int)
                          or not isinstance(entry.get("days"), dict)
                          or not 0 <= entry["offset"] <= entry["size"]):
                entry = None
            unchanged = (entry and entry["offset"] >= status.st_size
                         and entry["size"] == status.st_size and entry.get("mtime") == status.st_mtime)
            if unchanged or spent >= budget:
                if entry:
                    files[key] = entry  # keep what is known; anything new lands on a later poll
                continue
            if kind == "codex":
                needed = min(status.st_size, MAX_HEAD_BYTES) + min(status.st_size, MAX_TAIL_BYTES)
                if needed > budget - spent:
                    if entry:
                        files[key] = entry
                    continue
                days, offset = {}, status.st_size
                scanned = scan_codex(path, days)
                if scanned is None:
                    if entry:
                        files[key] = entry
                    continue
                spent += scanned
            else:
                resume, days = 0, {}
                if entry and entry["offset"] and (status.st_size > entry["size"] or (
                        status.st_size == entry["size"] and status.st_mtime == entry.get("mtime"))):
                    # Append-only: keep the earlier tally and read only what was added.
                    resume = entry["offset"]
                    days = {day: dict(models) for day, models in (entry.get("days") or {}).items()
                            if isinstance(models, dict)}
                offset, read = scan_turns(path, kind, resume, days,
                                          min(budget - spent, max(0, status.st_size - resume)))
                spent += read
            files[key] = {"provider": provider, "mtime": status.st_mtime, "size": status.st_size,
                          "offset": offset, "days": {d: v for d, v in days.items() if d >= earliest}}

    totals = {"codex": {}, "claude": {}}

    def fold(provider, days):
        if not isinstance(days, dict):
            return
        for day, models in (days or {}).items():
            if day not in window or not isinstance(models, dict):
                continue
            for name, tokens in models.items():
                totals[provider][name] = totals[provider].get(name, 0) + _count(tokens)

    for entry in files.values():
        if isinstance(entry, dict) and entry.get("provider") in totals:
            fold(entry["provider"], entry.get("days"))
    opencode = {} if budget > 0 else cached.get("opencode", {})
    if budget > 0:
        scan_opencode(roots(home)["opencode"] / "opencode.db", opencode, cutoff, now)
    fold("codex", opencode)

    if budget:
        updated = {"version": CACHE_VERSION, "files": files, "opencode": opencode}
        if updated != cached:
            atomic_json(cache_path, updated)
    return {provider: [{"name": name, "tokens": tokens}
                       for name, tokens in sorted(models.items(), key=lambda item: -item[1])[:MAX_MODELS]]
            for provider, models in totals.items()}
