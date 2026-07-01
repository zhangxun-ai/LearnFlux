(function () {
    const STORAGE_KEY = 'vta_bearer_token';
    const ENCRYPTION_KEY = 'vta_encrypt_key_2024';
    const viewToken = window.STUDY_VIEW_TOKEN || '';
    const state = {
        session: null,
        currentLineId: '',
        pollTimer: null,
        estimatedToken: '',
        noteFrameToken: '',
        noteFrames: {},
    };

    const els = {
        title: document.getElementById('study-title'),
        subtitle: document.getElementById('study-subtitle'),
        state: document.getElementById('study-state'),
        transcriptCount: document.getElementById('study-transcript-count'),
        noteCount: document.getElementById('study-note-count'),
        breadcrumbs: document.getElementById('study-breadcrumbs'),
        videoTitle: document.getElementById('video-title'),
        videoMeta: document.getElementById('video-meta'),
        videoFrame: document.getElementById('video-frame'),
        video: document.getElementById('study-video'),
        videoEmpty: document.getElementById('video-empty'),
        playToggle: document.getElementById('play-toggle'),
        progress: document.getElementById('video-progress'),
        videoTime: document.getElementById('video-time'),
        progressCard: document.getElementById('study-progress-card'),
        progressTitle: document.getElementById('study-progress-title'),
        progressDetail: document.getElementById('study-progress-detail'),
        progressFill: document.getElementById('study-progress-fill'),
        aiOverview: document.getElementById('ai-overview'),
        aiNotesList: document.getElementById('ai-notes-list'),
        transcriptList: document.getElementById('transcript-list'),
        noteBody: document.getElementById('note-body'),
        saveNote: document.getElementById('save-note'),
        notesList: document.getElementById('notes-list'),
        captureNote: document.getElementById('capture-note'),
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
            throw new Error(payload.detail || payload.message || '请求失败');
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

    function isPendingState(value) {
        return ['queued', 'processing', 'downloading', 'transcribing', 'generating_ai'].includes(value);
    }

    function renderSession(session) {
        state.session = session;
        const metadata = session.metadata || {};
        const playback = session.playback || {};
        const transcript = session.transcript || { lines: [] };
        const notes = session.notes || [];

        els.title.textContent = metadata.title || '本地视频学习';
        els.videoTitle.textContent = metadata.title || '本地视频';
        els.breadcrumbs.textContent = `本地视频 / ${metadata.title || '学习模式'}`;
        els.subtitle.textContent = metadata.author ? `作者：${metadata.author}` : '视频、文稿、AI 解读和时间点记录围绕同一条时间轴组织。';
        els.state.textContent = stateLabel(session.state);
        els.transcriptCount.textContent = `${transcript.lines.length} 段`;
        els.noteCount.textContent = `${notes.length} 条`;
        els.aiOverview.innerHTML = renderMarkdown(aiOverviewText(session));
        els.exportMarkdown.disabled = isPendingState(session.state) && !transcript.lines.length;

        renderPlayback(playback);
        renderProgress(session);
        renderTranscript(transcript.lines || [], session);
        renderAINotes(session);
        renderNotes(notes);
        applyEstimatedTranscriptTimes();
        generateNoteFrames(session);
        scheduleNextPoll(session);
    }

    function renderPlayback(playback) {
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

    function renderAINotes(session) {
        if (!els.aiNotesList) return;
        const sections = buildStudySections(session, 6);
        if (!sections.length) {
            els.aiNotesList.innerHTML = panelFallback(session, '笔记生成中', '文稿完成后会自动整理图文笔记。');
            return;
        }

        els.aiNotesList.innerHTML = sections.map((section) => {
            const timeButton = renderTimeButton(section, 'note');
            const points = section.points.map((point) => `<li>${escapeHTML(point)}</li>`).join('');
            const frame = state.noteFrames[section.id];
            const visual = frame
                ? `<img src="${frame}" alt="${escapeHTML(section.title)} 对应的视频画面" loading="lazy">`
                : `<div class="note-visual-fallback"><span>${escapeHTML(section.indexLabel)}</span><strong>${escapeHTML(section.title)}</strong></div>`;
            return `<article class="ai-note-section">
                <div class="note-heading">
                    <h4>${escapeHTML(section.indexText)} ${escapeHTML(section.title)}</h4>
                    ${timeButton}
                </div>
                <figure class="note-visual">${visual}</figure>
                <ul>${points}</ul>
            </article>`;
        }).join('');
    }

    function panelFallback(session, title, message) {
        if (isPendingState(session.state)) {
            return `<div class="empty-panel"><strong>${title}</strong><span>${message}</span></div>`;
        }
        if (session.state === 'failed') {
            return '<div class="empty-panel"><strong>内容生成失败</strong><span>请检查转录服务或重新上传视频。</span></div>';
        }
        return '<div class="empty-panel"><strong>暂无可整理内容</strong><span>当前任务还没有可用于生成学习卡片的文稿。</span></div>';
    }

    function groupTranscriptLines(lines, size) {
        const groups = [];
        for (let index = 0; index < lines.length; index += size) {
            groups.push(lines.slice(index, index + size));
        }
        return groups;
    }

    function buildStudySections(session, limit) {
        const lines = (session.transcript && session.transcript.lines) || [];
        const usableLines = lines.filter((line) => (line.text || '').trim());
        if (!usableLines.length) return [];

        const chunkSize = Math.max(1, Math.ceil(usableLines.length / limit));
        return groupTranscriptLines(usableLines, chunkSize).slice(0, limit).map((group, index) => {
            const firstLine = group[0];
            const clean = normalizeText(group.map((line) => line.text).join(' '));
            const title = sectionTitle(clean, index);
            return {
                id: `ai-note-${index + 1}`,
                indexText: chineseIndex(index + 1),
                indexLabel: String(index + 1).padStart(2, '0'),
                title,
                summary: shorten(clean, 120),
                points: splitPoints(clean),
                startSeconds: firstLine.seekable ? Number(firstLine.start_seconds) : null,
                seekable: Boolean(firstLine.seekable),
            };
        });
    }

    function chineseIndex(value) {
        const labels = ['一、', '二、', '三、', '四、', '五、', '六、', '七、', '八、'];
        return labels[value - 1] || `${value}.`;
    }

    function sectionTitle(text, index) {
        const first = text.split(/[。！？!?；;]/)[0] || text;
        return shorten(first, 24) || `重点 ${index + 1}`;
    }

    function splitPoints(text) {
        const sentences = [];
        let buffer = '';
        Array.from(text).forEach((char) => {
            buffer += char;
            if ('。！？!?；;'.includes(char)) {
                const sentence = buffer.trim();
                if (sentence) sentences.push(sentence);
                buffer = '';
            }
        });
        if (buffer.trim()) sentences.push(buffer.trim());
        const points = sentences.length ? sentences : [text];
        return points.slice(0, 3).map((item) => shorten(item, 58));
    }

    function normalizeText(value) {
        return String(value || '').replace(/\s+/g, ' ').trim();
    }

    function shorten(value, maxLength) {
        const text = normalizeText(value);
        if (text.length <= maxLength) return text;
        return `${text.slice(0, maxLength - 1)}…`;
    }

    function renderTimeButton(section, source) {
        if (!section.seekable || !Number.isFinite(section.startSeconds)) {
            return '<span class="time-pill is-disabled">--:--</span>';
        }
        return `<button class="time-pill panel-seek" type="button" data-source="${source}" data-time="${section.startSeconds}">▶ ${formatTime(section.startSeconds)}</button>`;
    }

    async function generateNoteFrames(session) {
        const playback = session.playback || {};
        if (!playback.source_available || !playback.source_url) return;

        const sections = buildStudySections(session, 6).filter((section) => section.seekable);
        if (!sections.length) return;

        const token = `${playback.source_url}:${sections.map((section) => Math.round(section.startSeconds || 0)).join(',')}`;
        if (state.noteFrameToken === token) return;
        state.noteFrameToken = token;
        state.noteFrames = {};

        try {
            const frames = await captureVideoFrames(playback.source_url, sections);
            if (!Object.keys(frames).length || state.noteFrameToken !== token) return;
            state.noteFrames = frames;
            if (state.session) renderAINotes(state.session);
        } catch (error) {
            state.noteFrames = {};
        }
    }

    function captureVideoFrames(sourceUrl, sections) {
        return new Promise((resolve) => {
            const video = document.createElement('video');
            const canvas = document.createElement('canvas');
            const context = canvas.getContext('2d');
            const frames = {};
            let index = 0;

            canvas.width = 360;
            canvas.height = 202;
            video.muted = true;
            video.playsInline = true;
            video.preload = 'metadata';

            const cleanup = () => {
                video.removeAttribute('src');
                video.load();
            };

            const finish = () => {
                cleanup();
                resolve(frames);
            };

            const captureCurrent = () => {
                const section = sections[index];
                try {
                    if (video.videoWidth && video.videoHeight && context) {
                        context.fillStyle = '#111';
                        context.fillRect(0, 0, canvas.width, canvas.height);
                        const scale = Math.max(canvas.width / video.videoWidth, canvas.height / video.videoHeight);
                        const width = video.videoWidth * scale;
                        const height = video.videoHeight * scale;
                        const x = (canvas.width - width) / 2;
                        const y = (canvas.height - height) / 2;
                        context.drawImage(video, x, y, width, height);
                        frames[section.id] = canvas.toDataURL('image/jpeg', 0.78);
                    }
                } catch (error) {
                    finish();
                    return;
                }

                index += 1;
                seekNext();
            };

            const seekNext = () => {
                if (index >= sections.length) {
                    finish();
                    return;
                }
                const target = Math.min(Math.max(0, sections[index].startSeconds || 0), Math.max(0, (video.duration || 0) - 0.2));
                video.currentTime = target;
            };

            video.addEventListener('loadedmetadata', seekNext, { once: true });
            video.addEventListener('seeked', captureCurrent);
            video.addEventListener('error', finish, { once: true });
            video.src = sourceUrl;
        });
    }

    function renderNotes(notes) {
        if (!notes.length) {
            els.notesList.innerHTML = '<div class="empty-panel"><strong>暂无记录</strong><span>播放视频时点击“记当前点”，或直接写下你的理解。</span></div>';
            return;
        }
        els.notesList.innerHTML = notes.map((note) => (
            `<article class="note-item">
                <strong>${formatTime(note.time_seconds)}</strong>
                <p>${escapeHTML(note.body || '')}</p>
            </article>`
        )).join('');
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
        renderAINotes(session);
        generateNoteFrames(session);
    }

    function bindNotes() {
        els.captureNote.addEventListener('click', () => {
            activateTab('notes');
            els.noteBody.focus();
        });
        els.saveNote.addEventListener('click', saveNote);
    }

    function bindActions() {
        els.copyCurrentLine.addEventListener('click', copyCurrentLine);
        els.exportMarkdown.addEventListener('click', exportMarkdown);
    }

    function activateTab(tab) {
        const button = document.querySelector(`.right-tabs [data-tab="${tab}"]`);
        if (button) button.click();
    }

    async function saveNote() {
        const body = els.noteBody.value.trim();
        if (!body) {
            showToast('请先写下笔记内容');
            return;
        }
        els.saveNote.disabled = true;
        try {
            await apiJSON(`/api/study/${encodeURIComponent(viewToken)}/notes`, {
                method: 'POST',
                body: JSON.stringify({
                    time_seconds: els.video.src ? Number(els.video.currentTime || 0) : null,
                    body,
                }),
            });
            els.noteBody.value = '';
            showToast('记录已保存');
            await loadSession();
            activateTab('notes');
        } catch (error) {
            showToast(error.message || '保存笔记失败');
        } finally {
            els.saveNote.disabled = false;
        }
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
            if (els.aiNotesList) {
                els.aiNotesList.innerHTML = `<div class="empty-panel"><strong>笔记加载失败</strong><span>${message}</span></div>`;
            }
            els.transcriptList.innerHTML = `<div class="empty-panel"><strong>文稿加载失败</strong><span>${message}</span></div>`;
            els.notesList.innerHTML = `<div class="empty-panel"><strong>记录加载失败</strong><span>${message}</span></div>`;
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
        bindNotes();
        bindActions();
        loadSession();
    }

    init();
})();
