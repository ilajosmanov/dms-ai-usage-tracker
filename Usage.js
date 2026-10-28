.pragma library

// Everything provider-specific lives in this one table. Provider identity is
// intentionally stable across themes and usage levels.
// `accent` is the brand color and is used for every fill, unmodified in both
// themes. `accentOnLight` is the same identity darkened to clear 4.5:1 as text
// on a light surface; the brand hex itself only reaches ~3.3:1 there.
var PROVIDERS = [
    {id: "codex", label: "Codex", accent: "#10A37F", accentOnLight: "#0B8368",
     dashboard: "https://chatgpt.com/codex/settings/usage"},
    {id: "claude", label: "Claude", accent: "#D97757", accentOnLight: "#B65A3C",
     dashboard: "https://claude.ai/settings/usage"}
];

function brand(provider) {
    return PROVIDERS.filter(function(p) { return p.id === provider; })[0] || PROVIDERS[0];
}

function accent(provider) {
    return brand(provider).accent;
}

function accentText(provider, isLightMode) {
    var entry = brand(provider);
    return isLightMode ? entry.accentOnLight : entry.accent;
}

function refreshIntervalMs(minutes) {
    var value = Number(minutes);
    if (!isFinite(value) || value <= 0)
        value = 2;
    return Math.round(Math.max(2, Math.min(30, value)) * 60000);
}

function brandLabel(provider) {
    return brand(provider).label;
}

function orderedProviders(primary) {
    var ids = PROVIDERS.map(function(p) { return p.id; });
    if (ids.indexOf(primary) < 1)
        return ids;
    return [primary].concat(ids.filter(function(id) { return id !== primary; }));
}

function providerOptions() {
    return PROVIDERS.map(function(p) { return {label: p.label, value: p.id}; });
}

function dashboardUrl(provider) {
    return brand(provider).dashboard;
}

function percent(window) {
    if (!window || typeof window.used !== "number" || !isFinite(window.used)) return "—";
    return window.used > 0 && window.used < 1 ? "<1%" : Math.round(window.used) + "%";
}

var SEVERITY_RANK = {critical: 3, warning: 2, normal: 1};

function urgency(window) {
    if (!window || typeof window.used !== "number" || !isFinite(window.used))
        return null;
    return [window.used, window.active ? 1 : 0,
            SEVERITY_RANK[String(window.severity || "")] || 0,
            // Same fullness, less time to spend it: the shorter window binds first.
            -(window.duration || 0)];
}

function outranks(candidate, best) {
    for (var i = 0; i < candidate.length; i++) {
        if (candidate[i] !== best[i])
            return candidate[i] > best[i];
    }
    return false;
}

function primaryWindow(account) {
    var windows = (account && account.windows) || [];
    var best = null;
    var rank = null;
    for (var i = 0; i < windows.length; i++) {
        var score = urgency(windows[i]);
        if (score === null)
            continue;
        if (rank === null || outranks(score, rank)) {
            best = windows[i];
            rank = score;
        }
    }
    return best || windows[0];
}

function primaryUsage(account) {
    var window = primaryWindow(account);
    return window && typeof window.used === "number" && isFinite(window.used) ? window.used : null;
}

function barWindow(account) {
    var windows = (account && account.windows) || [];
    var best = null;
    for (var i = 0; i < windows.length; i++) {
        var candidate = windows[i];
        if (!candidate || typeof candidate.used !== "number" || !isFinite(candidate.used)
            || typeof candidate.duration !== "number" || !isFinite(candidate.duration))
            continue;
        if (!best || candidate.duration < best.duration)
            best = candidate;
    }
    return best || primaryWindow(account);
}

function barUsage(account) {
    var window = barWindow(account);
    return window && typeof window.used === "number" && isFinite(window.used) ? window.used : null;
}

function barAccounts(codex, claude) {
    return [codex, claude].filter(function(a) { return barUsage(a) !== null; });
}


