(function () {
    'use strict';

    const DOCUMENT_TYPE = 'diagram';
    const ACTIVE_PHASES = new Set([
        'source_processing',
        'analyzing_outline',
        'selecting_evidence',
        'generating_visual',
        'validating',
    ]);

    function requestedDocumentTypes() {
        return [DOCUMENT_TYPE];
    }

    function latestAttemptFor(state) {
        return (state && state.latest_attempt) || {};
    }

    function progressPayload(state) {
        return (state && (
            state.workflow_progress
            || state.generation_progress
            || state.source_progress
        )) || {};
    }

    function progressLabel(state, fallback) {
        const progress = progressPayload(state);
        const phase = String((state && state.phase) || '');
        const stage = String(progress.stage || phase || '');
        return progress.stage_label
            || progress.message
            || ({
                source_processing: '正在解析内容，图解会在材料可用后自动开始',
                ready_for_generation: '正在准备图解生成',
                analyzing_outline: '正在建立全文知识架构',
                selecting_evidence: '正在回查原文依据',
                generating_visual: '正在生成完整图解',
                validating: '正在校验图解结构与原文引用',
            }[stage])
            || fallback
            || '正在处理';
    }

    function progressPercent(state) {
        const progress = progressPayload(state);
        const value = Number(
            progress.overall_percent !== undefined
                ? progress.overall_percent
                : progress.percent
        );
        return Number.isFinite(value) ? Math.max(0, Math.min(100, value)) : NaN;
    }

    function isFailedState(state) {
        const attempt = latestAttemptFor(state);
        return Boolean(
            (state && state.uiError)
            || attempt.status === 'failed'
            || (state && state.phase === 'failed')
        );
    }

    function isActiveVisualState(state, localLoading) {
        const attempt = latestAttemptFor(state);
        const phase = String((state && state.phase) || '');
        return Boolean(localLoading)
            || attempt.status === 'pending'
            || attempt.status === 'generating'
            || ACTIVE_PHASES.has(phase);
    }

    window.TranscriptVisualReader = {
        requestedDocumentTypes: requestedDocumentTypes,
        documentType: DOCUMENT_TYPE,
        isActiveVisualState: isActiveVisualState,
        progressLabel: progressLabel,
        progressPercent: progressPercent,
        isFailedState: isFailedState,
    };

    if (typeof document === 'undefined') return;

    const STORAGE_KEY = 'vta_bearer_token';
    const ENCRYPTION_KEY = 'vta_encrypt_key_2024';
    const POLL_MS = 2500;
    const textButton = document.getElementById('transcript-reader-text');
    const visualButton = document.getElementById('transcript-reader-visual');
    const textPanel = document.getElementById('transcript-summary-text-panel');
    const visualPanel = document.getElementById('transcript-summary-visual-panel');
    if (!textButton || !visualButton || !textPanel || !visualPanel || !window.VisualLearning) return;
    const secondarySections = Array.from(document.querySelectorAll('.transcript-secondary-section'));

    const viewToken = String(visualPanel.dataset.viewToken || '');
    const title = String(visualPanel.dataset.readerTitle || '内容总结');
    const reader = window.VisualLearning.createReaderState(viewToken, 'text');
    const documents = { diagram: null };
    const states = { diagram: null };
    const loading = new Set();
    const pollTimers = { diagram: null };
    const autoRetriedFailures = new Set();
    let checkingState = false;

    function node(tag, className, text) {
        const element = document.createElement(tag);
        if (className) element.className = className;
        if (text !== undefined && text !== null) element.textContent = String(text);
        return element;
    }

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

    function latestAttempt() {
        return latestAttemptFor(states.diagram || {});
    }

    function isGenerating() {
        return checkingState || isActiveVisualState(states.diagram || {}, loading.has(DOCUMENT_TYPE));
    }

    function statusText() {
        if (checkingState) return '正在检查图解状态...';
        if (loading.has(DOCUMENT_TYPE)) return '正在请求生成...';
        const state = states.diagram || {};
        if (state.uiError) return state.uiError;
        const attempt = state.latest_attempt || {};
        if (attempt.status === 'failed' || state.phase === 'failed') {
            return attempt.error_message || '生成失败，可重试';
        }
        if (isGenerating()) {
            const progress = progressPercent(state);
            const label = progressLabel(state, '正在生成完整图解');
            return Number.isFinite(progress) ? `${label} ${Math.round(progress)}%` : label;
        }
        if (documents.diagram) return state.stale ? '已有图解可查看，内容变化后可重新生成' : '已生成完整图解';
        return '正在准备图解生成';
    }

    function setActiveMode(mode, generateIfMissing) {
        const visual = mode === 'visual';
        reader.setMode(visual ? 'visual' : 'text');
        textPanel.hidden = visual;
        visualPanel.hidden = !visual;
        secondarySections.forEach((section) => {
            section.hidden = visual;
        });
        textButton.setAttribute('aria-selected', visual ? 'false' : 'true');
        visualButton.setAttribute('aria-selected', visual ? 'true' : 'false');
        textButton.tabIndex = visual ? -1 : 0;
        visualButton.tabIndex = visual ? 0 : -1;
        if (visual) {
            renderVisualPanel();
            ensureDocument(Boolean(generateIfMissing));
        }
    }

    function createAction(label, className, callback) {
        const button = node('button', `transcript-visual-action${className ? ` ${className}` : ''}`, label);
        button.type = 'button';
        button.disabled = isGenerating();
        button.addEventListener('click', callback);
        return button;
    }

    function renderToolbar(shell) {
        const toolbar = node('div', 'transcript-visual-toolbar');
        const left = node('div');
        left.appendChild(node('span', 'transcript-visual-kicker', '图解版'));
        left.appendChild(node('strong', '', title));
        left.appendChild(node('p', 'transcript-visual-status', statusText()));
        toolbar.appendChild(left);

        const actions = node('div', 'transcript-visual-toolbar-actions');
        if (documents.diagram) {
            actions.appendChild(createAction('重新生成', '', () => requestGeneration(true)));
            actions.appendChild(createAction('导出 SVG', '', exportDiagram));
        }
        toolbar.appendChild(actions);
        shell.appendChild(toolbar);
    }

    function renderEmpty(shell) {
        const empty = node('div', 'transcript-visual-empty');
        const generating = isGenerating();
        if (generating) {
            empty.classList.add('is-generating');
            empty.appendChild(node('div', 'vl-spinner'));
            empty.appendChild(node('strong', '', progressLabel(states.diagram || {}, statusText())));
            empty.appendChild(node('p', '', '系统会自动完成解析、证据回查、图解生成和结构校验；生成完成后会直接出现在这里。'));
            empty.appendChild(renderProgress());
            const skeleton = node('div', 'vl-skeleton');
            skeleton.appendChild(node('div', 'vl-skeleton-title'));
            skeleton.appendChild(node('div', 'vl-skeleton-box'));
            skeleton.appendChild(node('div', 'vl-skeleton-box'));
            empty.appendChild(skeleton);
        } else {
            const failed = isFailedState(states.diagram || {});
            empty.appendChild(node('strong', '', failed ? '图解生成遇到问题' : '正在准备图解生成'));
            empty.appendChild(node('p', '', failed
                ? '系统已完成自动尝试，当前仍未生成可用图解。你可以手动重新生成，已有文字解读不会受影响。'
                : '图解会自动开始生成，不需要额外点击。'));
            if (failed) {
                empty.appendChild(createAction('重新生成', 'primary', () => requestGeneration(true)));
            }
        }
        shell.appendChild(empty);
    }

    function renderProgress() {
        const progress = node('div', 'transcript-visual-progress');
        const percent = progressPercent(states.diagram || {});
        const percentText = Number.isFinite(percent) ? `${Math.round(percent)}%` : '准备中';
        const track = node('div', 'transcript-visual-progress-track');
        const fill = node('span', 'transcript-visual-progress-fill');
        fill.style.width = Number.isFinite(percent) ? `${percent}%` : '12%';
        track.appendChild(fill);
        progress.appendChild(track);
        progress.appendChild(node('div', 'transcript-visual-progress-meta', percentText));
        return progress;
    }

    function renderDiagram(shell) {
        const diagramHost = node('div', 'transcript-visual-diagram');
        const diagram = window.VisualLearning.render(diagramHost, documents.diagram, {
            readerMode: 'continuous',
            showInlineSourceRefs: false,
        });
        diagram.classList.add('vl-diagram', 'vl-reader-visual-atlas', 'transcript-summary-diagram');
        diagram.dataset.diagramRole = 'macro';
        diagram.setAttribute('data-focus-state', 'active');
        shell.appendChild(diagramHost);
    }

    function renderVisualPanel() {
        if (visualPanel.hidden) return;
        const shell = node('div', 'transcript-visual-shell');
        renderToolbar(shell);
        if (documents.diagram) renderDiagram(shell);
        else renderEmpty(shell);
        visualPanel.replaceChildren(shell);
    }

    function storeState(state) {
        states.diagram = state || {};
        const record = state && state.document;
        if (record && record.status === 'success' && record.document_json) {
            documents.diagram = record.document_json;
        }
        renderVisualPanel();
    }

    function stopPoll() {
        window.clearTimeout(pollTimers.diagram);
        pollTimers.diagram = null;
    }

    function shouldContinuePolling(state) {
        const attempt = (state && state.latest_attempt) || {};
        const phase = String((state && state.phase) || '');
        return attempt.status === 'pending'
            || attempt.status === 'generating'
            || ACTIVE_PHASES.has(phase);
    }

    function failureKey(state) {
        const attempt = (state && state.latest_attempt) || {};
        return String(attempt.id || attempt.updated_at || attempt.error_message || (state && state.phase) || 'failed');
    }

    async function continueAfterState(state, generation, generateIfMissing) {
        if (!generateIfMissing || !reader.accepts(viewToken, generation)) return;
        if (shouldContinuePolling(state)) {
            schedulePoll(generation, generateIfMissing);
            return;
        }
        const attempt = state.latest_attempt || {};
        const missing = !state.document;
        if (!missing) return;
        if (state.phase === 'ready_for_generation' || !attempt.status) {
            await requestGeneration(false);
            return;
        }
        if (isFailedState(state)) {
            const key = failureKey(state);
            if (!autoRetriedFailures.has(key)) {
                autoRetriedFailures.add(key);
                await requestGeneration(true);
            }
        }
    }

    function schedulePoll(generation, generateIfMissing) {
        stopPoll();
        pollTimers.diagram = window.setTimeout(async () => {
            if (!reader.accepts(viewToken, generation)) return;
            try {
                const state = await apiJSON(
                    `/api/visual-learning/study/${encodeURIComponent(viewToken)}?document_type=${encodeURIComponent(DOCUMENT_TYPE)}`
                );
                if (!reader.accepts(viewToken, generation)) return;
                storeState(state);
                await continueAfterState(state, generation, Boolean(generateIfMissing));
            } catch (error) {
                if (!reader.accepts(viewToken, generation)) return;
                storeState({ ...(states.diagram || {}), uiError: error.message });
            }
        }, POLL_MS);
    }

    async function requestGeneration(force) {
        if (loading.has(DOCUMENT_TYPE)) return;
        const generation = reader.generation();
        loading.add(DOCUMENT_TYPE);
        renderVisualPanel();
        try {
            const state = await apiJSON(
                `/api/visual-learning/study/${encodeURIComponent(viewToken)}/generate`,
                {
                    method: 'POST',
                    body: JSON.stringify({
                        document_type: DOCUMENT_TYPE,
                        style: 'study-notes',
                        diagram_type: 'auto',
                        force: Boolean(force),
                    }),
                }
            );
            if (!reader.accepts(viewToken, generation)) return;
            storeState(state);
            await continueAfterState(state, generation, true);
        } catch (error) {
            if (!reader.accepts(viewToken, generation)) return;
            storeState({ ...(states.diagram || {}), uiError: error.message });
        } finally {
            if (reader.accepts(viewToken, generation)) {
                loading.delete(DOCUMENT_TYPE);
                renderVisualPanel();
            }
        }
    }

    async function ensureDocument(generateIfMissing) {
        if (loading.has(DOCUMENT_TYPE)) return;
        const generation = reader.generation();
        checkingState = true;
        renderVisualPanel();
        try {
            const state = await apiJSON(
                `/api/visual-learning/study/${encodeURIComponent(viewToken)}?document_type=${encodeURIComponent(DOCUMENT_TYPE)}`
            );
            if (!reader.accepts(viewToken, generation)) return;
            checkingState = false;
            storeState(state);
            await continueAfterState(state, generation, Boolean(generateIfMissing));
        } catch (error) {
            if (!reader.accepts(viewToken, generation)) return;
            checkingState = false;
            if (generateIfMissing) await requestGeneration(false);
            else storeState({ uiError: error.message });
        } finally {
            if (reader.accepts(viewToken, generation)) {
                checkingState = false;
                renderVisualPanel();
            }
        }
    }

    function exportDiagram() {
        const diagram = window.VisualLearning.activeDiagram(visualPanel);
        if (diagram) window.VisualLearning.exportSvg(diagram, `${title}-图解.svg`);
    }

    textButton.addEventListener('click', () => setActiveMode('text', false));
    visualButton.addEventListener('click', () => setActiveMode('visual', true));
    [textButton, visualButton].forEach((button) => {
        button.addEventListener('keydown', (event) => {
            let nextButton = null;
            switch (event.key) {
                case 'ArrowRight':
                case 'ArrowDown':
                    nextButton = visualButton;
                    break;
                case 'ArrowLeft':
                case 'ArrowUp':
                    nextButton = textButton;
                    break;
                case 'Home':
                    nextButton = textButton;
                    break;
                case 'End':
                    nextButton = visualButton;
                    break;
                default:
                    return;
            }
            event.preventDefault();
            nextButton.focus();
            setActiveMode(nextButton === visualButton ? 'visual' : 'text', nextButton === visualButton);
        });
    });

    if (window.location.hash === '#summary-visual') {
        setActiveMode('visual', true);
    }
})();
