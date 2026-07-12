(function () {
    const STORAGE_KEY = 'vta_bearer_token';
    const ENCRYPTION_KEY = 'vta_encrypt_key_2024';
    const VIDEO_EXTS = ['.mp4', '.mov', '.mkv', '.webm', '.avi', '.m4v', '.mp3', '.m4a', '.wav', '.aac', '.flac'];
    const DOC_EXTS = ['.txt', '.md', '.markdown', '.csv', '.log', '.pdf', '.docx'];
    const POLL_MS = 2500;
    const DEFAULT_MAP_ZOOM = 1.16;
    const VISUAL_DOCUMENT_TYPES = ['overview', 'full_note'];

    const els = {
        creator: document.getElementById('collection-creator'),
        creatorOptions: document.getElementById('collection-creator-options'),
        title: document.getElementById('collection-title'),
        typeTabs: Array.from(document.querySelectorAll('.lc-type')),
        dropAction: document.getElementById('drop-action'),
        dropTitle: document.getElementById('drop-title'),
        dropSubtitle: document.getElementById('drop-subtitle'),
        pickFolder: document.getElementById('pick-folder'),
        pickFiles: document.getElementById('pick-files'),
        appendFolder: document.getElementById('append-folder'),
        appendFiles: document.getElementById('append-files'),
        folderInput: document.getElementById('folder-input'),
        filesInput: document.getElementById('files-input'),
        appendFolderInput: document.getElementById('append-folder-input'),
        appendFilesInput: document.getElementById('append-files-input'),
        cancelCollection: document.getElementById('cancel-collection'),
        importPreview: document.getElementById('import-preview'),
        collectionHistoryList: document.getElementById('collection-history-list'),
        collectionHistoryCount: document.getElementById('collection-history-count'),
        historyCreatorFilter: document.getElementById('history-creator-filter'),
        historyTopicFilter: document.getElementById('history-topic-filter'),
        historyDateFilter: document.getElementById('history-date-filter'),
        historyTypeFilter: document.getElementById('history-type-filter'),
        historyStatusFilter: document.getElementById('history-status-filter'),
        historyReset: document.getElementById('history-reset'),
        tokenHint: document.getElementById('token-hint'),
        workspaceTitle: document.getElementById('workspace-title'),
        workspaceSubtitle: document.getElementById('workspace-subtitle'),
        progressValue: document.getElementById('progress-value'),
        progressFill: document.getElementById('progress-fill'),
        metadataCreator: document.getElementById('metadata-creator'),
        metadataType: document.getElementById('metadata-type'),
        metadataDescription: document.getElementById('metadata-description'),
        metadataStarted: document.getElementById('metadata-started'),
        metadataCompleted: document.getElementById('metadata-completed'),
        metadataElapsed: document.getElementById('metadata-elapsed'),
        metadataImport: document.getElementById('metadata-import'),
        metadataExport: document.getElementById('metadata-export'),
        sourceList: document.getElementById('source-list'),
        sourceCount: document.getElementById('source-count'),
        tabs: Array.from(document.querySelectorAll('.lc-tab')),
        mapView: document.getElementById('map-view'),
        visualView: document.getElementById('visual-view'),
        summaryView: document.getElementById('summary-view'),
        sourceView: document.getElementById('source-view'),
        markdownView: document.getElementById('markdown-view'),
        mapTitle: document.getElementById('map-title'),
        mapSubtitle: document.getElementById('map-subtitle'),
        mapScopeCollection: document.getElementById('map-scope-collection'),
        mapScopeSource: document.getElementById('map-scope-source'),
        mapGenerate: document.getElementById('map-generate'),
        mapFocus: document.getElementById('map-focus'),
        mapStageFocus: document.getElementById('map-stage-focus'),
        mapToggleLinks: document.getElementById('map-toggle-links'),
        mapZoomOut: document.getElementById('map-zoom-out'),
        mapFit: document.getElementById('map-fit'),
        mapZoomIn: document.getElementById('map-zoom-in'),
        mapEmpty: document.getElementById('map-empty'),
        mapSvg: document.getElementById('knowledge-map-svg'),
        mapNodeAnchor: document.getElementById('map-node-anchor'),
        mapNodeTitle: document.getElementById('map-node-title'),
        mapNodeSummary: document.getElementById('map-node-summary'),
        mapNodeValue: document.getElementById('map-node-value'),
        mapNodeEvidence: document.getElementById('map-node-evidence'),
        mapJump: document.getElementById('map-jump'),
        mapCopyNote: document.getElementById('map-copy-note'),
        mapRelatedSources: document.getElementById('map-related-sources'),
        mapPathList: document.getElementById('map-path-list'),
        summaryStatus: document.getElementById('summary-status'),
        summaryDescription: document.getElementById('summary-description'),
        summaryProblem: document.getElementById('summary-problem'),
        summaryValue: document.getElementById('summary-value'),
        summaryMainline: document.getElementById('summary-mainline'),
        summaryChapters: document.getElementById('summary-chapters'),
        summaryFramework: document.getElementById('summary-framework'),
        summaryReview: document.getElementById('summary-review'),
        summaryCards: Array.from(document.querySelectorAll('[data-summary-card]')),
        summaryDialog: document.getElementById('summary-dialog'),
        summaryDialogTitle: document.getElementById('summary-dialog-title'),
        summaryDialogEyebrow: document.getElementById('summary-dialog-eyebrow'),
        summaryDialogClose: document.getElementById('summary-dialog-close'),
        summaryReader: document.getElementById('summary-reader'),
        summaryStructured: document.getElementById('summary-structured'),
        summaryArticle: document.getElementById('summary-article'),
        summaryToc: document.getElementById('summary-toc'),
        summaryModes: Array.from(document.querySelectorAll('[data-summary-mode]')),
        collectionSummaryText: document.getElementById('collection-summary-text'),
        collectionSummaryVisual: document.getElementById('collection-summary-visual'),
        collectionSummaryTextPanel: document.getElementById('collection-summary-text-panel'),
        collectionSummaryVisualPanel: document.getElementById('collection-summary-visual-panel'),
        collectionSummaryArticle: document.getElementById('collection-summary-article'),
        collectionSummaryVisualRoot: document.getElementById('collection-summary-visual-root'),
        generateSummary: document.getElementById('generate-summary'),
        summaryProgressText: document.getElementById('summary-progress-text'),
        summaryProgressFill: document.getElementById('summary-progress-fill'),
        exportMarkdown: document.getElementById('export-markdown'),
        sourceTitle: document.getElementById('source-title'),
        sourceMeta: document.getElementById('source-meta'),
        sourceTiming: document.getElementById('source-timing'),
        sourceError: document.getElementById('source-error'),
        sourceSummary: document.getElementById('source-summary'),
        sourceSummaryPreview: document.getElementById('source-summary-preview'),
        sourceSummarySource: document.getElementById('source-summary-source'),
        regenerateSourceSummary: document.getElementById('regenerate-source-summary'),
        sourceTranscript: document.getElementById('source-transcript'),
        openSource: document.getElementById('open-source'),
        openSourceFile: document.getElementById('open-source-file'),
        retrySource: document.getElementById('retry-source'),
        markdownRendered: document.getElementById('markdown-rendered'),
        markdownPreview: document.getElementById('markdown-preview'),
        markdownPreviewMode: document.getElementById('markdown-preview-mode'),
        markdownSourceMode: document.getElementById('markdown-source-mode'),
        collectionVisualRoot: document.getElementById('collection-visual-root'),
        collectionVisualOverviewStatus: document.getElementById('collection-visual-overview-status'),
        collectionVisualOverviewRetry: document.getElementById('collection-visual-overview-retry'),
        collectionVisualFullNoteStatus: document.getElementById('collection-visual-full-note-status'),
        collectionVisualFullNoteRetry: document.getElementById('collection-visual-full-note-retry'),
        collectionVisualTheme: document.getElementById('collection-visual-theme'),
        collectionVisualExport: document.getElementById('collection-visual-export'),
        collectionVisualPrint: document.getElementById('collection-visual-print'),
        collectionVisualOpen: document.getElementById('collection-visual-open'),
        collectionSummaryReaderOpen: document.getElementById('collection-summary-reader-open'),
        collectionImmersiveReader: document.getElementById('collection-immersive-reader'),
        toast: document.getElementById('toast')
    };

    let activeType = 'video_course';
    let collections = [];
    let filterOptions = { creator_names: [], titles: [] };
    let currentCollection = null;
    let selectedSourceId = null;
    let currentView = 'map';
    let knowledgeMapScope = 'collection';
    let selectedMapNodeId = null;
    let knowledgeMaps = { collection: null, sources: {} };
    let knowledgeMapLoading = false;
    const knowledgeMapErrors = new Map();
    const knowledgeMapRequests = new Set();
    let knowledgeMapLoadedKeys = new Set();
    let customMapPositions = {};
    let mapZoom = DEFAULT_MAP_ZOOM;
    let mapFocused = false;
    let mapLinksVisible = true;
    let sourceDetails = {};
    let sourceSummaryDisplayMode = 'preview';
    let markdownDisplayMode = 'preview';
    let summaryMode = 'guide';
    let collectionSummaryMode = 'text';
    let lastSummaryTrigger = null;
    const sourceDetailRequests = new Map();
    let busy = false;
    const summaryProgressByCollection = new Map();
    let pendingImportMethod = 'local_files';
    let pollTimer = null;
    let toastTimer = null;
    let collectionVisual = {
        collectionId: '',
        documents: { overview: null, full_note: null },
        states: { overview: null, full_note: null },
        loading: { overview: false, full_note: false },
        pollTimers: { overview: null, full_note: null },
        activating: false,
        theme: 'study-notes'
    };
    let collectionReader = {
        state: null,
        open: false,
        trigger: null,
        scrollY: 0
    };
    let initialTarget = readInitialTarget();
    const SUMMARY_CARD_META = {
        problem: {
            title: '这个系列解决什么问题',
            mode: 'guide',
            aliases: ['这个系列解决什么问题', '解决什么问题', '中心问题']
        },
        value: {
            title: '为什么值得学',
            mode: 'guide',
            aliases: ['为什么值得学', '值得学', '学习价值']
        },
        mainline: {
            title: '全系列主线',
            mode: 'mainline',
            aliases: ['全系列主线', '主线', '课程主线']
        },
        chapters: {
            title: '章节地图',
            mode: 'chapters',
            aliases: ['章节地图', '章节作用', '小节地图', '模块地图', '章节索引']
        },
        framework: {
            title: '核心框架',
            mode: 'framework',
            aliases: ['核心框架', '核心概念', '判断标准', '方法步骤']
        },
        review: {
            title: '复习索引',
            mode: 'review',
            aliases: ['复习索引', '复习路径', '回看']
        }
    };
    const SUMMARY_MODE_TITLES = {
        guide: '导览',
        mainline: '全系列主线',
        chapters: '章节地图',
        framework: '核心框架',
        review: '复习索引',
        full: '全文'
    };

    function readInitialTarget() {
        const params = new URLSearchParams(window.location.search);
        return {
            collectionId: params.get('collection_id') || '',
            sourceId: params.get('source_id') || ''
        };
    }

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
        [els.pickFolder, els.pickFiles, els.appendFolder, els.appendFiles, els.cancelCollection].forEach((button) => {
            if (button) button.disabled = busy;
        });
        if (els.dropAction) {
            els.dropAction.setAttribute('aria-busy', busy ? 'true' : 'false');
            els.dropAction.classList.toggle('is-busy', busy);
        }
        [els.creator, els.title].forEach((field) => {
            field.disabled = busy;
        });
        els.typeTabs.forEach((button) => {
            button.disabled = busy;
        });
        if (busy) {
            els.generateSummary.disabled = true;
            els.exportMarkdown.disabled = true;
            if (els.mapGenerate) els.mapGenerate.disabled = true;
        }
    }

    function selectedCollectionKey() {
        return currentCollection && currentCollection.id ? String(currentCollection.id) : '';
    }

    function resetCollectionVisualState(collectionId) {
        if (collectionReader.open) closeCollectionReader(false);
        window.clearInterval(collectionVisual.pollTimers.overview);
        window.clearInterval(collectionVisual.pollTimers.full_note);
        if (summaryMode.startsWith('visual-section:')) summaryMode = 'guide';
        collectionVisual = {
            collectionId: String(collectionId || ''),
            documents: { overview: null, full_note: null },
            states: { overview: null, full_note: null },
            loading: { overview: false, full_note: false },
            pollTimers: { overview: null, full_note: null },
            activating: false,
            theme: collectionVisual.theme || 'study-notes'
        };
        if (els.collectionVisualTheme) {
            els.collectionVisualTheme.value = collectionVisual.theme;
        }
        if (!window.VisualLearning || !window.VisualLearning.createReaderState) return;
        if (!collectionReader.state) {
            collectionReader.state = window.VisualLearning.createReaderState(collectionId, 'text');
        } else {
            collectionReader.state.resetOwner(collectionId);
        }
    }

    function summaryProgressState(collectionId) {
        const key = String(collectionId || '');
        return key ? summaryProgressByCollection.get(key) : null;
    }

    function isSummaryGenerating(collectionId) {
        const state = summaryProgressState(collectionId);
        return Boolean(state && state.active);
    }

    function renderVisibleSummaryProgress() {
        const collectionId = selectedCollectionKey();
        const state = summaryProgressState(collectionId);
        const active = Boolean(state && state.active);
        const value = active ? Math.max(0, Math.min(100, state.percent || 0)) : 0;
        if (els.summaryProgressFill) {
            els.summaryProgressFill.style.width = `${value}%`;
        }
        if (els.summaryProgressText) {
            if (active) {
                els.summaryProgressText.textContent = state.label || 'AI 生成中';
            } else {
                const markdown = currentCollection && currentCollection.summary_markdown;
                els.summaryProgressText.textContent = markdown ? '重新生成全系列解读' : '生成全系列解读';
            }
        }
        if (els.generateSummary) {
            els.generateSummary.classList.toggle('generating', active);
            els.generateSummary.setAttribute('aria-busy', active ? 'true' : 'false');
            els.generateSummary.setAttribute('aria-valuenow', String(value));
            if (active) {
                els.generateSummary.disabled = true;
            }
        }
    }

    function updateSummaryProgress(collectionId, percent, label) {
        const key = String(collectionId || '');
        if (!key) return;
        const state = summaryProgressByCollection.get(key) || {
            active: true,
            startedAt: Date.now(),
            timer: null,
            percent: 0,
            label: ''
        };
        state.active = true;
        state.percent = Math.max(0, Math.min(100, percent || 0));
        if (label) state.label = label;
        summaryProgressByCollection.set(key, state);
        if (selectedCollectionKey() === key) renderVisibleSummaryProgress();
    }

    function startSummaryProgress(collectionId) {
        const key = String(collectionId || '');
        if (!key) return;
        const previous = summaryProgressByCollection.get(key);
        if (previous && previous.timer) window.clearInterval(previous.timer);
        const state = {
            active: true,
            startedAt: Date.now(),
            timer: null,
            percent: 8,
            label: '准备生成...'
        };
        summaryProgressByCollection.set(key, state);
        if (selectedCollectionKey() === key) renderVisibleSummaryProgress();
        state.timer = window.setInterval(() => {
            const latest = summaryProgressByCollection.get(key);
            if (!latest || !latest.active) {
                window.clearInterval(state.timer);
                return;
            }
            const elapsedSeconds = Math.max(1, Math.floor((Date.now() - latest.startedAt) / 1000));
            const percent = Math.min(92, 16 + elapsedSeconds * 3);
            latest.percent = percent;
            latest.label = `AI 生成中 ${elapsedSeconds}s`;
            summaryProgressByCollection.set(key, latest);
            if (selectedCollectionKey() === key) renderVisibleSummaryProgress();
        }, 1000);
    }

    function stopSummaryProgress(collectionId, label) {
        const key = String(collectionId || '');
        if (!key) return;
        const state = summaryProgressByCollection.get(key);
        if (state && state.timer) {
            window.clearInterval(state.timer);
        }
        if (state) {
            state.active = false;
            state.percent = 100;
            state.label = label || '生成完成';
            summaryProgressByCollection.set(key, state);
        }
        summaryProgressByCollection.delete(key);
        if (selectedCollectionKey() === key) renderVisibleSummaryProgress();
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
                title: '拖放专题文档到这里',
                subtitle: '也可以使用下方按钮选择文件或文件夹。',
                goal: '从同一专题文档中提炼知识结构、判断标准和可执行清单。'
            };
        }
        return {
            accept: VIDEO_EXTS.join(','),
            title: '拖放课程视频到这里',
            subtitle: '也可以使用下方按钮选择文件或文件夹。',
            goal: '从同一视频课程中提炼整体主题、章节关系和可复用方法论。'
        };
    }

    function setActiveType(type) {
        activeType = type;
        const config = typeConfig(type);
        els.typeTabs.forEach((tab) => {
            tab.classList.toggle('active', tab.dataset.type === type);
        });
        [els.filesInput, els.folderInput, els.appendFilesInput, els.appendFolderInput].forEach((input) => {
            if (input) input.setAttribute('accept', config.accept);
        });
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

    function formatDateTime(value) {
        if (!value) return '-';
        const parsed = new Date(value);
        if (Number.isNaN(parsed.getTime())) return String(value).slice(0, 16);
        return `${String(parsed.getMonth() + 1).padStart(2, '0')}-${String(parsed.getDate()).padStart(2, '0')} ${String(parsed.getHours()).padStart(2, '0')}:${String(parsed.getMinutes()).padStart(2, '0')}`;
    }

    function formatDate(value) {
        if (!value) return '';
        const parsed = new Date(value);
        if (Number.isNaN(parsed.getTime())) return String(value).slice(0, 10);
        return `${String(parsed.getMonth() + 1).padStart(2, '0')}-${String(parsed.getDate()).padStart(2, '0')}`;
    }

    function toDateParam(date) {
        return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
    }

    function dateRangeParams(value) {
        if (!value) return {};
        const now = new Date();
        if (value === 'today') {
            const today = toDateParam(now);
            return { date_from: today, date_to: today };
        }
        if (value === '7d' || value === '30d') {
            const days = value === '7d' ? 7 : 30;
            const start = new Date(now);
            start.setDate(start.getDate() - days + 1);
            return { date_from: toDateParam(start), date_to: toDateParam(now) };
        }
        return {};
    }

    function collectionTypeLabel(type) {
        return type === 'document_topic' ? '文档专题' : '视频课程';
    }

    function importMethodLabel(method) {
        const labels = {
            local_folder: '本地文件夹',
            local_files: '本地多文件',
            link_batch: '链接合集'
        };
        return labels[method] || method || '-';
    }

    function isTerminalSourceStatus(status) {
        return ['success', 'failed', 'canceled'].includes(status);
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

    function compactText(value, limit) {
        const text = String(value || '').replace(/\s+/g, ' ').trim();
        if (!text) return '';
        const max = limit || 80;
        return text.length > max ? `${text.slice(0, max).replace(/[，,。；;\s]+$/, '')}...` : text;
    }

    function normalizeMarkdownForPreview(markdown) {
        let text = String(markdown || '').trim();
        const fenced = text.match(/^```(?:markdown|md)?\s*\n([\s\S]*?)\n```$/i);
        if (fenced) {
            text = fenced[1].trim();
        }
        text = text.replace(/^```ya?ml\s*\n[\s\S]*?\n```\s*/i, '').trim();
        const lines = text.split(/\n/);
        if (lines[0] && lines[0].trim() === '---') {
            const end = lines.findIndex((line, index) => index > 0 && line.trim() === '---');
            if (end > 0) {
                return lines.slice(end + 1).join('\n').trim();
            }
        }
        return text
            .replace(/^```(?:markdown|md|ya?ml)?\s*/i, '')
            .replace(/```\s*$/i, '')
            .trim();
    }

    function renderInlineMarkdown(value) {
        return escapeHTML(value)
            .replace(/`([^`]+)`/g, '<code>$1</code>')
            .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
            .replace(/__(.+?)__/g, '<strong>$1</strong>');
    }

    function splitInlineNumberedItems(value) {
        const text = String(value || '').replace(/\s+/g, ' ').trim();
        if (!text) return null;
        const matches = Array.from(text.matchAll(/(?:^|[\s：:；;。])(\d{1,2})[.、)]\s+/g));
        if (matches.length < 2) return null;
        const firstIndex = matches[0].index || 0;
        const intro = text.slice(0, firstIndex).trim().replace(/[：:；;，,。]$/, '');
        const items = matches.map((match, index) => {
            const start = (match.index || 0) + match[0].length;
            const end = index + 1 < matches.length ? matches[index + 1].index : text.length;
            return text.slice(start, end).trim().replace(/[；;]\s*$/, '');
        }).filter(Boolean);
        return items.length > 1 ? { intro, items } : null;
    }

    function summaryAnchorId(title, index) {
        const slug = String(title || '')
            .replace(/[^\w\u4e00-\u9fa5]+/g, '-')
            .replace(/^-+|-+$/g, '')
            .slice(0, 40);
        return `summary-section-${index}-${slug || 'section'}`;
    }

    function buildSummarySections(markdown) {
        const text = normalizeMarkdownForPreview(markdown);
        if (!text) return [];
        const sections = [];
        let current = null;
        text.split(/\n/).forEach((line) => {
            const heading = line.trim().match(/^##\s+(.+)$/);
            if (heading) {
                if (current) sections.push(current);
                current = {
                    title: heading[1].trim(),
                    lines: []
                };
                return;
            }
            if (!current) {
                if (!sections.length) {
                    current = { title: '全系列导览', lines: [] };
                } else {
                    return;
                }
            }
            current.lines.push(line);
        });
        if (current) sections.push(current);
        return sections.map((section, index) => ({
            id: summaryAnchorId(section.title, index + 1),
            title: section.title,
            body: section.lines.join('\n').trim()
        })).filter((section) => section.title || section.body);
    }

    function collectionReaderTextSections(markdown) {
        return buildSummarySections(markdown).map((section) => ({
            id: section.id,
            title: section.title,
            markdown: [`## ${section.title}`, section.body].filter(Boolean).join('\n\n')
        }));
    }

    function visualSummarySections() {
        const state = collectionVisual.states.full_note || collectionVisual.states.overview || {};
        return (state.interpretation_sections || []).map((section) => ({
            id: String(section.id || ''),
            title: String(section.title || ''),
            body: String(section.markdown || '')
        })).filter((section) => section.id && (section.title || section.body));
    }

    function findSummarySection(sections, aliases) {
        return sections.find((section) => aliases.some((alias) => section.title.includes(alias))) || null;
    }

    function markdownToHTML(markdown) {
        const text = normalizeMarkdownForPreview(markdown);
        if (!text) return '';

        const output = [];
        const paragraph = [];
        let listTag = '';

        const flushParagraph = () => {
            if (!paragraph.length) return;
            const text = paragraph.join(' ');
            const inlineList = splitInlineNumberedItems(text);
            if (inlineList) {
                if (inlineList.intro) {
                    output.push(`<p>${renderInlineMarkdown(inlineList.intro)}</p>`);
                }
                output.push(`<ol class="lc-inline-numbered">${inlineList.items
                    .map((item) => `<li>${renderInlineMarkdown(item)}</li>`)
                    .join('')}</ol>`);
            } else {
                output.push(`<p>${renderInlineMarkdown(text)}</p>`);
            }
            paragraph.length = 0;
        };
        const closeList = () => {
            if (!listTag) return;
            output.push(`</${listTag}>`);
            listTag = '';
        };
        const openList = (tag) => {
            flushParagraph();
            if (listTag === tag) return;
            closeList();
            output.push(`<${tag}>`);
            listTag = tag;
        };

        text.split(/\n/).forEach((line) => {
            const trimmed = line.trim();
            if (!trimmed) {
                flushParagraph();
                closeList();
                return;
            }

            const heading = trimmed.match(/^(#{1,6})\s+(.+)$/);
            if (heading) {
                flushParagraph();
                closeList();
                const level = heading[1].length;
                output.push(`<h${level}>${renderInlineMarkdown(heading[2])}</h${level}>`);
                return;
            }

            const unordered = trimmed.match(/^[-*+]\s+(.+)$/);
            if (unordered) {
                openList('ul');
                output.push(`<li>${renderInlineMarkdown(unordered[1])}</li>`);
                return;
            }

            const ordered = trimmed.match(/^\d+[.、)]\s+(.+)$/);
            if (ordered) {
                openList('ol');
                output.push(`<li>${renderInlineMarkdown(ordered[1])}</li>`);
                return;
            }

            const quote = trimmed.match(/^>\s?(.+)$/);
            if (quote) {
                flushParagraph();
                closeList();
                output.push(`<blockquote>${renderInlineMarkdown(quote[1])}</blockquote>`);
                return;
            }

            if (/^-{3,}$/.test(trimmed)) {
                flushParagraph();
                closeList();
                output.push('<hr>');
                return;
            }

            paragraph.push(trimmed);
        });

        flushParagraph();
        closeList();
        return output.join('');
    }

    function renderMarkdownPreview(target, markdown, fallback) {
        if (!target) return;
        const text = String(markdown || '').trim() || fallback;
        target.classList.remove('lc-markdown-source');
        target.innerHTML = markdownToHTML(text) || `<p>${escapeHTML(fallback || '')}</p>`;
    }

    function renderMarkdownSource(target, markdown, fallback) {
        if (!target) return;
        target.classList.add('lc-markdown-source');
        target.textContent = String(markdown || '').trim() || fallback || '';
    }

    function setViewToggle(previewButton, sourceButton, mode) {
        if (!previewButton || !sourceButton) return;
        previewButton.classList.toggle('active', mode === 'preview');
        sourceButton.classList.toggle('active', mode === 'source');
    }

    function selectedSource() {
        const sources = currentCollection ? (currentCollection.sources || []) : [];
        return sources.find((item) => item.id === selectedSourceId) || sources[0] || null;
    }

    async function createCollection() {
        const creatorName = els.creator.value.trim();
        const title = els.title.value.trim();
        if (!creatorName) {
            els.creator.focus();
            throw new Error('请先填写 IP 名称');
        }
        if (!title) {
            els.title.focus();
            throw new Error('请先填写专题名称');
        }
        const config = typeConfig(activeType);
        const payload = await apiJSON('/api/collections', {
            method: 'POST',
            body: JSON.stringify({
                title,
                creator_name: creatorName,
                collection_type: activeType,
                goal: config.goal,
                import_method: pendingImportMethod
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

    async function loadFilterOptions() {
        if (!getToken()) {
            filterOptions = { creator_names: [], titles: [] };
            renderFilterOptions();
            return;
        }
        try {
            const payload = await apiJSON('/api/collections/filter-options');
            filterOptions = payload.data || { creator_names: [], titles: [] };
            renderFilterOptions();
        } catch (error) {
            filterOptions = { creator_names: [], titles: [] };
            renderFilterOptions();
        }
    }

    function selectedHistoryFilters() {
        const params = new URLSearchParams();
        const values = {
            creator_name: els.historyCreatorFilter.value,
            title: els.historyTopicFilter.value,
            collection_type: els.historyTypeFilter.value,
            status: els.historyStatusFilter.value
        };
        Object.keys(values).forEach((key) => {
            if (values[key]) params.set(key, values[key]);
        });
        const dateParams = dateRangeParams(els.historyDateFilter.value);
        Object.keys(dateParams).forEach((key) => params.set(key, dateParams[key]));
        return params;
    }

    async function loadCollections(options) {
        const opts = options || {};
        if (!getToken()) {
            collections = [];
            renderHistory();
            return;
        }

        try {
            const params = selectedHistoryFilters();
            const query = params.toString();
            const payload = await apiJSON(query ? `/api/collections?${query}` : '/api/collections');
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
        resetCollectionVisualState(collectionId);
        selectedSourceId = opts.sourceId || null;
        sourceDetails = {};
        knowledgeMaps = { collection: null, sources: {} };
        knowledgeMapErrors.clear();
        knowledgeMapLoading = false;
        knowledgeMapRequests.clear();
        knowledgeMapLoadedKeys = new Set();
        customMapPositions = {};
        mapZoom = DEFAULT_MAP_ZOOM;
        mapFocused = false;
        currentView = opts.sourceId ? 'source' : 'map';
        knowledgeMapScope = opts.sourceId ? 'source' : 'collection';
        selectedMapNodeId = null;
        await refreshCollection(collectionId);
        const sources = currentCollection ? (currentCollection.sources || []) : [];
        const finished = sources.length > 0 && sources.every((source) => isTerminalSourceStatus(source.task_status));
        if (!finished) startPolling();
        if (!opts.silent) showToast('已打开历史专题');
    }

    async function importFiles(fileList, importMethod) {
        if (busy) {
            showToast('当前导入正在处理中');
            return;
        }
        const files = normalizeFiles(fileList);
        pendingImportMethod = importMethod || 'local_files';
        previewFiles(files);
        if (!files.length) {
            showToast('没有找到当前类型支持的文件');
            return;
        }

        setBusy(true);
        try {
            const collection = await createCollection();
            currentCollection = collection;
            resetCollectionVisualState(collection.id);
            selectedSourceId = null;
            knowledgeMapScope = 'collection';
            selectedMapNodeId = null;
            sourceDetails = {};
            knowledgeMaps = { collection: null, sources: {} };
            knowledgeMapErrors.clear();
            knowledgeMapLoading = false;
            knowledgeMapRequests.clear();
            knowledgeMapLoadedKeys = new Set();
            customMapPositions = {};
            mapZoom = DEFAULT_MAP_ZOOM;
            mapFocused = false;
            render();
            await uploadFiles(collection.id, files);
            showToast('已开始解析专题文件');
            await refreshCollection(collection.id);
            await loadFilterOptions();
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

    async function appendFilesToCurrentCollection(fileList, importMethod) {
        if (!currentCollection) {
            showToast('请先打开或创建一个专题');
            return;
        }
        const files = normalizeFiles(fileList);
        pendingImportMethod = importMethod || currentCollection.import_method || 'local_files';
        if (!files.length) {
            showToast('没有找到当前类型支持的文件');
            return;
        }

        setBusy(true);
        try {
            await uploadFiles(currentCollection.id, files);
            showToast('已追加 source，开始解析新增内容');
            await refreshCollection(currentCollection.id);
            await loadFilterOptions();
            await loadCollections({ selectLatest: false });
            startPolling();
        } catch (error) {
            showToast(error.message || '追加失败');
        } finally {
            setBusy(false);
            render();
            if (els.appendFolderInput) els.appendFolderInput.value = '';
            if (els.appendFilesInput) els.appendFilesInput.value = '';
        }
    }

    async function cancelCurrentCollection() {
        if (!currentCollection) {
            showToast('请先打开一个专题');
            return;
        }
        const sources = currentCollection.sources || [];
        const activeCount = sources.filter((source) => !isTerminalSourceStatus(source.task_status)).length;
        if (!activeCount) {
            showToast('当前没有正在解析的 source');
            return;
        }
        if (!window.confirm(`停止 ${activeCount} 个未完成 source 的解析？已完成内容会保留。`)) {
            return;
        }

        setBusy(true);
        try {
            const payload = await apiJSON(`/api/collections/${currentCollection.id}/cancel`, { method: 'POST' });
            window.clearInterval(pollTimer);
            await refreshCollection(currentCollection.id);
            await loadCollections({ selectLatest: false });
            const canceledCount = payload.data && payload.data.canceled_count;
            showToast(`已停止 ${canceledCount || activeCount} 个未完成 source`);
        } catch (error) {
            showToast(error.message || '停止解析失败');
        } finally {
            setBusy(false);
            render();
        }
    }

    async function refreshCollection(collectionId) {
        const payload = await apiJSON(`/api/collections/${collectionId}`);
        currentCollection = payload.data;
        if (currentCollection.collection_type) {
            setActiveType(currentCollection.collection_type);
        }
        if (currentCollection.creator_name) {
            els.creator.value = currentCollection.creator_name;
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
        const labels = {
            summarized: '已总结',
            ready: '待总结',
            processing: '解析中',
            stopped: '已停止',
            failed: '有失败',
            draft: '未导入'
        };
        return labels[collection.workflow_status] || (collection.summary_status === 'success' ? '已总结' : '未导入');
    }

    function renderFilterOptions() {
        const creatorValue = els.historyCreatorFilter.value;
        const topicValue = els.historyTopicFilter.value;
        const creators = filterOptions.creator_names || [];
        const titles = filterOptions.titles || [];

        els.creatorOptions.innerHTML = creators.map((name) => `<option value="${escapeHTML(name)}"></option>`).join('');
        els.historyCreatorFilter.innerHTML = '<option value="">全部 IP</option>' + creators.map((name) => {
            const selected = name === creatorValue ? ' selected' : '';
            return `<option value="${escapeHTML(name)}"${selected}>${escapeHTML(name)}</option>`;
        }).join('');
        els.historyTopicFilter.innerHTML = '<option value="">全部专题</option>' + titles.map((title) => {
            const selected = title === topicValue ? ' selected' : '';
            return `<option value="${escapeHTML(title)}"${selected}>${escapeHTML(title)}</option>`;
        }).join('');
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
            const type = collectionTypeLabel(collection.collection_type);
            const count = Number(collection.source_count || 0);
            const metrics = collection.metrics || {};
            const elapsed = metrics.elapsed_seconds ? ` · ${formatDuration(metrics.elapsed_seconds)}` : '';
            const date = formatDate(collection.created_at);
            return `
                <button class="lc-history-item${active}" type="button" data-collection-id="${escapeHTML(collection.id)}">
                    <span>
                        <strong>${escapeHTML(collection.title)}</strong>
                        <small>${escapeHTML(collection.creator_name || '未归属')} · ${escapeHTML(type)} · ${count} 个 source${escapeHTML(elapsed)}${date ? ' · ' + escapeHTML(date) : ''}</small>
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
                const finished = sources.length > 0 && sources.every((source) => isTerminalSourceStatus(source.task_status));
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
            failed: '失败',
            canceled: '已取消'
        };
        return labels[status] || '等待';
    }

    function currentMapKey() {
        if (!currentCollection) return '';
        if (knowledgeMapScope === 'source') {
            const source = selectedSource();
            return source ? `source:${source.id}` : '';
        }
        return 'collection';
    }

    function currentKnowledgeMapError() {
        const key = currentMapKey();
        return key ? (knowledgeMapErrors.get(key) || '') : '';
    }

    function setKnowledgeMapError(key, message) {
        if (!key) return;
        if (message) knowledgeMapErrors.set(key, message);
        else knowledgeMapErrors.delete(key);
    }

    function currentStoredKnowledgeMap() {
        if (knowledgeMapScope === 'source') {
            const source = selectedSource();
            return source ? knowledgeMaps.sources[source.id] || null : null;
        }
        return knowledgeMaps.collection || null;
    }

    function storeKnowledgeMap(record) {
        if (!record || !record.map_json) return;
        if (record.scope === 'source') {
            const key = record.source_id || (record.map_json.nodes || [])
                .flatMap((node) => node.source_ids || [])[0];
            if (key) knowledgeMaps.sources[key] = record;
            return;
        }
        knowledgeMaps.collection = record;
    }

    function mapEndpoint() {
        const params = new URLSearchParams({ scope: knowledgeMapScope });
        const source = selectedSource();
        if (knowledgeMapScope === 'source' && source) {
            params.set('source_id', source.id);
        }
        return `/api/collections/${currentCollection.id}/knowledge-map?${params.toString()}`;
    }

    async function loadKnowledgeMap() {
        const key = currentMapKey();
        if (!key || knowledgeMapRequests.has(key) || knowledgeMapLoadedKeys.has(key) || currentStoredKnowledgeMap()) return;
        const source = selectedSource();
        if (knowledgeMapScope === 'source' && (!source || source.task_status !== 'success')) return;

        knowledgeMapRequests.add(key);
        try {
            const payload = await apiJSON(mapEndpoint());
            setKnowledgeMapError(key, '');
            knowledgeMapLoadedKeys.add(key);
            if (payload.data && payload.data.status !== 'not_started') {
                storeKnowledgeMap(payload.data);
            }
        } catch (error) {
            if (currentMapKey() === key) {
                setKnowledgeMapError(key, error.message || '读取知识地图失败');
            }
        } finally {
            knowledgeMapRequests.delete(key);
            render();
        }
    }

    async function generateKnowledgeMap() {
        if (!currentCollection) {
            showToast('请先选择一个专题');
            return;
        }
        const source = selectedSource();
        if (knowledgeMapScope === 'source' && (!source || source.task_status !== 'success')) {
            showToast('当前小节解析完成后才能生成地图');
            return;
        }
        const key = currentMapKey();
        const force = Boolean(currentStoredKnowledgeMap());
        knowledgeMapLoading = true;
        setKnowledgeMapError(key, '');
        render();
        try {
            showToast(force ? '正在重新生成知识地图' : '正在生成知识地图，可能需要几十秒');
            const payload = await apiJSON(`/api/collections/${currentCollection.id}/knowledge-map`, {
                method: 'POST',
                body: JSON.stringify({
                    scope: knowledgeMapScope,
                    source_id: knowledgeMapScope === 'source' && source ? source.id : null,
                    force
                })
            });
            storeKnowledgeMap(payload.data);
            setKnowledgeMapError(key, '');
            if (key) knowledgeMapLoadedKeys.add(key);
            selectedMapNodeId = null;
            showToast('知识地图已生成');
        } catch (error) {
            const message = error.message || '生成知识地图失败';
            setKnowledgeMapError(key, message);
            showToast(message);
        } finally {
            knowledgeMapLoading = false;
            render();
        }
    }

    function sourceById(sourceId) {
        const sources = currentCollection ? (currentCollection.sources || []) : [];
        return sources.find((source) => source.id === sourceId) || null;
    }

    function anchorLabel(anchor) {
        if (!anchor) return '';
        if (typeof anchor === 'string') return anchor;
        return anchor.label || anchor.type || '';
    }

    function layoutKnowledgeMapNodes(nodes) {
        if (!nodes.length) return [];
        const key = currentMapKey();
        const saved = customMapPositions[key] || {};
        const centerIndex = Math.max(0, nodes.findIndex((node) => node.kind === 'core'));
        const center = nodes[centerIndex];
        const others = nodes.filter((_, index) => index !== centerIndex);
        const positioned = [];
        const centerPosition = saved[center.id] || { x: 430, y: 296 };
        positioned[centerIndex] = { ...center, ...centerPosition, w: 300, h: 128 };

        const rightCount = others.length <= 3 ? others.length : Math.ceil(others.length / 2);
        const rightNodes = others.slice(0, rightCount);
        const leftNodes = others.slice(rightCount);
        const slots = (count, side) => {
            if (!count) return [];
            const top = count <= 2 ? 220 : 92;
            const bottom = count <= 2 ? 390 : 552;
            const span = count === 1 ? 0 : bottom - top;
            return Array.from({ length: count }, (_, index) => ({
                x: side === 'right' ? 780 : 110,
                y: count === 1 ? 296 : top + (span * index) / (count - 1)
            }));
        };
        const rightSlots = slots(rightNodes.length, 'right');
        const leftSlots = slots(leftNodes.length, 'left');

        rightNodes.concat(leftNodes).forEach((node, index) => {
            const w = 270;
            const h = 112;
            const fallback = index < rightNodes.length
                ? rightSlots[index]
                : leftSlots[index - rightNodes.length];
            const point = saved[node.id] || fallback || { x: 80, y: 96 };
            const originalIndex = nodes.findIndex((item) => item.id === node.id);
            positioned[originalIndex] = { ...node, ...point, w, h };
        });
        return positioned.filter(Boolean);
    }

    function normalizeMapRecord(record) {
        const raw = record && record.map_json;
        if (!raw || !Array.isArray(raw.nodes) || !raw.nodes.length) return null;
        const scope = raw.scope || knowledgeMapScope;
        const source = selectedSource();
        const nodes = raw.nodes.map((node, index) => {
            const sourceIds = Array.isArray(node.source_ids) && node.source_ids.length
                ? node.source_ids
                : (scope === 'source' && source ? [source.id] : []);
            const firstSource = sourceIds.map(sourceById).find(Boolean) || null;
            const anchor = node.anchor || {};
            return {
                id: node.id || `node-${index + 1}`,
                kind: node.kind || 'concept',
                title: node.title || `节点 ${index + 1}`,
                summary: node.summary || '',
                value: node.user_value || node.value || '',
                evidence: node.evidence || '',
                anchor: anchorLabel(anchor),
                anchorSeconds: typeof anchor === 'object' ? anchor.seconds : null,
                sourceIds,
                sourceId: firstSource ? firstSource.id : null,
                sourceTitle: firstSource ? firstSource.title : '',
                sourceViewToken: firstSource ? firstSource.view_token : ''
            };
        });
        const positioned = layoutKnowledgeMapNodes(nodes);
        const nodeIds = new Set(positioned.map((node) => node.id));
        let edges = (raw.edges || []).map((edge) => {
            if (Array.isArray(edge)) return [edge[0], edge[1]];
            return [edge.from, edge.to];
        }).filter(([from, to]) => nodeIds.has(from) && nodeIds.has(to) && from !== to);
        if (!edges.length && positioned.length > 1) {
            const center = positioned.find((node) => node.kind === 'core') || positioned[0];
            edges = positioned
                .filter((node) => node.id !== center.id)
                .map((node) => [center.id, node.id]);
        }
        return {
            type: scope,
            title: raw.title || (scope === 'collection' ? '集合知识地图' : `${source ? source.title : 'Source'} 知识地图`),
            subtitle: raw.central_question
                ? `中心问题：${raw.central_question}`
                : (raw.user_value || '点击节点查看它讲什么、有什么用，以及对应的原文位置。'),
            userValue: raw.user_value || '',
            nodes: positioned,
            edges,
            path: raw.path || []
        };
    }

    function currentKnowledgeMap() {
        if (!currentCollection) {
            return {
                empty: true,
                title: '知识地图',
                subtitle: '选择一个专题后生成。',
                message: '请选择历史专题，或先导入视频/文档。'
            };
        }
        const sources = currentCollection.sources || [];
        if (!sources.length) {
            return {
                empty: true,
                title: '集合知识地图',
                subtitle: '导入一个系列后生成集合地图。',
                message: '暂无源内容，先导入视频或文档。'
            };
        }
        const source = selectedSource();
        if (knowledgeMapScope === 'source' && source && source.task_status !== 'success') {
            return {
                empty: true,
                title: `${source.title} 知识地图`,
                subtitle: '当前小节解析完成后才能生成。',
                message: `当前状态：${statusLabel(source.task_status)}。解析完成后可生成小节地图。`
            };
        }
        if (knowledgeMapLoading || knowledgeMapRequests.has(currentMapKey())) {
            return {
                empty: true,
                title: knowledgeMapScope === 'collection' ? '集合知识地图' : `${source ? source.title : 'Source'} 知识地图`,
                subtitle: '正在读取或生成高质量知识地图。',
                message: 'AI 正在理解内容并提炼地图，请稍等。'
            };
        }
        const normalized = normalizeMapRecord(currentStoredKnowledgeMap());
        if (normalized) return normalized;

        const mapError = currentKnowledgeMapError();
        if (mapError) {
            return {
                empty: true,
                title: '知识地图',
                subtitle: '知识地图暂时不可用。',
                message: mapError
            };
        }
        return {
            empty: true,
            title: knowledgeMapScope === 'collection' ? '集合知识地图' : `${source ? source.title : 'Source'} 知识地图`,
            subtitle: knowledgeMapScope === 'collection'
                ? '生成后会展示系列主线、整体价值和每个 source 的贡献。'
                : '生成后会展示这份内容最关键的节点，并绑定原文位置。',
            message: knowledgeMapScope === 'collection'
                ? '集合地图尚未生成。点击“生成知识地图”，AI 会先理解各小节再提炼系列主线。'
                : '当前小节地图尚未生成。点击“生成知识地图”，AI 会基于摘要和逐字稿提炼关键节点。'
        };
    }

    function clearMapSvg() {
        if (els.mapSvg) els.mapSvg.innerHTML = '';
    }

    function svgEl(name, attrs) {
        const node = document.createElementNS('http://www.w3.org/2000/svg', name);
        Object.keys(attrs || {}).forEach((key) => node.setAttribute(key, attrs[key]));
        return node;
    }

    function nodeCenter(node) {
        return [node.x + node.w / 2, node.y + node.h / 2];
    }

    function edgePath(from, to) {
        const [x1, y1] = nodeCenter(from);
        const [x2, y2] = nodeCenter(to);
        const midX = (x1 + x2) / 2;
        return `M ${x1} ${y1} C ${midX} ${y1}, ${midX} ${y2}, ${x2} ${y2}`;
    }

    function findMapNode(map, nodeId) {
        return map.nodes.find((node) => node.id === nodeId) || map.nodes[0];
    }

    function renderSvgText(parent, text, x, y, className) {
        const label = svgEl('text', { x, y, class: className });
        label.textContent = text;
        parent.appendChild(label);
    }

    function textLines(value, maxChars, maxLines) {
        const chars = Array.from(String(value || '').replace(/\s+/g, ' ').trim());
        if (!chars.length) return [];
        const lines = [];
        let index = 0;
        while (index < chars.length && lines.length < maxLines) {
            lines.push(chars.slice(index, index + maxChars).join(''));
            index += maxChars;
        }
        if (index < chars.length && lines.length) {
            lines[lines.length - 1] = `${lines[lines.length - 1].replace(/[，,。；;\s]+$/, '')}...`;
        }
        return lines;
    }

    function renderWrappedSvgText(parent, text, x, y, className, maxChars, maxLines, lineHeight) {
        const label = svgEl('text', { x, y, class: className });
        textLines(text, maxChars, maxLines).forEach((line, index) => {
            const tspan = svgEl('tspan', {
                x,
                dy: index === 0 ? 0 : lineHeight
            });
            tspan.textContent = line;
            label.appendChild(tspan);
        });
        parent.appendChild(label);
    }

    function mapViewBox() {
        const baseWidth = 1160;
        const baseHeight = 720;
        const width = baseWidth / mapZoom;
        const height = baseHeight / mapZoom;
        return `${(baseWidth - width) / 2} ${(baseHeight - height) / 2} ${width} ${height}`;
    }

    function visibleMapEdges(map, activeNode) {
        if (!mapLinksVisible) return [];
        const nodes = map.nodes || [];
        const root = nodes.find((node) => node.kind === 'core') || nodes[0];
        if (!root) return [];
        return nodes
            .filter((node) => node.id !== root.id)
            .map((node) => [root.id, node.id]);
    }

    function saveMapNodePosition(node) {
        const key = currentMapKey();
        if (!key) return;
        customMapPositions[key] = customMapPositions[key] || {};
        customMapPositions[key][node.id] = {
            x: Math.round(node.x),
            y: Math.round(node.y)
        };
    }

    function makeMapNodeDraggable(group, node) {
        let dragging = false;
        let moved = false;
        let startX = 0;
        let startY = 0;
        let originX = node.x;
        let originY = node.y;
        group.addEventListener('pointerdown', (event) => {
            if (event.button !== 0) return;
            dragging = true;
            moved = false;
            startX = event.clientX;
            startY = event.clientY;
            originX = node.x;
            originY = node.y;
            group.setPointerCapture(event.pointerId);
        });
        group.addEventListener('pointermove', (event) => {
            if (!dragging) return;
            const dx = (event.clientX - startX) / mapZoom;
            const dy = (event.clientY - startY) / mapZoom;
            if (Math.abs(dx) + Math.abs(dy) > 3) moved = true;
            node.x = Math.max(16, Math.min(1120 - node.w, originX + dx));
            node.y = Math.max(16, Math.min(690 - node.h, originY + dy));
            group.setAttribute('transform', `translate(${node.x} ${node.y})`);
        });
        group.addEventListener('pointerup', (event) => {
            if (!dragging) return;
            dragging = false;
            group.releasePointerCapture(event.pointerId);
            group.dataset.dragged = moved ? '1' : '';
            if (moved) {
                saveMapNodePosition(node);
                renderKnowledgeMap();
            }
        });
    }

    function renderMapSvg(map, activeNode) {
        clearMapSvg();
        if (!els.mapSvg || map.empty) return;
        els.mapSvg.setAttribute('viewBox', mapViewBox());
        visibleMapEdges(map, activeNode).forEach(([fromId, toId]) => {
            const from = findMapNode(map, fromId);
            const to = findMapNode(map, toId);
            if (!from || !to) return;
            const edgeActive = activeNode && activeNode.kind !== 'core' && (
                from.id === activeNode.id || to.id === activeNode.id
            );
            const path = svgEl('path', {
                d: edgePath(from, to),
                class: `lc-map-edge${edgeActive ? ' active' : ''}`
            });
            els.mapSvg.appendChild(path);
        });
        map.nodes.forEach((node) => {
            const group = svgEl('g', {
                class: `lc-map-node ${node.kind || 'concept'}${node.id === activeNode.id ? ' active' : ''}`,
                transform: `translate(${node.x} ${node.y})`,
                role: 'button',
                tabindex: '0',
                'aria-label': node.title
            });
            group.dataset.nodeId = node.id;
            group.appendChild(svgEl('rect', {
                x: 0,
                y: 0,
                width: node.w,
                height: node.h,
                rx: 16,
                ry: 16
            }));
            const titleChars = Math.max(10, Math.floor((node.w - 32) / 19));
            const summaryChars = Math.max(14, Math.floor((node.w - 32) / 13));
            renderSvgText(group, node.anchor || '', 16, 24, 'lc-map-node-anchor');
            renderWrappedSvgText(group, node.title, 16, 52, 'lc-map-node-title', titleChars, 2, 22);
            renderWrappedSvgText(group, node.summary, 16, 84, 'lc-map-node-summary', summaryChars, 2, 17);
            group.addEventListener('click', () => {
                if (group.dataset.dragged) {
                    group.dataset.dragged = '';
                    return;
                }
                selectedMapNodeId = node.id;
                renderKnowledgeMap();
            });
            group.addEventListener('keydown', (event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    selectedMapNodeId = node.id;
                    renderKnowledgeMap();
                }
            });
            makeMapNodeDraggable(group, node);
            els.mapSvg.appendChild(group);
        });
    }

    function renderRelatedSources(node) {
        if (!els.mapRelatedSources) return;
        const sources = currentCollection ? (currentCollection.sources || []) : [];
        const relatedIds = node && node.sourceIds && node.sourceIds.length
            ? node.sourceIds
            : (node && node.sourceId ? [node.sourceId] : []);
        const related = relatedIds.length
            ? relatedIds.map(sourceById).filter(Boolean)
            : sources.slice(0, 4);
        if (!related.length) {
            els.mapRelatedSources.innerHTML = '<span class="lc-map-related-empty">暂无关联 source</span>';
            return;
        }
        els.mapRelatedSources.innerHTML = related.map((source, index) => `
            <button type="button" data-map-related-source="${escapeHTML(source.id)}" title="打开源内容">
                <span>${index + 1}</span>
                <div>
                    <strong>${escapeHTML(compactText(source.title, 28))}</strong>
                    <em>打开源内容</em>
                </div>
            </button>
        `).join('');
        els.mapRelatedSources.querySelectorAll('[data-map-related-source]').forEach((button) => {
            button.addEventListener('click', () => {
                openRelatedSource(button.dataset.mapRelatedSource).catch((error) => {
                    showToast(error.message || '打开源内容失败');
                });
            });
        });
    }

    function mapPathLabels(map) {
        const nodes = map.nodes || [];
        return (map.path || []).map((item) => {
            const node = nodes.find((candidate) => candidate.id === item);
            return node ? node.title : item;
        });
    }

    function renderMapInspector(map, activeNode) {
        if (!els.mapNodeTitle) return;
        const node = activeNode || {};
        els.mapNodeAnchor.textContent = node.anchor || '-';
        els.mapNodeTitle.textContent = node.title || '选择一个节点';
        els.mapNodeSummary.textContent = node.summary || '点击地图节点后，这里会显示它讲什么。';
        els.mapNodeValue.textContent = node.value || '帮助你快速判断是否需要复看这段内容。';
        els.mapNodeEvidence.textContent = node.evidence || '节点会绑定视频时间点或文档段落。';
        els.mapJump.disabled = !activeNode;
        els.mapCopyNote.disabled = !activeNode;
        els.mapJump.textContent = map.type === 'collection' && (node.sourceId || (node.sourceIds || []).length) ? '进入小节地图' : '查看原文位置';
        els.mapPathList.innerHTML = mapPathLabels(map).map((item, index) => `<li><span>${index + 1}</span>${escapeHTML(item)}</li>`).join('');
        renderRelatedSources(node);
    }

    function setIconButtonState(button, label, icon) {
        if (!button) return;
        button.setAttribute('aria-label', label);
        button.setAttribute('title', label);
        const iconNode = button.querySelector('span');
        if (iconNode) iconNode.textContent = icon;
    }

    function renderKnowledgeMap() {
        if (!els.mapView) return;
        const source = selectedSource();
        els.mapView.classList.toggle('focused', mapFocused);
        const key = currentMapKey();
        if (key && !currentStoredKnowledgeMap() && !knowledgeMapLoadedKeys.has(key) && !knowledgeMapRequests.has(key) && !currentKnowledgeMapError()) {
            loadKnowledgeMap();
        }
        const map = currentKnowledgeMap();
        els.mapTitle.textContent = map.title;
        els.mapSubtitle.textContent = map.subtitle;
        els.mapScopeCollection.classList.toggle('active', knowledgeMapScope === 'collection');
        els.mapScopeSource.classList.toggle('active', knowledgeMapScope === 'source');
        els.mapScopeSource.disabled = !(currentCollection && (currentCollection.sources || []).length);
        if (els.mapGenerate) {
            const canGenerate = Boolean(currentCollection && (currentCollection.sources || []).length)
                && !(knowledgeMapScope === 'source' && (!source || source.task_status !== 'success'));
            els.mapGenerate.disabled = busy || knowledgeMapLoading || !canGenerate;
            els.mapGenerate.textContent = currentStoredKnowledgeMap() ? '重新生成地图' : '生成知识地图';
        }
        if (els.mapFocus) {
            els.mapFocus.textContent = mapFocused ? '退出全屏' : '全屏查看';
        }
        if (els.mapStageFocus) {
            setIconButtonState(els.mapStageFocus, mapFocused ? '退出全屏' : '全屏查看', mapFocused ? '↙' : '⛶');
        }
        if (els.mapToggleLinks) {
            setIconButtonState(els.mapToggleLinks, mapLinksVisible ? '隐藏连线' : '显示连线', mapLinksVisible ? '⛓' : '⋯');
        }

        if (map.empty) {
            clearMapSvg();
            els.mapEmpty.textContent = map.message;
            els.mapEmpty.classList.remove('hidden');
            renderMapInspector(map, null);
            return;
        }

        els.mapEmpty.classList.add('hidden');
        if (!selectedMapNodeId || !map.nodes.some((node) => node.id === selectedMapNodeId)) {
            selectedMapNodeId = map.nodes[0].id;
        }
        const activeNode = findMapNode(map, selectedMapNodeId);
        renderMapSvg(map, activeNode);
        renderMapInspector(map, activeNode);
    }

    function activeMapNode() {
        const map = currentKnowledgeMap();
        if (map.empty) return null;
        return findMapNode(map, selectedMapNodeId);
    }

    function setMapZoom(nextZoom) {
        mapZoom = Math.max(0.72, Math.min(1.8, nextZoom));
        renderKnowledgeMap();
    }

    function fitKnowledgeMap() {
        mapZoom = DEFAULT_MAP_ZOOM;
        renderKnowledgeMap();
    }

    function toggleMapFocus() {
        mapFocused = !mapFocused;
        renderKnowledgeMap();
    }

    function toggleMapLinks() {
        mapLinksVisible = !mapLinksVisible;
        renderKnowledgeMap();
    }

    function openMapNodeTarget() {
        const node = activeMapNode();
        if (!node) return;
        const targetSourceId = node.sourceId || (node.sourceIds || [])[0];
        if (knowledgeMapScope === 'collection' && targetSourceId) {
            selectedSourceId = targetSourceId;
            knowledgeMapScope = 'source';
            selectedMapNodeId = null;
            setKnowledgeMapError(currentMapKey(), '');
            currentView = 'map';
            render();
            return;
        }
        if (node.sourceViewToken) {
            const timeHash = Number.isFinite(Number(node.anchorSeconds)) ? `#t=${Math.floor(Number(node.anchorSeconds))}` : '';
            window.open(`/view/${node.sourceViewToken}${timeHash}`, '_blank', 'noopener');
            return;
        }
        currentView = 'source';
        render();
    }

    function copyMapNodeNote() {
        const node = activeMapNode();
        if (!node) return;
        const note = [
            `## ${node.title}`,
            '',
            `- 位置：${node.anchor || '-'}`,
            `- 讲什么：${node.summary || '-'}`,
            `- 对我有什么用：${node.value || '-'}`,
            `- 原文证据：${node.evidence || '-'}`
        ].join('\n');
        const done = () => showToast('节点笔记已复制');
        const fallback = () => {
            const textarea = document.createElement('textarea');
            textarea.value = note;
            textarea.setAttribute('readonly', 'readonly');
            textarea.style.position = 'fixed';
            textarea.style.top = '-1000px';
            document.body.appendChild(textarea);
            textarea.select();
            const copied = document.execCommand('copy');
            textarea.remove();
            if (copied) done();
            else showToast('复制失败，请手动复制');
        };
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(note).then(done).catch(fallback);
            return;
        }
        fallback();
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
                knowledgeMapScope = 'source';
                selectedMapNodeId = null;
                setKnowledgeMapError(currentMapKey(), '');
                currentView = currentView === 'source' ? 'source' : 'map';
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
        const canceled = sources.filter((source) => source.task_status === 'canceled').length;
        const stopped = canceled ? ` · 已停止 ${canceled} 个` : '';
        const active = sources.find((source) => !isTerminalSourceStatus(source.task_status));
        const stage = active ? ` · 当前：${sourceStageText(active)}` : '';
        els.workspaceSubtitle.textContent = `${done}/${sources.length} 个 source 已完成${stopped}${elapsed}${stage}`;
    }

    function renderWorkspaceActions() {
        const sources = currentCollection ? (currentCollection.sources || []) : [];
        const hasCollection = Boolean(currentCollection);
        const hasActive = sources.some((source) => !isTerminalSourceStatus(source.task_status));
        [els.appendFolder, els.appendFiles].forEach((button) => {
            if (button) button.disabled = busy || !hasCollection;
        });
        if (els.cancelCollection) {
            els.cancelCollection.disabled = busy || !hasActive;
        }
    }

    function renderSummaryCard(target, points, fallback) {
        if (!target) return;
        target.classList.remove('lc-markdown-source');
        if (!points || !points.length) {
            target.innerHTML = `<p>${escapeHTML(fallback || '')}</p>`;
            return;
        }
        target.innerHTML = `<ul class="lc-summary-points">${points
            .map((point) => `<li>${renderInlineMarkdown(point)}</li>`)
            .join('')}</ul>`;
    }

    function sourcePositionsFromText(text) {
        const numbers = new Set();
        String(text || '').replace(/第\s*([0-9０-９][0-9０-９\s、,，/-]*)\s*节/g, (_, raw) => {
            raw.replace(/[0-9０-９]+/g, (value) => {
                const number = Number(value.replace(/[０-９]/g, (char) => String('０１２３４５６７８９'.indexOf(char))));
                if (Number.isFinite(number) && number > 0) numbers.add(number);
                return value;
            });
            return raw;
        });
        return Array.from(numbers).sort((a, b) => a - b);
    }

    function sourceByPosition(position) {
        const sources = currentCollection ? (currentCollection.sources || []) : [];
        return sources.find((source, index) => Number(source.position || index + 1) === Number(position)) || null;
    }

    function cleanStructuredLine(line) {
        return cleanSummaryLine(line)
            .replace(/^#+\s*/, '')
            .replace(/^\*\s*/, '')
            .trim();
    }

    function extractStructuredEntries(section, limit) {
        if (!section || !section.body) return [];
        const entries = [];
        section.body.split(/\n/).forEach((line) => {
            const clean = cleanStructuredLine(line);
            if (!clean) return;
            const inlineList = splitInlineNumberedItems(clean);
            if (inlineList) {
                inlineList.items.forEach((item) => entries.push(item));
                return;
            }
            if (/^(模块|第\s*[0-9０-９]+|想|抓|补|找|回看|复习)/.test(clean) || entries.length < 2) {
                entries.push(clean);
            }
        });
        if (!entries.length) {
            entries.push(...summarizeMarkdownSection(section.body, [section.title], limit || 4));
        }
        return entries
            .map((entry) => entry.replace(/\s+/g, ' ').trim())
            .filter(Boolean)
            .slice(0, limit || 6);
    }

    function renderSourceJumpButtons(text) {
        const positions = sourcePositionsFromText(text).slice(0, 6);
        if (!positions.length) return '';
        const buttons = positions.map((position) => {
            const source = sourceByPosition(position);
            if (!source) return '';
            return `<button class="lc-source-chip" type="button" data-summary-source-position="${position}">第 ${position} 节</button>`;
        }).filter(Boolean);
        return buttons.length ? `<div class="lc-source-chip-row">${buttons.join('')}</div>` : '';
    }

    function renderStructuredSummaryBlocks(markdown) {
        if (!els.summaryStructured) return;
        const sections = buildSummarySections(markdown);
        if (!sections.length) {
            els.summaryStructured.innerHTML = '<p>生成全系列解读后显示结构化阅读入口。</p>';
            return;
        }
        const groups = [
            {
                title: '按主线看',
                section: findSummarySection(sections, ['全系列主线', '主线', '课程主线']),
                limit: 4
            },
            {
                title: '按章节定位',
                section: findSummarySection(sections, ['章节地图', '模块地图', '章节索引']),
                limit: 7
            },
            {
                title: '按复习目的回看',
                section: findSummarySection(sections, ['复习索引', '复习路径', '回看']),
                limit: 6
            }
        ].filter((group) => group.section);

        els.summaryStructured.innerHTML = groups.map((group) => {
            const entries = extractStructuredEntries(group.section, group.limit);
            return `
                <section class="lc-summary-structure-group">
                    <h4>${escapeHTML(group.title)}</h4>
                    <div class="lc-summary-structure-list">
                        ${entries.map((entry) => `
                            <article class="lc-summary-structure-item">
                                <p>${renderInlineMarkdown(entry)}</p>
                                ${renderSourceJumpButtons(entry)}
                            </article>
                        `).join('')}
                    </div>
                </section>
            `;
        }).join('') || '<p>生成全系列解读后显示结构化阅读入口。</p>';

        els.summaryStructured.querySelectorAll('[data-summary-source-position]').forEach((button) => {
            button.addEventListener('click', () => {
                const source = sourceByPosition(button.dataset.summarySourcePosition);
                if (!source) return;
                selectedSourceId = source.id;
                currentView = 'source';
                knowledgeMapScope = 'source';
                selectedMapNodeId = null;
                render();
                closeSummaryDialog();
            });
        });
    }

    function summaryModeAliases(mode) {
        if (mode && mode.startsWith('card:')) {
            const key = mode.slice('card:'.length);
            return (SUMMARY_CARD_META[key] && SUMMARY_CARD_META[key].aliases) || [];
        }
        const aliases = {
            guide: ['导览', '课前', '这个系列解决什么问题', '解决什么问题', '为什么值得学', '学习价值'],
            mainline: ['全系列主线', '主线', '课程主线'],
            chapters: ['章节地图', '章节作用', '小节地图', '模块地图', '章节索引'],
            framework: ['核心框架', '核心概念', '判断标准', '方法步骤'],
            review: ['复习索引', '复习路径', '回看']
        };
        return aliases[mode] || [];
    }

    function summaryBaseMode(mode) {
        if (mode && mode.startsWith('card:')) {
            const key = mode.slice('card:'.length);
            return (SUMMARY_CARD_META[key] && SUMMARY_CARD_META[key].mode) || 'guide';
        }
        if (mode && mode.startsWith('section:')) return '';
        if (mode && mode.startsWith('visual-section:')) return '';
        return mode || 'guide';
    }

    function summaryDialogTitle(activeSection) {
        if (summaryMode && summaryMode.startsWith('card:')) {
            const key = summaryMode.slice('card:'.length);
            return (SUMMARY_CARD_META[key] && SUMMARY_CARD_META[key].title) || '全系列解读';
        }
        return SUMMARY_MODE_TITLES[summaryMode] || (activeSection && activeSection.title) || '全系列解读';
    }

    function activeSummarySection(sections) {
        if (!sections.length) return null;
        if (summaryMode.startsWith('visual-section:')) {
            const id = summaryMode.slice('visual-section:'.length);
            return sections.find((section) => section.id === id) || sections[0];
        }
        if (summaryMode.startsWith('section:')) {
            const id = summaryMode.slice('section:'.length);
            return sections.find((section) => section.id === id) || sections[0];
        }
        const aliases = summaryModeAliases(summaryMode);
        return findSummarySection(sections, aliases) || sections[0];
    }

    function renderSummaryModeButtons() {
        const activeBaseMode = summaryBaseMode(summaryMode);
        els.summaryModes.forEach((button) => {
            const active = button.dataset.summaryMode === activeBaseMode;
            button.classList.toggle('active', active);
            button.setAttribute('aria-selected', active ? 'true' : 'false');
        });
    }

    function renderSummaryCardStates(markdown) {
        const hasMarkdown = Boolean(markdown);
        els.summaryCards.forEach((card) => {
            const key = card.dataset.summaryCard || '';
            const meta = SUMMARY_CARD_META[key] || { title: '全系列解读' };
            const active = isSummaryDialogOpen() && summaryMode === `card:${key}`;
            card.classList.toggle('is-active', hasMarkdown && active);
            card.setAttribute('aria-disabled', hasMarkdown ? 'false' : 'true');
            card.setAttribute('aria-label', hasMarkdown ? `查看${meta.title}完整内容` : `${meta.title}尚未生成`);
        });
    }

    function renderSummaryDialogTitle(activeSection) {
        if (els.summaryDialogEyebrow) {
            els.summaryDialogEyebrow.textContent = '全系列解读';
        }
        if (els.summaryDialogTitle) {
            els.summaryDialogTitle.textContent = summaryDialogTitle(activeSection);
        }
    }

    function renderSummaryToc(sections, activeSection) {
        if (!els.summaryToc) return;
        if (!sections.length) {
            els.summaryToc.innerHTML = '<span>生成后显示目录</span>';
            return;
        }
        els.summaryToc.innerHTML = sections.map((section) => `
            <button class="${activeSection && section.id === activeSection.id ? 'active' : ''}" type="button" data-summary-anchor="${escapeHTML(section.id)}">
                ${escapeHTML(section.title)}
            </button>
        `).join('');
        const modePrefix = summaryMode.startsWith('visual-section:') ? 'visual-section:' : 'section:';
        els.summaryToc.querySelectorAll('[data-summary-anchor]').forEach((button) => {
            button.addEventListener('click', () => {
                summaryMode = `${modePrefix}${button.dataset.summaryAnchor}`;
                renderSummaryReader(currentCollection && currentCollection.summary_markdown, '');
                renderSummaryCardStates(currentCollection && currentCollection.summary_markdown);
            });
        });
    }

    function renderSummaryReader(markdown, fallback) {
        if (!els.summaryArticle) return;
        const sections = summaryMode.startsWith('visual-section:')
            ? visualSummarySections()
            : buildSummarySections(markdown);
        const activeSection = activeSummarySection(sections);
        renderSummaryDialogTitle(activeSection);
        renderSummaryModeButtons();
        renderSummaryToc(sections, activeSection);
        renderStructuredSummaryBlocks(markdown);
        if (!sections.length) {
            els.summaryArticle.innerHTML = `<p>${escapeHTML(fallback || '生成全系列解读后显示。')}</p>`;
            return;
        }
        const visibleSections = summaryMode === 'full' ? sections : [activeSection || sections[0]];
        els.summaryArticle.innerHTML = visibleSections.map((section) => `
            <section class="lc-reader-section" id="${escapeHTML(section.id)}" data-summary-section="${escapeHTML(section.id)}">
                <h2>${renderInlineMarkdown(section.title)}</h2>
                ${markdownToHTML(section.body)}
            </section>
        `).join('');
    }

    function isSummaryDialogOpen() {
        return Boolean(els.summaryDialog && (els.summaryDialog.open || els.summaryDialog.classList.contains('open')));
    }

    function openSummaryDialog(mode, trigger) {
        const markdown = currentCollection && currentCollection.summary_markdown;
        if (!markdown) {
            showToast('请先生成全系列解读');
            return;
        }
        summaryMode = mode || summaryMode || 'guide';
        lastSummaryTrigger = trigger || document.activeElement;
        renderSummaryReader(markdown, '');
        if (!els.summaryDialog) return;
        if (typeof els.summaryDialog.showModal === 'function') {
            if (!els.summaryDialog.open) {
                els.summaryDialog.showModal();
            }
            renderSummaryCardStates(markdown);
            return;
        }
        els.summaryDialog.classList.add('open');
        els.summaryDialog.removeAttribute('aria-hidden');
        renderSummaryCardStates(markdown);
    }

    function closeSummaryDialog() {
        if (!els.summaryDialog) return;
        if (typeof els.summaryDialog.close === 'function' && els.summaryDialog.open) {
            els.summaryDialog.close();
            return;
        }
        els.summaryDialog.classList.remove('open');
        els.summaryDialog.setAttribute('aria-hidden', 'true');
        renderSummaryCardStates(currentCollection && currentCollection.summary_markdown);
        if (lastSummaryTrigger && typeof lastSummaryTrigger.focus === 'function') {
            lastSummaryTrigger.focus();
        }
    }

    function renderMarkdownExport(markdown, ready) {
        const fallback = ready ? '集合已解析完成，请先点击“生成全系列解读”。' : '生成全系列解读后显示。';
        setViewToggle(els.markdownPreviewMode, els.markdownSourceMode, markdownDisplayMode);
        if (els.markdownRendered) {
            els.markdownRendered.classList.toggle('hidden', markdownDisplayMode !== 'preview');
        }
        if (els.markdownPreview) {
            els.markdownPreview.classList.toggle('hidden', markdownDisplayMode !== 'source');
        }

        if (markdownDisplayMode === 'source') {
            renderMarkdownSource(els.markdownPreview, markdown, fallback);
            return;
        }
        renderMarkdownPreview(els.markdownRendered, markdown, fallback);
    }

    function renderSourceSummary(markdown, fallback) {
        const content = previewText(markdown, 12000);
        setViewToggle(els.sourceSummaryPreview, els.sourceSummarySource, sourceSummaryDisplayMode);
        if (sourceSummaryDisplayMode === 'source') {
            renderMarkdownSource(els.sourceSummary, content, fallback);
            return;
        }
        renderMarkdownPreview(els.sourceSummary, content, fallback);
    }

    function sourceFailureReason(source, detail) {
        return (detail && detail.error_message)
            || (source && source.error_message)
            || (source && source.progress && source.progress.message)
            || '';
    }

    function renderSourceError(source, detail) {
        if (!els.sourceError) return;
        const failed = source && source.task_status === 'failed';
        const reason = failed ? sourceFailureReason(source, detail) : '';
        els.sourceError.classList.toggle('hidden', !failed);
        if (!failed) {
            els.sourceError.textContent = '';
            return;
        }
        els.sourceError.innerHTML = `<strong>失败原因</strong><span>${escapeHTML(reason || '任务处理失败，暂无更具体原因。')}</span>`;
    }

    function renderSummary() {
        const markdown = currentCollection && currentCollection.summary_markdown;
        const sources = currentCollection ? (currentCollection.sources || []) : [];
        const ready = sources.length > 0 && sources.every((source) => source.task_status === 'success');

        els.summaryStatus.textContent = markdown ? '全系列解读已生成' : '等待生成全系列解读';
        els.summaryDescription.textContent = markdown
            ? '已从课前导览和课后复习两个场景提炼全集主线、章节作用和复习路径。'
            : (ready ? '所有源内容已解析完成，点击“生成全系列解读”建立全集视角。' : '导入并解析完成后，先建立全集主线，再按复习目的定位具体章节。');
        const waitingText = ready ? '点击生成后展示。' : '解析完成后生成。';
        renderSummaryCard(els.summaryProblem, markdown ? summarizeMarkdownSection(markdown, ['这个系列解决什么问题', '解决什么问题', '中心问题'], 2) : [], waitingText);
        renderSummaryCard(els.summaryValue, markdown ? summarizeMarkdownSection(markdown, ['为什么值得学', '值得学', '学习价值'], 2) : [], waitingText);
        renderSummaryCard(els.summaryMainline, markdown ? summarizeMarkdownSection(markdown, ['全系列主线', '主线', '课程主线'], 2) : [], waitingText);
        renderSummaryCard(els.summaryChapters, markdown ? summarizeMarkdownSection(markdown, ['章节地图', '章节作用', '小节地图'], 2) : [], waitingText);
        renderSummaryCard(els.summaryFramework, markdown ? summarizeMarkdownSection(markdown, ['核心框架', '核心概念', '判断标准', '方法步骤'], 2) : [], waitingText);
        renderSummaryCard(els.summaryReview, markdown ? summarizeMarkdownSection(markdown, ['复习索引', '复习路径', '回看'], 2) : [], waitingText);
        renderCollectionSummaryArticle(markdown, waitingText);
        renderSummaryReader(markdown, waitingText);
        renderSummaryCardStates(markdown);
        renderMarkdownExport(markdown, ready);
        setCollectionSummaryMode(collectionSummaryMode, false);
        renderVisibleSummaryProgress();
        const collectionId = currentCollection && currentCollection.id;
        els.generateSummary.disabled = busy || !ready || isSummaryGenerating(collectionId);
        els.exportMarkdown.disabled = busy || !markdown;
    }

    function cleanSummaryLine(line) {
        return String(line || '')
            .replace(/^#{1,6}\s*/, '')
            .replace(/^[-*+]\s*/, '')
            .replace(/^\d+[.、)]\s*/, '')
            .replace(/^>\s?/, '')
            .replace(/^\s*[：:]\s*/, '')
            .replace(/\*\*/g, '')
            .replace(/__/g, '')
            .replace(/`/g, '')
            .trim();
    }

    function summarizeMarkdownSection(markdown, keywords, maxItems) {
        const text = normalizeMarkdownForPreview(markdown);
        if (!text) return [];
        const lines = text.split(/\n/);
        const limit = maxItems || 4;
        const collected = [];
        let inSection = false;
        for (let index = 0; index < lines.length; index += 1) {
            const raw = lines[index];
            const heading = raw.match(/^(#{1,6})\s+(.+)$/);
            const cleanHeading = cleanSummaryLine(raw);
            if (heading && keywords.some((keyword) => cleanHeading.includes(keyword))) {
                inSection = true;
                continue;
            }
            if (inSection && /^##\s+/.test(raw)) {
                break;
            }
            if (!inSection) continue;

            const clean = cleanSummaryLine(raw);
            if (!clean || clean === ':' || clean === '：') continue;
            if (/^source\s*\d+$/i.test(clean)) continue;
            if (/^第\s*\d+\s*节$/.test(clean)) continue;
            if (clean.length < 8 && !/[。？！：:]/.test(clean)) continue;
            if (collected.includes(clean)) continue;
            collected.push(compactText(clean, 88));
            if (collected.length >= limit) break;
        }
        if (collected.length) return collected;
        return lines
            .map(cleanSummaryLine)
            .filter(Boolean)
            .filter((line) => !/^source\s*\d+$/i.test(line))
            .slice(0, limit)
            .map((line) => compactText(line, 88));
    }

    async function ensureSourceDetail(sourceId) {
        if (!currentCollection || !sourceId) return null;
        const existing = sourceDetails[sourceId];
        if (existing && !existing.loading) return existing;
        if (sourceDetailRequests.has(sourceId)) {
            return sourceDetailRequests.get(sourceId);
        }
        sourceDetails[sourceId] = { loading: true };
        render();
        const request = apiJSON(`/api/collections/${currentCollection.id}/sources/${sourceId}`)
            .then((payload) => {
                sourceDetails[sourceId] = payload.data;
                return payload.data;
            })
            .catch((error) => {
                const detail = { error: error.message || '加载源内容失败' };
                sourceDetails[sourceId] = detail;
                return detail;
            })
            .finally(() => {
                sourceDetailRequests.delete(sourceId);
                render();
            });
        sourceDetailRequests.set(sourceId, request);
        return request;
    }

    async function loadSourceDetail(sourceId) {
        await ensureSourceDetail(sourceId);
    }

    function renderSelectedSource() {
        const sources = currentCollection ? (currentCollection.sources || []) : [];
        const source = sources.find((item) => item.id === selectedSourceId) || sources[0];

        if (!source) {
            els.sourceTitle.textContent = '选择一个源内容';
            els.sourceMeta.textContent = '左侧选择后查看详情。';
            els.sourceTiming.textContent = '';
            renderSourceError(null, null);
            renderSourceSummary('', '解析完成后显示。');
            els.sourceTranscript.textContent = '解析完成后显示。';
            els.openSource.classList.add('hidden');
            renderSourceSummaryAction(null, null);
            renderSourceRetryAction(null);
            if (els.openSourceFile) {
                els.openSourceFile.disabled = true;
                els.openSourceFile.textContent = '打开源内容';
            }
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
        if (['failed', 'canceled'].includes(source.task_status) && !detail) {
            loadSourceDetail(source.id);
        }
        renderSourceError(source, detail);
        renderSourceSummaryAction(source, detail);
        renderSourceRetryAction(source);
        renderSourceFileButton(detail);
        if (source.task_status === 'success' && !detail) {
            loadSourceDetail(source.id);
            renderSourceSummary('', '正在加载 AI 解读摘要...');
            els.sourceTranscript.textContent = '正在加载逐字稿...';
            return;
        }
        if (detail && detail.loading) {
            renderSourceSummary('', '正在加载 AI 解读摘要...');
            els.sourceTranscript.textContent = '正在加载逐字稿...';
            return;
        }
        if (detail && detail.error) {
            renderSourceSummary('', detail.error);
            els.sourceTranscript.textContent = detail.error;
            return;
        }

        if (source.task_status === 'failed') {
            const reason = sourceFailureReason(source, detail);
            renderSourceSummary('', reason ? `解析失败：${reason}` : '解析失败，暂无摘要。');
            els.sourceTranscript.textContent = reason ? `解析失败：${reason}` : '解析失败，暂无逐字稿。';
            return;
        }

        renderSourceSummary(
            detail && detail.summary,
            source.task_status === 'success' ? '这个源内容的单篇摘要还未生成或仍在处理中。' : '解析完成后显示。'
        );
        els.sourceTranscript.textContent = detail && detail.transcript
            ? previewText(detail.transcript, 12000)
            : (source.task_status === 'success' ? '未读取到逐字稿内容，请点击“查看解读页”查看完整页。' : '解析完成后显示。');
    }

    function renderSourceSummaryAction(source, detail) {
        if (!els.regenerateSourceSummary) return;
        const canRegenerate = Boolean(
            source
            && source.view_token
            && source.task_status === 'success'
            && !(detail && detail.loading)
        );
        els.regenerateSourceSummary.classList.toggle('hidden', !(source && source.view_token));
        els.regenerateSourceSummary.disabled = busy || !canRegenerate;
        els.regenerateSourceSummary.textContent = detail && detail.summary
            ? '重新生成 AI 解读'
            : '生成 AI 解读';
    }

    function renderSourceRetryAction(source) {
        if (!els.retrySource) return;
        const canRetry = Boolean(
            source
            && ['failed', 'canceled'].includes(source.task_status)
        );
        els.retrySource.classList.toggle('hidden', !canRetry);
        els.retrySource.disabled = busy || !canRetry;
    }

    function renderSourceFileButton(detail) {
        if (!els.openSourceFile) return;
        const access = detail && detail.source_access;
        if (!access) {
            els.openSourceFile.disabled = true;
            els.openSourceFile.textContent = '源内容加载中';
            return;
        }
        if (access.kind === 'online_url') {
            els.openSourceFile.disabled = false;
            els.openSourceFile.textContent = '打开源链接';
            return;
        }
        if (access.kind === 'local_file') {
            els.openSourceFile.disabled = false;
            els.openSourceFile.textContent = '打开本地目录';
            return;
        }
        els.openSourceFile.disabled = true;
        els.openSourceFile.textContent = access.kind === 'local_missing' ? '源内容已清理' : '源内容不可用';
    }

    function openWaitingSourceWindow() {
        const popup = window.open('about:blank', '_blank');
        if (popup && popup.document) {
            popup.document.title = '正在打开源内容';
            popup.document.body.innerHTML = '<p style="font:16px system-ui;margin:24px;">正在打开源内容...</p>';
        }
        return popup;
    }

    function closeSourceWindow(popup) {
        try {
            if (popup && !popup.closed) popup.close();
        } catch (error) {
            // Ignore browser window cleanup failures.
        }
    }

    function navigateSourceWindow(popup, url) {
        if (popup && !popup.closed) {
            try {
                popup.opener = null;
            } catch (error) {
                // Some browsers block opener mutation; navigation can still continue.
            }
            popup.location.href = url;
            return;
        }
        window.open(url, '_blank', 'noopener');
    }

    async function openSourceAccess(access, detail, pendingWindow) {
        if (!access) {
            closeSourceWindow(pendingWindow);
            showToast('源内容信息还在加载');
            return;
        }
        if (access.kind === 'online_url' && access.url) {
            navigateSourceWindow(pendingWindow, access.url);
            return;
        }
        if (access.kind === 'local_file' && access.reveal_url) {
            try {
                const token = getToken();
                if (!token) throw new Error('请先在工作台设置 API 令牌');
                const response = await fetch(access.reveal_url, {
                    method: 'POST',
                    headers: { Authorization: `Bearer ${token}` }
                });
                if (!response.ok) {
                    const data = await response.json().catch(() => ({}));
                    throw new Error(data.detail || data.message || '打开本地目录失败');
                }
                closeSourceWindow(pendingWindow);
                showToast('已在本地目录中定位源文件');
                return;
            } catch (error) {
                closeSourceWindow(pendingWindow);
                showToast(error.message || '打开本地目录失败');
                return;
            }
        }
        if (access.kind !== 'local_file' || !access.url) {
            if (access.view_url) {
                navigateSourceWindow(pendingWindow, access.view_url);
                showToast(access.kind === 'local_missing' ? '旧 source 没有保留本地源内容，已打开解读页' : '源内容不可用，已打开解读页');
                return;
            }
            closeSourceWindow(pendingWindow);
            showToast(access.kind === 'local_missing' ? '这个旧 source 没有保留本地源内容' : '源内容不可用');
            return;
        }
        try {
            const token = getToken();
            if (!token) throw new Error('请先在工作台设置 API 令牌');
            const response = await fetch(access.url, {
                headers: { Authorization: `Bearer ${token}` }
            });
            if (!response.ok) {
                const data = await response.json().catch(() => ({}));
                throw new Error(data.detail || data.message || '打开源内容失败');
            }
            const blob = await response.blob();
            const url = URL.createObjectURL(blob);
            navigateSourceWindow(pendingWindow, url);
            window.setTimeout(() => URL.revokeObjectURL(url), 60000);
        } catch (error) {
            closeSourceWindow(pendingWindow);
            showToast(error.message || '打开源内容失败');
        }
    }

    async function openRelatedSource(sourceId) {
        if (!sourceId) return;
        selectedSourceId = sourceId;
        const pendingWindow = openWaitingSourceWindow();
        const detail = await ensureSourceDetail(sourceId);
        if (detail && detail.error) {
            closeSourceWindow(pendingWindow);
            showToast(detail.error);
            return;
        }
        await openSourceAccess(detail && detail.source_access, detail, pendingWindow);
    }

    async function openSourceFile() {
        const source = selectedSource();
        if (!source) {
            showToast('请先选择一个 source');
            return;
        }
        const pendingWindow = openWaitingSourceWindow();
        const detail = await ensureSourceDetail(source.id);
        if (detail && detail.error) {
            closeSourceWindow(pendingWindow);
            showToast(detail.error);
            return;
        }
        await openSourceAccess(detail && detail.source_access, detail, pendingWindow);
    }

    async function regenerateSourceSummary() {
        const source = selectedSource();
        if (!source || !source.view_token) {
            showToast('当前源内容还没有可重新生成的解读页');
            return;
        }
        if (source.task_status !== 'success') {
            showToast('源内容解析完成后才能重新生成 AI 解读');
            return;
        }

        setBusy(true);
        renderSelectedSource();
        try {
            await apiJSON('/api/recalibrate', {
                method: 'POST',
                body: JSON.stringify({
                    view_token: source.view_token,
                    regenerate_summary: true
                })
            });
            source.task_status = 'calibrating';
            source.progress = {
                stage: 'calibrating',
                stage_label: '正在重新生成 AI 解读',
                percent: 84
            };
            if (sourceDetails[source.id]) {
                sourceDetails[source.id] = {
                    ...sourceDetails[source.id],
                    summary: '',
                    loading: false
                };
            }
            showToast('已提交重新生成 AI 解读');
            startPolling();
        } catch (error) {
            showToast(error.message || '重新生成 AI 解读失败');
        } finally {
            setBusy(false);
            render();
        }
    }

    async function retrySelectedSource() {
        const source = selectedSource();
        if (!currentCollection || !source) {
            showToast('请先选择一个 source');
            return;
        }
        if (!['failed', 'canceled'].includes(source.task_status)) {
            showToast('只有失败或已取消的 source 可以重新解析');
            return;
        }

        setBusy(true);
        renderSelectedSource();
        try {
            const payload = await apiJSON(`/api/collections/${currentCollection.id}/sources/${source.id}/retry`, {
                method: 'POST'
            });
            if (payload.data && payload.data.collection) {
                currentCollection = payload.data.collection;
            } else if (payload.data && payload.data.source) {
                const sources = currentCollection.sources || [];
                currentCollection.sources = sources.map((item) => (
                    item.id === payload.data.source.id ? payload.data.source : item
                ));
            }
            delete sourceDetails[source.id];
            sourceDetailRequests.delete(source.id);
            selectedSourceId = source.id;
            showToast('已重新提交解析');
            await loadCollections({ selectLatest: false });
            startPolling();
        } catch (error) {
            showToast(error.message || '重新解析失败');
        } finally {
            setBusy(false);
            render();
        }
    }

    function collectionVisualStatusText(documentType) {
        if (!currentCollection || !currentCollection.summary_markdown) {
            return '请先生成全系列解读';
        }
        if (collectionVisual.loading[documentType]) return '正在请求生成…';
        const state = collectionVisual.states[documentType];
        if (!state) {
            return (currentView === 'summary' && collectionSummaryMode === 'visual')
                ? '正在读取状态…'
                : '切换到图解版后加载';
        }
        if (state.uiError) return state.uiError;
        const latestStatus = state.latest_attempt && state.latest_attempt.status;
        if (latestStatus === 'failed' || state.phase === 'failed') {
            const error = state.latest_attempt && state.latest_attempt.error_message;
            return error || '生成失败，可单独重试';
        }
        if (latestStatus === 'pending' || state.phase === 'ready_for_generation') return '等待生成…';
        if (latestStatus === 'generating' || state.phase === 'generating_visual') {
            const progress = state.workflow_progress && state.workflow_progress.overall_percent;
            return Number.isFinite(Number(progress)) ? `生成中 ${Math.round(Number(progress))}%` : '生成中…';
        }
        if (state.stale) return '正在更新，当前版本仍可查看';
        if (collectionVisual.documents[documentType]) return '已完成';
        return '等待生成…';
    }

    function collectionReaderAccepts(collectionId, readerGeneration) {
        return Boolean(
            collectionReader.state
            && collectionReader.state.accepts(collectionId, readerGeneration)
        );
    }

    function isCollectionVisualConsumerActive() {
        return Boolean(
            collectionReader.open
            || currentView === 'visual'
            || (currentView === 'summary' && collectionSummaryMode === 'visual')
        );
    }

    function ensureCollectionReaderState(collectionId, mode) {
        if (!window.VisualLearning || !window.VisualLearning.createReaderState) return false;
        if (!collectionReader.state) {
            collectionReader.state = window.VisualLearning.createReaderState(collectionId, mode || 'text');
        } else if (collectionReader.state.snapshot().ownerId !== collectionId) {
            collectionReader.state.resetOwner(collectionId);
        }
        return true;
    }

    function summaryReaderSectionId(mode) {
        if (!mode || mode === 'full') return '';
        const sections = collectionReaderTextSections(currentCollection && currentCollection.summary_markdown);
        const target = findSummarySection(sections, summaryModeAliases(mode));
        return target ? target.id : '';
    }

    function renderCollectionSummaryArticle(markdown, fallback) {
        if (!els.collectionSummaryArticle) return;
        const sections = buildSummarySections(markdown);
        if (!sections.length) {
            renderMarkdownPreview(els.collectionSummaryArticle, markdown, fallback);
            return;
        }
        els.collectionSummaryArticle.classList.remove('lc-markdown-source');
        els.collectionSummaryArticle.innerHTML = sections.map((section) => `
            <section class="lc-summary-inline-section" id="${escapeHTML(section.id)}">
                <h2>${renderInlineMarkdown(section.title)}</h2>
                ${markdownToHTML(section.body)}
            </section>
        `).join('');
    }

    function focusCollectionSummaryArticle(sectionId) {
        const markdown = currentCollection && currentCollection.summary_markdown;
        if (!markdown) {
            showToast('请先生成全系列解读');
            return;
        }
        currentView = 'summary';
        setCollectionSummaryMode('text', false);
        renderTabs();
        window.requestAnimationFrame(() => {
            const target = sectionId ? document.getElementById(sectionId) : null;
            const element = target || els.collectionSummaryArticle;
            if (!element) return;
            element.tabIndex = -1;
            element.focus({ preventScroll: true });
            element.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
    }

    function renderCollectionReader() {
        if (!collectionReader.open || !els.collectionImmersiveReader) return;
        if (!window.VisualLearning || !window.VisualLearning.renderImmersiveReader) return;
        const snapshot = collectionReader.state.snapshot();
        const interpretationState = collectionVisual.states.full_note
            || collectionVisual.states.overview
            || {};
        const sections = interpretationState.interpretation_sections || [];
        const fullNoteState = collectionVisual.states.full_note || {};
        const textSections = collectionReaderTextSections(currentCollection && currentCollection.summary_markdown);
        window.VisualLearning.renderImmersiveReader(els.collectionImmersiveReader, {
            mode: snapshot.mode,
            sectionId: snapshot.sectionId,
            title: (currentCollection && currentCollection.title) || '全系列解读',
            contextLabel: '全系列沉浸阅读',
            globalMarkdown: (currentCollection && currentCollection.summary_markdown) || '',
            sections: snapshot.mode === 'text' ? textSections : sections,
            overview: collectionVisual.documents.overview,
            fullNote: null,
            fullNoteStale: Boolean(fullNoteState.stale),
            overviewStatus: collectionVisualStatusText('overview'),
            fullNoteStatus: collectionVisualStatusText('full_note'),
            theme: collectionVisual.theme,
            visualScope: 'global',
            visualSubtitle: '这是当前合集的全局图解，用来建立宏观结构；子内容图解请进入对应内容独立查看。'
        }, {
            onClose: () => closeCollectionReader(true),
            onModeChange: (mode) => {
                collectionReader.state.setMode(mode);
                renderCollectionReader();
                if (mode === 'visual') ensureCollectionVisualLayer('overview');
            },
            onSectionChange: (sectionId) => {
                collectionReader.state.setSection(sectionId);
                if (collectionReader.state.snapshot().mode !== 'visual') renderCollectionReader();
            },
            onGenerateOverview: () => requestCollectionVisual('overview', false),
            onGenerateFullNote: () => requestCollectionVisual('full_note', false),
            onExport: exportCollectionVisualSvg,
            onExportText: exportMarkdown,
            onSourceRef: (refId) => navigateCollectionVisualRef(refId),
            onSectionEvidence: (evidence) => {
                const references = (evidence && evidence.references) || [];
                if (references.length === 1) navigateCollectionVisualRef(references[0].refId);
                else if (references.length > 1) showToast('本节有多个依据，请在图中选择具体原文引用');
            }
        });
    }

    function openCollectionReader(mode, trigger, sectionId) {
        const collectionId = selectedCollectionKey();
        if (!collectionId || !currentCollection || !currentCollection.summary_markdown) {
            showToast('请先生成全系列解读');
            return;
        }
        if (!ensureCollectionReaderState(collectionId, mode)) return;
        collectionReader.state.setMode(mode);
        if (sectionId !== undefined) {
            collectionReader.state.setSection(sectionId);
        }
        collectionReader.open = true;
        collectionReader.trigger = trigger || document.activeElement;
        collectionReader.scrollY = window.scrollY;
        els.collectionImmersiveReader.hidden = false;
        document.body.classList.add('vl-reader-open');
        renderCollectionReader();
        if (mode === 'visual') ensureCollectionVisualLayer('overview');
        else ensureCollectionVisualLayer('overview', false);
    }

    function openCollectionSummaryReader(mode, trigger) {
        const markdown = currentCollection && currentCollection.summary_markdown;
        if (!markdown) {
            showToast('请先生成全系列解读');
            return;
        }
        summaryMode = mode || summaryMode || 'full';
        const sectionId = summaryReaderSectionId(summaryMode);
        lastSummaryTrigger = trigger || document.activeElement;
        focusCollectionSummaryArticle(sectionId);
        renderSummaryModeButtons();
        renderSummaryCardStates(markdown);
    }

    function renderInlineSummaryVisual() {
        if (!els.collectionSummaryVisualRoot) return;
        const markdown = currentCollection && currentCollection.summary_markdown;
        const overview = collectionVisual.documents.overview;
        els.collectionSummaryVisualRoot.replaceChildren();
        if (!markdown) {
            els.collectionSummaryVisualRoot.appendChild(document.createTextNode('生成全系列解读后显示图解。'));
            return;
        }
        if (overview && window.VisualLearning && window.VisualLearning.render) {
            const host = document.createElement('div');
            host.className = 'lc-summary-inline-diagram';
            const diagram = window.VisualLearning.render(host, overview, {
                readerMode: 'continuous',
                showInlineSourceRefs: false,
                onSourceRef: (refId) => navigateCollectionVisualRef(refId),
                onSectionEvidence: (evidence) => {
                    const references = (evidence && evidence.references) || [];
                    if (references.length === 1) navigateCollectionVisualRef(references[0].refId);
                    else if (references.length > 1) showToast('本节有多个依据，请在图中选择具体原文引用');
                }
            });
            diagram.classList.add('vl-diagram', 'vl-reader-visual-atlas');
            els.collectionSummaryVisualRoot.appendChild(host);
            return;
        }
        const empty = document.createElement('div');
        empty.className = 'lc-summary-visual-empty';
        const status = document.createElement('strong');
        status.textContent = collectionVisualStatusText('overview');
        const detail = document.createElement('p');
        detail.textContent = '这里展示合集层面的全局图解；每个子内容的图解仍在对应内容页查看。';
        empty.append(status, detail);
        if (markdown) {
            const action = document.createElement('button');
            action.className = 'lc-btn primary';
            action.type = 'button';
            action.textContent = collectionVisual.loading.overview ? '正在生成…' : '生成图解';
            action.disabled = collectionVisual.loading.overview;
            action.addEventListener('click', () => requestCollectionVisual('overview', false));
            empty.appendChild(action);
        }
        els.collectionSummaryVisualRoot.appendChild(empty);
    }

    function setCollectionSummaryMode(mode, generateIfMissing) {
        collectionSummaryMode = mode === 'visual' ? 'visual' : 'text';
        const visual = collectionSummaryMode === 'visual';
        if (els.collectionSummaryTextPanel) {
            els.collectionSummaryTextPanel.hidden = visual;
            els.collectionSummaryTextPanel.classList.toggle('is-active', !visual);
        }
        if (els.collectionSummaryVisualPanel) {
            els.collectionSummaryVisualPanel.hidden = !visual;
            els.collectionSummaryVisualPanel.classList.toggle('is-active', visual);
        }
        if (els.collectionSummaryText) {
            els.collectionSummaryText.classList.toggle('active', !visual);
            els.collectionSummaryText.setAttribute('aria-selected', visual ? 'false' : 'true');
            els.collectionSummaryText.tabIndex = visual ? -1 : 0;
        }
        if (els.collectionSummaryVisual) {
            els.collectionSummaryVisual.classList.toggle('active', visual);
            els.collectionSummaryVisual.setAttribute('aria-selected', visual ? 'true' : 'false');
            els.collectionSummaryVisual.tabIndex = visual ? 0 : -1;
        }
        if (visual) {
            renderInlineSummaryVisual();
            const collectionId = selectedCollectionKey();
            if (collectionId && currentCollection && currentCollection.summary_markdown) {
                ensureCollectionReaderState(collectionId, 'visual');
                ensureCollectionVisualLayer('overview', Boolean(generateIfMissing));
            }
        }
    }

    function closeCollectionReader(restorePosition) {
        if (!collectionReader.open) return;
        collectionReader.open = false;
        if (collectionReader.state) collectionReader.state.invalidate();
        stopCollectionVisualPoll('overview');
        stopCollectionVisualPoll('full_note');
        els.collectionImmersiveReader.hidden = true;
        els.collectionImmersiveReader.replaceChildren();
        document.body.classList.remove('vl-reader-open');
        if (restorePosition !== false) {
            window.scrollTo({ top: collectionReader.scrollY, behavior: 'auto' });
            if (collectionReader.trigger && typeof collectionReader.trigger.focus === 'function') {
                collectionReader.trigger.focus({ preventScroll: true });
            }
        }
    }

    function renderCollectionVisual() {
        if (!els.collectionVisualRoot) return;
        const overviewStatus = collectionVisualStatusText('overview');
        const fullNoteStatus = collectionVisualStatusText('full_note');
        els.collectionVisualOverviewStatus.textContent = overviewStatus;
        els.collectionVisualFullNoteStatus.textContent = fullNoteStatus;
        const canRetry = Boolean(currentCollection && currentCollection.summary_markdown);
        els.collectionVisualOverviewRetry.disabled = !canRetry || collectionVisual.loading.overview;
        els.collectionVisualFullNoteRetry.disabled = !canRetry || collectionVisual.loading.full_note;

        const overview = collectionVisual.documents.overview;
        els.collectionVisualExport.disabled = !overview;
        els.collectionVisualPrint.disabled = !overview;
        const message = document.createElement('div');
        message.className = 'lc-visual-entry';
        const title = document.createElement('strong');
        title.textContent = overview ? '合集全局图解已经准备好' : '合集全局图解将在图解版中生成';
        const detail = document.createElement('p');
        detail.textContent = canRetry
            ? '这里只展示合集宏观图解；子内容图解请进入对应内容页独立查看。'
            : '请先生成全系列解读。';
        message.append(title, detail);
        els.collectionVisualRoot.replaceChildren(message);
        renderCollectionReader();
        renderInlineSummaryVisual();
    }

    function storeCollectionVisualState(documentType, state) {
        collectionVisual.states[documentType] = state || {};
        const documentRecord = state && state.document;
        if (documentRecord && documentRecord.status === 'success' && documentRecord.document_json) {
            collectionVisual.documents[documentType] = documentRecord.document_json;
        }
        renderCollectionVisual();
        renderInlineSummaryVisual();
    }

    function stopCollectionVisualPoll(documentType) {
        window.clearInterval(collectionVisual.pollTimers[documentType]);
        collectionVisual.pollTimers[documentType] = null;
    }

    function startCollectionVisualPoll(collectionId, documentType) {
        stopCollectionVisualPoll(documentType);
        const readerGeneration = collectionReader.state.generation();
        collectionVisual.pollTimers[documentType] = window.setInterval(async () => {
            if (!isCollectionVisualConsumerActive() || !collectionReaderAccepts(collectionId, readerGeneration)) {
                stopCollectionVisualPoll(documentType);
                return;
            }
            try {
                const payload = await apiJSON(
                    `/api/visual-learning/collections/${encodeURIComponent(collectionId)}?document_type=${encodeURIComponent(documentType)}`
                );
                if (!collectionReaderAccepts(collectionId, readerGeneration)) return;
                const state = payload.data || {};
                storeCollectionVisualState(documentType, state);
                const latestStatus = state.latest_attempt && state.latest_attempt.status;
                if (!['pending', 'generating'].includes(latestStatus) && state.phase !== 'generating_visual') {
                    stopCollectionVisualPoll(documentType);
                }
            } catch (error) {
                stopCollectionVisualPoll(documentType);
                if (!collectionReaderAccepts(collectionId, readerGeneration)) return;
                storeCollectionVisualState(documentType, {
                    ...(collectionVisual.states[documentType] || {}),
                    uiError: error.message || '图解状态刷新失败'
                });
            }
        }, POLL_MS);
    }

    async function requestCollectionVisual(documentType, force) {
        const collectionId = selectedCollectionKey();
        if (!collectionId || !currentCollection.summary_markdown) return;
        if (!ensureCollectionReaderState(collectionId, 'visual')) return;
        const readerGeneration = collectionReader.state.generation();
        collectionVisual.loading[documentType] = true;
        renderCollectionVisual();
        renderInlineSummaryVisual();
        try {
            const payload = await apiJSON(
                `/api/visual-learning/collections/${encodeURIComponent(collectionId)}/generate`,
                {
                    method: 'POST',
                    body: JSON.stringify({
                        document_type: documentType,
                        style: collectionVisual.theme,
                        diagram_type: 'auto',
                        force: Boolean(force)
                    })
                }
            );
            if (!collectionReaderAccepts(collectionId, readerGeneration)) return;
            const state = payload.data || {};
            storeCollectionVisualState(documentType, state);
            const latestStatus = state.latest_attempt && state.latest_attempt.status;
            if (['pending', 'generating'].includes(latestStatus) || state.phase === 'generating_visual') {
                startCollectionVisualPoll(collectionId, documentType);
            }
        } catch (error) {
            if (!collectionReaderAccepts(collectionId, readerGeneration)) return;
            storeCollectionVisualState(documentType, {
                ...(collectionVisual.states[documentType] || {}),
                uiError: error.message || '图解生成失败'
            });
        } finally {
            if (collectionReaderAccepts(collectionId, readerGeneration)) {
                collectionVisual.loading[documentType] = false;
                renderCollectionVisual();
            }
        }
    }

    async function ensureCollectionVisualLayer(documentType, generateIfMissing = true) {
        const collectionId = selectedCollectionKey();
        if (!collectionId || !isCollectionVisualConsumerActive()) return;
        if (!ensureCollectionReaderState(collectionId, 'visual')) return;
        const readerGeneration = collectionReader.state.generation();
        try {
            const payload = await apiJSON(
                `/api/visual-learning/collections/${encodeURIComponent(collectionId)}?document_type=${encodeURIComponent(documentType)}`
            );
            if (!collectionReaderAccepts(collectionId, readerGeneration)) return;
            const state = payload.data || {};
            storeCollectionVisualState(documentType, state);
            const latestStatus = state.latest_attempt && state.latest_attempt.status;
            if (['pending', 'generating'].includes(latestStatus) || state.phase === 'generating_visual') {
                startCollectionVisualPoll(collectionId, documentType);
                return;
            }
            if (
                generateIfMissing
                && (!state.document || state.stale || latestStatus === 'failed' || state.phase === 'failed')
            ) {
                await requestCollectionVisual(documentType, Boolean(state.stale || latestStatus === 'failed'));
            }
        } catch (error) {
            if (!collectionReaderAccepts(collectionId, readerGeneration)) return;
            storeCollectionVisualState(documentType, { uiError: error.message || '图解状态读取失败' });
        }
    }

    async function activateCollectionVisuals() {
        if (!collectionReader.open || !currentCollection || !currentCollection.summary_markdown) {
            renderCollectionVisual();
            return;
        }
        const collectionId = selectedCollectionKey();
        if (collectionVisual.collectionId !== collectionId) resetCollectionVisualState(collectionId);
        if (collectionVisual.activating) return;
        collectionVisual.activating = true;
        try {
            await Promise.all(VISUAL_DOCUMENT_TYPES.map((documentType) => ensureCollectionVisualLayer(documentType)));
        } finally {
            if (selectedCollectionKey() === collectionId) collectionVisual.activating = false;
        }
    }

    function retryCollectionVisual(documentType) {
        if (!VISUAL_DOCUMENT_TYPES.includes(documentType)) return;
        requestCollectionVisual(documentType, true);
    }

    function parseCollectionVisualRef(refId) {
        const collectionId = selectedCollectionKey();
        const value = String(refId || '');
        const sourcePrefix = `collection:${collectionId}:source:`;
        if (value.startsWith(sourcePrefix)) {
            const sourceId = value.slice(sourcePrefix.length).split(':')[0];
            return sourceId ? { kind: 'source', sourceId: sourceId } : null;
        }
        const sectionPrefix = `collection:${collectionId}:summary:section:`;
        if (value.startsWith(sectionPrefix)) {
            const sectionId = value.slice(sectionPrefix.length);
            return sectionId ? { kind: 'summary', sectionId: sectionId } : null;
        }
        if (value === `collection:${collectionId}:summary`) {
            return { kind: 'summary', sectionId: '' };
        }
        return null;
    }

    async function navigateCollectionVisualRef(refId) {
        const target = parseCollectionVisualRef(refId);
        if (!target || !currentCollection) {
            showToast('当前引用无法定位');
            return;
        }
        if (target.kind === 'source') {
            const sourceId = target.sourceId;
            const source = (currentCollection.sources || []).find((item) => String(item.id) === sourceId);
            if (!source) {
                showToast('引用的源内容不在当前专题中');
                return;
            }
            selectedSourceId = sourceId;
            currentView = 'source';
            render();
            await ensureSourceDetail(sourceId);
            const sourceButton = Array.from(els.sourceList.querySelectorAll('[data-source-id]'))
                .find((button) => button.dataset.sourceId === sourceId);
            if (sourceButton) sourceButton.focus();
            return;
        }
        currentView = 'summary';
        render();
        const sections = visualSummarySections();
        const matching = target.sectionId
            ? sections.find((section) => section.id === target.sectionId)
            : null;
        if (target.sectionId && !matching) {
            showToast('对应的全系列解读小节已不存在');
            return;
        }
        const textSections = collectionReaderTextSections(currentCollection.summary_markdown);
        const readerSection = matching
            ? textSections.find((section) => section.id === matching.id)
            : null;
        focusCollectionSummaryArticle(readerSection ? readerSection.id : '');
        if (matching && !readerSection) {
            showToast('已打开全系列解读，当前图解引用无法精确定位到文字章节');
        }
    }

    function exportCollectionVisualSvg() {
        if (!window.VisualLearning) return;
        const source = collectionReader.open
            ? els.collectionImmersiveReader
            : els.collectionVisualRoot;
        const diagram = window.VisualLearning.activeDiagram(source);
        if (!diagram) {
            showToast('当前没有可导出的图解');
            return;
        }
        const title = (currentCollection && currentCollection.title) || 'collection';
        window.VisualLearning.exportSvg(diagram, `${title}-visual.svg`);
    }

    function renderTabs() {
        els.tabs.forEach((tab) => {
            tab.classList.toggle('active', tab.dataset.view === currentView);
        });
        els.mapView.classList.toggle('hidden', currentView !== 'map');
        els.visualView.classList.toggle('hidden', currentView !== 'visual');
        els.summaryView.classList.toggle('hidden', currentView !== 'summary');
        els.sourceView.classList.toggle('hidden', currentView !== 'source');
        els.markdownView.classList.toggle('hidden', currentView !== 'markdown');
    }

    function renderMetadata() {
        const collection = currentCollection;
        if (!collection) {
            els.metadataCreator.textContent = els.creator.value.trim() || '未选择';
            els.metadataType.textContent = collectionTypeLabel(activeType);
            els.metadataDescription.textContent = '解析完成后由 AI 生成';
            els.metadataStarted.textContent = '-';
            els.metadataCompleted.textContent = '-';
            els.metadataElapsed.textContent = '-';
            els.metadataImport.textContent = '-';
            els.metadataExport.textContent = '-';
            return;
        }

        const metrics = collection.metrics || {};
        els.metadataCreator.textContent = collection.creator_name || '未归属';
        els.metadataType.textContent = collectionTypeLabel(collection.collection_type);
        els.metadataDescription.textContent = collection.description || '解析完成后由 AI 生成';
        els.metadataStarted.textContent = formatDateTime(metrics.started_at || collection.created_at);
        els.metadataCompleted.textContent = metrics.completed_at ? formatDateTime(metrics.completed_at) : '-';
        els.metadataElapsed.textContent = metrics.elapsed_seconds ? formatDuration(metrics.elapsed_seconds) : '-';
        els.metadataImport.textContent = importMethodLabel(collection.import_method);
        els.metadataExport.textContent = collection.export_status === 'exported' ? '已导出 Obsidian' : '未导出';
    }

    function render() {
        const title = currentCollection ? currentCollection.title : (els.title.value.trim() || '未命名专题');
        els.workspaceTitle.textContent = title;
        renderHistory();
        renderMetadata();
        renderProgress();
        renderWorkspaceActions();
        renderSources();
        renderSummary();
        renderSelectedSource();
        renderKnowledgeMap();
        renderCollectionVisual();
        renderTabs();
    }

    async function generateSummary() {
        if (!currentCollection) {
            showToast('请先导入一个专题');
            return;
        }
        const collectionId = currentCollection.id;
        const collectionTitle = currentCollection.title || '当前合集';
        if (isSummaryGenerating(collectionId)) {
            showToast('这个合集正在生成全系列解读');
            return;
        }

        startSummaryProgress(collectionId);
        try {
            showToast(`正在生成「${collectionTitle}」全系列解读`);
            const payload = await apiJSON(`/api/collections/${collectionId}/summary`, { method: 'POST' });
            updateSummaryProgress(collectionId, 96, '正在渲染结果...');
            const updatedCollection = payload.data;
            stopSummaryProgress(collectionId, '生成完成');
            collections = collections.map((collection) => (
                collection.id === collectionId
                    ? {
                        ...collection,
                        summary_status: updatedCollection.summary_status,
                        export_status: updatedCollection.export_status,
                        workflow_status: updatedCollection.workflow_status,
                        updated_at: updatedCollection.updated_at || collection.updated_at,
                        metrics: updatedCollection.metrics || collection.metrics
                    }
                    : collection
            ));
            if (currentCollection && currentCollection.id === collectionId) {
                currentCollection = updatedCollection;
                currentView = 'markdown';
            } else {
                renderHistory();
            }
            showToast(`「${updatedCollection.title || collectionTitle}」全系列解读已生成`);
        } catch (error) {
            stopSummaryProgress(collectionId, '生成失败');
            showToast(error.message || `「${collectionTitle}」全系列解读失败`);
        } finally {
            render();
        }
    }

    async function exportMarkdown() {
        if (!currentCollection || !currentCollection.summary_markdown) {
            showToast('请先生成全系列解读');
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
            showToast('笔记已导出');
        } catch (error) {
            showToast(error.message || '导出失败');
        }
    }

    function bindEvents() {
        els.typeTabs.forEach((tab) => {
            tab.addEventListener('click', () => setActiveType(tab.dataset.type));
        });

        [els.creator, els.title].forEach((field) => {
            field.addEventListener('input', () => {
                if (!currentCollection) render();
            });
        });

        [els.historyCreatorFilter, els.historyTopicFilter, els.historyDateFilter, els.historyTypeFilter, els.historyStatusFilter].forEach((field) => {
            field.addEventListener('change', () => {
                currentCollection = null;
                resetCollectionVisualState('');
                selectedSourceId = null;
                knowledgeMapScope = 'collection';
                selectedMapNodeId = null;
                sourceDetails = {};
                knowledgeMaps = { collection: null, sources: {} };
                knowledgeMapErrors.clear();
                knowledgeMapLoading = false;
                knowledgeMapRequests.clear();
                knowledgeMapLoadedKeys = new Set();
                customMapPositions = {};
                mapZoom = DEFAULT_MAP_ZOOM;
                mapFocused = false;
                loadCollections().catch((error) => {
                    showToast(error.message || '历史专题筛选失败');
                });
                render();
            });
        });

        els.historyReset.addEventListener('click', () => {
            els.historyCreatorFilter.value = '';
            els.historyTopicFilter.value = '';
            els.historyDateFilter.value = '';
            els.historyTypeFilter.value = '';
            els.historyStatusFilter.value = '';
            resetCollectionVisualState('');
            currentCollection = null;
            selectedSourceId = null;
            knowledgeMapScope = 'collection';
            selectedMapNodeId = null;
            sourceDetails = {};
            knowledgeMaps = { collection: null, sources: {} };
            knowledgeMapErrors.clear();
            knowledgeMapLoading = false;
            knowledgeMapRequests.clear();
            knowledgeMapLoadedKeys = new Set();
            customMapPositions = {};
            mapZoom = DEFAULT_MAP_ZOOM;
            mapFocused = false;
            loadCollections({ selectLatest: false }).catch((error) => {
                showToast(error.message || '历史专题加载失败');
            });
            render();
        });

        els.pickFolder.addEventListener('click', () => els.folderInput.click());
        els.pickFiles.addEventListener('click', () => els.filesInput.click());
        if (els.appendFolder) {
            els.appendFolder.addEventListener('click', () => els.appendFolderInput.click());
        }
        if (els.appendFiles) {
            els.appendFiles.addEventListener('click', () => els.appendFilesInput.click());
        }
        if (els.cancelCollection) {
            els.cancelCollection.addEventListener('click', cancelCurrentCollection);
        }
        els.folderInput.addEventListener('change', () => importFiles(els.folderInput.files, 'local_folder'));
        els.filesInput.addEventListener('change', () => importFiles(els.filesInput.files, 'local_files'));
        if (els.appendFolderInput) {
            els.appendFolderInput.addEventListener('change', () => appendFilesToCurrentCollection(els.appendFolderInput.files, 'local_folder'));
        }
        if (els.appendFilesInput) {
            els.appendFilesInput.addEventListener('change', () => appendFilesToCurrentCollection(els.appendFilesInput.files, 'local_files'));
        }

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
        els.dropAction.addEventListener('drop', (event) => importFiles(event.dataTransfer.files, 'local_files'));

        els.mapScopeCollection.addEventListener('click', () => {
            knowledgeMapScope = 'collection';
            selectedMapNodeId = null;
            setKnowledgeMapError(currentMapKey(), '');
            currentView = 'map';
            render();
        });
        els.mapScopeSource.addEventListener('click', () => {
            if (!(currentCollection && (currentCollection.sources || []).length)) return;
            knowledgeMapScope = 'source';
            selectedMapNodeId = null;
            setKnowledgeMapError(currentMapKey(), '');
            currentView = 'map';
            render();
        });
        els.mapJump.addEventListener('click', openMapNodeTarget);
        els.mapCopyNote.addEventListener('click', copyMapNodeNote);
        if (els.mapGenerate) {
            els.mapGenerate.addEventListener('click', generateKnowledgeMap);
        }
        if (els.mapFocus) {
            els.mapFocus.addEventListener('click', toggleMapFocus);
        }
        if (els.mapStageFocus) {
            els.mapStageFocus.addEventListener('click', toggleMapFocus);
        }
        if (els.mapToggleLinks) {
            els.mapToggleLinks.addEventListener('click', toggleMapLinks);
        }
        if (els.mapZoomOut) {
            els.mapZoomOut.addEventListener('click', () => setMapZoom(mapZoom - 0.16));
        }
        if (els.mapFit) {
            els.mapFit.addEventListener('click', fitKnowledgeMap);
        }
        if (els.mapZoomIn) {
            els.mapZoomIn.addEventListener('click', () => setMapZoom(mapZoom + 0.16));
        }
        if (els.openSourceFile) {
            els.openSourceFile.addEventListener('click', openSourceFile);
        }
        if (els.regenerateSourceSummary) {
            els.regenerateSourceSummary.addEventListener('click', regenerateSourceSummary);
        }
        if (els.retrySource) {
            els.retrySource.addEventListener('click', retrySelectedSource);
        }
        if (els.sourceSummaryPreview) {
            els.sourceSummaryPreview.addEventListener('click', () => {
                sourceSummaryDisplayMode = 'preview';
                renderSelectedSource();
            });
        }
        if (els.sourceSummarySource) {
            els.sourceSummarySource.addEventListener('click', () => {
                sourceSummaryDisplayMode = 'source';
                renderSelectedSource();
            });
        }
        if (els.markdownPreviewMode) {
            els.markdownPreviewMode.addEventListener('click', () => {
                markdownDisplayMode = 'preview';
                renderSummary();
            });
        }
        if (els.markdownSourceMode) {
            els.markdownSourceMode.addEventListener('click', () => {
                markdownDisplayMode = 'source';
                renderSummary();
            });
        }

        els.tabs.forEach((tab) => {
            tab.addEventListener('click', () => {
                const requestedView = tab.dataset.view || 'map';
                currentView = requestedView === 'visual' ? 'summary' : requestedView;
                render();
                if (requestedView === 'visual') {
                    setCollectionSummaryMode('visual', true);
                } else if (currentView === 'summary') {
                    setCollectionSummaryMode('text', false);
                } else {
                    stopCollectionVisualPoll('overview');
                    stopCollectionVisualPoll('full_note');
                }
            });
        });
        if (els.collectionSummaryText) {
            els.collectionSummaryText.addEventListener('click', () => setCollectionSummaryMode('text', false));
        }
        if (els.collectionSummaryVisual) {
            els.collectionSummaryVisual.addEventListener('click', () => setCollectionSummaryMode('visual', true));
        }
        if (els.collectionVisualOverviewRetry) {
            els.collectionVisualOverviewRetry.addEventListener('click', () => retryCollectionVisual('overview'));
        }
        if (els.collectionVisualFullNoteRetry) {
            els.collectionVisualFullNoteRetry.addEventListener('click', () => retryCollectionVisual('full_note'));
        }
        if (els.collectionVisualTheme) {
            els.collectionVisualTheme.addEventListener('change', () => {
                collectionVisual.theme = els.collectionVisualTheme.value;
                if (window.VisualLearning) {
                    window.VisualLearning.setTheme(els.collectionVisualRoot, collectionVisual.theme);
                    window.VisualLearning.setTheme(els.collectionImmersiveReader, collectionVisual.theme);
                }
            });
        }
        if (els.collectionVisualOpen) {
            els.collectionVisualOpen.addEventListener('click', () => {
                currentView = 'summary';
                render();
                setCollectionSummaryMode('visual', true);
            });
        }
        if (els.collectionSummaryReaderOpen) {
            els.collectionSummaryReaderOpen.addEventListener('click', () => {
                focusCollectionSummaryArticle('');
            });
        }
        if (els.collectionVisualExport) {
            els.collectionVisualExport.addEventListener('click', exportCollectionVisualSvg);
        }
        if (els.collectionVisualPrint) {
            els.collectionVisualPrint.addEventListener('click', () => window.print());
        }
        document.addEventListener('keydown', (event) => {
            if (event.key === 'Escape' && collectionReader.open) {
                event.preventDefault();
                closeCollectionReader(true);
            }
        });
        els.summaryCards.forEach((card) => {
            const openCard = () => {
                if (card.getAttribute('aria-disabled') === 'true') {
                    showToast('请先生成全系列解读');
                    return;
                }
                openCollectionSummaryReader(`card:${card.dataset.summaryCard || 'problem'}`, card);
            };
            card.addEventListener('click', openCard);
            card.addEventListener('keydown', (event) => {
                if (event.key !== 'Enter' && event.key !== ' ') return;
                event.preventDefault();
                openCard();
            });
        });
        if (els.summaryDialogClose) {
            els.summaryDialogClose.addEventListener('click', closeSummaryDialog);
        }
        if (els.summaryDialog) {
            els.summaryDialog.addEventListener('click', (event) => {
                if (event.target === els.summaryDialog) {
                    closeSummaryDialog();
                }
            });
            els.summaryDialog.addEventListener('close', () => {
                renderSummaryCardStates(currentCollection && currentCollection.summary_markdown);
                if (lastSummaryTrigger && typeof lastSummaryTrigger.focus === 'function') {
                    lastSummaryTrigger.focus();
                }
            });
        }
        els.summaryModes.forEach((button) => {
            button.addEventListener('click', () => {
                openCollectionSummaryReader(button.dataset.summaryMode || 'guide', button);
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
        await loadFilterOptions();
        if (initialTarget.collectionId) {
            await selectCollection(initialTarget.collectionId, {
                silent: true,
                sourceId: initialTarget.sourceId
            });
            initialTarget = { collectionId: '', sourceId: '' };
            await loadCollections({ selectLatest: false });
        } else {
            await loadCollections();
        }
    }

    init().catch((error) => showToast(error.message || '初始化失败'));
})();