function overPace(account, now) {
    if (!account || account.status !== "ok") return false;
    var pacing = pace(barWindow(account), now);
    return pacing !== null && pacing.delta >= 2;
}

function planLabel(plan) {
    return String(plan || "").replace(/_/g, " ").replace(/\b[a-z]/g, function(c) { return c.toUpperCase(); });
}

function shortPlan(plan, name) {
    var text = planLabel(plan);
    if (name)
        text = text.replace(new RegExp("\\b" + name + "\\b", "i"), "");
    return text.replace(/^\s*Default\b/i, "").replace(/\s+/g, " ").trim();
}

function shortWindow(label) {
    return String(label || "").replace(/\s*window$/i, "").replace(/(\d+)\s*days$/i, "$1d").trim();
}

// Model ids carry a release date that means nothing at this width.
function modelLabel(name) {
    return String(name || "").replace(/\s*\b20\d{6}\b\s*$/, "").trim();
}

// Caution is earned either way: by the number, or by the provider saying so.
function nearLimit(window) {
    if (!window)
        return false;
    if (String(window.severity || "") === "critical")
        return true;
    return typeof window.used === "number" && isFinite(window.used) && window.used >= 90;
}

function clientLabel(label) {
    return String(label || "").replace(/\bOpenCode\b/g, "opencode");
}

function countdown(resetAt, now) {
    if (!resetAt)
        return "Reset time unavailable";
    var seconds = resetAt - now / 1000;
    if (seconds <= 0)
        return "Awaiting reset update";
    var minutes = Math.ceil(seconds / 60);
    var hours = Math.floor(minutes / 60);
    if (hours >= 24)
        return "Resets in " + Math.floor(hours / 24) + "d " + hours % 24 + "h";
    return "Resets in " + hours + "h " + minutes % 60 + "m";
}

function resetShort(resetAt, now) {
    var text = countdown(resetAt, now);
    return text.indexOf("Resets in ") === 0 ? text.slice(10) : "—";
}

function pace(window, now) {
    if (!window || !window.duration || !window.resetAt || window.resetAt * 1000 <= now)
        return null;
    var elapsed = Math.max(0, Math.min(1, 1 - (window.resetAt - now / 1000) / window.duration));
    var delta = Math.round(window.used - elapsed * 100);
    return { expected: elapsed * 100, delta: delta,
        text: Math.abs(delta) < 2 ? "On pace" : Math.abs(delta) + "% " + (delta > 0 ? "over" : "under") + " pace" };
}

function age(updatedAt, now) {
    if (!updatedAt)
        return "Never synced";
    var minutes = Math.max(0, Math.floor((now / 1000 - updatedAt) / 60));
    if (minutes < 1)
        return "Updated just now";
    if (minutes < 60)
        return "Updated " + minutes + "m ago";
    return "Updated " + Math.floor(minutes / 60) + "h ago";
}

function latestUpdate(snapshot) {
    var accounts = (snapshot.accounts || []);
    var live = accounts.filter(function(a) { return a.status === "ok"; });
    var stamps = (live.length ? live : accounts).map(function(a) { return a.updatedAt; })
        .filter(function(t) { return typeof t === "number" && isFinite(t); });
    return stamps.length ? Math.max.apply(null, stamps) : null;
}

// The age the header no longer carries for a saved column.
function savedAge(updatedAt, now) {
    if (!updatedAt)
        return "";
    var minutes = Math.max(0, Math.floor((now / 1000 - updatedAt) / 60));
    if (minutes < 1)
        return "under 1m old";
    if (minutes < 60)
        return minutes + "m old";
    return Math.floor(minutes / 60) + "h old";
}

function originNote(account, now) {
    if (!account || !account.origin)
        return "";
    var when = savedAge(account.updatedAt, now);
    return "via " + account.origin + (when ? " · " + when : "");
}

