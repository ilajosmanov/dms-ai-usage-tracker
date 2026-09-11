const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const usage = vm.createContext({});
vm.runInContext(fs.readFileSync(path.join(__dirname, '../Usage.js'), 'utf8').replace(/^\.pragma library\s*/, ''), usage);
const now = 1900000000000;
function account(provider, used, status = 'ok') {
    return { provider, status, windows: [{ used, duration: 1000, resetAt: now / 1000 + 500 }] };
}

test('provider accents always use their brand colors', () => {
    assert.equal(usage.accent('codex'), '#10A37F');
    assert.equal(usage.accent('claude'), '#D97757');
    assert.equal(usage.accent('unknown'), '#10A37F', 'an unknown provider still gets a stable color');
});

test('daily bars report their peak, and nothing they did not sample', () => {
    const date = usage.days([], now)[6].date;
    const days = usage.days([{date, value: 42}], now);
    assert.equal(usage.dayTooltip(days[6]), `${date} · 42% peak`);
    assert.equal(usage.dayTooltip(usage.days([], now)[6]), `${date} · No usage sample`);
});

test('token counts shorten without losing their magnitude', () => {
    assert.equal(usage.tokens(1632925607), '1.6B');
    assert.equal(usage.tokens(80700000), '80.7M');
    assert.equal(usage.tokens(334800), '334.8K');
    assert.equal(usage.tokens(512), '512');
    for (const bad of [null, undefined, NaN, Infinity, -1, 'x'])
        assert.equal(usage.tokens(bad), '—');
});

test('model bars scale against the busiest model and drop what was not observed', () => {
    const bars = usage.modelBars({models: [
        {name: 'GPT-5.6 Sol', tokens: 1000},
        {name: 'GPT-6 Astra', tokens: 250},
        {name: 'GPT-5.6 Luna', tokens: 0},
        {name: '', tokens: 900},
        {name: 'Bad', tokens: 'lots'},
    ]});
    assert.equal(bars.map(b => b.name).join(','), 'GPT-5.6 Sol,GPT-6 Astra');
    assert.equal(bars[0].share, 1);
    assert.equal(bars[1].share, 0.25);
    assert.equal(bars[1].label, '250');
    assert.equal(usage.modelBars({}).length, 0);
    assert.equal(usage.modelBars(null).length, 0);
});

// Windows arrive shortest-first, which is the order the rows are drawn in and
// exactly the wrong order to read a headline from.
function claudeAccount(session, weekly, scoped) {
    return {provider: 'claude', status: 'ok', windows: [
        {id: 'five_hour', label: '5-hour window', used: session, duration: 18000,
         resetAt: now / 1000 + 17000, severity: 'normal', active: false},
        {id: 'seven_day', label: '7-day window', used: weekly, duration: 604800,
         resetAt: now / 1000 + 150000, severity: 'warning', active: false},
        {id: 'weekly_scoped:fable', label: 'Fable · 7 days', used: scoped, duration: 604800,
         resetAt: now / 1000 + 150000, severity: 'critical', active: true},
    ]};
}

test('the headline window is the fullest one, not the shortest', () => {
    // A session window that just rolled over is 0% and says nothing about the
    // weekly quota it sits next to.
    const rolled = claudeAccount(0, 76, 97);
    assert.equal(usage.primaryWindow(rolled).id, 'weekly_scoped:fable');
    assert.equal(usage.primaryUsage(rolled), 97);
    const burning = claudeAccount(88, 40, 12);
    assert.equal(usage.primaryWindow(burning).id, 'five_hour',
        'a session about to run out is the headline too, when it is the fullest');
    assert.equal(usage.primaryUsage(burning), 88);
});

test('a provider verdict breaks ties and never outranks a fuller meter', () => {
    const account = claudeAccount(0, 90, 60);
    assert.equal(usage.primaryWindow(account).id, 'seven_day',
        'critical and active must not beat a plainly fuller window');
    const tied = claudeAccount(0, 60, 60);
    assert.equal(usage.primaryWindow(tied).id, 'weekly_scoped:fable',
        "equally full, the service's own flags decide");
    const flat = {windows: [
        {id: 'long', used: 50, duration: 604800},
        {id: 'short', used: 50, duration: 18000},
    ]};
    assert.equal(usage.primaryWindow(flat).id, 'short',
        'with no flags at all, the shorter window binds first');
});

