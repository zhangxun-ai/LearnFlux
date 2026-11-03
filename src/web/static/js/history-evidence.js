/* Source-scoped questions reuse the history selection and authenticated session. */
(function () {
    'use strict';
    const panel = document.getElementById('historyEvidence');
    if (!panel) return;
    const form = document.getElementById('historyEvidenceForm');
    const question = document.getElementById('historyEvidenceQuestion');
    const submit = document.getElementById('historyEvidenceSubmit');
    const status = document.getElementById('historyEvidenceStatus');
    const answer = document.getElementById('historyEvidenceAnswer');
    const sources = document.getElementById('historyEvidenceSources');
    let tokens = [];
    let history = [];
    let request = null;
    let revision = 0;

    function textElement(tag, text, className) {
        const node = document.createElement(tag);
        node.textContent = String(text || '');
        if (className) node.className = className;
        return node;
    }

    function appendInline(node, value) {
        String(value).split(/(\*\*[^*]+\*\*)/g).forEach((part) => {
            node.append(part.startsWith('**') && part.endsWith('**')
                ? textElement('strong', part.slice(2, -2)) : document.createTextNode(part));
        });
    }

    function renderAnswer(value) {
        answer.replaceChildren();
        String(value || '').split(/\n\s*\n/).filter(Boolean).forEach((block) => {
            const heading = block.match(/^(#{1,4})\s+(.+)$/);
            const node = document.createElement(heading ? 'h3' : 'p');
            appendInline(node, heading ? heading[2] : block);
            answer.append(node);
        });
    }

    function renderSources(items) {
        sources.replaceChildren();
        if (!Array.isArray(items) || !items.length) return;
        sources.append(textElement('h3', '核对原文'));
        items.forEach((source) => {
            if (!tokens.includes(source.view_token)) return;
            const details = document.createElement('details');
            const passages = Array.isArray(source.passages) ? source.passages : [];
            details.append(textElement('summary', `${source.id || ''} · ${source.title || '未命名资料'} · ${passages.length} 段依据`));
            passages.forEach((passage) => {
                const paragraph = document.createElement('p');
                const link = textElement('a', `${source.id || ''}/${passage.id || ''} · ${passage.label || '查看原文'}`);
                const params = new URLSearchParams();
                if (passage.line_id) params.set('visual_line_id', passage.line_id);
                if (Number.isFinite(passage.start_seconds)) params.set('visual_start', passage.start_seconds);
                link.href = `/study/${encodeURIComponent(source.view_token)}${params.size ? '?' + params : ''}`;
                link.target = '_blank';
                link.rel = 'noopener';
                paragraph.append(link, textElement('span', passage.text || ''));
                details.append(paragraph);
            });
            sources.append(details);
        });
    }

    function reset() {
        revision += 1;
        if (request) request.abort();
        request = null;
        history = [];
        submit.disabled = false;
        submit.textContent = '依据原文回答';
        answer.replaceChildren();
        sources.replaceChildren();
        status.textContent = '';
    }

    window.LearnFluxEvidence = Object.freeze({
        open(selected, items) {
            const next = Array.from(new Set(selected));
            if (next.length < 2 || next.length > 5) return;
            if (JSON.stringify(next) !== JSON.stringify(tokens)) reset();
            tokens = next;
            const titles = next.map((token) => {
                const item = items.find((row) => row.view_token === token);
                return item?.title || '未命名资料';
            });
            document.getElementById('historyEvidenceScope').textContent = `${next.length} 篇资料：${titles.join('、')}`;
            panel.hidden = false;
            panel.scrollIntoView({ block: 'nearest', behavior: 'auto' });
            question.focus({ preventScroll: true });
        },
    });

    document.getElementById('historyEvidenceClose').addEventListener('click', () => {
        panel.hidden = true;
        document.getElementById('compareSelectedBtn').focus();
    });

    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const value = question.value.trim();
        if (!value || submit.disabled) return;
        const current = ++revision;
        request = new AbortController();
        submit.disabled = true;
        submit.textContent = '正在核对原文…';
        status.textContent = '正在查找相关段落，并依据原文组织回答…';
        answer.setAttribute('aria-busy', 'true');
        try {
            if (window.LearnFluxAuth) await window.LearnFluxAuth.ready;
            const response = await fetch('/api/study/compare', {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ view_tokens: tokens, question: value, history: history.slice(-8) }),
                signal: request.signal,
            });
            const payload = await response.json();
            if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : '暂时无法回答，请稍后重试。');
            if (current !== revision) return;
            const data = payload.data || payload;
            renderAnswer(data.answer || '未找到足够依据，请换一个更具体的问题。');
            renderSources(data.sources);
            history.push({ role: 'user', content: value }, { role: 'assistant', content: data.answer || '' });
            status.textContent = '回答仅依据本次选择的资料，可展开下方原文核对。';
        } catch (error) {
            if (error.name !== 'AbortError' && current === revision) status.textContent = error.message || '暂时无法回答，请稍后重试。';
        } finally {
            if (current === revision) {
                submit.disabled = false;
                submit.textContent = '依据原文回答';
                answer.removeAttribute('aria-busy');
                request = null;
            }
        }
    });

    window.addEventListener('learnflux:authchange', () => {
        reset();
        tokens = [];
        panel.hidden = true;
    });
})();