function savedTitle(account, now) {
    var origin = account && account.origin;
    var when = savedAge(account && account.updatedAt, now);
    return (origin ? "Showing " + origin + "'s last check" : "Showing saved usage")
        + (when ? " · " + when : "");
}

// Report the collector's retry deadline without guessing how the provider scopes it.
function retryNote(retryAt, now) {
    if (typeof retryAt !== "number" || !isFinite(retryAt) || retryAt <= 0)
        return "";
    var minutes = Math.ceil((retryAt - now / 1000) / 60);
    if (minutes <= 0)
        return "";
    var wait = minutes < 60 ? minutes + "m"
        : Math.floor(minutes / 60) + "h" + (minutes % 60 ? " " + minutes % 60 + "m" : "");
    return "Next check in " + wait + ".";
}

// The collector writes the same note on every account; the panel shows it once.
function sharedNote(snapshot) {
    var notes = (snapshot.accounts || []).map(function(a) { return a.note; })
        .filter(function(n) { return typeof n === "string" && n !== ""; });
    return notes.length ? notes[0] : "";
}

function providerAccounts(snapshot, provider) {
    return (snapshot.accounts || []).filter(function(a) { return a.provider === provider; });
}

function representativeAccount(accounts) {
    var selected = null;
    var highest = -1;
    accounts.forEach(function(account) {
        var used = primaryUsage(account);
        if (used === null)
            used = -1;
        if (!selected || used > highest) {
            selected = account;
            highest = used;
        }
    });
    return selected;
}

function days(history, now) {
    var result = [];
    var today = new Date(now);
    for (var offset = 6; offset >= 0; offset--) {
        var date = new Date(today.getFullYear(), today.getMonth(), today.getDate() - offset);
        var key = date.getFullYear() + "-" + ("0" + (date.getMonth() + 1)).slice(-2) + "-" + ("0" + date.getDate()).slice(-2);
        var match = (history || []).filter(function(h) { return h.date === key; })[0];
        result.push({date: key, label: ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"][date.getDay()],
            value: match ? match.value : null});
    }
    return result;
}

function historyLabel(history) {
    var spans = (history || []).map(function(h) { return h.duration; })
        .filter(function(d) { return typeof d === "number" && isFinite(d) && d > 0; });
    if (!spans.length)
        return "Daily peak";
    return "Daily peak · " + shortWindow(spanLabel(spans[0]));
}

function spanLabel(seconds) {
    if (seconds % 86400 === 0)
        return (seconds / 86400) + "-day window";
    if (seconds % 3600 === 0)
        return (seconds / 3600) + "-hour window";
    return "window";
}

function dayTooltip(day) {
    var peak = day && day.value !== null && typeof day.value === "number" ? Math.round(day.value) + "% peak" : "No usage sample";
    return (day ? day.date : "") + " · " + peak;
}

// Token counts run to ten figures, so a bar chart needs a short, honest label.
function tokens(value) {
    if (typeof value !== "number" || !isFinite(value) || value < 0) return "—";
    if (value >= 1e9) return (value / 1e9).toFixed(1) + "B";
    if (value >= 1e6) return (value / 1e6).toFixed(1) + "M";
    if (value >= 1e3) return (value / 1e3).toFixed(1) + "K";
    return String(Math.round(value));
}

function modelBars(account) {
    var models = (account && account.models) || [];
    var top = 0;
    for (var i = 0; i < models.length; i++) {
        if (models[i] && typeof models[i].tokens === "number" && isFinite(models[i].tokens) && models[i].tokens > top)
            top = models[i].tokens;
    }
    var result = [];
    for (var j = 0; j < models.length; j++) {
        var entry = models[j];
        if (!entry || typeof entry.name !== "string" || !entry.name || typeof entry.tokens !== "number" || !(entry.tokens > 0))
            continue;
        // Bars are relative to the busiest model, so the smallest one stays visible.
        result.push({name: entry.name, tokens: entry.tokens, label: tokens(entry.tokens), share: entry.tokens / top});
    }
    return result;
}
