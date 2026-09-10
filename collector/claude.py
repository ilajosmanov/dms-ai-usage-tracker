"""Claude owns authentication and usage retrieval; we own process bounds and dating.

get_usage is an experimental stream-json control request, not an inference prompt.
Its response can hide a failed fetch behind cached data. Only Claude's account-bound
disk capture supplies a trustworthy timestamp; never date the response itself now.
"""

import json
import os
import selectors
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path

from .jsonfile import read_json
from .providers import UsageError, number, parse_claude

TIMEOUT = 25
MAX_OUTPUT = 4_000_000
MIN_INTERVAL = 300


def identity(state):
    account = state.get("oauthAccount") or {}
    if not isinstance(account, dict) or not account.get("accountUuid"):
        return ""
    return str(account["accountUuid"]) + ":" + str(account.get("organizationUuid") or "")


def account_matches(credential):
    return bool(credential.get("account")) and identity(read_json(credential.get("configFile", ""))) == credential["account"]


def current_token(credential):
    oauth = read_json(credential.get("authFile", "")).get("claudeAiOauth")
    token = oauth.get("accessToken") if isinstance(oauth, dict) else None
    return token if isinstance(token, str) and token else credential["secret"]


def read(credential, now):
    """Read only captures belonging to the discovered account and native profile."""
    state = read_json(credential.get("configFile", ""))
    expected = credential.get("account")
    if not expected or identity(state) != expected:
        return None
    stored = state.get("cachedUsageUtilization")
    if not isinstance(stored, dict):
        return None
    account = state["oauthAccount"]["accountUuid"]
    fetched = number(stored.get("fetchedAtMs"))
    if stored.get("accountUuid") != account or not fetched or not 0 < fetched / 1000 <= now:
        return None
    try:
        data = parse_claude(stored.get("utilization") or {})
    except (UsageError, ValueError, TypeError, AttributeError, KeyError):
        return None
    data["plan"] = credential.get("plan") or data["plan"]
    return {"data": data, "fetchedAt": fetched / 1000, "origin": "Claude Code"}


def _stop(process):
    # Also stop descendants after an early parent exit; this process group is ours.
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=1)


