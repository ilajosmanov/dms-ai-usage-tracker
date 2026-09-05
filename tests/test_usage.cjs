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

test('daily bars carry that date models into their hover text', () => {
    const date = usage.days([], now, {})[6].date;
    const days = usage.days([{date, value: 42}], now, {[date]: ['GPT-6 Astra', 'GPT-5.6 Sol']});
    assert.equal(days[6].models.join(','), 'GPT-6 Astra,GPT-5.6 Sol');
    assert.equal(usage.dayTooltip(days[6]), `${date} · 42% peak\nModels · GPT-6 Astra, GPT-5.6 Sol`);
    assert.equal(usage.dayTooltip(usage.days([], now, {})[6]), `${date} · No usage sample\nModels · Not observed locally`);
});

test('only the consuming provider owns the full ring and percentage', () => {
    for (const provider of ['codex', 'claude']) {
        const codex = account('codex', provider === 'codex' ? 37 : 0);
        const claude = account('claude', provider === 'claude' ? 56 : 0);
        const segments = usage.ringSegments(codex, claude);
        assert.equal(segments.length, 1);
        assert.equal(segments[0].provider, provider);
        assert.equal(segments[0].share, 1, 'one consumer owns the entire circle regardless of utilization');
        assert.equal(segments[0].sweep, 2 * Math.PI, 'single-provider ring fills clockwise');
        assert.equal(segments[0].start, -Math.PI / 2, 'single-provider ring starts at the top');
        assert.equal(usage.barAccounts(codex, claude).map(a => a.provider).join(','), provider);
    }
});
test('ring segments are proportional to quota percentages and cover the whole circle', () => {
    const segments = usage.ringSegments(account('codex', 60), account('claude', 20));
    assert.equal(segments.length, 2);
    assert.equal(segments[0].share, 0.75);
    assert.equal(segments[1].share, 0.25);
    assert.equal(segments[0].start, -Math.PI / 2);
    assert.equal(segments[0].sweep, Math.PI * 1.5);
    assert.equal(segments[1].start, segments[0].start + segments[0].sweep);
    assert.equal(segments[0].sweep + segments[1].sweep, Math.PI * 2);
    assert.equal(usage.percent({used: segments[0].used}), '60%', 'numeric quota percentages stay unchanged');
    assert.equal(usage.percent({used: segments[1].used}), '20%');
});
test('equal usage splits equally; fractional usage is not rounded away', () => {
    const equal = usage.ringSegments(account('codex', 12), account('claude', 12));
    assert.equal(equal[0].share, 0.5);
    assert.equal(equal[1].share, 0.5);
    const tiny = usage.ringSegments(account('codex', 0.2), account('claude', 0.6, 'stale'));
    assert.equal(tiny[0].share, 0.25);
    assert.ok(Math.abs(tiny[1].share - 0.75) < 1e-12);
    assert.equal(tiny[1].stale, true);
});
test('reset transitions from split back to the remaining provider', () => {
    const codex = account('codex', 50), claude = account('claude', 50);
    assert.equal(usage.ringSegments(codex, claude).length, 2);
    codex.windows[0].used = 0;
    assert.equal(usage.ringSegments(codex, claude)[0].provider, 'claude');
    assert.equal(usage.ringSegments(codex, claude).length, 1);
});
test('idle and unavailable providers never produce a split or fabricated usage', () => {
    for (const pair of [[account('codex', 0), account('claude', 0)], [{windows: []}, {windows: []}]]) {
        const segments = usage.ringSegments(...pair);
        assert.equal(segments.length, 1);
        assert.equal(segments[0].provider, '');
    }
    assert.equal(usage.percent({used: NaN}), '—');
    assert.equal(usage.percent({used: Infinity}), '—');
    assert.equal(usage.barAccounts(account('codex', NaN), account('claude', 0)).length, 1);
    assert.equal(usage.percent({used: 0.2}), '<1%');
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
