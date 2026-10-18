const assert = require('node:assert/strict');
const {
    initializeTextImport, initializeFileImport, APIManager, TaskHistoryManager,
} = require('../../src/web/static/js/app.js');

class Element {
    constructor() {
        this.handlers = new Map();
        this.dataset = {};
        this.value = '';
        this.textContent = '';
        this.hidden = false;
        this.disabled = false;
        this.checked = false;
        this.files = [];
        this.classList = { add() {}, remove() {} };
    }
    addEventListener(name, handler) { this.handlers.set(name, handler); }
    emit(name, data = {}) { return this.handlers.get(name)?.({ preventDefault() {}, ...data }); }
    setAttribute() {}
    focus() {}
    click() { return this.emit('click'); }
}
const ids = [
    'study-text-form', 'study-text-title', 'study-text-content', 'study-text-submit',
    'study-text-status', 'study-text-count', 'study-draft-note', 'study-draft-clear',
    'file-dropzone', 'file-input', 'dropzone-hint', 'file-selection', 'selected-file-name',
    'selected-file-details', 'file-transcription-options', 'file-cloud-note',
    'file-actions', 'file-submit', 'file-remove', 'file-cancel', 'file-upload-status',
];
const elements = Object.fromEntries(ids.map(id => [id, new Element()]));
const byId = id => elements[id];
let strategy = 'cloud';
const cloudRadio = new Element();
cloudRadio.value = 'cloud';
const localRadio = new Element();
localRadio.value = 'local';
const storage = new Map();
let authState = { status: 'authenticated', authenticated: true, user: { user_id: 'owner-a' }, expires_at: 'session-a' };
const windowEvents = new Map();
global.window = { location: { href: '' }, LearnFluxAuth: {
    requireSession: async () => {}, getTokenPlaceholder: () => 'test-session',
    isCancellation: () => false, getState: () => authState,
}, addEventListener: (name, handler) => {
    if (!windowEvents.has(name)) windowEvents.set(name, []);
    windowEvents.get(name).push(handler);
} };
const setAuth = next => {
    authState = next;
    for (const handler of windowEvents.get('learnflux:authchange') || []) handler({ detail: next });
};
global.document = {
    getElementById: byId,
    querySelector: selector => selector.includes('file-transcription-strategy')
        ? (strategy === 'cloud' ? cloudRadio : localRadio) : null,
    querySelectorAll: selector => selector.includes('file-transcription-strategy') ? [cloudRadio, localRadio] : [],
};
global.sessionStorage = {
    getItem: key => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, value),
    removeItem: key => storage.delete(key),
};
global.FormData = class {
    constructor() { this.entries = new Map(); }
    append(key, value) { this.entries.set(key, value); }
    get(key) { return this.entries.get(key); }
};
const flush = () => new Promise(resolve => setImmediate(resolve));

