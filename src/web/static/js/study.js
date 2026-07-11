(function () {
    const STORAGE_KEY = 'vta_bearer_token';
    const ENCRYPTION_KEY = 'vta_encrypt_key_2024';
    const viewToken = window.STUDY_VIEW_TOKEN || '';
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
        playToggle: document.getElementById('play-toggle'),
        progress: document.getElementById('video-progress'),
        videoTime: document.getElementById('video-time'),
        playStrip: document.getElementById('study-play-strip'),
        sourceCard: document.getElementById('study-source-card'),
        sourceName: document.getElementById('study-source-name'),
        sourceMeta: document.getElementById('study-source-meta'),
        studySourceOpen: document.getElementById('study-source-open'),
        progressCard: document.getElementById('study-progress-card'),
        progressTitle: document.getElementById('study-progress-title'),
        progressDetail: document.getElementById('study-progress-detail'),
        progressFill: document.getElementById('study-progress-fill'),
        aiOverview: document.getElementById('ai-overview'),
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
            const error = new Error(payload.detail || payload.message || '请求失败');
            error.status = response.status;
            throw error;
        }
        return payload.data;
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
        const playback = session.playback || {};
        const source = session.source || { kind: 'unknown' };
        const transcript = session.transcript || { lines: [] };

        const documentSource = ['document', 'text'].includes(source.kind);
        const sourceLabel = documentSource ? '文档学习' : (source.kind === 'audio' ? '音频学习' : '视频学习');
        els.studyPageContext.textContent = sourceLabel;
        els.studyWorkbenchTitle.textContent = sourceLabel;
        document.title = `${metadata.title || sourceLabel} - 内容解析工作台`;
        els.title.textContent = metadata.title || sourceLabel;
        els.videoTitle.textContent = metadata.title || sourceLabel;
        els.breadcrumbs.textContent = `${sourceLabel} / ${metadata.title || '学习模式'}`;
        els.subtitle.textContent = metadata.author
            ? `作者：${metadata.author}`
            : (documentSource ? '原文、AI 解读、图解和问答围绕同一份文档组织。' : '视频、文稿、AI 解读和问答围绕同一条时间轴组织。');
        els.state.textContent = stateLabel(session.state);
        els.transcriptCount.textContent = `${transcript.lines.length} 段`;
        els.aiModel.textContent = modelLabel(session.ai && session.ai.chat_model);
        els.aiOverview.innerHTML = renderMarkdown(aiOverviewText(session));
        els.exportMarkdown.disabled = isPendingState(session.state) && !transcript.lines.length;

        renderSourceMode(source);
        renderPlayback(playback, source);
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
            if (els.video.getAttribute('src') !== playback.source_url) {
                els.video.src = playback.source_url;
            }
            els.videoFrame.classList.add('has-video');
            els.videoMeta.textContent = '本地视频 · 已保留源文件';
            return;
        }
        els.video.removeAttribute('src');
        els.videoFrame.classList.remove('has-video');
        els.videoMeta.textContent = playback.unavailable_reason || '源视频不可用';
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
        const paragraphs = groupTranscriptLines(lines, 5).map((group) => (
            `<p>${group.map((line) => {
                const disabled = line.seekable ? '' : ' disabled';
                const time = line.seekable ? formatTime(line.start_seconds) : '--:--';
                const title = line.estimated ? `${time} 估算时间` : time;
                return `<button class="transcript-segment" type="button" data-line-id="${escapeHTML(line.id)}" data-time="${line.start_seconds ?? ''}" title="${escapeHTML(title)}"${disabled}>${escapeHTML(line.text)}</button>`;
            }).join('')}</p>`
        )).join('');

        els.transcriptList.innerHTML = `<article class="manuscript-reader">${paragraphs}</article>
            <button class="back-playhead" type="button">回播放处</button>`;
    }

    function groupTranscriptLines(lines, size) {
        const groups = [];
        for (let index = 0; index < lines.length; index += size) {
            groups.push(lines.slice(index, index + size));
        }
        return groups;
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
            window.VisualLearning.render(els.visualModalContent, visualDocument, options);
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
                { onSourceRef: handleVisualSourceRef }
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
        const target = Array.from(document.querySelectorAll('.transcript-segment'))
            .find((button) => button.dataset.lineId === line.id);
        if (target) {
            document.querySelectorAll('.transcript-segment').forEach((button) => {
                button.classList.toggle('is-current', button === target);
            });
            target.scrollIntoView({ block: 'center', behavior: 'smooth' });
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
            });
        });
    }

    function bindTranscript() {
        els.transcriptList.addEventListener('click', (event) => {
            const scrollButton = event.target.closest('.back-playhead');
            if (scrollButton) {
                scrollActiveTranscriptIntoView();
                return;
            }
            const button = event.target.closest('.transcript-segment');
            if (!button || button.disabled) return;
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
        els.playToggle.addEventListener('click', () => {
            if (!els.video.src) return;
            if (els.video.paused) {
                els.video.play().catch(() => showToast('浏览器阻止了自动播放，请直接点击视频播放'));
            } else {
                els.video.pause();
            }
        });
        els.video.addEventListener('play', () => { els.playToggle.textContent = 'Ⅱ'; });
        els.video.addEventListener('pause', () => { els.playToggle.textContent = '▶'; });
        els.video.addEventListener('timeupdate', updateVideoProgress);
        els.video.addEventListener('loadedmetadata', () => {
            updateVideoProgress();
            applyEstimatedTranscriptTimes();
        });
    }

    function seekTo(seconds) {
        if (!Number.isFinite(seconds) || !els.video.src) return;
        els.video.currentTime = Math.max(0, seconds);
        if (els.video.paused) {
            els.video.play().catch(() => {});
        }
    }

    function updateVideoProgress() {
        const duration = els.video.duration || 0;
        const current = els.video.currentTime || 0;
        const value = duration ? `${Math.min(100, (current / duration) * 100)}%` : '0%';
        els.progress.style.setProperty('--value', value);
        els.videoTime.textContent = `${formatTime(current)} / ${formatTime(duration)}`;
        highlightTranscript(current);
    }

    function highlightTranscript(currentSeconds) {
        const lines = (state.session && state.session.transcript && state.session.transcript.lines) || [];
        let active = null;
        for (const line of lines) {
            if (!line.seekable) continue;
            if (line.start_seconds <= currentSeconds) {
                active = line;
            }
        }
        if (!active || active.id === state.currentLineId) return;
        state.currentLineId = active.id;
        document.querySelectorAll('.transcript-segment').forEach((button) => {
            button.classList.toggle('is-current', button.dataset.lineId === active.id);
        });
    }

    function scrollActiveTranscriptIntoView() {
        const current = document.querySelector('.transcript-segment.is-current');
        if (current) {
            current.scrollIntoView({ block: 'center', behavior: 'smooth' });
            return;
        }
        const line = getCurrentTranscriptLine();
        if (!line) return;
        const target = Array.from(document.querySelectorAll('.transcript-segment'))
            .find((button) => button.dataset.lineId === line.id);
        if (target) target.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }

    function getCurrentTranscriptLine() {
        const lines = (state.session && state.session.transcript && state.session.transcript.lines) || [];
        if (!lines.length) return null;
        const currentLine = lines.find((line) => line.id === state.currentLineId);
        if (currentLine) return currentLine;

        const currentSeconds = Number(els.video.currentTime || 0);
        let active = null;
        for (const line of lines) {
            if (!line.seekable) continue;
            if (line.start_seconds <= currentSeconds) {
                active = line;
            }
        }
        return active || lines[0];
    }

    function applyEstimatedTranscriptTimes() {
        const session = state.session;
        const lines = (session && session.transcript && session.transcript.lines) || [];
        if (!lines.length || lines.some((line) => line.seekable)) return;

        const duration = Number(els.video.duration || 0);
        if (!Number.isFinite(duration) || duration <= 0) return;

        const token = `${session.metadata && session.metadata.view_token}:${Math.round(duration)}:${lines.length}`;
        if (state.estimatedToken === token) return;

        const step = duration / lines.length;
        session.transcript.lines = lines.map((line, index) => ({
            ...line,
            start_seconds: Number((index * step).toFixed(3)),
            end_seconds: Number(Math.min(duration, (index + 1) * step).toFixed(3)),
            seekable: true,
            estimated: true,
        }));
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
            const result = await apiJSON(`/api/study/${encodeURIComponent(viewToken)}/ai-chat`, {
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
            const response = await fetch(`/api/study/${encodeURIComponent(viewToken)}/export/markdown`, {
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

    async function loadSession() {
        window.clearTimeout(state.pollTimer);
        try {
            const session = await apiJSON(`/api/study/${encodeURIComponent(viewToken)}`);
            renderSession(session);
        } catch (error) {
            const message = escapeHTML(error.message || '请稍后重试');
            els.state.textContent = '不可用';
            els.title.textContent = '学习内容加载失败';
            els.aiOverview.textContent = error.message || '请稍后重试';
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
        bindActions();
        bindVisualLearning();
        loadSession();
    }

    init();
})();
