"""Read recent model identifiers from local client session metadata only."""

import json
import os
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

from .providers import hidden
from .stores import roots

MAX_FILES_PER_STORE = 32
MAX_TAIL_BYTES = 256 * 1024
RECENT_SECONDS = 7 * 86400
MAX_MODELS_PER_DAY = 6


def _recent_files(root, now):
    try:
        candidates = [(path.stat().st_mtime, path) for path in root.rglob("*.jsonl")
                      if path.is_file() and path.stat().st_mtime >= now - RECENT_SECONDS]
    except OSError:
        return []
    candidates.sort(key=lambda item: item[0], reverse=True)
    return [path for _, path in candidates[:MAX_FILES_PER_STORE]]


def _tail_objects(path):
    try:
        with path.open("rb") as stream:
            size = stream.seek(0, os.SEEK_END)
            start = max(0, size - MAX_TAIL_BYTES)
            stream.seek(start)
            if start:
                stream.readline()  # discard a partial JSONL record
            lines = stream.readlines()
    except OSError:
        return []
    result = []
    for raw in reversed(lines):
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeError):
            continue
        if isinstance(value, dict):
            result.append(value)
    return result


def _display_name(model):
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


def _model_from(record, store):
    if store == "codex":
        if record.get("type") != "turn_context":
            return ""
        payload = record.get("payload") or {}
        return payload.get("model", "") if isinstance(payload, dict) else ""
    if store == "claude":
        message = record.get("message") or {}
        return message.get("model", "") if isinstance(message, dict) else ""
    # Pi and OMP records use both direct ids and nested message metadata.
    direct = record.get("model") or record.get("modelId")
    if isinstance(direct, str):
        return direct
    message = record.get("message") or {}
    if isinstance(message, dict) and isinstance(message.get("model"), str):
        return message["model"]
    payload = record.get("payload") or {}
    return payload.get("model", "") if isinstance(payload, dict) else ""


def _day(value, fallback):
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


def _opencode_models_by_day(path, now):
    if not path.is_file():
        return []
    try:
        uri = path.resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=2)) as connection:
            rows = connection.execute(
                "SELECT model, time_updated FROM session WHERE model IS NOT NULL AND time_updated >= ? "
                "ORDER BY time_updated DESC LIMIT ?", (int((now - RECENT_SECONDS) * 1000), MAX_FILES_PER_STORE)
            )
            result = []
            for raw, updated in rows:
                try:
                    model = json.loads(raw) if isinstance(raw, str) else raw
                except ValueError:
                    model = raw
                if isinstance(model, dict) and model.get("providerID") in ("openai", "openai-codex"):
                    result.append((_day(updated, now), model.get("id", "")))
                elif isinstance(model, str):
                    result.append((_day(updated, now), model))
            return result
    except (OSError, sqlite3.Error):
        return []


def recent_models_by_day(home=None, now=None):
    """Return newest-first model names keyed by provider and local calendar day."""
    now = time.time() if now is None else now
    today = datetime.fromtimestamp(now).date()
    valid_days = {str(today - timedelta(days=offset)) for offset in range(7)}
    base = roots(home)
    stores = [
        ("codex", "codex", base["codex"] / "sessions"),
        ("codex", "pi", base["pi"] / "sessions"),
        ("codex", "omp", base["omp"] / "sessions"),
        ("claude", "claude", base["claude"] / "projects"),
    ]
    result = {"codex": {}, "claude": {}}
    seen = {"codex": {}, "claude": {}}

    def add(provider, day, model):
        name = _display_name(model)
        day_seen = seen[provider].setdefault(day, set())
        if day not in valid_days or not name or name in day_seen:
            return
        models = result[provider].setdefault(day, [])
        if len(models) >= MAX_MODELS_PER_DAY:
            return
        models.append(name)
        day_seen.add(name)

    for provider, store, root in stores:
        for path in _recent_files(root, now):
            try:
                fallback = path.stat().st_mtime
            except OSError:
                continue
            for record in _tail_objects(path):
                name = _display_name(_model_from(record, store))
                if not name:
                    continue
                # OMP can contain non-OpenAI providers; only retain Codex-family ids.
                if store in ("pi", "omp") and not (name.startswith("GPT-") or name.startswith("o")):
                    continue
                add(provider, _day(record.get("timestamp"), fallback), name)
    opencode_db = base["opencode"] / "opencode.db"
    for day, model in _opencode_models_by_day(opencode_db, now):
        add("codex", day, model)
    return result
