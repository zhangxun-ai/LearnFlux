const assert = require('node:assert/strict');
const scenario = process.argv[2];
const remote = scenario === 'remote';
globalThis.window = globalThis;
globalThis.location = new URL(remote ? 'https://learnflux.test/' : 'http://localhost:8000/');
globalThis.localStorage = { getItem: () => null, removeItem: () => {} };
globalThis.sessionStorage = { getItem: () => null, removeItem: () => {} };
globalThis.CustomEvent = class { constructor(type, init) { this.detail = init.detail; } };
globalThis.dispatchEvent = () => true;
globalThis.XMLHttpRequest = undefined;
let probes = 0;
const writes = [];
const response = (status, data = {}) => new Response(JSON.stringify(data), {
    status, headers: { 'Content-Type': 'application/json' },
});
const authenticated = (csrf) => ({ authenticated: true, csrf_token: csrf, user: { user_id: 'user-1' } });
globalThis.fetch = async (input, options = {}) => {
    if (String(input) === '/api/auth/session') {
        probes += 1;
        if (probes === 1) {
            return scenario === 'initially_missing' ? response(401) : response(200, authenticated('old-csrf'));
        }
        if (scenario === 'offline') throw new TypeError('Failed to fetch');
        if (scenario === 'disabled') return response(401);
        if (scenario === 'concurrent') await new Promise(resolve => setTimeout(resolve, 20));
        return response(200, authenticated('new-csrf'));
    }
    const headers = new Headers(options.headers);
    const body = input instanceof Request ? await input.text() : options.body;
    writes.push({ headers, body });
    if (scenario === 'http500') return response(500);
    if (scenario === 'explicit_bearer' || remote || scenario === 'always_401' || scenario === 'disabled') return response(401);
    return response(headers.get('X-CSRF-Token') === 'new-csrf' ? 200 : 401);
};
require('../../src/web/static/js/auth-session.js');

(async () => {
    await LearnFluxAuth.ready;
    if (['initially_missing', 'preflight'].includes(scenario)) {
        await LearnFluxAuth.requireSession();
        assert.equal(LearnFluxAuth.isAuthenticated(), true);
        assert.equal(probes, 2);
        assert.equal((await fetch('/api/task', { method: 'POST', body: 'same content' })).status, 200);
        assert.equal(writes.length, 1);
    } else if (scenario === 'offline') {
        await assert.rejects(LearnFluxAuth.requireSession(), /Failed to fetch/);
        assert.equal(writes.length, 0);
    } else if (scenario === 'concurrent') {
        const results = await Promise.all([1, 2].map(() => fetch('/api/task', { method: 'POST', body: 'same content' })));
        assert.deepEqual(results.map(item => item.status), [200, 200]);
        assert.equal(probes, 2);
        assert.equal(writes.length, 4);
    } else {
        const options = { method: 'POST', body: 'same content' };
        let input = '/api/task';
        if (scenario === 'request_body') {
            input = new Request('http://localhost:8000/api/task', options);
            delete options.body;
        }
        if (scenario === 'explicit_bearer') options.headers = { Authorization: 'Bearer test-api-token' };
        if (scenario === 'stream') options.body = new ReadableStream({ start(controller) { controller.close(); } });
        const result = await fetch(input, options);
        if (scenario === 'explicit_bearer' || remote || scenario === 'http500') {
            assert.equal(probes, 1);
            assert.equal(writes.length, 1);
            assert.equal(result.status, scenario === 'http500' ? 500 : 401);
            assert.equal(LearnFluxAuth.isAuthenticated(), !remote);
        } else if (scenario === 'stream') {
            assert.equal(probes, 2);
            assert.equal(writes.length, 1);
            assert.equal(LearnFluxAuth.isAuthenticated(), true);
        } else if (scenario === 'disabled') {
            assert.equal(probes, 2);
            assert.equal(writes.length, 1);
            assert.equal(result.status, 401);
            assert.equal(LearnFluxAuth.isAuthenticated(), false);
        } else {
            assert.equal(probes, 2);
            assert.equal(writes.length, 2);
            assert.equal(writes[1].body, 'same content');
            assert.equal(writes[1].headers.get('X-CSRF-Token'), 'new-csrf');
            assert.equal(result.status, scenario === 'always_401' ? 401 : 200);
            assert.equal(LearnFluxAuth.isAuthenticated(), scenario !== 'always_401');
        }
    }
    console.log('Local auth reconnect scenario passed:', scenario);
})().catch(error => { console.error(error); process.exitCode = 1; });
