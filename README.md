# AI Usage for Dank Material Shell

Codex and Claude subscription usage in one native, theme-aware DankBar widget.
Requires Dank Material Shell / Quickshell and Python 3.10+. Tested with DMS 1.6.

## Install

```sh
python3 scripts/install.py
```

Links this checkout into `~/.config/DankMaterialShell/plugins/aiUsage`, enables it,
and adds it to the first enabled bar. Existing settings are preserved and backed
up before modification. Keep this checkout in place. Use `--no-bar` to place the
widget yourself under DMS Settings → DankBar → Widgets.

To uninstall, remove the widget from the bar, disable the plugin, and unlink the
`aiUsage` symlink. The checkout and cached usage remain available.

## Usage

The bar shows one circle followed by color-matched percentages, without a text title.
The ring is a proportional breakdown of the displayed primary-window
quota percentages: 60% Codex and 20% Claude produces a three-quarter Codex segment
and one-quarter Claude segment. Segments run clockwise from the top, Codex first
in the OpenAI green, then Claude in the Anthropic coral. Provider color is the one
thing here that does not follow your Material You palette, and it is identical in
light and dark themes, so a meter always reads as its own subscription. There are no remaining
allowance tracks. A single active subscription owns the entire colored ring.
This is a comparison of quota percentages, not raw token totals or a combined quota;
different subscriptions and windows have different allowances. Numeric percentages
remain unchanged. A reset to zero returns the ring to the remaining active provider.
If both are idle, the ring is neutral and both show 0%; unknown usage shows a dash.

Each active provider gets its own upward arrow when at least two percentage points
over its linear pace, matching the dashboard's pacing label and provider color.
Both can show arrows at once. Unknown reset times and stale data do not produce
pace warnings. The **Show pacing** setting controls these arrows too.

Click to open the dashboard. Right-click, or use its refresh button, to check usage
now. Provider tabs use matching colors. Multiple accounts get a native DMS selector;
the initial selection and ring show the highest primary-window utilization.
Manual account selections persist through refreshes. Vertical bars show the same
ring, with percentages and arrows stacked below it.
The header keeps the update time and dashboard, refresh, and close icons visible
while scrolling. The dashboard icon is immediately left of refresh; opening it
closes the usage dialog. Overflow uses the native DMS auto-hiding scrollbar.

The dashboard displays actual quota windows returned by each provider, reset times,
and optional pacing against the elapsed portion of a known fixed-length window.
Weekly-only Codex accounts are correctly labeled weekly. Claude may return usage
without a reset time; the widget does not invent one. Codex Spark quota buckets and
Anthropic's undocumented Nimbus Quill placeholder are intentionally hidden; real
model-scoped Claude limits such as Fable remain visible.

The seven-day chart records daily peak primary-window utilization observed by this
widget. Unsampled days are missing, not zero. It is a quota chart, not a spend chart.

**Models this week** is a separate block, one bar per model, for each provider. It totals
the tokens each model processed in local sessions over the last seven days — input, output,
and cache reads — and scales every bar against the busiest model. This is the one part of
the widget that is *not* account-wide: it counts what ran in session logs on this machine,
so another device's work is not included, and it is neither billing nor quota. Codex,
pi, OMP, opencode, and Claude Code sessions all count toward it.

## Connections

Account usage is shared across clients. The collector deduplicates matching Codex
account identities and tries the freshest available login. It reads, without modifying:

- `$CODEX_HOME/auth.json` (default `~/.codex/auth.json`)
- `$CLAUDE_CONFIG_DIR/.credentials.json` (default `~/.claude/.credentials.json`)
- `$PI_CODING_AGENT_DIR/auth.json` (default `~/.pi/agent/auth.json`)
- `~/.omp/agent/auth.json` and the current OMP SQLite `~/.omp/agent/agent.db`
- `$XDG_DATA_HOME/opencode/auth.json` (default `~/.local/share/opencode/auth.json`), for Codex OAuth only

