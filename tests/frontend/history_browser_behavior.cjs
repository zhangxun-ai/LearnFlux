const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('src/web/static/history.html', 'utf8').split('<script>').at(-1).split('</script>')[0];
function element(value = '') {
    return { value, textContent: '', innerHTML: '', hidden: false, style: {}, dataset: {}, children: [], attributes: {}, selectedOptions: [],
        classList: { toggle() {}, add() {}, remove() {} }, addEventListener() {}, setAttribute(key, val) { this.attributes[key] = val; },
        querySelector() { return null; }, querySelectorAll() { return []; }, replaceChildren() {}, appendChild() {}, append(...children) { this.children.push(...children); },
        scrollIntoView() {}, focus() {}, isConnected: true };
}
function harness(search = '') {
    const fields = new Map();
    for (const id of ['filterQ', 'filterStartDate', 'filterEndDate', 'filterPlatform', 'filterAuthor']) fields.set(id, element());
    for (const id of ['filterStatus', 'filterRead', 'filterMarked', 'historyDateRange']) fields.set(id, element('all'));
    fields.set('filterRecordType', element('task'));
    const get = id => { if (!fields.has(id)) fields.set(id, element()); return fields.get(id); };
    const storage = () => { const entries = new Map(); return { getItem: key => entries.get(key) || null, setItem: (key, val) => entries.set(key, val), removeItem: key => entries.delete(key) }; };
    const localStorage = storage(); const sessionStorage = storage();
    const document = { getElementById: get, querySelectorAll: () => [], querySelector: () => null,
        addEventListener() {}, createElement: () => element(), body: { classList: { contains: () => false } } };
    const location = { pathname: '/static/history.html', search };
    const user = { authenticated: true, user: { user_id: 'alice' }, expires_at: 'today' };
    const auth = { ready: { then() {} }, isAuthenticated: () => true, getState: () => user, getTokenPlaceholder: () => 'session', requireSession: async () => {} };
    const window = { LearnFluxAuth: auth, location, addEventListener() {}, matchMedia: () => ({ matches: false }) };
    const history = { replaceState(_, __, url) { location.search = url.startsWith('?') ? url : ''; } };
    const sandbox = { window, document, location, history, localStorage, sessionStorage, URL, URLSearchParams,
        console, setTimeout, clearTimeout, AbortController, requestAnimationFrame: fn => fn(), fetch: () => { throw new Error('Unexpected fetch'); } };
    const context = vm.createContext(sandbox); vm.runInContext(source, context);
    // Rendering is verified in the real browser; these tests isolate async state transitions.
    vm.runInContext('renderList = items => { displayedItems = items; globalThis.lastItems = items; }; renderPagination = () => {}; updateUnreadBadge = () => {}; updateSelectionUI = () => {};', context);
    return { context, get, sandbox, run: code => vm.runInContext(code, context) };
}
function deferred() { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; }
function response(items, total = items.length) { return { ok: true, status: 200, json: async () => ({ code: 200, data: { items, total, api_key_masked: 'owner-mask' } }) }; }
async function run() {
    {
        const h = harness();
        const row = h.run(`buildRow({title:'<img src=x onerror=alert(1)>', status:'failed', view_token:'a"b', error:'<script>bad</script>', platform:'youtube'}, new Set(), 0)`);
        assert.match(row, /查看原因/); assert.match(row, /%22/); assert.match(row, /&lt;script&gt;/);
        assert.doesNotMatch(row, /<img|<script|type="checkbox"/);
        assert.match(h.run(`buildRow({title:'Ready', status:'success', view_token:'ok'}, new Set(), 0)`), /data-preview-view="ok"/);
        assert.match(h.run(`buildRow({status:'awaiting_cloud_confirmation', view_token:'quote'}, new Set(), 0)`), /确认费用/);
        const stableCover = h.run(`historyCoverURL({task_id:'persistent-record', title:'Before'})`);
        assert.equal(stableCover, h.run(`historyCoverURL({task_id:'persistent-record', title:'After'})`), 'Changing a title must not change an identified record cover');
        assert.match(stableCover, /^\/static\/images\/history\/cover-[a-z-]+\.webp$/);
        h.run(`assignHistoryCovers(Array.from({length: 7}, (_, index) => ({task_id: 'cover-record-' + index})))`);
        const mappedCovers = h.run(`Array.from({length: 7}, (_, index) => historyCoverURL({task_id: 'cover-record-' + index}))`);
        assert.equal(new Set(mappedCovers.slice(0, 6)).size, 6, 'The first six rendered records use distinct reference illustrations');
        assert.equal(mappedCovers[0], mappedCovers[6], 'Illustrations repeat only after the full six-scene sequence');
        assert.ok(h.run(`buildRow({task_id:'cover-record-0', status:'success', view_token:'cover-view'}, new Set(), 0)`).includes(mappedCovers[0]), 'A list row uses the same assigned cover as its recent card');
        assert.equal(h.run(`historyCoverURL({task_id:'cover-record-0', title:'Renamed'})`), mappedCovers[0], 'The current result mapping is stable for the same record');
        h.run('assignHistoryCovers([])');
        assert.equal(h.run('historyCoverAssignments.size'), 0, 'A new result replaces the previous cover mapping');

        assert.match(h.run(`buildRow({task_id:'persistent-record', status:'success', view_token:'ok', excerpt:'<script>snippet</script>'}, new Set(), 0)`), /&lt;script&gt;snippet&lt;\/script&gt;/);

    }
    {
        const h = harness(); const pending = deferred();
        h.context.apiFetch = () => pending.promise;
        const panel = element(); const button = element(); const row = { isConnected: true, querySelector: () => panel };
        h.context.row = row; h.context.button = button;
        const task = h.run(`toggleSummary('one', row, button)`);
        assert.equal(panel.hidden, false);
        h.run('closeSummary()'); pending.resolve({ code: 200, data: { summary: 'Late response' } }); await task;
        assert.equal(panel.hidden, true); assert.notEqual(panel.textContent, 'Late response');
        assert.equal(button.attributes['aria-expanded'], 'false');
        assert.equal(h.run('summaryPlainText("## Heading\\n**bold** [source](https://example.com)")'), 'Heading\nbold source');
    }
    {
        const h = harness(); const old = deferred(); const latest = deferred(); let calls = 0;
        h.context.fetch = () => (++calls === 1 ? old.promise : latest.promise);
        h.get('filterQ').value = 'first'; const first = h.run('fetchHistory()');
        h.get('filterQ').value = 'second'; const second = h.run('fetchHistory()');
        latest.resolve(response([{ title: 'Second', view_token: 'second', status: 'success' }])); await second;
        old.resolve(response([{ title: 'First', view_token: 'first', status: 'success' }])); await first;
        assert.equal(h.context.lastItems[0].title, 'Second');
        await h.run('fetchHistory()'); assert.equal(calls, 2, 'Fresh cached query must not refetch');
    }
    {
        const h = harness();
        h.run(`cacheOwner = 'alice'; writeHistoryCache('records', {items:[{title:'A',wechat_webhook:'secret'}],webhooks:['secret']});`);
        assert.equal(h.run(`readHistoryCache('records', 10000).items[0].wechat_webhook`), undefined);
        assert.equal(h.run(`readHistoryCache('records', 10000).webhooks.length`), 0);
        h.run(`cacheOwner = 'bob'; responseCache.clear();`);
        assert.equal(h.run(`readHistoryCache('records', 10000)`), null, 'Another owner must not reuse cached records');
    }
    {
        const h = harness('?page=3&per_page=50');
        h.run('restoreHistoryLocation()'); assert.equal(h.run('currentPage'), 2); assert.equal(h.run('PAGE_SIZE'), 50);
        h.run('serializeFiltersToURL(false)'); assert.match(h.sandbox.location.search, /page=3/);
        h.run('serializeFiltersToURL()'); assert.equal(h.run('currentPage'), 0);
    }
    {
        const h = harness(); const rows = Array.from({ length: 501 }, (_, i) => ({ view_token: 'record-' + i, title: String(i), status: 'success' }));
        h.get('filterRead').value = 'unread'; let calls = 0;
        h.context.fetch = async () => response(++calls === 1 ? rows.slice(0, 500) : rows.slice(500), 501);
        await h.run('fetchHistory()'); assert.equal(calls, 2); assert.equal(h.run('_filteredItems.length'), 501);
        assert.equal(h.run('_filteredItems.at(-1).view_token'), 'record-500');
    }
    {
        const h = harness();
        h.run(`pageSizeChoice = 'all'; PAGE_SIZE = 1000; currentMasked = 'owner-mask';
            saveReadSet(new Set(['opened-1', 'opened-2']));`);
        h.context.data = { api_key_masked: 'owner-mask', total: 2500, items: [
            { view_token: 'opened-1', status: 'success' },
            { view_token: 'opened-2', status: 'success' },
            { view_token: 'other', status: 'success' },
        ] };
        h.run(`applyHistoryData(data, 'read')`);
        assert.equal(h.run('pageSizeChoice'), 'all', 'All must apply to filtered results, not the raw library size');
        assert.equal(h.context.lastItems.length, 2);
    }
    {
        const h = harness();
        h.run(`pageSizeChoice = 'all'; PAGE_SIZE = 1000;`);
        h.context.data = { total: 1001, items: Array.from({ length: 1000 }, (_, i) => ({ view_token: 'item-' + i })) };
        h.run(`applyHistoryData(data, 'all')`);
        assert.equal(h.run('PAGE_SIZE'), 100);
        assert.equal(h.context.lastItems.length, 100, 'Page fallback must render only its stated page size');
    }
    {
        const h = harness('?page=2');
        h.context.window.LearnFluxAuth.ready = Promise.resolve({ authenticated: true });
        h.context.loadFilterOptions = () => new Promise(() => {});
        h.context.updateRecordTypeFilterUI = () => {}; h.context.updateFilterSummary = () => {};
        h.context.fetch = async () => response([{ title: 'Page two', view_token: 'two', status: 'success' }], 100);
        await h.run('loadHistory()');
        assert.equal(h.run('currentPage'), 1, 'Initial navigation must restore page from URL');
        assert.equal(h.context.lastItems[0].title, 'Page two', 'Metadata must not gate list loading');
    }
    {
        const h = harness();
        const expandingMain = { scrollHeight: 2000, clientHeight: 2000, scrollTop: 0 };
        h.context.document.querySelector = () => expandingMain;
        assert.equal(h.run('historyScrollRoot()'), null, 'A content-height main must restore the window scroll position');
        const scrollingMain = { scrollHeight: 2000, clientHeight: 700, scrollTop: 180 };
        h.context.document.querySelector = () => scrollingMain;
        h.context.getComputedStyle = () => ({ overflowY: 'auto' });
        assert.equal(h.run('historyScrollRoot()'), scrollingMain, 'A bounded scrollable main remains the scroll root');
    }
    {
        const h = harness();
        for (const [status, viewToken, label] of [
            ['unknown', '', '仅导入记录'], ['unknown', 'view', '待确认'],
            ['canceled', 'view', '已取消'], ['cancelled', 'view', '已取消'],
            ['awaiting_cloud_confirmation', 'view', '待确认费用'], ['queued', 'view', '排队中'],
            ['success', 'view', '解析完成'], ['failed', 'view', '失败']
        ]) {
            h.context.statusItem = { task_id: 'status-record', title: 'Status record', status, view_token: viewToken };
            const card = h.run('buildTendederoCard(statusItem, 0)');
            const cardLabel = card.children.at(-1).children.at(-1).textContent;
            assert.equal(cardLabel, label, 'A recent card must show the actual task state');
            assert.ok(h.run('buildRow(statusItem, new Set(), 0)').includes(label), 'Card and table state labels must agree');
        }
    }
    console.log('History browser behavior checks passed');
}
run().catch(error => { console.error(error); process.exitCode = 1; });
