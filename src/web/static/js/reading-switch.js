(function () {
    'use strict';

    const panel = document.getElementById('readingSwitch');
    const trigger = document.getElementById('readingSwitchTrigger');
    const floating = document.getElementById('readingSwitchFloating');
    if (!panel || !trigger || !floating) return;

    const input = document.getElementById('readingSwitchQuery');
    const message = document.getElementById('readingSwitchMessage');
    const retry = document.getElementById('readingSwitchRetry');
    const results = document.getElementById('readingSwitchResults');
    const mobile = window.matchMedia('(max-width: 720px)');
    const header = trigger.closest('.result-header');
    const topbar = document.querySelector('.topbar');
    const auth = window.LearnFluxAuth;
    let anchor = trigger;
    let request;
    let searchTimer;
    let readingY;
    let topbarHeight = 0;

    const isOpen = () => panel.matches(':popover-open');
    const stateKey = 'learnFluxReadingSwitch';

    function status(text = '', action = '') {
        message.textContent = text;
        retry.textContent = action;
        retry.hidden = !action;
    }

    function addGroup(label, items) {
        if (!items.length) return;
        const group = document.createElement('section');
        group.className = 'reading-switch-group';
        const heading = document.createElement('h3');
        heading.textContent = label;
        group.append(heading);
        for (const item of items) {
            const link = document.createElement('a');
            link.className = 'reading-switch-row';
            link.href = '/view/' + encodeURIComponent(item.view_token);
            const copy = document.createElement('span');
            copy.className = 'reading-switch-copy';
            copy.textContent = item.title;
            if (item.author) {
                const author = document.createElement('small');
                author.className = 'reading-switch-meta';
                author.textContent = item.author;
                copy.append(author);
            }
            const meta = document.createElement('span');
            meta.className = 'reading-switch-meta';
            if (item.reason) meta.classList.add('reading-switch-reason');
            meta.textContent = item.reason || item.date;
            link.append(copy, meta);
            group.append(link);
        }
        results.append(group);
    }

    function cancelSearch() {
        window.clearTimeout(searchTimer);
        request?.abort();
    }

    function showSignIn() {
        status('连接 LearnFlux 后可以查看你的解读。', '连接 LearnFlux');
    }

    async function load() {
        if (!isOpen()) return;
        cancelSearch();
        results.replaceChildren();
        status('正在查找解读…');
        request = new AbortController();
        const { signal } = request;
        const q = input.value.trim();

        try {
            await auth?.ready;
            if (signal.aborted) return;
            if (auth && !auth.isAuthenticated()) {
                showSignIn();
                return;
            }
            const params = new URLSearchParams({ current: panel.dataset.viewToken, q });
            const response = await fetch('/api/audit/reading-switch?' + params, {
                credentials: 'same-origin', cache: 'no-store', signal
            });
            if (signal.aborted) return;
            if (response.status === 401) {
                showSignIn();
                return;
            }
            if (response.status === 403 || response.status === 404) {
                status('当前账号无法从这篇解读打开学习记录。');
                return;
            }
            if (!response.ok) throw new Error('Reading history unavailable');
            const { data } = await response.json();
            if (signal.aborted) return;

            if (q) {
                status(data.matches.length ? '' : '没有匹配的解读，试试更短的标题或作者名。');
                addGroup('搜索结果', data.matches);
            } else {
                status(data.related.length || data.recent.length ? '' : '还没有其他已完成的解读。');
                addGroup('相关解读', data.related);
                addGroup('最近解读', data.recent);
            }
        } catch (error) {
            if (!signal.aborted) status('暂时无法读取解读，请重试。', '重试');
        }
    }

    function queueSearch() {
        cancelSearch();
        results.replaceChildren();
        status('正在查找解读…');
        searchTimer = window.setTimeout(load, 180);
    }

    function placePanel() {
        const viewport = window.visualViewport;
        if (mobile.matches && viewport) {
            panel.style.setProperty('--switch-viewport-bottom',
                Math.max(0, window.innerHeight - viewport.height - viewport.offsetTop) + 'px');
            panel.style.setProperty('--switch-sheet-height', Math.round(viewport.height * 0.68) + 'px');
            return;
        }
        const active = anchor === trigger && !floating.hidden ? floating : anchor;
        const rect = active.getBoundingClientRect();
        const bottom = active === trigger ? header.getBoundingClientRect().bottom : rect.bottom;
        const top = Math.max(8, Math.min(bottom + 8, window.innerHeight - 170));
        panel.style.setProperty('--switch-top', top + 'px');
        panel.style.setProperty('--switch-right', Math.max(12, window.innerWidth - rect.right) + 'px');
        panel.style.setProperty('--switch-max-height', (window.innerHeight - top - 12) + 'px');
    }

    function updateFloatingSwitch() {
        const visibleTop = mobile.matches ? topbarHeight : 0;
        const hidden = trigger.getBoundingClientRect().bottom > visibleTop;
        if (floating.hidden !== hidden) {
            floating.hidden = hidden;
            if (isOpen()) placePanel();
        }
    }

    if (topbar) {
        new ResizeObserver(() => {
            topbarHeight = topbar.offsetHeight;
            floating.style.setProperty('--reading-topbar-height', topbarHeight + 'px');
            updateFloatingSwitch();
        }).observe(topbar);
    }
    const placeIfOpen = () => { if (isOpen()) placePanel(); };
    window.addEventListener('scroll', updateFloatingSwitch, { passive: true });
    window.addEventListener('resize', () => {
        updateFloatingSwitch();
        placeIfOpen();
    });
    updateFloatingSwitch();
    window.visualViewport?.addEventListener('resize', placeIfOpen);
    window.visualViewport?.addEventListener('scroll', placeIfOpen);
    [trigger, floating].forEach((button) => {
        button.addEventListener('click', () => { anchor = button; });
    });
    panel.addEventListener('beforetoggle', (event) => {
        if (event.newState === 'open') {
            readingY = window.scrollY;
            placePanel();
        }
    });
    panel.addEventListener('toggle', () => {
        trigger.setAttribute('aria-expanded', String(isOpen()));
        floating.setAttribute('aria-expanded', String(isOpen()));
        if (isOpen()) {
            if (!mobile.matches) input.focus({ preventScroll: true });
            void load();
        } else {
            cancelSearch();
        }
    });

    input.addEventListener('input', (event) => { if (!event.isComposing) queueSearch(); });
    input.addEventListener('compositionend', queueSearch);
    input.addEventListener('keydown', (event) => {
        if (event.isComposing) return;
        const first = results.querySelector('a');
        if (event.key === 'ArrowDown' && first) {
            event.preventDefault();
            first.focus();
        } else if (event.key === 'Enter' && first) {
            event.preventDefault();
            first.click();
        }
    });
    retry.addEventListener('click', async () => {
        if (auth && retry.textContent === '连接 LearnFlux') {
            panel.hidePopover();
            try {
                await auth.requireSession({ title: '连接后切换解读', reason: '连接后可查找自己的学习记录。' });
                panel.showPopover();
            } catch (error) {
                if (!auth.isCancellation(error)) {
                    panel.showPopover();
                    status(auth.authErrorMessage(error), '连接 LearnFlux');
                }
            }
            return;
        }
        void load();
    });
    window.addEventListener('learnflux:authchange', () => {
        cancelSearch();
        results.replaceChildren();
        if (isOpen()) void load();
    });

    // Keep normal links and browser history. Record the position on the entry we leave.
    results.addEventListener('click', (event) => {
        if (!event.target.closest('a') || event.button !== 0 ||
            event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        const visual = document.getElementById('transcript-reader-visual');
        history.replaceState({
            ...history.state,
            [stateKey]: { y: readingY, visual: visual?.getAttribute('aria-selected') === 'true' }
        }, '');
        panel.hidePopover();
    });
    window.addEventListener('pageshow', (event) => {
        const navigation = performance.getEntriesByType('navigation')[0];
        const saved = history.state?.[stateKey];
        if (!saved || (!event.persisted && navigation?.type !== 'back_forward')) return;
        const state = { ...history.state };
        delete state[stateKey];
        history.replaceState(state, '');
        if (saved.visual && !event.persisted) document.getElementById('transcript-reader-visual')?.click();
        requestAnimationFrame(() => requestAnimationFrame(() => {
            window.scrollTo({ top: saved.y, behavior: 'instant' });
        }));
    });
})();
