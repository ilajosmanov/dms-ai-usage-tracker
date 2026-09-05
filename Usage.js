.pragma library

// Everything provider-specific lives in this one table. Provider identity is
// intentionally stable across themes and usage levels.
var PROVIDERS = [
    {id: "codex", label: "Codex", accent: "#10A37F",
     dashboard: "https://chatgpt.com/codex/settings/usage"},
    {id: "claude", label: "Claude", accent: "#D97757",
     dashboard: "https://claude.ai/settings/usage"}
];

function brand(provider) {
    return PROVIDERS.filter(function(p) { return p.id === provider; })[0] || PROVIDERS[0];
}

function accent(provider) {
    return brand(provider).accent;
}

function tabs() {
    return PROVIDERS.map(function(p) { return {id: p.id, label: p.label}; });
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

function ringSegments(codex, claude) {
    var accounts = barAccounts(codex, claude).filter(function(a) { return primaryUsage(a) > 0; });
    var total = accounts.reduce(function(sum, a) { return sum + primaryUsage(a); }, 0);
    var start = -Math.PI / 2;
    if (!total)
        return [{provider: "", used: null, share: 0, start: start, sweep: Math.PI * 2, stale: false}];
    return accounts.map(function(a) {
        // Relative quota percentages, not token totals or a combined allowance.
        var share = primaryUsage(a) / total;
        var segment = {provider: a.provider, used: primaryUsage(a), share: share,
            stale: a.status === "stale", start: start, sweep: Math.PI * 2 * share};
        start += segment.sweep;
        return segment;
    });
}

function overPace(account, now) {
    if (!account || account.status !== "ok") return false;
    var pacing = pace((account.windows || [])[0], now);
    return pacing !== null && pacing.delta >= 2;
}

function planLabel(plan) {
    return String(plan || "").replace(/_/g, " ").replace(/\b[a-z]/g, function(c) { return c.toUpperCase(); });
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

function stringList(value) {
    if (!value || typeof value.length !== "number") return [];
    var result = [];
    for (var i = 0; i < value.length; i++) {
        if (typeof value[i] === "string" && value[i] !== "")
            result.push(value[i]);
    }
    return result;
}

function days(history, now, modelsByDay) {
    var result = [];
    var today = new Date(now);
    for (var offset = 6; offset >= 0; offset--) {
        var date = new Date(today.getFullYear(), today.getMonth(), today.getDate() - offset);
        var key = date.getFullYear() + "-" + ("0" + (date.getMonth() + 1)).slice(-2) + "-" + ("0" + date.getDate()).slice(-2);
        var match = (history || []).filter(function(h) { return h.date === key; })[0];
        var models = stringList(modelsByDay ? modelsByDay[key] : null);
        result.push({date: key, label: ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"][date.getDay()],
            value: match ? match.value : null, models: models});
    }
    return result;
}

function dayTooltip(day) {
    var peak = day && day.value !== null && typeof day.value === "number" ? Math.round(day.value) + "% peak" : "No usage sample";
    var names = stringList(day ? day.models : null);
    var models = names.length ? names.join(", ") : "Not observed locally";
    return (day ? day.date : "") + " · " + peak + "\nModels · " + models;
}
