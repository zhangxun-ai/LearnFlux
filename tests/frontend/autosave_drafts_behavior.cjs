const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const today = '2026-11-06';
const yesterday = '2026-11-05';
const root = path.resolve(__dirname, '../../src/web/static/js');
const tick = () => new Promise(resolve => setImmediate(resolve));

function browser(memory = new Map()) {
    const timers = new Map();
    const requests = [];
    let timerId = 0;
    const context = {
        Headers, URLSearchParams, FormData,
        LearnFluxTime: {dateKey: () => today, parse: value => Date.parse(value)},
        localStorage: {
            getItem: key => memory.get(key) ?? null,
            setItem: (key, value) => memory.set(key, value),
            removeItem: key => memory.delete(key),
        },
        fetch(url, options = {}) {
            return new Promise(resolve => requests.push({
                url,
                method: options.method || 'GET',
                body: options.body && JSON.parse(options.body),
                reply(data, status = 200) {
                    resolve({ok: status < 400, status, json: async () => ({code: status, data})});
                },
            }));
        },
        setTimeout(callback, delay) {
            timers.set(++timerId, {callback, delay});
            return timerId;
        },
        clearTimeout: id => timers.delete(id),
    };
    context.window = {
        LearnFluxAuth: {ready: Promise.resolve({authenticated: true}), getTokenPlaceholder: () => 'session'},
        location: {pathname: '/review/daily', hash: '', search: ''},
        setTimeout: context.setTimeout,
    };
    return {
        context, memory, requests,
        runTimers(delay) {
            for (const [id, timer] of timers) {
                if (timer.delay !== delay) continue;
                timers.delete(id);
                timer.callback();
            }
        },
    };
}

function element() {
    const listeners = {};
    return {
        value: '',
        dataset: {},
        classList: {add() {}, remove() {}},
        addEventListener: (name, listener) => { listeners[name] = listener; },
        emit: (name, event) => listeners[name](event),
    };
}

function setupJournal(memory, initialText = '', handoff = false) {
    const page = browser(memory);
    const document = element();
    const editor = element();
    editor.value = initialText;
    if (handoff) editor.dataset.focusHandoff = 'true';
    const history = element();
    const type = element();
    const ids = {'focus-editor': editor, 'journal-history-list': history, 'journal-type-select': type};
    document.getElementById = id => ids[id] ?? null;
    document.querySelector = () => null;
    document.querySelectorAll = () => [];
    page.context.document = document;
    vm.runInNewContext(fs.readFileSync(path.join(root, 'focus-journal.js'), 'utf8'), page.context);
    document.emit('DOMContentLoaded');
    return {
        ...page, editor, type,
        edit(value) { editor.value = value; editor.emit('input'); },
        select(date, type = 'daily') {
            const card = {dataset: {entryDate: date, entryType: type}};
            history.emit('click', {target: {closest: () => card}});
        },
    };
}

async function journalDrafts() {
    const page = setupJournal();
    await tick();
    page.requests.shift().reply({body: 'Stored today'});
    await tick();

    page.edit('New draft for today');
    page.select(yesterday);
    await tick();
    const saveToday = page.requests.shift();
    assert.equal(saveToday.method, 'POST');
    assert.equal(saveToday.body.entry_date, today);
    assert.equal(saveToday.body.body, 'New draft for today');
    const loadYesterday = page.requests.shift();
    assert.match(loadYesterday.url, new RegExp(yesterday));
    page.edit('Edit while yesterday is loading');
    loadYesterday.reply({body: 'Stale response for yesterday'});
    await tick();
    assert.equal(page.editor.value, 'Edit while yesterday is loading');

    // Both days survive a reload even though neither save has been confirmed.
    const reloaded = setupJournal(page.memory, 'Unscoped legacy text');
    assert.equal(reloaded.editor.value, 'New draft for today');
    reloaded.select(yesterday);
    assert.equal(reloaded.editor.value, 'Edit while yesterday is loading');

    page.type.value = 'note';
    page.type.emit('change');
    await tick();
    const saveYesterday = page.requests.shift();
    assert.equal(saveYesterday.body.entry_date, yesterday);
    assert.equal(saveYesterday.body.entry_type, 'daily');
    assert.equal(saveYesterday.body.body, 'Edit while yesterday is loading');
    const loadNote = page.requests.shift();
    assert.match(loadNote.url, /entry_type=note/);
    loadNote.reply(null);
    saveToday.reply({updated_at: '2026-11-06T08:00:00Z'});
    saveYesterday.reply({updated_at: '2026-11-06T08:00:01Z'});
    await tick();
    assert.equal(page.editor.value, '');

    page.edit('First note');
    page.runTimers(700);
    await tick();
    const saveFirst = page.requests.shift();
    page.edit('Latest note');
    page.runTimers(700);
    await tick();
    assert.equal(page.requests.length, 0);
    saveFirst.reply({});
    await tick();
    const saveLatest = page.requests.shift();
    assert.equal(saveLatest.body.entry_type, 'note');
    assert.equal(saveLatest.body.body, 'Latest note');
    saveLatest.reply(null, 500);
    await tick();
    const retryPage = setupJournal(page.memory);
    retryPage.select(yesterday, 'note');
    assert.equal(retryPage.editor.value, 'Latest note');
    assert.equal(setupJournal(page.memory, 'Article handoff', true).editor.value, 'Article handoff');

    page.edit('Note retry');
    page.runTimers(700);
    await tick();
    const noteRetry = page.requests.shift();
    const todayTab = setupJournal(page.memory);
    todayTab.edit('Today in another tab');
    noteRetry.reply({});
    await tick();
    assert.equal(setupJournal(page.memory).editor.value, 'Today in another tab');
    assert.equal(
        setupJournal(page.memory, 'New article handoff', true).editor.value,
        'Today in another tab\n\nNew article handoff',
    );
    assert.equal(setupJournal(page.memory).editor.value, 'Today in another tab\n\nNew article handoff');
}

