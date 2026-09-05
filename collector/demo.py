"""Explicit demo fixtures used by the preview, never by default."""

import time
from datetime import datetime, timedelta


def snapshot():
    now = time.time()
    today = datetime.fromtimestamp(now).date()
    accounts = []
    for provider, name, used, weekly, plan, sources in [
        ("codex", "Codex", 38, 62, "pro", ["Codex", "pi", "OMP", "opencode"]),
        ("claude", "Claude", 56, 58, "Max 5x", ["Claude Code"])
    ]:
        windows = [{"id": "primary", "label": "5-hour window", "used": used, "resetAt": now + 8940, "duration": 18000},
                   {"id": "secondary", "label": "7-day window", "used": weekly, "resetAt": now + 180000, "duration": 604800}]
        weekly = ([{"name": "GPT-5.6 Sol", "tokens": 1_632_925_607}, {"name": "GPT-5.6 Terra", "tokens": 502_735_046},
                   {"name": "GPT-6 Astra", "tokens": 144_677_223}, {"name": "GPT-5.6 Luna", "tokens": 20_695_597}]
                  if provider == "codex" else
                  [{"name": "Claude Opus 5", "tokens": 902_450_118}, {"name": "Claude Fable 5", "tokens": 115_820_744},
                   {"name": "Claude Sonnet 5", "tokens": 34_480_915}])
        accounts.append({"id": provider + "-demo", "provider": provider, "name": name, "label": " + ".join(sources),
                         "plan": plan, "sources": sources, "windows": windows,
                         "models": weekly,
                         "status": "ok", "updatedAt": now, "message": "", "note": "Account-wide usage across connected clients.",
                         "history": [{"date": str(today - timedelta(days=6-i)), "value": v, "window": "primary"} for i, v in enumerate([32, 57, 44, 76, 23, 49, used])]})
    return {"version": 1, "demo": True, "checkedAt": now, "accounts": accounts}