Nonstandard Codex/Claude credential paths and the OMP database can be selected in
plugin settings. Codex keyring-only storage is not read. API keys are not treated
as subscription tokens. The plugin never uses refresh tokens; reconnect an expired
session in its source client.

## Refresh and privacy

Local credentials are checked every thirty seconds; the cache is rewritten only when
something actually changed. A new or changed login bypasses cached sign-in errors
immediately on the next check. Normal API polling follows the configured 2–15 minute
interval, shared across bars and screens. After a failure the next attempt is at
least two minutes out regardless of that setting. Manual refresh bypasses the
interval with a five-second cooldown. Provider rate limits still apply: HTTP 429
responses back off for at least five minutes. A check that starts while another is
still running reports the last stored result rather than queueing behind it.

Failures retain saved usage for at most 24 hours, with a warning, original update
time, and dimmed rings. Older data is hidden. Failed or missing connections never
appear as zero usage.

An account is identified by its provider account id or token subject, falling back
to the credential store it came from, so a rotated token keeps its recorded history.

Session logs are read incrementally. A file already scanned is re-read only from the byte
where the previous scan stopped, and Codex, which reports a running session total, is read
from its head and tail alone; a first scan of a long history is spread over the next few
polls rather than blocking one. The scan reads token counts and model ids. It never reads
message content, and its bookkeeping stays in
`$XDG_CACHE_HOME/dms-ai-usage/activity.json` (mode 0600).

Only usage metadata, model names with their local token totals, opaque identity hashes,
and a keyed credential fingerprint are cached in `$XDG_CACHE_HOME/dms-ai-usage/usage.json`
(default `~/.cache/dms-ai-usage/usage.json`, mode 0600, in a 0700 directory).
The fingerprint exists solely to notice that you signed in again; it is an HMAC under a
random per-install key in `fingerprint.key`, so the cache holds nothing a reader could
check a guessed token against. Refresh bookkeeping stays in that file and is never
published to the widget.

Raw credentials, email addresses, account IDs, prompts, and messages are not cached
or returned to QML. Credentials travel in HTTPS headers, not process arguments, and a
token or account id that could not be sent verbatim in a header is discarded rather
than sent. Provider-supplied text renders as plain text, never as markup.
No telemetry, model requests, token refreshes, or credential-store writes occur.
Redirects are rejected.

The only network destinations are `chatgpt.com/backend-api/wham/usage` and
`api.anthropic.com/api/oauth/usage`.

## Development

```sh
python3 get-ai-usage                  # sanitized live account data
python3 get-ai-usage --force          # check now, respecting rate limits
python3 get-ai-usage --offline        # no network requests
python3 get-ai-usage --demo           # sample data; no credential reads
python3 -m unittest discover -s tests -v
node --test tests/test_usage.cjs       # presentation logic; Node needed for tests only
python3 scripts/preview.py            # render fifteen native QML states offscreen
```

Optional `--config /path/to/settings.json` accepts plugin settings, for example
`{"refreshInterval": 5}`. Otherwise settings come from DMS's
`plugin_settings.json` under `aiUsage`.

`scripts/preview.py` renders fifteen QML states offscreen against installed DMS
components: both providers, multiple-account selection and refresh, missing/stale usage,
narrow layout, light theme, horizontal/vertical bar rings, single-provider usage, reset
transitions, and two independent pace arrows. It runs entirely on `--demo` data in an
isolated config, and its output under `screenshots/` is an untracked test artifact.
Set `DMS_QML_ROOT` if DMS is installed somewhere other than `/usr/share/quickshell/dms`.

DMS can cache child QML components during plugin reloads. Restart DMS after updating
the plugin if old controls remain visible.

Inspired by [titeya/dms-claudecode](https://github.com/titeya/dms-claudecode).
MIT licensed; attribution to Nicolas Bellamy's reference design is retained in LICENSE.
