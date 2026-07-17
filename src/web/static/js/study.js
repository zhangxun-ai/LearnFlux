(function () {
    const STORAGE_KEY = 'vta_bearer_token';
    const ENCRYPTION_KEY = 'vta_encrypt_key_2024';
    const PLAYBACK_RATE_KEY = 'vta_study_playback_rate';
    let viewToken = window.STUDY_VIEW_TOKEN || '';
    let collectionId = window.STUDY_COLLECTION_ID || '';
    let sourceId = window.STUDY_SOURCE_ID || '';
    let pageMode = window.STUDY_PAGE_MODE || (viewToken ? 'single' : 'library');
    const playerRuntime = window.StudyPlayerRuntime;
    const state = {
        session: null,
        currentLineId: '',
        pollTimer: null,
        chatThinkingTimer: null,
        estimatedToken: '',
        visualDocuments: {},
        visualStates: {},
        visualLoading: new Set(),
        visualPollTimers: {},
        visualActivated: false,
        visualTabActive: false,
        activeVisualType: 'overview',
        requestedVisualSourceApplied: false,
        chatMessages: [],
        libraryKind: 'single',
        libraryTimer: null,
        localObjectUrl: '',
        progressSavedAt: 0,
        transcriptFollow: true,
        isSeeking: false,
        playbackRate: 1,
        noteContext: '',
        noteDocument: null,
        noteDirty: false,
        noteSaving: false,
        noteSaveTimer: null,
        noteLoadController: null,
        noteBinding: null,
        noteConflict: null,
    };

    const els = {
        title: document.getElementById('study-title'),
        studyPageContext: document.getElementById('study-page-context'),
        studyWorkbenchTitle: document.getElementById('study-workbench-title'),
        subtitle: document.getElementById('study-subtitle'),
        state: document.getElementById('study-state'),
        transcriptCount: document.getElementById('study-transcript-count'),
        aiModel: document.getElementById('study-ai-model'),
        breadcrumbs: document.getElementById('study-breadcrumbs'),
        videoTitle: document.getElementById('video-title'),
        videoMeta: document.getElementById('video-meta'),
        videoFrame: document.getElementById('video-frame'),
        video: document.getElementById('study-video'),
        videoEmpty: document.getElementById('video-empty'),
        audioTitle: document.getElementById('study-audio-title'),
        playToggle: document.getElementById('play-toggle'),
        progress: document.getElementById('video-progress'),
        videoTime: document.getElementById('video-time'),
        playbackRate: document.getElementById('playback-rate'),
        playStrip: document.getElementById('study-play-strip'),
        sourceCard: document.getElementById('study-source-card'),
        sourceName: document.getElementById('study-source-name'),
        sourceMeta: document.getElementById('study-source-meta'),
        studySourceOpen: document.getElementById('study-source-open'),
        progressCard: document.getElementById('study-progress-card'),
        progressTitle: document.getElementById('study-progress-title'),
        progressDetail: document.getElementById('study-progress-detail'),
        progressFill: document.getElementById('study-progress-fill'),
        retry: document.getElementById('study-retry'),
        aiOverview: document.getElementById('ai-overview'),
        aiOverviewMeta: document.getElementById('ai-overview-meta'),
        aiOverviewExpand: document.getElementById('ai-overview-expand'),
        aiReadingDialog: document.getElementById('ai-reading-dialog'),
        aiReadingContent: document.getElementById('ai-reading-content'),
        aiReadingClose: document.getElementById('ai-reading-close'),
        visualOverview: document.getElementById('visual-learning-overview'),
        visualStatus: document.getElementById('visual-learning-status'),
        visualStatusText: document.getElementById('visual-learning-status-text'),
        visualRetry: document.getElementById('visual-retry'),
        visualFullNoteStatus: document.getElementById('visual-full-note-status'),
        visualFullNoteStatusText: document.getElementById('visual-full-note-status-text'),
        visualFullNoteRetry: document.getElementById('visual-full-note-retry'),
        visualExpand: document.getElementById('visual-expand'),
        visualFullNote: document.getElementById('visual-full-note'),
        visualTheme: document.getElementById('visual-theme'),
        visualDialog: document.getElementById('visual-learning-dialog'),
        visualModalTitle: document.getElementById('visual-modal-title'),
        visualModalContent: document.getElementById('visual-learning-modal-content'),
        visualModalStatus: document.getElementById('visual-modal-status'),
        visualRegenerate: document.getElementById('visual-regenerate'),
        visualModalClose: document.getElementById('visual-modal-close'),
        visualExportSvg: document.getElementById('visual-export-svg'),
        visualPrint: document.getElementById('visual-print'),
        transcriptList: document.getElementById('transcript-list'),
        chatQuestion: document.getElementById('chat-question'),
        sendChat: document.getElementById('send-chat'),
        chatList: document.getElementById('chat-list'),
        askAiEntry: document.getElementById('ask-ai-entry'),
        toast: document.getElementById('study-toast'),
        exportMarkdown: document.getElementById('export-markdown'),
        copyCurrentLine: document.getElementById('copy-current-line'),
        library: document.getElementById('study-library'),
        player: document.getElementById('study-player'),
        librarySearch: document.getElementById('study-library-search'),
        libraryList: document.getElementById('study-library-list'),
        libraryState: document.getElementById('study-library-state'),
        libraryCount: document.getElementById('study-library-count'),
        libraryListTitle: document.getElementById('study-library-list-title'),
        singleImport: document.getElementById('study-single-import'),
        collectionImport: document.getElementById('study-collection-import'),
        singleFile: document.getElementById('study-single-file'),
        collectionFolder: document.getElementById('study-collection-folder'),
        collectionFiles: document.getElementById('study-collection-files'),
        collectionNav: document.getElementById('study-collection-nav'),
        collectionSelect: document.getElementById('study-collection-select'),
        collectionPrev: document.getElementById('study-collection-prev'),
        collectionNext: document.getElementById('study-collection-next'),
        collectionPosition: document.getElementById('study-collection-position'),
        currentCaption: document.getElementById('current-caption'),
        currentCaptionTime: document.getElementById('current-caption-time'),
        currentCaptionText: document.getElementById('current-caption-text'),
        askCurrentCaption: document.getElementById('ask-current-caption'),
        transcriptFollow: document.getElementById('transcript-follow'),
        noteEditor: document.getElementById('study-note-editor'),
        noteStatus: document.getElementById('study-note-status'),
        noteSync: document.getElementById('study-note-sync'),
        noteBinding: document.getElementById('study-note-binding'),
        bindingDialog: document.getElementById('obsidian-binding-dialog'),
        bindingClose: document.getElementById('obsidian-binding-close'),
        bindingCancel: document.getElementById('obsidian-binding-cancel'),
        bindingSave: document.getElementById('obsidian-binding-save'),
        bindingScope: document.getElementById('obsidian-binding-scope'),
        bindingStatus: document.getElementById('obsidian-binding-status'),
        transcriptDirectory: document.getElementById('obsidian-transcript-directory'),
        noteDirectory: document.getElementById('obsidian-note-directory'),
        conflictDialog: document.getElementById('obsidian-conflict-dialog'),
        conflictClose: document.getElementById('obsidian-conflict-close'),
        conflictTitle: document.getElementById('obsidian-conflict-title'),
        conflictMessage: document.getElementById('obsidian-conflict-message'),
        conflictApp: document.getElementById('obsidian-conflict-app'),
        conflictFile: document.getElementById('obsidian-conflict-file'),
    };

    function studyApiBase() {
        if (pageMode === 'collection' && collectionId && sourceId) {
            return `/api/study/collections/${encodeURIComponent(collectionId)}/sources/${encodeURIComponent(sourceId)}`;
        }
        return `/api/study/${encodeURIComponent(viewToken)}`;
    }

    function noteContextKey() {
        if (pageMode === 'collection') {
            return `collection:${collectionId}:${sourceId}`;
        }
        return `single:${viewToken}`;
    }

    function bindingApiBase() {
        if (pageMode === 'collection' && collectionId) {
            return `/api/study/collections/${encodeURIComponent(collectionId)}/obsidian-binding`;
        }
        return `${studyApiBase()}/obsidian-binding`;
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
        window.clearTimeout(showToast.timer);
        els.toast.textContent = message;
        els.toast.classList.add('show');
        showToast.timer = window.setTimeout(() => els.toast.classList.remove('show'), 2400);
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
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || payload.code >= 400) {
            const detail = payload.detail;
            const message = typeof detail === 'string'
                ? detail
                : ((detail && (detail.message || detail.code)) || payload.message || '请求失败');
            const error = new Error(message);
            error.status = response.status;
            error.detail = detail;
            throw error;
        }
        return payload.data;
    }

    function setNoteStatus(message, status) {
        if (!els.noteStatus) return;
        els.noteStatus.textContent = message;
        els.noteStatus.dataset.state = status || '';
    }

    function resetStudyNoteState() {
        window.clearTimeout(state.noteSaveTimer);
        if (state.noteLoadController) state.noteLoadController.abort();
        state.noteLoadController = null;
        state.noteDocument = null;
        state.noteDirty = false;
        state.noteSaving = false;
        state.noteBinding = null;
        state.noteConflict = null;
        els.noteEditor.value = '';
        els.noteEditor.disabled = true;
        els.noteSync.disabled = true;
        setNoteStatus('正在加载', 'saving');
    }

    async function loadStudyNote(force) {
        const context = noteContextKey();
        if (!viewToken || (pageMode === 'collection' && (!collectionId || !sourceId))) return;
        if (!force && state.noteContext === context && state.noteDocument) return;
        if (state.noteLoadController) state.noteLoadController.abort();
        const controller = new AbortController();
        state.noteLoadController = controller;
        state.noteContext = context;
        setNoteStatus('正在加载', 'saving');
        try {
            const result = await apiJSON(`${studyApiBase()}/note-document`, {
                signal: controller.signal,
            });
            if (state.noteContext !== context) return;
            state.noteDocument = result.document;
            state.noteDirty = false;
            state.noteConflict = null;
            els.noteEditor.value = (result.document && result.document.body) || '';
            els.noteEditor.disabled = false;
            els.noteSync.disabled = false;
            if (result.state === 'clean') {
                setNoteStatus('已同步', 'synced');
            } else if (result.state === 'binding_required') {
                setNoteStatus('已保存 · 尚未绑定', 'dirty');
            } else if (result.state === 'skipped_empty') {
                setNoteStatus('已保存 · 空笔记不建文件', 'dirty');
            } else {
                setNoteStatus('已保存 · 尚未同步', 'dirty');
            }
        } catch (error) {
            if (error.name === 'AbortError') return;
            const detail = error.detail || {};
            if (error.status === 409 && (detail.state === 'conflict' || detail.state === 'external_deleted')) {
                state.noteDocument = {
                    body: detail.app_body || '',
                    revision: detail.preconditions && detail.preconditions.expected_revision,
                };
                els.noteEditor.value = state.noteDocument.body;
                els.noteEditor.disabled = false;
                els.noteSync.disabled = false;
                showObsidianConflict(detail);
                return;
            }
            setNoteStatus(error.message || '笔记加载失败', 'error');
        } finally {
            if (state.noteLoadController === controller) state.noteLoadController = null;
        }
    }

    function scheduleStudyNoteSave() {
        if (!state.noteDocument || els.noteEditor.disabled) return;
        state.noteDirty = true;
        setNoteStatus('尚未保存', 'dirty');
        window.clearTimeout(state.noteSaveTimer);
        state.noteSaveTimer = window.setTimeout(saveStudyNote, 700);
    }

    async function saveStudyNote() {
        window.clearTimeout(state.noteSaveTimer);
        if (!state.noteDirty || state.noteSaving || !state.noteDocument) return state.noteDocument;
        const context = noteContextKey();
        const body = els.noteEditor.value;
        const revision = Number(state.noteDocument.revision || 0);
        if (!revision) return state.noteDocument;
        state.noteSaving = true;
        setNoteStatus('正在保存', 'saving');
        try {
            const document = await apiJSON(`${studyApiBase()}/note-document`, {
                method: 'PUT',
                body: JSON.stringify({ body, expected_revision: revision }),
            });
            if (state.noteContext !== context) return document;
            state.noteDocument = document;
            state.noteDirty = els.noteEditor.value !== body;
            if (state.noteDirty) {
                setNoteStatus('有新的修改待保存', 'dirty');
                state.noteSaveTimer = window.setTimeout(saveStudyNote, 700);
            } else {
                setNoteStatus('已保存 · 尚未同步', 'dirty');
            }
            return document;
        } catch (error) {
            const current = error.detail && error.detail.current;
            if (error.status === 409 && current) {
                state.noteDocument = current;
                setNoteStatus('另一页面已修改，当前草稿已暂停保存', 'conflict');
            } else {
                setNoteStatus(error.message || '保存失败', 'error');
            }
            throw error;
        } finally {
            state.noteSaving = false;
        }
    }

    async function loadObsidianBinding() {
        const data = await apiJSON(bindingApiBase());
        state.noteBinding = data.binding || null;
        return data;
    }

    function populateDirectorySelect(select, items, selectedValue) {
        const values = Array.from(new Set([...(items || []), selectedValue].filter(Boolean)));
        select.innerHTML = values.map((value) => (
            `<option value="${escapeHTML(value)}"${value === selectedValue ? ' selected' : ''}>${escapeHTML(value)}</option>`
        )).join('');
        if (!values.length) {
            select.innerHTML = '<option value="">没有可选目录</option>';
        }
    }

    async function openObsidianBindingDialog() {
        if (!els.bindingDialog.open) els.bindingDialog.showModal();
        els.bindingSave.disabled = true;
        els.bindingStatus.textContent = '正在读取 Vault 目录…';
        els.bindingScope.textContent = pageMode === 'collection'
            ? '这是合集目录绑定：保存一次后，同合集其他分集会自动沿用。修改绑定不会移动或删除旧文件。'
            : '这是单篇内容绑定：只影响当前学习内容。修改绑定不会移动或删除旧文件。';
        try {
            const [status, bindingData, transcriptData, noteData] = await Promise.all([
                apiJSON('/api/obsidian/status'),
                loadObsidianBinding(),
                apiJSON('/api/obsidian/directories?root=raw'),
                apiJSON('/api/obsidian/directories?root=vault'),
            ]);
            if (!status.available) throw new Error('Obsidian Vault 当前不可用，请检查本地配置');
            const binding = bindingData.binding || {};
            populateDirectorySelect(
                els.transcriptDirectory,
                transcriptData.items,
                binding.transcript_directory
            );
            populateDirectorySelect(
                els.noteDirectory,
                noteData.items,
                binding.note_directory
            );
            els.bindingStatus.textContent = `${status.display_path || '本地 Vault'} · 请选择两个已存在目录`;
            els.bindingSave.disabled = false;
        } catch (error) {
            els.bindingStatus.textContent = error.message || 'Vault 目录读取失败';
        }
    }

    async function saveObsidianBinding() {
        const transcriptDirectory = els.transcriptDirectory.value;
        const noteDirectory = els.noteDirectory.value;
        if (!transcriptDirectory || !noteDirectory) {
            els.bindingStatus.textContent = '请先选择文字稿和笔记目录';
            return;
        }
        els.bindingSave.disabled = true;
        els.bindingStatus.textContent = '正在保存绑定…';
        try {
            const binding = await apiJSON(bindingApiBase(), {
                method: 'PUT',
                body: JSON.stringify({
                    transcript_directory: transcriptDirectory,
                    note_directory: noteDirectory,
                    expected_revision: state.noteBinding ? state.noteBinding.revision : null,
                }),
            });
            state.noteBinding = binding;
            els.bindingDialog.close();
            setNoteStatus('已保存 · 尚未同步', 'dirty');
            showToast(pageMode === 'collection' ? '合集目录绑定已保存' : '目录绑定已保存');
        } catch (error) {
            els.bindingStatus.textContent = error.message || '目录绑定保存失败';
        } finally {
            els.bindingSave.disabled = false;
        }
    }

    function showObsidianConflict(detail) {
        state.noteConflict = detail;
        const externalDeleted = detail.state === 'external_deleted';
        els.conflictTitle.textContent = externalDeleted ? 'Obsidian 笔记文件已删除' : '笔记存在双边修改';
        els.conflictMessage.textContent = externalDeleted
            ? '请选择用学习页笔记重建文件，或明确接受删除。系统不会自动处理。'
            : '学习页和 Obsidian 都有修改，请明确选择要保留的版本。';
        els.conflictApp.value = detail.app_body || '';
        els.conflictFile.value = externalDeleted ? '（文件已不存在）' : (detail.obsidian_body || '');
        els.conflictDialog.querySelectorAll('[data-choice]').forEach((button) => {
            const externalChoice = ['recreate_from_app', 'accept_external_deletion'].includes(button.dataset.choice);
            button.hidden = externalDeleted ? !externalChoice : externalChoice;
        });
        setNoteStatus('存在冲突', 'conflict');
        if (!els.conflictDialog.open) els.conflictDialog.showModal();
    }

    async function resolveObsidianConflict(choice) {
        const conflict = state.noteConflict;
        if (!conflict || !conflict.preconditions) return;
        const button = els.conflictDialog.querySelector(`[data-choice="${choice}"]`);
        if (button) button.disabled = true;
        try {
            const result = await apiJSON(`${studyApiBase()}/obsidian-conflict/resolve`, {
                method: 'POST',
                body: JSON.stringify({ choice, ...conflict.preconditions }),
            });
            state.noteConflict = null;
            state.noteDocument = result.document;
            state.noteDirty = false;
            els.noteEditor.value = (result.document && result.document.body) || '';
            els.conflictDialog.close();
            setNoteStatus(choice === 'accept_external_deletion' ? '已接受删除' : '已同步', 'synced');
            showToast('冲突已处理');
        } catch (error) {
            const detail = error.detail || {};
            if (error.status === 409 && detail.preconditions) {
                showObsidianConflict(detail);
                showToast('内容又发生了变化，请重新确认');
            } else {
                showToast(error.message || '冲突处理失败');
            }
        } finally {
            if (button) button.disabled = false;
        }
    }

    async function syncStudyNoteToObsidian() {
        if (els.noteSync.disabled) return;
        els.noteSync.disabled = true;
        try {
            if (state.noteDirty) await saveStudyNote();
            if (state.noteDirty) return;
            const bindingData = await loadObsidianBinding();
            if (bindingData.required) {
                await openObsidianBindingDialog();
                return;
            }
            setNoteStatus('正在同步', 'saving');
            const result = await apiJSON(`${studyApiBase()}/obsidian-sync`, { method: 'POST' });
            if (result.overall === 'partial') {
                setNoteStatus('部分同步成功，可重试', 'error');
                showToast('部分文件同步失败，再点一次即可重试');
            } else {
                setNoteStatus('已同步', 'synced');
                showToast('文字稿和笔记已同步到 Obsidian');
            }
        } catch (error) {
            const detail = error.detail || {};
            if (detail.code === 'binding_required') {
                await openObsidianBindingDialog();
            } else if (detail.code === 'transcript_not_ready') {
                setNoteStatus('文字稿未就绪，笔记已保存在学习页', 'dirty');
                showToast('文字稿未就绪，稍后再同步到 Obsidian');
            } else if (detail.state === 'conflict' || detail.state === 'external_deleted') {
                showObsidianConflict(detail);
            } else {
                setNoteStatus(error.message || '同步失败', 'error');
                showToast(error.message || '同步失败');
            }
        } finally {
            els.noteSync.disabled = false;
        }
    }

    function bindStudyNote() {
        els.noteEditor.addEventListener('input', scheduleStudyNoteSave);
        els.noteSync.addEventListener('click', syncStudyNoteToObsidian);
        els.noteBinding.addEventListener('click', openObsidianBindingDialog);
        els.bindingSave.addEventListener('click', saveObsidianBinding);
        els.bindingClose.addEventListener('click', () => els.bindingDialog.close());
        els.bindingCancel.addEventListener('click', () => els.bindingDialog.close());
        els.bindingDialog.addEventListener('click', (event) => {
            if (event.target === els.bindingDialog) els.bindingDialog.close();
        });
        els.conflictClose.addEventListener('click', () => els.conflictDialog.close());
        els.conflictDialog.addEventListener('click', (event) => {
            if (event.target === els.conflictDialog) els.conflictDialog.close();
        });
        els.conflictDialog.querySelectorAll('[data-choice]').forEach((button) => {
            button.addEventListener('click', () => resolveObsidianConflict(button.dataset.choice));
        });
    }

    function formatTime(seconds) {
        if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return '--:--';
        const total = Math.max(0, Math.floor(Number(seconds)));
        const h = Math.floor(total / 3600);
        const m = Math.floor((total % 3600) / 60);
        const s = total % 60;
        if (h > 0) {
            return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
        }
        return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
    }

    function stateLabel(value) {
        return {
            queued: '排队中',
            ready: '可学习',
            source_missing: '仅文稿',
            downloading: '下载中',
            transcribing: '转录中',
            processing: '处理中',
            generating_ai: '生成 AI',
            failed: '失败',
            canceled: '已取消',
        }[value] || value || '未知';
    }

    function modelLabel(value) {
        const model = String(value || 'deepseek-v4-pro');
        if (model === 'deepseek-v4-pro') return 'V4 Pro';
        if (model === 'deepseek-v4-flash') return 'V4 Flash';
        return model.replace(/^deepseek-/, '');
    }

    function isPendingState(value) {
        return ['queued', 'processing', 'downloading', 'transcribing', 'generating_ai'].includes(value);
    }

    function renderSession(session) {
        state.session = session;
        const metadata = session.metadata || {};
        if (metadata.view_token) viewToken = metadata.view_token;
        const playback = session.playback || {};
        const source = session.source || { kind: 'unknown' };
        const transcript = session.transcript || { lines: [] };

        const documentSource = ['document', 'text'].includes(source.kind);
        const sourceLabel = documentSource ? '文档学习' : (source.kind === 'audio' ? '音频学习' : '视频学习');
        
        let displayTitle = metadata.title || sourceLabel;
        if (typeof displayTitle === 'string') {
            displayTitle = displayTitle.replace(/\.(mp3|mp4|m4a|wav|aac|flac|mov|mkv|webm)$/i, '');
        }

        els.studyPageContext.textContent = sourceLabel;
        els.studyWorkbenchTitle.textContent = sourceLabel;
        document.title = `${displayTitle} - 内容解析工作台`;
        els.title.textContent = displayTitle;
        els.videoTitle.textContent = displayTitle;
        els.breadcrumbs.textContent = sourceLabel;
        els.subtitle.textContent = documentSource ? '原文、AI 解读、图解和问答围绕同一份文档组织。' : '视频、文稿、AI 解读和问答围绕同一条时间轴组织。';
        els.state.textContent = stateLabel(session.state);
        els.transcriptCount.textContent = `${transcript.lines.length} 段`;
        els.aiModel.textContent = modelLabel(session.ai && session.ai.chat_model);
        const overviewText = aiOverviewText(session);
        const overviewHtml = renderMarkdown(overviewText);
        els.aiOverview.innerHTML = overviewHtml;
        els.aiReadingContent.innerHTML = overviewHtml;
        const hasOverview = Boolean(session.ai && session.ai.overview);
        els.aiOverviewExpand.disabled = !hasOverview;
        els.aiOverviewMeta.textContent = hasOverview
            ? `${String(session.ai.overview).replace(/\s/g, '').length} 字 · 完整内容`
            : '内容生成中';
        els.exportMarkdown.disabled = isPendingState(session.state) && !transcript.lines.length;

        els.library.hidden = true;
        els.player.hidden = false;

        renderSourceMode(source);
        renderPlayback(playback, source);
        renderCollectionNavigation(session.collection);
        const currentNoteContext = noteContextKey();
        if (state.noteContext !== currentNoteContext) {
            resetStudyNoteState();
            state.noteContext = currentNoteContext;
            loadStudyNote(true);
        }
        renderProgress(session);
        renderTranscript(transcript.lines || [], session);
        renderChat();
        applyEstimatedTranscriptTimes();
        applyRequestedVisualSource();
        if (state.visualTabActive) activateVisualLearning();
        scheduleNextPoll(session);
    }

    function renderSourceMode(source) {
        const documentSource = ['document', 'text'].includes(source.kind);
        document.body.classList.toggle('is-document-source', documentSource);
        document.body.classList.toggle('is-audio-source', source.kind === 'audio');
        els.videoFrame.hidden = documentSource;
        els.playStrip.hidden = documentSource;
        els.sourceCard.hidden = !documentSource;
        if (!documentSource) return;
        els.sourceName.textContent = source.filename || '原始文档';
        els.sourceMeta.textContent = source.kind === 'text'
            ? '文字原稿 · 可在右侧文稿中精确定位'
            : '文档原件 · 可在右侧文稿中精确定位';
        const available = Boolean(source.original_url);
        els.studySourceOpen.hidden = !available;
        if (available) els.studySourceOpen.href = source.original_url;
    }

    function renderPlayback(playback, source) {
        if (['document', 'text'].includes(source.kind)) {
            els.video.removeAttribute('src');
            els.videoFrame.classList.remove('has-video');
            els.videoMeta.textContent = source.kind === 'text' ? '文字原稿' : '文档原件';
            return;
        }
        if (playback.source_available && playback.source_url) {
            if (!playerRuntime.sameMediaResource(
                els.video.getAttribute('src'),
                playback.source_url
            )) {
                els.video.src = playback.source_url;
            }
            if (state.localObjectUrl) {
                URL.revokeObjectURL(state.localObjectUrl);
                state.localObjectUrl = '';
            }
            els.videoFrame.classList.add('has-video');
            els.videoMeta.textContent = source.kind === 'audio' ? '本地音频 · 已保留源文件' : '本地视频 · 已保留源文件';
            return;
        }
        if (state.localObjectUrl) {
            if (els.video.getAttribute('src') !== state.localObjectUrl) els.video.src = state.localObjectUrl;
            els.videoFrame.classList.add('has-video');
            els.videoMeta.textContent = '本地文件 · 正在后台解析';
            return;
        }
        els.video.removeAttribute('src');
        els.videoFrame.classList.remove('has-video');
        els.videoMeta.textContent = playback.unavailable_reason || '源视频不可用';
    }

    function renderCollectionNavigation(collection) {
        if (!collection || !Array.isArray(collection.sources)) {
            els.collectionNav.hidden = true;
            return;
        }
        collectionId = collection.id || collectionId;
        sourceId = collection.current_source_id || sourceId;
        const sources = collection.sources;
        const index = Math.max(0, sources.findIndex((item) => item.id === sourceId));
        els.collectionSelect.innerHTML = sources.map((item, itemIndex) => (
            `<option value="${escapeHTML(item.id)}"${item.id === sourceId ? ' selected' : ''}>${escapeHTML(`${String(itemIndex + 1).padStart(2, '0')}｜${item.title}`)}</option>`
        )).join('');
        els.collectionPrev.disabled = index <= 0;
        els.collectionNext.disabled = index >= sources.length - 1;
        els.collectionPosition.textContent = `第 ${index + 1}/${sources.length} 集`;
        els.collectionNav.hidden = false;
    }

    function renderProgress(session) {
        const progress = session.progress || {};
        if (!els.progressCard) return;

        if (!isPendingState(session.state) && session.state !== 'failed' && session.state !== 'canceled') {
            els.progressCard.hidden = true;
            return;
        }

        els.progressCard.hidden = false;
        els.progressTitle.textContent = progressTitle(session);
        els.progressDetail.textContent = progressDetail(session);
        const percent = Number(progress.percent);
        const width = Number.isFinite(percent) ? Math.max(0, Math.min(100, percent)) : 8;
        els.progressFill.style.width = `${width}%`;
        els.retry.hidden = session.state !== 'failed' && session.state !== 'canceled';
    }

    function progressTitle(session) {
        if (session.state === 'queued') return '任务已创建，等待开始转录';
        if (session.state === 'downloading') return '正在准备视频内容';
        if (session.state === 'transcribing' || session.state === 'processing') return '正在转录本地视频';
        if (session.state === 'generating_ai') return '正在生成 AI 总结';
        if (session.state === 'failed') return '处理失败';
        if (session.state === 'canceled') return '任务已取消';
        return '正在处理学习内容';
    }

    function progressDetail(session) {
        const progress = session.progress || {};
        const parts = [];
        if (progress.stage_label) parts.push(progress.stage_label);
        if (Number.isFinite(Number(progress.percent))) parts.push(`${Math.round(Number(progress.percent))}%`);
        if (progress.message) parts.push(progress.message);
        if (parts.length) return `${parts.join(' · ')}，页面会自动刷新。`;
        if (session.state === 'generating_ai') return '文稿已经生成，正在生成 AI 总结，页面会自动刷新。';
        if (session.state === 'failed') return (session.metadata && session.metadata.message) || '请回到上传页重新提交或检查转录服务。';
        return '后台正在处理，长视频需要一些时间，页面会自动刷新。';
    }

    function aiOverviewText(session) {
        if (session.ai && session.ai.overview) return session.ai.overview;
        if (session.state === 'generating_ai') return '文稿已生成，正在生成 AI 总结。完成后这里会自动刷新显示。';
        if (session.state === 'queued') return '任务已创建，等待后台开始转录。';
        if (session.state === 'transcribing' || session.state === 'processing' || session.state === 'downloading') {
            return '正在转录本地视频。转录完成后会继续生成 AI 总结，页面会自动刷新。';
        }
        if (session.state === 'failed') return (session.metadata && session.metadata.message) || '处理失败，暂时无法生成 AI 总结。';
        if (session.state === 'canceled') return '任务已取消。';
        return 'AI 总结尚未生成。';
    }

    function renderMarkdown(markdown) {
        const lines = String(markdown || '').replace(/\r\n/g, '\n').split('\n');
        const html = [];
        let listItems = [];
        let listTag = 'ul';

        function flushList() {
            if (!listItems.length) return;
            html.push(`<${listTag}>${listItems.join('')}</${listTag}>`);
            listItems = [];
        }

        lines.forEach((rawLine) => {
            const line = rawLine.trim();
            if (!line) {
                flushList();
                return;
            }

            if (/^[-*_]{3,}$/.test(line)) {
                flushList();
                return;
            }

            const heading = line.match(/^(#{1,5})\s+(.+)$/);
            if (heading) {
                flushList();
                const level = Math.min(5, Math.max(3, heading[1].length + 2));
                html.push(`<h${level}>${inlineMarkdown(heading[2])}</h${level}>`);
                return;
            }

            const unordered = line.match(/^[-*]\s+(.+)$/);
            const ordered = line.match(/^\d+[.、]\s+(.+)$/);
            if (unordered || ordered) {
                const nextTag = ordered ? 'ol' : 'ul';
                if (listItems.length && listTag !== nextTag) flushList();
                listTag = nextTag;
                listItems.push(`<li>${inlineMarkdown((unordered || ordered)[1])}</li>`);
                return;
            }

            const quote = line.match(/^>\s?(.+)$/);
            if (quote) {
                flushList();
                html.push(`<blockquote>${inlineMarkdown(quote[1])}</blockquote>`);
                return;
            }

            flushList();
            html.push(`<p>${inlineMarkdown(line)}</p>`);
        });

        flushList();
        return html.join('') || '<p>暂无内容。</p>';
    }

    function inlineMarkdown(value) {
        return escapeHTML(value)
            .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
            .replace(/`([^`]+)`/g, '<code>$1</code>');
    }

    function renderTranscript(lines, session) {
        if (!lines.length) {
            if (isPendingState(session.state)) {
                els.transcriptList.innerHTML = '<div class="empty-panel"><strong>文稿生成中</strong><span>正在转录本地视频，完成后会自动刷新显示文稿。</span></div>';
            } else if (session.state === 'failed') {
                els.transcriptList.innerHTML = '<div class="empty-panel"><strong>文稿生成失败</strong><span>请检查转录服务或重新上传视频。</span></div>';
            } else {
                els.transcriptList.innerHTML = '<div class="empty-panel"><strong>暂无文稿</strong><span>转录完成后会显示在这里。</span></div>';
            }
            return;
        }
        const rows = lines.map((line) => {
            const disabled = line.seekable ? '' : ' disabled';
            const time = line.seekable ? formatTime(line.start_seconds) : '--:--';
            const title = line.estimated ? `${time} · 估算时间` : time;
            const current = line.id === state.currentLineId ? ' is-current' : '';
            return `<div class="transcript-row${current}" data-line-id="${escapeHTML(line.id)}">
                <time>${escapeHTML(time)}</time>
                <button class="transcript-segment" type="button" data-line-id="${escapeHTML(line.id)}" data-time="${line.start_seconds ?? ''}" title="${escapeHTML(title)}"${disabled}>${escapeHTML(line.text)}</button>
            </div>`;
        }).join('');

        els.transcriptList.innerHTML = `<article class="manuscript-reader">${rows}</article>
            <button class="back-playhead" type="button">回到当前字幕</button>`;
        syncTranscriptFollowButton();
    }

    function visualSourceReady(session) {
        const overview = ((session.ai || {}).overview || '').trim();
        return Boolean(overview);
    }

    function setVisualStatus(message, retry) {
        if (!els.visualStatus) return;
        els.visualStatus.hidden = !message;
        els.visualStatusText.textContent = message || '';
        els.visualRetry.hidden = !retry;
    }

    function setFullNoteStatus(message, retry) {
        els.visualFullNoteStatus.hidden = !message;
        els.visualFullNoteStatusText.textContent = message || '';
        els.visualFullNoteRetry.hidden = !retry;
    }

    function renderVisualPlaceholder(container, title, message) {
        if (!container) return;
        const empty = document.createElement('div');
        empty.className = 'empty-panel';
        const heading = document.createElement('strong');
        const copy = document.createElement('span');
        heading.textContent = title;
        copy.textContent = message;
        empty.append(heading, copy);
        container.replaceChildren(empty);
    }

    function renderVisualDocument(documentType, visualDocument) {
        if (!visualDocument || !window.VisualLearning) return;
        state.visualDocuments[documentType] = visualDocument;
        const options = { onSourceRef: handleVisualSourceRef };
        renderTwoLayerVisual();
        if (documentType === 'overview') els.visualExpand.disabled = false;
        if (state.activeVisualType === documentType && els.visualDialog.open) {
            window.VisualLearning.render(
                els.visualModalContent,
                visualDocument,
                { ...options, showInlineSourceRefs: true }
            );
        }
        applyVisualTheme();
    }

    function renderTwoLayerVisual() {
        if (!window.VisualLearning) return;
        const fullNoteState = state.visualStates.full_note || {};
        const overviewState = state.visualStates.overview || {};
        const sectionCandidates = [
            fullNoteState.interpretation_sections,
            overviewState.interpretation_sections,
        ];
        const sections = sectionCandidates.find((items) => Array.isArray(items) && items.length)
            || sectionCandidates.find(Array.isArray)
            || [];
        const availability = [
            fullNoteState.interpretation_available,
            overviewState.interpretation_available,
        ].filter((value) => typeof value === 'boolean');
        const interpretationAvailable = availability.includes(true)
            ? true
            : (availability.includes(false) ? false : Boolean(sections.length));
        if (!state.visualDocuments.overview
            && !state.visualDocuments.full_note
            && interpretationAvailable !== false) return;
        window.VisualLearning.renderTwoLayer(els.visualOverview, {
            overview: state.visualDocuments.overview,
            fullNote: state.visualDocuments.full_note,
            sections: sections,
            interpretationAvailable: interpretationAvailable,
        }, {
            onSourceRef: handleVisualSourceRef,
            onSectionEvidence: handleVisualSectionEvidence,
        });
    }

    function applyVisualTheme() {
        const theme = els.visualTheme.value;
        window.VisualLearning.setTheme(els.visualOverview, theme);
        window.VisualLearning.setTheme(els.visualModalContent, theme);
    }

    function handleVisualState(documentType, payload) {
        state.visualStates[documentType] = payload;
        const documentRecord = payload && payload.document;
        const attempt = payload && payload.latest_attempt;
        if (documentRecord && documentRecord.status === 'success' && documentRecord.document_json) {
            renderVisualDocument(documentType, documentRecord.document_json);
        } else {
            renderTwoLayerVisual();
        }

        const pending = attempt && ['pending', 'generating'].includes(attempt.status);
        const failed = attempt && attempt.status === 'failed';
        if (documentType === 'overview') {
            if (payload && payload.stale) {
                setVisualStatus('原文已经更新，当前展示的是上一版视觉速览。', true);
            } else if (failed) {
                setVisualStatus(documentRecord && documentRecord.status === 'success'
                    ? '新版本生成失败，已保留上一版。'
                    : '视觉速览生成失败。', true);
            } else if (pending) {
                setVisualStatus('正在生成视觉速览…', false);
            } else {
                setVisualStatus('', false);
            }
        } else if (payload && payload.stale) {
            setFullNoteStatus('原解读已经更新，当前展示的是上一版完整笔记。', true);
        } else if (failed) {
            setFullNoteStatus(documentRecord && documentRecord.status === 'success'
                ? '完整笔记新版本生成失败，已保留上一版。'
                : '完整笔记生成失败。', true);
        } else if (pending) {
            setFullNoteStatus('正在生成完整笔记…', false);
        } else {
            setFullNoteStatus('', false);
        }
        if (pending) scheduleVisualPoll(documentType);
        updateVisualDialogState(documentType, payload);
        return Boolean(documentRecord && documentRecord.status === 'success' && documentRecord.document_json);
    }

    function updateVisualDialogState(documentType, payload) {
        if (state.activeVisualType !== documentType) return;
        const attempt = payload && payload.latest_attempt;
        const pending = attempt && ['pending', 'generating'].includes(attempt.status);
        const failed = attempt && attempt.status === 'failed';
        const stale = Boolean(payload && payload.stale);
        if (pending) {
            els.visualModalStatus.textContent = '正在生成新版本…';
            els.visualRegenerate.hidden = true;
        } else if (stale) {
            els.visualModalStatus.textContent = '原内容已更新，当前是上一版。';
            els.visualRegenerate.hidden = false;
        } else if (failed) {
            els.visualModalStatus.textContent = '新版本生成失败，已保留上一版。';
            els.visualRegenerate.hidden = false;
        } else {
            els.visualModalStatus.textContent = '';
            els.visualRegenerate.hidden = true;
        }
    }

    async function loadVisualState(documentType, generateWhenMissing) {
        if (state.visualLoading.has(documentType)) return;
        state.visualLoading.add(documentType);
        try {
            const payload = await apiJSON(
                `/api/visual-learning/study/${encodeURIComponent(viewToken)}?document_type=${encodeURIComponent(documentType)}`
            );
            const hasDocument = handleVisualState(documentType, payload);
            if (!hasDocument && !payload.latest_attempt && generateWhenMissing) {
                await requestVisualGeneration(documentType);
            } else if (!hasDocument && documentType === 'full_note' && !payload.latest_attempt) {
                renderVisualPlaceholder(els.visualModalContent, '尚未生成完整笔记', '点击完整笔记后开始生成。');
            }
        } catch (error) {
            if (documentType === 'overview') {
                setVisualStatus(error.status === 404 || error.status === 405
                    ? '视觉学习接口尚未加载，请重启服务。'
                    : (error.message || '视觉速览加载失败。'), true);
            } else {
                setFullNoteStatus(error.message || '完整笔记加载失败。', true);
                renderVisualPlaceholder(els.visualModalContent, '完整笔记加载失败', error.message || '请稍后重试。');
            }
        } finally {
            state.visualLoading.delete(documentType);
        }
    }

    async function requestVisualGeneration(documentType, options) {
        const force = Boolean(options && options.force);
        if (state.visualLoading.has(`generate:${documentType}`)) return;
        state.visualLoading.add(`generate:${documentType}`);
        if (documentType === 'full_note') {
            setFullNoteStatus('正在生成完整笔记…', false);
            renderVisualPlaceholder(els.visualModalContent, '正在生成完整笔记', '内容较长时需要等待一会儿。');
        }
        try {
            const payload = await apiJSON(
                `/api/visual-learning/study/${encodeURIComponent(viewToken)}/generate`,
                {
                    method: 'POST',
                    body: JSON.stringify({
                        document_type: documentType,
                        style: els.visualTheme.value,
                        diagram_type: 'auto',
                        force,
                    }),
                }
            );
            handleVisualState(documentType, payload);
        } catch (error) {
            if (documentType === 'overview') {
                setVisualStatus(error.message || '视觉速览生成失败。', true);
            } else {
                setFullNoteStatus(error.message || '完整笔记生成失败。', true);
                renderVisualPlaceholder(els.visualModalContent, '完整笔记生成失败', error.message || '请稍后重试。');
            }
        } finally {
            state.visualLoading.delete(`generate:${documentType}`);
        }
    }

    function scheduleVisualPoll(documentType) {
        window.clearTimeout(state.visualPollTimers[documentType]);
        state.visualPollTimers[documentType] = window.setTimeout(
            () => loadVisualState(documentType, false),
            2200
        );
    }

    function ensureVisualOverview(session) {
        if (!visualSourceReady(session)) {
            setVisualStatus('原文就绪后会自动生成视觉速览。', false);
            return;
        }
        loadVisualState('overview', true);
    }

    function activateVisualLearning() {
        if (state.visualActivated) return;
        if (!visualSourceReady(state.session || {})) {
            state.visualActivated = false;
            setVisualStatus('原文就绪后可重新打开图解。', false);
            return;
        }
        state.visualActivated = true;
        setFullNoteStatus('正在加载完整笔记…', false);
        loadVisualState('overview', true);
        loadVisualState('full_note', true);
    }

    function openVisualDialog(documentType) {
        state.activeVisualType = documentType;
        els.visualModalTitle.textContent = documentType === 'full_note' ? '完整图文笔记' : '视觉速览';
        const document = state.visualDocuments[documentType];
        if (document) {
            window.VisualLearning.render(
                els.visualModalContent,
                document,
                { onSourceRef: handleVisualSourceRef, showInlineSourceRefs: true }
            );
            applyVisualTheme();
        } else {
            renderVisualPlaceholder(els.visualModalContent, '正在准备内容', '请稍候。');
        }
        if (!els.visualDialog.open) els.visualDialog.showModal();
        updateVisualDialogState(documentType, state.visualStates[documentType] || {});
    }

    function handleVisualSourceRef(refId, sourceRef) {
        if (els.visualDialog.open) els.visualDialog.close();
        if (refId.endsWith(':summary') || refId.includes(':summary:section:')) {
            activateTab('ai');
            els.aiOverview.scrollIntoView({ block: 'start', behavior: 'smooth' });
            return;
        }
        activateTab('transcript');
        const lines = ((state.session || {}).transcript || {}).lines || [];
        let line = sourceRef.line_id
            ? lines.find((item) => item.id === sourceRef.line_id)
            : null;
        if (!line && Number.isInteger(sourceRef.paragraph_index)) {
            line = lines[sourceRef.paragraph_index];
        }
        if (Number.isFinite(Number(sourceRef.start_seconds)) && els.video.src) {
            seekTo(Number(sourceRef.start_seconds));
        }
        if (!line) return;
        state.currentLineId = line.id;
        const target = Array.from(document.querySelectorAll('.transcript-row'))
            .find((row) => row.dataset.lineId === line.id);
        if (target) {
            document.querySelectorAll('.transcript-row').forEach((row) => {
                row.classList.toggle('is-current', row === target);
            });
            scrollTranscriptTarget(target);
        }
    }

    function handleVisualSectionEvidence(payload) {
        const references = (payload && payload.originalReferences) || [];
        const fallback = (payload && payload.summaryReferences) || [];
        const selected = references[0] || fallback[0];
        if (selected) handleVisualSourceRef(selected.refId, selected.sourceRef);
    }

    function applyRequestedVisualSource() {
        if (state.requestedVisualSourceApplied) return;
        const params = new URLSearchParams(window.location.search);
        const sourceKind = params.get('visual_source');
        const lineId = params.get('visual_line_id');
        const paragraphValue = params.get('visual_paragraph');
        const startValue = params.get('visual_start');
        if (!sourceKind && !lineId && paragraphValue === null && startValue === null) return;
        state.requestedVisualSourceApplied = true;
        handleVisualSourceRef(
            sourceKind === 'summary' ? `study:${viewToken}:summary` : 'requested-source',
            {
                line_id: lineId || null,
                paragraph_index: paragraphValue === null ? null : Number(paragraphValue),
                start_seconds: startValue === null ? null : Number(startValue),
            }
        );
    }

    function renderChat() {
        if (!state.chatMessages.length) {
            els.chatList.innerHTML = '<div class="chat-empty"><strong>问任何看不懂的地方</strong><span>AI 会先读视频全文和总结，再结合专业知识回答。</span></div>';
            return;
        }
        els.chatList.innerHTML = state.chatMessages.map((message) => {
            const meta = message.role === 'assistant'
                ? escapeHTML(message.pending ? '正在思考' : modelLabel(message.model))
                : '你';
            const content = message.pending
                ? renderThinking(message.thinkingStep || 0)
                : message.role === 'assistant'
                ? `<div class="markdown-content chat-answer">${renderMarkdown(message.content || '')}</div>`
                : `<p>${escapeHTML(message.content || '')}</p>`;
            const stateClass = message.pending ? ' is-pending' : (message.error ? ' is-error' : '');
            return `<article class="chat-message is-${escapeHTML(message.role)}${stateClass}">
                <strong>${meta}</strong>
                ${content}
            </article>`;
        }).join('');
        els.chatList.scrollTop = els.chatList.scrollHeight;
    }

    function renderThinking(stepIndex) {
        const steps = ['阅读视频全文', '定位相关上下文', '组织回答'];
        const items = steps.map((step, index) => {
            const stateClass = index < stepIndex ? ' is-done' : (index === stepIndex ? ' is-active' : '');
            return `<li class="${stateClass}">${escapeHTML(step)}</li>`;
        }).join('');
        return `<div class="chat-thinking-box">
            <div class="chat-thinking" aria-label="AI 正在思考"><span></span><span></span><span></span></div>
            <ol class="chat-thinking-steps">${items}</ol>
        </div>`;
    }

    function escapeHTML(value) {
        return String(value || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function bindTabs() {
        document.querySelectorAll('.right-tabs [data-tab]').forEach((button) => {
            button.addEventListener('click', () => {
                const tab = button.dataset.tab;
                document.querySelectorAll('.right-tabs [data-tab]').forEach((item) => {
                    item.classList.toggle('is-active', item === button);
                });
                document.querySelectorAll('.study-panel-view').forEach((panel) => {
                    panel.classList.toggle('is-active', panel.id === `tab-${tab}`);
                });
                state.visualTabActive = tab === 'visual';
                if (tab === 'visual') activateVisualLearning();
                if (tab === 'notes' && !state.noteDocument) loadStudyNote(true);
            });
        });
    }

    function bindTranscript() {
        els.transcriptFollow.addEventListener('click', () => {
            state.transcriptFollow = !state.transcriptFollow;
            syncTranscriptFollowButton();
            if (state.transcriptFollow) scrollActiveTranscriptIntoView();
        });
        els.transcriptList.addEventListener('click', (event) => {
            const scrollButton = event.target.closest('.back-playhead');
            if (scrollButton) {
                state.transcriptFollow = true;
                syncTranscriptFollowButton();
                scrollActiveTranscriptIntoView();
                return;
            }
            const button = event.target.closest('.transcript-segment');
            if (!button || button.disabled) return;
            state.transcriptFollow = true;
            syncTranscriptFollowButton();
            const seconds = Number(button.dataset.time);
            seekTo(seconds);
        });
    }

    function bindPanelSeek() {
        document.querySelector('.panel').addEventListener('click', (event) => {
            const button = event.target.closest('.panel-seek');
            if (!button) return;
            seekTo(Number(button.dataset.time));
        });
    }

    function bindVideo() {
        els.playToggle.addEventListener('click', async () => {
            if (!els.video.src) return;
            try {
                await playerRuntime.togglePlayback(els.video);
            } catch (error) {
                showToast('音视频暂时无法播放，请检查源文件后重试');
            }
        });
        els.video.addEventListener('play', () => setPlaybackButtonState(true));
        els.video.addEventListener('pause', () => setPlaybackButtonState(false));
        els.video.addEventListener('timeupdate', updateVideoProgress);
        els.video.addEventListener('loadedmetadata', () => {
            playerRuntime.setPlaybackRate(els.video, state.playbackRate);
            updateVideoProgress();
            applyEstimatedTranscriptTimes();
            restorePlaybackProgress();
        });
        els.playbackRate.addEventListener('change', () => {
            state.playbackRate = playerRuntime.setPlaybackRate(els.video, els.playbackRate.value);
            localStorage.setItem(PLAYBACK_RATE_KEY, String(state.playbackRate));
            els.playbackRate.value = String(state.playbackRate);
        });
        els.progress.addEventListener('input', () => {
            const duration = Number(els.video.duration || 0);
            if (!duration) return;
            state.isSeeking = true;
            const progress = Math.max(0, Math.min(100, Number(els.progress.value || 0)));
            const seconds = playerRuntime.progressSeconds(progress, duration);
            els.progress.style.setProperty('--value', `${progress}%`);
            els.videoTime.textContent = `${formatTime(seconds)} / ${formatTime(duration)}`;
            els.progress.setAttribute('aria-valuetext', `${formatTime(seconds)} / ${formatTime(duration)}`);
            highlightTranscript(seconds);
        });
        els.progress.addEventListener('change', async () => {
            const duration = Number(els.video.duration || 0);
            if (!duration) return;
            try {
                await playerRuntime.seekFromProgress(els.video, els.progress.value);
            } catch (error) {
                showToast('无法从所选位置播放，请检查音视频文件后重试');
            } finally {
                state.isSeeking = false;
                updateVideoProgress();
            }
        });
        els.progress.addEventListener('pointercancel', cancelProgressPreview);
        els.video.addEventListener('pause', savePlaybackProgress);
        window.addEventListener('beforeunload', savePlaybackProgress);
        const storedRate = Number(localStorage.getItem(PLAYBACK_RATE_KEY) || 1);
        state.playbackRate = playerRuntime.setPlaybackRate(els.video, storedRate);
        els.playbackRate.value = String(state.playbackRate);
    }

    function cancelProgressPreview() {
        state.isSeeking = false;
        updateVideoProgress();
    }

    function setPlaybackButtonState(isPlaying) {
        els.playToggle.textContent = isPlaying ? 'Ⅱ' : '▶';
        els.playToggle.setAttribute('aria-label', isPlaying ? '暂停' : '播放');
        els.playToggle.title = isPlaying ? '暂停' : '播放';
    }

    function seekTo(seconds) {
        if (!Number.isFinite(seconds) || !els.video.src) return;
        els.video.currentTime = Math.max(0, seconds);
        if (els.video.paused) {
            els.video.play().catch(() => {});
        }
    }

    function updateVideoProgress() {
        if (state.isSeeking) return;
        const duration = els.video.duration || 0;
        const current = els.video.currentTime || 0;
        const value = duration ? `${Math.min(100, (current / duration) * 100)}%` : '0%';
        els.progress.style.setProperty('--value', value);
        els.progress.value = duration ? String(Math.min(100, (current / duration) * 100)) : '0';
        els.videoTime.textContent = `${formatTime(current)} / ${formatTime(duration)}`;
        els.progress.setAttribute('aria-valuetext', `${formatTime(current)} / ${formatTime(duration)}`);
        highlightTranscript(current);
        if (Date.now() - state.progressSavedAt > 5000) savePlaybackProgress();
    }

    function highlightTranscript(currentSeconds) {
        const lines = (state.session && state.session.transcript && state.session.transcript.lines) || [];
        const active = playerRuntime.activeLineAt(lines, currentSeconds);
        if (!active || active.id === state.currentLineId) return;
        state.currentLineId = active.id;
        document.querySelectorAll('.transcript-row').forEach((row) => {
            row.classList.toggle('is-current', row.dataset.lineId === active.id);
        });
        els.currentCaptionTime.textContent = formatTime(active.start_seconds);
        els.currentCaptionText.textContent = active.text || '';
        if (state.transcriptFollow) scrollActiveTranscriptIntoView();
    }

    function progressKey() {
        if (pageMode === 'collection') return `vta_study_progress:${collectionId}:${sourceId}`;
        return `vta_study_progress:${viewToken || 'local'}`;
    }

    function savePlaybackProgress() {
        if (!els.video || !Number.isFinite(Number(els.video.currentTime))) return;
        state.progressSavedAt = Date.now();
        localStorage.setItem(progressKey(), JSON.stringify({
            time: Number(els.video.currentTime || 0),
            duration: Number(els.video.duration || 0),
            updated_at: new Date().toISOString(),
        }));
    }

    function restorePlaybackProgress() {
        try {
            const saved = JSON.parse(localStorage.getItem(progressKey()) || '{}');
            const seconds = Number(saved.time || 0);
            if (seconds > 0 && seconds < Number(els.video.duration || Infinity) - 2) {
                els.video.currentTime = seconds;
            }
        } catch (error) {
            // Ignore malformed browser-local progress.
        }
    }

    function scrollActiveTranscriptIntoView() {
        const current = document.querySelector('.transcript-row.is-current');
        if (current) {
            scrollTranscriptTarget(current);
            return;
        }
        const line = getCurrentTranscriptLine();
        if (!line) return;
        const target = Array.from(document.querySelectorAll('.transcript-row'))
            .find((row) => row.dataset.lineId === line.id);
        if (target) scrollTranscriptTarget(target);
    }

    function scrollTranscriptTarget(target) {
        const viewport = document.getElementById('tab-transcript');
        if (!viewport || !target) return;
        const viewportRect = viewport.getBoundingClientRect();
        const targetRect = target.getBoundingClientRect();
        const offset = targetRect.top - viewportRect.top - ((viewport.clientHeight - targetRect.height) / 2);
        viewport.scrollTo({ top: viewport.scrollTop + offset, behavior: 'smooth' });
    }

    function syncTranscriptFollowButton() {
        els.transcriptFollow.setAttribute('aria-pressed', state.transcriptFollow ? 'true' : 'false');
        els.transcriptFollow.textContent = state.transcriptFollow ? '● 跟随中' : '跟随播放';
        els.transcriptFollow.title = state.transcriptFollow ? '点击暂停自动跟随' : '点击恢复自动跟随';
    }

    function getCurrentTranscriptLine() {
        const lines = (state.session && state.session.transcript && state.session.transcript.lines) || [];
        if (!lines.length) return null;
        const currentLine = lines.find((line) => line.id === state.currentLineId);
        if (currentLine) return currentLine;

        const currentSeconds = Number(els.video.currentTime || 0);
        return playerRuntime.activeLineAt(lines, currentSeconds) || lines[0];
    }

    function applyEstimatedTranscriptTimes() {
        const session = state.session;
        const lines = (session && session.transcript && session.transcript.lines) || [];
        if (!lines.length || lines.some((line) => line.seekable)) return;

        const duration = Number(els.video.duration || 0);
        if (!Number.isFinite(duration) || duration <= 0) return;

        const token = `${session.metadata && session.metadata.view_token}:${Math.round(duration)}:${lines.length}`;
        if (state.estimatedToken === token) return;

        session.transcript.lines = playerRuntime.estimateTimeline(lines, duration);
        state.estimatedToken = token;
        renderTranscript(session.transcript.lines, session);
    }

    function bindChat() {
        els.askAiEntry.addEventListener('click', () => {
            activateTab('chat');
            els.chatQuestion.focus();
        });
        els.sendChat.addEventListener('click', sendChat);
        els.chatQuestion.addEventListener('input', autosizeChatInput);
        els.chatQuestion.addEventListener('keydown', (event) => {
            if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
                event.preventDefault();
                sendChat();
            }
        });
    }

    function autosizeChatInput() {
        els.chatQuestion.style.height = 'auto';
        const nextHeight = Math.min(150, Math.max(46, els.chatQuestion.scrollHeight));
        els.chatQuestion.style.height = `${nextHeight}px`;
    }

    function bindActions() {
        els.copyCurrentLine.addEventListener('click', copyCurrentLine);
        els.exportMarkdown.addEventListener('click', exportMarkdown);
        els.retry.addEventListener('click', retryStudy);
        els.aiOverviewExpand.addEventListener('click', () => {
            if (!els.aiOverviewExpand.disabled && !els.aiReadingDialog.open) {
                els.aiReadingDialog.showModal();
            }
        });
        els.aiReadingClose.addEventListener('click', () => els.aiReadingDialog.close());
        els.aiReadingDialog.addEventListener('click', (event) => {
            if (event.target === els.aiReadingDialog) els.aiReadingDialog.close();
        });
    }

    async function retryStudy() {
        if (els.retry.disabled) return;
        els.retry.disabled = true;
        try {
            if (pageMode === 'collection') {
                await apiJSON(
                    `/api/collections/${encodeURIComponent(collectionId)}/sources/${encodeURIComponent(sourceId)}/retry`,
                    { method: 'POST' }
                );
            } else {
                const result = await apiJSON(`${studyApiBase()}/retry`, { method: 'POST' });
                viewToken = result.view_token;
                history.replaceState({}, '', `/study/${encodeURIComponent(viewToken)}`);
            }
            showToast('已重新提交解析');
            await loadSession();
        } catch (error) {
            showToast(error.message || '重新解析失败');
        } finally {
            els.retry.disabled = false;
        }
    }

    function bindVisualLearning() {
        els.visualTheme.addEventListener('change', applyVisualTheme);
        els.visualExpand.addEventListener('click', () => openVisualDialog('overview'));
        els.visualFullNote.addEventListener('click', async () => {
            openVisualDialog('full_note');
            await loadVisualState('full_note', false);
            const payload = state.visualStates.full_note || {};
            const attempt = payload.latest_attempt;
            if (!state.visualDocuments.full_note && (!attempt || attempt.status === 'failed')) {
                await requestVisualGeneration('full_note', { force: Boolean(attempt) });
            }
        });
        els.visualRetry.addEventListener('click', () => {
            requestVisualGeneration('overview', { force: true });
        });
        els.visualFullNoteRetry.addEventListener('click', () => {
            requestVisualGeneration('full_note', { force: true });
        });
        els.visualRegenerate.addEventListener('click', () => {
            requestVisualGeneration(state.activeVisualType, { force: true });
        });
        els.visualModalClose.addEventListener('click', () => els.visualDialog.close());
        els.visualDialog.addEventListener('click', (event) => {
            if (event.target === els.visualDialog) els.visualDialog.close();
        });
        els.visualExportSvg.addEventListener('click', () => {
            const metadata = (state.session && state.session.metadata) || {};
            try {
                window.VisualLearning.exportSvg(
                    window.VisualLearning.activeDiagram(els.visualOverview),
                    `${safeFilename(metadata.title || 'visual-learning')}.svg`
                );
            } catch (error) {
                showToast(error.message || '导出失败');
            }
        });
        els.visualPrint.addEventListener('click', () => window.print());
    }

    function activateTab(tab) {
        const button = document.querySelector(`.right-tabs [data-tab="${tab}"]`);
        if (button) button.click();
    }

    async function sendChat() {
        if (els.sendChat.disabled) return;
        const question = els.chatQuestion.value.trim();
        if (!question) {
            showToast('请先输入问题');
            return;
        }
        const history = state.chatMessages
            .filter((message) => message.role === 'user' || message.role === 'assistant')
            .slice(-8)
            .map((message) => ({ role: message.role, content: message.content }));
        const userMessage = {
            role: 'user',
            content: question,
        };
        const pendingId = `pending-${Date.now()}`;
        state.chatMessages.push(userMessage);
        state.chatMessages.push({
            id: pendingId,
            role: 'assistant',
            pending: true,
            content: '',
            model: 'deepseek-v4-pro',
            thinkingStep: 0,
        });
        els.chatQuestion.value = '';
        autosizeChatInput();
        renderChat();
        startChatThinking(pendingId);
        els.sendChat.disabled = true;
        try {
            const result = await apiJSON(`${studyApiBase()}/ai-chat`, {
                method: 'POST',
                body: JSON.stringify({
                    question,
                    history,
                }),
            });
            state.chatMessages = state.chatMessages.filter((message) => message.id !== pendingId);
            state.chatMessages.push({
                role: 'assistant',
                content: result.answer || '暂无回答。',
                model: result.model || 'deepseek-v4-pro',
            });
            renderChat();
        } catch (error) {
            state.chatMessages = state.chatMessages.filter((message) => message.id !== pendingId);
            const message = chatErrorMessage(error);
            state.chatMessages.push({
                role: 'assistant',
                content: message,
                model: 'deepseek-v4-pro',
                error: true,
            });
            renderChat();
            showToast(message);
        } finally {
            stopChatThinking();
            els.sendChat.disabled = false;
        }
    }

    function startChatThinking(pendingId) {
        stopChatThinking();
        state.chatThinkingTimer = window.setInterval(() => {
            const pending = state.chatMessages.find((message) => message.id === pendingId);
            if (!pending) {
                stopChatThinking();
                return;
            }
            pending.thinkingStep = Math.min(2, Number(pending.thinkingStep || 0) + 1);
            renderChat();
        }, 1800);
    }

    function stopChatThinking() {
        if (!state.chatThinkingTimer) return;
        window.clearInterval(state.chatThinkingTimer);
        state.chatThinkingTimer = null;
    }

    function chatErrorMessage(error) {
        if (error && (error.status === 404 || error.status === 405)) {
            return 'AI 接口还没有被当前运行中的服务加载。请重启服务后再试。';
        }
        if (error && error.status === 401) {
            return 'API 令牌不可用或已过期，请回到工作台重新设置令牌。';
        }
        return (error && error.message) || 'AI 回答生成失败，请稍后重试。';
    }

    async function copyCurrentLine() {
        const line = getCurrentTranscriptLine();
        if (!line) {
            showToast('暂无可复制文稿');
            return;
        }
        const text = line.seekable ? `[${formatTime(line.start_seconds)}] ${line.text}` : line.text;
        try {
            await navigator.clipboard.writeText(text);
            showToast('已复制当前段');
        } catch (error) {
            showToast('复制失败，请手动选择文稿');
        }
    }

    async function exportMarkdown() {
        const token = getToken();
        if (!token) {
            showToast('请先在工作台设置 API 令牌');
            return;
        }
        els.exportMarkdown.disabled = true;
        try {
            const response = await fetch(`${studyApiBase()}/export/markdown`, {
                headers: { Authorization: `Bearer ${token}` },
            });
            if (!response.ok) {
                const payload = await response.json().catch(() => ({}));
                throw new Error(payload.detail || payload.message || '导出失败');
            }
            const blob = await response.blob();
            const url = URL.createObjectURL(blob);
            const link = document.createElement('a');
            const metadata = (state.session && state.session.metadata) || {};
            link.href = url;
            link.download = `${safeFilename(metadata.title || 'study-notes')}.md`;
            document.body.appendChild(link);
            link.click();
            link.remove();
            URL.revokeObjectURL(url);
            showToast('已开始下载');
        } catch (error) {
            showToast(error.message || '导出失败');
        } finally {
            els.exportMarkdown.disabled = false;
        }
    }

    function safeFilename(value) {
        return String(value || 'study-notes').replace(/[\\/:*?"<>|]+/g, '_').slice(0, 80) || 'study-notes';
    }

    function setLibraryKind(kind) {
        state.libraryKind = kind === 'collection' ? 'collection' : 'single';
        document.querySelectorAll('[data-library-kind]').forEach((button) => {
            const active = button.dataset.libraryKind === state.libraryKind;
            button.classList.toggle('is-active', active);
            button.setAttribute('aria-selected', active ? 'true' : 'false');
        });
        els.singleImport.hidden = state.libraryKind !== 'single';
        els.collectionImport.hidden = state.libraryKind !== 'collection';
        els.libraryListTitle.textContent = state.libraryKind === 'collection' ? '我的合集' : '最近学习';
        loadLibrary();
    }

    async function loadLibrary() {
        window.clearTimeout(state.libraryTimer);
        els.libraryState.hidden = false;
        els.libraryState.textContent = '正在读取真实内容…';
        els.libraryList.replaceChildren();
        try {
            const query = (els.librarySearch.value || '').trim();
            const data = await apiJSON(
                `/api/study/library?kind=${encodeURIComponent(state.libraryKind)}&q=${encodeURIComponent(query)}&limit=50`
            );
            renderLibrary(data.items || [], Number(data.total || 0));
        } catch (error) {
            els.libraryCount.textContent = '';
            els.libraryState.hidden = false;
            els.libraryState.innerHTML = `${escapeHTML(error.message || '内容读取失败')}。<a href="/settings">前往设置</a>`;
        }
    }

    function renderLibrary(items, total) {
        els.libraryCount.textContent = total ? `共 ${total} 项` : '';
        if (!items.length) {
            els.libraryState.hidden = false;
            els.libraryState.textContent = state.libraryKind === 'collection'
                ? '还没有可播放的合集。你可以直接选择一个文件夹或多个音视频。'
                : '还没有保留源文件的已解析内容。你可以直接选择本地音视频开始。';
            return;
        }
        els.libraryState.hidden = true;
        els.libraryList.innerHTML = items.map((item) => {
            const isCollection = state.libraryKind === 'collection';
            const meta = isCollection
                ? `${item.source_count || 0} 集 · ${item.ready_count || 0} 集已解析${item.creator_name ? ` · ${item.creator_name}` : ''}`
                : `${item.source_kind === 'audio' ? '音频' : '视频'} · ${stateLabel(item.state)}${item.author ? ` · ${item.author}` : ''}`;
            return `<a class="study-library-card" href="${escapeHTML(item.study_url || '#')}">
                <span class="study-library-card-icon" aria-hidden="true">${isCollection ? '▥' : (item.source_kind === 'audio' ? '♪' : '▶')}</span>
                <span><strong>${escapeHTML(item.title || '未命名内容')}</strong><span>${escapeHTML(meta)}</span></span>
                <span class="study-library-card-action">${isCollection ? '选择一集' : '进入播放器'} →</span>
            </a>`;
        }).join('');
    }

    function acceptedMediaFiles(fileList) {
        const extensions = /\.(mp3|m4a|wav|aac|flac|mp4|mov|mkv|webm|avi|m4v)$/i;
        return Array.from(fileList || [])
            .filter((file) => /^(audio|video)\//.test(file.type || '') || extensions.test(file.name || ''))
            .sort((a, b) => (a.webkitRelativePath || a.name).localeCompare(
                b.webkitRelativePath || b.name,
                undefined,
                { numeric: true, sensitivity: 'base' }
            ));
    }

    function showLocalPreview(file, contextLabel) {
        if (state.localObjectUrl) URL.revokeObjectURL(state.localObjectUrl);
        state.localObjectUrl = URL.createObjectURL(file);
        const audio = (file.type || '').startsWith('audio/') || /\.(mp3|m4a|wav|aac|flac)$/i.test(file.name);
        renderSession({
            state: 'ready',
            metadata: { title: file.name, view_token: viewToken },
            playback: { source_available: false, source_url: '', unavailable_reason: '' },
            source: { kind: audio ? 'audio' : 'video', filename: file.name, media_type: file.type || '' },
            transcript: { lines: [] },
            ai: { overview: '本地文件正在后台上传和解析。播放不需要等待；逐字稿生成后会自动出现在右侧。', chat_model: 'deepseek-v4-pro' },
            notes: [],
            progress: {},
        });
        els.studyPageContext.textContent = contextLabel;
        window.setTimeout(() => els.video.play().catch(() => {}), 0);
    }

    async function importSingleFile(file) {
        if (!file) return;
        pageMode = 'single';
        viewToken = '';
        showLocalPreview(file, '单个内容 · 本地文件');
        const form = new FormData();
        form.append('file', file, file.name);
        try {
            const result = await apiJSON('/api/study/upload', { method: 'POST', body: form });
            viewToken = result.view_token;
            history.replaceState({}, '', `/study/${encodeURIComponent(viewToken)}`);
            await loadSession();
        } catch (error) {
            els.progressCard.hidden = false;
            els.progressTitle.textContent = '上传或解析启动失败';
            els.progressDetail.textContent = `${error.message || '请重新选择文件'}；当前本地播放不受影响。`;
            showToast(error.message || '上传失败');
        } finally {
            els.singleFile.value = '';
        }
    }

    function collectionTitle(files) {
        const relative = files[0] && files[0].webkitRelativePath;
        if (relative && relative.includes('/')) return relative.split('/')[0].trim() || '本地音视频合集';
        const stem = String((files[0] && files[0].name) || '').replace(/\.[^.]+$/, '');
        return stem.replace(/^[\s\d._-]+/, '').replace(/[\s_-]*\d+$/, '').trim() || '本地音视频合集';
    }

    async function importCollectionFiles(fileList) {
        const files = acceptedMediaFiles(fileList);
        if (!files.length) {
            showToast('没有找到支持的音视频文件');
            return;
        }
        pageMode = 'collection';
        collectionId = '';
        sourceId = '';
        viewToken = '';
        showLocalPreview(files[0], `合集内容 · ${collectionTitle(files)}`);
        try {
            const collection = await apiJSON('/api/collections', {
                method: 'POST',
                body: JSON.stringify({
                    title: collectionTitle(files),
                    creator_name: '未归属',
                    collection_type: 'video_course',
                    import_method: 'study_local_import',
                }),
            });
            collectionId = collection.id;
            const form = new FormData();
            files.forEach((file) => form.append('files', file, file.name));
            const result = await apiJSON(
                `/api/collections/${encodeURIComponent(collectionId)}/sources/upload`,
                { method: 'POST', body: form }
            );
            const sources = result.sources || [];
            if (!sources.length) throw new Error('合集没有创建出可播放内容');
            sourceId = sources[0].id;
            history.replaceState(
                {},
                '',
                `/study/collections/${encodeURIComponent(collectionId)}/sources/${encodeURIComponent(sourceId)}`
            );
            await loadSession();
        } catch (error) {
            els.progressCard.hidden = false;
            els.progressTitle.textContent = '合集导入失败';
            els.progressDetail.textContent = `${error.message || '请重新选择文件'}；当前第一集仍可在本地播放。`;
            showToast(error.message || '合集导入失败');
        } finally {
            els.collectionFolder.value = '';
            els.collectionFiles.value = '';
        }
    }

    async function navigateCollectionSource(nextSourceId, pushHistory) {
        if (!nextSourceId || nextSourceId === sourceId) return;
        savePlaybackProgress();
        sourceId = nextSourceId;
        state.currentLineId = '';
        state.chatMessages = [];
        state.visualDocuments = {};
        state.visualStates = {};
        resetStudyNoteState();
        state.noteContext = '';
        if (pushHistory !== false) {
            history.pushState(
                {},
                '',
                `/study/collections/${encodeURIComponent(collectionId)}/sources/${encodeURIComponent(sourceId)}`
            );
        }
        await loadSession();
    }

    function bindLibrary() {
        document.querySelectorAll('[data-library-kind]').forEach((button) => {
            button.addEventListener('click', () => setLibraryKind(button.dataset.libraryKind));
        });
        els.librarySearch.addEventListener('input', () => {
            window.clearTimeout(state.libraryTimer);
            state.libraryTimer = window.setTimeout(loadLibrary, 260);
        });
        els.singleFile.addEventListener('change', () => importSingleFile(acceptedMediaFiles(els.singleFile.files)[0]));
        els.collectionFolder.addEventListener('change', () => importCollectionFiles(els.collectionFolder.files));
        els.collectionFiles.addEventListener('change', () => importCollectionFiles(els.collectionFiles.files));
    }

    function bindCollectionNavigation() {
        els.collectionSelect.addEventListener('change', () => navigateCollectionSource(els.collectionSelect.value));
        els.collectionPrev.addEventListener('click', () => {
            const index = els.collectionSelect.selectedIndex;
            if (index > 0) navigateCollectionSource(els.collectionSelect.options[index - 1].value);
        });
        els.collectionNext.addEventListener('click', () => {
            const index = els.collectionSelect.selectedIndex;
            if (index >= 0 && index < els.collectionSelect.options.length - 1) {
                navigateCollectionSource(els.collectionSelect.options[index + 1].value);
            }
        });
        els.askCurrentCaption.addEventListener('click', () => {
            const line = getCurrentTranscriptLine();
            activateTab('chat');
            els.chatQuestion.value = line ? `请解释这句话：“${line.text}”` : '';
            autosizeChatInput();
            els.chatQuestion.focus();
        });
        window.addEventListener('popstate', () => {
            const collectionMatch = location.pathname.match(/^\/study\/collections\/([^/]+)\/sources\/([^/]+)$/);
            if (collectionMatch) {
                pageMode = 'collection';
                collectionId = decodeURIComponent(collectionMatch[1]);
                sourceId = decodeURIComponent(collectionMatch[2]);
                loadSession();
                return;
            }
            const singleMatch = location.pathname.match(/^\/study\/([^/]+)$/);
            if (singleMatch) {
                pageMode = 'single';
                viewToken = decodeURIComponent(singleMatch[1]);
                loadSession();
                return;
            }
            location.reload();
        });
    }

    async function loadSession() {
        window.clearTimeout(state.pollTimer);
        try {
            const session = await apiJSON(studyApiBase());
            renderSession(session);
        } catch (error) {
            const message = escapeHTML(error.message || '请稍后重试');
            els.state.textContent = '不可用';
            els.title.textContent = '学习内容加载失败';
            els.aiOverview.textContent = error.message || '请稍后重试';
            els.aiReadingContent.textContent = error.message || '请稍后重试';
            els.aiOverviewExpand.disabled = true;
            els.aiOverviewMeta.textContent = '内容加载失败';
            setVisualStatus(error.message || '视觉速览加载失败', true);
            els.transcriptList.innerHTML = `<div class="empty-panel"><strong>文稿加载失败</strong><span>${message}</span></div>`;
            els.chatList.innerHTML = `<div class="empty-panel"><strong>问答加载失败</strong><span>${message}</span></div>`;
            els.exportMarkdown.disabled = true;
            showToast(error.message || '学习内容加载失败');
        }
    }

    function scheduleNextPoll(session) {
        window.clearTimeout(state.pollTimer);
        if (isPendingState(session.state)) {
            state.pollTimer = window.setTimeout(loadSession, 3000);
        }
    }

    function init() {
        bindTabs();
        bindTranscript();
        bindPanelSeek();
        bindVideo();
        bindChat();
        bindStudyNote();
        bindActions();
        bindVisualLearning();
        bindLibrary();
        bindCollectionNavigation();
        if (pageMode === 'library') {
            els.library.hidden = false;
            els.player.hidden = true;
            loadLibrary();
        } else {
            els.library.hidden = true;
            els.player.hidden = false;
            loadSession();
        }
    }

    init();
})();
