/** Shared timestamp parsing and Beijing calendar/display rules. */
(function (root) {
    'use strict';
    const TIME_ZONE = 'Asia/Shanghai';
    const OFFSET_MS = 8 * 60 * 60 * 1000;

    function parse(value) {
        if (value instanceof Date) return value.getTime();
        if (typeof value === 'number') return Number.isFinite(value) ? value : NaN;
        if (typeof value !== 'string' || !value.trim()) return NaN;
        let text = value.trim().replace(' ', 'T');
        // Legacy database timestamps are UTC, even when their offset is absent.
        if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?$/.test(text)) text += 'Z';
        return Date.parse(text);
    }

    function format(value, options = {}) {
        const timestamp = parse(value);
        if (!Number.isFinite(timestamp)) return '';
        return new Intl.DateTimeFormat('zh-CN', { ...options, timeZone: TIME_ZONE }).format(timestamp);
    }

    function dateKey(value = Date.now()) {
        const timestamp = parse(value);
        return Number.isFinite(timestamp)
            ? new Date(timestamp + OFFSET_MS).toISOString().slice(0, 10) : '';
    }

    function shiftDate(key, days) {
        const date = new Date(key + 'T00:00:00Z');
        date.setUTCDate(date.getUTCDate() + days);
        return date.toISOString().slice(0, 10);
    }

    function startOfDay(value = Date.now()) {
        return Date.parse(dateKey(value) + 'T00:00:00+08:00');
    }

    const api = Object.freeze({ TIME_ZONE, parse, format, dateKey, shiftDate, startOfDay });
    root.LearnFluxTime = api;
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(globalThis);
