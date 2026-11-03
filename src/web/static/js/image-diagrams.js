(function (global) {
    'use strict';

    const ACTIVE = new Set(['queued', 'planning', 'generating']);
    const LABELS = {
        queued: '已排队，等待开始', planning: '正在整理内容与绘图方案',
        generating: '正在生成图片', reviewing: '图解已生成',
        succeeded: '图解已生成', failed: '本次生成未完成', unknown: '本次请求结果尚未确认',
    };
    const mounts = new WeakMap();
    let instanceCount = 0;

    function node(tag, className, text) {
        const element = document.createElement(tag);
        if (className) element.className = className;
        if (text !== undefined) element.textContent = String(text);
        return element;
    }
    function action(label, className, callback) {
        const button = node('button', className || 'idg-button', label);
        button.type = 'button';
        button.addEventListener('click', callback);
        return button;
    }
    function uuid() {
        if (global.crypto && global.crypto.randomUUID) return global.crypto.randomUUID();
        return `image-${Date.now()}-${Math.random().toString(36).slice(2, 14)}`;
    }
    function normalizeJob(job) {
        if (!job || job.status !== 'reviewing') return job;
        return { ...job, status: job.image_url ? 'succeeded' : 'generating', stage: job.image_url ? 'completed' : 'generating' };
    }
    function timeLabel(value) {
        if (!value) return '';
        if (global.LearnFluxTime) return global.LearnFluxTime.format(value, {
            month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
        });
        return new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false });
    }
    function privateImageURL(value) {
        try {
            const url = new URL(value, global.location.href);
            return url.origin === global.location.origin && url.pathname.startsWith('/api/image-diagrams/jobs/')
                ? url.href : '';
        } catch (_) { return ''; }
    }
    async function apiJSON(url, options) {
        const init = options || {};
        const headers = new Headers(init.headers || {});
        if (init.body) headers.set('Content-Type', 'application/json');
        const response = await global.fetch(url, { ...init, headers, credentials: 'same-origin' });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || Number(payload.code || 0) >= 400) {
            const detail = payload.detail;
            const error = new Error(typeof detail === 'string' ? detail : payload.message || '图解请求未完成，请稍后检查状态');
            error.status = response.status;
            throw error;
        }
        return payload.data || {};
    }

    function mount(container, options) {
        if (!container) throw new Error('Image diagram container is required');
        if (mounts.has(container)) mounts.get(container).destroy();
        const config = options || {};
        const viewToken = String(config.viewToken || '');
        const base = `/api/image-diagrams/study/${encodeURIComponent(viewToken)}`;
        const prefix = `idg-${++instanceCount}`;
        const state = {
            destroyed: false, loaded: false, enabled: false, sourceReady: true, loading: false, submitting: false,
            versions: [], selected: null, active: null, timer: null,
            pendingSubmission: null, refreshSerial: 0, dialogTrigger: null,
            progressTimer: null, progressPaused: false, submissionStarted: null,
        };
        const root = node('section', 'image-diagrams');
        root.setAttribute('aria-label', 'AI 图片图解');
        const statusArea = node('div', 'idg-status-area');
        const refreshButton = action('刷新状态', 'idg-button idg-quiet', async () => {
            if (state.authRequired && global.LearnFluxAuth) {
                try {
                    await global.LearnFluxAuth.requireSession({ title: '连接后查看图解', reason: '连接后读取已有图片和生成进度。' });
                } catch (_) { return; }
            }
            await refresh();
        });
        const form = node('div', 'idg-controls');
        form.id = `${prefix}-edit`;
        form.hidden = true;
        function field(labelText, element, suffix) {
            const wrap = node('div', 'idg-field');
            element.id = `${prefix}-${suffix}`;
            const label = node('label', '', labelText);
            label.setAttribute('for', element.id);
            wrap.append(label, element);
            return wrap;
        }
        const instructions = node('textarea');
        instructions.rows = 2;
        instructions.maxLength = 2000;
        instructions.placeholder = '希望这张图怎么改？';
        const instructionsField = field('修改意见', instructions, 'instructions');
        const actions = node('div', 'idg-actions');
        const generateButton = action('生成图解', 'idg-button idg-primary', () => submit('generate'));
        const regenerateButton = action('重新生成', 'idg-button', () => submit('regenerate'));
        const reviseButton = action('生成修改版', 'idg-button idg-primary', () => submit('revise'));
        const editButton = action('修改', 'idg-button idg-quiet', () => {
            form.hidden = !form.hidden;
            editButton.setAttribute('aria-expanded', String(!form.hidden));
            if (!form.hidden) instructions.focus();
        });
        editButton.setAttribute('aria-controls', form.id);
        editButton.setAttribute('aria-expanded', 'false');
        const cancelEdit = action('取消', 'idg-button idg-quiet', () => {
            form.hidden = true;
            editButton.setAttribute('aria-expanded', 'false');
            editButton.focus();
        });
        regenerateButton.hidden = true;
        actions.append(reviseButton, cancelEdit);
        form.append(instructionsField, actions);
        const status = node('p', 'idg-status', '正在读取已有图解…');
        status.setAttribute('role', 'status');
        status.setAttribute('aria-live', 'polite');
        statusArea.append(status, refreshButton);
        const progressPanel = node('div', 'idg-progress');
        progressPanel.hidden = true;
        progressPanel.setAttribute('aria-label', '图解生成进度');
        const progressTop = node('div', 'idg-progress-top');
        const progressTitle = node('p', 'idg-progress-title');
        progressTitle.setAttribute('role', 'status');
        progressTitle.setAttribute('aria-live', 'polite');
        const elapsed = node('span', 'idg-progress-time');
        progressTop.append(progressTitle, elapsed);
        const progressDetail = node('p', 'idg-progress-detail');
        const stepList = node('ol', 'idg-progress-steps');
        const steps = ['准备内容', '绘制图解'].map(label => {
            const item = node('li', '', label);
            stepList.append(item);
            return item;
        });
        const progressTrack = node('div', 'idg-progress-track');
        progressTrack.setAttribute('role', 'progressbar');
        const progressFill = node('span');
        progressTrack.append(progressFill);
        const progressHint = node('p', 'idg-progress-hint', '可以先去阅读，图解会在后台继续生成');
        progressPanel.append(progressTop, progressDetail, stepList, progressTrack, progressHint);
        let progressInView = true;
        function syncProgressVisibility() {
            progressPanel.dataset.visible = !document.hidden && progressInView ? 'true' : 'false';
        }
        const progressObserver = typeof global.IntersectionObserver === 'function'
            ? new global.IntersectionObserver(entries => {
                progressInView = entries.some(entry => entry.isIntersecting);
                syncProgressVisibility();
            }) : null;
        if (progressObserver) progressObserver.observe(progressPanel);
        if (document.addEventListener) document.addEventListener('visibilitychange', syncProgressVisibility);
        syncProgressVisibility();
        const preview = node('div', 'idg-preview');
        const imageButton = action('', 'idg-image-button', () => openZoom());
        imageButton.setAttribute('aria-label', '放大查看当前图解');
        const image = node('img', 'idg-image');
        image.loading = 'lazy';
        image.decoding = 'async';
        imageButton.append(image);
        imageButton.hidden = true;
        const entry = node('div', 'idg-entry');
        entry.append(generateButton);
        preview.append(imageButton, entry);
        const resultBar = node('div', 'idg-result-bar');
        resultBar.hidden = true;
        const resultMeta = node('span', 'idg-muted');
        const zoomButton = action('放大', 'idg-button idg-quiet', () => openZoom());
        const download = node('a', 'idg-button idg-quiet', '下载');
        download.setAttribute('download', '');
        resultBar.append(zoomButton, download, editButton);
        const more = node('details', 'idg-more');
        more.hidden = true;
        more.append(node('summary', '', '更多'));
        const historySelect = node('select');
        const historyField = field('历史版本', historySelect, 'history');
        historyField.hidden = true;
        const sourceNotes = node('details', 'idg-source-notes');
        sourceNotes.hidden = true;
        more.append(resultMeta, regenerateButton, historyField, sourceNotes);
        const dialog = node('dialog', 'idg-zoom');
        dialog.setAttribute('aria-label', '放大查看图解');
        const dialogBar = node('div', 'idg-zoom-bar');
        const closeButton = action('关闭', 'idg-button', () => dialog.close());
        const zoomStage = node('div', 'idg-zoom-stage');
        const zoomImage = node('img');
        const zoomToggle = action('原始尺寸', 'idg-button', () => {
            zoomStage.dataset.zoom = zoomStage.dataset.zoom === 'actual' ? 'fit' : 'actual';
            zoomToggle.textContent = zoomStage.dataset.zoom === 'actual' ? '适应屏幕' : '原始尺寸';
        });
        dialogBar.append(node('span', '', '滚动查看图片'), zoomToggle, closeButton);
        zoomStage.append(zoomImage);
        dialog.append(dialogBar, zoomStage);
        dialog.addEventListener('click', (event) => { if (event.target === dialog) dialog.close(); });
        dialog.addEventListener('close', () => {
            if (state.dialogTrigger && state.dialogTrigger.isConnected) state.dialogTrigger.focus();
        });
        root.append(statusArea, progressPanel, resultBar, form, preview, more, dialog);
        container.replaceChildren(root);

        function busy() { return state.submitting || Boolean(state.active && ACTIVE.has(state.active.status)); }
        function updateControls() {
            const blocked = !state.loaded || !state.enabled || !state.sourceReady || busy();
            const unresolved = Boolean(state.pendingSubmission);
            generateButton.disabled = blocked;
            generateButton.textContent = unresolved ? '确认上次请求' : '生成图解';
            regenerateButton.disabled = blocked || unresolved;
            reviseButton.disabled = blocked || unresolved;
            instructions.disabled = blocked || unresolved;
            const hasImage = Boolean(state.selected && state.selected.image_url);
            entry.hidden = busy() || (hasImage && !unresolved);
            const unknown = Boolean(state.versions[0] && state.versions[0].status === 'unknown');
            if (unknown && !unresolved) generateButton.disabled = true;
            if (unknown && !unresolved) entry.hidden = true;
            regenerateButton.textContent = unknown ? '已核对用量，重新生成' : '重新生成';
            regenerateButton.hidden = !hasImage && !unknown;
            editButton.disabled = blocked || unresolved;
            if (!hasImage) form.hidden = true;
            more.hidden = !hasImage && !unknown;
            if (unknown && !hasImage) more.open = true;
            refreshButton.disabled = state.loading;
            root.setAttribute('aria-busy', busy() ? 'true' : 'false');
            renderProgress();
        }
        function renderProgress() {
            const working = busy();
            progressPanel.hidden = !working;
            if (!working) {
                if (state.progressTimer !== null) global.clearInterval(state.progressTimer);
                state.progressTimer = null;
                return;
            }
            const job = state.active || {};
            const phase = job.status || 'queued';
            const index = phase === 'generating' ? 1 : 0;
            const detail = job.progress || {};
            const count = Number(detail.completed_chunks), total = Number(detail.total_chunks);
            const counted = phase === 'planning' && detail.phase === 'reading'
                && Number.isInteger(count) && Number.isInteger(total) && total > 1 && count >= 0 && count <= total;
            const titles = { queued: '等待开始', planning: '正在整理内容', generating: '正在绘制图解' };
            const title = state.submitting ? '正在开始生成' : titles[phase] || '正在生成图解';
            // Do not repeatedly announce the same stage or the elapsed clock.
            if (progressTitle.textContent !== title) progressTitle.textContent = title;
            const started = Date.parse(job.created_at || state.submissionStarted || '');
            const seconds = Number.isFinite(started) ? Math.max(0, Math.floor((Date.now() - started) / 1000)) : 0;
            elapsed.textContent = seconds < 60 ? `已用 ${seconds} 秒` : `已用 ${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`;
            const heartbeat = Date.parse(job.updated_at || '');
            const stale = Number.isFinite(heartbeat) && Date.now() - heartbeat > 90000;
            const paused = state.progressPaused || stale;
            progressPanel.dataset.paused = paused ? 'true' : 'false';
            progressPanel.dataset.compact = state.selected ? 'true' : 'false';
            const descriptions = {
                queued: '请求已保存，等待处理',
                planning: detail.phase === 'composing' ? '全文已读完，正在组织画面重点' : counted ? `已读 ${count} / ${total} 段` : '梳理重点与内容之间的关系',
                generating: '正在把重点与关系绘制成图片',
            };
            progressDetail.textContent = paused ? '等待进度更新' : descriptions[phase] || '';
            steps.forEach((step, position) => {
                step.dataset.state = position < index ? 'done' : position === index ? 'current' : 'pending';
                if (position === index) step.setAttribute('aria-current', 'step');
                else step.removeAttribute('aria-current');
            });
            progressTrack.setAttribute('aria-label', counted ? '原文读取进度' : title);
            progressTrack.dataset.mode = counted ? 'determinate' : 'indeterminate';
            if (counted) {
                progressTrack.setAttribute('aria-valuemin', '0');
                progressTrack.setAttribute('aria-valuemax', String(total));
                progressTrack.setAttribute('aria-valuenow', String(count));
                progressTrack.setAttribute('aria-valuetext', `已读 ${count} / ${total} 段`);
                progressFill.style.transform = `scaleX(${count / total})`;
            } else {
                ['aria-valuemin', 'aria-valuemax', 'aria-valuenow', 'aria-valuetext'].forEach(name => progressTrack.removeAttribute(name));
                progressFill.style.transform = '';
            }
            progressHint.hidden = seconds < 20 || Boolean(state.selected) || !job.id;
            if (state.progressTimer === null) state.progressTimer = global.setInterval(renderProgress, 1000);
        }
        function setStatus(message, kind) {
            status.textContent = message;
            status.dataset.kind = kind || '';
            statusArea.hidden = !message || kind === 'working';
            refreshButton.hidden = kind !== 'error' && kind !== 'waiting';
        }
        function sourceLink(ref, label) {
            // Calibrated text can have different line identities from the raw study transcript.
            if (ref && ref.source_kind === 'calibrated') {
                const link = node('a', 'idg-source-link', label || '查看校对原文');
                const excerpt = String(ref.excerpt || '').slice(0, 100);
                link.href = `/view/${encodeURIComponent(viewToken)}#calibrated-section${excerpt ? ':~:text=' + encodeURIComponent(excerpt) : ''}`;
                return link;
            }
            const params = new URLSearchParams();
            if (ref && ref.line_id) params.set('visual_line_id', ref.line_id);
            if (ref && Number.isInteger(ref.paragraph_index)) params.set('visual_paragraph', String(ref.paragraph_index));
            if (ref && ref.start_seconds !== null && ref.start_seconds !== undefined && Number.isFinite(Number(ref.start_seconds))) {
                params.set('visual_start', String(ref.start_seconds));
            }
            const link = node('a', 'idg-source-link', label || '查看原文');
            link.href = `/study/${encodeURIComponent(viewToken)}${params.size ? '?' + params.toString() : ''}`;
            return link;
        }
        function renderSourceNotes(job) {
            sourceNotes.replaceChildren();
            const refs = (job && job.source_refs) || [];
            sourceNotes.hidden = !job;
            if (!job) return;
            sourceNotes.append(node('summary', '', refs.length ? `对照原文 · ${refs.length} 处依据` : '对照原文'));
            if (!refs.length) { sourceNotes.append(sourceLink(null, '打开原文与文字解读')); return; }
            const list = node('ol');
            refs.forEach((ref) => {
                const item = node('li');
                item.append(sourceLink(ref, ref.id ? `查看依据 ${ref.id}` : '查看原文位置'));
                if (ref.excerpt) item.append(node('p', '', String(ref.excerpt).slice(0, 500)));
                list.append(item);
            });
            sourceNotes.append(list);
        }
        function choose(job) {
            state.selected = job && job.image_url ? job : null;
            if (!state.selected) {
                imageButton.hidden = true; resultBar.hidden = true;
                sourceNotes.hidden = true; updateControls(); return;
            }
            const sourceURL = privateImageURL(state.selected.image_url);
            if (!sourceURL) {
                setStatus('图片地址暂不可用，请刷新状态', 'error');
                return;
            }
            if (image.getAttribute('src') !== sourceURL) image.src = sourceURL;
            image.alt = state.selected.section_title ? `${state.selected.section_title}的内容图解` : '整篇内容的 AI 图解';
            imageButton.hidden = false; resultBar.hidden = false;
            const downloadURL = privateImageURL(state.selected.download_url || state.selected.image_url);
            download.href = downloadURL;
            download.hidden = !downloadURL;
            resultMeta.textContent = [state.selected.section_title || '整篇总览', timeLabel(state.selected.created_at), state.selected.stale ? '原文已更新' : ''].filter(Boolean).join(' · ');
            historySelect.value = state.selected.id;
            renderSourceNotes(state.selected);
            updateControls();
        }
        function renderVersions() {
            const old = historySelect.value;
            historySelect.replaceChildren();
            state.versions.forEach((job, index) => {
                const label = `第 ${state.versions.length - index} 版 · ${job.section_title || '整篇总览'} · ${LABELS[job.status] || job.status} · ${timeLabel(job.created_at)}`;
                const option = new Option(label, job.id);
                option.disabled = !job.image_url;
                historySelect.append(option);
            });
            historyField.hidden = state.versions.length < 2;
            if (state.selected) historySelect.value = state.selected.id;
            else if (old) historySelect.value = old;
        }
        function consumeJob(job, selectNew) {
            job = normalizeJob(job);
            if (!job || !job.id) return;
            const index = state.versions.findIndex((value) => value.id === job.id);
            if (index >= 0) state.versions[index] = job;
            else state.versions.unshift(job);
            state.active = ACTIVE.has(job.status) ? job : null;
            state.progressPaused = false;
            if (job.image_url && (selectNew || !state.selected || state.selected.id === job.id)) choose(job);
            renderVersions();
            if (job.status === 'unknown') {
                setStatus('请求已发出，但结果尚未确认。请先检查 OpenAI 用量；系统不会自动重发。点击“已核对用量，重新生成”会创建新的付费请求。原有图片仍可查看。', 'error');
            } else if (job.status === 'failed') {
                setStatus(job.error_message || '本次未生成新图，原有图片仍可查看。检查原因后可手动重新生成。', 'error');
            } else {
                setStatus(ACTIVE.has(job.status) ? LABELS[job.stage] || LABELS[job.status] : '', ACTIVE.has(job.status) ? 'working' : '');
            }
            updateControls();
            if (state.active) schedulePoll(state.active.id);
        }
        function schedulePoll(id) {
            global.clearTimeout(state.timer);
            state.timer = global.setTimeout(async () => {
                if (state.destroyed) return;
                try {
                    const data = await apiJSON(`/api/image-diagrams/jobs/${encodeURIComponent(id)}`);
                    if (!state.destroyed) consumeJob(data.job || data, true);
                } catch (error) {
                    if (state.destroyed) return;
                    state.progressPaused = true;
                    renderProgress();
                    setStatus('进度暂时无法读取，生成任务不会因此重新提交。可点击“刷新状态”继续查看。', 'error');
                    // A failed progress read never becomes another paid submission.
                    state.timer = null;
                }
            }, 2500);
        }
        async function refresh() {
            if (state.destroyed || state.loading) return;
            state.loading = true;
            const serial = ++state.refreshSerial;
            updateControls();
            try {
                const data = await apiJSON(base);
                if (state.destroyed || serial !== state.refreshSerial) return;
                state.loaded = true;
                state.authRequired = false;
                refreshButton.textContent = '刷新状态';
                state.enabled = Boolean(data.enabled);
                state.sourceReady = data.source_ready !== false;
                state.versions = (data.versions || []).map(normalizeJob);
                const selected = state.selected && state.versions.find((job) => job.id === state.selected.id);
                choose(selected || state.versions.find((job) => job.image_url));
                renderVersions();
                const active = normalizeJob(data.active_job) || state.versions.find((job) => ACTIVE.has(job.status));
                state.active = null;
                if (active) consumeJob(active, false);
                else if (!state.sourceReady) setStatus(data.source_message || '原文准备中', 'waiting');
                else if (!state.enabled) setStatus(data.disabled_reason || '图解服务尚未配置', 'waiting');
                else {
                    const latest = state.versions[0];
                    if (latest && ['failed', 'unknown'].includes(latest.status)) consumeJob(latest, false);
                    else setStatus('');
                }
            } catch (error) {
                if (state.destroyed) return;
                state.authRequired = error.status === 401;
                if (state.authRequired) refreshButton.textContent = '连接并刷新';
                const message = state.authRequired ? '连接后可查看已有图解和生成新图片。'
                    : error.status === 404 || error.status === 405
                    ? '图解接口尚未加载，请启动更新后的服务，再刷新状态。'
                    : error.message || '暂时无法读取图解，请刷新状态重试';
                setStatus(message, 'error');
            } finally {
                if (!state.destroyed) { state.loading = false; updateControls(); }
            }
        }
        async function submit(kind) {
            if (busy() || !state.loaded || !state.enabled || !state.sourceReady || state.destroyed) return;
            if (kind === 'revise' && !instructions.value.trim()) {
                setStatus('请先填写这张图需要修改的地方。', 'error');
                instructions.focus(); return;
            }
            if (global.LearnFluxAuth && !global.LearnFluxAuth.getTokenPlaceholder()) {
                try { await global.LearnFluxAuth.requireSession({ title: '连接后生成图解', reason: '连接后继续本次生成，已填写的要求会保留。' }); }
                catch (_) { return; }
            }
            if (busy() || state.destroyed) return;
            const selected = state.selected;
            const useSelected = kind !== 'generate' && selected;
            const payload = state.pendingSubmission || {
                scope: useSelected ? selected.scope : 'overview',
                section_id: useSelected ? selected.section_id || null : null,
                style: useSelected ? selected.style || 'warm-guide' : 'warm-guide',
                instructions: kind === 'revise' ? instructions.value.trim() : '',
                revision_of: kind === 'revise' && selected ? selected.id : null,
                request_id: uuid(), regenerate: kind === 'regenerate',
            };
            state.pendingSubmission = payload;
            state.submitting = true;
            state.submissionStarted = new Date().toISOString();
            setStatus('正在提交本次图解生成…', 'working');
            updateControls();
            try {
                const data = await apiJSON(`${base}/generate`, { method: 'POST', body: JSON.stringify(payload) });
                if (state.destroyed) return;
                state.pendingSubmission = null;
                form.hidden = true;
                editButton.setAttribute('aria-expanded', 'false');
                consumeJob(data.job || data, true);
            } catch (error) {
                if (state.destroyed) return;
                if (error.status && error.status < 500) state.pendingSubmission = null;
                setStatus(state.pendingSubmission
                    ? '提交结果尚未确认。点击“确认上次请求”会沿用同一次请求标识，避免重复生成。也可先刷新状态。'
                    : error.message || '请求未完成，请检查后重试', 'error');
            } finally {
                if (!state.destroyed) { state.submitting = false; updateControls(); }
            }
        }
        function openZoom() {
            if (!state.selected) return;
            zoomImage.src = privateImageURL(state.selected.image_url);
            zoomImage.alt = image.alt;
            zoomStage.dataset.zoom = global.innerWidth <= 600 ? 'actual' : 'fit';
            zoomToggle.textContent = zoomStage.dataset.zoom === 'actual' ? '适应屏幕' : '原始尺寸';
            state.dialogTrigger = document.activeElement;
            if (typeof dialog.showModal === 'function') dialog.showModal();
            else { dialog.setAttribute('open', ''); closeButton.focus(); }
        }
        historySelect.addEventListener('change', () => choose(state.versions.find((job) => job.id === historySelect.value)));
        image.addEventListener('error', () => setStatus('图片暂时无法加载，请刷新状态。已生成的图片不会重新提交。', 'error'));
        const controller = {
            refresh,
            destroy() {
                state.destroyed = true;
                ++state.refreshSerial;
                global.clearTimeout(state.timer);
                if (state.progressTimer !== null) global.clearInterval(state.progressTimer);
                if (progressObserver) progressObserver.disconnect();
                if (document.removeEventListener) document.removeEventListener('visibilitychange', syncProgressVisibility);
                if (dialog.open) dialog.close();
                mounts.delete(container);
            },
        };
        mounts.set(container, controller);
        updateControls();
        refresh();
        return controller;
    }
    global.ImageDiagrams = { mount, statusLabel: (value) => LABELS[value] || value };
})(window);
