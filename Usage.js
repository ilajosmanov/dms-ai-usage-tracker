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

function brandLabel(provider) {
    return brand(provider).label;
}

// Column order, primary first. Both providers are always shown; the setting
// only decides which one takes the left column.
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

function primaryUsage(account) {
    var window = account && (account.windows || [])[0];
    return window && typeof window.used === "number" && isFinite(window.used) ? window.used : null;
}

function barAccounts(codex, claude) {
    var known = [codex, claude].filter(function(a) { return primaryUsage(a) !== null; });
    var active = known.filter(function(a) { return primaryUsage(a) > 0; });
    return active.length ? active : known;
}


function overPace(account, now) {
    if (!account || account.status !== "ok") return false;
    var pacing = pace((account.windows || [])[0], now);
    return pacing !== null && pacing.delta >= 2;
}

function planLabel(plan) {
    return String(plan || "").replace(/_/g, " ").replace(/\b[a-z]/g, function(c) { return c.toUpperCase(); });
}

// A 185px column cannot hold "Default Claude Max 5x" next to the provider name
// it already repeats, so drop the redundant words and keep the plan itself.
function shortPlan(plan, name) {
    var text = planLabel(plan);
    if (name)
        text = text.replace(new RegExp("\\b" + name + "\\b", "i"), "");
    return text.replace(/^\s*Default\b/i, "").replace(/\s+/g, " ").trim();
}

// Window labels lose their "window" suffix in the columns; the full label stays
// in the row tooltip and the accessible name.
function shortWindow(label) {
    return String(label || "").replace(/\s*window$/i, "").replace(/(\d+)\s*days$/i, "$1d").trim();
}

// Model ids carry a release date that means nothing at this width.
function modelLabel(name) {
    return String(name || "").replace(/\s*\b20\d{6}\b\s*$/, "").trim();
}

function nearLimit(window) {
    return !!window && typeof window.used === "number" && isFinite(window.used) && window.used >= 90;
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

// The column repeats "resets in" once per provider at most, so the rows carry
// the bare duration.
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

// One header, two providers: report the oldest fetch, so the age never claims
// to be fresher than the stalest column on screen.
function latestUpdate(snapshot) {
    var stamps = (snapshot.accounts || []).map(function(a) { return a.updatedAt; })
        .filter(function(t) { return typeof t === "number" && isFinite(t); });
    return stamps.length ? Math.min.apply(null, stamps) : null;
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
    // Both the pill and the initial popout show the highest primary utilization.
    // Keep source order intact for the account selector, including tied/unknown meters.
    var selected = null;
    var highest = -1;
    accounts.forEach(function(account) {
        var primary = (account.windows || [])[0];
        var used = primary && typeof primary.used === "number" ? primary.used : -1;
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