test('windows without a usable number are skipped, never headlined', () => {
    const partial = {windows: [{id: 'broken', used: NaN, duration: 18000},
                               {id: 'real', used: 44, duration: 604800}]};
    assert.equal(usage.primaryWindow(partial).id, 'real');
    assert.equal(usage.primaryUsage(partial), 44);
    // Nothing measurable at all: still name a limit rather than going blank.
    const unknown = {windows: [{id: 'broken', label: '5-hour window', used: null}]};
    assert.equal(usage.primaryWindow(unknown).id, 'broken');
    assert.equal(usage.primaryUsage(unknown), null);
    assert.equal(usage.primaryWindow({windows: []}), undefined);
    assert.equal(usage.primaryUsage(null), null);
});

test('the bar charts the shortest window, whatever the week is doing', () => {
    // The shape that made this worth separating: an idle session beside a week
    // that is nearly spent. The panel still headlines the week; the bar does not.
    const rolled = claudeAccount(0, 76, 97);
    assert.equal(usage.barWindow(rolled).id, 'five_hour');
    assert.equal(usage.barUsage(rolled), 0);
    assert.equal(usage.primaryWindow(rolled).id, 'weekly_scoped:fable',
        'the limiting window is unchanged by where the bar looks');
    // Ties on length never happen for Claude, but a provider could report two
    // weeks and nothing shorter; the first one reported wins and stays put.
    const weeksOnly = {windows: [
        {id: 'seven_day', used: 12, duration: 604800},
        {id: 'weekly_scoped:fable', used: 96, duration: 604800},
    ]};
    assert.equal(usage.barWindow(weeksOnly).id, 'seven_day');
    // A window with no length cannot be the shortest, even when it is the only
    // one carrying a reading.
    const unlabelled = {windows: [{id: 'no-duration', used: 44},
                                  {id: 'week', used: 9, duration: 604800}]};
    assert.equal(usage.barWindow(unlabelled).id, 'week');
    // Nothing measurable with a length at all: fall back rather than go blank.
    const shapeless = {windows: [{id: 'broken', used: 51}]};
    assert.equal(usage.barWindow(shapeless).id, 'broken');
    assert.equal(usage.barUsage(shapeless), 51);
    assert.equal(usage.barWindow({windows: []}), undefined);
    assert.equal(usage.barUsage(null), null);
});

test('pace and account choice each follow their own window', () => {
    // 6% into the session with nothing spent in it: under pace, however close
    // the week beside it is to its wall.
    assert.equal(usage.overPace(claudeAccount(0, 76, 97), now), false,
        'the arrow belongs to the number it sits against');
    assert.equal(usage.overPace(claudeAccount(88, 2, 1), now), true);
    const accounts = [claudeAccount(30, 10, 5), claudeAccount(0, 20, 95)];
    assert.equal(usage.representativeAccount(accounts), accounts[1],
        'the picker opens on the account closest to a wall, whichever window that is');
});

test('a provider calling a window critical is enough to earn caution', () => {
    assert.equal(usage.nearLimit({used: 62, severity: 'critical'}), true);
    assert.equal(usage.nearLimit({used: 62, severity: 'warning'}), false);
    assert.equal(usage.nearLimit({used: 91}), true, 'the number alone still earns it');
    assert.equal(usage.nearLimit({used: NaN, severity: 'critical'}), true);
    assert.equal(usage.nearLimit(null), false);
});

test('the daily peak names the window it charts', () => {
    assert.equal(usage.historyLabel([{value: 3, duration: 18000}]), 'Daily peak · 5-hour');
    assert.equal(usage.historyLabel([{value: 3, duration: 604800}]), 'Daily peak · 7-day');
    // A series written before durations were recorded claims nothing it cannot back.
    assert.equal(usage.historyLabel([{value: 3, window: 'primary'}]), 'Daily peak');
    assert.equal(usage.historyLabel([]), 'Daily peak');
    assert.equal(usage.historyLabel(null), 'Daily peak');
});

