"""Discover only known credential stores, read-only. No token refresh or writes."""

import base64
import hashlib
import json
import math
import sqlite3
from contextlib import closing
from pathlib import Path

from .jsonfile import read_json
from .stores import roots


def header_safe(value):
    """Reject anything that cannot be sent verbatim in a request header."""
    return isinstance(value, str) and not any(c in value for c in "\r\n")


def claims(token):
    try:
        payload = token.split(".")[1]
        result = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return result if isinstance(result, dict) else {}
    except (ValueError, IndexError, TypeError):
        return {}


def discover(config, home=None):
    home = Path(home) if home else Path.home()
    found = []
    def add(provider, source, data, account="", plan=""):
        if not isinstance(data, dict):
            return
        secret = data.get("access_token") or data.get("accessToken") or data.get("access") or data.get("key")
        if not header_safe(secret) or not secret:
            return
        jwt = claims(secret)
        auth = jwt.get("https://api.openai.com/auth") or {}
        if not isinstance(auth, dict):
            auth = {}
        account = account or data.get("account_id") or data.get("accountId") or auth.get("chatgpt_account_id") or ""
        # Account + user avoids merging distinct members of a shared workspace.
        # The account id travels in a request header too, so hold it to the same rule.
        account = str(account) if header_safe(account) else ""
        # Identity must outlive token rotation: prefer an account id or JWT subject,
        # and fall back to the store, which is stable where the raw token is not.
        subject = str(jwt.get("sub", ""))
        identity = account + ":" + subject if account else subject or "store:" + source
        uid = hashlib.sha256((provider + ":" + identity).encode()).hexdigest()[:20]
        try:
            expires = float(data.get("expires") or data.get("expiresAt") or float(jwt.get("exp", 0)) * 1000)
            if not math.isfinite(expires):
                expires = 0
        except (TypeError, ValueError):
            expires = 0
        found.append({"id": provider + "-" + uid, "provider": provider, "source": source,
                      "secret": secret, "account": account, "plan": plan,
                      "expires": expires})

    store = roots(home)
    codex = read_json(Path(config.get("codexAuthFile") or store["codex"] / "auth.json").expanduser())
    add("codex", "Codex", codex.get("tokens", {}))
    claude = read_json(Path(config.get("claudeAuthFile") or store["claude"] / ".credentials.json").expanduser()).get("claudeAiOauth", {})
    if not isinstance(claude, dict):
        claude = {}
    add("claude", "Claude Code", claude, plan=str(claude.get("rateLimitTier") or claude.get("subscriptionType") or "Claude subscription").replace("_", " "))
    stores = [("pi", store["pi"] / "auth.json"),
              ("OMP", store["omp"] / "auth.json"),
              ("opencode", store["opencode"] / "auth.json")]
    mapping = {"openai": "codex", "openai-codex": "codex"}
    for source, path in stores:
        for name, data in read_json(path).items():
            provider = mapping.get(name)
            if provider and isinstance(data, dict):
                if data.get("type") not in (None, "oauth"):
                    continue
                add(provider, source, data)
    db = Path(config.get("ompDatabase") or store["omp"] / "agent.db").expanduser()
    if db.is_file():
        try:
            with closing(sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)) as conn:
                rows = conn.execute("SELECT provider, credential_type, data FROM auth_credentials WHERE disabled_cause IS NULL ORDER BY id")
                for name, kind, raw in rows:
                    provider = mapping.get(name)
                    if provider and kind == "oauth":
                        try:
                            add(provider, "OMP", json.loads(raw))
                        except (ValueError, TypeError):
                            pass
        except sqlite3.Error:
            pass
    # One output account per identity, with fallback credentials from other clients.
    groups = {}
    for credential in found:
        groups.setdefault(credential["id"], []).append(credential)
    return groups
