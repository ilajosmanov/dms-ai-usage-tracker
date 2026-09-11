"""Explicit demo fixtures used by the preview, never by default."""

import time
from datetime import datetime, timedelta


def snapshot():
    now = time.time()
    today = datetime.fromtimestamp(now).date()
    accounts = []
    for provider, name, used, weekly, scoped, plan, sources in [
        ("codex", "Codex", 38, 62, None, "pro", ["Codex", "pi", "OMP", "opencode"]),
        # A nearly idle session window beside an almost spent per-model week: the
        # shape the panel used to headline as "0% used".
        ("claude", "Claude", 12, 58, 94, "Max 5x", ["Claude Code"])
    ]:
        windows = [{"id": "five_hour", "label": "5-hour window", "used": used, "resetAt": now + 8940,
                    "duration": 18000, "severity": "normal", "active": False},
                   {"id": "seven_day", "label": "7-day window", "used": weekly, "resetAt": now + 180000,
                    "duration": 604800, "severity": "warning", "active": False}]
        if scoped is not None:
            windows.append({"id": "weekly_scoped:fable", "label": "Fable · 7 days", "used": scoped,
                            "resetAt": now + 180000, "duration": 604800,
                            "severity": "critical", "active": True})
        weekly = ([{"name": "GPT-5.6 Sol", "tokens": 1_632_925_607}, {"name": "GPT-5.6 Terra", "tokens": 502_735_046},
                   {"name": "GPT-6 Astra", "tokens": 144_677_223}, {"name": "GPT-5.6 Luna", "tokens": 20_695_597}]
                  if provider == "codex" else
                  [{"name": "Claude Opus 5", "tokens": 902_450_118}, {"name": "Claude Fable 5", "tokens": 115_820_744},
                   {"name": "Claude Sonnet 5", "tokens": 34_480_915}])
        accounts.append({"id": provider + "-demo", "provider": provider, "name": name, "label": " + ".join(sources),
                         "plan": plan, "sources": sources, "windows": windows,
                         "models": weekly,
                         "status": "ok", "updatedAt": now - (95 if provider == "claude" else 0),
                         # One column read from its client's own state, one checked directly,
                         # so the preview always renders both attributions.
                         "origin": "Claude Code" if provider == "claude" else "",
                         "message": "", "note": "Account-wide usage across connected clients.",
                         # The daily peak charts the shortest window, so it ends on `used`.
                         "history": [{"date": str(today - timedelta(days=6-i)), "value": v,
                                      "window": "five_hour", "duration": 18000}
                                     for i, v in enumerate([32, 57, 44, 76, 23, 49, used])]})
    return {"version": 1, "demo": True, "checkedAt": now, "accounts": accounts}
