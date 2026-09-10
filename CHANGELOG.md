# Changelog

All notable changes to this plugin. Versions follow [semantic versioning](https://semver.org).

## 1.0.0 — 2026-09-10

First public release, submitted to the Dank Material Shell plugin registry.

Published under the display name **Subscription Usage Meter**; the plugin id stays
`aiUsage`, so existing installs and their settings are unaffected.

### Bar

- One vertical meter per subscription, each filled from its own quota rather than a
  shared total, in the provider's brand color in both light and dark themes.
- Per-provider pace arrows, shown only when a provider is at least two points over
  its linear pace and its reset time is known.
- Horizontal and vertical bar layouts.

### Popout

- Codex and Claude side by side, one column each, with independent status: one
  provider can be disconnected while the other reads normally. The **Primary
  provider** setting swaps the columns.
- Per-limit rows with the real window, a pace notch, the countdown, and a caution
  color once a window is at least 90% consumed.
- Seven-day strip of daily peak utilization, and a **Models this week** block
  totalling local session tokens per model.
- Native account selector for providers with more than one account.

### Collection

- Codex: account-wide provider usage, reusing newer `rate_limits` snapshots from
  local session logs between API checks.
- Claude: Claude Code's native `get_usage` control request, run in a short-lived
  safe-mode subprocess with tools, MCP, telemetry, and auto-update disabled, and
  verified against `cachedUsageUtilization` so a cached fallback is never dated as
  a fresh check.
- Existing Codex, Claude Code, pi, OMP, and opencode logins are detected; nonstandard
  paths can be set in plugin settings.
- Failures retain the last verified reading for at most 24 hours, with its original
  capture time and a stale marker. Missing readings never render as zero.
- Only usage metadata, model names with local token totals, opaque identity hashes,
  and an HMAC credential fingerprint are cached, in `~/.cache/dms-ai-usage/`
  (mode 0600 in a 0700 directory).

### Requirements

- Dank Material Shell 1.6 or newer, Python 3.10 or newer (standard library only).
- Claude collection needs a recent `claude` executable on `PATH`; verified with
  Claude Code 2.1.263.
