(function () {
    'use strict';

    const openButton = document.getElementById('obsidian-knowledge-open');
    const dialog = document.getElementById('obsidian-knowledge-dialog');
    if (!openButton || !dialog) return;

    const directory = document.getElementById('obsidian-knowledge-directory');
    const directories = document.getElementById('obsidian-knowledge-directories');
    const refresh = document.getElementById('obsidian-knowledge-refresh');
    const conflicts = document.getElementById('obsidian-knowledge-conflicts');
    const contentOptions = Array.from(document.querySelectorAll('input[name="obsidian-knowledge-type"]'));
    const message = document.getElementById('obsidian-knowledge-message');
    const applyButton = document.getElementById('obsidian-knowledge-apply');
    const notice = document.getElementById('obsidian-knowledge-notice');
    const noticeTitle = document.getElementById('obsidian-knowledge-notice-title');
    const noticeDetail = document.getElementById('obsidian-knowledge-notice-detail');
    const viewToken = openButton.dataset.viewToken || '';
    const baseUrl = `/api/obsidian/knowledge/single/${encodeURIComponent(viewToken)}`;

    let binding = null;
    let loading = false;
    let noticeTimer = null;
    let directoriesReady = false;
    let pendingPreview = null;

    function documentTypes() { return contentOptions.filter(input => input.checked).map(input => input.value); }

    function invalidatePreview() {
        pendingPreview = null;
        conflicts.hidden = true;
        conflicts.textContent = '';
        applyButton.textContent = '同步到 Obsidian';
        setLoading(loading);
    }

    function token() {
        if (typeof window.getContentMarkToken === 'function') {
            return window.getContentMarkToken();
        }
        return window.LearnFluxAuth
            ? window.LearnFluxAuth.getTokenPlaceholder()
            : '';
    }

    async function apiJSON(url, options) {
        const accessToken = token();
        if (!accessToken) throw new Error('请先在工作台设置 API 令牌');
        const init = options || {};
        const headers = new Headers(init.headers || {});
        headers.set('Authorization', `Bearer ${accessToken}`);
        if (init.body) headers.set('Content-Type', 'application/json');
        const response = await fetch(url, { ...init, headers });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
            const detail = payload.detail || {};
            const error = new Error(detail.code || payload.message || `HTTP ${response.status}`);
            error.status = response.status;
            error.code = detail.code || '';
            error.latestPreview = detail.latest_preview || null;
            throw error;
        }
        return payload.data || {};
    }

    function setLoading(next) {
        loading = next;
        openButton.disabled = next;
        dialog.querySelectorAll('input, button').forEach(control => { control.disabled = next; });
        applyButton.disabled = next || !directoriesReady || !documentTypes().length;
    }

    function setMessage(text, tone) {
        message.textContent = text || '';
        message.dataset.tone = tone || '';
    }

    function showSyncNotice(tone, title, detail) {
        window.clearTimeout(noticeTimer);
        notice.dataset.tone = tone;
        noticeTitle.textContent = title;
        noticeDetail.textContent = detail;
        notice.hidden = false;
        if (typeof notice.showPopover === 'function') {
            if (notice.matches(':popover-open')) notice.hidePopover();
            notice.showPopover();
        }
        noticeTimer = window.setTimeout(() => {
            if (typeof notice.hidePopover === 'function' && notice.matches(':popover-open')) {
                notice.hidePopover();
            }
            notice.hidden = true;
        }, 3600);
    }

    async function loadDirectories(preserve = false) {
        const previousDirectory = directory.value;
        directoriesReady = false;
        directories.replaceChildren();
        directory.value = '';
        const data = await apiJSON('/api/obsidian/directories?root=vault', { cache: 'no-store' });
        if (data.knowledge_sync_version !== 2) {
            throw new Error('Obsidian 同步功能已更新，请重启 LearnFlux 服务后刷新页面。');
        }
        (data.items || []).forEach(path => {
            const option = document.createElement('option');
            option.value = path;
            directories.append(option);
        });
        directoriesReady = true;
        if (preserve) directory.value = previousDirectory;
        else if ((data.items || []).includes('03-知识')) directory.value = '03-知识';
    }

    async function openKnowledgeDialog() {
        if (loading) return;
        invalidatePreview();
        binding = null;
        setMessage('正在读取知识库目录…');
        dialog.showModal();
        setLoading(true);
        try {
            const [bindingData] = await Promise.all([apiJSON(`${baseUrl}/binding`), loadDirectories()]);
            binding = bindingData.binding || null;
            setMessage('选择已有目录或输入完整路径；留空为知识库根目录。');
        } catch (error) {
            directoriesReady = false;
            directories.replaceChildren();
            directory.value = '';
            setMessage(`加载失败：${error.message}。请刷新目录后重试。`, 'error');
        } finally { setLoading(false); }
    }

    async function ensureBinding() {
        if (binding) return binding;
        const data = await apiJSON(`${baseUrl}/binding`, {
            method: 'PUT',
            body: JSON.stringify({ category: '知识', collection_directory: '', expected_revision: null })
        });
        binding = data.binding;
        return binding;
    }

    async function syncKnowledgeToObsidian() {
        if (loading || !directoriesReady || !documentTypes().length) return;
        setLoading(true);
        applyButton.textContent = '同步中…';
        setMessage('正在同步到 Obsidian…');
        try {
            await ensureBinding();
            const request = { target_directory: directory.value.trim(), document_types: documentTypes(), force: false };
            const confirmedConflict = Boolean(pendingPreview);
            const previewData = pendingPreview || await apiJSON(`${baseUrl}/preview`, {
                method: 'POST', body: JSON.stringify(request)
            });
            const changed = (previewData.items || []).flatMap(item => item.documents || []).filter(doc => doc.state === 'externally_modified');
            if (changed.length && !confirmedConflict) {
                pendingPreview = previewData;
                conflicts.hidden = false;
                conflicts.textContent = changed.map(doc => `${doc.relative_path}\n${doc.diff || '此文件已在 Obsidian 中修改'}`).join('\n\n');
                setMessage('检测到 Obsidian 中的修改。请核对差异，再点击覆盖；也可选择其他目录保留原文件。', 'warning');
                return;
            }
            if (!(previewData.preconditions || []).length) {
                setMessage('所选内容尚未生成，请先生成 AI 总结或逐字稿。', 'warning');
                return;
            }
            const data = await apiJSON(`${baseUrl}/apply`, {
                method: 'POST',
                body: JSON.stringify({
                    ...request,
                    expected_binding_revision: previewData.binding_revision,
                    preconditions: previewData.preconditions,
                    force: confirmedConflict || Boolean(previewData.force)
                })
            });
            if (data.counts && data.counts.failed) {
                setMessage('部分文件同步失败，请重试。', 'warning');
                showSyncNotice(
                    'error',
                    '同步未完成',
                    `有 ${data.counts.failed} 个文件未能写入，请检查后重试。`
                );
                return;
            }
            dialog.close();
            showSyncNotice('success', '同步成功', '所选内容已写入 Obsidian。');
        } catch (error) {
            pendingPreview = null;
            conflicts.hidden = true;
            if (error.status === 409 && error.code === 'stale_preview') {
                setMessage('内容或 Obsidian 文件刚刚发生变化，请重新同步。', 'warning');
                showSyncNotice('error', '同步未完成', '内容刚刚发生变化，请重新同步。');
            } else {
                setMessage(`同步失败：${error.message}`, 'error');
                showSyncNotice('error', '同步失败', error.message || '请稍后重试。');
            }
        } finally {
            applyButton.textContent = pendingPreview ? '覆盖 Obsidian 中的修改' : '同步到 Obsidian';
            setLoading(false);
        }
    }

    dialog.addEventListener('cancel', event => { if (loading) event.preventDefault(); });
    openButton.addEventListener('click', openKnowledgeDialog);
    applyButton.addEventListener('click', syncKnowledgeToObsidian);
    directory.addEventListener('input', invalidatePreview);
    contentOptions.forEach(input => input.addEventListener('change', invalidatePreview));
    refresh.addEventListener('click', async () => {
        if (loading) return;
        invalidatePreview();
        setLoading(true);
        try {
            await loadDirectories(true);
            const exists = !directory.value || directories.children && Array.from(directories.children).some(option => option.value === directory.value);
            setMessage(exists ? '目录已刷新，已保留所选目录。' : '目录已刷新，当前路径不存在，同步时将创建。请核对目标路径。');
        } catch (error) { setMessage(`目录刷新失败：${error.message}`, 'error'); }
        finally { setLoading(false); }
    });
})();
