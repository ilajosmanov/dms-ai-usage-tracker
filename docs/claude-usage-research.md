# Claude subscription usage monitoring research

Researched 2026-09-10. This compares primary project source at the pinned revisions below, not installation counts or claims that every third-party implementation works reliably. No third-party monitor was installed or given account credentials. A bounded local runtime probe was also performed; its observed results are recorded below.

## Findings

The useful distinction is **who owns authentication and where the quota measurement comes from**. Current plugins use three approaches: consume Claude Code’s official statusline data, let Claude Code perform authenticated retrieval/renewal, or establish an independently owned login. Reading a saved access token forever does not implement renewal. Local token/cost estimates are a separate product from authoritative subscription percentages.

For this widget, prefer Claude Code’s structured `get_usage` control request, with bounded lifecycle and verified capture freshness. This can put token renewal and authenticated requests back under Claude Code’s ownership without requiring the user to keep a terminal open. `get_usage` is referenced by Claude HUD’s current README and appears in the published Anthropic SDK type union; a local probe verified it on the installed binary as described below. The interface remains experimental; validate response shape defensively. Sources: [Claude HUD usage integration](https://github.com/jarrodwatts/claude-hud/blob/939eb66485832dead1b0a28a954f76f7aa2bdb06/README.md#usage-limits), [Anthropic SDK 0.3.211 published types](https://app.unpkg.com/%40anthropic-ai/claude-agent-sdk%400.3.211/files/sdk.d.ts).

## Compared implementations

| Implementation | Quota source | Authentication ownership | Useful while Claude is closed? |
| --- | --- | --- | --- |
| d-mato/claude-usage-bar | Native stream-json `get_usage` | Entirely owned by Claude Code | Yes: spawns a CLI process for each collection |
| CodexBar | OAuth usage endpoint, CLI `/usage`, web endpoint | Distinguishes CLI-owned and app-owned credentials | Yes, through delegated CLI probes or an available independent source; each can fail |
| Claude HUD | Official statusline stdin; optional local snapshot | HUD never fetches usage itself | Can retain/read snapshots, but fresh collection needs Claude or an external feeder |
| Claude Code Usage Monitor (Maciek) | Captured official statusline; labeled local estimates otherwise | No network in official capture/read module | Historical data and estimates remain; live official capture stops |
| cc-usage-monitor | Official statusline stdin | Claude Code supplies quota data | No independent background quota collection |
| ClaudexBar | OAuth usage endpoint | Own PKCE grant and token store, with shared-login fallback | Own grant can refresh independently; fallback has an ownership flaw |
| claude-web-usage | Claude web organization usage endpoint | Reads Claude Desktop session cookies | While saved cookie remains valid; cookie expiry/Cloudflare still require recovery |
| claude_usage (Python/Linux-compatible) | OAuth usage endpoint | Briefly starts Claude to renew saved credential | Intended to work unattended; crude subprocess lifecycle needs improvement |

### d-mato/claude-usage-bar: the closest fit

At `b4a3bccf6e924d79fc8c05dcf1af4edcac83b93e`, this SwiftBar plugin runs `claude -p --input-format stream-json --output-format stream-json --verbose`, sends one `get_usage` control frame, and selects a matching `request_id` from line-delimited output. It never reads or writes OAuth credentials. Its subprocess has a 60-second timeout. This supplies a directly relevant working architecture, though our adapter should additionally disable hooks/tools/MCP and verify data capture time. Source: [native transport](https://github.com/d-mato/claude-usage-bar/blob/b4a3bccf6e924d79fc8c05dcf1af4edcac83b93e/claude-usage.5m.py#L23).

Its README records a progression from inaccurate local-log aggregation to direct OAuth polling, then a one-token inference/header probe, finally the zero-inference control request. It labels the interface undocumented and version-sensitive. This history is the maintainer’s account, not a controlled comparison proving all earlier paths universally fail. Source: [architecture and version history](https://github.com/d-mato/claude-usage-bar/blob/b4a3bccf6e924d79fc8c05dcf1af4edcac83b93e/README.md).

### CodexBar: explicit credential ownership and multiple sources

At `7fdc17636f161ab410d8a6a0e8f45b6a595cf8d2`, expired `.claudeCLI` credentials trigger delegation; only `.codexbar` credentials enter the direct refresh-token path. Presence of CLI storage keeps ambiguous mirrored credentials CLI-owned. This is a concrete safeguard against two applications independently rotating the same refresh-token chain. Sources: [owner resolution](https://github.com/steipete/CodexBar/blob/7fdc17636f161ab410d8a6a0e8f45b6a595cf8d2/Sources/CodexBarCore/Providers/Claude/ClaudeOAuth/ClaudeOAuthCredentials.swift#L731), [expiry dispatch](https://github.com/steipete/CodexBar/blob/7fdc17636f161ab410d8a6a0e8f45b6a595cf8d2/Sources/CodexBarCore/Providers/Claude/ClaudeOAuth/ClaudeOAuthCredentials.swift#L1608).

Delegation runs `/status` through a PTY, ends the probe, then checks for an updated readable credential source. The coordinator joins overlapping attempts and applies per-profile cooldowns. Its default attempt timeout is eight seconds and normal cooldown five minutes. Copy the ownership and bounded-verification principles, not an assumption that starting a process proves renewal. Sources: [PTY auth touch](https://github.com/steipete/CodexBar/blob/7fdc17636f161ab410d8a6a0e8f45b6a595cf8d2/Sources/CodexBarCore/Providers/Claude/ClaudeStatusProbe.swift#L344), [coordinator](https://github.com/steipete/CodexBar/blob/7fdc17636f161ab410d8a6a0e8f45b6a595cf8d2/Sources/CodexBarCore/Providers/Claude/ClaudeOAuth/ClaudeOAuthDelegatedRefreshCoordinator.swift).

The OAuth 429 gate persists deadlines keyed by a hash of the access token. It uses a future `Retry-After`, otherwise five minutes, and extends rather than shortens an existing deadline. Manual interaction bypasses this gate. The fetcher parses numeric seconds and HTTP-date headers. These are CodexBar policy choices, not proof that Anthropic throttles exclusively per token. Sources: [rate-limit gate](https://github.com/steipete/CodexBar/blob/7fdc17636f161ab410d8a6a0e8f45b6a595cf8d2/Sources/CodexBarCore/Providers/Claude/ClaudeOAuth/ClaudeOAuthUsageRateLimitGate.swift), [HTTP handling](https://github.com/steipete/CodexBar/blob/7fdc17636f161ab410d8a6a0e8f45b6a595cf8d2/Sources/CodexBarCore/Providers/Claude/ClaudeOAuth/ClaudeOAuthUsageFetcher.swift).

The main app pipeline falls back OAuth → CLI → Web; explicit source choices are terminal. Web uses `sessionKey` with `/api/organizations/{orgId}/usage`. Last successful percentages remain visible as stale when all live sources fail. Account checks prevent enriching one account with another account’s web data. Cloudflare challenge handling retains cookies instead of treating every failure as logout. Source: [provider documentation](https://github.com/steipete/CodexBar/blob/7fdc17636f161ab410d8a6a0e8f45b6a595cf8d2/docs/claude.md).

### Claude HUD and cc-usage-monitor: avoid adding quota requests

Claude HUD at `939eb66485832dead1b0a28a954f76f7aa2bdb06` reads `rate_limits.five_hour/seven_day.used_percentage` and epoch reset times from stdin. It also accepts model-scoped windows. Missing windows remain absent. Source: [stdin parser](https://github.com/jarrodwatts/claude-hud/blob/939eb66485832dead1b0a28a954f76f7aa2bdb06/src/stdin.ts#L379).

HUD can write official stdin quota to a private local snapshot and can consume a fresh external snapshot. This is useful as an opportunistic source for desktop widgets, but the writer runs when Claude invokes its statusline, so it does not solve indefinitely closed-client refresh. Source: [snapshot reader/writer](https://github.com/jarrodwatts/claude-hud/blob/939eb66485832dead1b0a28a954f76f7aa2bdb06/src/external-usage.ts).

cc-usage-monitor at `be79620bbe0664377cc146f63ecc5ccff7f5c17d` similarly renders stdin quota and separately computes local session token/cost totals. Its parser does not call an OAuth usage endpoint. Source: [quota parser](https://github.com/harveyxiacn/cc-usage-monitor/blob/be79620bbe0664377cc146f63ecc5ccff7f5c17d/lib/parse.js).

### Claude Code Usage Monitor: official data and estimates are distinct

At `c59a83bf943f329f0e61f1a29c760353ee1860a5`, Maciek’s monitor has an official statusline capture/read module. It writes atomically, treats captures older than 600 seconds as stale, rejects invalid percentages, and clears a captured window’s percentage when its reset time has passed. A missing statusline quota writes a tombstone. Source: [official data module](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor/blob/c59a83bf943f329f0e61f1a29c760353ee1860a5/src/claude_monitor/output/official.py).

Its broader product still provides local estimates and forecasting, but labels provenance and shows weekly percentages only from official data. Token P90 calculations are historical estimates, not recovered Anthropic account limits. Sources: [README trust model](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor/blob/c59a83bf943f329f0e61f1a29c760353ee1860a5/README.md), [P90 calculator](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor/blob/c59a83bf943f329f0e61f1a29c760353ee1860a5/src/claude_monitor/core/p90_calculator.py).

### ClaudexBar: separate login, with a fallback caveat

At `b6b402b67595b390c1b735cda6b9254ad536b71d`, ClaudexBar implements a separate authorization-code/PKCE login, stores its own credentials, and persists rotated refresh tokens. Its auth document says `claude setup-token` lacks the profile scope required by usage. This is evidence of that project’s integration, not an independently verified guarantee about all token issuances. Sources: [auth design](https://github.com/ipangdz/claudexbar/blob/b6b402b67595b390c1b735cda6b9254ad536b71d/docs/AUTH.md), [provider refresh](https://github.com/ipangdz/claudexbar/blob/b6b402b67595b390c1b735cda6b9254ad536b71d/Sources/ClaudexBarCore/ClaudeProvider.swift).

Code-review caveat: the credential reader falls back to Claude Code storage and returns its refresh token, while the provider refreshes credentials without tracking ownership. Therefore its own-login path avoids sharing, but the blanket non-conflict claim does not hold for fallback. Do not copy this fallback. The provider maps 429 to a generic error without propagating `Retry-After`. Source: [credential selection](https://github.com/ipangdz/claudexbar/blob/b6b402b67595b390c1b735cda6b9254ad536b71d/Sources/ClaudexBarCore/CredentialReaders.swift#L63).

### claude-web-usage: another endpoint, not guaranteed availability

At `ab56a804c3894a08659850d53ea415454847ce55`, this script decrypts macOS Claude Desktop cookies and calls the organization usage endpoint directly. It has a 30-second cache, five-second request timeout, a 15-second lock-file age check, and a stale marker after five minutes. Every non-200 response falls back to cache; there is no distinct 429 deadline in this path. The check-then-write lock is not atomic mutual exclusion. Source: [fetch/cache implementation](https://github.com/skibidiskib/claude-web-usage/blob/ab56a804c3894a08659850d53ea415454847ce55/combined-statusline.js#L14).

Its documentation acknowledges expired cookies and Cloudflare failures can require reopening Desktop or claude.ai. Its claim of avoiding the OAuth throttle does not establish that the web endpoint cannot throttle. Linux would also need a different credential acquisition implementation. Source: [troubleshooting](https://github.com/skibidiskib/claude-web-usage/blob/ab56a804c3894a08659850d53ea415454847ce55/TROUBLESHOOTING.md).

### claude_usage: minimal native refresh delegation

At `4ecb04b512464100a6310eac65d455846aa5c401`, this Python CLI reads `.credentials.json`, caches successful usage for five minutes, and launches bare `claude` for approximately 20 seconds when access expires or a usage request returns 401. It terminates that process, rereads credentials, and retries. `Retry-After` is displayed, but no deadline is persisted to prevent another invocation retrying immediately. The implementation does not robustly verify refresh success or serialize concurrent refreshers. It also hardcodes a Claude CLI User-Agent; that is not evidence that changing User-Agent reliably repairs throttling. Source: [complete implementation](https://github.com/thiswillbeyourgithub/claude_usage/blob/4ecb04b512464100a6310eac65d455846aa5c401/claude_usage.py).

## Local feasibility validation

The local probe tested installed Claude Code `2.1.263` on 2026-09-10 with an expired saved access token. It launched a temporary CLI process in an isolated temporary working directory with:

```text
--print --input-format stream-json --output-format stream-json --verbose
--safe-mode --tools "" --strict-mcp-config --mcp-config '{"mcpServers":{}}'
--no-session-persistence
```

It sent these control requests in order, waiting for the initialization response before requesting usage, with no user/model messages:

```json
{"type":"control_request","request_id":"init","request":{"subtype":"initialize"}}
{"type":"control_request","request_id":"usage","request":{"subtype":"get_usage","skip_behaviors":true}}
```

Responses were matched by request ID. Both control responses succeeded in approximately 1.71 seconds. Claude renewed its own credential. The response recorded zero session cost, zero API duration, and no model usage, and returned authoritative quota windows. The existing collector subsequently read fresh `Claude Code` usage from the native local cache and reported status `ok`. These are local observations, not third-party claims.

The native implementation can return seeded cached usage when retrieval fails, so a successful control response alone cannot prove freshness. A production adapter must correlate `cachedUsageUtilization.fetchedAtMs` and account identity (`accountUuid`) before and after the request. Never timestamp an old response as freshly captured merely because a new process returned it. This is why transport success, auth renewal, and quota freshness need separate checks.

This probe establishes feasibility with the installed version. It does not implement the widget integration or establish reliability across future CLI versions. The research recommendation is to make native structured collection plus native cache reading the normal path, with PTY probing only a compatibility fallback. Preserve existing polling cadence and conservative backoff; honor an actual `Retry-After` longer than one hour instead of truncating it to one hour. The production collector has not been migrated by this research task.

## Implementation follow-up (2026-09-10)

The widget now uses this approach in `collector/claude.py`, integrated with the
existing collector schedule and lock. Claude performs its own renewal; account-bound
captures determine freshness. The normal Claude interval is at least five minutes,
execution is bounded to 25 seconds plus cleanup, and raw process diagnostics stay
private. Unsupported native versions report an error instead of silently reverting
to unrenewed OAuth polling. PTY fallback was not needed for the verified installed
version and is not implemented.

Verification includes an actual native collection on Claude Code 2.1.263, isolated
subprocess tests for expired-login recovery and cached fallback, concurrent collector
processes, account switching during a check, retry waits, capture expiration, and
process cleanup. See `tests/test_claude.py` and the current README for behavior.

A subsequent closed-client check exposed an integration error: setting
`CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` also blocked the native usage request
on 2.1.263, causing a successful control reply containing only saved data. Removing
that flag restored a fresh capture without opening the interactive client. The
collector now disables telemetry, error reporting, and automatic updates separately;
a live check with those settings confirmed HTTP 200 and zero model usage. Capture
comparison also tolerates reset timestamp differences below one second, observed
between successive service responses, while preserving the saved timestamp and
requiring all other normalized window fields to match.

## Recommended acceptance criteria for this widget

These are recommendations derived from the comparison, not claims already verified in this repository:

1. With Claude’s interactive UI closed and its access token expired, the widget obtains a fresh authoritative quota or reports a specific verified recovery failure. Prefer a bounded native structured request that lets Claude handle authentication.
2. Shared Claude refresh tokens remain Claude-owned; the widget does not create a second independent refresh writer. Any independent login has explicit separate storage and ownership.
3. Fresh official cached/statusline data can avoid an extra request. Account identity and capture time travel with every snapshot; account changes never reuse another account’s percentages.
4. Persist request cooldowns; honor actual `Retry-After`; keep renewal failure separate from usage-endpoint throttling. Do not promise that re-login fixes or cannot fix all 429s, and do not assert global/account/token throttle scope without direct evidence.
5. Retain last known readings with capture age and stale status. After a reset, do not present the previous window as a fresh percentage or invent zero usage.
6. If native retrieval is unavailable, expose a deliberate fallback. Web sessions are optional and require their own credential lifecycle; token-cost estimates remain labeled estimates.
7. Validate closed-client expired-token recovery, concurrency, retry deadlines, account switch, malformed/no-data responses, and subprocess cleanup. A third-party README or a mocked success alone does not prove runtime recovery.
