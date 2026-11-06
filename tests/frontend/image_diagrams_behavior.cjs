const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

class Element {
    constructor(tag = 'div') {
        this.tagName = tag; this.children = []; this.dataset = {}; this.listeners = {};
        this.attributes = {}; this.hidden = false; this.disabled = false; this.value = '';
        this.textContent = ''; this.isConnected = true; this.open = false;
        this.style = {};
        const classes = new Set();
        this.classList = { toggle: (name, on) => { if (on) classes.add(name); else classes.delete(name); }, contains: (name) => classes.has(name) };
    }
    append(...children) {
        this.children.push(...children);
        if (this.tagName === 'select' && !this.value && children[0]) this.value = children[0].value;
    }
    replaceChildren(...children) { this.children = []; this.value = ''; this.append(...children); }
    addEventListener(name, handler) { this.listeners[name] = handler; }
    setAttribute(name, value) { this.attributes[name] = String(value); }
    getAttribute(name) { return this.attributes[name] || null; }
    removeAttribute(name) { delete this.attributes[name]; }
    get options() { return this.children; }
    set src(value) { this.attributes.src = value; }
    get src() { return this.attributes.src || ''; }
    focus() { this.focused = true; }
    showModal() { this.open = true; }
    close() { this.open = false; if (this.listeners.close) this.listeners.close(); }
}
function Option(text, value) { const option = new Element('option'); option.textContent = text; option.value = value; return option; }
function descendants(root) { return [root, ...root.children.flatMap(descendants)]; }
function visibleDescendants(root) {
    if (root.hidden || root.tagName === 'dialog' && !root.open) return [];
    const children = root.tagName === 'details' && !root.open
        ? root.children.filter((child) => child.tagName === 'summary') : root.children;
    return [root, ...children.flatMap(visibleDescendants)];
}
const tick = () => new Promise(setImmediate);
const response = (data, status = 200) => ({ ok: status < 400, status, json: async () => ({ data }) });
function harness(fetch) {
    const timers = [];
    const intervals = [];
    const window = {
        fetch, location: { href: 'http://localhost:8000/study/view-a', origin: 'http://localhost:8000' },
        crypto: { randomUUID: () => 'request-' + Math.random().toString(36).slice(2) },
        setTimeout: (fn) => { timers.push({ fn }); return timers.length; },
        clearTimeout: (id) => { if (timers[id - 1]) timers[id - 1].cancelled = true; },
        setInterval: (fn) => { intervals.push({ fn }); return intervals.length; },
        clearInterval: (id) => { if (intervals[id - 1]) intervals[id - 1].cancelled = true; },
    };
    const document = { createElement: (tag) => new Element(tag), activeElement: null };
    vm.runInNewContext(fs.readFileSync('src/web/static/js/image-diagrams.js', 'utf8'), {
        window, document, Option, URL, URLSearchParams, Headers, Date, console, WeakMap, Set,
    });
    const root = new Element();
    const controller = window.ImageDiagrams.mount(root, { viewToken: 'view-a' });
    return {
        root, controller, window, timers, intervals,
        all: () => descendants(root),
        visible: () => visibleDescendants(root),
        button: (text) => descendants(root).find((node) => node.tagName === 'button' && node.textContent === text),
        get: (suffix) => descendants(root).find((node) => node.id && node.id.endsWith('-' + suffix)),
        async poll() {
            const timer = timers.find((item) => !item.cancelled && !item.fired);
            assert.ok(timer, 'Expected an active progress poll'); timer.fired = true;
            await timer.fn(); await tick();
        },
    };
}
const job = (id = 'job-1', overrides = {}) => ({
    id, status: 'succeeded', stage: 'succeeded', style: 'warm-guide', scope: 'overview',
    image_url: `/api/image-diagrams/jobs/${id}/image`, download_url: `/api/image-diagrams/jobs/${id}/image?download=1`,
    created_at: '2026-10-30T01:00:00+00:00', ...overrides,
});
const state = (versions = [], active = null) => ({
    enabled: true, title: 'Source title', styles: [{ id: 'warm-guide', label: 'Warm' }, { id: 'handdrawn', label: 'Drawn' }],
    sections: [{ id: 'section-1', title: 'Chapter one' }], versions, active_job: active,
});

