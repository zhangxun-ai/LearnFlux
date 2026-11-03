/* Delivery is a separate state from local parsing; fetch only on result pages. */
(function () {
    'use strict';
    const panel = document.getElementById('feishuDelivery');
    if (!panel?.dataset.taskId) return;
    const label = document.getElementById('feishuDeliveryLabel');
    const detail = document.getElementById('feishuDeliveryDetail');
    const open = document.getElementById('feishuDeliveryOpen');
    const retry = document.getElementById('feishuDeliveryRetry');
    const endpoint = `/api/tasks/${encodeURIComponent(panel.dataset.taskId)}/delivery/feishu`;
    let timer = null;
    let busy = false;
    let generation = 0;
    let controller = null;
    let retryUntil = 0;
    let failureUntil = 0;

    function scheduleNext(state) {
        window.clearTimeout(timer);
        timer = null;
        const now = Date.now();
        if (state === 'done' || state === 'unavailable') {
            retryUntil = 0;
            failureUntil = 0;
            return;
        }
        const deadline = retryUntil || failureUntil;
        const delay = deadline ? (deadline > now ? Math.min(10000, deadline - now) : 0)
            : ['pending', 'syncing', 'verifying'].includes(state) ? 30000 : 0;
        if (delay) timer = window.setTimeout(load, delay);
    }

    function render(data) {
        if (data.state === 'done' || data.state === 'unavailable') retryUntil = 0;
        panel.hidden = data.state === 'unavailable';
        panel.dataset.state = data.state || '';
        label.textContent = data.label || '飞书同步状态待确认';
        detail.textContent = data.message || '';
        open.hidden = true;
        if (data.document_url) {
            try {
                const url = new URL(data.document_url);
                if (url.protocol === 'https:' && (url.hostname === 'feishu.cn' || url.hostname.endsWith('.feishu.cn'))) {
                    open.href = url.href;
                    open.hidden = false;
                }
            } catch (_) { /* Keep invalid external URLs out of the document. */ }
        }
        const waitingForRetry = data.state === 'needs_attention' && retryUntil > Date.now();
        if (waitingForRetry) {
            label.textContent = '已安排重新同步';
            detail.textContent = '后台将核对现有文档后继续处理。';
        }
        retry.hidden = !data.can_retry || waitingForRetry;
        retry.disabled = false;
        retry.textContent = '重试同步';
        scheduleNext(data.state);
    }

    async function load() {
        if (busy || document.hidden) return;
        busy = true;
        const current = generation;
        controller = new AbortController();
        window.clearTimeout(timer);
        try {
            if (window.LearnFluxAuth) await window.LearnFluxAuth.ready;
            if (current !== generation) return;
            const response = await fetch(endpoint, { credentials: 'same-origin', signal: controller.signal });
            if (!response.ok) throw new Error('Delivery status unavailable');
            const payload = await response.json();
            if (current !== generation) return;
            failureUntil = 0;
            render(payload.data || payload);
        } catch (error) {
            if (current !== generation || error.name === 'AbortError') return;
            if (!failureUntil) failureUntil = retryUntil || Date.now() + 90000;
            const willRetry = Math.max(retryUntil, failureUntil) > Date.now();
            if (!panel.hidden) detail.textContent = willRetry
                ? '同步状态暂时无法读取，稍后会再次检查。'
                : '同步状态暂时无法读取，请刷新页面重新检查。';
            scheduleNext('error');
        } finally {
            if (current === generation) {
                busy = false;
                controller = null;
            }
        }
    }

    retry.addEventListener('click', async () => {
        if (busy) return;
        busy = true;
        const current = generation;
        controller = new AbortController();
        window.clearTimeout(timer);
        retry.disabled = true;
        retry.textContent = '正在安排重试…';
        try {
            const response = await fetch(endpoint + '/retry', { method: 'POST', credentials: 'same-origin', signal: controller.signal });
            const payload = await response.json();
            if (current !== generation) return;
            if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : '重试暂时未能安排，请稍后再试。');
            const data = payload.data || payload;
            retryUntil = Date.now() + 90000;
            failureUntil = 0;
            if (data.state) render(data);
            else {
                label.textContent = '已安排重新同步';
                detail.textContent = '后台将核对现有文档后继续处理。';
                scheduleNext('needs_attention');
            }
        } catch (error) {
            if (current !== generation || error.name === 'AbortError') return;
            detail.textContent = error.message || '重试暂时未能安排，请稍后再试。';
        } finally {
            if (current === generation) {
                busy = false;
                controller = null;
                retry.disabled = false;
                retry.textContent = '重试同步';
            }
        }
    });

    window.addEventListener('learnflux:authchange', (event) => {
        generation += 1;
        controller?.abort();
        controller = null;
        busy = false;
        retryUntil = 0;
        failureUntil = 0;
        window.clearTimeout(timer);
        panel.hidden = true;
        label.textContent = '';
        detail.textContent = '';
        open.hidden = true;
        open.removeAttribute('href');
        retry.hidden = true;
        if (event.detail?.authenticated) void load();
    });
    document.addEventListener('visibilitychange', () => { if (!document.hidden) void load(); });
    void load();
})();