def _request(credential):
    binary = shutil.which("claude")
    if not binary:
        raise UsageError("Claude Code was not found. Install it and make claude available on PATH.", retry_after=300)
    if Path(credential.get("authFile", "")).name != ".credentials.json":
        raise UsageError("Native Claude usage requires a profile's .credentials.json file. Update the Claude credentials path.", "auth", 300)
    # Avoid routing the subprocess to an API key, proxy provider, or another OAuth
    # token inherited by the desktop shell. Claude reads the selected native profile.
    environment = {k: v for k, v in os.environ.items()
                   if not k.startswith(("ANTHROPIC_", "CLAUDE_")) and k != "CLAUDECODE"}
    # Essential-traffic mode also blocks /api/oauth/usage in Claude 2.1.263,
    # which silently returns a saved reading instead. Disable only background
    # reporting and updates so the usage request can actually reach the service.
    environment.update(DISABLE_TELEMETRY="1", DISABLE_ERROR_REPORTING="1", DISABLE_AUTOUPDATER="1")
    if credential.get("configDir"):
        environment["CLAUDE_CONFIG_DIR"] = credential["configDir"]
    command = [binary, "--print", "--input-format", "stream-json", "--output-format", "stream-json",
               "--verbose", "--safe-mode", "--tools", "", "--strict-mcp-config",
               "--mcp-config", '{"mcpServers":{}}', "--no-session-persistence"]
    with tempfile.TemporaryDirectory(prefix="dms-claude-usage-") as directory:
        process = subprocess.Popen(command, cwd=directory, env=environment, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ, "stdout")
                selector.register(process.stderr, selectors.EVENT_READ, "stderr")
                buffer = b""
                total = 0
                initialized = False
                deadline = time.monotonic() + TIMEOUT

                def send(request_id, request):
                    frame = {"type": "control_request", "request_id": request_id, "request": request}
                    process.stdin.write((json.dumps(frame) + "\n").encode())
                    process.stdin.flush()

                send("init", {"subtype": "initialize"})
                while selector.get_map() and time.monotonic() < deadline:
                    for key, _ in selector.select(min(0.5, max(0, deadline - time.monotonic()))):
                        raw = os.read(key.fileobj.fileno(), 65536)
                        if not raw:
                            selector.unregister(key.fileobj)
                            continue
                        total += len(raw)
                        if total > MAX_OUTPUT:
                            raise UsageError("Claude Code returned too much output. Check for a plugin or Claude update.", retry_after=300)
                        # Drain stderr, but never retain or publish diagnostics that
                        # may contain account details, credentials, or response bodies.
                        if key.data == "stderr":
                            continue
                        buffer += raw
                        while b"\n" in buffer:
                            line, buffer = buffer.split(b"\n", 1)
                            try:
                                frame = json.loads(line)
                            except (ValueError, UnicodeError):
                                continue
                            if not isinstance(frame, dict) or frame.get("type") != "control_response":
                                continue
                            response = frame.get("response")
                            if not isinstance(response, dict):
                                continue
                            expected = "usage" if initialized else "init"
                            if response.get("request_id") != expected:
                                continue
                            if response.get("subtype") != "success":
                                raise UsageError("Claude Code could not answer the usage request. Check its sign-in and version.", retry_after=300)
                            if not initialized:
                                initialized = True
                                send("usage", {"subtype": "get_usage", "skip_behaviors": True})
                            else:
                                data = response.get("response")
                                if not isinstance(data, dict):
                                    raise UsageError("Claude Code returned an unsupported usage response.", retry_after=300)
                                return data
                raise UsageError("Claude Code did not return usage in time. Check its sign-in and version.", retry_after=300)
        finally:
            _stop(process)
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()


def _same_windows(current, saved):
    """The service varies reset fractions between otherwise identical readings."""
    if len(current) != len(saved):
        return False
    for left, right in zip(current, saved):
        left, right = dict(left), dict(right)
        reset, saved_reset = left.pop("resetAt", None), right.pop("resetAt", None)
        if left != right:
            return False
        if reset != saved_reset and (reset is None or saved_reset is None or abs(reset - saved_reset) >= 1):
            return False
    return True


def fetch(credential, interval=MIN_INTERVAL):
    """Fetch through Claude and verify identity, shape, and the dated capture."""
    try:
        result = _request(credential)
    except (OSError, subprocess.SubprocessError):
        raise UsageError("Could not run Claude Code to check usage.", retry_after=300) from None
    state = read_json(credential.get("configFile", ""))
    if not credential.get("account") or identity(state) != credential["account"]:
        raise UsageError("Claude's account changed. Checking the current account on the next poll.", retry_after=30)
    limits = result.get("rate_limits")
    if result.get("rate_limits_available") is not True or not isinstance(limits, dict):
        oauth = read_json(credential.get("authFile", "")).get("claudeAiOauth") or {}
        expires = number(oauth.get("expiresAt")) if isinstance(oauth, dict) else None
        if expires and expires / 1000 <= time.time():
            raise UsageError("Claude could not renew its expired login. Sign in again in Claude Code.", "auth", max(300, interval))
        raise UsageError("Claude Code did not return subscription limits. Check its sign-in and subscription.", retry_after=max(300, interval))
    try:
        data = parse_claude(limits)
    except (UsageError, ValueError, TypeError, KeyError, AttributeError):
        raise UsageError("Claude Code returned an unsupported usage response.", retry_after=300) from None
    now = time.time()
    reading = read(credential, now)
    if not reading or now - reading["fetchedAt"] >= interval or not _same_windows(data["windows"], reading["data"]["windows"]):
        raise UsageError("Claude could not verify fresh usage. Retrying later.", retry_after=max(300, interval))
    return reading
