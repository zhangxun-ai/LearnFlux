(function () {
    'use strict';

    const STORAGE_KEY = 'vta_bearer_token';
    const ENCRYPTION_KEY = 'vta_encrypt_key_2024';
    const state = {
        mode: 'text',
        file: null,
        viewToken: '',
        document: null,
        pollTimer: null,
        startedAt: 0,
        lastOverallPercent: 0,
        readerScrollPending: false,
        evidenceTrigger: null,
        evidenceScrollY: 0,
    };

    const els = {
        tabs: Array.from(document.querySelectorAll('[data-source-mode]')),
        textPanel: document.getElementById('visual-text-panel'),
        filePanel: document.getElementById('visual-file-panel'),
        title: document.getElementById('visual-text-title'),
        content: document.getElementById('visual-text-content'),
        fileInput: document.getElementById('visual-file-input'),
        fileDrop: document.getElementById('visual-file-drop'),
        fileName: document.getElementById('visual-file-name'),
        diagramType: document.getElementById('visual-diagram-type'),
        style: document.getElementById('visual-style'),
        generate: document.getElementById('visual-generate'),
        status: document.getElementById('visual-job-status'),
        statusStage: document.getElementById('visual-progress-stage'),
        statusMeta: document.getElementById('visual-progress-meta'),
        statusFill: document.getElementById('visual-progress-fill'),
        canvas: document.getElementById('visual-canvas'),
        outputTitle: document.getElementById('visual-output-title'),
        recommendations: document.getElementById('visual-recommendations'),
        pageNavigation: document.getElementById('visual-page-navigation'),
        exportButton: document.getElementById('visual-export'),
        printButton: document.getElementById('visual-print-page'),
        history: document.getElementById('visual-history'),
        historyRefresh: document.getElementById('visual-history-refresh'),
        readerExit: document.getElementById('visual-reader-exit'),
        currentSection: document.getElementById('visual-current-section'),
        readingProgress: document.getElementById('visual-reading-progress'),
        readingProgressLabel: document.getElementById('visual-reading-progress-label'),
        readingProgressFill: document.getElementById('visual-reading-progress-fill'),
        evidenceLayer: document.getElementById('visual-evidence-layer'),
        evidenceDrawer: document.getElementById('visual-evidence-drawer'),
        evidenceOverlay: document.getElementById('visual-evidence-overlay'),
        evidenceClose: document.getElementById('visual-evidence-close'),
        evidencePosition: document.getElementById('visual-evidence-position'),
        evidenceTitle: document.getElementById('visual-evidence-title'),
        evidenceClaim: document.getElementById('visual-evidence-claim'),
        evidenceList: document.getElementById('visual-evidence-list'),
    };

    function decryptToken(encoded) {
        if (!encoded) return '';
        try {
            const reversed = encoded.split('').reverse().join('');
            const decoded = decodeURIComponent(escape(atob(reversed)));
            return decoded.replace(ENCRYPTION_KEY, '');
        } catch (error) {
            return encoded;
        }
    }

    function getToken() {
        return decryptToken(localStorage.getItem(STORAGE_KEY));
    }

    async function apiJSON(url, options) {
        const token = getToken();
        if (!token) throw new Error('请先在系统设置中配置 API 访问令牌');
        const init = options || {};
        const headers = new Headers(init.headers || {});
        headers.set('Authorization', `Bearer ${token}`);
        if (init.body && !(init.body instanceof FormData)) {
            headers.set('Content-Type', 'application/json');
        }
        const response = await fetch(url, { ...init, headers });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || Number(payload.code || 0) >= 400) {
            const error = new Error(payload.detail || payload.message || `请求失败（HTTP ${response.status}）`);
            error.status = response.status;
            throw error;
        }
        return payload.data;
    }

    function setStatus(message, kind) {
        els.statusStage.textContent = message || '';
        els.statusMeta.textContent = '';
        if (kind === 'success') {
            state.lastOverallPercent = 100;
            els.statusFill.style.width = '100%';
        } else if (!kind) {
            els.statusFill.style.width = '0%';
        }
        els.status.dataset.kind = kind || '';
    }

    function formatElapsed() {
        if (!state.startedAt) return '';
        const seconds = Math.max(0, Math.round((Date.now() - state.startedAt) / 1000));
        const minutes = Math.floor(seconds / 60);
        return minutes ? `${minutes}分${seconds % 60}秒` : `${seconds}秒`;
    }

    function setProgress(progress, kind) {
        const value = progress || {};
        const requestedPercent = Number(
            value.overall_percent !== undefined ? value.overall_percent : value.percent
        );
        const percent = Number.isFinite(requestedPercent)
            ? Math.max(state.lastOverallPercent, Math.max(0, Math.min(100, requestedPercent)))
            : NaN;
        if (Number.isFinite(percent)) state.lastOverallPercent = percent;
        els.statusStage.textContent = value.stage_label || value.message || '正在处理…';
        const meta = [];
        if (Number.isFinite(percent)) meta.push(`${Math.round(percent)}%`);
        if (state.startedAt) meta.push(`已耗时 ${formatElapsed()}`);
        if (value.updated_at) meta.push(`更新于 ${new Date(value.updated_at).toLocaleTimeString()}`);
        els.statusMeta.textContent = meta.join(' · ');
        els.statusFill.style.width = Number.isFinite(percent)
            ? `${Math.max(0, Math.min(100, percent))}%`
            : '12%';
        els.status.dataset.kind = kind || 'working';
    }

    function updateGenerateState() {
        const ready = state.mode === 'text' ? Boolean(els.content.value.trim()) : Boolean(state.file);
        els.generate.disabled = !ready;
    }

    function switchMode(mode) {
        state.mode = mode;
        els.tabs.forEach((tab) => {
            const active = tab.dataset.sourceMode === mode;
            tab.classList.toggle('is-active', active);
            tab.setAttribute('aria-selected', active ? 'true' : 'false');
        });
        els.textPanel.hidden = mode !== 'text';
        els.filePanel.hidden = mode !== 'file';
        els.textPanel.classList.toggle('is-active', mode === 'text');
        els.filePanel.classList.toggle('is-active', mode === 'file');
        updateGenerateState();
    }

    async function ingestSource() {
        if (state.mode === 'text') {
            return apiJSON('/api/study/text', {
                method: 'POST',
                body: JSON.stringify({
                    title: els.title.value.trim(),
                    content: els.content.value.trim(),
                }),
            });
        }
        const form = new FormData();
        form.append('file', state.file);
        form.append('use_speaker_recognition', 'false');
        form.append('visual_fast_path', 'true');
        return uploadFile(form);
    }

    function uploadFile(form) {
        return new Promise((resolve, reject) => {
            const token = getToken();
            if (!token) {
                reject(new Error('请先在系统设置中配置 API 访问令牌'));
                return;
            }
            const request = new XMLHttpRequest();
            request.open('POST', '/api/study/upload');
            request.setRequestHeader('Authorization', `Bearer ${token}`);
            request.upload.onprogress = (event) => {
                if (!event.lengthComputable) return;
                setProgress({
                    stage_label: '正在上传文档',
                    overall_percent: 5 * (event.loaded / event.total),
                }, 'working');
            };
            request.onerror = () => reject(new Error('文档上传失败，请重试'));
            request.onload = () => {
                let payload = {};
                try { payload = JSON.parse(request.responseText || '{}'); } catch (error) { payload = {}; }
                if (request.status < 200 || request.status >= 300 || Number(payload.code || 0) >= 400) {
                    reject(new Error(payload.detail || payload.message || `上传失败（HTTP ${request.status}）`));
                    return;
                }
                resolve(payload.data);
            };
            request.send(form);
        });
    }

    async function waitForSource(viewToken) {
        const payload = await apiJSON(
            `/api/visual-learning/study/${encodeURIComponent(viewToken)}?document_type=diagram`
        );
        if (payload.phase === 'ready_for_generation') return payload;
        if (payload.phase === 'failed') {
            throw new Error('全文分析失败，请重新提交内容');
        }
        if (payload.workflow_progress) setProgress(payload.workflow_progress, 'working');
        await new Promise((resolve) => { state.pollTimer = window.setTimeout(resolve, 1800); });
        return waitForSource(viewToken);
    }

    async function generateDiagram(viewToken, force) {
        setStatus('正在组织图解结构…', 'working');
        const payload = await apiJSON(
            `/api/visual-learning/study/${encodeURIComponent(viewToken)}/generate`,
            {
                method: 'POST',
                body: JSON.stringify({
                    document_type: 'diagram',
                    diagram_type: els.diagramType.value,
                    style: els.style.value,
                    force: Boolean(force),
                }),
            }
        );
        consumeVisualState(payload);
    }

    function consumeVisualState(payload) {
        const record = payload && payload.document;
        const attempt = payload && payload.latest_attempt;
        const liveProgress = payload && payload.workflow_progress;
        if (liveProgress) setProgress(liveProgress, 'working');
        if (record && record.status === 'success' && record.document_json) {
            renderDocument(record);
            setStatus('图解已生成', 'success');
            loadHistory();
            return;
        }
        const target = attempt || record;
        if (payload && payload.phase === 'ready_for_generation' && !target && state.viewToken) {
            generateDiagram(state.viewToken, false).catch(handleError);
            return;
        }
        if (target && ['pending', 'generating'].includes(target.status)) {
            if (!liveProgress) setStatus(target.status === 'pending' ? '等待生成…' : '正在生成图解…', 'working');
            pollDocument(target.id);
            return;
        }
        if (target && target.status === 'failed') {
            throw new Error(target.error_message || '图解生成失败');
        }
    }

    async function pollDocument(documentId) {
        window.clearTimeout(state.pollTimer);
        state.pollTimer = window.setTimeout(async () => {
            try {
                const payload = await apiJSON(`/api/visual-learning/documents/${encodeURIComponent(documentId)}`);
                consumeVisualState(payload);
            } catch (error) {
                setStatus(error.message || '图解生成失败', 'error');
                els.generate.disabled = false;
            }
        }, 2000);
    }

    function enterReaderMode() {
        document.body.classList.add('vl-reader-mode');
        els.readerExit.hidden = false;
        updateReadingState();
    }

    function exitReaderMode() {
        closeEvidenceDrawer();
        document.body.classList.remove('vl-reader-mode');
        els.readerExit.hidden = true;
        const url = new URL(window.location.href);
        url.searchParams.delete('document_id');
        url.hash = '';
        window.history.replaceState({}, '', url);
        window.scrollTo({ top: 0, behavior: 'auto' });
    }

    function setActiveSection(section) {
        const pageId = section ? section.dataset.pageId : '';
        const title = section ? section.dataset.sectionTitle : '尚未开始';
        els.currentSection.textContent = title;
        Array.from(els.pageNavigation.querySelectorAll('a')).forEach((link) => {
            if (link.dataset.pageId === pageId) link.setAttribute('aria-current', 'location');
            else link.removeAttribute('aria-current');
        });
    }

    function updateReadingState() {
        state.readerScrollPending = false;
        if (!document.body.classList.contains('vl-reader-mode')) return;
        const range = document.documentElement.scrollHeight - window.innerHeight;
        const percent = range <= 0
            ? 100
            : Math.round(Math.min(1, Math.max(0, window.scrollY / range)) * 100);
        els.readingProgress.setAttribute('aria-valuenow', String(percent));
        els.readingProgressLabel.value = `${percent}%`;
        els.readingProgressFill.style.transform = `scaleX(${percent / 100})`;

        const sections = Array.from(els.canvas.querySelectorAll('.vl-page'));
        if (!sections.length) return;
        if (range > 0 && window.scrollY >= range - 2) {
            setActiveSection(sections[sections.length - 1]);
            return;
        }
        const activationLine = document.querySelector('.vl-output-toolbar').getBoundingClientRect().bottom + 24;
        let active = sections[0];
        sections.forEach((section) => {
            const heading = section.querySelector('h2');
            if (heading && heading.getBoundingClientRect().top <= activationLine + 2) active = section;
        });
        setActiveSection(active);
    }

    function scheduleReadingUpdate() {
        if (state.readerScrollPending) return;
        state.readerScrollPending = true;
        window.requestAnimationFrame(updateReadingState);
    }

    function evidenceMeta(sourceRef) {
        const parts = [];
        if (Number.isInteger(sourceRef.paragraph_index)) parts.push(`第 ${sourceRef.paragraph_index + 1} 段`);
        if (sourceRef.line_id) parts.push(`定位 ${sourceRef.line_id}`);
        if (Number.isFinite(Number(sourceRef.start_seconds))) parts.push(`时间 ${Math.round(Number(sourceRef.start_seconds))} 秒`);
        return parts.join(' · ') || '原文摘录';
    }

    function openEvidenceDrawer(payload, trigger) {
        state.evidenceTrigger = trigger;
        state.evidenceScrollY = window.scrollY;
        els.evidencePosition.textContent = `原文依据 · ${payload.references.length} 条`;
        els.evidenceTitle.textContent = payload.page.title || '章节依据';
        els.evidenceClaim.textContent = payload.page.learning_goal || '';
        els.evidenceList.replaceChildren();
        payload.references.forEach((item) => {
            const entry = document.createElement('article');
            const label = document.createElement('strong');
            const quote = document.createElement('blockquote');
            const meta = document.createElement('p');
            label.textContent = item.blockTitle;
            quote.textContent = item.sourceRef.excerpt;
            meta.textContent = evidenceMeta(item.sourceRef);
            entry.append(label, quote, meta);
            els.evidenceList.appendChild(entry);
        });
        els.evidenceLayer.hidden = false;
        document.getElementById('main-content').inert = true;
        const sidebar = document.querySelector('.sidebar');
        if (sidebar) sidebar.inert = true;
        document.body.classList.add('vl-evidence-open');
        document.body.style.top = `-${state.evidenceScrollY}px`;
        window.requestAnimationFrame(() => els.evidenceClose.focus());
    }

    function closeEvidenceDrawer() {
        if (els.evidenceLayer.hidden) return;
        els.evidenceLayer.hidden = true;
        document.getElementById('main-content').inert = false;
        const sidebar = document.querySelector('.sidebar');
        if (sidebar) sidebar.inert = false;
        document.body.classList.remove('vl-evidence-open');
        document.body.style.top = '';
        const previous = document.documentElement.style.scrollBehavior;
        document.documentElement.style.scrollBehavior = 'auto';
        window.scrollTo(0, state.evidenceScrollY);
        window.requestAnimationFrame(() => {
            document.documentElement.style.scrollBehavior = previous;
            if (state.evidenceTrigger) state.evidenceTrigger.focus({ preventScroll: true });
        });
    }

    function renderDocument(record) {
        state.document = record;
        state.viewToken = record.owner_id;
        els.outputTitle.textContent = record.document_json.title || '视觉图解';
        window.VisualLearning.render(els.canvas, record.document_json, {
            readerMode: 'continuous',
            onSectionEvidence: openEvidenceDrawer,
        });
        window.VisualLearning.setTheme(els.canvas, els.style.value);
        renderPageNavigation(record.document_json.pages || []);
        els.exportButton.disabled = false;
        els.printButton.disabled = false;
        renderRecommendations(record.document_json.diagram_recommendations || []);
        els.generate.disabled = false;
        enterReaderMode();
        const url = new URL(window.location.href);
        url.searchParams.set('document_id', record.id);
        window.history.replaceState({}, '', url);
        window.requestAnimationFrame(() => {
            window.requestAnimationFrame(() => {
                if (window.location.hash) {
                    const target = document.querySelector(window.location.hash);
                    const heading = target && (target.querySelector('h2') || target);
                    if (heading) {
                        window.setTimeout(() => {
                            const activationLine = document.querySelector('.vl-output-toolbar').getBoundingClientRect().bottom + 24;
                            window.scrollBy({ top: heading.getBoundingClientRect().top - activationLine, behavior: 'auto' });
                            if (target.matches('.vl-page')) setActiveSection(target);
                        }, 0);
                    }
                    return;
                }
                updateReadingState();
            });
        });
    }

    function renderPageNavigation(pages) {
        els.pageNavigation.replaceChildren();
        const sections = Array.from(els.canvas.querySelectorAll('.vl-page'));
        (pages || []).forEach((page, index) => {
            const section = sections[index];
            if (!section) return;
            const link = document.createElement('a');
            const number = document.createElement('span');
            const title = document.createElement('strong');
            link.href = `#${section.id}`;
            link.dataset.pageId = page.id || `page-${index + 1}`;
            number.textContent = String(index + 1).padStart(2, '0');
            title.textContent = page.title || `第 ${index + 1} 节`;
            link.append(number, title);
            link.addEventListener('click', (event) => {
                event.preventDefault();
                const heading = section.querySelector('h2') || section;
                heading.scrollIntoView({
                    behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth',
                    block: 'start',
                });
                window.history.pushState({}, '', link.getAttribute('href'));
            });
            els.pageNavigation.appendChild(link);
        });
        els.pageNavigation.hidden = !pages || pages.length < 1;
        setActiveSection(sections[0]);
    }

    function renderRecommendations(recommendations) {
        els.recommendations.replaceChildren();
        if (!recommendations.length) {
            els.recommendations.hidden = true;
            return;
        }
        const label = document.createElement('span');
        label.textContent = '推荐';
        els.recommendations.appendChild(label);
        recommendations.forEach((item) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.textContent = item.label;
            button.title = item.rationale;
            button.addEventListener('click', () => {
                els.diagramType.value = item.diagram_type;
                if (state.viewToken) generateDiagram(state.viewToken, true).catch(handleError);
            });
            els.recommendations.appendChild(button);
        });
        els.recommendations.hidden = false;
    }

    async function loadHistory() {
        try {
            const payload = await apiJSON('/api/visual-learning/documents?document_type=diagram&limit=20');
            const documents = payload.documents || [];
            els.history.replaceChildren();
            if (!documents.length) {
                const empty = document.createElement('p');
                empty.textContent = '暂无生成记录';
                els.history.appendChild(empty);
                return;
            }
            documents.forEach((record) => {
                const button = document.createElement('button');
                button.type = 'button';
                button.className = 'vl-history-item';
                const title = document.createElement('strong');
                const meta = document.createElement('span');
                title.textContent = (record.document_json || {}).title || '未命名图解';
                meta.textContent = record.style || 'study-notes';
                button.append(title, meta);
                button.addEventListener('click', () => openDocument(record.id));
                els.history.appendChild(button);
            });
        } catch (error) {
            els.history.replaceChildren();
        }
    }

    async function openDocument(documentId) {
        setStatus('正在打开图解…', 'working');
        const payload = await apiJSON(`/api/visual-learning/documents/${encodeURIComponent(documentId)}`);
        const record = payload.document;
        if (!record || record.status !== 'success') throw new Error('图解尚未生成完成');
        els.style.value = record.style || 'study-notes';
        renderDocument(record);
        setStatus('', '');
    }

    function handleError(error) {
        setStatus(error.message || '操作失败，请重试', 'error');
        els.generate.disabled = false;
        els.generate.textContent = '重新提交';
    }

    async function startGeneration() {
        if (els.generate.disabled) return;
        els.generate.disabled = true;
        els.generate.textContent = '生成中…';
        state.startedAt = Date.now();
        state.lastOverallPercent = 0;
        window.clearTimeout(state.pollTimer);
        try {
            setStatus(state.mode === 'text' ? '正在保存文字…' : '正在上传文档…', 'working');
            const source = await ingestSource();
            state.viewToken = source.view_token;
            await waitForSource(state.viewToken);
            await generateDiagram(state.viewToken, false);
        } catch (error) {
            handleError(error);
        }
    }

    function bindEvents() {
        els.tabs.forEach((tab) => tab.addEventListener('click', () => switchMode(tab.dataset.sourceMode)));
        els.content.addEventListener('input', updateGenerateState);
        els.fileDrop.addEventListener('click', () => els.fileInput.click());
        els.fileInput.addEventListener('change', () => {
            state.file = els.fileInput.files && els.fileInput.files[0];
            els.fileName.textContent = state.file ? state.file.name : '选择文档';
            updateGenerateState();
        });
        els.fileDrop.addEventListener('dragover', (event) => event.preventDefault());
        els.fileDrop.addEventListener('drop', (event) => {
            event.preventDefault();
            state.file = event.dataTransfer && event.dataTransfer.files[0];
            els.fileName.textContent = state.file ? state.file.name : '选择文档';
            updateGenerateState();
        });
        els.generate.addEventListener('click', startGeneration);
        els.style.addEventListener('change', () => window.VisualLearning.setTheme(els.canvas, els.style.value));
        els.exportButton?.addEventListener('click', () => {
            if (state.document) window.VisualLearning.exportSvg(els.canvas, `${state.document.id}.svg`);
        });
        els.printButton?.addEventListener('click', () => window.print());
        els.historyRefresh.addEventListener('click', loadHistory);
        els.readerExit.addEventListener('click', exitReaderMode);
        els.evidenceClose.addEventListener('click', closeEvidenceDrawer);
        els.evidenceOverlay.addEventListener('click', closeEvidenceDrawer);
        window.addEventListener('scroll', scheduleReadingUpdate, { passive: true });
        window.addEventListener('resize', scheduleReadingUpdate);
        document.addEventListener('keydown', (event) => {
            if (els.evidenceLayer.hidden) return;
            if (event.key === 'Escape') {
                event.preventDefault();
                closeEvidenceDrawer();
                return;
            }
            if (event.key === 'Tab') {
                event.preventDefault();
                els.evidenceClose.focus();
            }
        });
    }

    async function init() {
        bindEvents();
        updateGenerateState();
        loadHistory();
        const documentId = new URLSearchParams(window.location.search).get('document_id');
        if (documentId) {
            try {
                await openDocument(documentId);
            } catch (error) {
                handleError(error);
            }
        }
    }

    init();
})();
