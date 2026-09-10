"""Provider transport and normalization. Never log credentials or response bodies."""

import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

try:
    VERSION = str(json.loads((Path(__file__).resolve().parent.parent / "plugin.json").read_text())["version"])
except (OSError, ValueError, KeyError):
    VERSION = "0"


# Buckets a provider reports but that are not part of the subscription a user
# recognizes. Kept in one place: three different response shapes filter on it.
HIDDEN_QUOTAS = {"codex": ("spark",), "claude": ("nimbus_quill",)}


def hidden(provider, *parts):
    text = " ".join(str(part) for part in parts).casefold()
    return any(token in text for token in HIDDEN_QUOTAS.get(provider, ()))


class UsageError(Exception):
    def __init__(self, message, status="error", retry_after=120, rate_limited=False):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after
        self.rate_limited = rate_limited


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(url, headers, *, as_json=True):
    """Only GET official origins; reject redirects so auth cannot cross origins."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {
        "chatgpt.com", "api.anthropic.com"
    }:
        raise UsageError("Unsupported usage endpoint.")
    req = urllib.request.Request(url, headers={
        "User-Agent": "dms-ai-usage/" + VERSION, "Accept": "application/json", **headers
    })
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=12) as response:
            raw = response.read(4_000_001)
        if len(raw) > 4_000_000:
            raise UsageError("Usage response exceeds the supported size.")
        text = raw.decode("utf-8")
        return json.loads(text) if as_json else text
    except urllib.error.HTTPError as exc:
        exc.close()
        if exc.code in (301, 302, 303, 307, 308):
            raise UsageError("Provider redirected the usage request; refusing to follow it.") from None
        if exc.code == 401:
            raise UsageError("Session expired. Sign in again in the source client.", "auth") from None
        if exc.code == 403:
            raise UsageError("Access denied. Check this account's subscription and sign-in.", "auth") from None
        if exc.code == 429:
            retry = exc.headers.get("Retry-After", "300")
            try:
                seconds = int(retry) if retry.isdigit() else parsedate_to_datetime(retry).timestamp() - time.time()
            except (ValueError, TypeError, OverflowError):
                seconds = 300
            # The panel renders the retry deadline separately from the failure.
            raise UsageError("Provider rate limited this check.", "error", max(300, seconds), rate_limited=True) from None
        raise UsageError(f"Provider returned HTTP {exc.code}.") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        # A local link that is not up yet (resume from suspend, roaming) is not a
        # provider fault: retry on the next poll instead of the provider backoff.
        raise UsageError("Could not reach the provider. Check your connection.", retry_after=10) from None
    except (ValueError, UnicodeError):
        raise UsageError("Provider returned an unsupported response.") from None


def number(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError):
        return None


def timestamp(value):
    if isinstance(value, (float, int)):
        return number(value)
    if isinstance(value, str):
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if result.tzinfo is None:
                result = result.replace(tzinfo=timezone.utc)
            return result.timestamp()
        except (ValueError, OverflowError):
            pass
    return None


def window(key, label, used, reset, duration):
    pct = number(used)
    if pct is None or pct < 0:
        return None
    return {"id": key, "label": label, "used": pct,
            "resetAt": timestamp(reset), "duration": number(duration)}


def duration_label(seconds, fallback):
    if seconds and seconds % 86400 == 0:
        return f"{int(seconds / 86400)}-day window"
    if seconds and seconds % 3600 == 0:
        return f"{int(seconds / 3600)}-hour window"
    return fallback


def parse_codex(data):
    windows = []
    groups = [("", "", data.get("rate_limit") or {})]
    for extra in data.get("additional_rate_limits") or []:
        feature = str(extra.get("metered_feature", "additional"))
        name = str(extra.get("limit_name", "Additional"))
        if hidden("codex", feature, name):
            continue
        groups.append((feature + ":", name + " · ", extra.get("rate_limit") or {}))
    for prefix, label_prefix, limits in groups:
        for key, fallback in (("primary_window", "Primary window"), ("secondary_window", "Secondary window")):
            item = limits.get(key)
            if not isinstance(item, dict):
                continue
            duration = number(item.get("limit_window_seconds"))
            reset = item.get("reset_at")
            if reset is None and number(item.get("reset_after_seconds")) is not None:
                reset = time.time() + number(item["reset_after_seconds"])
            result = window(prefix + key, label_prefix + duration_label(duration, fallback), item.get("used_percent"), reset, duration)
            if result:
                windows.append(result)
    if not windows:
        raise UsageError("No subscription usage windows returned for this account.")
    return {"windows": windows, "plan": str(data.get("plan_type") or "Subscription").replace("_", " "),
            "note": "Account-wide usage across every client using this subscription."}


def parse_claude(data):
    windows = []
    labels = {"five_hour": ("5-hour window", 18000), "seven_day": ("7-day window", 604800),
              "seven_day_sonnet": ("Sonnet · 7 days", 604800), "seven_day_opus": ("Opus · 7 days", 604800),
              "seven_day_fable": ("Fable · 7 days", 604800), "fable": ("Fable · 7 days", 604800)}
    canonical = {"session": ("five_hour", "5-hour window", 18000),
                 "weekly_all": ("seven_day", "7-day window", 604800)}
    seen = set()
    for index, item in enumerate(data.get("limits") or []):
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind", ""))
        if kind == "weekly_scoped":
            scope = item.get("scope") or {}
            model = scope.get("model") or {} if isinstance(scope, dict) else {}
            display = str(model.get("display_name", "")).strip() if isinstance(model, dict) else ""
            if not display:
                continue
            key, label, duration = "weekly_scoped:" + display.casefold().replace(" ", "_"), display + " · 7 days", 604800
        elif kind in canonical:
            key, label, duration = canonical[kind]
        else:
            continue
        result = window(key, label, item.get("percent", item.get("utilization")), item.get("resets_at"), duration)
        if result:
            windows.append(result)
            seen.add(key)
    for key, (label, duration) in labels.items():
        item = data.get(key)
        if key in seen or not isinstance(item, dict) or "utilization" not in item:
            continue
        result = window(key, label, item.get("utilization"), item.get("resets_at"), duration)
        if result:
            windows.append(result)
    if not windows:
        raise UsageError("No Claude subscription usage windows returned.")
    # Response key order is not a contract; shortest known window first, unknown last.
    windows.sort(key=lambda w: (w["duration"] is None, w["duration"] or 0))
    result = {"windows": windows, "plan": "Claude subscription", "note": "Subscription usage reported by Anthropic."}
    extra = data.get("extra_usage") or {}
    if extra.get("is_enabled"):
        result["note"] += " Extra usage billing is enabled."
    return result


def fetch(credential):
    provider = credential["provider"]
    headers = {"Authorization": "Bearer " + credential["secret"]}
    if provider == "codex":
        if credential.get("account"):
            headers["ChatGPT-Account-Id"] = credential["account"]
        return parse_codex(request("https://chatgpt.com/backend-api/wham/usage", headers))
    raise UsageError("Unsupported provider.")
