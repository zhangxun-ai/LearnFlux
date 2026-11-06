(function () {
    'use strict';

    const LOCAL_DRAFT_PREFIX = 'vta_focus_studio_journal_draft:';
    const LOCAL_DRAFT_MIGRATED_KEY = 'vta_focus_studio_journal_draft_migrated';
    const LOCAL_TEXT_KEY = 'vta_focus_studio_text';
    const LOCAL_SAVED_AT_KEY = 'vta_focus_studio_saved_at';

    const TYPE_LABELS = {
        daily: '日记',
        note: '随笔',
        weekly_plan: '周计划',
        weekly_review: '周复盘',
        monthly_plan: '月计划',
        monthly_review: '月复盘'
    };

    const state = {
        date: todayISO(),
        month: todayISO().slice(0, 7),
        entryType: 'daily',
        drafts: new Map(),
        savesInFlight: new Set(),
        saveTimer: null,
        closeTimer: null,
        entryLoad: 0,
        historyLoaded: false
    };

    const els = {};

    function bindElements() {
        els.editor = document.getElementById('focus-editor');
        els.saveStatus = document.getElementById('save-status');
        els.dateLabel = document.getElementById('journal-date-label');
        els.typeSelect = document.getElementById('journal-type-select');
        els.historyList = document.getElementById('journal-history-list');
        els.historyNote = document.getElementById('journal-history-note');
        els.reviewQuestion = document.getElementById('journal-review-question');
        els.reviewResult = document.getElementById('journal-review-result');
        els.sidecar = document.getElementById('journal-sidecar');
        els.shell = document.querySelector('.journal-shell');
        els.sidecarClose = document.getElementById('journal-sidecar-close');
        els.openButtons = document.querySelectorAll('[data-journal-open]');
        els.tabs = document.querySelectorAll('[data-journal-tab]');
        els.panels = document.querySelectorAll('[data-journal-panel]');
    }

    function getToken() {
        return window.LearnFluxAuth
            ? window.LearnFluxAuth.getTokenPlaceholder()
            : '';
    }

    async function apiJSON(url, options) {
        const token = getToken();
        if (!token) {
            throw new Error('NO_TOKEN');
        }
        const init = options || {};
        const headers = new Headers(init.headers || {});
        headers.set('Authorization', 'Bearer ' + token);
        if (init.body && !(init.body instanceof FormData)) {
            headers.set('Content-Type', 'application/json');
        }
        const response = await fetch(url, { ...init, headers });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || payload.code >= 400) {
            throw new Error(payload.detail || payload.message || '请求失败');
        }
        return payload.data;
    }

    function todayISO() {
        return LearnFluxTime.dateKey();
    }

    function formatDateLabel(value) {
        const date = new Date(value + 'T00:00:00+08:00');
        if (Number.isNaN(date.getTime())) return value;
        return date.toLocaleDateString('zh-CN', { timeZone: 'Asia/Shanghai',
            year: 'numeric',
            month: 'long',
            day: 'numeric',
            weekday: 'short'
        });
    }

    function formatClock(value) {
        if (!value) return '';
        const date = new Date(LearnFluxTime.parse(value));
        if (Number.isNaN(date.getTime())) return '';
        return date.toLocaleTimeString('zh-CN', { timeZone: 'Asia/Shanghai',
            hour: '2-digit',
            minute: '2-digit',
            hour12: false
        });
    }

    function setStatus(text) {
        if (!els.saveStatus) return;
        els.saveStatus.textContent = text;
        els.saveStatus.classList.add('is-fresh');
        window.setTimeout(() => els.saveStatus.classList.remove('is-fresh'), 900);
    }

    function updateMeta() {
        if (els.dateLabel) els.dateLabel.textContent = formatDateLabel(state.date);
        if (els.typeSelect) els.typeSelect.value = state.entryType;
    }

    function titleFromBody(body, date = state.date, type = state.entryType) {
        const line = String(body || '').split('\n').map((item) => item.trim()).find(Boolean);
        if (line) return line.slice(0, 80);
        return date + ' ' + (TYPE_LABELS[type] || '记录');
    }

    function shortBody(body) {
        const text = String(body || '').replace(/\s+/g, ' ').trim();
        return text.length > 54 ? text.slice(0, 54) + '...' : text;
    }

    function entryKey() {
        return state.date + ':' + state.entryType;
    }

    function readDraft(key) {
        if (state.drafts.has(key)) return state.drafts.get(key);
        try {
            const draft = JSON.parse(localStorage.getItem(LOCAL_DRAFT_PREFIX + key));
            if (draft) state.drafts.set(key, draft);
            return draft;
        } catch (error) {
            return null;
        }
    }

    function clearDraft(key, draft) {
        state.drafts.delete(key);
        try {
            const storageKey = LOCAL_DRAFT_PREFIX + key;
            if (localStorage.getItem(storageKey) === JSON.stringify(draft)) {
                localStorage.removeItem(storageKey);
            }
        } catch (error) {}
    }

    function captureDraft() {
        const body = els.editor.value;
        const draft = {
            entry_date: state.date,
            entry_type: state.entryType,
            title: titleFromBody(body),
            body
        };
        const key = entryKey();
        state.drafts.set(key, draft);
        try {
            localStorage.setItem(LOCAL_DRAFT_PREFIX + key, JSON.stringify(draft));
        } catch (error) {}
    }

    function scheduleSave() {
        state.entryLoad++;
        const key = entryKey();
        captureDraft();
        setStatus('Local');
        clearTimeout(state.saveTimer);
        state.saveTimer = setTimeout(() => {
            state.saveTimer = null;
            saveEntry(key);
        }, 700);
    }

    async function saveEntry(key) {
        const draft = state.drafts.get(key);
        if (!draft || state.savesInFlight.has(key)) return;
        state.savesInFlight.add(key);
        try {
            await window.LearnFluxAuth?.ready;
            const entry = await apiJSON('/api/journal/entries', {
                method: 'POST',
                body: JSON.stringify(draft)
            });
            state.historyLoaded = false;
            if (state.drafts.get(key) !== draft) return;
            clearDraft(key, draft);
            if (key === entryKey()) {
                const clock = formatClock(entry?.updated_at);
                setStatus(clock ? 'Synced ' + clock : 'Synced');
            }
        } catch (error) {
            if (key === entryKey() && state.drafts.get(key) === draft) {
                setStatus(error.message === 'NO_TOKEN' ? 'Local' : 'Offline');
            }
        } finally {
            state.savesInFlight.delete(key);
            const pending = state.drafts.get(key);
            if (pending && pending !== draft && (key !== entryKey() || state.saveTimer === null)) {
                saveEntry(key);
            }
        }
    }

    async function loadCurrentEntry(legacySavedAt = null) {
        const load = ++state.entryLoad;
        const key = entryKey();
        const draft = readDraft(key);
        updateMeta();
        els.editor.value = draft?.body ?? '';
        if (draft && legacySavedAt === null) {
            setStatus('Local');
            return;
        }
        setStatus('Loading');
        const params = new URLSearchParams({
            entry_date: state.date,
            entry_type: state.entryType
        });
        try {
            await window.LearnFluxAuth?.ready;
            if (load !== state.entryLoad) return;
            const entry = await apiJSON('/api/journal/entry?' + params.toString());
            if (load !== state.entryLoad) return;
            if (draft) {
                // The pre-journal fallback had one draft without a date or type.
                if (!entry || legacySavedAt > LearnFluxTime.parse(entry.updated_at)) {
                    setStatus('Local');
                    return;
                }
                clearDraft(key, draft);
            }
            if (entry && typeof entry.body === 'string') {
                els.editor.value = entry.body;
                const clock = formatClock(entry.updated_at);
                setStatus(clock ? 'Synced ' + clock : 'Synced');
            } else {
                setStatus('Ready');
            }
        } catch (error) {
            if (load === state.entryLoad) {
                setStatus(error.message === 'NO_TOKEN' ? 'Local' : 'Offline');
            }
        }
    }

    function selectEntry(date, type) {
        if (date === state.date && type === state.entryType) return;
        if (state.saveTimer !== null) {
            clearTimeout(state.saveTimer);
            state.saveTimer = null;
            saveEntry(entryKey());
        }
        state.date = date;
        state.month = date.slice(0, 7);
        state.entryType = type;
        loadCurrentEntry();
    }

    async function loadHistory() {
        if (!els.historyList || state.historyLoaded) return;
        if (!getToken()) {
            els.historyList.innerHTML = '<div class="journal-empty">先在工作台保存 API 令牌后，历史记录会自动同步。</div>';
            return;
        }
        els.historyList.innerHTML = '<div class="journal-empty">正在读取本月记录...</div>';
        try {
            const params = new URLSearchParams({ month: state.month, limit: '40' });
            const data = await apiJSON('/api/journal/entries?' + params.toString());
            renderHistory((data && data.items) || []);
            state.historyLoaded = true;
        } catch (error) {
            els.historyList.innerHTML = '<div class="journal-empty">历史记录暂时不可用。</div>';
        }
    }

    function renderHistory(entries) {
        if (!entries.length) {
            els.historyList.innerHTML = '<div class="journal-empty">本月还没有保存的记录。</div>';
            return;
        }
        els.historyList.innerHTML = entries.map((entry) => {
            const entryDate = escapeHTML(entry.entry_date);
            const entryType = escapeHTML(entry.entry_type);
            const label = escapeHTML(TYPE_LABELS[entry.entry_type] || entry.entry_type);
            const title = escapeHTML(entry.title || titleFromBody(entry.body, entry.entry_date, entry.entry_type));
            const preview = escapeHTML(shortBody(entry.body));
            return '<button type="button" class="journal-history-card" ' +
                'data-entry-date="' + entryDate + '" data-entry-type="' + entryType + '">' +
                '<span>' + entryDate + ' · ' + label + '</span>' +
                '<strong>' + title + '</strong>' +
                (preview ? '<small>' + preview + '</small>' : '') +
                '</button>';
        }).join('');
    }

    function escapeHTML(value) {
        return String(value || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function mondayOf(dateValue) {
        const day = new Date(dateValue + 'T00:00:00Z').getUTCDay() || 7;
        return LearnFluxTime.shiftDate(dateValue, 1 - day);
    }

    function monthStart(dateValue) {
        return dateValue.slice(0, 7) + '-01';
    }

    function toISO(date) {
        return LearnFluxTime.dateKey(date);
    }

    async function runReview(range) {
        if (!els.reviewResult || !els.reviewQuestion) return;
        if (!getToken()) {
            els.reviewResult.textContent = '先在工作台保存 API 令牌后，AI 才能读取你的记录做复盘。';
            return;
        }
        const rangeStart = range === 'month' ? monthStart(state.date) : mondayOf(state.date);
        const question = els.reviewQuestion.value.trim();
        els.reviewResult.textContent = '正在结合记录复盘...';
        try {
            const review = await apiJSON('/api/journal/reviews', {
                method: 'POST',
                body: JSON.stringify({
                    range_start: rangeStart,
                    range_end: state.date,
                    question
                })
            });
            els.reviewResult.textContent = review.answer || 'AI 没有返回内容。';
        } catch (error) {
            els.reviewResult.textContent = error.message || 'AI 复盘生成失败。';
        }
    }

    function setActivePanel(panel) {
        const target = panel === 'review' ? 'review' : 'history';
        els.tabs.forEach((button) => {
            const active = button.dataset.journalTab === target;
            button.classList.toggle('active', active);
            button.setAttribute('aria-selected', active ? 'true' : 'false');
            button.tabIndex = active ? 0 : -1;
        });
        els.panels.forEach((panelEl) => {
            const active = panelEl.dataset.journalPanel === target;
            panelEl.classList.toggle('active', active);
            panelEl.hidden = !active;
        });
        els.openButtons.forEach((button) => {
            const active = button.dataset.journalOpen === target;
            button.classList.toggle('active', active);
            button.setAttribute('aria-expanded', active ? 'true' : 'false');
        });
    }

    function openPanel(panel) {
        const target = panel === 'review' ? 'review' : 'history';
        cancelPanelClose();
        document.body.dataset.journalSidecar = target;
        if (els.sidecar) {
            els.sidecar.setAttribute('aria-hidden', 'false');
        }
        setActivePanel(target);
        if (target === 'history') {
            loadHistory();
        }
    }

    function isPanelOpen(panel) {
        const target = panel === 'review' ? 'review' : 'history';
        return document.body.dataset.journalSidecar === target;
    }

    function togglePanel(panel) {
        if (isPanelOpen(panel)) {
            closePanel();
            return;
        }
        openPanel(panel);
    }

    function cancelPanelClose() {
        if (!state.closeTimer) return;
        clearTimeout(state.closeTimer);
        state.closeTimer = null;
    }

    function schedulePanelClose() {
        if (!document.body.dataset.journalSidecar) return;
        cancelPanelClose();
        state.closeTimer = setTimeout(closePanel, 180);
    }

    function closePanel() {
        cancelPanelClose();
        delete document.body.dataset.journalSidecar;
        if (els.sidecar) {
            els.sidecar.setAttribute('aria-hidden', 'true');
        }
        els.openButtons.forEach((button) => {
            button.classList.remove('active');
            button.setAttribute('aria-expanded', 'false');
        });
    }

    function bindEvents() {
        if (els.editor) {
            els.editor.addEventListener('input', scheduleSave);
        }
        if (els.typeSelect) {
            els.typeSelect.addEventListener('change', () => {
                selectEntry(state.date, els.typeSelect.value || 'daily');
            });
        }
        const journalTabs = Array.from(els.tabs);
        journalTabs.forEach((button) => {
            button.addEventListener('click', () => openPanel(button.dataset.journalTab));
            button.addEventListener('keydown', (event) => {
                const currentIndex = journalTabs.indexOf(button);
                let nextIndex = currentIndex;
                if (event.key === 'ArrowRight') nextIndex = (currentIndex + 1) % journalTabs.length;
                else if (event.key === 'ArrowLeft') nextIndex = (currentIndex - 1 + journalTabs.length) % journalTabs.length;
                else if (event.key === 'Home') nextIndex = 0;
                else if (event.key === 'End') nextIndex = journalTabs.length - 1;
                else return;
                event.preventDefault();
                journalTabs[nextIndex].focus();
                openPanel(journalTabs[nextIndex].dataset.journalTab);
            });
        });
        els.openButtons.forEach((button) => {
            button.addEventListener('click', () => togglePanel(button.dataset.journalOpen));
        });
        if (els.shell) {
            els.shell.addEventListener('mouseenter', cancelPanelClose);
            els.shell.addEventListener('mouseleave', schedulePanelClose);
        }
        if (els.sidecarClose) {
            els.sidecarClose.addEventListener('click', closePanel);
        }
        if (els.historyList) {
            els.historyList.addEventListener('click', (event) => {
                const card = event.target.closest('.journal-history-card');
                if (!card) return;
                selectEntry(card.dataset.entryDate || state.date, card.dataset.entryType || 'daily');
            });
        }
        document.querySelectorAll('[data-review-range]').forEach((button) => {
            button.addEventListener('click', () => runReview(button.dataset.reviewRange));
        });
        document.addEventListener('keydown', (event) => {
            if (event.key === 'Escape') {
                closePanel();
            }
        });
    }

    function init() {
        bindElements();
        if (!els.editor) return;
        els.editor.dataset.journalAutosave = 'true';
        const handoff = els.editor.dataset.focusHandoff;
        let legacyText = '';
        let legacySavedAt = null;
        try {
            if (!localStorage.getItem(LOCAL_DRAFT_MIGRATED_KEY) && !readDraft(entryKey())) {
                if (handoff) {
                    legacyText = localStorage.getItem(LOCAL_TEXT_KEY) || '';
                } else if (els.editor.value) {
                    legacySavedAt = LearnFluxTime.parse(localStorage.getItem(LOCAL_SAVED_AT_KEY)) || 0;
                    captureDraft();
                }
            }
            localStorage.setItem(LOCAL_DRAFT_MIGRATED_KEY, '1');
        } catch (error) {}
        if (handoff) {
            const previous = readDraft(entryKey())?.body ?? legacyText;
            if (previous && previous !== els.editor.value) {
                els.editor.value = previous + '\n\n' + els.editor.value;
            }
            captureDraft();
        }
        bindEvents();
        loadCurrentEntry(legacySavedAt);
    }

    document.addEventListener('DOMContentLoaded', init);
})();
