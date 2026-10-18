const assert = require('node:assert/strict');
const { UIManager, renderSubmittedTaskStatus, APIManager, initializeTranscriptionStrategy } = require('../../src/web/static/js/app.js');
class Element {
    constructor(tag) {
        this.tagName = tag.toUpperCase();
        this.children = [];
        this.attributes = {};
        this.style = {};
        this.textContent = '';
        this.className = '';
        this.open = false;
    }
    append(...nodes) { this.children.push(...nodes); }
    appendChild(node) { this.append(node); }
    prepend(...nodes) { this.children.unshift(...nodes); }
    replaceChildren(...nodes) { this.children = nodes; }
    setAttribute(key, value) { this.attributes[key] = value; }
    scrollIntoView() {}
    focus() { document.activeElement = this; }
    contains(node) { return this === node || this.children.some(child => child.contains(node)); }
    querySelector(selector) {
        return flatten(this).find(node => selector === '.task-status-meta[open]'
            ? node.className === 'task-status-meta' && node.open
            : node.className === selector.slice(1)) || null;
    }
}
const container = new Element('div');
const content = new Element('div');
container.id = 'status-container';
content.id = 'status-content';
container.append(content);
const flatten = node => [node, ...node.children.flatMap(flatten)];
global.document = {
    activeElement: null,
    createElement: tag => new Element(tag),
    createTextNode: text => Object.assign(new Element('#text'), { textContent: text }),
    getElementById: id => flatten(container).find(node => node.id === id) || null,
};
const nodes = () => flatten(content);
const texts = () => nodes().map(node => node.textContent).join('\n');
const render = (status, progress, extra = {}) => renderSubmittedTaskStatus(
    'test-task', 'token"><script>', { status, progress, ...extra }, null, false, { scroll: false },
);
(async () => {
    render('processing', { percent: 12, stage_label: '正在下载音视频', confidence: 'low' });
    assert.equal(nodes().find(node => node.tagName === 'PROGRESS').value, 12);
    assert.match(texts(), /正在下载音视频/);
    assert.match(texts(), /预估进度/);
    assert.equal(nodes().find(node => node.tagName === 'A').href, '/view/token%22%3E%3Cscript%3E');
    const meta = nodes().find(node => node.tagName === 'DETAILS');
    assert.equal(meta.open, false);
    meta.open = true;
    document.activeElement = nodes().find(node => node.tagName === 'A');
    render('processing', { percent: 40, stage_label: '正在转录' });
    assert.equal(nodes().find(node => node.tagName === 'DETAILS').open, true);
    assert.equal(document.activeElement, nodes().find(node => node.tagName === 'A'));
    assert.equal(container.className.includes('fade-in'), false);
    for (const percent of [undefined, null, '', 'bad']) {
        render('queued', { percent });
        assert.equal(nodes().some(node => node.tagName === 'PROGRESS'), false);
    }
    render('processing', { percent: 110 });
    assert.equal(nodes().find(node => node.tagName === 'PROGRESS').value, 100);
    const hostile = '<img src=x onerror=alert(1)>';
    render('failed', {}, { error_message: hostile });
    assert.match(texts(), /解析失败/);
    assert.equal(nodes().some(node => node.textContent === hostile), true);
    assert.equal(nodes().some(node => node.tagName === 'IMG'), false);
    assert.equal(document.getElementById('retry-local-asr'), null);
    const originalRetry = APIManager.retryASR;
    const originalSetTimeout = global.setTimeout;
    const timers = [];
    global.setTimeout = (callback, delay) => { timers.push({ callback, delay }); return timers.length; };
    const retries = [];
    APIManager.retryASR = async (...args) => { retries.push(args); };
    const retryProgress = { evidence: { retry_available: true } };
    render('failed', retryProgress);
    assert.match(texts(), /无需重新下载/);
    assert.equal(typeof document.getElementById('retry-local-asr').onclick, 'function');
    assert.equal(typeof document.getElementById('retry-cloud-asr').onclick, 'function');
    const localRetry = document.getElementById('retry-local-asr');
    await Promise.all([localRetry.onclick(), localRetry.onclick()]);
    assert.deepEqual(retries, [['test-task', 'local']]);
    assert.equal(timers.at(-1).delay, 2500);
    render('failed', retryProgress);
    await document.getElementById('retry-cloud-asr').onclick();
    assert.deepEqual(retries.at(-1), ['test-task', 'cloud']);
    assert.match(texts(), /正在解析/);
    render('cancelled', retryProgress);
    assert.equal(document.getElementById('retry-local-asr'), null);
    APIManager.retryASR = async () => { throw new Error('retry failed'); };
    render('failed', retryProgress);
    await document.getElementById('retry-local-asr').onclick();
    assert.match(texts(), /retry failed/);
    assert.equal(document.getElementById('retry-local-asr').disabled, undefined);
    APIManager.retryASR = originalRetry;
    global.setTimeout = originalSetTimeout;
    render('completed', {}, { title: hostile });
    assert.match(texts(), /查看结果/);
    assert.equal(nodes().some(node => node.tagName === 'PROGRESS'), false);
    assert.equal(nodes().some(node => node.tagName === 'IMG'), false);
    render('awaiting_cloud_confirmation', {});
    assert.match(texts(), /等待费用确认/);
    assert.equal(nodes().some(node => node.className === 'loading-spinner'), false);
    let confirmed = 0;
    let local = 0;
    APIManager.confirmCloudQuote = async (...args) => {
        assert.deepEqual(args, ['test-task', 'quote', '0.25']);
        confirmed++;
    };
    APIManager.useLocalForCloudQuote = async id => { assert.equal(id, 'test-task'); local++; };
    const quoteProgress = { evidence: { cloud_quote: {
        quote_token: 'quote', max_cost_cny: '0.25', duration_seconds: 60, billable_seconds: 60,
    } } };
    render('awaiting_cloud_confirmation', quoteProgress);
    assert.equal(confirmed, 0);
    assert.match(texts(), /预计费用 ¥0.25/);
    assert.doesNotMatch(texts(), /费用上限/);
    assert.equal(document.getElementById('refresh-cloud-quote'), null);
    await document.getElementById('confirm-cloud-quote').onclick();
    assert.equal(confirmed, 1);
    render('awaiting_cloud_confirmation', quoteProgress);
    await document.getElementById('use-local-quote').onclick();
    assert.equal(local, 1);
    for (const [code, nextCost] of [['quote_expired', '0.25'], ['quote_token_mismatch', '0.30'], ['quote_not_confirmable', '0.30']]) {
        let confirmationAttempts = 0;
        let statusRequests = 0;
        APIManager.confirmCloudQuote = async () => { confirmationAttempts++; throw new Error(code); };
        APIManager.getTaskStatus = async taskId => {
            assert.equal(taskId, 'test-task');
            statusRequests++;
            return { data: { status: 'awaiting_cloud_confirmation', progress: {
                evidence: { cloud_quote: { ...quoteProgress.evidence.cloud_quote,
                    quote_token: 'updated-quote', max_cost_cny: nextCost } }
            } } };
        };
        render('awaiting_cloud_confirmation', quoteProgress);
        await document.getElementById('confirm-cloud-quote').onclick();
        assert.equal(statusRequests, 1);
        assert.equal(confirmationAttempts, 1);
        assert.equal(texts().includes(`预计费用 ¥${nextCost}`), true);
        assert.match(texts(), /报价已更新，请确认预计费用/);
        assert.doesNotMatch(texts(), /quote_expired|quote_token_mismatch|quote_not_confirmable/);
        assert.equal(document.getElementById('refresh-cloud-quote'), null);
        APIManager.confirmCloudQuote = async (...args) => {
            assert.deepEqual(args, ['test-task', 'updated-quote', nextCost]);
            confirmationAttempts++;
        };
        await document.getElementById('confirm-cloud-quote').onclick();
        assert.equal(confirmationAttempts, 2);
    }
    APIManager.confirmCloudQuote = async () => { throw new Error('quote_expired'); };
    APIManager.getTaskStatus = async () => { throw new Error('network unavailable'); };
    render('awaiting_cloud_confirmation', quoteProgress);
    await document.getElementById('confirm-cloud-quote').onclick();
    assert.match(texts(), /报价暂时无法更新，请稍后重试/);
    assert.doesNotMatch(texts(), /quote_expired|network unavailable/);
    assert.equal(typeof document.getElementById('confirm-cloud-quote').onclick, 'function');
    UIManager.showStatus('error', hostile, hostile);
    assert.equal(nodes().some(node => node.tagName === 'IMG'), false);
    const storage = new Map();
    global.localStorage = {
        getItem: key => storage.get(key) || null,
        setItem: (key, value) => storage.set(key, value),
    };
    const inputs = ['local', 'cloud', 'local', 'cloud'].map(value => ({
        value, checked: false, addEventListener: (_, handler) => {},
    }));
    inputs.forEach(input => { input.addEventListener = (_, handler) => { input.onchange = handler; }; });
    document.querySelectorAll = () => inputs;
    initializeTranscriptionStrategy();
    assert.deepEqual(inputs.map(input => input.checked), [true, false, true, false]);
    inputs[3].checked = true;
    inputs[3].onchange();
    assert.equal(storage.get('vta_transcription_strategy'), '"cloud"');
    assert.deepEqual(inputs.map(input => input.checked), [false, true, false, true]);
    inputs.forEach(input => { input.checked = false; });
    initializeTranscriptionStrategy();
    assert.deepEqual(inputs.map(input => input.checked), [false, true, false, true]);
    storage.set('vta_transcription_strategy', '"invalid"');
    initializeTranscriptionStrategy();
    assert.deepEqual(inputs.map(input => input.checked), [true, false, true, false]);
    global.window = { LearnFluxAuth: {
        requireSession: async () => {}, getTokenPlaceholder: () => 'session-placeholder',
    } };
    let retryRequest;
    global.fetch = async (url, options) => {
        retryRequest = { url, options };
        return { ok: true, json: async () => ({ code: 202 }) };
    };
    assert.deepEqual(await APIManager.retryASR('task/id', 'cloud'), { code: 202 });
    assert.equal(retryRequest.url, '/api/task/task%2Fid/asr-retry');
    assert.equal(retryRequest.options.method, 'POST');
    assert.deepEqual(JSON.parse(retryRequest.options.body), { transcription_strategy: 'cloud' });
    global.fetch = async () => ({ ok: false, json: async () => ({ detail: 'audio expired' }) });
    await assert.rejects(APIManager.retryASR('task', 'local'), /audio expired/);
    console.log('Task status behavior checks passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
