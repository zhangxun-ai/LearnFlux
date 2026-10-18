const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const template = fs.readFileSync('src/web/templates/processing.html', 'utf8');
const source = template.slice(template.indexOf('    function readApiToken()'),
    template.indexOf('    if (quoteActions && !quoteActions.hidden)'));
class Element {
    constructor(tag) { this.tagName = tag; this.children = []; this.style = {}; this.dataset = {}; this.textContent = ''; }
    set textContent(value) { this._text = value; this.children = []; }
    get textContent() { return this._text; }
    appendChild(node) { this.children.push(node); }
    replaceChildren(...nodes) { this.children = nodes; this.textContent = ''; }
    setAttribute() {}
    querySelectorAll() { return this.children.filter(node => node.dataset.action); }
    querySelector() { return this.children.find(node => node.dataset.action === 'cloud-confirm'); }
}
const flatten = node => [node, ...node.children.flatMap(flatten)];
const response = (data, ok = true) => ({ ok, json: async () => data });
async function scenario(code, cost = '0.30', refreshFails = false) {
    const quote = { duration_seconds: 60, billable_seconds: 60, max_cost_cny: '0.25', quote_token: 'old' };
    const actions = new Element('div'); actions.dataset.taskId = 'task/id';
    const nodes = { 'cloud-quote-actions': actions, 'cancel-task': new Element('button'),
        'progress-stage': new Element('div'), 'progress-message': new Element('div') };
    const requests = [];
    let gets = 0;
    const sandbox = { console, window: { LearnFluxAuth: { getTokenPlaceholder: () => 'session' } },
        document: { getElementById: id => nodes[id] || null, createElement: tag => new Element(tag) },
        fetch: async (url, options = {}) => {
            requests.push({ url, options });
            if (options.method === 'POST') return response({ detail: code }, false);
            gets++;
            if (gets === 2 && refreshFails) throw new Error('network unavailable');
            return response({ data: { status: 'awaiting_cloud_confirmation', progress: {
                evidence: { cloud_quote: gets === 1 ? quote : { ...quote, quote_token: 'new', max_cost_cny: cost } }
            } } });
        } };
    vm.createContext(sandbox);
    vm.runInContext(source + '\nglobalThis.load = loadCloudQuoteActions;', sandbox);
    await sandbox.load();
    await actions.querySelector().onclick();
    const allText = flatten(actions).map(node => node.textContent).join('\n');
    assert.doesNotMatch(allText, /重新加载报价|刷新报价/);
    const posts = requests.filter(request => request.options.method === 'POST');
    assert.equal(posts.length, 1);
    assert.equal(posts[0].url, '/api/task/task%2Fid/cloud-confirm');
    assert.equal(JSON.parse(posts[0].options.body).quote_token, 'old');
    if (code === 'network_failure' || refreshFails) {
        assert.match(allText, /重试/);
        assert.equal(gets, refreshFails ? 2 : 1);
        if (refreshFails) assert.doesNotMatch(allText, /quote_expired/);
        return;
    }
    assert.equal(gets, 2);
    assert.match(allText, /报价已更新，请确认预计费用/);
    assert.equal(allText.includes(`预计费用 ¥${cost}`), true);
    assert.doesNotMatch(allText, /quote_expired|quote_token_mismatch|quote_not_confirmable/);
    sandbox.fetch = async (url, options = {}) => {
        requests.push({ url, options });
        return response({ detail: 'network unavailable' }, false);
    };
    await actions.querySelector().onclick();
    assert.equal(JSON.parse(requests.at(-1).options.body).quote_token, 'new');
    assert.equal(JSON.parse(requests.at(-1).options.body).accepted_max_cost_cny, cost);
}
(async () => {
    await scenario('quote_expired', '0.25');
    await scenario('quote_token_mismatch');
    await scenario('quote_not_confirmable');
    await scenario('network_failure');
    await scenario('quote_expired', '0.25', true);
    console.log('Processing quote behavior checks passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