test('providers with known usage keep their meters even at zero', () => {
    for (const provider of ['codex', 'claude']) {
        const codex = account('codex', provider === 'codex' ? 37 : 0);
        const claude = account('claude', provider === 'claude' ? 56 : 0);
        assert.equal(usage.barAccounts(codex, claude).map(a => a.provider).join(','), 'codex,claude');
    }
    assert.equal(usage.barAccounts(account('codex', 60), account('claude', 20)).length, 2,
        'two consumers get two bars');
    assert.equal(usage.barAccounts(account('codex', 0), account('claude', 0)).length, 2,
        'a pair of known-idle accounts still reports both, at zero');
    assert.equal(usage.barAccounts({windows: []}, {windows: []}).length, 0);
    assert.equal(usage.barAccounts(account('codex', NaN), account('claude', 0)).length, 1);
    // A provider reporting only a week still gets a bar; there is no shorter
    // window to insist on.
    assert.equal(usage.barAccounts({provider: 'codex', status: 'ok',
        windows: [{id: 'primary_window', used: 64, duration: 604800}]}, {windows: []}).length, 1);
});

test('percentages stay honest at both ends of the scale', () => {
    assert.equal(usage.percent({used: 60}), '60%');
    assert.equal(usage.percent({used: 0.2}), '<1%');
    assert.equal(usage.percent({used: NaN}), '—');
    assert.equal(usage.percent({used: Infinity}), '—');
});

test('brand fills never change; brand text darkens only on a light surface', () => {
    assert.equal(usage.accentText('codex', false), '#10A37F', 'dark mode keeps the brand hex');
    assert.equal(usage.accentText('claude', false), '#D97757');
    assert.equal(usage.accentText('codex', true), '#0B8368');
    assert.equal(usage.accentText('claude', true), '#B65A3C');
    assert.equal(usage.accent('codex'), usage.brand('codex').accent, 'fills always use the brand color');
});

test('both providers are always shown, primary first', () => {
    // Arrays cross the vm realm boundary, so compare their contents.
    assert.equal(usage.orderedProviders('codex').join(','), 'codex,claude');
    assert.equal(usage.orderedProviders('claude').join(','), 'claude,codex');
    assert.equal(usage.orderedProviders('').join(','), 'codex,claude', 'an unset setting keeps source order');
    assert.equal(usage.orderedProviders('gemini').join(','), 'codex,claude');
});

test('column labels shorten without inventing or losing meaning', () => {
    assert.equal(usage.shortWindow('5-hour window'), '5-hour');
    assert.equal(usage.shortWindow('7-day window'), '7-day');
    assert.equal(usage.shortWindow('Fable · 7 days'), 'Fable · 7d');
    assert.equal(usage.shortWindow(''), '');
    assert.equal(usage.shortPlan('default claude max 5x', 'Claude'), 'Max 5x');
    assert.equal(usage.shortPlan('pro', 'Codex'), 'Pro');
    assert.equal(usage.shortPlan('business_plan', 'Codex'), 'Business Plan');
    assert.equal(usage.shortPlan('', 'Codex'), '');
    assert.equal(usage.modelLabel('Claude Haiku 4 5 20251001'), 'Claude Haiku 4 5');
    assert.equal(usage.modelLabel('GPT-5.6 Sol'), 'GPT-5.6 Sol');
});

test('a near-limit window is called out separately from an over-pace one', () => {
    assert.equal(usage.nearLimit({used: 90}), true);
    assert.equal(usage.nearLimit({used: 89.4}), false);
    assert.equal(usage.nearLimit({used: NaN}), false);
    assert.equal(usage.nearLimit(null), false);
    assert.equal(usage.overPace(account('codex', 95), now), true,
        'the two signals are independent, and can both be true');
});

test('a backed-off column cannot freeze the header clock for the live one', () => {
    const live = {status: 'ok', updatedAt: 500};
    const saved = {status: 'stale', updatedAt: 200};
    assert.equal(usage.latestUpdate({accounts: [live, saved]}), 500,
        'a refresh that did update Codex must not still read as 5m ago because Claude is rate limited');
    assert.equal(usage.latestUpdate({accounts: [saved, {status: 'stale', updatedAt: 400}]}), 400,
        'with nothing live the header falls back to the newest saved check');
    assert.equal(usage.latestUpdate({accounts: [{updatedAt: 500}, {}]}), 500);
    assert.equal(usage.latestUpdate({accounts: []}), null);
    assert.equal(usage.latestUpdate({}), null);
    assert.equal(usage.age(null, now), 'Never synced');
});