async function main() {
    {
        let archiveState = 'ready';
        const writes = [];
        const h = harness(async (url, init = {}) => {
            if (!url.endsWith('/feishu')) return response(state([job()]));
            if (init.method === 'POST') {
                writes.push(url);
                archiveState = 'queued';
            }
            return response({ state: archiveState, document_url: 'https://my.feishu.cn/wiki/archive#image-block' });
        });
        await tick();
        const sync = h.button('同步到飞书');
        assert.equal(sync.hidden, false);
        assert.deepEqual(writes, []);
        await sync.listeners.click();
        assert.deepEqual(writes, ['/api/image-diagrams/jobs/job-1/feishu']);
        assert.ok(h.visible().some(node => node.textContent === '已排队同步图解'));
        archiveState = 'done';
        await h.poll();
        assert.ok(h.visible().some(node => node.textContent === '图解已同步'));
        assert.ok(h.visible().some(node => node.href === 'https://my.feishu.cn/wiki/archive#image-block'
            && node.textContent === '在飞书中打开图解'));
        h.controller.destroy();
    }
    {
        const legacy = job('legacy-reviewing', { status: 'reviewing', stage: 'reviewing', review: {
            status: 'unavailable', summary: 'LEGACY_REVIEW_MUST_NOT_RENDER', issues: [],
        } });
        const calls = [];
        const h = harness(async (url, init = {}) => {
            calls.push({ url, ...init });
            return response(state([legacy], legacy));
        });
        await tick();
        assert.equal(h.all().find(node => node.className === 'idg-progress').hidden, true, 'A legacy saved image is already complete');
        assert.equal(h.button('修改').disabled, false);
        assert.equal(h.timers.length, 0, 'Saved legacy images must not keep polling an obsolete review phase');
        assert.equal(h.all().some(node => node.textContent.includes('LEGACY_REVIEW_MUST_NOT_RENDER')), false);
        assert.equal(h.all().some(node => node.textContent.includes('核对内容') || node.textContent.includes('检查未完成')), false);
        assert.equal(calls.some(call => call.method === 'POST'), false);
        assert.ok(h.visible().some(node => node.tagName === 'img' && node.src.endsWith('/legacy-reviewing/image')));
    }
    {
        let phase = 'planning';
        const active = () => job('progress-job', {
            status: phase, stage: phase, image_url: phase === 'succeeded' ? '/api/image-diagrams/jobs/progress-job/image' : '',
            created_at: new Date(Date.now() - 45000).toISOString(), updated_at: new Date().toISOString(),
            progress: phase === 'planning' ? { phase: 'reading', completed_chunks: 3, total_chunks: 11 } : null,
        });
        const h = harness(async url => response(url.includes('/jobs/') ? active() : state([active()], active())));
        await tick();
        const bar = h.all().find(node => node.getAttribute('role') === 'progressbar');
        const panel = h.all().find(node => node.className === 'idg-progress');
        const steps = h.all().find(node => node.className === 'idg-progress-steps');
        assert.deepEqual(steps.children.map(node => node.textContent), ['准备内容', '绘制图解']);
        assert.equal(panel.hidden, false);
        assert.equal(bar.getAttribute('aria-valuenow'), '3');
        assert.equal(bar.getAttribute('aria-valuemax'), '11');
        assert.ok(h.visible().some(node => node.textContent === '已读 3 / 11 段'));
        assert.equal(h.visible().some(node => node.textContent.includes('%')), false, 'No invented completion percentage');
        assert.equal(h.visible().some(node => node.textContent === '刷新状态'), false);
        phase = 'generating';
        await h.poll();
        assert.equal(bar.getAttribute('aria-valuenow'), null, 'Image generation duration is unknown');
        assert.equal(bar.dataset.mode, 'indeterminate');
        assert.ok(h.visible().some(node => node.textContent === '正在绘制图解'));
        phase = 'succeeded';
        await h.poll();
        assert.equal(panel.hidden, true);
        assert.ok(h.intervals.every(value => value.cancelled), 'Finished progress clocks must stop');
    }
    {
        const active = job('interrupted', { status: 'generating', image_url: '', updated_at: new Date().toISOString() });
        let posts = 0;
        const h = harness(async (url, init = {}) => {
            if (init.method === 'POST') posts++;
            if (url.includes('/jobs/')) throw new Error('Connection lost');
            return response(state([active], active));
        });
        await tick();
        await h.poll();
        assert.equal(h.all().find(node => node.className === 'idg-progress').dataset.paused, 'true');
        assert.ok(h.visible().some(node => node.textContent === '等待进度更新'));
        assert.ok(h.visible().some(node => node.textContent === '刷新状态'));
        assert.equal(posts, 0);
    }
    {
        const calls = [];
        const h = harness(async (url, init = {}) => { calls.push({ url, ...init }); return response(state()); });
        await tick();
        assert.equal(calls.length, 1);
        assert.equal(calls[0].url, '/api/image-diagrams/study/view-a');
        assert.equal(calls.some((call) => call.method === 'POST'), false);
        assert.equal(h.get('style'), undefined, 'Reading must not require style configuration');
        assert.equal(h.get('scope'), undefined, 'Reading must not require scope configuration');
        await h.controller.refresh();
        assert.equal(calls.some((call) => call.method === 'POST'), false, 'Navigation and refresh must remain read-only');
        assert.equal(h.button('生成图解').disabled, false);
        assert.deepEqual(h.visible().filter((node) => node.textContent).map((node) => node.textContent), ['生成图解'], 'Empty state should have one clear action and no repeated explanatory copy');
    }
    {
        const calls = []; let resolveSubmission;
        const h = harness(async (url, init = {}) => {
            calls.push({ url, ...init });
            if (init.method === 'POST') return new Promise((resolve) => { resolveSubmission = resolve; });
            return response(state());
        });
        await tick();
        const submit = h.button('生成图解');
        const first = submit.listeners.click();
        await submit.listeners.click();
        assert.equal(calls.filter((call) => call.method === 'POST').length, 1, 'Repeated clicks must not submit twice');
        const body = JSON.parse(calls.find((call) => call.method === 'POST').body);
        assert.equal(body.scope, 'overview');
        assert.equal(body.section_id, null);
        assert.equal(body.style, 'warm-guide');
        assert.equal(body.instructions, '');
        assert.equal(submit.disabled, true);
        assert.equal(h.visible().some((node) => node === submit), false, 'Submission progress replaces the initial action');
        resolveSubmission(response(job('new-job', { status: 'generating', stage: 'generating', image_url: '' })));
        await first;
        assert.equal(h.timers.length, 1);
        assert.equal(submit.disabled, true);
        h.controller.destroy();
        assert.equal(h.timers[0].cancelled, true);
        assert.ok(h.intervals.every(value => value.cancelled), 'Progress clocks must stop on destroy');
    }
    {
        const old = job('old-job');
        const active = job('new-job', { status: 'generating', stage: 'generating', image_url: '' });
        let polling = false; const calls = [];
        const h = harness(async (url, init = {}) => {
            calls.push({ url, ...init });
            if (url.includes('/jobs/')) { polling = true; return response(job('new-job', { status: 'failed', image_url: '', error_message: 'Quota exhausted' })); }
            return response(state([active, old], active));
        });
        await tick();
        assert.ok(h.all().find((node) => node.tagName === 'img' && node.src.endsWith('/old-job/image')));
        await h.poll();
        assert.equal(polling, true);
        assert.ok(h.all().find((node) => node.tagName === 'img' && node.src.endsWith('/old-job/image')), 'A new failure must not hide the old image');
        assert.equal(calls.some((call) => call.method === 'POST'), false, 'Polling failure must not automatically retry generation');
    }
    {
        const bodies = []; let attempts = 0;
        const h = harness(async (url, init = {}) => {
            if (init.method === 'POST') {
                bodies.push(JSON.parse(init.body)); attempts += 1;
                if (attempts === 1) throw new Error('Network disconnected');
                return response(job('confirmed', { status: 'queued', image_url: '' }));
            }
            return response(state());
        });
        await tick();
        await h.button('生成图解').listeners.click();
        assert.equal(bodies.length, 1);
        assert.equal(h.get('instructions').disabled, true, 'Ambiguous submission must keep the original recipe');
        await h.button('确认上次请求').listeners.click();
        assert.equal(bodies.length, 2);
        assert.equal(bodies[0].request_id, bodies[1].request_id, 'Explicit retry must reuse the idempotency identity');
        assert.deepEqual(bodies[0], bodies[1]);
    }
    {
        const old = job('old', { scope: 'section', section_id: 'section-1', section_title: 'Chapter one', style: 'handdrawn', review: {
            status: 'needs_attention', summary: '<script>alert(1)</script>', issues: [{ severity: 'high', description: '<img onerror=alert(1)>', source_ref_id: 'P3' }],
        }, source_refs: [{ id: 'P3', line_id: 'line-3', start_seconds: 42, paragraph_index: 2, excerpt: '<img onerror=alert(1)>' }] });
        let submitted;
        const h = harness(async (url, init = {}) => {
            if (init.method === 'POST') { submitted = JSON.parse(init.body); return response(job('revision')); }
            return response(state([old]));
        });
        await tick();
        assert.equal(h.all().some((node) => node.tagName === 'script'), false);
        assert.equal(h.all().filter((node) => node.tagName === 'img').length, 2, 'Legacy review text must not create executable markup');
        const evidenceLinks = h.all().filter((node) => node.tagName === 'a' && node.className === 'idg-source-link');
        assert.equal(evidenceLinks.length, 1);
        assert.equal(evidenceLinks[0].href, '/study/view-a?visual_line_id=line-3&visual_paragraph=2&visual_start=42');
        assert.equal(h.visible().some((node) => node.id && node.id.endsWith('-instructions')), false, 'Edit form stays hidden until requested');
        assert.equal(h.all().some((node) => node.className === 'idg-review'), false, 'Content review UI has been removed');
        assert.equal(h.visible().some((node) => node.textContent === '生成图解'), false, 'Successful image replaces the empty-state action');
        await h.button('修改').listeners.click();
        assert.equal(h.button('修改').getAttribute('aria-expanded'), 'true');
        const revise = h.button('生成修改版');
        await revise.listeners.click();
        assert.equal(submitted, undefined, 'Revision requires a concrete edit request');
        h.get('instructions').value = 'Make labels larger';
        await revise.listeners.click();
        assert.equal(submitted.revision_of, 'old');
        assert.equal(submitted.scope, 'section');
        assert.equal(submitted.section_id, 'section-1');
        assert.equal(submitted.instructions, 'Make labels larger');
        assert.equal(submitted.style, 'handdrawn', 'Revisions preserve an existing image style without asking users to configure it');
        assert.equal(h.button('修改').getAttribute('aria-expanded'), 'false');
        h.button('放大').listeners.click();
        assert.equal(h.all().find((node) => node.tagName === 'dialog').open, true);
        h.button('关闭').listeners.click();
        assert.equal(h.all().find((node) => node.tagName === 'dialog').open, false);
    }
    {
        const unknown = job('unknown', { status: 'unknown', image_url: '' });
        const calls = [];
        const h = harness(async (url, init = {}) => { calls.push({ url, ...init }); return response(state([unknown])); });
        await tick();
        assert.ok(h.all().some((node) => node.textContent.includes('系统不会自动重发')));
        assert.equal(h.timers.length, 0);
        assert.equal(calls.some((call) => call.method === 'POST'), false);
        assert.equal(h.button('生成图解').disabled, true);
        await h.button('已核对用量，重新生成').listeners.click();
        const explicit = calls.find((call) => call.method === 'POST');
        assert.equal(JSON.parse(explicit.body).regenerate, true, 'Unknown outcomes require a deliberate new paid attempt');
    }
    {
        let posts = 0;
        const h = harness(async (url, init = {}) => {
            if (init.method === 'POST') posts += 1;
            return response({ ...state(), source_ready: false });
        });
        await tick();
        assert.equal(h.button('生成图解').disabled, true);
        await h.button('生成图解').listeners.click();
        assert.equal(posts, 0, 'Source must be ready before a manual submission is allowed');
    }
    {
        const old = job('old');
        const h = harness(async () => response(state([job('latest'), old])));
        await tick();
        assert.equal(h.visible().some((node) => node.textContent === '刷新状态'), false);
        assert.equal(h.visible().some((node) => node.textContent === '图解已生成'), false);
        assert.equal(h.visible().some((node) => node.textContent === '历史版本'), false);
        const menu = h.all().find((node) => node.className === 'idg-more');
        assert.equal(menu.open, false);
        menu.open = true;
        assert.equal(h.visible().some((node) => node.textContent === '历史版本'), true);
        await h.button('修改').listeners.click();
        await h.button('取消').listeners.click();
        assert.equal(h.visible().some((node) => node.id && node.id.endsWith('-instructions')), false);
        h.get('history').value = 'old';
        h.get('history').listeners.change();
        assert.ok(h.visible().some((node) => node.tagName === 'img' && node.src.endsWith('/old/image')));
    }
    {
        const source = fs.readFileSync('src/web/static/js/study.js', 'utf8');
        const handle = source.slice(source.indexOf('    function handleVisualSourceRef('), source.indexOf('    function handleVisualSectionEvidence('));
        const apply = source.slice(source.indexOf('    function applyRequestedVisualSource('), source.indexOf('    function renderChat('));
        let playbackStarts = 0;
        const row = { dataset: { lineId: 'line-1' }, classList: { toggle() {} } };
        const ctx = {
            state: { requestedVisualSourceApplied: false, session: { transcript: { lines: [] } } },
            els: { visualDialog: { open: false }, video: { src: 'media.mp4', currentTime: 0 }, aiOverview: { scrollIntoView() {} } },
            window: { location: { search: '?visual_line_id=line-1&visual_start=42' } },
            document: { querySelectorAll: () => [row] }, viewToken: 'view-a', URLSearchParams,
            activateTab() {}, scrollTranscriptTarget() {}, seekTo: () => { playbackStarts += 1; },
        };
        vm.createContext(ctx); vm.runInContext(handle + apply, ctx);
        vm.runInContext('applyRequestedVisualSource()', ctx);
        assert.equal(ctx.state.requestedVisualSourceApplied, false, 'Evidence link must wait until source lines exist');
        ctx.state.session.transcript.lines = [{ id: 'line-1' }];
        vm.runInContext('applyRequestedVisualSource()', ctx);
        assert.equal(ctx.state.requestedVisualSourceApplied, true);
        assert.equal(ctx.els.video.currentTime, 42);
        assert.equal(playbackStarts, 0, 'Opening an evidence link must not autoplay media');
        vm.runInContext('applyRequestedVisualSource()', ctx);
        assert.equal(playbackStarts, 0);
        vm.runInContext("handleVisualSourceRef('P1', {line_id:'line-1', start_seconds:45})", ctx);
        assert.equal(playbackStarts, 1, 'Existing direct playback interactions retain their behavior');
    }
    {
        const nodes = Object.fromEntries(['transcript-reader-text', 'transcript-reader-visual', 'transcript-summary-text-panel', 'transcript-summary-visual-panel'].map((id) => [id, new Element()]));
        const secondary = new Element();
        nodes['transcript-summary-visual-panel'].dataset.viewToken = 'view-a';
        let mounts = 0;
        const window = {
            VisualLearning: {}, ImageDiagrams: { mount: () => { mounts += 1; return { destroy() {} }; } },
            location: { hash: '' }, addEventListener() {},
        };
        const document = { getElementById: (id) => nodes[id], querySelectorAll: () => [secondary] };
        vm.runInNewContext(fs.readFileSync('src/web/static/js/transcript-visual-reader.js', 'utf8'), { window, document, Set, Array });
        assert.equal(mounts, 0, 'The image reader stays lazy until its tab is opened');
        nodes['transcript-reader-visual'].listeners.click();
        assert.equal(nodes['transcript-summary-text-panel'].hidden, true);
        assert.equal(nodes['transcript-summary-text-panel'].classList.contains('is-active'), false);
        assert.equal(nodes['transcript-summary-visual-panel'].hidden, false);
        assert.equal(secondary.hidden, true);
        assert.equal(mounts, 1);
        nodes['transcript-reader-text'].listeners.click();
        assert.equal(nodes['transcript-summary-text-panel'].hidden, false);
        assert.equal(nodes['transcript-summary-visual-panel'].hidden, true);
        assert.equal(secondary.hidden, false);
        nodes['transcript-reader-visual'].listeners.click();
        assert.equal(mounts, 1, 'Switching tabs reuses the existing reader without resubmitting');
    }
    {
        const calibrated = job('calibrated', {
            source_refs: [{ id: 'P2', source_kind: 'calibrated', line_id: 'calibrated-line-2', start_seconds: 12, excerpt: '真实的校对段落，保留内容位置。' }],
            review: { status: 'needs_attention', issues: [{ description: '请核对这段内容', source_ref_id: 'P2' }] },
        });
        const h = harness(async () => response(state([calibrated])));
        await tick();
        const links = h.all().filter((node) => node.tagName === 'a' && node.className === 'idg-source-link');
        assert.equal(links.length, 1);
        const target = '/view/view-a#calibrated-section:~:text=' + encodeURIComponent('真实的校对段落，保留内容位置。');
        assert.equal(links[0].href, target);
        assert.equal(links.some((link) => link.href.includes('visual_line_id')), false, 'Calibrated identities must not be applied to raw transcript rows');
    }
    console.log('Image diagram browser behavior checks passed.');
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
