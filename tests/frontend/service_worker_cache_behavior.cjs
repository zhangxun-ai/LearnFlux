'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const origin = 'http://localhost';
const handlers = {};
const stored = new Map();
const fetched = [];
let offline = false;
let privateResponse = false;
let claimed = false;
let precached = [];
const key = (request) => typeof request === 'string' ? new URL(request, origin).href : request.url;

class WorkerRequest extends Request {
    constructor(request, options) {
        super(typeof request === 'string' ? new URL(request, origin) : request, options);
    }
}

const cache = {
    addAll: async (requests) => { precached = requests; },
    put: async (request, response) => { stored.set(key(request), response); },
    match: async (request) => stored.get(key(request))?.clone(),
};
const context = vm.createContext({
    Request: WorkerRequest,
    Response,
    URL,
    Set,
    self: {
        location: { origin },
        addEventListener: (name, handler) => { handlers[name] = handler; },
        skipWaiting: async () => {},
        clients: { claim: async () => { claimed = true; } },
    },
    caches: {
        open: async () => cache,
        match: async (request) => stored.get(key(request))?.clone(),
        delete: () => { throw new Error('Existing caches must not be deleted'); },
    },
    fetch: async (request, options) => {
        fetched.push({ request, options });
        if (offline) throw new Error('Offline');
        // A default fetch can return old bytes from the HTTP cache even online.
        return new Response(options?.cache === 'no-store' ? 'fresh shell' : 'stale shell', {
            headers: { 'Cache-Control': privateResponse ? 'private, no-store' : 'no-cache' },
        });
    },
});

vm.runInContext(fs.readFileSync('src/web/static/service-worker.js', 'utf8'), context);

async function dispatch(url, method = 'GET') {
    let response;
    const work = [];
    handlers.fetch({
        request: new WorkerRequest(url, { method }),
        respondWith: (promise) => { response = promise; },
        waitUntil: (promise) => { work.push(promise); },
    });
    if (!response) return null;
    const resolved = await response;
    await Promise.all(work);
    return resolved;
}

async function main() {
    await new Promise((resolve, reject) => handlers.install({ waitUntil: (promise) => promise.then(resolve, reject) }));
    assert.ok(precached.length > 0);
    assert.ok(precached.every((request) => request.cache === 'no-store'));
    await new Promise((resolve, reject) => handlers.activate({ waitUntil: (promise) => promise.then(resolve, reject) }));
    assert.equal(claimed, true);

    const history = `${origin}/static/history.html`;
    const response = await dispatch(history);
    assert.equal(await response.text(), 'fresh shell');
    assert.equal(fetched.at(-1).options.cache, 'no-store');
    assert.equal(await stored.get(history).clone().text(), 'fresh shell');
    assert.equal(await (await dispatch(`${origin}/static/css/workbench-wildwood.css?v=old`)).text(), 'fresh shell');

    offline = true;
    assert.equal(await (await dispatch(history)).text(), 'fresh shell');
    assert.equal((await dispatch(`${origin}/static/js/missing.js`)).type, 'error');
    offline = false;

    for (const path of ['/api/tasks', '/api/briefings', '/view/private', '/export/private', '/reading/private', '/study/private', '/collections/private', '/static/private.html', '/static/private.pdf']) {
        assert.equal(await dispatch(origin + path), null, path);
    }
    assert.equal(await dispatch(`${origin}/settings`, 'POST'), null);
    assert.equal(await dispatch('https://example.com/static/app.js'), null);
    privateResponse = true;
    await dispatch(`${origin}/static/js/private.js`);
    assert.equal(stored.has(`${origin}/static/js/private.js`), false);

    let load;
    let registration;
    vm.runInNewContext(fs.readFileSync('src/web/static/js/pwa-register.js', 'utf8'), {
        window: { isSecureContext: true, addEventListener: (name, fn) => { if (name === 'load') load = fn; } },
        navigator: { serviceWorker: { register: async (url, options) => { registration = { url, options }; } } },
        console,
    });
    await load();
    assert.equal(registration.url, '/service-worker.js');
    assert.equal(registration.options.updateViaCache, 'none');
    process.stdout.write('Service worker cache regression checks passed.\n');
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