test('a saved column dates itself, since the header no longer does it for them', () => {
    assert.equal(usage.savedAge(now / 1000 - 900, now), '15m old');
    assert.equal(usage.savedAge(now / 1000 - 20, now), 'under 1m old');
    assert.equal(usage.savedAge(now / 1000 - 7500, now), '2h old');
    assert.equal(usage.savedAge(null, now), '');
});

test('a reading taken by a client is attributed to that client, never to us', () => {
    assert.equal(usage.originNote({origin: 'Codex', updatedAt: now / 1000 - 120}, now), 'via Codex · 2m old');
    assert.equal(usage.originNote({origin: 'Claude Code', updatedAt: now / 1000 - 20}, now),
        'via Claude Code · under 1m old');
    assert.equal(usage.originNote({origin: '', updatedAt: now / 1000}, now), '',
        'a check we made ourselves needs no attribution');
    assert.equal(usage.originNote(null, now), '');
    assert.equal(usage.originNote({origin: 'Codex'}, now), 'via Codex', 'an undated reading is still attributed');
});

test('a column showing an older reading dates it and says whose it is', () => {
    assert.equal(usage.savedTitle({origin: 'Codex', updatedAt: now / 1000 - 300}, now),
        "Showing Codex's last check · 5m old");
    assert.equal(usage.savedTitle({updatedAt: now / 1000 - 2220}, now), 'Showing saved usage · 37m old',
        'our own saved check is not attributed to a client');
    assert.equal(usage.savedTitle({}, now), 'Showing saved usage');
});

test('a provider backoff reports its deadline without guessing authentication recovery', () => {
    assert.equal(usage.retryNote(now / 1000 + 3300, now), 'Next check in 55m.');
    assert.equal(usage.retryNote(now / 1000 + 3900, now), 'Next check in 1h 5m.');
    assert.equal(usage.retryNote(now / 1000 + 3600, now), 'Next check in 1h.');
    assert.equal(usage.retryNote(now / 1000 - 10, now), '', 'an expired backoff is not a wait');
    assert.equal(usage.retryNote(0, now), '');
    assert.equal(usage.retryNote(undefined, now), '');
});

test('row countdowns drop the prefix the header no longer repeats', () => {
    const window = {duration: 3600, resetAt: now / 1000 + 3600};
    assert.equal(usage.countdown(window.resetAt, now), 'Resets in 1h 0m');
    assert.equal(usage.resetShort(window.resetAt, now), '1h 0m');
    assert.equal(usage.resetShort(now / 1000 + 86400 * 6.9, now), '6d 21h');
    assert.equal(usage.resetShort(null, now), '—');
    assert.equal(usage.resetShort(now / 1000 - 10, now), '—');
});

test('each provider has its own pace warning, with unknown and stale data excluded', () => {
    assert.equal(usage.overPace(account('codex', 80), now), true);
    assert.equal(usage.overPace(account('claude', 70), now), true);
    assert.equal(usage.overPace(account('codex', 51), now), false);
    assert.equal(usage.overPace(account('codex', 52), now), true);
    assert.equal(usage.overPace(account('claude', 80, 'stale'), now), false);
    const missingReset = account('claude', 80);
    missingReset.windows[0].resetAt = null;
    assert.equal(usage.overPace(missingReset, now), false);
    assert.equal(usage.overPace(account('codex', 80), now + 600000), false);
});
test('plan labels capitalize words without breaking multipliers; client labels normalize', () => {
    assert.equal(usage.planLabel('pro'), 'Pro');
    assert.equal(usage.planLabel('max 5x'), 'Max 5x');
    assert.equal(usage.planLabel('business_plan'), 'Business Plan');
    assert.equal(usage.clientLabel('Codex + OpenCode + OMP'), 'Codex + opencode + OMP');
});
