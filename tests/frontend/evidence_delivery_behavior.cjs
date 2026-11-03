const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

class Element {
    constructor(tag = 'div') {
        this.tagName = tag;
        this.children = [];
        this.dataset = {};
        this.listeners = {};
        this.hidden = true;
        this.disabled = false;
        this.attributes = {};
        this.textContent = '';
        this.value = '';
    }
    append(...nodes) { this.children.push(...nodes); }
    replaceChildren(...nodes) { this.children = nodes; }
    addEventListener(name, handler) { this.listeners[name] = handler; }
    setAttribute(name, value) { this.attributes[name] = value; }
    removeAttribute(name) { delete this.attributes[name]; }
    scrollIntoView() {}
    focus() {}
}

function harness(file, fetch) {
    const nodes = new Map();
    const get = (id) => {
        if (!nodes.has(id)) nodes.set(id, new Element());
        return nodes.get(id);
    };
    get('feishuDelivery').dataset.taskId = 'task-1';
    const document = { hidden: false, getElementById: get,
        createElement: (tag) => new Element(tag), createTextNode: (text) => ({ textContent: text }),
        addEventListener() {},
    };
    const listeners = {};
    const timers = [];
    const documentListeners = {};
    let now = 0;
    document.addEventListener = (name, handler) => { documentListeners[name] = handler; };
    const window = { LearnFluxAuth: { ready: Promise.resolve() },
        addEventListener: (name, handler) => { listeners[name] = handler; },
        setTimeout: (handler, delay) => { timers.push({ handler, delay }); return timers.length; },
        clearTimeout(id) { if (timers[id - 1]) timers[id - 1].cancelled = true; },
    };
    const context = { window, document, fetch, URL, URLSearchParams, AbortController, console, Date: { now: () => now } };
    vm.runInNewContext(fs.readFileSync(file, 'utf8'), context);
    return { get, window, timers, listeners, document, documentListeners,
        pendingTimers: () => timers.filter(item => !item.cancelled && !item.fired),
        async fireNext() {
            const timer = timers.find(item => !item.cancelled && !item.fired);
            assert.ok(timer, 'Expected a scheduled delivery check');
            timer.fired = true;
            now += timer.delay;
            await timer.handler();
            await new Promise(setImmediate);
        },
    };
}

const response = (data, ok = true) => ({ ok, json: async () => ({ data }) });
const tick = () => new Promise(setImmediate);
function descendants(node) { return [node, ...(node.children || []).flatMap(descendants)]; }

