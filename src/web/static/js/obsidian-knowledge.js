(function () {
    'use strict';

    const openButton = document.getElementById('obsidian-knowledge-open');
    const dialog = document.getElementById('obsidian-knowledge-dialog');
    if (!openButton || !dialog) return;

    const categorySelect = document.getElementById('obsidian-knowledge-category');
    const recommendation = document.getElementById('obsidian-knowledge-recommendation');
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

    function token() {
        if (typeof window.getContentMarkToken === 'function') {
            return window.getContentMarkToken();
        }
        return localStorage.getItem('vta_api_key_persist')
            || sessionStorage.getItem('vta_api_key')
            || localStorage.getItem('api_key')
            || '';
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
        categorySelect.disabled = next;
        applyButton.disabled = next || !categorySelect.value;
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

    async function openKnowledgeDialog() {
        setMessage('正在读取分类与同步状态…');
        recommendation.textContent = '正在生成分类建议…';
        dialog.showModal();
        setLoading(true);
        try {
            const [categoriesData, bindingData, recommendationData] = await Promise.all([
                apiJSON('/api/obsidian/knowledge/categories'),
                apiJSON(`${baseUrl}/binding`),
                apiJSON(`${baseUrl}/recommend-category`, { method: 'POST' })
            ]);
            categorySelect.replaceChildren();
            (categoriesData.items || []).forEach((category) => {
                const option = window.document.createElement('option');
                option.value = category;
                option.textContent = category;
                categorySelect.append(option);
            });
            binding = bindingData.binding || null;
            const suggested = binding && binding.category
                ? binding.category
                : recommendationData.category;
            if (suggested) categorySelect.value = suggested;
            recommendation.textContent = recommendationData.category
                ? `AI 建议：${recommendationData.category}（${recommendationData.reason || '可手动修改'}）`
                : '未能生成建议，请手动选择分类。';
            setMessage(
                categorySelect.options.length
                    ? '请选择分类，然后直接同步到 Obsidian。'
                    : 'raw 下没有可用的一级分类，请先在 Vault 中创建分类目录。',
                categorySelect.options.length ? '' : 'error'
            );
        } catch (error) {
            setMessage(`加载失败：${error.message}。请检查 Obsidian 配置和登录状态。`, 'error');
        } finally {
            setLoading(false);
        }
    }

    async function ensureBinding() {
        const category = categorySelect.value;
        if (!category) throw new Error('请选择一级分类');
        if (binding && binding.category === category) return binding;
        const data = await apiJSON(`${baseUrl}/binding`, {
            method: 'PUT',
            body: JSON.stringify({
                category,
                collection_directory: '',
                expected_revision: binding ? binding.revision : null
            })
        });
        binding = data.binding;
        return binding;
    }

    async function syncKnowledgeToObsidian() {
        setLoading(true);
        applyButton.textContent = '同步中…';
        setMessage('正在同步到 Obsidian…');
        try {
            await ensureBinding();
            const previewData = await apiJSON(`${baseUrl}/preview`, {
                method: 'POST',
                body: JSON.stringify({ force: false })
            });
            const data = await apiJSON(`${baseUrl}/apply`, {
                method: 'POST',
                body: JSON.stringify({
                    expected_binding_revision: previewData.binding_revision,
                    preconditions: previewData.preconditions,
                    force: Boolean(previewData.force)
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
            showSyncNotice('success', '同步成功', '原文与 AI 解读已写入 Obsidian。');
        } catch (error) {
            if (error.status === 409 && error.code === 'stale_preview') {
                setMessage('内容或 Obsidian 文件刚刚发生变化，请重新同步。', 'warning');
                showSyncNotice('error', '同步未完成', '内容刚刚发生变化，请重新同步。');
            } else {
                setMessage(`同步失败：${error.message}`, 'error');
                showSyncNotice('error', '同步失败', error.message || '请稍后重试。');
            }
        } finally {
            applyButton.textContent = '同步到 Obsidian';
            setLoading(false);
        }
    }

    openButton.addEventListener('click', openKnowledgeDialog);
    applyButton.addEventListener('click', syncKnowledgeToObsidian);
    categorySelect.addEventListener('change', () => {
        applyButton.disabled = loading || !categorySelect.value;
        setMessage('分类已变化，点击同步后将保存并写入 Obsidian。');
    });
})();