(async () => {
    initializeTextImport();
    byId('study-text-title').value = 'Draft title';
    byId('study-text-content').value = 'Keep this important draft.';
    byId('study-text-content').emit('input');
    assert.equal(byId('study-text-submit').disabled, false);
    assert.equal(byId('study-text-count').textContent, '26 / 200,000 字');
    assert.equal(storage.size, 1);

    let textRequests = 0;
    APIManager.submitStudyText = async () => { textRequests += 1; throw new Error('Service unavailable'); };
    await byId('study-text-form').emit('submit');
    assert.equal(byId('study-text-status').textContent, 'Service unavailable');
    assert.equal(byId('study-text-submit').disabled, false);
    assert.equal(byId('study-text-content').value, 'Keep this important draft.');
    assert.equal(storage.size, 1);

    // The same tab can recover a draft without a network request.
    byId('study-text-title').value = '';
    byId('study-text-content').value = '';
    initializeTextImport();
    assert.equal(byId('study-text-title').value, 'Draft title');
    assert.equal(byId('study-text-content').value, 'Keep this important draft.');
    assert.match(byId('study-draft-note').textContent, /恢复/);

    let finishText;
    APIManager.submitStudyText = () => {
        textRequests += 1;
        return new Promise(resolve => { finishText = resolve; });
    };
    const textSubmit = byId('study-text-form').emit('submit');
    await byId('study-text-form').emit('submit');
    assert.equal(textRequests, 2, 'A pending text submit must not be repeated');
    const previousDraftKey = [...storage.keys()][0];
    setAuth({ status: 'authenticated', authenticated: true, user: { user_id: 'owner-a' }, expires_at: 'session-a-renewed' });
    assert.equal(byId('study-text-content').value, 'Keep this important draft.', 'A session refresh must preserve visible text');
    assert.equal(byId('study-text-submit').disabled, true, 'A session refresh must preserve the active submission');
    assert.equal(storage.has(previousDraftKey), false);
    assert.ok([...storage.keys()].some(key => key.includes('session-a-renewed')));
    finishText({ data: { view_token: 'safe-text-token' } });
    await textSubmit;
    assert.equal(window.location.href, '/study/safe-text-token');
    assert.equal(storage.size, 0, 'A successful submission must clear the renewed draft scope');

    const previousPage = window.location.href;
    byId('study-text-content').value = 'Owner A private draft';
    byId('study-text-content').emit('input');
    let finishOldSubmit;
    APIManager.submitStudyText = () => new Promise(resolve => { finishOldSubmit = resolve; });
    const oldSubmission = byId('study-text-form').emit('submit');
    setAuth({ status: 'unauthenticated', authenticated: false, user: null });
    assert.equal(byId('study-text-content').value, '');
    assert.equal(byId('study-text-title').value, '');
    assert.equal(storage.size, 0, 'Logout must clear the active scoped draft');
    // Old anonymous drafts are deliberately neither restored nor migrated.
    storage.set('learnflux_study_text_draft_v1', JSON.stringify({ content: 'Unknown owner draft' }));
    setAuth({ status: 'authenticated', authenticated: true, user: { user_id: 'owner-b' }, expires_at: 'session-b' });
    assert.equal(byId('study-text-content').value, '', 'Owner B must never recover owner A or an unscoped draft');
    byId('study-text-content').value = 'Owner B current draft';
    byId('study-text-content').emit('input');
    finishOldSubmit({ data: { view_token: 'owner-a-result' } });
    await oldSubmission;
    assert.equal(window.location.href, previousPage, 'A late response from A must not navigate the new owner');
    assert.equal(byId('study-text-content').value, 'Owner B current draft');
    assert.ok([...storage.keys()].some(key => key.startsWith('learnflux_study_text_draft_v2:owner-b')));
    assert.equal(storage.get('learnflux_study_text_draft_v1').includes('Unknown owner'), true);

    let recentURL;
    global.fetch = async url => {
        recentURL = url;
        return new Response(JSON.stringify({ data: { items: [] } }), {
            status: 200, headers: { 'Content-Type': 'application/json' },
        });
    };
    await APIManager.getTaskHistory();
    assert.equal(recentURL, '/api/tasks?limit=4&offset=0', 'The import page must only fetch recent tasks');

    initializeFileImport();
    let uploadRequests = 0;
    let uploadArgs;
    let finishUpload;
    global.fetch = (url, options) => {
        uploadRequests += 1;
        uploadArgs = { url, options };
        return new Promise(resolve => { finishUpload = resolve; });
    };
    byId('file-input').files = [{ name: 'notes.pdf', type: 'application/pdf', size: 2048 }];
    byId('file-input').emit('change');
    assert.equal(uploadRequests, 0, 'Selecting a file must never upload it');
    assert.equal(byId('selected-file-name').textContent, 'notes.pdf');
    assert.equal(byId('file-transcription-options').hidden, true);
    assert.equal(byId('file-cloud-note').hidden, true);
    assert.equal(byId('file-actions').hidden, false);

    const upload = byId('file-submit').emit('click');
    await flush();
    await byId('file-submit').emit('click');
    assert.equal(uploadRequests, 1, 'A pending upload must not be repeated');
    assert.equal(uploadArgs.url, '/api/upload-transcribe');
    assert.equal(uploadArgs.options.body.get('transcription_strategy'), 'local', 'Documents must ignore cloud radio');
    finishUpload(new Response(JSON.stringify({ detail: 'PDF could not be read' }), {
        status: 422, headers: { 'Content-Type': 'application/json' },
    }));
    await upload;
    assert.match(byId('file-upload-status').textContent, /PDF could not be read/);
    assert.equal(byId('selected-file-name').textContent, 'notes.pdf');
    assert.equal(byId('file-submit').disabled, false);

    byId('file-dropzone').emit('drop', { dataTransfer: {
        files: [{ name: 'lesson.mp3', type: 'audio/mpeg', size: 4096 }],
    } });
    assert.equal(uploadRequests, 1, 'Dropping a file must only stage it');
    assert.equal(byId('file-transcription-options').hidden, false);
    assert.equal(byId('file-cloud-note').hidden, false);
    assert.match(byId('selected-file-details').textContent, /音频/);
    const addedTasks = [];
    TaskHistoryManager.addTask = task => addedTasks.push(task);
    const cloudUpload = byId('file-submit').emit('click');
    await flush();
    assert.equal(uploadArgs.options.body.get('transcription_strategy'), 'cloud');
    finishUpload(new Response(JSON.stringify({ code: 202, data: { task_id: 'task-file', view_token: 'safe-file-token' } }), {
        status: 200, headers: { 'Content-Type': 'application/json' },
    }));
    await cloudUpload;
    assert.equal(window.location.href, '/view/safe-file-token');
    assert.equal(addedTasks[0].title, 'lesson.mp3');
    assert.equal(addedTasks[0].type, 'video');

    strategy = 'local';
    byId('file-input').files = [{ name: 'local-video.mp4', type: 'video/mp4', size: 8192 }];
    byId('file-input').emit('change');
    const localUpload = byId('file-submit').emit('click');
    await flush();
    assert.equal(uploadArgs.url, '/api/study/upload');
    finishUpload(new Response(JSON.stringify({ code: 202, data: { task_id: 'local-task', view_token: 'local-view-token' } }), {
        status: 200, headers: { 'Content-Type': 'application/json' },
    }));
    await localUpload;
    assert.equal(window.location.href, '/view/local-view-token');
    assert.equal(addedTasks[1].task_id, 'local-task');
    assert.equal(addedTasks[1].title, 'local-video.mp4');
    assert.equal(addedTasks[1].type, 'video');

    byId('file-remove').emit('click');
    assert.equal(byId('file-actions').hidden, true);
    byId('file-input').files = [{ name: 'archive.zip', size: 2048 }];
    byId('file-input').emit('change');
    assert.match(byId('file-upload-status').textContent, /格式/);
    assert.equal(byId('file-actions').hidden, true);

    let abortSignal;
    global.fetch = (url, options) => {
        abortSignal = options.signal;
        return new Promise((resolve, reject) => {
            options.signal.addEventListener('abort', () => reject(Object.assign(new Error('Aborted'), { name: 'AbortError' })));
        });
    };
    byId('file-input').files = [{ name: 'cancel-me.mp3', type: 'audio/mpeg', size: 1024 }];
    byId('file-input').emit('change');
    const cancelledUpload = byId('file-submit').emit('click');
    await flush();
    byId('file-cancel').emit('click');
    await cancelledUpload;
    assert.equal(abortSignal.aborted, true);
    assert.equal(byId('file-submit').disabled, false);
    assert.equal(byId('selected-file-name').textContent, 'cancel-me.mp3');
    assert.match(byId('file-upload-status').textContent, /已取消/);

    console.log('Single-study import behavior checks passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
