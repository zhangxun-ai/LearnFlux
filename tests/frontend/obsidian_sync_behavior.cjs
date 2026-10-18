const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
    constructor(value = '') { this.value = value; this.checked = true; this.dataset = {}; this.children = []; this.events = {}; this.disabled = false; }
    addEventListener(name, handler) { this.events[name] = handler; }
    async emit(name) { return this.events[name]?.({}); }
    replaceChildren() { this.children = []; }
    append(child) { this.children.push(child); }
    querySelectorAll() { return []; }
    showModal() { this.open = true; }
    close() { this.open = false; }
}
async function singleFlow() {
    const nodes = new Map();
    const get = id => { if (!nodes.has(id)) nodes.set(id, new Element()); return nodes.get(id); };
    const options = [new Element('analysis'), new Element('raw')];
    const calls = [];
    let paths = ['03-知识', '03-知识/新目录'];
    let directoryFailure = false;
    let apiVersion = 2;
    let conflict = false;
    const context = {
        document: { getElementById: get, querySelectorAll: () => options, createElement: () => new Element() }, Headers,
        fetch: async (url, init) => {
            calls.push({url, init, body: init.body && JSON.parse(init.body)});
            let data = {};
            if (url.includes('/directories')) {
                if (directoryFailure) throw Error('offline');
                data = {items: paths, knowledge_sync_version: apiVersion};
            } else if (url.endsWith('/binding')) data = {binding: {revision: 1, category: 'legacy'}};
            else if (url.endsWith('/preview')) data = {binding_revision: 1, preconditions: [{id: 'x'}], items: [{documents: [{state: conflict ? 'externally_modified' : 'new', relative_path: '03-知识/AI 总结/a.md', diff: 'user edits'}]}]};
            else if (url.endsWith('/apply')) data = {counts: {created: 1}};
            return {ok: true, json: async () => ({data})};
        }
    };
    context.window = {document: context.document, getContentMarkToken: () => 'test', setTimeout: () => 1, clearTimeout() {}};
    vm.runInNewContext(fs.readFileSync('src/web/static/js/obsidian-knowledge.js', 'utf8'), context);
    const open = get('obsidian-knowledge-open'), apply = get('obsidian-knowledge-apply'), dir = get('obsidian-knowledge-directory');
    await open.emit('click');
    assert.equal(calls.find(c => c.url.includes('/directories')).init.cache, 'no-store');
    assert.deepEqual(get('obsidian-knowledge-directories').children.map(c => c.value), paths);
    dir.value = '03-知识/新目录'; await dir.emit('input');
    options[1].checked = false; await options[1].emit('change');
    await apply.emit('click');
    let sent = calls.find(c => c.url.endsWith('/apply')).body;
    assert.equal(sent.target_directory, '03-知识/新目录');
    assert.deepEqual(sent.document_types, ['analysis']);
    assert.equal(get('obsidian-knowledge-dialog').open, false);
    paths = ['04-资源/已更新']; await open.emit('click');
    assert.deepEqual(get('obsidian-knowledge-directories').children.map(c => c.value), paths);
    assert.equal(dir.value, '');
    conflict = true;
    let count = calls.filter(c => c.url.endsWith('/apply')).length;
    await apply.emit('click');
    assert.equal(calls.filter(c => c.url.endsWith('/apply')).length, count, 'conflict must not auto overwrite');
    assert.equal(get('obsidian-knowledge-conflicts').hidden, false);
    await apply.emit('click');
    assert.equal(calls.at(-1).body.force, true);
    await open.emit('click'); await apply.emit('click');
    dir.value = 'other'; await dir.emit('input');
    count = calls.filter(c => c.url.endsWith('/apply')).length;
    await apply.emit('click');
    assert.equal(calls.filter(c => c.url.endsWith('/apply')).length, count, 'directory change invalidates conflict confirmation');
    options[0].checked = false; await options[0].emit('change');
    assert.equal(apply.disabled, true);
    apiVersion = undefined;
    options[0].checked = true;
    await get('obsidian-knowledge-refresh').emit('click');
    assert.equal(apply.disabled, true, 'old backend must not accept sync');
    assert.match(get('obsidian-knowledge-message').textContent, /重启 LearnFlux/);
    count = calls.filter(c => c.url.endsWith('/apply')).length;
    await apply.emit('click');
    assert.equal(calls.filter(c => c.url.endsWith('/apply')).length, count);
    directoryFailure = true; await get('obsidian-knowledge-refresh').emit('click');
    assert.equal(apply.disabled, true);
    assert.equal(get('obsidian-knowledge-directories').children.length, 0);
    assert.equal(dir.value, '');
}
async function collectionFlow() {
    const source = fs.readFileSync('src/web/static/js/collections.js', 'utf8');
    function extract(start, end) { return source.slice(source.indexOf(start), source.indexOf(end, source.indexOf(start))); }
    const calls = [];
    const ctx = {collectionDirectoriesReady: true, collectionVaultDirectories: ['old'], renderCollectionDirectoryPanel() {}, apiJSON: async (url, init) => { calls.push({url, init}); return {data: {items: ['03-知识/新目录'], knowledge_sync_version: 2}}; }};
    vm.createContext(ctx);
    vm.runInContext(extract('    function normalizeCollectionDirectoryName', '    function collectionDocumentTypes') + extract('    async function loadCollectionVaultDirectories', '    function setCollectionDirectoryValue'), ctx);
    assert.equal(ctx.normalizeCollectionDirectoryName('  03-知识/课程/第一节/ '), '03-知识/课程/第一节/');
    await ctx.loadCollectionVaultDirectories();
    assert.equal(calls[0].url, '/api/obsidian/directories?root=vault');
    assert.equal(calls[0].init.cache, 'no-store');
    assert.deepEqual(Array.from(ctx.collectionVaultDirectories), ['', '03-知识/新目录']);
    ctx.apiJSON = async () => ({data: {items: ['old/raw']}});
    await assert.rejects(ctx.loadCollectionVaultDirectories(), /重启 LearnFlux/);
    assert.equal(ctx.collectionDirectoriesReady, false);
    assert.equal(ctx.collectionVaultDirectories.length, 0);
    ctx.apiJSON = async () => {throw Error('offline');};
    await assert.rejects(ctx.loadCollectionVaultDirectories());
    assert.equal(ctx.collectionDirectoriesReady, false);
    assert.equal(ctx.collectionVaultDirectories.length, 0);
    // Recover the complete dialog after an old backend or failed first load.
    let rendered = 0;
    let chapters = [];
    let panelOpened = false;
    Object.assign(ctx, {
        collectionKnowledgeBusy: false, currentCollection: {id: 'course'}, collectionKnowledgeBinding: null,
        els: {obsidianCollectionDirectory: {value: '03-知识/新目录'}, obsidianCollectionSources: {querySelectorAll: () => chapters}},
        clearCollectionKnowledgePreview() {}, setCollectionKnowledgeBusy(value) { ctx.collectionKnowledgeBusy = value; },
        setCollectionKnowledgeMessage() {},
        renderCollectionKnowledgeSources() { rendered++; chapters = [{checked: true}]; },
        setCollectionDirectoryValue(value) { ctx.els.obsidianCollectionDirectory.value = value; },
        openCollectionDirectoryPanel() { panelOpened = true; }, closeCollectionDirectoryPanel() { panelOpened = false; },
        apiJSON: async url => ({data: url.includes('/directories')
            ? {items: ['03-知识/新目录'], knowledge_sync_version: 2}
            : {binding: {revision: 1, category: 'legacy'}}})
    });
    vm.runInContext(extract('    async function refreshCollectionKnowledgeDirectories', '    function clearCollectionKnowledgePreview'), ctx);
    await ctx.refreshCollectionKnowledgeDirectories();
    assert.equal(rendered, 1, 'refresh must restore missing chapters after initial load failure');
    assert.equal(ctx.collectionDirectoriesReady, true);
    assert.equal(ctx.collectionKnowledgeBinding.revision, 1);
    assert.equal(panelOpened, true);
    chapters[0].checked = false;
    await ctx.refreshCollectionKnowledgeDirectories();
    assert.equal(rendered, 1, 'refresh must preserve an existing chapter selection');
    assert.equal(chapters[0].checked, false);
    ctx.apiJSON = async () => { throw Error('offline'); };
    await ctx.refreshCollectionKnowledgeDirectories();
    assert.equal(ctx.collectionDirectoriesReady, false);
    assert.equal(panelOpened, false);

}
(async () => { await singleFlow(); await collectionFlow(); console.log('Obsidian frontend behavior tests passed'); })().catch(error => { console.error(error); process.exitCode = 1; });
