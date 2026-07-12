(function () {
    'use strict';

    function requestedDocumentTypes(action) {
        return action === 'full-note' ? ['full_note'] : ['overview'];
    }

    window.TranscriptVisualReader = {
        requestedDocumentTypes: requestedDocumentTypes,
    };

    if (typeof document === 'undefined') return;

    const STORAGE_KEY = 'vta_bearer_token';
    const ENCRYPTION_KEY = 'vta_encrypt_key_2024';
    const POLL_MS = 2500;
    const root = document.getElementById('transcript-immersive-reader');
    const textButton = document.getElementById('transcript-reader-text');
    const visualButton = document.getElementById('transcript-reader-visual');
    const summaryData = document.getElementById('transcript-summary-data');
    if (!root || !window.VisualLearning) return;

    const viewToken = String(root.dataset.viewToken || '');
    const title = String(root.dataset.readerTitle || '内容总结');
    let summary = '';
    try {
        summary = JSON.parse(summaryData ? summaryData.textContent : '""') || '';
    } catch (_error) {
        summary = summaryData ? summaryData.textContent : '';
    }

    const reader = window.VisualLearning.createReaderState(viewToken, 'text');
    const documents = { overview: null, full_note: null };
    const states = { overview: null, full_note: null };
    const loading = new Set();
    const pollTimers = { overview: null, full_note: null };
    let isOpen = false;
    let trigger = null;
    let scrollY = 0;

    function decryptToken(encoded) {
        if (!encoded) return '';
        try {
            const reversed = encoded.split('').reverse().join('');
            const decoded = decodeURIComponent(escape(atob(reversed)));
            return decoded.replace(ENCRYPTION_KEY, '');
        } catch (_error) {
            return encoded;
        }
    }

    function getToken() {
        return decryptToken(localStorage.getItem(STORAGE_KEY))
            || localStorage.getItem('api_key')
            || '';
    }

    async function apiJSON(url, options) {
        const token = getToken();
        if (!token) throw new Error('请先在工作台设置 API 令牌');
        const init = options || {};
        const headers = new Headers(init.headers || {});
        headers.set('Authorization', `Bearer ${token}`);
        if (init.body) headers.set('Content-Type', 'application/json');
        const response = await fetch(url, { ...init, headers: headers });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || Number(payload.code) >= 400) {
            throw new Error(payload.detail || payload.message || '图解请求失败');
        }
        return payload.data || {};
    }

    function statusText(documentType) {
        if (loading.has(documentType)) return '正在请求生成…';
        const state = states[documentType] || {};
        if (state.uiError) return state.uiError;
        const attempt = state.latest_attempt || {};
        if (attempt.status === 'failed' || state.phase === 'failed') {
            return attempt.error_message || '生成失败，可重试';
        }
        if (attempt.status === 'generating' || attempt.status === 'pending' || state.phase === 'generating_visual') {
            const progress = state.workflow_progress && state.workflow_progress.overall_percent;
            return Number.isFinite(Number(progress)) ? `生成中 ${Math.round(Number(progress))}%` : '生成中…';
        }
        if (documents[documentType]) return state.stale ? '旧版仍可查看，新版生成中' : '已完成';
        return documentType === 'overview' ? '全局图解尚未生成' : '逐段图解尚未生成';
    }

    function storeState(documentType, state) {
        states[documentType] = state || {};
        const record = state && state.document;
        if (record && record.status === 'success' && record.document_json) {
            documents[documentType] = record.document_json;
        }
        renderReader();
    }

    function sections() {
        const state = states.full_note || states.overview || {};
        return state.interpretation_sections || [];
    }

    function renderReader() {
        if (!isOpen) return;
        const snapshot = reader.snapshot();
        window.VisualLearning.renderImmersiveReader(root, {
            mode: snapshot.mode,
            sectionId: snapshot.sectionId,
            title: title,
            contextLabel: '单节解读',
            globalMarkdown: summary,
            sections: sections(),
            overview: documents.overview,
            fullNote: documents.full_note,
            fullNoteStale: Boolean(states.full_note && states.full_note.stale),
            overviewStatus: statusText('overview'),
            fullNoteStatus: statusText('full_note'),
            theme: 'study-notes'
        }, {
            onClose: closeReader,
            onModeChange: (mode) => {
                reader.setMode(mode);
                renderReader();
                if (mode === 'visual' && !documents.overview) ensureDocument('overview', true);
            },
            onSectionChange: (sectionId) => {
                reader.setSection(sectionId);
                renderReader();
            },
            onGenerateOverview: () => ensureDocument('overview', true),
            onGenerateFullNote: () => ensureDocument('full_note', true),
            onExport: () => {
                const diagram = window.VisualLearning.activeDiagram(root);
                if (diagram) window.VisualLearning.exportSvg(diagram, `${title}-图解.svg`);
            }
        });
    }

    function stopPoll(documentType) {
        window.clearTimeout(pollTimers[documentType]);
        pollTimers[documentType] = null;
    }

    function schedulePoll(documentType, generation) {
        stopPoll(documentType);
        pollTimers[documentType] = window.setTimeout(async () => {
            if (!reader.accepts(viewToken, generation)) return;
            try {
                const state = await apiJSON(
                    `/api/visual-learning/study/${encodeURIComponent(viewToken)}?document_type=${encodeURIComponent(documentType)}`
                );
                if (!reader.accepts(viewToken, generation)) return;
                storeState(documentType, state);
                const attempt = state.latest_attempt || {};
                if (attempt.status === 'pending' || attempt.status === 'generating' || state.phase === 'generating_visual') {
                    schedulePoll(documentType, generation);
                }
            } catch (error) {
                if (!reader.accepts(viewToken, generation)) return;
                storeState(documentType, { ...(states[documentType] || {}), uiError: error.message });
            }
        }, POLL_MS);
    }

    async function requestGeneration(documentType, force, generation) {
        loading.add(documentType);
        renderReader();
        try {
            const state = await apiJSON(
                `/api/visual-learning/study/${encodeURIComponent(viewToken)}/generate`,
                {
                    method: 'POST',
                    body: JSON.stringify({
                        document_type: documentType,
                        style: 'study-notes',
                        diagram_type: 'auto',
                        force: Boolean(force)
                    })
                }
            );
            if (!reader.accepts(viewToken, generation)) return;
            storeState(documentType, state);
            const attempt = state.latest_attempt || {};
            if (attempt.status === 'pending' || attempt.status === 'generating' || state.phase === 'generating_visual') {
                schedulePoll(documentType, generation);
            }
        } catch (error) {
            if (!reader.accepts(viewToken, generation)) return;
            storeState(documentType, { ...(states[documentType] || {}), uiError: error.message });
        } finally {
            if (reader.accepts(viewToken, generation)) {
                loading.delete(documentType);
                renderReader();
            }
        }
    }

    async function ensureDocument(documentType, generateIfMissing) {
        if (loading.has(documentType)) return;
        const generation = reader.generation();
        try {
            const state = await apiJSON(
                `/api/visual-learning/study/${encodeURIComponent(viewToken)}?document_type=${encodeURIComponent(documentType)}`
            );
            if (!reader.accepts(viewToken, generation)) return;
            storeState(documentType, state);
            const attempt = state.latest_attempt || {};
            if (attempt.status === 'pending' || attempt.status === 'generating' || state.phase === 'generating_visual') {
                schedulePoll(documentType, generation);
                return;
            }
            if (generateIfMissing && (!state.document || state.stale || attempt.status === 'failed')) {
                await requestGeneration(documentType, Boolean(state.stale || attempt.status === 'failed'), generation);
            }
        } catch (error) {
            if (!reader.accepts(viewToken, generation)) return;
            if (generateIfMissing) await requestGeneration(documentType, false, generation);
            else storeState(documentType, { uiError: error.message });
        }
    }

    function openReader(mode, source) {
        reader.setMode(mode);
        isOpen = true;
        trigger = source || document.activeElement;
        scrollY = window.scrollY;
        root.hidden = false;
        document.body.classList.add('vl-reader-open');
        renderReader();
        ensureDocument('overview', mode === 'visual');
    }

    function closeReader() {
        if (!isOpen) return;
        isOpen = false;
        reader.invalidate();
        stopPoll('overview');
        stopPoll('full_note');
        root.hidden = true;
        root.replaceChildren();
        document.body.classList.remove('vl-reader-open');
        window.scrollTo({ top: scrollY, behavior: 'auto' });
        if (trigger && typeof trigger.focus === 'function') trigger.focus({ preventScroll: true });
    }

    if (textButton) textButton.addEventListener('click', () => openReader('text', textButton));
    if (visualButton) {
        visualButton.addEventListener('click', () => {
            if (documents.overview) {
                openReader('visual', visualButton);
            } else {
                startInlineGeneration();
            }
        });
    }
    
    async function startInlineGeneration() {
        if (loading.has('overview')) return;
        visualButton.disabled = true;
        
        // Polling will update button state through a callback we add to storeState, 
        // but for simplicity we can just manually poll here or let the existing logic run.
        // Actually, the cleanest way is to hook into storeState.
        ensureDocument('overview', true);
    }
    
    // We need to update the button text when state changes.
    // Let's hook into storeState.
    const originalStoreState = storeState;
    storeState = function(documentType, state) {
        originalStoreState(documentType, state);
        if (documentType === 'overview' && visualButton) {
            if (documents.overview) {
                visualButton.disabled = false;
                visualButton.textContent = '查看图解';
                // Automatically open if we were generating inline and just finished
                if (!isOpen && visualButton.dataset.autoOpen === 'true') {
                    visualButton.dataset.autoOpen = 'false';
                    openReader('visual', visualButton);
                }
            } else {
                const st = statusText('overview');
                if (st.includes('生成中') || st.includes('正在请求')) {
                    visualButton.disabled = true;
                    visualButton.textContent = st;
                    visualButton.dataset.autoOpen = 'true';
                } else if (st.includes('尚未生成') || st.includes('失败')) {
                    visualButton.disabled = false;
                    visualButton.textContent = '一键图解';
                    visualButton.dataset.autoOpen = 'false';
                }
            }
        }
    };

    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && isOpen) {
            event.preventDefault();
            closeReader();
        }
    });
})();
