const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const time = require('../../src/web/static/js/time.js');
const { TaskHistoryManager, formatRelativeTime, inDateRange } = require('../../src/web/static/js/app.js');

if (!process.env.LEARNFLUX_TIME_CHILD) {
    for (const zone of ['Asia/Shanghai', 'UTC', 'America/Los_Angeles', 'Pacific/Kiritimati']) {
        const result = spawnSync(process.execPath, [__filename], {
            env: { ...process.env, TZ: zone, LEARNFLUX_TIME_CHILD: '1' }, encoding: 'utf8',
        });
        assert.equal(result.status, 0, `${zone}: ${result.stdout}${result.stderr}`);
    }
    console.log('PASS: Beijing time behavior in four host timezones');
} else {
    const now = Date.parse('2026-10-21T16:00:30Z');
    Date.now = () => now;
    const legacyUTC = '2026-10-21 16:00:00';
    for (const value of [legacyUTC, '2026-10-21T16:00:00', '2026-10-21T16:00:00Z',
        '2026-10-21T16:00:00.000000', '2026-10-21T16:00:00+00:00',
        '2026-10-22T00:00:00+08:00', '2026-10-21T11:00:00-05:00']) {
        const entry = TaskHistoryManager.serverTaskToHistoryEntry({ created_at: value, task_id: 'recent' });
        assert.equal(now - entry.timestamp, 30_000, value);
        assert.equal(formatRelativeTime(entry.timestamp), '刚刚', value);
        assert.equal(time.dateKey(value), '2026-10-22', value);
        assert.equal(time.format(value, { hour: '2-digit', minute: '2-digit', hour12: false }), '00:00');
    }
    assert.equal(time.dateKey(), '2026-10-22');
    assert.equal(time.dateKey('2026-10-21T15:59:59Z'), '2026-10-21');
    assert.equal(time.shiftDate('2026-01-01', -1), '2025-12-31');
    assert.equal(time.shiftDate('2024-03-01', -1), '2024-02-29');
    assert.equal(inDateRange(time.parse('2026-10-21 16:00:00'), 'today'), true);
    assert.equal(inDateRange(time.parse('2026-10-21 15:59:59'), 'today'), false);
    assert.equal(time.startOfDay(), now - 30_000);
    assert.equal(time.format('invalid'), '');
    assert.equal(time.format(null), '');
    assert.ok(Number.isNaN(time.parse(null)));
    assert.equal(TaskHistoryManager.timestampFromServer('invalid'), now);
    assert.equal(formatRelativeTime(now - 120_000), '2 分钟前');
    assert.equal(formatRelativeTime(now - 8 * 3600_000), '8 小时前');
    assert.equal(time.parse(0), 0);
}
