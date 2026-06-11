(function () {
    const STORAGE_KEY = 'vta_bearer_token';
    const ENCRYPTION_KEY = 'vta_encrypt_key_2024';
    const VIDEO_EXTS = ['.mp4', '.mov', '.mkv', '.webm', '.avi', '.m4v', '.mp3', '.m4a', '.wav', '.aac', '.flac'];
    const DOC_EXTS = ['.txt', '.md', '.markdown', '.csv', '.log', '.pdf', '.docx'];
    const POLL_MS = 2500;

    const els = {
        title: document.getElementById('collection-title'),
        typeTabs: Array.from(document.querySelectorAll('.lc-type')),
        dropAction: document.getElementById('drop-action'),
        dropTitle: document.getElementById('drop-title'),
        dropSubtitle: document.getElementById('drop-subtitle'),
        pickFolder: document.getElementById('pick-folder'),
        pickFiles: document.getElementById('pick-files'),
        folderInput: document.getElementById('folder-input'),
        filesInput: document.getElementById('files-input'),
        importPreview: document.getElementById('import-preview'),
        collectionHistoryList: document.getElementById('collection-history-list'),
        collectionHistoryCount: document.getElementById('collection-history-count'),
        tokenHint: document.getElementById('token-hint'),
        workspaceTitle: document.getElementById('workspace-title'),
        workspaceSubtitle: document.getElementById('workspace-subtitle'),
        progressValue: document.getElementById('progress-value'),
        progressFill: document.getElementById('progress-fill'),
        sourceList: document.getElementById('source-list'),
        sourceCount: document.getElementById('source-count'),
        tabs: Array.from(document.querySelectorAll('.lc-tab')),
        summaryView: document.getElementById('summary-view'),
        sourceView: document.getElementById('source-view'),
        markdownView: document.getElementById('markdown-view'),
        summaryStatus: document.getElementById('summary-status'),
        summaryDescription: document.getElementById('summary-description'),
        summaryStructure: document.getElementById('summary-structure'),
        summaryProgression: document.getElementById('summary-progression'),
        summaryEvidence: document.getElementById('summary-evidence'),
        summarySop: document.getElementById('summary-sop'),
        generateSummary: document.getElementById('generate-summary'),
        exportMarkdown: document.getElementById('export-markdown'),
        sourceTitle: document.getElementById('source-title'),
        sourceMeta: document.getElementById('source-meta'),
        sourceTiming: document.getElementById('source-timing'),
        sourceSummary: document.getElementById('source-summary'),
        sourceTranscript: document.getElementById('source-transcript'),
        openSource: document.getElementById('open-source'),
        markdownPreview: document.getElementById('markdown-preview'),
        toast: document.getElementById('toast')
    };

    let activeType = 'video_course';
    let collections = [];
    let currentCollection = null;
    let selectedSourceId = null;
    let currentView = 'summary';
    let sourceDetails = {};
    let busy = false;
    let pollTimer = null;
    let toastTimer = null;

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

    function showToast(message) {
        window.clearTimeout(toastTimer);
        els.toast.textContent = message;
        els.toast.classList.add('show');
        toastTimer = window.setTimeout(() => els.toast.classList.remove('show'), 2600);
    }

    function setBusy(nextBusy) {
        busy = nextBusy;
        [els.pickFolder, els.pickFiles, els.dropAction].forEach((button) => {
            button.disabled = busy;
        });
        els.typeTabs.forEach((button) => {
            button.disabled = busy;
        });
        if (busy) {
            els.generateSummary.disabled = true;
            els.exportMarkdown.disabled = true;
        }
    }

    async function apiJSON(url, options) {
        const token = getToken();
        if (!token) {
            throw new Error('请先在工作台设置 API 令牌');
        }

        const init = options || {};
        const headers = new Headers(init.headers || {});
        headers.set('Authorization', `Bearer ${token}`);
        if (init.body && !(init.body instanceof FormData)) {
            headers.set('Content-Type', 'application/json');
        }

        const response = await fetch(url, { ...init, headers });
        const contentType = response.headers.get('content-type') || '';
        const payload = contentType.includes('application/json') ? await response.json() : await response.text();
        if (!response.ok) {
            const detail = typeof payload === 'object' ? (payload.detail || payload.message) : payload;
            throw new Error(detail || `HTTP ${response.status}`);
        }
        return payload;
    }

    function typeConfig(type) {
        if (type === 'document_topic') {
            return {
                accept: DOC_EXTS.join(','),
                title: '上传专题文档',
                subtitle: '选择专题文件夹，或一次选择多篇文档。',
                goal: '从同一专题文档中提炼知识结构、判断标准和可执行清单。'
            };
        }
        return {
            accept: VIDEO_EXTS.join(','),
            title: '上传课程视频',
            subtitle: '选择专题文件夹，或一次选择多个视频。',
            goal: '从同一视频课程中提炼整体主题、章节关系和可复用方法论。'
        };
    }

    function setActiveType(type) {
        activeType = type;
        const config = typeConfig(type);
        els.typeTabs.forEach((tab) => {
            tab.classList.toggle('active', tab.dataset.type === type);
        });
        els.filesInput.setAttribute('accept', config.accept);
        els.dropTitle.textContent = config.title;
        els.dropSubtitle.textContent = config.subtitle;
    }

    function isAllowedFile(file) {
        if (!file || !file.name || file.name.startsWith('.')) return false;
        const lower = file.name.toLowerCase();
        const exts = activeType === 'document_topic' ? DOC_EXTS : VIDEO_EXTS;
        return exts.some((ext) => lower.endsWith(ext));
    }

    function normalizeFiles(fileList) {
        return Array.from(fileList || [])
            .filter((file) => file.size > 0 && isAllowedFile(file))
            .sort((a, b) => {
                const left = a.webkitRelativePath || a.name;
                const right = b.webkitRelativePath || b.name;
                return left.localeCompare(right, 'zh-Hans-CN', { numeric: true, sensitivity: 'base' });
            });
    }

    function previewFiles(files) {
        if (!files.length) {
            els.importPreview.innerHTML = '<strong>尚未选择文件</strong><span>选择后会按文件名顺序逐个解析</span>';
            return;
        }

        const first = files[0].webkitRelativePath || files[0].name;
        const last = files[files.length - 1].webkitRelativePath || files[files.length - 1].name;
        els.importPreview.innerHTML = `<strong>${escapeHTML(files.length)} 个文件</strong><span>${escapeHTML(first)}${files.length > 1 ? ' - ' + escapeHTML(last) : ''}</span>`;
    }

    function escapeHTML(value) {
        return String(value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function formatDuration(seconds) {
        if (seconds === null || seconds === undefined || Number.isNaN(Number(seconds))) return '';
        const total = Math.max(0, Number(seconds));
        const hours = Math.floor(total / 3600);
        const minutes = Math.floor((total % 3600) / 60);
        const secs = Math.floor(total % 60);
        if (hours) return `${hours}小时${minutes}分`;
        if (minutes) return `${minutes}分${secs}秒`;
        return `${secs}秒`;
    }

    function sourceProgressPercent(source) {
        if (!source) return 0;
        if (source.task_status === 'success') return 100;
        if (source.task_status === 'failed') return source.progress && source.progress.percent ? source.progress.percent : 0;
        if (source.progress && Number.isFinite(Number(source.progress.percent))) {
            return Math.max(0, Math.min(95, Number(source.progress.percent)));
        }
        if (source.task_status === 'calibrating') return 94;
        if (source.task_status === 'processing') return 30;
        return 0;
    }

    function sourceStageText(source) {
        if (!source) return '';
        if (source.progress && source.progress.stage_label) return source.progress.stage_label;
        return statusLabel(source.task_status);
    }

    function previewText(text, limit) {
        const value = String(text || '').trim();
        if (!value) return '';
        const max = limit || 12000;
        if (value.length <= max) return value;
        return `${value.slice(0, max)}\n\n... 已截断，点击“原文/逐字稿”查看完整内容。`;
    }

    async function createCollection() {
        const title = els.title.value.trim() || '未命名专题';
        const config = typeConfig(activeType);
        const payload = await apiJSON('/api/collections', {
            method: 'POST',
            body: JSON.stringify({
                title,
                collection_type: activeType,
                goal: config.goal
            })
        });
        return payload.data;
    }

    async function uploadFiles(collectionId, files) {
        const formData = new FormData();
        files.forEach((file) => {
            const name = file.webkitRelativePath || file.name;
            formData.append('files', file, name);
        });
        return apiJSON(`/api/collections/${collectionId}/sources/upload`, {
            method: 'POST',
            body: formData
        });
    }

    async function loadCollections(options) {
        const opts = options || {};
        if (!getToken()) {
            collections = [];
            renderHistory();
            return;
        }

        try {
            const payload = await apiJSON('/api/collections');
            collections = (payload.data && payload.data.collections) || [];
            renderHistory();
            if (opts.selectLatest !== false && !currentCollection && collections.length) {
                await selectCollection(collections[0].id, { silent: true });
            }
        } catch (error) {
            collections = [];
            renderHistory(error.message || '历史专题加载失败');
        }
    }

    async function selectCollection(collectionId, options) {
        if (!collectionId) return;
        const opts = options || {};
        window.clearInterval(pollTimer);
        selectedSourceId = null;
        sourceDetails = {};
        currentView = 'summary';
        await refreshCollection(collectionId);
        const sources = currentCollection ? (currentCollection.sources || []) : [];
        const finished = sources.length > 0 && sources.every((source) => ['success', 'failed'].includes(source.task_status));
        if (!finished) startPolling();
        if (!opts.silent) showToast('已打开历史专题');
    }

    async function importFiles(fileList) {
        const files = normalizeFiles(fileList);
        previewFiles(files);
        if (!files.length) {
            showToast('没有找到当前类型支持的文件');
            return;
        }

        setBusy(true);
        try {
            const collection = await createCollection();
            currentCollection = collection;
            selectedSourceId = null;
            sourceDetails = {};
            render();
            await uploadFiles(collection.id, files);
            showToast('已开始解析专题文件');
            await refreshCollection(collection.id);
            await loadCollections({ selectLatest: false });
            startPolling();
        } catch (error) {
            showToast(error.message || '导入失败');
        } finally {
            setBusy(false);
            render();
            els.folderInput.value = '';
            els.filesInput.value = '';
        }
    }

    async function refreshCollection(collectionId) {
        const payload = await apiJSON(`/api/collections/${collectionId}`);
        currentCollection = payload.data;
        if (currentCollection.collection_type) {
            setActiveType(currentCollection.collection_type);
        }
        if (currentCollection.title) {
            els.title.value = currentCollection.title;
        }
        if (!selectedSourceId && currentCollection.sources && currentCollection.sources.length) {
            selectedSourceId = currentCollection.sources[0].id;
        }
        render();
    }

    function collectionStatusLabel(collection) {
        if (collection.summary_status === 'success') return '已总结';
        if (Number(collection.source_count || 0) > 0) return '已导入';
        return '空专题';
    }

    function renderHistory(errorMessage) {
        if (!els.collectionHistoryList || !els.collectionHistoryCount) return;

        els.collectionHistoryCount.textContent = collections.length ? `${collections.length} 个` : '0 个';
        if (errorMessage) {
            els.collectionHistoryList.innerHTML = `<div class="lc-history-empty">${escapeHTML(errorMessage)}</div>`;
            return;
        }
        if (!getToken()) {
            els.collectionHistoryList.innerHTML = '<div class="lc-history-empty">设置 API 令牌后显示历史专题</div>';
            return;
        }
        if (!collections.length) {
            els.collectionHistoryList.innerHTML = '<div class="lc-history-empty">暂无历史专题</div>';
            return;
        }

        els.collectionHistoryList.innerHTML = collections.slice(0, 8).map((collection) => {
            const active = currentCollection && collection.id === currentCollection.id ? ' active' : '';
            const type = collection.collection_type === 'document_topic' ? '文档专题' : '视频课程';
            const count = Number(collection.source_count || 0);
            return `
                <button class="lc-history-item${active}" type="button" data-collection-id="${escapeHTML(collection.id)}">
                    <span>
                        <strong>${escapeHTML(collection.title)}</strong>
                        <small>${escapeHTML(type)} · ${count} 个 source</small>
                    </span>
                    <em>${escapeHTML(collectionStatusLabel(collection))}</em>
                </button>
            `;
        }).join('');

        els.collectionHistoryList.querySelectorAll('[data-collection-id]').forEach((button) => {
            button.addEventListener('click', () => {
                selectCollection(button.dataset.collectionId).catch((error) => {
                    showToast(error.message || '打开历史专题失败');
                });
            });
        });
    }

    function startPolling() {
        window.clearInterval(pollTimer);
        pollTimer = window.setInterval(async () => {
            if (!currentCollection) return;
            try {
                await refreshCollection(currentCollection.id);
                const sources = currentCollection.sources || [];
                const finished = sources.length > 0 && sources.every((source) => ['success', 'failed'].includes(source.task_status));
                if (finished) {
                    window.clearInterval(pollTimer);
                }
            } catch (error) {
                window.clearInterval(pollTimer);
                showToast(error.message || '刷新解析状态失败');
            }
        }, POLL_MS);
    }

    function statusLabel(status) {
        const labels = {
            pending: '等待',
            queued: '排队',
            processing: '解析中',
            calibrating: 'AI处理中',
            success: '完成',
            failed: '失败'
        };
        return labels[status] || '等待';
    }

    function renderSources() {
        const sources = currentCollection ? (currentCollection.sources || []) : [];
        els.sourceCount.textContent = sources.length ? `${sources.length} 个 source` : '0 个';

        if (!sources.length) {
            els.sourceList.innerHTML = '<div class="lc-empty">导入专题文件后，这里会显示每个 source 的解析状态。</div>';
            return;
        }

        els.sourceList.innerHTML = sources.map((source, index) => {
            const active = source.id === selectedSourceId ? ' active' : '';
            const status = source.task_status || 'pending';
            const stage = sourceStageText(source);
            const duration = source.elapsed_seconds ? ` · ${formatDuration(source.elapsed_seconds)}` : '';
            return `
                <button class="lc-source-item${active}" type="button" data-source-id="${escapeHTML(source.id)}">
                    <span class="lc-source-index">${index + 1}</span>
                    <span class="lc-source-main">
                        <span class="lc-source-title">${escapeHTML(source.title)}</span>
                        <span class="lc-source-meta">${escapeHTML(stage || source.task_title || source.source_type || '')}${escapeHTML(duration)}</span>
                    </span>
                    <span class="lc-status ${escapeHTML(status)}">${statusLabel(status)}</span>
                </button>
            `;
        }).join('');

        els.sourceList.querySelectorAll('[data-source-id]').forEach((button) => {
            button.addEventListener('click', () => {
                selectedSourceId = button.dataset.sourceId;
                currentView = 'source';
                render();
            });
        });
    }

    function renderProgress() {
        const sources = currentCollection ? (currentCollection.sources || []) : [];
        const done = sources.filter((source) => source.task_status === 'success').length;
        const percent = sources.length
            ? Math.round(sources.reduce((sum, source) => sum + sourceProgressPercent(source), 0) / sources.length)
            : 0;
        els.progressValue.textContent = `${percent}%`;
        els.progressFill.style.width = `${percent}%`;
        if (!sources.length) {
            els.workspaceSubtitle.textContent = '选择一个专题文件夹，开始逐个解析。';
            return;
        }
        const metrics = currentCollection.metrics || {};
        const elapsed = metrics.elapsed_seconds ? ` · 总耗时 ${formatDuration(metrics.elapsed_seconds)}` : '';
        const active = sources.find((source) => !['success', 'failed'].includes(source.task_status));
        const stage = active ? ` · 当前：${sourceStageText(active)}` : '';
        els.workspaceSubtitle.textContent = `${done}/${sources.length} 个 source 已完成${elapsed}${stage}`;
    }

    function renderSummary() {
        const markdown = currentCollection && currentCollection.summary_markdown;
        const sources = currentCollection ? (currentCollection.sources || []) : [];
        const ready = sources.length > 0 && sources.every((source) => source.task_status === 'success');

        els.summaryStatus.textContent = markdown ? '专题总结已生成' : '等待生成集合级总结';
        els.summaryDescription.textContent = markdown
            ? '已从整体视角整理主题、结构、递进关系、证据和行动清单。'
            : (ready ? '所有 source 已解析完成，点击“生成总结”进行集合级综合分析。' : '导入并解析完成后，再从整体视角生成总结。');
        const cardText = markdown ? '已生成，切换到 Markdown 查看完整内容。' : (ready ? '点击生成总结后展示。' : '解析完成后生成。');
        els.summaryStructure.textContent = cardText;
        els.summaryProgression.textContent = cardText;
        els.summaryEvidence.textContent = cardText;
        els.summarySop.textContent = cardText;
        els.markdownPreview.textContent = markdown || (ready ? '集合已解析完成，请先点击“生成总结”。' : '生成专题总结后显示。');
        els.generateSummary.disabled = busy || !ready;
        els.exportMarkdown.disabled = busy || !markdown;
    }

    async function loadSourceDetail(sourceId) {
        if (!currentCollection || !sourceId || sourceDetails[sourceId]) return;
        sourceDetails[sourceId] = { loading: true };
        render();
        try {
            const payload = await apiJSON(`/api/collections/${currentCollection.id}/sources/${sourceId}`);
            sourceDetails[sourceId] = payload.data;
        } catch (error) {
            sourceDetails[sourceId] = { error: error.message || '加载 source 内容失败' };
        }
        render();
    }

    function renderSelectedSource() {
        const sources = currentCollection ? (currentCollection.sources || []) : [];
        const source = sources.find((item) => item.id === selectedSourceId) || sources[0];

        if (!source) {
            els.sourceTitle.textContent = '选择一个 source';
            els.sourceMeta.textContent = '左侧选择后查看详情。';
            els.sourceTiming.textContent = '';
            els.sourceSummary.textContent = '解析完成后显示。';
            els.sourceTranscript.textContent = '解析完成后显示。';
            els.openSource.classList.add('hidden');
            return;
        }

        selectedSourceId = source.id;
        els.sourceTitle.textContent = source.title;
        els.sourceMeta.textContent = `${statusLabel(source.task_status)} · ${sourceStageText(source)}`;
        els.sourceTiming.textContent = source.elapsed_seconds
            ? `处理耗时 ${formatDuration(source.elapsed_seconds)}`
            : (source.progress && source.progress.percent !== undefined ? `当前进度 ${source.progress.percent}%` : '');
        els.openSource.href = source.view_token ? `/view/${source.view_token}` : '#';
        els.openSource.classList.toggle('hidden', !source.view_token);

        const detail = sourceDetails[source.id];
        if (source.task_status === 'success' && !detail) {
            loadSourceDetail(source.id);
            els.sourceSummary.textContent = '正在加载 AI 解读摘要...';
            els.sourceTranscript.textContent = '正在加载逐字稿...';
            return;
        }
        if (detail && detail.loading) {
            els.sourceSummary.textContent = '正在加载 AI 解读摘要...';
            els.sourceTranscript.textContent = '正在加载逐字稿...';
            return;
        }
        if (detail && detail.error) {
            els.sourceSummary.textContent = detail.error;
            els.sourceTranscript.textContent = detail.error;
            return;
        }

        els.sourceSummary.textContent = detail && detail.summary
            ? previewText(detail.summary, 5000)
            : (source.task_status === 'success' ? '这个 source 的单篇摘要还未生成或仍在处理中。' : '解析完成后显示。');
        els.sourceTranscript.textContent = detail && detail.transcript
            ? previewText(detail.transcript, 12000)
            : (source.task_status === 'success' ? '未读取到逐字稿内容，请点击“原文/逐字稿”查看完整页。' : '解析完成后显示。');
    }

    function renderTabs() {
        els.tabs.forEach((tab) => {
            tab.classList.toggle('active', tab.dataset.view === currentView);
        });
        els.summaryView.classList.toggle('hidden', currentView !== 'summary');
        els.sourceView.classList.toggle('hidden', currentView !== 'source');
        els.markdownView.classList.toggle('hidden', currentView !== 'markdown');
    }

    function render() {
        const title = currentCollection ? currentCollection.title : (els.title.value.trim() || '如何走出人生困局');
        els.workspaceTitle.textContent = title;
        renderHistory();
        renderProgress();
        renderSources();
        renderSummary();
        renderSelectedSource();
        renderTabs();
    }

    async function generateSummary() {
        if (!currentCollection) {
            showToast('请先导入一个专题');
            return;
        }

        setBusy(true);
        try {
            showToast('正在生成集合级总结');
            const payload = await apiJSON(`/api/collections/${currentCollection.id}/summary`, { method: 'POST' });
            currentCollection = payload.data;
            currentView = 'markdown';
            render();
            showToast('专题总结已生成');
        } catch (error) {
            showToast(error.message || '生成总结失败');
        } finally {
            setBusy(false);
            render();
        }
    }

    async function exportMarkdown() {
        if (!currentCollection || !currentCollection.summary_markdown) {
            showToast('请先生成专题总结');
            return;
        }

        try {
            const token = getToken();
            if (!token) throw new Error('请先在工作台设置 API 令牌');
            const response = await fetch(`/api/collections/${currentCollection.id}/export/markdown`, {
                headers: { Authorization: `Bearer ${token}` }
            });
            if (!response.ok) {
                const data = await response.json().catch(() => ({}));
                throw new Error(data.detail || data.message || '导出失败');
            }
            const blob = await response.blob();
            const url = URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = url;
            link.download = `${currentCollection.title || 'learning-collection'}.md`;
            document.body.appendChild(link);
            link.click();
            link.remove();
            URL.revokeObjectURL(url);
            showToast('Markdown 已导出');
        } catch (error) {
            showToast(error.message || '导出失败');
        }
    }

    function bindEvents() {
        els.typeTabs.forEach((tab) => {
            tab.addEventListener('click', () => setActiveType(tab.dataset.type));
        });

        els.title.addEventListener('input', () => {
            if (!currentCollection) render();
        });

        els.pickFolder.addEventListener('click', () => els.folderInput.click());
        els.pickFiles.addEventListener('click', () => els.filesInput.click());
        els.dropAction.addEventListener('click', () => els.filesInput.click());
        els.folderInput.addEventListener('change', () => importFiles(els.folderInput.files));
        els.filesInput.addEventListener('change', () => importFiles(els.filesInput.files));

        ['dragenter', 'dragover'].forEach((eventName) => {
            els.dropAction.addEventListener(eventName, (event) => {
                event.preventDefault();
                els.dropAction.classList.add('dragging');
            });
        });
        ['dragleave', 'drop'].forEach((eventName) => {
            els.dropAction.addEventListener(eventName, (event) => {
                event.preventDefault();
                els.dropAction.classList.remove('dragging');
            });
        });
        els.dropAction.addEventListener('drop', (event) => importFiles(event.dataTransfer.files));

        els.tabs.forEach((tab) => {
            tab.addEventListener('click', () => {
                currentView = tab.dataset.view;
                render();
            });
        });

        els.generateSummary.addEventListener('click', generateSummary);
        els.exportMarkdown.addEventListener('click', exportMarkdown);
    }

    async function init() {
        setActiveType(activeType);
        bindEvents();
        const token = getToken();
        els.tokenHint.textContent = token ? '' : '需要 API 令牌，请先在工作台设置。';
        render();
        await loadCollections();
    }

    init().catch((error) => showToast(error.message || '初始化失败'));
})();
