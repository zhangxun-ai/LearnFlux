(function () {
    'use strict';

    const openButton = document.getElementById('obsidian-knowledge-open');
    const dialog = document.getElementById('obsidian-knowledge-dialog');
    if (!openButton || !dialog) return;

    const categorySelect = document.getElementById('obsidian-knowledge-category');
    const recommendation = document.getElementById('obsidian-knowledge-recommendation');
    const sourceAccess = document.getElementById('obsidian-knowledge-source-access');
    const message = document.getElementById('obsidian-knowledge-message');
    const previewList = document.getElementById('obsidian-knowledge-preview-list');
    const previewButton = document.getElementById('obsidian-knowledge-preview');
    const applyButton = document.getElementById('obsidian-knowledge-apply');
    const viewToken = openButton.dataset.viewToken || '';
    const baseUrl = `/api/obsidian/knowledge/single/${encodeURIComponent(viewToken)}`;

    let binding = null;
    let preview = null;
    let loading = false;

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
        previewButton.disabled = next || !categorySelect.value;
        applyButton.disabled = next || !preview;
    }

    function setMessage(text, tone) {
        message.textContent = text || '';
        message.dataset.tone = tone || '';
    }

    function clearPreview() {
        preview = null;
        previewList.replaceChildren();
        sourceAccess.textContent = '尚未生成预览';
        applyButton.disabled = true;
        applyButton.textContent = '确认同步';
    }

    function stateLabel(state) {
        return {
            new: '新建',
            unchanged: '无变化',
            changed: 'LearnFlux 内容已更新',
            externally_modified: 'Obsidian 中有修改',
            relocated: '已恢复重命名文件'
        }[state] || state;
    }

    function renderPreview(data) {
        preview = data;
        previewList.replaceChildren();
        const item = (data.items || [])[0] || {};
        sourceAccess.textContent = item.source_access || '来源路径不可用';
        let overwritesExternal = false;
        (item.documents || []).forEach((previewDocument) => {
            const card = window.document.createElement('article');
            card.className = 'obsidian-knowledge-document';
            card.dataset.state = previewDocument.state;
            const heading = window.document.createElement('div');
            heading.className = 'obsidian-knowledge-document-head';
            const title = window.document.createElement('strong');
            const pathText = String(previewDocument.relative_path || '');
            const isCollectionIndex = pathText.includes('00-合集总览');
            title.textContent = isCollectionIndex
                ? (previewDocument.document_type === 'raw' ? '合集总览（目录）' : '合集总览（主线）')
                : (previewDocument.document_type === 'raw' ? '原材料' : 'AI 解读');
            const badge = window.document.createElement('span');
            badge.textContent = stateLabel(previewDocument.state);
            heading.append(title, badge);
            const path = window.document.createElement('code');
            path.textContent = previewDocument.relative_path;
            const diff = window.document.createElement('pre');
            diff.textContent = previewDocument.diff || '内容无变化';
            card.append(heading, path, diff);
            previewList.append(card);
            overwritesExternal = overwritesExternal
                || previewDocument.state === 'externally_modified';
        });
        applyButton.textContent = overwritesExternal
            ? '覆盖 Obsidian 中的修改'
            : '确认同步';
        applyButton.disabled = false;
        setMessage('预览已生成。请核对两个目标路径后确认。', 'success');
    }

    async function openKnowledgeDialog() {
        clearPreview();
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
                    ? '请选择分类，然后生成同步预览。'
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

    async function generatePreview() {
        setLoading(true);
        clearPreview();
        setMessage('正在生成同步预览…');
        try {
            await ensureBinding();
            const data = await apiJSON(`${baseUrl}/preview`, {
                method: 'POST',
                body: JSON.stringify({ force: false })
            });
            renderPreview(data);
        } catch (error) {
            setMessage(`预览失败：${error.message}`, 'error');
        } finally {
            setLoading(false);
        }
    }

    async function refreshPreviewAfterStale(error) {
        const latest = error.latestPreview || await apiJSON(`${baseUrl}/preview`, {
            method: 'POST',
            body: JSON.stringify({ force: false })
        });
        renderPreview(latest);
        setMessage('内容或 Obsidian 文件在确认前发生变化，预览已刷新，请重新确认。', 'warning');
    }

    async function applyPreview() {
        if (!preview) return;
        setLoading(true);
        setMessage('正在写入 Obsidian…');
        try {
            const data = await apiJSON(`${baseUrl}/apply`, {
                method: 'POST',
                body: JSON.stringify({
                    expected_binding_revision: preview.binding_revision,
                    preconditions: preview.preconditions,
                    force: Boolean(preview.force)
                })
            });
            const results = (data.items || []).flatMap((item) => item.documents || []);
            results.forEach((result) => {
                const row = window.document.createElement('p');
                row.className = 'obsidian-knowledge-result';
                row.dataset.status = result.status;
                row.textContent = `${result.document_type}: ${result.relative_path} — ${result.status}`;
                previewList.append(row);
            });
            setMessage(
                data.counts && data.counts.failed
                    ? '部分文件同步失败，可重新生成预览后安全重试。'
                    : '已完成同步。',
                data.counts && data.counts.failed ? 'warning' : 'success'
            );
            preview = null;
            applyButton.disabled = true;
        } catch (error) {
            if (error.status === 409 && error.code === 'stale_preview') {
                await refreshPreviewAfterStale(error);
            } else {
                setMessage(`同步失败：${error.message}`, 'error');
            }
        } finally {
            setLoading(false);
        }
    }

    openButton.addEventListener('click', openKnowledgeDialog);
    previewButton.addEventListener('click', generatePreview);
    applyButton.addEventListener('click', applyPreview);
    categorySelect.addEventListener('change', () => {
        clearPreview();
        setMessage('分类已变化，请重新生成预览。');
    });
})();
