(function () {
    'use strict';

    const TOKEN_KEY = 'vta_bearer_token';
    const ENCRYPTION_KEY = 'vta_encrypt_key_2024';
    const DRAFT_PREFIX = 'learnflux_review_draft:';
    const TABS = ['daily', 'weekly', 'monthly', 'annual', 'insights'];
    const TAB_LABELS = {
        daily: '今日复盘', weekly: '周度复盘', monthly: '月度复盘',
        annual: '年度复盘', insights: '内在洞察',
    };
    const TAB_DESCRIPTIONS = {
        daily: '选一件触动你的事，依次写下当时的反应与现在的理解。',
        weekly: '回看七天记录，完成聚焦、连接、抽象与行动实验。',
        monthly: '用内心、行动、结果与备注，留下这个月最重要的内容。',
        annual: '把十二个月放在同一张表里，看见跨越时间的联结。',
        insights: '从枝叶到树干再到根系，逐层整理对自己的认识。',
    };
    const MEANING_LABELS = {
        discovery: '发现', learning: '学习', decision: '决心',
        joy: '快乐', hunch: '预感', '': '暂时没有新的意义', custom: '自定义',
    };
    const EMOTIONS = ['快乐', '信任', '恐惧', '惊讶', '悲伤', '厌恶', '愤怒', '期待', '安心', '困惑', '委屈', '疲惫'];
    const AI_PURPOSES = {
        daily_reframe: '区分事实、感受与现在可控的选择，不强迫积极解释。',
        weekly_focus: '从本周来源中提出最多三个值得你确认的聚焦候选。',
        weekly_connections: '寻找直接、间接或意外连接，并保留每条来源。',
        weekly_abstraction: '从具体事件提出可证伪的枝叶、树干或树根候选。',
        action_experiment: '把你已认可的方向具体化成一个小型验证实验。',
        annual_summary: '基于月度来源提出年度关键词和总结候选。',
        inner_insight: '提出带证据、反例与不确定性的内在洞察候选。',
    };
    const HELP = {
        fact: {
            title: '事实：先写摄像头能拍到的内容',
            body: '只记录发生了什么、谁说了什么、时间地点或可观察结果。先不解释动机，也不急着评价自己。',
            example: '例：会议开始 10 分钟后，我才打开准备好的提纲。',
        },
        meaning: {
            title: '意义：写你现在真正认可的理解',
            body: '意义可以是发现、学习、决断、喜悦或一个尚未证实的直觉。它不必积极，也没有标准答案。',
            example: '例：我并不是不会表达，而是在多人场合需要更明确的开场锚点。',
        },
        past: {
            title: '当时：让原始反应被看见',
            body: '写当时真实的想法、感受、行动与结果。行动和结果没有发生也可以留空。',
            example: '例：我担心被打断，所以先把最重要的话咽了回去。',
        },
        present: {
            title: '现在：换一副眼镜再看一次',
            body: '可以从自己、对方或旁观者视角观察，问“我真正想要什么”“现在还有什么能控制”。不要强迫积极化。',
            example: '例：现在我能做的是提前说出结论，再邀请别人追问。',
        },
        people: {
            title: '人物与关键词：给未来检索留下入口',
            body: '人物写真实称呼或你能辨认的代号；关键词写场景、主题或反复出现的线索。它们只用于组织记录，不代表人物标签。',
            example: '例：人物“产品搭档”；关键词“周会、即兴表达”。',
        },
        expected: {
            title: '预期结果：先写可观察信号',
            body: '描述采取行动后可能看到什么，不把愿望当成已经发生的结果。结果可以不理想，也可以与预期不同。',
            example: '例：我能在开场 30 秒内说出结论，并收到至少一个具体追问。',
        },
        actual: {
            title: '后续实际结果：过几天再回来补也可以',
            body: '记录后来真正发生的事情，用它检验原来的认识。没有执行、结果相反或仍不确定都可以如实写。',
            example: '例：我说出了结论，但仍然紧张；讨论更快进入了具体问题。',
        },
        focus: {
            title: '聚焦：重要不等于事情最大',
            body: '从一周的记录里选 1 到 3 件真正值得继续理解的事。数量可以少，不必为了凑满三件而选择。',
            example: '试着问：哪件小事如果被看懂，会改变我之后的选择？',
        },
        connection: {
            title: '连接：暂时只描述关系',
            body: '直接连接通常时间相近，间接连接跨越场景，意外连接则原本看似无关。先写观察，不把相关性当成因果。',
            example: '例：我在会议前和运动前都出现了同一种拖延，但原因还不确定。',
        },
        abstraction: {
            title: '抽象：从枝叶慢慢走向树根',
            body: 'L1 到 L3 靠近事件，L4 到 L6 关注兴趣、优势与反复模式，L7 到 L8 才触及信念、愿望与固定想法。证据不足时停在较浅层更诚实。',
            example: '例：先写“我在多人讨论前会反复准备”，不要直接跳到人格结论。',
        },
        experiment: {
            title: '行动实验：验证理解，而不是增加待办',
            body: '用 Why、What、Who、When、Where、How 加资源预算和成功信号，把已认可的方向变成小、可逆、可复查的尝试。',
            example: '例：下一次周会前 10 分钟写一句结论，开场 30 秒内说出来。',
        },
    };

    const today = localISODate();
    const initialParams = new URLSearchParams(window.location.search);
    const legacyGuideRequested = /^\/review\/guide\/?$/.test(window.location.pathname)
        || window.location.hash.startsWith('#guide');
    const initialDate = /^\d{4}-\d{2}-\d{2}$/.test(initialParams.get('date') || '') ? initialParams.get('date') : today;
    const initialMonth = /^\d{4}-\d{2}$/.test(initialParams.get('month') || '') ? initialParams.get('month') : initialDate.slice(0, 7);
    const initialYear = /^\d{4}$/.test(initialParams.get('year') || '') ? initialParams.get('year') : initialDate.slice(0, 4);
    const state = {
        tab: initialTab(),
        date: initialDate,
        month: initialMonth,
        year: initialYear,
        preferences: {newbie_mode: true, week_start_day: 0, obsidian_root: '复盘'},
        daily: null,
        weekly: null,
        monthly: null,
        annual: null,
        insights: [],
        insightOverview: null,
        insightSources: [],
        saveTimers: new Map(),
        emotionTarget: null,
        emotionSelection: [],
        draggedFocusId: null,
        aiContext: null,
        toastTimer: null,
        guideRendered: false,
        initialSource: initialParams.get('source_type') && initialParams.get('source_id')
            ? {type: initialParams.get('source_type'), id: initialParams.get('source_id')}
            : null,
    };
    window.LearnFluxReviewState = state;

    const elements = {
        view: document.getElementById('review-view'),
        status: document.getElementById('review-page-status'),
        saveState: document.getElementById('review-save-state'),
        periodControls: document.getElementById('review-period-controls'),
        periodInput: document.getElementById('review-period-input'),
        periodPrev: document.getElementById('review-period-prev'),
        periodNext: document.getElementById('review-period-next'),
        periodToday: document.getElementById('review-period-today'),
        primary: document.getElementById('review-primary-action'),
        title: document.getElementById('review-title'),
        description: document.getElementById('review-description'),
        newbie: document.getElementById('review-newbie-mode'),
        guideOpen: document.getElementById('review-guide-open'),
        guideDialog: document.getElementById('review-guide-dialog'),
        guideContent: document.getElementById('review-guide-content'),
        searchOpen: document.getElementById('review-search-open'),
        searchDialog: document.getElementById('review-search-dialog'),
        searchForm: document.getElementById('review-search-form'),
        searchResults: document.getElementById('review-search-results'),
        sourceDialog: document.getElementById('review-source-dialog'),
        sourceContent: document.getElementById('review-source-content'),
        helpDialog: document.getElementById('review-help-dialog'),
        helpTitle: document.getElementById('review-help-title'),
        helpContent: document.getElementById('review-help-content'),
        emotionDialog: document.getElementById('review-emotion-dialog'),
        emotionGrid: document.getElementById('review-emotion-grid'),
        emotionCustom: document.getElementById('review-emotion-custom'),
        emotionApply: document.getElementById('review-emotion-apply'),
        aiDialog: document.getElementById('review-ai-dialog'),
        aiContent: document.getElementById('review-ai-content'),
        aiActions: document.getElementById('review-ai-actions'),
        toast: document.getElementById('review-toast'),
    };

    function localISODate(value = new Date()) {
        const offset = value.getTimezoneOffset() * 60000;
        return new Date(value.getTime() - offset).toISOString().slice(0, 10);
    }

    function initialTab() {
        const pathTab = window.location.pathname.match(/^\/review\/([^/]+)\/?$/)?.[1];
        const hashTab = window.location.hash.replace(/^#/, '');
        const candidate = pathTab || initialParams?.get('tab') || hashTab || '';
        return TABS.includes(candidate) ? candidate : 'daily';
    }

    function decryptToken(encoded) {
        if (!encoded) return '';
        try {
            const reversed = encoded.split('').reverse().join('');
            const decoded = decodeURIComponent(escape(atob(reversed)));
            return decoded.endsWith(ENCRYPTION_KEY)
                ? decoded.slice(0, -ENCRYPTION_KEY.length)
                : encoded;
        } catch (error) {
            return encoded;
        }
    }

    function token() {
        return decryptToken(localStorage.getItem(TOKEN_KEY)).trim();
    }

    async function api(path, options = {}) {
        const accessToken = token();
        if (!accessToken) throw new Error('请先在系统设置中保存 API 访问令牌');
        const headers = new Headers(options.headers || {});
        headers.set('Authorization', `Bearer ${accessToken}`);
        if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json');
        const response = await fetch(path, {...options, headers});
        let payload = null;
        try { payload = await response.json(); } catch (error) {}
        if (!response.ok) {
            const detail = payload?.detail;
            throw new Error(typeof detail === 'string' ? detail : payload?.message || `请求失败（${response.status}）`);
        }
        return payload?.data ?? payload;
    }

    function escapeHTML(value) {
        return String(value ?? '').replace(/[&<>'"]/g, (character) => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
        })[character]);
    }

    function escapeAttr(value) { return escapeHTML(value).replace(/`/g, '&#96;'); }

    function compactText(value, length = 120) {
        const text = String(value || '').replace(/\s+/g, ' ').trim();
        return text.length > length ? `${text.slice(0, length)}…` : text;
    }

    function lines(value) {
        return Array.isArray(value)
            ? value.map((item) => typeof item === 'string' ? item : item?.text || item?.title || '').filter(Boolean).join('\n')
            : '';
    }

    function parseLines(value) {
        return String(value || '').split(/\n+/).map((item) => item.trim()).filter(Boolean);
    }

    function setBusy(busy) {
        elements.view.setAttribute('aria-busy', String(Boolean(busy)));
        if (busy) elements.view.innerHTML = '<div class="review-loading">正在整理复盘记录…</div>';
    }

    function setPageError(message = '') {
        elements.status.textContent = message;
    }

    function setSaveState(kind, message) {
        elements.saveState.className = `review-save-state${kind ? ` is-${kind}` : ''}`;
        elements.saveState.innerHTML = '<span class="review-state-mark" aria-hidden="true"></span><span></span>';
        elements.saveState.firstElementChild.textContent = kind === 'error' ? '!' : kind === 'saving' ? '…' : '✓';
        elements.saveState.lastElementChild.textContent = message;
    }

    function syncLabel(sync) {
        if (!sync) return '已保存到 LearnFlux';
        if (sync.status === 'synced') return '已保存，已同步 Obsidian';
        if (sync.status === 'unchanged') return '已保存，Obsidian 无变化';
        if (sync.status === 'not_configured') return '已保存，Obsidian 未配置';
        if (sync.status === 'failed') return '已保存，Obsidian 同步失败，可稍后重试';
        return '已保存到 LearnFlux';
    }

    function toast(message) {
        clearTimeout(state.toastTimer);
        elements.toast.textContent = message;
        elements.toast.hidden = false;
        state.toastTimer = setTimeout(() => { elements.toast.hidden = true; }, 3200);
    }

    function openDialog(dialog) {
        if (dialog && !dialog.open) dialog.showModal();
    }

    function closeDialog(dialog) {
        if (dialog?.open) dialog.close();
    }

    function draftKey(id) { return `${DRAFT_PREFIX}${id}`; }

    function readDraft(item) {
        try {
            const draft = JSON.parse(localStorage.getItem(draftKey(item.id)) || 'null');
            const serverTime = Date.parse(item.updated_at || 0) || 0;
            if (draft?.saved_at > serverTime && draft.payload) return {...item, ...draft.payload, _draft: true};
        } catch (error) {}
        return item;
    }

    function writeDraft(id, payload) {
        try { localStorage.setItem(draftKey(id), JSON.stringify({saved_at: Date.now(), payload})); } catch (error) {}
    }

    function clearDraft(id) {
        try { localStorage.removeItem(draftKey(id)); } catch (error) {}
    }

    function updateTabChrome() {
        document.querySelectorAll('[data-review-section]').forEach((link) => {
            const active = link.dataset.reviewSection === state.tab;
            link.classList.toggle('is-active', active);
            if (active) link.setAttribute('aria-current', 'page');
            else link.removeAttribute('aria-current');
        });
        elements.periodControls.hidden = state.tab === 'insights';
        const configs = {
            daily: {type: 'date', value: state.date},
            weekly: {type: 'date', value: state.date},
            monthly: {type: 'month', value: state.month},
            annual: {type: 'number', value: state.year, min: '1900', max: '2200'},
        };
        const config = configs[state.tab];
        if (config) {
            elements.periodInput.type = config.type;
            elements.periodInput.value = config.value;
            elements.periodInput.min = config.min || '';
            elements.periodInput.max = config.max || '';
        }
        const actions = {
            daily: '新增事件', weekly: '保存本周', monthly: '保存本月',
            annual: '保存年度总结', insights: '新增洞察',
        };
        elements.primary.textContent = actions[state.tab];
        elements.title.textContent = TAB_LABELS[state.tab];
        elements.description.textContent = TAB_DESCRIPTIONS[state.tab];
        document.title = `${TAB_LABELS[state.tab]} · LearnFlux`;
        document.querySelector('.topbar-page-title').textContent = `复盘 / ${TAB_LABELS[state.tab]}`;
    }

    async function selectTab(tab, {replace = false} = {}) {
        if (!TABS.includes(tab)) tab = 'daily';
        state.tab = tab;
        const target = new URL(window.location.href);
        target.pathname = `/review/${tab}`;
        target.hash = '';
        target.searchParams.delete('tab');
        if (`${window.location.pathname}${window.location.search}${window.location.hash}` !== `${target.pathname}${target.search}`) {
            if (replace) history.replaceState(null, '', `${target.pathname}${target.search}`);
            else history.pushState(null, '', `${target.pathname}${target.search}`);
        }
        updateTabChrome();
        await loadCurrentView();
    }

    async function loadCurrentView() {
        setPageError('');
        setBusy(true);
        try {
            if (state.tab === 'daily') await loadDaily();
            else if (state.tab === 'weekly') await loadWeekly();
            else if (state.tab === 'monthly') await loadMonthly();
            else if (state.tab === 'annual') await loadAnnual();
            else if (state.tab === 'insights') await loadInsights();
        } catch (error) {
            elements.view.innerHTML = renderError(error.message);
            setPageError(error.message);
            setSaveState('error', '加载失败');
        } finally {
            elements.view.setAttribute('aria-busy', 'false');
        }
    }

    function renderError(message) {
        return `<div class="review-empty"><div><span class="review-empty-mark">!</span><h2>这部分暂时没有加载成功</h2><p>${escapeHTML(message)}</p><button class="review-button review-button-primary" type="button" data-action="retry">重试</button></div></div>`;
    }

    async function loadPreferences() {
        try {
            state.preferences = await api('/api/reviews/preferences');
            elements.newbie.checked = state.preferences.newbie_mode !== false;
            document.body.classList.toggle('newbie-off', !elements.newbie.checked);
        } catch (error) {
            setPageError(error.message);
        }
    }

    async function loadDaily() {
        state.daily = await api(`/api/reviews/daily-events?date=${encodeURIComponent(state.date)}`);
        state.daily.items = state.daily.items.map(readDraft);
        renderDaily();
        const restored = state.daily.items.some((item) => item._draft);
        setSaveState(
            restored ? 'saving' : 'saved',
            restored ? `已恢复本地草稿 · 今天 ${state.daily.total} 件` : `今天已记录 ${state.daily.total} 件`,
        );
    }

    function renderDaily() {
        const items = state.daily?.items || [];
        if (!items.length) {
            elements.view.innerHTML = `<div class="review-empty"><div><h2>今天还没有复盘记录</h2><p>选一件触动你的事，从客观事实开始填写。</p><button class="review-button review-button-primary" type="button" data-action="add-daily">记录第一件事</button></div></div>`;
            return;
        }
        elements.view.innerHTML = `<div class="review-stack">${items.map(renderDailyCard).join('')}</div>`;
    }

    function meaningOptions(selected) {
        return Object.entries(MEANING_LABELS).map(([value, label]) => (
            `<option value="${escapeAttr(value)}"${value === selected ? ' selected' : ''}>${escapeHTML(label)}</option>`
        )).join('');
    }

    function meaningTypesMarkup(item) {
        const selected = item.meaning_types?.length
            ? item.meaning_types
            : item.meaning_type !== undefined ? [item.meaning_type] : [];
        return Object.entries(MEANING_LABELS).map(([value, label]) => `<label class="review-choice-chip"><input type="checkbox" data-meaning-type value="${escapeAttr(value)}"${selected.includes(value) ? ' checked' : ''}><span>${escapeHTML(label)}</span></label>`).join('');
    }

    function emotionsMarkup(values) {
        const names = (values || []).map((value) => typeof value === 'string' ? value : value?.name).filter(Boolean);
        return names.length
            ? names.map((name) => `<span class="review-chip">${escapeHTML(name)}</span>`).join('')
            : '<span class="review-chip">尚未选择情绪</span>';
    }

    function renderDailyCard(item, index) {
        const past = item.past || {};
        const present = item.present || {};
        const savedAt = item._draft ? '本地草稿' : formatTime(item.updated_at);
        return `<article class="review-event-card review-daily-template" data-event-id="${escapeAttr(item.id)}">
            <header class="review-event-header">
                <div class="review-event-heading"><span>第 ${index + 1} 件</span><input class="review-title-input" data-field="title" value="${escapeAttr(item.title)}" placeholder="给这件事起一个便于回看的名字" aria-label="事件标题"></div>
                <details class="review-more-menu"><summary>更多</summary><div>
                    <button type="button" data-action="source" data-source-type="daily" data-source-id="${escapeAttr(item.id)}">查看来源</button>
                    <button type="button" data-ai="daily_reframe" data-ai-source-id="${escapeAttr(item.id)}">AI 辅助</button>
                    <button type="button" data-action="duplicate-daily">复制事件</button>
                    <button class="is-danger" type="button" data-action="delete-daily">删除事件</button>
                </div></details>
            </header>
            <label class="review-event-prompt"><span>事件</span><strong>什么事件让你内心有所触动？ <button class="review-help-trigger" type="button" data-help="fact" aria-label="查看事件字段帮助">?</button></strong><textarea data-field="fact" placeholder="只写实际发生、可以观察到的内容">${escapeHTML(item.fact)}</textarea></label>
            <div class="review-daily-columns">
                <section class="review-daily-lane is-past">
                    <header><span>当时</span><h3>事件发生时的理解</h3></header>
                    <label class="review-template-field"><span class="review-template-kind">意义</span><strong>当时你如何理解这件事？有什么感受？</strong><textarea data-field="past.thoughts" placeholder="如实写下当时的想法和感受">${escapeHTML(past.thoughts)}</textarea></label>
                    <label class="review-template-field"><span class="review-template-kind">行动</span><strong>当时你采取了什么行动？</strong><textarea data-field="past.action" placeholder="没有采取行动也可以留空">${escapeHTML(past.action)}</textarea></label>
                    <label class="review-template-field"><span class="review-template-kind">结果</span><strong>当时的行动带来了什么结果？</strong><textarea data-field="past.result" placeholder="尚未出现结果也可以留空">${escapeHTML(past.result)}</textarea></label>
                </section>
                <section class="review-daily-lane is-present">
                    <header><span>现在</span><h3>重新看这件事</h3></header>
                    <label class="review-template-field"><span class="review-template-kind">意义</span><strong>现在重新看，你发现了什么？ <button class="review-help-trigger" type="button" data-help="meaning" aria-label="查看意义重塑帮助">?</button></strong><textarea data-field="quick_meaning" placeholder="写下你现在真正认可的理解">${escapeHTML(item.quick_meaning || present.new_view)}</textarea></label>
                    <label class="review-template-field"><span class="review-template-kind">行动</span><strong>从现在开始，你可以采取什么具体行动？</strong><textarea data-field="present.action" placeholder="写成自己现在可以做到的行动">${escapeHTML(present.action)}</textarea></label>
                    <label class="review-template-field"><span class="review-template-kind">结果</span><strong>这些行动可能会带来怎样的结果？</strong><textarea data-field="present.expected_result" placeholder="写下可以观察到的结果">${escapeHTML(present.expected_result)}</textarea></label>
                    <details class="review-inline-result">
                        <summary>已经行动？补充实际结果</summary>
                        <label class="review-field"><span>后来实际发生了什么 <button class="review-help-trigger" type="button" data-help="actual" aria-label="查看实际结果帮助">?</button></span><textarea data-field="present.actual_result" placeholder="如实记录结果，也可以写未执行">${escapeHTML(present.actual_result || present.result)}</textarea></label>
                    </details>
                </section>
            </div>
            <details class="review-template-extras">
                <summary>人物、关键词与情绪（可选）</summary>
                <div class="review-extras-grid">
                    <label class="review-field"><span>当时真正想要什么</span><textarea data-field="past.desire" placeholder="可选">${escapeHTML(past.desire)}</textarea></label>
                    <label class="review-field"><span>现在看见了自己的什么</span><textarea data-field="present.self_discovery" placeholder="可选">${escapeHTML(present.self_discovery)}</textarea></label>
                    <label class="review-field"><span>涉及人物 <button class="review-help-trigger" type="button" data-help="people" aria-label="查看人物和关键词帮助">?</button></span><input data-list-field="people" value="${escapeAttr((item.people || []).join('、'))}" placeholder="用顿号或逗号分开"></label>
                    <label class="review-field"><span>关键词</span><input data-list-field="keywords" value="${escapeAttr((item.keywords || []).join('、'))}" placeholder="例如：周会、表达"></label>
                </div>
                <fieldset class="review-choice-field"><legend>这次意义更接近什么（可多选）</legend><div class="review-meaning-types">${meaningTypesMarkup(item)}</div><label class="review-field"><span>自定义</span><input data-field="meaning_custom" value="${escapeAttr(item.meaning_custom)}" placeholder="可选"></label></fieldset>
                <div class="review-emotions" data-emotion-list>${emotionsMarkup(item.emotions)}</div>
                <button class="review-button review-button-small review-button-quiet" type="button" data-action="choose-emotions">选择情绪</button>
            </details>
            <footer class="review-card-footer"><span data-card-status>${escapeHTML(savedAt)}</span></footer>
        </article>`;
    }

    function collectDailyCard(card) {
        const payload = {past: {}, present: {}};
        card.querySelectorAll('[data-field]').forEach((input) => {
            const [group, field] = input.dataset.field.split('.');
            if (field && (group === 'past' || group === 'present')) payload[group][field] = input.value;
            else payload[group] = input.value;
        });
        card.querySelectorAll('[data-list-field]').forEach((input) => {
            payload[input.dataset.listField] = String(input.value || '').split(/[、,，\n]+/).map((value) => value.trim()).filter(Boolean);
        });
        payload.meaning_types = [...card.querySelectorAll('[data-meaning-type]:checked')].map((input) => input.value);
        payload.meaning_type = payload.meaning_types[0] || '';
        payload.present.new_view = payload.quick_meaning || '';
        const item = state.daily.items.find((entry) => entry.id === card.dataset.eventId);
        payload.emotions = item?.emotions || [];
        return payload;
    }

    function scheduleDailySave(card) {
        const id = card.dataset.eventId;
        const payload = collectDailyCard(card);
        writeDraft(id, payload);
        card.querySelector('[data-card-status]').textContent = '本地草稿';
        setSaveState('saving', '正在自动保存…');
        clearTimeout(state.saveTimers.get(id));
        state.saveTimers.set(id, setTimeout(() => saveDailyCard(card), 800));
    }

    async function saveDailyCard(card) {
        const id = card.dataset.eventId;
        clearTimeout(state.saveTimers.get(id));
        state.saveTimers.delete(id);
        const payload = collectDailyCard(card);
        try {
            const data = await api(`/api/reviews/daily-events/${encodeURIComponent(id)}`, {
                method: 'PATCH', body: JSON.stringify(payload),
            });
            const updated = data.record;
            const index = state.daily.items.findIndex((item) => item.id === id);
            if (index >= 0) state.daily.items[index] = updated;
            clearDraft(id);
            card.querySelector('[data-card-status]').textContent = `已保存 ${formatTime(updated.updated_at)}`;
            setSaveState('saved', syncLabel(data.sync));
        } catch (error) {
            card.querySelector('[data-card-status]').textContent = '保存失败，草稿仍在本机';
            setSaveState('error', '自动保存失败 · 本地草稿已保留');
            toast(error.message);
        }
    }

    async function addDaily() {
        try {
            setSaveState('saving', '正在创建事件…');
            const data = await api('/api/reviews/daily-events', {
                method: 'POST',
                body: JSON.stringify({review_date: state.date, past: {}, present: {}, emotions: []}),
            });
            state.daily = state.daily || {items: []};
            state.daily.items.push(data.record);
            renderDaily();
            setSaveState('saved', syncLabel(data.sync));
            const card = elements.view.querySelector(`[data-event-id="${CSS.escape(data.record.id)}"]`);
            card?.querySelector('.review-title-input')?.focus();
        } catch (error) {
            setSaveState('error', '创建失败');
            toast(error.message);
        }
    }

    async function deleteDaily(card) {
        if (!window.confirm('删除这条复盘事件？这个操作只删除该事件。')) return;
        const id = card.dataset.eventId;
        try {
            await api(`/api/reviews/daily-events/${encodeURIComponent(id)}`, {method: 'DELETE'});
            state.daily.items = state.daily.items.filter((item) => item.id !== id);
            clearDraft(id);
            renderDaily();
            setSaveState('saved', '事件已删除');
        } catch (error) { toast(error.message); }
    }

    async function duplicateDaily(card) {
        try {
            const data = await api(`/api/reviews/daily-events/${encodeURIComponent(card.dataset.eventId)}/duplicate`, {method: 'POST'});
            state.daily.items.push(data.record);
            renderDaily();
            setSaveState('saved', syncLabel(data.sync));
            toast('已复制为新的独立事件');
        } catch (error) { toast(error.message); }
    }

    function openEmotionPicker(card) {
        const item = state.daily.items.find((entry) => entry.id === card.dataset.eventId);
        state.emotionTarget = card.dataset.eventId;
        state.emotionSelection = (item?.emotions || []).map((value) => typeof value === 'string' ? value : value?.name).filter(Boolean);
        elements.emotionGrid.innerHTML = EMOTIONS.map((name) => `<button type="button" data-emotion="${escapeAttr(name)}" aria-pressed="${state.emotionSelection.includes(name)}">${escapeHTML(name)}</button>`).join('');
        elements.emotionCustom.value = '';
        openDialog(elements.emotionDialog);
    }

    function addCustomEmotion() {
        const value = elements.emotionCustom.value.trim();
        if (!value) return;
        if (!state.emotionSelection.includes(value)) state.emotionSelection.push(value);
        elements.emotionCustom.value = '';
        elements.emotionGrid.insertAdjacentHTML('beforeend', `<button type="button" data-emotion="${escapeAttr(value)}" aria-pressed="true">${escapeHTML(value)}</button>`);
    }

    function applyEmotions() {
        const item = state.daily.items.find((entry) => entry.id === state.emotionTarget);
        const card = elements.view.querySelector(`[data-event-id="${CSS.escape(state.emotionTarget || '')}"]`);
        if (!item || !card) return closeDialog(elements.emotionDialog);
        item.emotions = state.emotionSelection.map((name) => ({name}));
        card.querySelector('[data-emotion-list]').innerHTML = emotionsMarkup(item.emotions);
        scheduleDailySave(card);
        closeDialog(elements.emotionDialog);
    }

    async function loadWeekly() {
        state.weekly = await api(`/api/reviews/weekly/${encodeURIComponent(state.date)}`);
        renderWeekly();
        setSaveState('saved', '本周来源已聚合');
    }

    function renderWeekly() {
        const data = state.weekly;
        const record = data.record || {focus_ids: [], abstraction: {}, summary: ''};
        const focusIds = record.focus_ids || [];
        const byDay = groupBy(data.daily_events || [], (item) => item.review_date);
        const start = new Date(`${data.period.start}T12:00:00`);
        const days = Array.from({length: 7}, (_, offset) => {
            const day = new Date(start);
            day.setDate(start.getDate() + offset);
            return localISODate(day);
        });
        const dailyRows = days.map((day) => {
            const items = byDay[day] || [];
            return `<section class="review-source-day"><h4><span>${escapeHTML(day.slice(5))}</span>${weekdayLabel(day)}</h4><div>${items.map((item) => `<label class="review-source-event"><input type="checkbox" data-focus-source="${escapeAttr(item.id)}"${focusIds.includes(item.id) ? ' checked' : ''}><span><strong>${escapeHTML(item.title || '未命名事件')}</strong><p>${escapeHTML(compactText(item.fact || item.quick_meaning, 90))}</p></span></label>`).join('') || '<p class="review-source-empty">暂无记录</p>'}</div></section>`;
        }).join('');
        elements.view.innerHTML = `<div class="review-week-sheet">
            <section class="review-week-reflection" aria-label="周度复盘">
                <header class="review-sheet-heading"><h2>本周复盘</h2><p>${escapeHTML(data.period.start)} 至 ${escapeHTML(data.period.end)}</p></header>
                ${weeklyStep(1, '聚焦', '从右侧选择 1-3 件真正重要的事', `<ul class="review-focus-list" id="review-focus-list">${focusIds.map((id) => renderFocusItem(id, data.daily_events)).join('') || '<li class="review-source-empty">从右侧每日记录中勾选</li>'}</ul>`, 'focus')}
                ${weeklyStep(2, '连接', '寻找直接、间接或意外的联结', renderConnections(data.connections || []), 'connection', 'weekly_connections')}
                ${weeklyStep(3, '抽象', '从枝叶逐步靠近树干和根系', renderAbstraction(record.abstraction || {}), 'abstraction', 'weekly_abstraction')}
                ${weeklyStep(4, '行动实验', '把认可的理解变成一个可验证的行动', renderExperiments(data.experiments || []), 'experiment', 'action_experiment')}
                <section class="review-week-summary"><label class="review-field"><span>本周总结</span><textarea id="review-week-summary" placeholder="这一周最值得留下的是什么？">${escapeHTML(record.summary || '')}</textarea></label></section>
            </section>
            <aside class="review-week-daily" aria-label="本周每日记录">
                <header class="review-sheet-heading"><h2>每日记录</h2><button class="review-help-trigger" type="button" data-help="focus" aria-label="查看聚焦帮助">?</button></header>
                ${dailyRows}
            </aside>
        </div>`;
    }

    function weeklyStep(number, title, subtitle, body, helpKey, aiType = '') {
        return `<details class="review-week-step"${number === 1 ? ' open' : ''}><summary><span class="review-step-number">${number}</span><span><strong>${escapeHTML(title)}</strong><small>${escapeHTML(subtitle)}</small></span></summary><div class="review-week-step-body"><div class="review-step-tools"><button class="review-help-trigger" type="button" data-help="${helpKey}" aria-label="查看${escapeAttr(title)}帮助">?</button>${aiType ? `<button class="review-button review-button-small review-button-quiet" type="button" data-ai="${aiType}">从记录寻找候选</button>` : ''}</div>${body}</div></details>`;
    }

    function renderFocusItem(id, events) {
        const item = (events || []).find((entry) => entry.id === id);
        return `<li class="review-focus-item" draggable="true" data-focus-id="${escapeAttr(id)}"><span class="review-drag-handle" aria-hidden="true">••</span><span><strong>${escapeHTML(item?.title || '来源事件')}</strong><small>${escapeHTML(item?.review_date || '')}</small></span><button class="review-dialog-close" type="button" data-action="remove-focus" aria-label="移出聚焦">×</button></li>`;
    }

    function renderConnections(items) {
        const events = state.weekly?.daily_events || [];
        const optionMarkup = (selected = '') => `<option value="">请选择事件</option>${events.map((item) => `<option value="${escapeAttr(item.id)}"${item.id === selected ? ' selected' : ''}>${escapeHTML(item.review_date)} · ${escapeHTML(item.title || compactText(item.fact, 32) || '未命名事件')}</option>`).join('')}`;
        const cards = items.map((item) => renderConnectionCard(item)).join('');
        const disabled = events.length < 2 ? ' disabled' : '';
        return `<div class="review-connection-list">${cards || '<p class="review-source-empty">还没有连接记录</p>'}</div><details class="review-form-disclosure"><summary>${events.length < 2 ? '至少需要两条事件' : '建立一条连接'}</summary><form class="review-connection-form" id="review-connection-form" data-period-type="weekly"><div class="review-connection-route"><label class="review-field"><span>起点事件</span><select name="source_id" required${disabled}>${optionMarkup()}</select></label><span class="review-connection-arrow" aria-hidden="true">→</span><label class="review-field"><span>终点事件</span><select name="target_id" required${disabled}>${optionMarkup()}</select></label></div><div class="review-field-row"><label class="review-field"><span>连接标题</span><input name="title" required placeholder="例如：准备动作在两个场景里重复出现"></label><label class="review-field"><span>类型</span><select name="connection_type"><option value="direct">直接</option><option value="indirect">间接</option><option value="unexpected">意外</option></select></label></div><label class="review-field"><span>方向</span><select name="direction"><option value="forward">起点 → 终点</option><option value="bidirectional">双向影响</option><option value="reverse">终点 → 起点</option></select></label><label class="review-field"><span>联结说明</span><textarea name="description" placeholder="只写看见的关系，暂不确定因果"></textarea></label><input type="hidden" name="source_type" value="daily"><input type="hidden" name="target_type" value="daily"><div class="review-card-actions"><button class="review-button review-button-quiet" type="button" data-action="cancel-connection-edit" hidden>取消编辑</button><button class="review-button review-button-primary" type="submit"${disabled}>添加连接</button></div></form></details>`;
    }

    function connectionEndpointLabel(type, id) {
        let record = null;
        if (type === 'daily') record = state.weekly?.daily_events?.find((item) => item.id === id);
        if (type === 'monthly') record = state.monthly?.monthly_reviews?.find((item) => item.id === id) || state.annual?.months?.find((item) => item.id === id);
        return record?.title || record?.month_key || record?.review_date || shortId(id);
    }

    function renderConnectionCard(item) {
        const sourceType = item.source_type || 'daily';
        const targetType = item.target_type || sourceType;
        const sourceId = item.source_id || item.source_ids?.[0] || '';
        const targetId = item.target_id || item.source_ids?.[1] || '';
        const arrow = item.direction === 'bidirectional' ? '↔' : item.direction === 'reverse' ? '←' : '→';
        const actions = state.tab === 'annual' ? '' : `<div class="review-card-actions"><button class="review-button review-button-small review-button-ghost" type="button" data-action="edit-connection" data-id="${escapeAttr(item.id)}">编辑</button><button class="review-button review-button-small review-button-danger" type="button" data-action="delete-connection" data-id="${escapeAttr(item.id)}">删除</button></div>`;
        return `<article class="review-connection-card" data-connection-id="${escapeAttr(item.id)}"><header><div><span class="review-chip">${connectionLabel(item.connection_type)}</span><h4>${escapeHTML(item.title || '一条连接')}</h4></div>${actions}</header><div class="review-connection-path"><button class="review-chip is-source" type="button" data-action="source" data-source-type="${escapeAttr(sourceType)}" data-source-id="${escapeAttr(sourceId)}">${escapeHTML(connectionEndpointLabel(sourceType, sourceId))}</button><strong aria-label="方向">${arrow}</strong><button class="review-chip is-source" type="button" data-action="source" data-source-type="${escapeAttr(targetType)}" data-source-id="${escapeAttr(targetId)}">${escapeHTML(connectionEndpointLabel(targetType, targetId))}</button></div><p>${escapeHTML(item.description || '暂未补充说明')}</p></article>`;
    }

    function connectionLabel(value) {
        return ({direct: '直接连接', indirect: '间接连接', unexpected: '意外连接'})[value] || '连接';
    }

    function renderAbstraction(values) {
        const groups = [
            {className: '', title: '枝叶 · 贴近事件', levels: [1, 2, 3], open: true},
            {className: ' is-trunk', title: '树干 · 兴趣、优势与模式', levels: [4, 5, 6], open: false},
            {className: ' is-root', title: '树根 · 信念、愿望与固定想法', levels: [7, 8], open: false},
        ];
        return `<div class="review-abstraction-groups">${groups.map((group) => `<details class="review-abstraction-group${group.className}"${group.open ? ' open' : ''}><summary><span><strong>${escapeHTML(group.title)}</strong><small>${group.open ? '先从这三项开始' : '有跨周期证据时再展开'}</small></span><span class="review-chip">证据不足就停在这里</span></summary><div class="review-abstraction-levels">${group.levels.map((level) => `<label class="review-field"><span>L${level} · ${escapeHTML(abstractionTitle(level))}</span><textarea data-abstraction-level="${level}" placeholder="${escapeAttr(abstractionPlaceholder(level))}">${escapeHTML(values[String(level)] || values[level] || '')}</textarea></label>`).join('')}</div></details>`).join('')}</div>`;
    }

    function abstractionTitle(level) {
        return ({1: '状态', 2: '在意的事', 3: '重要人物', 4: '兴趣', 5: '优势', 6: '思维与行为模式', 7: '信念与固有观念', 8: '真实想法与愿望'})[level];
    }

    function abstractionPlaceholder(level) {
        return ({
            1: '本周头脑、内心和身体状态怎样？',
            2: '本周最在意的事情是什么？',
            3: '本周的重要人物有哪些？',
            4: '最近反复关注什么，可能体现哪些兴趣？',
            5: '哪些事相对容易做好，可能体现哪些优势？',
            6: '出现了哪些重复的思维或行为模式？',
            7: '这些模式背后可能有什么信念或固有观念？',
            8: '我真正的想法、愿望和想过的生活是什么？',
        })[level];
    }

    function renderExperiments(items) {
        const cards = items.map((item) => `<article class="review-experiment-card"><header><div><span class="review-chip">${escapeHTML(experimentStatusLabel(item.status))}</span><h4>${escapeHTML(item.title || '行动实验')}</h4></div><div class="review-card-actions"><button class="review-button review-button-small review-button-ghost" type="button" data-action="source" data-source-type="experiment" data-source-id="${escapeAttr(item.id)}">来源</button><button class="review-button review-button-small review-button-danger" type="button" data-action="delete-experiment" data-id="${escapeAttr(item.id)}">删除</button></div></header><p>${escapeHTML(compactText(item.what || item.how, 160))}</p><p>最小第一步：${escapeHTML(item.first_step || '尚未填写')} · 复查：${escapeHTML(item.review_date || '待定')}</p><details class="review-event-details"><summary>${item.period_key !== state.weekly.period.start ? '来自上一周期 · ' : ''}回看执行与实际结果</summary><form class="review-experiment-review" data-experiment-review="${escapeAttr(item.id)}"><div class="review-field-row"><label class="review-field"><span>是否执行</span><select name="executed"><option value="">尚未回看</option><option value="yes"${item.executed === 'yes' ? ' selected' : ''}>已执行</option><option value="partial"${item.executed === 'partial' ? ' selected' : ''}>执行了一部分</option><option value="no"${item.executed === 'no' ? ' selected' : ''}>未执行</option></select></label><label class="review-field"><span>继续 / 调整 / 停止</span><select name="next_decision"><option value="">尚未决定</option><option value="continue"${item.next_decision === 'continue' ? ' selected' : ''}>继续</option><option value="adjust"${item.next_decision === 'adjust' ? ' selected' : ''}>调整</option><option value="stop"${item.next_decision === 'stop' ? ' selected' : ''}>停止</option></select></label></div><label class="review-field"><span>实际发生了什么</span><textarea name="result">${escapeHTML(item.result || '')}</textarea></label><label class="review-field"><span>原来的认识是否仍成立</span><textarea name="insight_result">${escapeHTML(item.insight_result || '')}</textarea></label><button class="review-button review-button-primary" type="submit">保存回看结果</button></form></details></article>`).join('');
        return `<div class="review-experiment-list">${cards || '<p class="review-chip">还没有行动实验</p>'}</div><details class="review-event-details review-create-experiment"><summary>＋ 新建行动实验（4W1H + 资源预算）</summary><form class="review-step-body" id="review-experiment-form"><div class="review-field-row"><label class="review-field"><span>实验标题</span><input name="title" required></label><label class="review-field"><span>复查日期</span><input name="review_date" type="date"></label></div><label class="review-field"><span>Why · 为什么值得验证</span><textarea name="why"></textarea></label><label class="review-field"><span>What · 具体做什么</span><textarea name="what"></textarea></label><div class="review-field-row"><label class="review-field"><span>Who · 和谁</span><input name="who"></label><label class="review-field"><span>When · 何时</span><input name="when"></label></div><div class="review-field-row"><label class="review-field"><span>Where · 在哪里</span><input name="where"></label><label class="review-field"><span>How · 怎么做</span><input name="how"></label></div><div class="review-field-row"><label class="review-field"><span>资源</span><input name="resources"></label><label class="review-field"><span>预算 / 时间上限</span><input name="budget"></label></div><div class="review-field-row"><label class="review-field"><span>这是我真正想尝试的吗</span><select name="desire_check"><option value="">还没确认</option><option value="yes">是</option><option value="no">不是</option><option value="unsure">暂不确定</option></select></label><label class="review-field"><span>主要由我自己控制吗</span><select name="control_check"><option value="">还没确认</option><option value="yes">是</option><option value="partial">部分可控</option><option value="no">否</option><option value="unsure">暂不确定</option></select></label></div><label class="review-field"><span>最小的第一步</span><textarea name="first_step" placeholder="小到可以直接开始、失败也容易调整"></textarea></label><label class="review-field"><span>预计看到什么结果</span><textarea name="success_signal" placeholder="看到什么，才算这个理解得到一点支持？"></textarea></label><button class="review-button review-button-primary" type="submit">创建实验</button></form></details>`;
    }

    function experimentStatusLabel(value) {
        return ({planned: '待实验', active: '观察中', completed: '已完成', stopped: '已停止'})[value] || value;
    }

    function selectedWeeklyIds() {
        return [...elements.view.querySelectorAll('[data-focus-id]')].map((item) => item.dataset.focusId);
    }

    function updateWeeklyFocus(id, selected) {
        const current = state.weekly.record?.focus_ids ? [...state.weekly.record.focus_ids] : [];
        const exists = current.includes(id);
        if (selected && !exists) {
            if (current.length >= 3) {
                const checkbox = elements.view.querySelector(`[data-focus-source="${CSS.escape(id)}"]`);
                if (checkbox) checkbox.checked = false;
                return toast('第一版最多聚焦 3 件事；可以先移除一件。');
            }
            current.push(id);
        } else if (!selected && exists) current.splice(current.indexOf(id), 1);
        state.weekly.record = {...(state.weekly.record || {}), focus_ids: current};
        const list = document.getElementById('review-focus-list');
        list.innerHTML = current.map((sourceId) => renderFocusItem(sourceId, state.weekly.daily_events)).join('') || '<li class="review-chip">从右侧勾选本周聚焦</li>';
    }

    async function saveWeekly() {
        const focusIds = selectedWeeklyIds();
        const abstraction = {};
        elements.view.querySelectorAll('[data-abstraction-level]').forEach((input) => { abstraction[input.dataset.abstractionLevel] = input.value; });
        const payload = {focus_ids: focusIds, abstraction, summary: document.getElementById('review-week-summary')?.value || '', status: 'active'};
        try {
            setSaveState('saving', '正在保存周度复盘…');
            const data = await api(`/api/reviews/weekly/${encodeURIComponent(state.date)}`, {method: 'PUT', body: JSON.stringify(payload)});
            state.weekly.record = data.record;
            setSaveState('saved', syncLabel(data.sync));
            toast('周度复盘已保存');
        } catch (error) { setSaveState('error', '保存失败'); toast(error.message); }
    }

    async function createConnection(form) {
        const data = Object.fromEntries(new FormData(form));
        data.period_type = form.dataset.periodType || 'weekly';
        data.period_key = data.period_type === 'monthly' ? state.month.slice(0, 4) : state.weekly.period.start;
        data.source_ids = [data.source_id, data.target_id];
        try {
            const editingId = form.dataset.editingId;
            const item = await api(editingId ? `/api/reviews/connections/${encodeURIComponent(editingId)}` : '/api/reviews/connections', {method: editingId ? 'PATCH' : 'POST', body: JSON.stringify(data)});
            const target = data.period_type === 'monthly' ? state.monthly.connections : state.weekly.connections;
            const index = target.findIndex((entry) => entry.id === item.id);
            if (index >= 0) target[index] = item; else target.unshift(item);
            if (data.period_type === 'monthly') renderMonthly(); else renderWeekly();
            toast(editingId ? '连接已更新。' : '连接已记录；它仍然只是待观察的关系。');
        } catch (error) { toast(error.message); }
    }

    async function createExperiment(form) {
        const data = Object.fromEntries(new FormData(form));
        data.period_key = state.weekly.period.start;
        data.source_ids = selectedWeeklyIds();
        try {
            const response = await api('/api/reviews/action-experiments', {method: 'POST', body: JSON.stringify(data)});
            state.weekly.experiments.unshift(response.record);
            renderWeekly();
            setSaveState('saved', syncLabel(response.sync));
        } catch (error) { toast(error.message); }
    }

    function editableExperimentPayload(item) {
        const fields = ['period_key', 'title', 'why', 'what', 'who', 'when', 'where', 'how', 'resources', 'budget', 'success_signal', 'desire_check', 'control_check', 'first_step', 'review_date', 'result', 'executed', 'insight_result', 'next_decision', 'source_ids', 'status'];
        return Object.fromEntries(fields.map((field) => [field, item[field] ?? (field === 'source_ids' ? [] : '')]));
    }

    async function reviewExperiment(form) {
        const id = form.dataset.experimentReview;
        const item = state.weekly.experiments.find((entry) => entry.id === id);
        if (!item) return;
        const values = Object.fromEntries(new FormData(form));
        const payload = {...editableExperimentPayload(item), ...values};
        if (values.next_decision === 'stop') payload.status = 'stopped';
        else if (values.executed) payload.status = 'active';
        try {
            const response = await api(`/api/reviews/action-experiments/${encodeURIComponent(id)}`, {method: 'PATCH', body: JSON.stringify(payload)});
            Object.assign(item, response.record);
            renderWeekly();
            setSaveState('saved', syncLabel(response.sync));
            toast('行动实验的实际结果已保存。');
        } catch (error) { toast(error.message); }
    }

    async function loadMonthly() {
        state.monthly = await api(`/api/reviews/monthly/${encodeURIComponent(state.month)}`);
        renderMonthly();
        setSaveState('saved', '本月来源已聚合');
    }

    function renderMonthly() {
        const record = state.monthly.record || {};
        const columns = [
            ['inner', '内心', '本月的重要发现、情绪、想法等内心声音'],
            ['actions', '行动', '本月实际采取的行动'],
            ['results', '结果', '本月已经看见的成果或反馈'],
            ['notes', '备注', '新的发现、想尝试的事或需要记住的背景'],
        ];
        const sourceLinks = state.monthly.daily_events.slice(0, 80).map((item) => `<button class="review-source-link" type="button" data-action="source" data-source-type="daily" data-source-id="${escapeAttr(item.id)}"><span>${escapeHTML(item.review_date)}</span>${escapeHTML(item.title || '未命名事件')}</button>`).join('');
        elements.view.innerHTML = `<div class="review-month-page"><section class="review-month-sheet" aria-label="${escapeAttr(state.month)} 月度复盘模板"><header class="review-sheet-heading"><h2>${escapeHTML(state.month)} 月度复盘</h2><p>每栏记录 1-3 件最重要的事，四栏不必互为因果。</p></header><div class="review-month-grid">${columns.map(([key, title, hint]) => `<label class="review-month-column"><span>${title}</span><small>${hint}</small><textarea class="review-textarea" data-month-field="${key}" placeholder="每行一条">${escapeHTML(lines(record[key]))}</textarea></label>`).join('')}</div></section><details class="review-secondary-panel"><summary>跨月联结与本月确认</summary><div class="review-secondary-content"><label class="review-field"><span>跨月联结（每行一条）</span><textarea id="review-month-cross" placeholder="例如：三月的想法在五月进入行动">${escapeHTML(lines(record.cross_month))}</textarea></label><label class="review-field"><span>给这个月的自己一句确认</span><textarea id="review-month-affirmation" placeholder="写下你真正认可的投入、选择或坚持">${escapeHTML(record.affirmation || '')}</textarea></label>${renderMonthlyConnections()}</div></details><details class="review-secondary-panel"><summary>本月记录来源</summary><div class="review-source-list">${sourceLinks || '<p class="review-source-empty">本月暂无每日记录</p>'}</div></details></div>`;
    }

    function renderMonthlyConnections() {
        const months = state.monthly.monthly_reviews || [];
        const options = (selected = '') => `<option value="">请选择月份</option>${months.map((item) => `<option value="${escapeAttr(item.id)}"${item.id === selected ? ' selected' : ''}>${escapeHTML(item.month_key)}</option>`).join('')}`;
        const disabled = months.length < 2 ? ' disabled' : '';
        return `<div class="review-period-connection"><h4>已记录的跨月联结</h4><div class="review-connection-list">${(state.monthly.connections || []).map(renderConnectionCard).join('') || '<p class="review-source-empty">保存至少两个月后，可以建立方向联结。</p>'}</div><details class="review-form-disclosure"><summary>${months.length < 2 ? '至少需要两个月' : '建立跨月联结'}</summary><form class="review-connection-form" id="review-month-connection-form" data-period-type="monthly"><div class="review-connection-route"><label class="review-field"><span>起点月份</span><select name="source_id" required${disabled}>${options()}</select></label><span class="review-connection-arrow" aria-hidden="true">→</span><label class="review-field"><span>终点月份</span><select name="target_id" required${disabled}>${options()}</select></label></div><div class="review-field-row"><label class="review-field"><span>连接标题</span><input name="title" required placeholder="例如：三月的想法在五月进入行动"></label><label class="review-field"><span>类型</span><select name="connection_type"><option value="direct">直接</option><option value="indirect">间接</option><option value="unexpected">意外</option></select></label></div><label class="review-field"><span>方向</span><select name="direction"><option value="forward">起点 → 终点</option><option value="bidirectional">双向影响</option><option value="reverse">终点 → 起点</option></select></label><label class="review-field"><span>联结说明</span><textarea name="description"></textarea></label><input type="hidden" name="source_type" value="monthly"><input type="hidden" name="target_type" value="monthly"><div class="review-card-actions"><button class="review-button review-button-quiet" type="button" data-action="cancel-connection-edit" hidden>取消编辑</button><button class="review-button review-button-primary" type="submit"${disabled}>添加联结</button></div></form></details></div>`;
    }

    async function saveMonthly() {
        const payload = {};
        elements.view.querySelectorAll('[data-month-field]').forEach((input) => { payload[input.dataset.monthField] = parseLines(input.value); });
        payload.cross_month = parseLines(document.getElementById('review-month-cross')?.value);
        payload.affirmation = document.getElementById('review-month-affirmation')?.value || '';
        payload.status = 'active';
        try {
            setSaveState('saving', '正在保存月度复盘…');
            const data = await api(`/api/reviews/monthly/${encodeURIComponent(state.month)}`, {method: 'PUT', body: JSON.stringify(payload)});
            state.monthly.record = data.record;
            const existing = state.monthly.monthly_reviews.findIndex((item) => item.id === data.record.id);
            if (existing >= 0) state.monthly.monthly_reviews[existing] = data.record;
            else state.monthly.monthly_reviews.unshift(data.record);
            setSaveState('saved', syncLabel(data.sync));
            toast('月度复盘已保存');
        } catch (error) { setSaveState('error', '保存失败'); toast(error.message); }
    }

    async function loadAnnual() {
        state.annual = await api(`/api/reviews/annual/${encodeURIComponent(state.year)}`);
        renderAnnual();
        setSaveState('saved', '十二个月来源已聚合');
    }

    function renderAnnual(keyword = '') {
        const record = state.annual.record || {};
        const normalizedKeyword = keyword.trim();
        const cell = (items) => {
            const values = items || [];
            return values.length ? `<ul>${values.map((value) => `<li>${highlight(value, normalizedKeyword)}</li>`).join('')}</ul>` : '<span class="review-empty-cell">空</span>';
        };
        const aiCandidates = (state.annual.ai_candidates || []).map((item) => {
            const candidate = item.confirmed_content || item.candidate || {};
            return `<article class="review-ai-candidate"><span class="review-meta-text">${item.status === 'confirmed' ? '已确认候选' : '待确认候选'}</span><p><strong>${escapeHTML(candidate.statement || '')}</strong></p><div class="review-emotions">${(candidate.evidence || []).map((evidence) => `<button class="review-chip is-source" type="button" data-action="source" data-source-type="${escapeAttr(evidence.source_type || 'monthly')}" data-source-id="${escapeAttr(evidence.source_id)}">${escapeHTML(evidence.record_date || shortId(evidence.source_id))}</button>`).join('')}</div><p class="review-ai-uncertainty">${escapeHTML(candidate.uncertainty_note || '仍需更多来源验证')}</p></article>`;
        }).join('');
        const rows = state.annual.months.map((month) => {
            const monthNumber = Number(String(month.month_key || '').slice(-2)) || '';
            const monthLabel = monthNumber ? `${monthNumber}月` : month.month_key;
            return `<tr><th scope="row">${month.id ? `<button class="review-month-source" type="button" data-action="source" data-source-type="monthly" data-source-id="${escapeAttr(month.id)}">${escapeHTML(monthLabel)}</button>` : escapeHTML(monthLabel)}</th><td>${cell(month.inner)}</td><td>${cell(month.actions)}</td><td>${cell(month.results)}</td><td>${cell(month.notes)}</td></tr>`;
        }).join('');
        elements.view.innerHTML = `<div class="review-annual-page"><section class="review-annual-sheet"><header class="review-sheet-heading"><h2>${escapeHTML(state.year)} 年度复盘</h2><p>一页掌握全年动向。点击月份可以回到对应记录。</p></header><div class="review-annual-surface"><table class="review-annual-table"><thead><tr><th>月份</th><th>内心</th><th>行动</th><th>结果</th><th>备注</th></tr></thead><tbody>${rows}</tbody></table></div></section><section class="review-annual-summary"><header><h2>年度关键词与总结</h2><button class="review-button review-button-small review-button-quiet" type="button" data-ai="annual_summary">从月度记录寻找候选</button></header><div class="review-annual-summary-fields"><label class="review-field"><span>关键词（每行一个）</span><textarea id="review-annual-keywords" placeholder="例如：表达、运动、边界">${escapeHTML(lines(record.keywords))}</textarea></label><label class="review-field"><span>这一年最值得留下的理解</span><textarea id="review-annual-summary">${escapeHTML(record.summary || '')}</textarea></label></div></section><details class="review-secondary-panel"><summary>查看跨月联结</summary><div class="review-secondary-content review-connection-list">${(state.annual.connections || []).map(renderConnectionCard).join('') || '<p class="review-source-empty">本年度暂无跨月联结</p>'}</div></details>${aiCandidates ? `<details class="review-secondary-panel"><summary>查看已保存的年度候选</summary><div class="review-secondary-content review-ai-candidates">${aiCandidates}</div></details>` : ''}</div>`;
    }

    function highlight(value, keyword) {
        const escaped = escapeHTML(value);
        if (!keyword) return escaped;
        const safe = keyword.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        return escaped.replace(new RegExp(safe, 'gi'), (match) => `<mark class="review-highlight">${match}</mark>`);
    }

    async function saveAnnual() {
        const payload = {
            keywords: parseLines(document.getElementById('review-annual-keywords')?.value),
            summary: document.getElementById('review-annual-summary')?.value || '',
            status: 'active',
        };
        try {
            setSaveState('saving', '正在保存年度复盘…');
            const data = await api(`/api/reviews/annual/${encodeURIComponent(state.year)}`, {method: 'PUT', body: JSON.stringify(payload)});
            state.annual.record = data.record;
            setSaveState('saved', syncLabel(data.sync));
            toast('年度复盘已保存');
        } catch (error) { setSaveState('error', '保存失败'); toast(error.message); }
    }

    async function loadInsights() {
        const data = await api('/api/reviews/insights');
        state.insights = data.items || [];
        state.insightOverview = data.overview || {};
        state.insightSources = data.recent_sources || [];
        renderInsights();
        setSaveState('saved', `${state.insights.length} 条洞察记录`);
    }

    function renderInsights(showForm = false) {
        const levels = [
            ['branch', 1, '自己的状态', '本周你的头脑、内心和身体状态怎么样？'],
            ['branch', 2, '内心最在意的事', '当下你最在意的事情有哪些？'],
            ['branch', 3, '重要人物', '对你来说，生活中的重要人物是谁？'],
            ['trunk', 4, '兴趣所在', '你最近在关注什么？'],
            ['trunk', 5, '优势和特长', '你的优势和特长是什么？'],
            ['trunk', 6, '思维模式和行为模式', '你惯常的思维模式或行为模式有哪些？'],
            ['root', 7, '信念和固有观念', '促使你形成这些模式的根源是什么？'],
            ['root', 8, '想法和愿望', '你真正渴望的是什么，想成为怎样的人？'],
        ];
        const tiers = [
            ['branch', '枝叶可见期', '从当下可见的状态开始'],
            ['trunk', '树干可见期', '从多次记录中寻找稳定倾向'],
            ['root', '根系可见期', '只有跨周期证据充分时才下探'],
        ];
        const overview = state.insightOverview || {};
        const tierLabels = {branch: '枝叶', trunk: '树干', root: '树根'};
        const suitable = (overview.suitable_tiers || []).map((tier) => tierLabels[tier]).join('、') || '继续积累事实记录';
        const next = overview.next_tier ? tierLabels[overview.next_tier] : '可继续验证已有洞察';
        const bands = tiers.map(([tier, title, subtitle]) => `<section class="review-insight-band is-${tier}"><header><h2>${title}</h2><p>${subtitle}</p></header><div class="review-insight-levels">${levels.filter(([levelTier]) => levelTier === tier).map(([, level, levelTitle, prompt]) => {
            const items = state.insights.filter((item) => Number(item.level) === level);
            return `<article class="review-insight-level"><header><span>${level}</span><div><h3>${escapeHTML(levelTitle)}</h3><p>${escapeHTML(prompt)}</p></div></header><div class="review-insight-grid">${items.map(renderInsightCard).join('') || '<p class="review-source-empty">尚未形成洞察</p>'}</div></article>`;
        }).join('')}</div></section>`).join('');
        elements.view.innerHTML = `<div class="review-insight-page"><section class="review-insight-note"><div><strong>当前可整理：${escapeHTML(suitable)}</strong><p>进入${escapeHTML(next)}前，需要更多跨周期记录与反例。</p></div><button class="review-button review-button-quiet" type="button" data-ai="inner_insight">从记录寻找候选</button></section>${showForm ? renderInsightForm() : ''}<section class="review-insight-map" aria-label="八个抽象化层级">${bands}</section></div>`;
    }

    function renderInsightForm() {
        const sources = state.insightSources.map((item) => `<label class="review-source-event"><input type="checkbox" name="source_id" value="${escapeAttr(item.id)}"><span><strong>${escapeHTML(item.review_date)} · ${escapeHTML(item.title || '未命名事件')}</strong><p>${escapeHTML(compactText(item.fact || item.quick_meaning, 90))}</p></span></label>`).join('');
        return `<section class="review-insight-form" id="review-insight-create"><header><h2>新增洞察</h2><p>先写可验证的陈述，再补充来源、反例和验证行动。</p></header><form id="review-insight-form"><div class="review-field-row"><label class="review-field"><span>层级</span><select name="tier"><option value="branch">枝叶</option><option value="trunk">树干</option><option value="root">根系</option></select></label><label class="review-field"><span>抽象级别 L1-L8</span><input name="level" type="number" value="1" min="1" max="8"></label></div><label class="review-field"><span>类别</span><select name="category"><option value="state">状态</option><option value="concern">在意的事</option><option value="person">重要人物</option><option value="interest">兴趣</option><option value="strength">优势</option><option value="thought_pattern">思维模式</option><option value="behavior_pattern">行为模式</option><option value="belief">信念</option><option value="fixed_idea">固有观念</option><option value="wish">真实想法与愿望</option></select></label><label class="review-field"><span>候选陈述</span><textarea name="statement" required placeholder="例如：在需要即兴表达的场合，我会通过过度准备来降低不确定性。"></textarea></label><fieldset class="review-source-picker"><legend>引用最近的原始记录</legend>${sources || '<p class="review-source-empty">还没有可引用的每日记录</p>'}</fieldset><label class="review-field"><span>补充支持证据（每行一条）</span><textarea name="evidence"></textarea></label><label class="review-field"><span>反例或另一种解释（每行一条）</span><textarea name="counter_evidence"></textarea></label><div class="review-field-row"><label class="review-field"><span>不确定性（0-1）</span><input name="uncertainty" type="number" value="0.5" min="0" max="1" step="0.1"></label><label class="review-field"><span>为什么仍不确定</span><input name="uncertainty_note" placeholder="例如：目前只有一周的记录"></label></div><label class="review-field"><span>用于验证的最小行动</span><textarea name="verification_experiment" placeholder="下一次如何在现实里观察它是否成立？"></textarea></label><button class="review-button review-button-primary" type="submit">保存为待确认洞察</button></form></section>`;
    }

    function renderInsightCard(item) {
        const strength = item.evidence_strength || {};
        const span = item.evidence_span || {};
        const evidence = (item.evidence || []).map((entry) => typeof entry === 'string' ? `<li>${escapeHTML(entry)}</li>` : `<li>${entry.source_id ? `<button class="review-chip is-source" type="button" data-action="source" data-source-type="${escapeAttr(entry.source_type || 'daily')}" data-source-id="${escapeAttr(entry.source_id)}">${escapeHTML(entry.record_date || shortId(entry.source_id))}</button>` : ''} ${escapeHTML(entry.observation || entry.text || entry.source_excerpt || '')}</li>`).join('');
        return `<article class="review-insight-card"><header><span class="review-meta-text">${escapeHTML(categoryLabel(item.category))}，${escapeHTML(statusLabel(item.status))}</span><button class="review-text-button" type="button" data-action="source" data-source-type="insight" data-source-id="${escapeAttr(item.id)}">来源</button></header><h4>${escapeHTML(item.statement)}</h4><details class="review-inline-evidence"><summary>证据与验证</summary><p>${escapeHTML(strength.label || '证据较少')}，独立来源 ${strength.independent_sources || item.source_ids?.length || 0} 条，反例 ${item.counter_evidence?.length || 0} 条${span.days ? `，跨 ${span.days} 天` : ''}</p>${evidence ? `<ul>${evidence}</ul>` : ''}<p class="review-ai-uncertainty">仍不确定：${escapeHTML(item.uncertainty_note || '需要更多现实记录')}</p>${item.verification_experiment ? `<p><strong>验证行动：</strong>${escapeHTML(item.verification_experiment)}</p>` : ''}<label class="review-field"><span>我的状态</span><select data-insight-status="${escapeAttr(item.id)}"><option value="pending"${['pending', 'candidate'].includes(item.status) ? ' selected' : ''}>待确认</option><option value="observing"${item.status === 'observing' ? ' selected' : ''}>继续观察</option><option value="accepted"${['accepted', 'recognized', 'verified'].includes(item.status) ? ' selected' : ''}>我认可</option><option value="rejected"${item.status === 'rejected' ? ' selected' : ''}>我不认可</option><option value="disproved"${item.status === 'disproved' ? ' selected' : ''}>已被证伪</option></select></label></details></article>`;
    }

    function categoryLabel(value) {
        return ({
            state: '状态', concern: '在意的事', person: '重要人物', interest: '兴趣',
            strength: '优势', thought_pattern: '思维模式', behavior_pattern: '行为模式',
            belief: '信念', fixed_idea: '固有观念', wish: '真实想法与愿望',
            important_event: '全年重要事件', inner_change: '内在变化', key_action: '关键行动',
            delayed_result: '延迟结果', important_person: '关键人物', belief_change: '信念变化',
            open_question: '待观察问题', next_experiment: '下一年验证方向',
        })[value] || value || '未分类';
    }

    function tierLabel(value) {
        return ({branch: '枝叶', trunk: '树干', root: '树根'})[value] || value || '未分层';
    }

    function statusLabel(value) {
        return ({pending: '待确认', candidate: '待确认', observing: '继续观察', accepted: '我认可', recognized: '我认可', verified: '我认可', rejected: '我不认可', disproved: '已被证伪'})[value] || value;
    }

    async function createInsight(form) {
        const formData = new FormData(form);
        const raw = Object.fromEntries(formData);
        const sourceIds = formData.getAll('source_id');
        const sourceEvidence = sourceIds.map((id) => {
            const source = state.insightSources.find((item) => item.id === id) || {};
            return {source_type: 'daily', source_id: id, record_date: source.review_date || '', source_excerpt: source.fact || source.quick_meaning || '', observation: ''};
        });
        const payload = {
            tier: raw.tier, level: Number(raw.level), category: raw.category, statement: raw.statement,
            evidence: [...sourceEvidence, ...parseLines(raw.evidence).map((text) => ({text}))],
            counter_evidence: parseLines(raw.counter_evidence).map((text) => ({text})),
            uncertainty: Number(raw.uncertainty), uncertainty_note: raw.uncertainty_note,
            verification_experiment: raw.verification_experiment,
            status: 'pending', source_ids: sourceIds.map((id) => ({type: 'daily', id})),
        };
        try {
            const data = await api('/api/reviews/insights', {method: 'POST', body: JSON.stringify(payload)});
            state.insights.unshift(data.record);
            renderInsights();
            setSaveState('saved', syncLabel(data.sync));
        } catch (error) { toast(error.message); }
    }

    async function updateInsightStatus(id, status) {
        const item = state.insights.find((entry) => entry.id === id);
        if (!item) return;
        const payload = {...item, status};
        delete payload.id; delete payload.user_id; delete payload.created_at; delete payload.updated_at; delete payload.ai_candidate_id;
        try {
            const data = await api(`/api/reviews/insights/${encodeURIComponent(id)}`, {method: 'PATCH', body: JSON.stringify(payload)});
            Object.assign(item, data.record);
            setSaveState('saved', syncLabel(data.sync));
            toast(`洞察状态已改为“${statusLabel(status)}”`);
        } catch (error) { toast(error.message); }
    }

    function renderGuide() {
        const guideCases = [
            ['工作和团队', '事实：评审会上三次讨论都回到同一个边界问题。', '观察：也许不是团队不配合，而是验收边界还没有被写清楚。', '实验：下一次评审前先写三条“不做什么”。'],
            ['人际关系', '事实：对方说“我需要晚一点回复”，当天没有继续对话。', '观察：我的失落是真实感受，但不能直接证明对方在回避我。', '实验：先询问对方适合继续谈的时间。'],
            ['情绪和自我怀疑', '事实：发布前我连续改了五次首页标题。', '观察：反复修改可能在降低不确定性，也可能是信息仍不清楚。', '实验：请一位目标用户复述他看到的价值。'],
            ['重要选择', '事实：我为两个方向各投入了两周，都产出过可用原型。', '观察：先比较真实投入后的能量和反馈，不急着给自己贴“摇摆”标签。', '实验：为每个方向再做一个同等成本的验证。'],
            ['兴趣发现', '事实：最近六条记录都主动提到课程结构与学习反馈。', '观察：课程设计可能是兴趣候选；仍需和外部奖励带来的兴奋区分。', '实验：安排一段不公开、不售卖的课程设计时间，记录体验。'],
            ['优势发现', '事实：三次协作中，别人都请我把复杂过程整理成步骤。', '观察：结构化表达可能是一项优势候选，而不是一次偶然称赞。', '实验：在不同场景再主动承担一次整理工作。'],
            ['思维模式', '事实：产品进入展示阶段时，我会新增“必须先完成”的功能。', '观察：我可能用扩范围推迟被评价，但也可能确有关键缺口。', '实验：新增需求前先写明不做它会造成的可观察风险。'],
            ['AI 创业方向', '事实：我在三次客户谈话后都更愿意讨论工作流，而不是单点模型能力。', '观察：真正关注的可能是可落地流程；证据还只来自少量访谈。', '实验：下一次只演示端到端工作流，记录客户追问。'],
        ];
        const caseMarkup = `<div class="review-case-grid">${guideCases.map(([title, fact, observation, experiment]) => `<article class="review-skill"><strong>${escapeHTML(title)}</strong><p><b>事实</b> · ${escapeHTML(fact)}</p><p><b>暂定观察</b> · ${escapeHTML(observation)}</p><p><b>验证行动</b> · ${escapeHTML(experiment)}</p></article>`).join('')}</div>`;
        const sections = [
            ['guide-value', '复盘的价值', `<p>复盘不是为了证明自己做错了什么，而是把经历变成可再次使用的资源。你不需要先想清楚宏大目标；从已经发生的小事开始就够了。</p><ul><li>记录帮助事实、感受和内在声音被看见。</li><li>周、月和年视图让零散经历在时间冷却后形成自己的资料库。</li><li>最后回到小型行动实验，用现实反馈继续修正理解。</li></ul>`],
            ['guide-misunderstanding', '常见误区', `<ul><li><strong>把复盘当成自我批评：</strong>会让记录只剩责备，而看不到可控部分。</li><li><strong>强迫积极：</strong>真正不认可的正向解释没有帮助。</li><li><strong>每次都要有结论：</strong>暂时无解、重复和矛盾本身也是资料。</li><li><strong>抽象后不行动：</strong>洞察需要由现实中的小实验检验。</li></ul>`],
            ['guide-record', '怎么记录', `<p>先写专有名词、实际说法、可观察动作和结果。再写当时真实的感受。记录可以轻、短、重复，也可以在中断后直接重新开始。</p><h3>最小记录</h3><p>一句事实 + 一句它对你的意义。完整矩阵可以以后再补。</p>`],
            ['guide-skills', '七个核心技能', `<div class="review-skill-grid">${[
                ['切分', '分开事实/感受、他人/自己、行动/结果、过去/现在。'],
                ['意义化', '寻找你真正认可的发现、学习、决断、喜悦或直觉。'],
                ['聚焦', '从许多记录里选择少数真正重要的线索。'],
                ['连接', '观察直接、间接或意外关系，同时保留不确定性。'],
                ['抽象', '提取共同点、已有资源与可迁移模式。'],
                ['具体化', '把认可的理解变成近期可做、可观察的实验。'],
                ['换视角', '从自己、他人或旁观者位置重新看同一事件。'],
            ].map(([name, text]) => `<div class="review-skill"><strong>${name}</strong><span>${text}</span></div>`).join('')}</div>`],
            ['guide-rhythm', '日 / 周 / 月 / 年', `<ul><li><strong>每日：</strong>多事件记录，先事实与意义，需要时再补当时/现在。</li><li><strong>每周：</strong>聚焦 → 连接 → 抽象 → 行动实验，通常 5–10 分钟即可开始。</li><li><strong>每月：</strong>内心、行动、结果和备注彼此独立，再观察跨月连续或反差。</li><li><strong>每年：</strong>回看十二个月来源，寻找年度关键词，但保留月份原文。</li></ul>`],
            ['guide-tree', '复盘树', `<p><strong>枝叶</strong>靠近状态、关注和重要的人；<strong>树干</strong>靠近兴趣、优势和反复模式；<strong>树根</strong>靠近信念、愿望和固定想法。越往根部越需要多时间、多来源与反例。</p>`],
            ['guide-perspective', '视角切换与自我对话', `<p>同一事件可以从自己的角度、对方的角度、旁观者的角度、未来自己的角度或更高层级重新观察。换视角不是替别人编造动机，而是提出新的问题。</p><ul><li>我当时真正想保护或获得什么？</li><li>如果只看可观察事实，旁观者会怎么描述？</li><li>三个月后的我会希望现在保留哪条证据？</li><li>哪些部分仍在我的控制范围内？</li></ul>`],
            ['guide-habit', '如何坚持而不惩罚自己', `<ul><li>把工具放在容易打开的位置，用碎片开始。</li><li>允许和可信任的人一起复盘，但结论仍由你确认。</li><li>责备自己或他人时，切到“观察模式”：发生了什么？我现在还能控制什么？</li><li>中断不代表失败；下一条记录就是新的起点。</li></ul>`],
            ['guide-case', '案例库：从事实回到行动', `<p>这些案例只示范填写逻辑，不替你得出结论。每个“观察”都可以被后续记录修正。</p>${caseMarkup}`],
        ];
        elements.guideContent.innerHTML = `<div class="review-guide-layout"><nav class="review-guide-nav" aria-label="指南目录">${sections.map(([id, title]) => `<a href="#${id}">${title}</a>`).join('')}</nav><div class="review-guide-content">${sections.map(([id, title, content]) => `<article class="review-guide-card" id="${id}"><h2>${title}</h2>${content}</article>`).join('')}</div></div>`;
        state.guideRendered = true;
    }

    function openGuide() {
        if (!state.guideRendered) renderGuide();
        openDialog(elements.guideDialog);
    }

    function openHelp(key) {
        const item = HELP[key];
        if (!item) return;
        elements.helpTitle.textContent = item.title;
        elements.helpContent.innerHTML = `<p>${escapeHTML(item.body)}</p><div class="review-causality-note"><strong>例子：</strong><span>${escapeHTML(item.example)}</span></div>`;
        openDialog(elements.helpDialog);
    }

    async function openSource(type, id) {
        elements.sourceContent.innerHTML = '<div class="review-loading">正在读取原始来源…</div>';
        openDialog(elements.sourceDialog);
        try {
            const data = await api(`/api/reviews/source/${encodeURIComponent(type)}/${encodeURIComponent(id)}`);
            const record = data.record || {};
            elements.sourceContent.innerHTML = `<div class="review-causality-note"><strong>${escapeHTML(type)}</strong><span>${escapeHTML(id)} · 所有上层结论都应能回到这里。</span></div><pre class="review-source-json">${escapeHTML(JSON.stringify(record, null, 2))}</pre>${data.sources?.length ? `<h3>上游来源</h3><div class="review-source-list">${data.sources.map((source) => `<button class="review-source-link" type="button" data-action="source" data-source-type="${escapeAttr(source.type)}" data-source-id="${escapeAttr(source.id)}">${escapeHTML(source.type)} · ${escapeHTML(source.id)}</button>`).join('')}</div>` : ''}`;
        } catch (error) {
            elements.sourceContent.innerHTML = renderError(error.message);
        }
    }

    function aiScopeFor(type) {
        if (state.tab === 'weekly') {
            let ids = selectedWeeklyIds();
            if (!ids.length) ids = (state.weekly?.daily_events || []).map((item) => item.id).slice(0, 20);
            return ids.map((id) => ({type: 'daily', id}));
        }
        if (state.tab === 'monthly') {
            return (state.monthly?.daily_events || []).slice(0, 30).map((item) => ({type: 'daily', id: item.id}));
        }
        if (state.tab === 'annual') {
            return (state.annual?.months || []).filter((item) => item.id).map((item) => ({type: 'monthly', id: item.id}));
        }
        if (state.tab === 'daily') {
            return (state.daily?.items || []).map((item) => ({type: 'daily', id: item.id}));
        }
        return [];
    }

    function aiScopeLabel(item) {
        if (item.type === 'monthly') {
            const month = (state.annual?.months || []).find((entry) => entry.id === item.id)
                || (state.monthly?.monthly_reviews || []).find((entry) => entry.id === item.id);
            return month?.month_key || shortId(item.id);
        }
        const daily = [
            ...(state.daily?.items || []),
            ...(state.weekly?.daily_events || []),
            ...(state.monthly?.daily_events || []),
            ...(state.insightSources || []),
        ].find((entry) => entry.id === item.id);
        if (!daily) return shortId(item.id);
        const title = daily.title || compactText(daily.fact || daily.quick_meaning, 28) || '未命名事件';
        return `${daily.review_date || ''} · ${title}`.replace(/^ · /, '');
    }

    async function openAI(analysisType, sourceId = '') {
        let scope = sourceId ? [{type: 'daily', id: sourceId}] : aiScopeFor(analysisType);
        if (analysisType === 'inner_insight' && !scope.length) {
            try {
                const recent = await api('/api/reviews/search?record_type=daily&limit=20');
                scope = (recent.items || []).map((item) => ({type: 'daily', id: item.id}));
            } catch (error) { return toast(error.message); }
        }
        if (!scope.length) return toast('当前范围还没有可交给 AI 的来源记录。');
        state.aiContext = {analysisType, scope};
        elements.aiContent.innerHTML = `<section class="review-ai-scope"><h3>本次目的</h3><p>${escapeHTML(AI_PURPOSES[analysisType] || '')}</p></section><h3>将读取 ${scope.length} 条明确来源</h3><div class="review-emotions">${scope.map((item) => `<span class="review-chip" title="${escapeAttr(item.id)}">${escapeHTML(item.type)} · ${escapeHTML(aiScopeLabel(item))}</span>`).join('')}</div><div class="review-causality-note"><strong>边界：</strong><span>AI 结果只保存为候选；不会自动诊断、强迫积极，也不会在你确认前写入正式洞察。</span></div>`;
        elements.aiActions.innerHTML = '<button class="review-button review-button-ghost" type="button" data-dialog-close>取消</button><button class="review-button review-button-primary" type="button" data-action="run-ai">确认范围并调用 AI</button>';
        openDialog(elements.aiDialog);
    }

    async function runAI() {
        const context = state.aiContext;
        if (!context) return;
        elements.aiContent.insertAdjacentHTML('beforeend', '<div class="review-loading" id="review-ai-loading">AI 正在整理证据、反例和不确定性…</div>');
        elements.aiActions.innerHTML = '';
        try {
            const data = await api('/api/reviews/ai/analyze', {
                method: 'POST',
                body: JSON.stringify({analysis_type: context.analysisType, purpose: AI_PURPOSES[context.analysisType], scope: context.scope}),
            });
            renderAICandidates(data.items || []);
        } catch (error) {
            elements.aiContent.innerHTML += `<div class="review-causality-note"><strong>调用失败：</strong><span>${escapeHTML(error.message)}</span></div>`;
            elements.aiActions.innerHTML = '<button class="review-button review-button-ghost" type="button" data-dialog-close>关闭</button><button class="review-button review-button-primary" type="button" data-action="run-ai">重试</button>';
        }
    }

    function renderAICandidates(items) {
        elements.aiContent.innerHTML = `<section class="review-ai-scope"><h3>AI 候选 · 仍待你确认</h3><p>可以修改陈述、确认成洞察，或直接忽略。来源 ID 已由服务端校验。</p></section><div class="review-ai-candidates">${items.map((item) => {
            const candidate = item.candidate || {};
            return `<article class="review-ai-candidate" data-candidate-id="${escapeAttr(item.id)}" data-candidate="${escapeAttr(JSON.stringify(candidate))}"><span class="review-chip is-ai">AI 候选 · ${escapeHTML(categoryLabel(candidate.category))} · ${escapeHTML(tierLabel(candidate.tier))} L${candidate.level}</span><label class="review-field"><span>候选陈述（可编辑）</span><textarea data-ai-statement>${escapeHTML(candidate.statement)}</textarea></label><ul class="review-ai-evidence">${(candidate.evidence || []).map((evidence) => {
                const sourceType = state.aiContext?.scope.find((source) => source.id === evidence.source_id)?.type || 'daily';
                return `<li><button class="review-chip is-source" type="button" data-action="source" data-source-type="${escapeAttr(sourceType)}" data-source-id="${escapeAttr(evidence.source_id)}">${escapeHTML(shortId(evidence.source_id))}</button> ${escapeHTML(evidence.observation)}</li>`;
            }).join('')}</ul><p><strong>证据强度：</strong>${escapeHTML(candidate.evidence_strength?.label || '证据较少')} · 独立来源 ${candidate.evidence_strength?.independent_sources || candidate.evidence?.length || 0} 条</p><p class="review-ai-uncertainty"><strong>仍不确定：</strong>${escapeHTML(candidate.uncertainty_note || '需要更多记录')} · 反例：${escapeHTML((candidate.counter_evidence || []).join('；') || '尚未找到明确反例')}</p><p><strong>验证实验：</strong>${escapeHTML(candidate.verification_experiment || '尚未提出')}</p><div class="review-card-actions"><button class="review-button review-button-small review-button-ghost" type="button" data-action="dismiss-ai">忽略</button><button class="review-button review-button-small review-button-primary" type="button" data-action="confirm-ai">确认候选</button><button class="review-button review-button-small review-button-primary" type="button" data-action="confirm-ai-insight">确认并加入洞察树</button></div></article>`;
        }).join('')}</div>`;
        elements.aiActions.innerHTML = '<button class="review-button review-button-ghost" type="button" data-dialog-close>完成</button>';
    }

    async function confirmAI(card, createInsight) {
        const id = card.dataset.candidateId;
        const candidate = JSON.parse(card.dataset.candidate || '{}');
        candidate.statement = card.querySelector('[data-ai-statement]').value;
        try {
            const data = await api(`/api/reviews/ai-candidates/${encodeURIComponent(id)}/confirm`, {
                method: 'POST', body: JSON.stringify({content: candidate, create_insight: createInsight}),
            });
            card.innerHTML = `<div class="review-causality-note"><strong>已由你确认：</strong><span>${escapeHTML(data.candidate.confirmed_content.statement || '')}${data.insight ? ' · 已加入洞察树' : ''}${data.applied_to ? ' · 已追加到年度总结' : ''}</span></div>`;
            if (data.applied_to && state.tab === 'annual') await loadAnnual();
            toast(createInsight ? '候选已确认并加入洞察树' : data.applied_to ? '候选已确认并追加到年度总结' : '候选已确认');
        } catch (error) { toast(error.message); }
    }

    async function dismissAI(card) {
        try {
            await api(`/api/reviews/ai-candidates/${encodeURIComponent(card.dataset.candidateId)}/dismiss`, {method: 'POST'});
            card.remove();
            toast('AI 候选已忽略，不会改变正式记录');
        } catch (error) { toast(error.message); }
    }

    async function searchReviews(form) {
        const values = Object.fromEntries(new FormData(form));
        const query = new URLSearchParams();
        Object.entries(values).forEach(([key, value]) => { if (value) query.append(key, value); });
        elements.searchResults.innerHTML = '<div class="review-loading">正在搜索…</div>';
        try {
            const data = await api(`/api/reviews/search?${query.toString()}`);
            elements.searchResults.innerHTML = data.items.length ? data.items.map((item) => `<button class="review-search-result" type="button" data-action="source" data-source-type="${escapeAttr(item.record_type)}" data-source-id="${escapeAttr(item.id)}"><header><strong>${escapeHTML(searchTitle(item))}</strong><span class="review-chip">${escapeHTML(recordTypeLabel(item.record_type))}</span></header><p>${escapeHTML(searchPreview(item))}</p></button>`).join('') : '<div class="review-empty review-search-empty"><div><p>没有找到符合条件的记录。</p></div></div>';
        } catch (error) { elements.searchResults.innerHTML = renderError(error.message); }
    }

    function searchTitle(item) {
        return item.title || item.statement || item.month_key || item.week_start || item.year_key || item.review_date || '复盘记录';
    }

    function searchPreview(item) {
        const candidates = [
            item.fact,
            item.quick_meaning,
            item.current_understanding,
            item.statement,
            item.summary,
            item.review_summary,
            item.what,
            item.why,
            item.result,
            item.first_step,
        ];
        for (const candidate of candidates) {
            const value = Array.isArray(candidate)
                ? candidate.map((entry) => typeof entry === 'string' ? entry : entry?.text || entry?.title || entry?.statement || '').filter(Boolean).join(' · ')
                : candidate;
            const preview = compactText(value, 180);
            if (preview) return preview;
        }
        return `点击查看这条${recordTypeLabel(item.record_type)}记录的完整内容`;
    }

    function recordTypeLabel(value) {
        return ({daily: '每日', weekly: '周度', monthly: '月度', annual: '年度', insight: '洞察', experiment: '行动实验'})[value] || value;
    }

    function groupBy(items, getter) {
        return items.reduce((result, item) => {
            const key = getter(item);
            (result[key] ||= []).push(item);
            return result;
        }, {});
    }

    function weekdayLabel(value) {
        const labels = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];
        return labels[new Date(`${value}T12:00:00`).getDay()];
    }

    function shortId(id) { return String(id || '').length > 14 ? `${String(id).slice(0, 10)}…` : String(id || ''); }

    function formatTime(value) {
        if (!value) return '尚未保存';
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return String(value);
        return new Intl.DateTimeFormat('zh-CN', {month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit'}).format(date);
    }

    function shiftPeriod(direction) {
        if (state.tab === 'daily' || state.tab === 'weekly') {
            const date = new Date(`${state.date}T12:00:00`);
            date.setDate(date.getDate() + direction * (state.tab === 'weekly' ? 7 : 1));
            state.date = localISODate(date);
        } else if (state.tab === 'monthly') {
            const [year, month] = state.month.split('-').map(Number);
            const date = new Date(year, month - 1 + direction, 1, 12);
            state.month = localISODate(date).slice(0, 7);
        } else if (state.tab === 'annual') state.year = String(Number(state.year) + direction);
        updateTabChrome();
        loadCurrentView();
    }

    async function primaryAction() {
        if (state.tab === 'daily') return addDaily();
        if (state.tab === 'weekly') return saveWeekly();
        if (state.tab === 'monthly') return saveMonthly();
        if (state.tab === 'annual') return saveAnnual();
        if (state.tab === 'insights') {
            renderInsights(true);
            return document.getElementById('review-insight-create')?.scrollIntoView({behavior: 'smooth'});
        }
        return selectTab('daily');
    }

    async function savePreferences() {
        try {
            state.preferences = await api('/api/reviews/preferences', {
                method: 'PUT', body: JSON.stringify({newbie_mode: elements.newbie.checked}),
            });
            document.body.classList.toggle('newbie-off', !elements.newbie.checked);
            toast(elements.newbie.checked ? '新手提示已开启' : '新手提示已隐藏');
        } catch (error) { toast(error.message); }
    }

    function handleViewClick(event) {
        const button = event.target.closest('button, [data-action]');
        if (!button) return;
        const action = button.dataset.action;
        if (button.dataset.help) return openHelp(button.dataset.help);
        if (button.dataset.ai) return openAI(button.dataset.ai, button.dataset.aiSourceId || '');
        if (action === 'retry') return loadCurrentView();
        if (action === 'add-daily') return addDaily();
        if (action === 'source') return openSource(button.dataset.sourceType, button.dataset.sourceId);
        const dailyCard = button.closest('[data-event-id]');
        if (action === 'delete-daily') return deleteDaily(dailyCard);
        if (action === 'duplicate-daily') return duplicateDaily(dailyCard);
        if (action === 'choose-emotions') return openEmotionPicker(dailyCard);
        if (action === 'remove-focus') {
            const id = button.closest('[data-focus-id]').dataset.focusId;
            const checkbox = elements.view.querySelector(`[data-focus-source="${CSS.escape(id)}"]`);
            if (checkbox) checkbox.checked = false;
            return updateWeeklyFocus(id, false);
        }
        if (action === 'delete-connection') return deleteConnection(button.dataset.id);
        if (action === 'edit-connection') return editConnection(button.dataset.id);
        if (action === 'cancel-connection-edit') return cancelConnectionEdit(button.closest('form'));
        if (action === 'delete-experiment') return deleteExperiment(button.dataset.id);
    }

    function activeConnections() {
        return state.tab === 'monthly' ? state.monthly.connections : state.weekly.connections;
    }

    function activeConnectionForm() {
        return document.getElementById(state.tab === 'monthly' ? 'review-month-connection-form' : 'review-connection-form');
    }

    function editConnection(id) {
        const item = activeConnections().find((entry) => entry.id === id);
        const form = activeConnectionForm();
        if (!item || !form) return;
        form.dataset.editingId = id;
        ['source_id', 'target_id', 'title', 'connection_type', 'direction', 'description'].forEach((name) => {
            const input = form.elements.namedItem(name);
            if (input) input.value = item[name] || (name === 'source_id' ? item.source_ids?.[0] : name === 'target_id' ? item.source_ids?.[1] : '');
        });
        const cancel = form.querySelector('[data-action="cancel-connection-edit"]');
        if (cancel) cancel.hidden = false;
        const submit = form.querySelector('[type="submit"]');
        if (submit) submit.textContent = '保存连接修改';
        form.scrollIntoView({behavior: 'smooth', block: 'center'});
    }

    function cancelConnectionEdit(form) {
        if (!form) return;
        delete form.dataset.editingId;
        form.reset();
        const cancel = form.querySelector('[data-action="cancel-connection-edit"]');
        if (cancel) cancel.hidden = true;
        const submit = form.querySelector('[type="submit"]');
        if (submit) submit.textContent = form.dataset.periodType === 'monthly' ? '添加方向连接' : '添加连接';
    }

    async function deleteConnection(id) {
        if (!window.confirm('删除这条连接记录？')) return;
        try {
            await api(`/api/reviews/connections/${encodeURIComponent(id)}`, {method: 'DELETE'});
            if (state.tab === 'monthly') {
                state.monthly.connections = state.monthly.connections.filter((item) => item.id !== id);
                renderMonthly();
            } else {
                state.weekly.connections = state.weekly.connections.filter((item) => item.id !== id);
                renderWeekly();
            }
        } catch (error) { toast(error.message); }
    }

    async function deleteExperiment(id) {
        if (!window.confirm('删除这个行动实验？')) return;
        try {
            await api(`/api/reviews/action-experiments/${encodeURIComponent(id)}`, {method: 'DELETE'});
            state.weekly.experiments = state.weekly.experiments.filter((item) => item.id !== id);
            renderWeekly();
        } catch (error) { toast(error.message); }
    }

    function handleViewInput(event) {
        const card = event.target.closest('[data-event-id]');
        if (card && event.target.matches('[data-field], [data-list-field], [data-meaning-type]')) scheduleDailySave(card);
        if (event.target.id === 'review-annual-filter') renderAnnual(event.target.value);
    }

    function handleViewChange(event) {
        if (event.target.matches('[data-meaning-type]')) {
            const card = event.target.closest('[data-event-id]');
            const choices = [...card.querySelectorAll('[data-meaning-type]')];
            if (event.target.value === '' && event.target.checked) choices.filter((item) => item !== event.target).forEach((item) => { item.checked = false; });
            else if (event.target.checked) choices.filter((item) => item.value === '').forEach((item) => { item.checked = false; });
            scheduleDailySave(card);
        }
        if (event.target.matches('[data-focus-source]')) updateWeeklyFocus(event.target.dataset.focusSource, event.target.checked);
        if (event.target.matches('[data-insight-status]')) updateInsightStatus(event.target.dataset.insightStatus, event.target.value);
    }

    function handleViewSubmit(event) {
        if (event.target.id === 'review-connection-form') { event.preventDefault(); createConnection(event.target); }
        if (event.target.id === 'review-month-connection-form') { event.preventDefault(); createConnection(event.target); }
        if (event.target.id === 'review-experiment-form') { event.preventDefault(); createExperiment(event.target); }
        if (event.target.matches('[data-experiment-review]')) { event.preventDefault(); reviewExperiment(event.target); }
        if (event.target.id === 'review-insight-form') { event.preventDefault(); createInsight(event.target); }
    }

    function handleViewKeydown(event) {
        if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
            const card = event.target.closest('[data-event-id]');
            if (card) { event.preventDefault(); saveDailyCard(card); }
        }
    }

    function handleDragStart(event) {
        const item = event.target.closest('[data-focus-id]');
        if (!item) return;
        state.draggedFocusId = item.dataset.focusId;
        event.dataTransfer.effectAllowed = 'move';
    }

    function handleDragOver(event) {
        const target = event.target.closest('[data-focus-id]');
        if (!target || !state.draggedFocusId || target.dataset.focusId === state.draggedFocusId) return;
        event.preventDefault();
        const list = target.parentElement;
        const dragged = list.querySelector(`[data-focus-id="${CSS.escape(state.draggedFocusId)}"]`);
        if (dragged) list.insertBefore(dragged, target);
    }

    function bindEvents() {
        document.querySelectorAll('[data-review-section]').forEach((link) => link.addEventListener('click', (event) => {
            if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
            event.preventDefault();
            selectTab(link.dataset.reviewSection);
        }));
        elements.primary.addEventListener('click', primaryAction);
        elements.guideOpen.addEventListener('click', openGuide);
        elements.periodPrev.addEventListener('click', () => shiftPeriod(-1));
        elements.periodNext.addEventListener('click', () => shiftPeriod(1));
        elements.periodToday.addEventListener('click', () => {
            state.date = today; state.month = today.slice(0, 7); state.year = today.slice(0, 4);
            updateTabChrome(); loadCurrentView();
        });
        elements.periodInput.addEventListener('change', () => {
            if (state.tab === 'daily' || state.tab === 'weekly') state.date = elements.periodInput.value;
            else if (state.tab === 'monthly') state.month = elements.periodInput.value;
            else if (state.tab === 'annual') state.year = elements.periodInput.value;
            loadCurrentView();
        });
        elements.newbie.addEventListener('change', savePreferences);
        elements.searchOpen.addEventListener('click', () => openDialog(elements.searchDialog));
        elements.searchForm.addEventListener('submit', (event) => { event.preventDefault(); searchReviews(event.target); });
        elements.view.addEventListener('click', handleViewClick);
        elements.view.addEventListener('input', handleViewInput);
        elements.view.addEventListener('change', handleViewChange);
        elements.view.addEventListener('submit', handleViewSubmit);
        elements.view.addEventListener('keydown', handleViewKeydown);
        elements.view.addEventListener('dragstart', handleDragStart);
        elements.view.addEventListener('dragover', handleDragOver);
        document.addEventListener('click', (event) => {
            const close = event.target.closest('[data-dialog-close]');
            if (close) closeDialog(close.closest('dialog'));
            const source = event.target.closest('[data-action="source"]');
            if (source && !elements.view.contains(source)) openSource(source.dataset.sourceType, source.dataset.sourceId);
            const action = event.target.closest('[data-action]')?.dataset.action;
            if (action === 'run-ai') runAI();
            const candidate = event.target.closest('[data-candidate-id]');
            if (action === 'confirm-ai') confirmAI(candidate, false);
            if (action === 'confirm-ai-insight') confirmAI(candidate, true);
            if (action === 'dismiss-ai') dismissAI(candidate);
        });
        elements.emotionGrid.addEventListener('click', (event) => {
            const button = event.target.closest('[data-emotion]');
            if (!button) return;
            const name = button.dataset.emotion;
            const selected = !state.emotionSelection.includes(name);
            state.emotionSelection = selected
                ? [...state.emotionSelection, name]
                : state.emotionSelection.filter((item) => item !== name);
            button.setAttribute('aria-pressed', String(selected));
        });
        elements.emotionCustom.addEventListener('keydown', (event) => {
            if (event.key === 'Enter') { event.preventDefault(); addCustomEmotion(); }
        });
        elements.emotionApply.addEventListener('click', applyEmotions);
        window.addEventListener('popstate', () => {
            const next = window.location.pathname.match(/^\/review\/([^/]+)\/?$/)?.[1];
            if (TABS.includes(next) && next !== state.tab) {
                state.tab = next;
                updateTabChrome();
                loadCurrentView();
            }
        });
    }

    async function init() {
        bindEvents();
        const canonical = `/review/${state.tab}${window.location.search}`;
        if (`${window.location.pathname}${window.location.search}${window.location.hash}` !== canonical) {
            history.replaceState(null, '', canonical);
        }
        updateTabChrome();
        await loadPreferences();
        await loadCurrentView();
        if (legacyGuideRequested) openGuide();
        if (state.initialSource) {
            const source = state.initialSource;
            state.initialSource = null;
            await openSource(source.type, source.id);
        }
    }

    init();
})();