async function main() {
    {
        const calls = [];
        const h = harness('src/web/static/js/history-evidence.js', async (url, options) => {
            calls.push({ url, ...options });
            return response({ answer: '**Answer** <script>unsafe</script>', sources: [
                { id: 'S1', view_token: 'a', title: '<img src=x>', passages: [
                    { id: 'P1', label: '12:34', line_id: 'line-123', start_seconds: 754, text: '<img onerror=alert(1)>' },
                ].concat(Array.from({ length: 11 }, (_, i) => ({ id: `P${i + 2}`, label: `Paragraph ${i + 2}`, line_id: `line-${i + 2}`, text: 'Evidence' }))) },
                { id: 'S3', view_token: 'outside-selection', title: 'Not selected', passages: [] },
            ] });
        });
        h.window.LearnFluxEvidence.open(['a'], []);
        assert.equal(h.get('historyEvidence').hidden, true);
        h.window.LearnFluxEvidence.open(['a', 'b'], [{ view_token: 'a', title: 'A' }]);
        h.get('historyEvidenceQuestion').value = 'Compare the methods';
        await h.get('historyEvidenceForm').listeners.submit({ preventDefault() {} });
        assert.deepEqual(JSON.parse(calls[0].body).view_tokens, ['a', 'b']);
        assert.equal(calls[0].url, '/api/study/compare');
        const all = descendants(h.get('historyEvidenceSources'));
        assert.equal(all.filter(node => node.tagName === 'details').length, 1);
        assert.equal(all.some(node => node.tagName === 'img' || node.tagName === 'script'), false);
        assert.equal(all.find(node => node.tagName === 'a').href, '/study/a?visual_line_id=line-123&visual_start=754');
        assert.equal(all.filter(node => node.tagName === 'a').length, 12);
        assert.match(all.filter(node => node.tagName === 'a').at(-1).textContent, /S1\/P12/);
        assert.equal(h.get('historyEvidenceSubmit').disabled, false);
        assert.equal(descendants(h.get('historyEvidenceAnswer')).some(node => node.tagName === 'strong'), true);
    }
    {
        // A citation from a later retrieved passage remains available in single-study answers.
        const source = fs.readFileSync('src/web/static/js/study.js', 'utf8');
        const start = source.indexOf('    function renderChatEvidence(');
        const end = source.indexOf('    function bindRovingTabKeys(', start);
        assert.ok(start >= 0 && end > start);
        const passages = Array.from({ length: 12 }, (_, i) => ({ id: `P${i + 1}`, label: `Paragraph ${i + 1}`, line_id: `line-${i + 1}`, text: 'Original evidence' }));
        const html = vm.runInNewContext(source.slice(start, end) + '\nrenderChatEvidence({passages});', { passages });
        assert.match(html, /原文依据 · 12 段/);
        assert.match(html, /data-evidence-line="line-12"/);
        assert.match(html, /P12 · Paragraph 12/);
    }
    {
        let finish;
        const h = harness('src/web/static/js/history-evidence.js', () => new Promise(resolve => { finish = resolve; }));
        h.window.LearnFluxEvidence.open(['a', 'b'], []);
        h.get('historyEvidenceQuestion').value = 'Private question';
        const pending = h.get('historyEvidenceForm').listeners.submit({ preventDefault() {} });
        await tick();
        h.listeners['learnflux:authchange']();
        finish(response({ answer: 'Previous owner result', sources: [] }));
        await pending;
        assert.equal(h.get('historyEvidence').hidden, true);
        assert.equal(h.get('historyEvidenceAnswer').children.length, 0);
        assert.equal(h.get('historyEvidenceSubmit').disabled, false);
    }
    {
        let data = { state: 'done', label: 'Delivered', document_url: 'https://my.feishu.cn/docx/example', can_retry: false };
        const h = harness('src/web/static/js/feishu-delivery.js', async () => response(data));
        await tick();
        assert.equal(h.get('feishuDelivery').hidden, false);
        assert.equal(h.get('feishuDeliveryOpen').href, data.document_url);
        assert.equal(h.get('feishuDeliveryRetry').hidden, true);
    }
    {
        const h = harness('src/web/static/js/feishu-delivery.js', async () => response({ state: 'unavailable' }));
        await tick();
        assert.equal(h.get('feishuDelivery').hidden, true);
    }
    {
        let retries = 0;
        let finish;
        const h = harness('src/web/static/js/feishu-delivery.js', async (url, options) => {
            if (options?.method === 'POST') {
                retries += 1;
                return new Promise(resolve => { finish = resolve; });
            }
            return response({ state: 'needs_attention', label: 'Needs attention', can_retry: true, document_url: 'javascript:alert(1)' });
        });
        await tick();
        assert.equal(h.get('feishuDeliveryOpen').hidden, true);
        assert.equal(h.get('feishuDeliveryRetry').hidden, false);
        const first = h.get('feishuDeliveryRetry').listeners.click();
        await h.get('feishuDeliveryRetry').listeners.click();
        assert.equal(retries, 1);
        finish(response({ state: 'pending', label: 'Queued', can_retry: false }));
        await first;
        assert.equal(h.get('feishuDeliveryRetry').disabled, false);
        assert.equal(h.timers.at(-1).delay, 10000);
    }
    {
        // The retry endpoint returns the old attention state until the worker runs.
        let delivered = false;
        let reads = 0;
        const h = harness('src/web/static/js/feishu-delivery.js', async (url, options) => {
            if (options?.method !== 'POST') reads += 1;
            return response(delivered ? { state: 'done', label: 'Delivered' }
                : { state: 'needs_attention', label: 'Old readback mismatch', can_retry: true });
        });
        await tick();
        await h.get('feishuDeliveryRetry').listeners.click();
        assert.equal(h.get('feishuDeliveryLabel').textContent, '已安排重新同步');
        assert.equal(h.pendingTimers().length, 1);
        await h.fireNext();
        assert.equal(reads, 2);
        delivered = true;
        await h.fireNext();
        assert.equal(h.get('feishuDeliveryLabel').textContent, 'Delivered');
        assert.equal(h.pendingTimers().length, 0);
    }
    {
        // Even a still-running retry stops background checks after ninety seconds.
        let retried = false;
        const h = harness('src/web/static/js/feishu-delivery.js', async (url, options) => {
            if (options?.method === 'POST') retried = true;
            return response(retried ? { state: 'pending', label: 'Queued' }
                : { state: 'needs_attention', can_retry: true });
        });
        await tick();
        await h.get('feishuDeliveryRetry').listeners.click();
        for (let i = 0; i < 9; i += 1) await h.fireNext();
        assert.equal(h.pendingTimers().length, 0);
    }
    {
        let fail = false;
        const h = harness('src/web/static/js/feishu-delivery.js', async () => {
            if (fail) throw new Error('Network unavailable');
            return response({ state: 'verifying', label: 'Verifying' });
        });
        await tick();
        fail = true;
        await h.fireNext();
        assert.match(h.get('feishuDeliveryDetail').textContent, /稍后会再次检查/);
        assert.equal(h.pendingTimers().length, 1);
        for (let i = 0; i < 9; i += 1) await h.fireNext();
        assert.equal(h.pendingTimers().length, 0);
        assert.match(h.get('feishuDeliveryDetail').textContent, /刷新页面/);
    }
    {
        let finish;
        let reads = 0;
        const h = harness('src/web/static/js/feishu-delivery.js', () => {
            reads += 1;
            if (reads === 1) return new Promise(resolve => { finish = resolve; });
            return Promise.resolve(response({ state: 'unavailable' }));
        });
        await tick();
        h.listeners['learnflux:authchange']({ detail: { authenticated: true } });
        await tick();
        finish(response({ state: 'done', label: 'Previous owner delivery', document_url: 'https://my.feishu.cn/docx/private' }));
        await tick();
        assert.equal(reads, 2);
        assert.equal(h.get('feishuDelivery').hidden, true);
        assert.notEqual(h.get('feishuDeliveryLabel').textContent, 'Previous owner delivery');
        assert.equal(h.get('feishuDeliveryOpen').hidden, true);
        assert.equal(h.pendingTimers().length, 0);
    }
    console.log('Evidence and delivery browser behavior checks passed');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