function legacyHandoff() {
    const text = 'vta_focus_studio_text';
    const inbox = 'vta_focus_studio_inbox';
    const memory = new Map([
        [text, 'Older unscoped draft'],
        [inbox, JSON.stringify({text: 'Incoming article'})],
    ]);
    const page = browser(memory);
    const source = fs.readFileSync(path.join(root, 'focus-studio.js'), 'utf8');
    const start = source.indexOf('    function loadInitialText() {');
    const end = source.indexOf('    function bindEvents() {', start);
    const context = vm.createContext({
        STORAGE: {text, inbox, savedAt: 'vta_focus_studio_saved_at'},
        editor: element(),
        document: {getElementById: () => element()},
        localStorage: page.context.localStorage,
    });
    vm.runInContext(source.slice(start, end), context);
    const incoming = context.loadInitialText();
    assert.equal(incoming, 'Incoming article');
    assert.equal(memory.get(text), 'Older unscoped draft');
    assert.equal(
        setupJournal(memory, incoming, Boolean(context.editor.dataset.focusHandoff)).editor.value,
        'Older unscoped draft\n\nIncoming article',
    );
}

function reviewPage(memory) {
    const page = browser(memory);
    const node = {querySelector: () => ({textContent: ''})};
    const saveState = {firstElementChild: {}, lastElementChild: {}};
    page.context.document = {
        querySelector: () => node,
        getElementById: id => id === 'review-save-state' ? saveState : node,
    };
    const source = fs.readFileSync(path.join(root, 'review.js'), 'utf8');
    const instrumented = source.replace(/    init\(\);\s*\}\)\(\);\s*$/, `    window.testReview = {
        scheduleDailySave, saveDailyCard, readDraft,
    };
})();`);
    vm.runInNewContext(instrumented, page.context);
    return {...page, state: page.context.window.LearnFluxReviewState, ...page.context.window.testReview};
}

async function reviewDrafts() {
    const page = reviewPage();
    const item = {id: 'a', fact: 'Saved'};
    page.state.daily = {items: [item]};
    page.state.dailyEventId = item.id;
    const input = {dataset: {field: 'fact'}, value: 'First edit'};
    const card = {
        dataset: {eventId: item.id},
        querySelectorAll: selector => selector === '[data-field]' ? [input] : [],
        querySelector: () => ({textContent: ''}),
    };

    page.scheduleDailySave(card);
    page.runTimers(800);
    const first = page.requests.shift();
    assert.equal(first.body.fact, 'First edit');
    input.value = 'Later edit';
    page.scheduleDailySave(card);
    page.runTimers(800);
    assert.equal(page.requests.length, 0, 'The next patch must wait for the first');
    first.reply({record: {...item, fact: 'First edit'}});
    await tick();
    const later = page.requests.shift();
    assert.equal(later.body.fact, 'Later edit');
    assert.equal(page.state.daily.items[0].fact, 'Later edit');

    // A later server timestamp for the older write does not hide an unsaved draft.
    const reopened = reviewPage(page.memory);
    assert.equal(reopened.readDraft({...item, updated_at: '2099-01-01T00:00:00Z'}).fact, 'Later edit');
    later.reply(null, 500);
    await tick();
    assert.equal(page.readDraft(item).fact, 'Later edit');

    const saved = page.saveDailyCard(card);
    const retry = page.requests.shift();
    // Moving to a different day during the request keeps the visible records unchanged.
    page.state.daily = {items: [{id: 'b', fact: 'Different date'}]};
    page.state.dailyEventId = 'b';
    retry.reply({record: {...item, fact: 'Later edit'}});
    await saved;
    assert.equal(page.state.daily.items[0].fact, 'Different date');
    assert.equal(page.memory.has('learnflux_review_draft:a'), false);
}

(async () => {
    await journalDrafts();
    legacyHandoff();
    await reviewDrafts();
    console.log('Journal and review autosave behavior checks passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
