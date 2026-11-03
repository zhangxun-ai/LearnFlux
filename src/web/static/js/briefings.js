(function () {
    'use strict';
    var auth = window.LearnFluxAuth;
    var el = function (id) { return document.getElementById('briefings-' + id); };
    var tabs = Array.from(document.querySelectorAll('[data-briefing-kind]'));
    var query = new URLSearchParams(window.location.search);
    var kind = query.get('kind') === 'wechat' ? 'wechat' : 'ai';
    var initialDate = /^\d{4}-\d{2}-\d{2}$/.test(query.get('date') || '') ? query.get('date') : '';
    var rows = [], warnings = [], destinations = {}, selected = null, preview = null, edition = '';
    var listVersion = 0, selectionVersion = 0, previewVersion = 0;
    var syncing = false, gateCleanup = null, frameObserver = null;
    var successStates = new Set(['done', 'synced', 'unchanged', 'already_synced']);

    function status(message) { el('status').textContent = message || ''; }
    function authenticated() { return Boolean(auth && auth.isAuthenticated()); }
    function base(row) { return '/api/briefings/' + encodeURIComponent(row.kind) + '/' + encodeURIComponent(row.bundle); }
    function closePreview() {
        previewVersion += 1;
        preview = null;
        el('preview-body').textContent = '';
        el('destination').textContent = '';
        el('private-notice').textContent = '';
        el('private-notice').hidden = true;
        el('preview-status').textContent = '';
        el('preview-confirm').disabled = true;
        if (el('preview').open) el('preview').close();
    }
    function clearReport() {
        selectionVersion += 1;
        selected = null;
        closePreview();
        if (frameObserver) frameObserver.disconnect();
        frameObserver = null;
        el('frame').hidden = true;
        el('frame').removeAttribute('src');
        el('frame').src = 'about:blank';
        el('frame').style.height = '';
        el('download').removeAttribute('href');
        el('save-menu').open = false;
        el('report-tools').hidden = true;
    }
    function clearPrivate() {
        listVersion += 1;
        clearReport();
        rows = []; warnings = []; destinations = {}; edition = '';
        el('date').replaceChildren();
        el('date').disabled = true;
        el('warning').textContent = '';
        el('warning').hidden = true;
        el('empty').hidden = true;
        el('workspace').hidden = true;
    }
    function showGate() {
        if (gateCleanup) gateCleanup();
        gateCleanup = null;
        if (!auth) { status('登录组件暂不可用，请刷新工作台。'); return; }
        if (authenticated()) return;
        gateCleanup = auth.renderAuthGate(el('auth'), {
            title: '连接后查看日报',
            reason: '日报仅供当前工作台的本人账户查看。',
            actionLabel: '连接工作台'
        });
    }
    async function request(url, options) {
        var response = await fetch(url, Object.assign({ credentials: 'same-origin', cache: 'no-store' }, options || {}));
        if (response.status === 401 || response.status === 403) {
            clearPrivate();
            showGate();
            var denied = new Error('当前会话无法读取日报，请连接本人账户后重试。');
            denied.denied = true;
            throw denied;
        }
        if (!response.ok) {
            var payload = await response.json().catch(function () { return {}; });
            throw new Error(typeof payload.detail === 'string' ? payload.detail : '请求未完成，请稍后重试。');
        }
        return response;
    }
    function updateButtons() {
        ['obsidian', 'feishu'].forEach(function (destination) {
            var available = Boolean(destinations[destination] && destinations[destination].available);
            el(destination).disabled = syncing || !selected || !available;
            el(destination).title = available ? '' : '工作台尚未配置此同步目标';
        });
        tabs.forEach(function (tab) { tab.disabled = syncing || !authenticated(); });
        el('date').disabled = syncing || !rows.length;
        el('refresh').disabled = syncing;
    }
    function showWarning() {
        var messages = warnings.filter(function (item) { return !item.kind || item.kind === kind; }).map(function (item) { return item.message; }).filter(Boolean);
        el('warning').textContent = messages.join('\n');
        el('warning').hidden = !messages.length;
    }
    async function chooseReport(date) {
        clearReport();
        edition = date || '';
        selected = rows.find(function (row) { return row.kind === kind && row.date === edition; }) || null;
        var row = selected, version = selectionVersion;
        updateButtons();
        if (!row) {
            el('empty').textContent = edition ? '这期' + (kind === 'wechat' ? '微信日报' : 'AI 导游') + '尚未生成。' : '还没有可查看的日报。';
            el('empty').hidden = false; status(''); return;
        }
        el('empty').hidden = true;
        el('report-tools').hidden = false;
        el('download').href = base(row) + '/files/report.md';
        status('正在读取日报…');
        try {
            // Check authorization before exposing the iframe; assets remain relative to its real URL.
            var response = await request(base(row) + '/files/report.html');
            if (response.body && response.body.cancel) await response.body.cancel();
            if (version !== selectionVersion || !authenticated()) return;
            el('frame').src = base(row) + '/files/report.html';
            el('frame').hidden = false;
            status('');
        } catch (error) {
            if (error.denied || version === selectionVersion) status(error.message);
        }
    }
    function showKind(preferredDate) {
        tabs.forEach(function (tab) { tab.setAttribute('aria-pressed', String(tab.dataset.briefingKind === kind)); });
        var options = Array.from(new Set(rows.map(function (row) { return row.date; }))).sort().reverse();
        if (preferredDate && !options.includes(preferredDate)) options.push(preferredDate);
        options.sort().reverse();
        el('date').replaceChildren();
        options.forEach(function (date) {
            var option = document.createElement('option');
            option.value = date;
            option.textContent = date.replace(/^(\d{4})-(\d{2})-(\d{2})$/, '$1 年 $2 月 $3 日');
            el('date').append(option);
        });
        var chosen = options.includes(preferredDate) ? preferredDate : options[0];
        if (chosen) el('date').value = chosen;
        showWarning();
        chooseReport(chosen);
    }
    async function load() {
        if (!authenticated()) { clearPrivate(); showGate(); status('连接本人账户后可查看日报。'); return; }
        var version = ++listVersion, oldDate = edition || initialDate;
        clearReport();
        status('正在检查已生成的日报…');
        if (gateCleanup) gateCleanup();
        gateCleanup = null;
        el('auth').replaceChildren();
        try {
            var data = await (await request('/api/briefings')).json();
            if (version !== listVersion || !authenticated()) return;
            rows = (Array.isArray(data.items) ? data.items : []).filter(function (row) { return ['ai', 'wechat'].includes(row.kind) && typeof row.bundle === 'string' && typeof row.date === 'string'; });
            warnings = Array.isArray(data.warnings) ? data.warnings : [];
            destinations = data.destinations || {};
            el('workspace').hidden = false;
            showKind(oldDate);
        } catch (error) {
            if (error.denied || version === listVersion) status(error.message);
        }
    }
    async function openPreview(destination) {
        if (!selected || syncing) return;
        el('save-menu').open = false;
        closePreview();
        var row = selected, currentSelection = selectionVersion, version = previewVersion;
        status('正在准备同步预览…');
        try {
            var data = await (await request(base(row) + '/preview/' + destination)).json();
            if (version !== previewVersion || currentSelection !== selectionVersion || !authenticated()) return;
            if (typeof data.markdown !== 'string' || !/^[a-f0-9]{64}$/.test(data.content_sha256 || '')) throw new Error('预览内容校验未通过，请刷新日报后重试。');
            preview = { row: row, destination: destination, hash: data.content_sha256, selection: currentSelection };
            el('preview-title').textContent = data.title || '预览同步内容';
            el('destination').textContent = '保存到：' + (data.destination_label || destination);
            el('preview-body').textContent = data.markdown;
            el('private-notice').textContent = data.private_notice || (row.kind === 'wechat' ? '本次同步包含私人聊天摘要。请确认目标空间及可访问的人，再点击确认同步。' : '');
            el('private-notice').hidden = !el('private-notice').textContent;
            el('preview-confirm').disabled = false;
            el('preview').showModal();
            status('');
        } catch (error) {
            if (error.denied || version === previewVersion) status(error.message);
        }
    }
    async function sync() {
        if (!preview || syncing || preview.selection !== selectionVersion) return;
        var value = preview, version = previewVersion;
        syncing = true;
        updateButtons();
        el('preview-confirm').disabled = true;
        el('preview-status').textContent = '正在同步，请稍候…';
        try {
            var result = await (await request(base(value.row) + '/sync/' + value.destination, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content_sha256: value.hash, confirm: true, confirm_private: value.row.kind === 'wechat' })
            })).json();
            if (version !== previewVersion || !authenticated()) return;
            var successful = successStates.has(result.status);
            el('preview-status').textContent = result.label || (successful ? '同步完成。' : '同步尚未确认，请核对目标内容后再处理。');
            if (successful && typeof result.url === 'string') {
                try {
                    var url = new URL(result.url);
                    if (url.protocol === 'https:') {
                        var link = document.createElement('a');
                        link.href = url.href; link.target = '_blank'; link.rel = 'noopener noreferrer'; link.textContent = '打开文档';
                        el('preview-status').append(link);
                    }
                } catch (error) { /* Invalid target links are not rendered. */ }
            }
            // Keep confirmation disabled: another write needs a new, current preview.
        } catch (error) {
            if (error.denied) status(error.message);
            else if (version === previewVersion) el('preview-status').textContent = '同步结果尚未确认。' + error.message + ' 请先核对目标内容，不要连续重复提交。';
        } finally {
            syncing = false;
            updateButtons();
        }
    }
    function sizeFrame() {
        if (!selected || !authenticated() || el('frame').hidden) return;
        try {
            var doc = el('frame').contentDocument;
            if (!doc || !doc.body) return;
            el('frame').style.height = Math.max(520, doc.body.scrollHeight + 2) + 'px';
        } catch (error) { /* External navigation cannot expose its document. */ }
    }
    el('frame').addEventListener('load', function () {
        sizeFrame();
        if (frameObserver) frameObserver.disconnect();
        if (!selected || !authenticated() || el('frame').hidden) return;
        try {
            var doc = el('frame').contentDocument;
            if (doc && doc.body && window.ResizeObserver) {
                frameObserver = new ResizeObserver(sizeFrame);
                frameObserver.observe(doc.body);
            }
        } catch (error) { /* External pages are not inspected. */ }
    });
    tabs.forEach(function (tab) { tab.addEventListener('click', function () { if (syncing) return; kind = tab.dataset.briefingKind; showKind(edition); }); });
    el('date').addEventListener('change', function () { chooseReport(el('date').value); });
    el('refresh').addEventListener('click', load);
    document.addEventListener('click', function (event) { if (!el('save-menu').contains(event.target)) el('save-menu').open = false; });
    document.addEventListener('keydown', function (event) { if (event.key === 'Escape') el('save-menu').open = false; });
    el('download').addEventListener('click', function () { el('save-menu').open = false; });
    ['obsidian', 'feishu'].forEach(function (destination) { el(destination).addEventListener('click', function () { openPreview(destination); }); });
    el('preview-close').addEventListener('click', closePreview);
    el('preview-cancel').addEventListener('click', closePreview);
    el('preview').addEventListener('cancel', function (event) { event.preventDefault(); closePreview(); });
    el('preview-confirm').addEventListener('click', sync);
    window.addEventListener('resize', sizeFrame);
    window.addEventListener('pagehide', clearPrivate);
    window.addEventListener('pageshow', function (event) { if (event.persisted) load(); });
    window.addEventListener('learnflux:authchange', function () {
        clearPrivate();
        if (authenticated()) load();
        else { showGate(); status('已断开连接，日报内容已隐藏。'); }
    });
    if (auth) auth.ready.then(load);
    else showGate();
})();
