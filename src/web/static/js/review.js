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
    const TAB_KICKERS = {
        daily: '今天', weekly: '本周', monthly: '全年视图',
        annual: '回看这一年', insights: '来自长期记录',
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
        emotion: {
            title: '不知道怎么表达情绪？',
            body: '先从最接近的词开始，不必一次选得很准确。几种看似矛盾的感受也可以同时存在。',
            example: '既期待接下来的机会，也担心自己准备不足，可以同时选择“期待”和“恐惧”，再用自己的话补充。',
            image: '/static/images/review/emotion-wheel.png',
            image_alt: '普鲁奇克情绪轮盘，展示八种基本情绪、强弱变化与相邻情绪形成的复合感受',
            image_caption: '《复盘自己：从记录到蜕变的行动指南》图 3-4',
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

    const REVIEW_EXAMPLES = {
        daily: {
            title: '每日复盘案例',
            subject: '团队氛围低迷时，找到自己能做的事',
            context: '一位实践者感觉团队抱怨变多，却一直不知道从哪里开始改变。',
            sections: [
                {
                    title: '事件',
                    fields: [
                        ['什么事件让你内心有所触动？', '业绩不佳，团队氛围低迷。抱怨与相互指责的声音越来越多。'],
                    ],
                },
                {
                    title: '第一步 · 如实记录',
                    fields: [
                        ['事件发生时，我在想什么、感受什么？', '为什么大家这么爱抱怨？真让人烦躁。'],
                        ['当时我采取了什么行动？', '没有采取行动。'],
                        ['这个行动带来了什么结果？', '抱怨的人越来越多。'],
                    ],
                },
                {
                    title: '第二步 · 意义重塑',
                    fields: [
                        ['回顾后，我重新注意到了什么？', '我看到大家可能觉得自己的努力被浪费，因此感到无力。我可以更多地肯定成员的努力。'],
                        ['从现在开始，我可以采取什么具体行动？', '在部门例会上介绍成员的新尝试，营造一起点赞的氛围。'],
                        ['这些行动可能会带来怎样的结果？', '发言的成员感到开心，团队逐渐恢复良好氛围。'],
                    ],
                },
            ],
        },
        weekly: {
            title: '周度复盘案例',
            subject: '从一本书和一封邮件开始的联结',
            context: '一位技术工作者读到一本好书后，给素未谋面的作者写信，后来促成了一场约 80 人参加的内部分享会。',
            sections: [
                {
                    title: '01 · 聚焦',
                    fields: [
                        ['本周最影响我的三件事', '读到一本把复杂技术讲清楚的书；给退休专家发出真诚邮件；原本约 4 人的分享会扩大到约 80 人。'],
                    ],
                },
                {
                    title: '02 · 找联系',
                    fields: [
                        ['这些事情之间的联系', '被内容打动 → 主动表达受到的启发 → 得到专家回应 → 分享机会扩大 → 同事开始来请教。'],
                    ],
                },
                {
                    title: '03 · 看模式',
                    fields: [
                        ['这周让我更了解自己的什么？', '当我把真实的感动具体表达出来，并先发出一次邀请时，知识、他人与自己的专业信心会产生新的联结。'],
                    ],
                },
                {
                    title: '04 · 具体化',
                    fields: [
                        ['下一次，我准备怎么做？', '遇到真正有价值的内容时，写一封说明具体触动与邀请目的的邮件，先尝试组织一次小范围分享。'],
                    ],
                },
            ],
        },
        monthly: {
            title: '月度复盘案例',
            subject: '4 月的想法，在之后几个月形成结果',
            context: '原书的年度表把“内心、行动、结果、备注”分别记录，再回看跨月发生的联结，不强迫它们在同一个月形成因果。',
            sections: [
                {
                    title: '4 月',
                    fields: [
                        ['内心', '工作坊也许就是我可以为之努力一生的工作；对离职者增多感到焦虑。'],
                        ['行动', '在部门提议设立新媒体部门；购入自行车，开始运动。'],
                        ['结果', '领导力工作坊大受欢迎，好评如潮。'],
                        ['回看后想留下的话', '对今后的职业发展感到迷茫。'],
                    ],
                },
                {
                    title: '跨月联结',
                    fields: [
                        ['从想法到结果', '4 月提出设立新媒体部门 → 6 月新部门正式启动 → 8 月新媒体部门在公司会议上获得好评。'],
                    ],
                },
            ],
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
        dailyEventId: null,
        weekly: null,
        weeklyStep: 1,
        weeklyDrafts: new Map(),
        monthly: null,
        monthlyDrafts: new Map(),
        annual: null,
        annualDrafts: new Map(),
        draftVersions: new Map(),
        savesInFlight: new Set(),
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
        workspace: document.querySelector('.review-workspace'),
        pageHeading: document.querySelector('.review-page-heading'),
        pageActions: document.querySelector('.review-page-actions'),
        contextBar: document.querySelector('.review-context-bar'),
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
        exampleDialog: document.getElementById('review-example-dialog'),
        exampleTitle: document.getElementById('review-example-title'),
        exampleContent: document.getElementById('review-example-content'),
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

    function toast(message, duration = 3200) {
        clearTimeout(state.toastTimer);
        elements.toast.textContent = message;
        elements.toast.hidden = false;
        state.toastTimer = setTimeout(() => { elements.toast.hidden = true; }, duration);
    }

    function openDialog(dialog) {
        if (dialog && !dialog.open) dialog.showModal();
    }

    function closeDialog(dialog) {
        if (dialog?.open) dialog.close();
    }

    function openSearch() {
        document.querySelectorAll('.review-more-menu[open]').forEach((menu) => menu.removeAttribute('open'));
        openDialog(elements.searchDialog);
        requestAnimationFrame(() => elements.searchForm.elements.keyword.focus({preventScroll: true}));
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

    function draftVersionKey(type, key) { return `${type}:${key}`; }

    function draftVersion(type, key) {
        return state.draftVersions.get(draftVersionKey(type, key)) || 0;
    }

    function markDraftChanged(type, key) {
        const versionKey = draftVersionKey(type, key);
        state.draftVersions.set(versionKey, (state.draftVersions.get(versionKey) || 0) + 1);
    }

    function clearDraftVersion(type, key) {
        state.draftVersions.delete(draftVersionKey(type, key));
    }

    function updateTabChrome() {
        elements.workspace.dataset.reviewTab = state.tab;
        if (state.tab === 'daily') {
            if (elements.periodControls.parentElement !== elements.contextBar) {
                elements.contextBar.prepend(elements.periodControls);
            }
            if (elements.saveState.parentElement !== elements.contextBar) {
                elements.contextBar.append(elements.saveState);
            }
        } else {
            if (elements.periodControls.parentElement !== elements.pageActions) {
                elements.pageActions.insertBefore(elements.periodControls, elements.primary);
            }
            if (elements.saveState.parentElement !== elements.pageHeading) {
                elements.pageHeading.append(elements.saveState);
            }
        }
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
            annual: '保存年度总结', insights: '整理一条洞察',
        };
        elements.primary.textContent = actions[state.tab];
        elements.primary.hidden = state.tab === 'daily';
        elements.title.textContent = TAB_LABELS[state.tab];
        elements.description.textContent = TAB_KICKERS[state.tab];
        elements.description.hidden = state.tab === 'daily';
        const currentPeriod = state.tab === 'daily' || state.tab === 'weekly'
            ? state.date === today
            : state.tab === 'monthly'
                ? state.month === today.slice(0, 7)
                : state.tab === 'annual'
                    ? state.year === today.slice(0, 4)
                    : true;
        elements.periodToday.hidden = currentPeriod;
        document.title = `${TAB_LABELS[state.tab]} · LearnFlux`;
        document.querySelector('.topbar-page-title').textContent = `复盘 / ${TAB_LABELS[state.tab]}`;
    }

    async function selectTab(tab, {replace = false} = {}) {
        if (!TABS.includes(tab)) tab = 'daily';
        if (state.tab === 'weekly') syncWeeklyDraftFromView();
        if (state.tab === 'monthly') captureMonthlyDraft();
        if (state.tab === 'annual') captureAnnualDraft();
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
        if (!state.daily.items.some((item) => item.id === state.dailyEventId)) {
            state.dailyEventId = state.daily.items[0]?.id || null;
        }
        renderDaily();
        const restored = state.daily.items.some((item) => item._draft);
        setSaveState(
            restored ? 'saving' : 'saved',
            restored ? `已恢复本地草稿 · 今天 ${state.daily.total} 件` : `今天已记录 ${state.daily.total} 件`,
        );
    }

    function activeDailyItem() {
        const items = state.daily?.items || [];
        return items.find((item) => item.id === state.dailyEventId) || items[0] || null;
    }

    function renderDaily() {
        const items = state.daily?.items || [];
        if (!items.length) {
            state.dailyEventId = null;
            elements.view.innerHTML = `<div class="review-empty"><div><h2>今天还没有复盘记录</h2><p>选一件触动你的事，从客观事实开始填写。</p><div class="review-empty-actions"><button class="review-button review-button-primary" type="button" data-action="add-daily">记录第一件事</button><button class="review-example-trigger" type="button" data-action="open-example">查看填写案例</button></div></div></div>`;
            return;
        }
        const current = activeDailyItem();
        state.dailyEventId = current.id;
        elements.view.innerHTML = `<div class="review-daily-workspace">
            ${renderDailyCard(current, items)}
        </div>`;
    }

    function emotionsMarkup(values) {
        const names = (values || []).map((value) => typeof value === 'string' ? value : value?.name).filter(Boolean);
        return names.map((name) => `<span class="review-chip">${escapeHTML(name)}</span>`).join('');
    }

    function renderDailyCard(item, items = []) {
        const past = item.past || {};
        const present = item.present || {};
        const savedAt = item._draft ? '本地草稿' : formatTime(item.updated_at);
        const assistReady = Boolean(String(item.fact || '').trim() && String(past.thoughts || '').trim());
        const thoughtsId = `review-past-thoughts-${escapeAttr(item.id)}`;
        const meaningId = `review-present-meaning-${escapeAttr(item.id)}`;
        const currentIndex = Math.max(0, items.findIndex((record) => record.id === item.id));
        const pager = items.length > 1 ? `<nav class="review-record-pager" aria-label="切换今日记录">
            <button type="button" data-action="shift-daily" data-shift="-1" aria-label="上一条记录"${currentIndex === 0 ? ' disabled' : ''}>←</button>
            <span>第 ${currentIndex + 1} / ${items.length} 条</span>
            <button type="button" data-action="shift-daily" data-shift="1" aria-label="下一条记录"${currentIndex === items.length - 1 ? ' disabled' : ''}>→</button>
        </nav>` : '';
        return `<article class="review-event-card review-daily-template" data-event-id="${escapeAttr(item.id)}">
            <section class="review-event-prompt">
                <header>
                    <div><span>事件</span><div class="review-prompt-title"><h2>什么事件让你内心有所触动？</h2><button class="review-help-trigger" type="button" data-help="fact" aria-label="查看客观事实填写帮助">?</button></div><p>只写客观发生的事，不加入感受或评价 <button class="review-example-trigger" type="button" data-action="open-example">查看填写案例</button></p></div>
                    <div class="review-event-actions">
                        <button class="review-icon-button review-event-tool" type="button" data-action="open-search" aria-label="搜索复盘记录" title="搜索记录"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"></circle><path d="m20 20-4-4"></path></svg></button>
                        <button class="review-icon-button review-event-tool" type="button" data-action="add-daily" aria-label="记录另一件事" title="记录另一件事"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"></path></svg></button>
                        <details class="review-more-menu review-event-menu">
                            <summary aria-label="记录操作">•••</summary>
                            <div><button class="is-danger" type="button" data-action="delete-daily">删除记录</button></div>
                        </details>
                    </div>
                </header>
                ${pager}
                <textarea rows="3" data-field="fact" aria-label="什么事件让你内心有所触动？">${escapeHTML(item.fact)}</textarea>
            </section>
            <div class="review-daily-columns">
                <section class="review-daily-lane is-past">
                    <header><span>第一步</span><h3>如实记录</h3></header>
                    <div class="review-method-flow">
                        <div class="review-template-field">
                            <div class="review-template-heading"><label for="${thoughtsId}">事件发生时，我在想什么、感受什么？</label><button class="review-help-trigger" type="button" data-help="emotion" aria-label="不知道怎么表达情绪时查看情绪轮盘">?</button></div>
                            <small>不修饰，也不判断好坏</small>
                            <textarea id="${thoughtsId}" rows="4" data-field="past.thoughts">${escapeHTML(past.thoughts)}</textarea>
                            <div class="review-field-tools review-emotion-tools"><div class="review-emotions" data-emotion-list>${emotionsMarkup(item.emotions)}</div><button class="review-inline-action" type="button" data-action="choose-emotions">选择情绪词</button></div>
                        </div>
                        <label class="review-template-field"><strong>当时我采取了什么行动？</strong><small>如果没有，可以留空</small><textarea rows="3" data-field="past.action">${escapeHTML(past.action)}</textarea></label>
                        <label class="review-template-field"><strong>这个行动带来了什么结果？</strong><small>如果还没有明显结果，可以留空</small><textarea rows="3" data-field="past.result">${escapeHTML(past.result)}</textarea></label>
                    </div>
                </section>
                <section class="review-daily-lane is-present">
                    <header><span>第二步</span><h3>意义重塑</h3></header>
                    <div class="review-method-flow">
                        <div class="review-template-field">
                            <div class="review-template-heading"><label for="${meaningId}">回顾事件和左侧记录后，我重新注意到了什么？</label><button class="review-help-trigger" type="button" data-help="meaning" aria-label="查看意义重塑填写帮助">?</button></div>
                            <small>可以是对事件的新看法，也可以是对自己的新发现</small>
                            <textarea id="${meaningId}" rows="5" data-field="quick_meaning">${escapeHTML(item.quick_meaning || present.new_view)}</textarea>
                            <div class="review-field-tools"><button class="review-inline-action" type="button" data-ai="daily_reframe" data-ai-source-id="${escapeAttr(item.id)}" data-daily-assist${assistReady ? '' : ' hidden'}>获得一个新视角候选</button></div>
                        </div>
                        <label class="review-template-field"><strong>从现在开始，我可以采取什么具体行动？</strong><small>只写从现在开始、仅靠自己可以做到的事</small><textarea rows="4" data-field="present.action">${escapeHTML(present.action)}</textarea></label>
                        <label class="review-template-field"><strong>这些行动可能会带来怎样的结果？</strong><small>行动后可以回来补充实际结果；没有发生也算结果</small><textarea rows="3" data-field="present.expected_result">${escapeHTML(present.expected_result)}</textarea></label>
                    </div>
                    <details class="review-inline-result">
                        <summary>已经行动？补充实际结果</summary>
                        <label class="review-field"><span>后来实际发生了什么 <button class="review-help-trigger" type="button" data-help="actual" aria-label="查看实际结果帮助">?</button></span><textarea data-field="present.actual_result" placeholder="如实记录结果，也可以写未执行">${escapeHTML(present.actual_result || present.result)}</textarea></label>
                    </details>
                </section>
            </div>
            <details class="review-record-organizer">
                <summary><span>整理记录（可选）</span><small>以后按名称、人物或主题查找</small></summary>
                <div class="review-organizer-grid">
                    <label class="review-field"><span>记录名称</span><input class="review-title-input" data-field="title" value="${escapeAttr(item.title)}" placeholder="例如：没有先说结论的评审会"></label>
                    <label class="review-field"><span>涉及人物</span><input data-list-field="people" value="${escapeAttr((item.people || []).join('、'))}" placeholder="用顿号或逗号分开"></label>
                    <label class="review-field"><span>主题</span><input data-list-field="keywords" value="${escapeAttr((item.keywords || []).join('、'))}" placeholder="例如：周会、表达"></label>
                </div>
            </details>
            <span class="sr-only" data-card-status>${escapeHTML(savedAt)}</span>
        </article>`;
    }

    function collectDailyCard(card) {
        const item = state.daily.items.find((entry) => entry.id === card.dataset.eventId);
        const payload = {
            past: {...(item?.past || {})},
            present: {...(item?.present || {})},
        };
        card.querySelectorAll('[data-field]').forEach((input) => {
            const [group, field] = input.dataset.field.split('.');
            if (field && (group === 'past' || group === 'present')) payload[group][field] = input.value;
            else payload[group] = input.value;
        });
        card.querySelectorAll('[data-list-field]').forEach((input) => {
            payload[input.dataset.listField] = String(input.value || '').split(/[、,，\n]+/).map((value) => value.trim()).filter(Boolean);
        });
        payload.present.new_view = payload.quick_meaning || '';
        payload.emotions = item?.emotions || [];
        return payload;
    }

    function updateDailyAssist(card) {
        const button = card.querySelector('[data-daily-assist]');
        if (!button) return;
        const fact = card.querySelector('[data-field="fact"]')?.value.trim();
        const thoughts = card.querySelector('[data-field="past.thoughts"]')?.value.trim();
        button.hidden = !(fact && thoughts);
    }

    function selectDailyEvent(id) {
        if (!state.daily?.items.some((item) => item.id === id)) return;
        state.daily.items = state.daily.items.map(readDraft);
        state.dailyEventId = id;
        renderDaily();
    }

    function shiftDailyEvent(direction) {
        const items = state.daily?.items || [];
        const currentIndex = items.findIndex((item) => item.id === state.dailyEventId);
        const target = items[currentIndex + direction];
        if (target) selectDailyEvent(target.id);
    }

    function scheduleDailySave(card) {
        const id = card.dataset.eventId;
        const payload = collectDailyCard(card);
        writeDraft(id, payload);
        const index = state.daily.items.findIndex((item) => item.id === id);
        if (index >= 0) {
            state.daily.items[index] = {...state.daily.items[index], ...payload, _draft: true};
        }
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
            if (state.tab === 'daily') toast('已保存', 1800);
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
            state.dailyEventId = data.record.id;
            renderDaily();
            setSaveState('saved', syncLabel(data.sync));
            const card = elements.view.querySelector(`[data-event-id="${CSS.escape(data.record.id)}"]`);
            card?.querySelector('[data-field="fact"]')?.focus();
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
            state.dailyEventId = state.daily.items[0]?.id || null;
            clearDraft(id);
            renderDaily();
            setSaveState('saved', '事件已删除');
        } catch (error) { toast(error.message); }
    }

    async function duplicateDaily(card) {
        try {
            const data = await api(`/api/reviews/daily-events/${encodeURIComponent(card.dataset.eventId)}/duplicate`, {method: 'POST'});
            state.daily.items.push(data.record);
            state.dailyEventId = data.record.id;
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
        const draft = state.weeklyDrafts.get(state.weekly.period.start);
        if (draft) state.weekly.record = {...(state.weekly.record || {}), ...draft};
        state.weeklyStep = 1;
        renderWeekly();
        setSaveState(draft ? 'dirty' : 'saved', draft ? '已恢复本周未保存内容' : '本周来源已聚合');
    }

    function weeklyStepButton(number, title) {
        const active = state.weeklyStep === number;
        const done = state.weeklyStep > number;
        return `<button type="button" data-weekly-step="${number}" class="${active ? 'is-active' : ''}${done ? ' is-done' : ''}" aria-current="${active ? 'step' : 'false'}"><span>${done ? '✓' : number}</span><strong>${escapeHTML(title)}</strong></button>`;
    }

    function weeklySourceRows(data, focusIds) {
        const byDay = groupBy(data.daily_events || [], (item) => item.review_date);
        const start = new Date(`${data.period.start}T12:00:00`);
        return Array.from({length: 7}, (_, offset) => {
            const day = new Date(start);
            day.setDate(start.getDate() + offset);
            const key = localISODate(day);
            const items = byDay[key] || [];
            if (!items.length) {
                return `<div class="review-week-source is-empty"><span><b>${escapeHTML(weekdayLabel(key))}</b><small>${escapeHTML(key.slice(5))}</small></span><strong>没有记录</strong><i aria-hidden="true"></i></div>`;
            }
            return items.map((item) => {
                const selected = focusIds.includes(item.id);
                return `<label class="review-week-source${selected ? ' is-selected' : ''}"><span><b>${escapeHTML(weekdayLabel(key))}</b><small>${escapeHTML(key.slice(5))}</small></span><strong>${escapeHTML(item.title || compactText(item.fact || item.quick_meaning, 44) || '未命名事件')}</strong><input type="checkbox" data-focus-source="${escapeAttr(item.id)}"${selected ? ' checked' : ''}><i aria-hidden="true">${selected ? '✓' : ''}</i></label>`;
            }).join('');
        }).join('');
    }

    function weeklyPanel(number, kicker, title, description, body) {
        return `<section class="review-week-panel${state.weeklyStep === number ? ' is-active' : ''}" data-week-panel="${number}" tabindex="-1"><header><span>${escapeHTML(kicker)}</span><h2>${escapeHTML(title)}</h2><p>${escapeHTML(description)} <button class="review-example-trigger" type="button" data-action="open-example">查看填写案例</button></p></header>${body}</section>`;
    }

    function setWeeklyStep(step) {
        syncWeeklyDraftFromView();
        state.weeklyStep = Math.max(1, Math.min(4, Number(step) || 1));
        elements.view.querySelectorAll('[data-weekly-step]').forEach((button) => {
            const number = Number(button.dataset.weeklyStep);
            button.classList.toggle('is-active', number === state.weeklyStep);
            button.classList.toggle('is-done', number < state.weeklyStep);
            button.setAttribute('aria-current', number === state.weeklyStep ? 'step' : 'false');
            const marker = button.querySelector('span');
            if (marker) marker.textContent = number < state.weeklyStep ? '✓' : String(number);
        });
        elements.view.querySelectorAll('[data-week-panel]').forEach((panel) => {
            panel.classList.toggle('is-active', Number(panel.dataset.weekPanel) === state.weeklyStep);
        });
        const footer = elements.view.querySelector('.review-week-footer');
        if (footer) {
            const [previous, status, next] = footer.children;
            previous.disabled = state.weeklyStep === 1;
            status.textContent = `第 ${state.weeklyStep} 步，共 4 步`;
            next.disabled = state.weeklyStep === 4;
        }
        elements.view.querySelector('.review-week-result')?.classList.toggle('is-visible', state.weeklyStep === 4);
        const panel = elements.view.querySelector(`[data-week-panel="${state.weeklyStep}"]`);
        panel?.focus({preventScroll: true});
        panel?.scrollIntoView({behavior: 'smooth', block: 'start'});
    }

    function weeklyDraftKey() {
        return state.weekly?.period?.start || state.date;
    }

    function syncWeeklyDraftFromView(markDirty = false) {
        if (state.tab !== 'weekly' || !state.weekly || !elements.view.querySelector('.review-weekly-workspace')) return;
        const current = state.weekly.record || {focus_ids: [], abstraction: {}, summary: ''};
        const abstraction = {...(current.abstraction || {})};
        const summaryInput = document.getElementById('review-week-summary');
        elements.view.querySelectorAll('[data-abstraction-level]').forEach((input) => {
            abstraction[input.dataset.abstractionLevel] = input.value;
        });
        state.weekly.record = {
            ...current,
            focus_ids: selectedWeeklyIds(),
            abstraction,
            summary: summaryInput ? summaryInput.value : current.summary || '',
        };
        const key = weeklyDraftKey();
        if (markDirty || state.weeklyDrafts.has(key)) {
            state.weeklyDrafts.set(key, {...state.weekly.record});
            if (markDirty) markDraftChanged('weekly', key);
        }
    }

    function renderWeekly() {
        const data = state.weekly;
        const record = data.record || {focus_ids: [], abstraction: {}, summary: ''};
        const focusIds = record.focus_ids || [];
        const selectedCards = focusIds.map((id) => renderFocusItem(id, data.daily_events)).join('');
        const selectedContext = focusIds.map((id) => {
            const item = (data.daily_events || []).find((entry) => entry.id === id);
            return `<article><span>${escapeHTML(item?.review_date?.slice(5) || '')}</span><strong>${escapeHTML(item?.title || compactText(item?.fact, 52) || '来源事件')}</strong></article>`;
        }).join('');
        const abstractions = record.abstraction || {};
        const takeaway = record.summary || [...Array(8)].map((_, index) => abstractions[String(8 - index)] || abstractions[8 - index]).find(Boolean) || '完成四步后，在这里留下本周最重要的理解。';
        const nextExperiment = (data.experiments || []).find((item) => !['completed', 'stopped'].includes(item.status)) || data.experiments?.[0];
        const stepOne = `<ul class="review-selected-events review-focus-list" id="review-focus-list">${selectedCards || '<li class="review-source-empty">从左侧选择一条仍让你有感受的记录。</li>'}</ul>`;
        const stepTwo = `<div class="review-connection-map">${selectedContext || '<p class="review-source-empty">先在第一步选择记录。</p>'}<i aria-hidden="true"></i></div>${renderConnections(data.connections || [])}`;
        const stepThree = `<div class="review-level-choices" aria-label="观察层级"><div class="is-selected"><span>1–3</span><strong>靠近事实</strong></div><div><span>4–6</span><strong>寻找模式</strong></div><div><span>7–8</span><strong>需要长期证据</strong></div></div>${renderAbstraction(abstractions)}`;
        const stepFour = `${renderExperiments(data.experiments || [])}<label class="review-field review-week-summary"><span>本周带走的一句话</span><textarea id="review-week-summary" placeholder="这一周最值得留下的是什么？">${escapeHTML(record.summary || '')}</textarea></label>`;
        elements.view.innerHTML = `<div class="review-weekly-workspace">
            <aside class="review-week-source-rail" aria-label="本周每日记录"><header><div><span>每日记录</span><strong>选择最重要的事</strong></div><b data-weekly-selected-count>${focusIds.length}/3</b></header><div class="review-week-source-list">${weeklySourceRows(data, focusIds)}</div></aside>
            <article class="review-week-flow" aria-label="周度复盘四步流程">
                <nav class="review-week-stepper" aria-label="周度复盘步骤">${weeklyStepButton(1, '聚焦')}${weeklyStepButton(2, '找联系')}${weeklyStepButton(3, '看模式')}${weeklyStepButton(4, '具体化')}</nav>
                ${weeklyPanel(1, '01 · 聚焦', '本周最影响我的三件事', '不是选“最正确”的事，只选现在仍让你有感受的事。', stepOne)}
                ${weeklyPanel(2, '02 · 找联系', '这些事情之间，哪里很像？', '先描述你看见的重复，不急着解释原因。', stepTwo)}
                ${weeklyPanel(3, '03 · 看模式', '这周让我更了解自己的什么？', '先从靠近事实的层级开始，深层判断需要更长时间。', stepThree)}
                ${weeklyPanel(4, '04 · 具体化', '下一次，我准备怎么做？', '行动要足够具体，也必须在自己的控制范围内。', stepFour)}
                <footer class="review-week-footer"><button type="button" data-action="shift-weekly-step" data-shift="-1"${state.weeklyStep === 1 ? ' disabled' : ''}>← 上一步</button><span>第 ${state.weeklyStep} 步，共 4 步</span><button class="is-primary" type="button" data-action="shift-weekly-step" data-shift="1"${state.weeklyStep === 4 ? ' disabled' : ''}>下一步 →</button></footer>
            </article>
            <aside class="review-week-result${state.weeklyStep === 4 ? ' is-visible' : ''}"><span>本周带走</span><blockquote>“${escapeHTML(takeaway)}”</blockquote><strong>下一步</strong><p>${escapeHTML(nextExperiment?.first_step || nextExperiment?.what || '还没有行动实验。')}</p><small>${escapeHTML(nextExperiment?.review_date || data.period.end)}</small></aside>
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
        const key = weeklyDraftKey();
        state.weeklyDrafts.set(key, {...state.weekly.record});
        markDraftChanged('weekly', key);
        setSaveState('dirty', '本周有未保存更改');
        const list = document.getElementById('review-focus-list');
        list.innerHTML = current.map((sourceId) => renderFocusItem(sourceId, state.weekly.daily_events)).join('') || '<li class="review-chip">从右侧勾选本周聚焦</li>';
        const checkbox = elements.view.querySelector(`[data-focus-source="${CSS.escape(id)}"]`);
        const source = checkbox?.closest('.review-week-source');
        source?.classList.toggle('is-selected', current.includes(id));
        const mark = source?.querySelector('i');
        if (mark) mark.textContent = current.includes(id) ? '✓' : '';
        const count = elements.view.querySelector('[data-weekly-selected-count]');
        if (count) count.textContent = `${current.length}/3`;
    }

    async function saveWeekly() {
        syncWeeklyDraftFromView();
        const record = state.weekly.record || {};
        const payload = {focus_ids: record.focus_ids || [], abstraction: record.abstraction || {}, summary: record.summary || '', status: 'active'};
        const savedDate = state.date;
        const savedKey = weeklyDraftKey();
        const saveId = draftVersionKey('weekly', savedKey);
        if (state.savesInFlight.has(saveId)) return;
        state.savesInFlight.add(saveId);
        const savedVersion = draftVersion('weekly', savedKey);
        try {
            setSaveState('saving', '正在保存周度复盘…');
            const data = await api(`/api/reviews/weekly/${encodeURIComponent(savedDate)}`, {method: 'PUT', body: JSON.stringify(payload)});
            const unchanged = draftVersion('weekly', savedKey) === savedVersion;
            if (unchanged) {
                state.weeklyDrafts.delete(savedKey);
                clearDraftVersion('weekly', savedKey);
            }
            if (state.tab === 'weekly' && weeklyDraftKey() === savedKey && unchanged) {
                state.weekly.record = data.record;
                setSaveState('saved', syncLabel(data.sync));
            } else if (state.tab === 'weekly' && weeklyDraftKey() === savedKey) {
                setSaveState('dirty', '保存期间有新更改，请再保存一次');
            }
            toast('周度复盘已保存');
        } catch (error) {
            if (state.tab === 'weekly' && weeklyDraftKey() === savedKey) setSaveState('error', '保存失败');
            toast(error.message);
        } finally {
            state.savesInFlight.delete(saveId);
        }
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
        const draft = state.monthlyDrafts.get(state.month);
        if (draft) state.monthly.record = {...(state.monthly.record || {}), ...draft};
        renderMonthly();
        setSaveState(draft ? 'dirty' : 'saved', draft ? '已恢复本月未保存内容' : '本月来源已聚合');
    }

    function collectMonthlyDraft() {
        if (state.tab !== 'monthly' || !elements.view.querySelector('.review-monthly-workspace')) return null;
        const draft = {};
        elements.view.querySelectorAll('[data-month-field]').forEach((input) => {
            draft[input.dataset.monthField] = parseLines(input.value);
        });
        draft.cross_month = parseLines(document.getElementById('review-month-cross')?.value);
        draft.affirmation = document.getElementById('review-month-affirmation')?.value || '';
        return draft;
    }

    function captureMonthlyDraft(markDirty = false) {
        if (!markDirty && !state.monthlyDrafts.has(state.month)) return;
        const draft = collectMonthlyDraft();
        if (!draft) return;
        state.monthlyDrafts.set(state.month, draft);
        if (markDirty) markDraftChanged('monthly', state.month);
        if (state.monthly?.record) state.monthly.record = {...state.monthly.record, ...draft};
    }

    function compactMonthCell(value) {
        const first = Array.isArray(value)
            ? value.map((item) => typeof item === 'string' ? item : item?.text || item?.title || '').find(Boolean)
            : '';
        return first ? escapeHTML(compactText(first, 54)) : '<span class="is-blank">—</span>';
    }

    function monthlyYearRecords() {
        const year = state.month.slice(0, 4);
        const records = new Map((state.monthly.monthly_reviews || [])
            .filter((item) => String(item.month_key || '').startsWith(`${year}-`))
            .map((item) => [item.month_key, item]));
        if (state.monthly.record) records.set(state.month, state.monthly.record);
        return Array.from({length: 12}, (_, index) => {
            const monthKey = `${year}-${String(index + 1).padStart(2, '0')}`;
            return {monthKey, record: records.get(monthKey) || {inner: [], actions: [], results: [], notes: []}};
        });
    }

    async function selectMonthlyMonth(month) {
        if (!/^\d{4}-\d{2}$/.test(month) || month === state.month) return;
        captureMonthlyDraft();
        state.month = month;
        updateTabChrome();
        await loadMonthly();
    }

    function renderMonthlyConnectionOverview() {
        const connection = (state.monthly.connections || [])[0];
        if (!connection) {
            return '<div class="review-month-connection is-empty"><span>跨月</span><i aria-hidden="true">→</i><span>联结</span><p>保存至少两个月后，可以在下方建立真实的跨月联结。</p></div>';
        }
        const sourceId = connection.source_id || connection.source_ids?.[0] || '';
        const targetId = connection.target_id || connection.source_ids?.[1] || '';
        return `<div class="review-month-connection"><span>${escapeHTML(connectionEndpointLabel('monthly', sourceId))}</span><i aria-hidden="true">${connection.direction === 'bidirectional' ? '↔' : connection.direction === 'reverse' ? '←' : '→'}</i><span>${escapeHTML(connectionEndpointLabel('monthly', targetId))}</span><p>${escapeHTML(connection.description || connection.title || '已记录一条跨月联结')}</p></div>`;
    }

    function renderMonthly() {
        const record = state.monthly.record || {};
        const columns = [
            ['inner', '内心', '这个月真正牵动我的事'],
            ['actions', '行动', '我实际做过什么'],
            ['results', '结果', '现实发生了什么变化'],
            ['notes', '回看后想留下的话', '新的发现、想尝试的事或需要记住的背景'],
        ];
        const year = state.month.slice(0, 4);
        const monthNumber = Number(state.month.slice(5));
        const yearRows = monthlyYearRecords().map(({monthKey, record: monthRecord}, index) => `<tr class="${monthKey === state.month ? 'is-active' : ''}${monthKey > today.slice(0, 7) ? ' is-future' : ''}" data-action="select-month" data-month="${escapeAttr(monthKey)}"><th scope="row"><button type="button" data-action="select-month" data-month="${escapeAttr(monthKey)}"${monthKey === state.month ? ' aria-current="true"' : ''}>${index + 1}月</button></th><td>${compactMonthCell(monthRecord.inner)}</td><td>${compactMonthCell(monthRecord.actions)}</td><td>${compactMonthCell(monthRecord.results)}</td><td>${compactMonthCell(monthRecord.notes)}</td></tr>`).join('');
        const sourceLinks = state.monthly.daily_events.slice(0, 80).map((item) => `<button class="review-source-link" type="button" data-action="source" data-source-type="daily" data-source-id="${escapeAttr(item.id)}"><span>${escapeHTML(item.review_date)}</span>${escapeHTML(item.title || '未命名事件')}</button>`).join('');
        elements.view.innerHTML = `<div class="review-month-page"><div class="review-monthly-workspace">
            <section class="review-year-overview"><header><div><span>${escapeHTML(year)}</span><h2>这一年发生了什么变化</h2></div><p>点击月份继续编辑</p></header><div class="review-year-table-wrap"><table class="review-year-table"><thead><tr><th>月份</th><th>内心</th><th>行动</th><th>结果</th><th>备注</th></tr></thead><tbody>${yearRows}</tbody></table></div>${renderMonthlyConnectionOverview()}</section>
            <aside class="review-month-editor" aria-label="${escapeAttr(state.month)} 月度复盘模板"><header><div><span>${escapeHTML(year)} 年</span><h2>${monthNumber} 月</h2></div><button class="review-example-trigger" type="button" data-action="open-example">查看填写案例</button></header>${columns.map(([key, title, hint]) => `<label class="review-field"><span>${escapeHTML(title)}</span><small>${escapeHTML(hint)}</small><textarea data-month-field="${key}" placeholder="每行一条">${escapeHTML(lines(record[key]))}</textarea></label>`).join('')}</aside>
        </div><details class="review-secondary-panel"><summary>跨月联结与本月确认</summary><div class="review-secondary-content"><label class="review-field"><span>跨月联结（每行一条）</span><textarea id="review-month-cross" placeholder="例如：三月的想法在五月进入行动">${escapeHTML(lines(record.cross_month))}</textarea></label><label class="review-field"><span>给这个月的自己一句确认</span><textarea id="review-month-affirmation" placeholder="写下你真正认可的投入、选择或坚持">${escapeHTML(record.affirmation || '')}</textarea></label>${renderMonthlyConnections()}</div></details><details class="review-secondary-panel"><summary>本月记录来源</summary><div class="review-source-list">${sourceLinks || '<p class="review-source-empty">本月暂无每日记录</p>'}</div></details></div>`;
    }

    function renderMonthlyConnections() {
        const months = state.monthly.monthly_reviews || [];
        const options = (selected = '') => `<option value="">请选择月份</option>${months.map((item) => `<option value="${escapeAttr(item.id)}"${item.id === selected ? ' selected' : ''}>${escapeHTML(item.month_key)}</option>`).join('')}`;
        const disabled = months.length < 2 ? ' disabled' : '';
        return `<div class="review-period-connection"><h4>已记录的跨月联结</h4><div class="review-connection-list">${(state.monthly.connections || []).map(renderConnectionCard).join('') || '<p class="review-source-empty">保存至少两个月后，可以建立方向联结。</p>'}</div><details class="review-form-disclosure"><summary>${months.length < 2 ? '至少需要两个月' : '建立跨月联结'}</summary><form class="review-connection-form" id="review-month-connection-form" data-period-type="monthly"><div class="review-connection-route"><label class="review-field"><span>起点月份</span><select name="source_id" required${disabled}>${options()}</select></label><span class="review-connection-arrow" aria-hidden="true">→</span><label class="review-field"><span>终点月份</span><select name="target_id" required${disabled}>${options()}</select></label></div><div class="review-field-row"><label class="review-field"><span>连接标题</span><input name="title" required placeholder="例如：三月的想法在五月进入行动"></label><label class="review-field"><span>类型</span><select name="connection_type"><option value="direct">直接</option><option value="indirect">间接</option><option value="unexpected">意外</option></select></label></div><label class="review-field"><span>方向</span><select name="direction"><option value="forward">起点 → 终点</option><option value="bidirectional">双向影响</option><option value="reverse">终点 → 起点</option></select></label><label class="review-field"><span>联结说明</span><textarea name="description"></textarea></label><input type="hidden" name="source_type" value="monthly"><input type="hidden" name="target_type" value="monthly"><div class="review-card-actions"><button class="review-button review-button-quiet" type="button" data-action="cancel-connection-edit" hidden>取消编辑</button><button class="review-button review-button-primary" type="submit"${disabled}>添加联结</button></div></form></details></div>`;
    }

    async function saveMonthly() {
        const payload = collectMonthlyDraft() || {};
        payload.status = 'active';
        const savedMonth = state.month;
        const saveId = draftVersionKey('monthly', savedMonth);
        if (state.savesInFlight.has(saveId)) return;
        state.savesInFlight.add(saveId);
        const savedVersion = draftVersion('monthly', savedMonth);
        try {
            setSaveState('saving', '正在保存月度复盘…');
            const data = await api(`/api/reviews/monthly/${encodeURIComponent(savedMonth)}`, {method: 'PUT', body: JSON.stringify(payload)});
            const unchanged = draftVersion('monthly', savedMonth) === savedVersion;
            if (unchanged) {
                state.monthlyDrafts.delete(savedMonth);
                clearDraftVersion('monthly', savedMonth);
            }
            if (state.tab === 'monthly' && state.month === savedMonth && unchanged) {
                state.monthly.record = data.record;
                const existing = state.monthly.monthly_reviews.findIndex((item) => item.id === data.record.id);
                if (existing >= 0) state.monthly.monthly_reviews[existing] = data.record;
                else state.monthly.monthly_reviews.unshift(data.record);
                setSaveState('saved', syncLabel(data.sync));
            } else if (state.tab === 'monthly' && state.month === savedMonth) {
                setSaveState('dirty', '保存期间有新更改，请再保存一次');
            }
            toast('月度复盘已保存');
        } catch (error) {
            if (state.tab === 'monthly' && state.month === savedMonth) setSaveState('error', '保存失败');
            toast(error.message);
        } finally {
            state.savesInFlight.delete(saveId);
        }
    }

    async function loadAnnual() {
        state.annual = await api(`/api/reviews/annual/${encodeURIComponent(state.year)}`);
        const draft = state.annualDrafts.get(state.year);
        if (draft) state.annual.record = {...(state.annual.record || {}), ...draft};
        renderAnnual();
        setSaveState(draft ? 'dirty' : 'saved', draft ? '已恢复本年未保存内容' : '十二个月来源已聚合');
    }

    function collectAnnualDraft() {
        if (state.tab !== 'annual' || !elements.view.querySelector('.review-annual-workspace')) return null;
        return {
            keywords: parseLines(document.getElementById('review-annual-keywords')?.value),
            summary: document.getElementById('review-annual-summary')?.value || '',
        };
    }

    function captureAnnualDraft(markDirty = false) {
        if (!markDirty && !state.annualDrafts.has(state.year)) return;
        const draft = collectAnnualDraft();
        if (!draft) return;
        state.annualDrafts.set(state.year, draft);
        if (markDirty) markDraftChanged('annual', state.year);
        if (state.annual?.record) state.annual.record = {...state.annual.record, ...draft};
    }

    async function selectAnnualYear(year) {
        if (!/^\d{4}$/.test(year) || year === state.year) return;
        captureAnnualDraft();
        state.year = year;
        updateTabChrome();
        await loadAnnual();
    }

    function annualMonthItems(field, limit = 6) {
        const items = [];
        (state.annual.months || []).forEach((month) => {
            const monthNumber = Number(String(month.month_key || '').slice(-2));
            (month[field] || []).forEach((value) => {
                const text = typeof value === 'string' ? value : value?.text || value?.title || '';
                if (text && items.length < limit) items.push(`<li><span>${monthNumber}月</span>${escapeHTML(text)}</li>`);
            });
        });
        return items.join('');
    }

    function annualWatchItems(record) {
        const values = [];
        (record.cross_month || []).forEach((item) => {
            const text = typeof item === 'string' ? item : item?.text || item?.title || item?.description || '';
            if (text) values.push(text);
        });
        (state.annual.connections || []).forEach((item) => {
            const text = item.description || item.title || '';
            if (text) values.push(text);
        });
        if (!values.length) {
            [...(state.annual.months || [])].reverse().some((month) => {
                const note = (month.notes || []).find(Boolean);
                if (note) values.push(note);
                return Boolean(note);
            });
        }
        return values.slice(0, 3);
    }

    function renderAnnual() {
        const record = state.annual.record || {};
        const aiCandidates = (state.annual.ai_candidates || []).map((item) => {
            const candidate = item.confirmed_content || item.candidate || {};
            return `<article class="review-ai-candidate"><span class="review-meta-text">${item.status === 'confirmed' ? '已确认候选' : '待确认候选'}</span><p><strong>${escapeHTML(candidate.statement || '')}</strong></p><div class="review-emotions">${(candidate.evidence || []).map((evidence) => `<button class="review-chip is-source" type="button" data-action="source" data-source-type="${escapeAttr(evidence.source_type || 'monthly')}" data-source-id="${escapeAttr(evidence.source_id)}">${escapeHTML(evidence.record_date || shortId(evidence.source_id))}</button>`).join('')}</div><p class="review-ai-uncertainty">${escapeHTML(candidate.uncertainty_note || '仍需更多来源验证')}</p></article>`;
        }).join('');
        const months = state.annual.months.map((month) => {
            const monthNumber = Number(String(month.month_key || '').slice(-2)) || '';
            const monthLabel = monthNumber ? `${monthNumber}月` : month.month_key;
            const active = month.month_key === today.slice(0, 7);
            const empty = !month.id || month.status === 'empty';
            return `<button type="button" data-action="open-annual-month" data-month="${escapeAttr(month.month_key)}" class="${active ? 'is-current' : ''}${empty ? ' is-empty' : ''}"><span>${escapeHTML(monthLabel)}</span><i aria-hidden="true"></i></button>`;
        }).join('');
        const keywords = (record.keywords || []).map((item) => `<span>${escapeHTML(item)}</span>`).join('');
        const changes = `${annualMonthItems('inner', 3)}${annualMonthItems('results', 3)}`;
        const actions = annualMonthItems('actions');
        const watch = annualWatchItems(record);
        elements.view.innerHTML = `<div class="review-annual-page"><div class="review-annual-workspace">
            <article class="review-annual-lead"><span>${escapeHTML(state.year)} · 年度总结</span><textarea id="review-annual-summary" aria-label="这一年的核心理解" rows="3" placeholder="回看十二个月后，什么理解最值得留下？">${escapeHTML(record.summary || '')}</textarea><div class="review-annual-keywords">${keywords || '<span class="is-empty">尚未提炼关键词</span>'}</div><details class="review-annual-keyword-editor"><summary>编辑年度关键词</summary><label class="review-field"><span>每行一个关键词</span><textarea id="review-annual-keywords" placeholder="例如：表达、运动、边界">${escapeHTML(lines(record.keywords))}</textarea></label><button class="review-button review-button-small review-button-quiet" type="button" data-ai="annual_summary">从月度记录寻找候选</button></details></article>
            <section class="review-year-trace"><header><h2>十二个月</h2><span>有记录的月份会形成轨迹</span></header><div>${months}</div></section>
            <div class="review-annual-columns"><section><span>发生的变化</span><ul>${changes || '<li class="is-empty">还没有月度内心或结果记录</li>'}</ul></section><section><span>我真正做过的事</span><ul>${actions || '<li class="is-empty">还没有月度行动记录</li>'}</ul></section><section class="is-watch"><span>继续观察</span>${watch.length ? `<ul>${watch.map((item) => `<li>${escapeHTML(item)}</li>`).join('')}</ul>` : '<p>还没有形成需要继续观察的跨月线索。</p>'}</section></div>
        </div><details class="review-secondary-panel"><summary>查看跨月联结</summary><div class="review-secondary-content review-connection-list">${(state.annual.connections || []).map(renderConnectionCard).join('') || '<p class="review-source-empty">本年度暂无跨月联结</p>'}</div></details>${aiCandidates ? `<details class="review-secondary-panel"><summary>查看已保存的年度候选</summary><div class="review-secondary-content review-ai-candidates">${aiCandidates}</div></details>` : ''}</div>`;
    }

    function highlight(value, keyword) {
        const escaped = escapeHTML(value);
        if (!keyword) return escaped;
        const safe = keyword.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        return escaped.replace(new RegExp(safe, 'gi'), (match) => `<mark class="review-highlight">${match}</mark>`);
    }

    async function saveAnnual() {
        const payload = {...(collectAnnualDraft() || {}), status: 'active'};
        const savedYear = state.year;
        const saveId = draftVersionKey('annual', savedYear);
        if (state.savesInFlight.has(saveId)) return;
        state.savesInFlight.add(saveId);
        const savedVersion = draftVersion('annual', savedYear);
        try {
            setSaveState('saving', '正在保存年度复盘…');
            const data = await api(`/api/reviews/annual/${encodeURIComponent(savedYear)}`, {method: 'PUT', body: JSON.stringify(payload)});
            const unchanged = draftVersion('annual', savedYear) === savedVersion;
            if (unchanged) {
                state.annualDrafts.delete(savedYear);
                clearDraftVersion('annual', savedYear);
            }
            if (state.tab === 'annual' && state.year === savedYear && unchanged) {
                state.annual.record = data.record;
                setSaveState('saved', syncLabel(data.sync));
            } else if (state.tab === 'annual' && state.year === savedYear) {
                setSaveState('dirty', '保存期间有新更改，请再保存一次');
            }
            toast('年度复盘已保存');
        } catch (error) {
            if (state.tab === 'annual' && state.year === savedYear) setSaveState('error', '保存失败');
            toast(error.message);
        } finally {
            state.savesInFlight.delete(saveId);
        }
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
            [1, '自己的状态', '枝叶'], [2, '内心最在意的事', '枝叶'], [3, '重要人物', '枝叶'],
            [4, '兴趣所在', '树干'], [5, '优势和特长', '树干'], [6, '思维与行为模式', '树干'],
            [7, '信念和固有观念', '根系'], [8, '想法和愿望', '根系'],
        ];
        const overview = state.insightOverview || {};
        const tierLabels = {branch: '枝叶', trunk: '树干', root: '树根'};
        const suitable = (overview.suitable_tiers || []).map((tier) => tierLabels[tier]).join('、') || '继续积累事实记录';
        const next = overview.next_tier ? tierLabels[overview.next_tier] : '可继续验证已有洞察';
        const maxLevel = Number(overview.max_level || 0);
        const nextLimit = ({branch: 3, trunk: 6, root: 8})[overview.next_tier] || maxLevel;
        const depthRows = levels.map(([level, label, tier]) => {
            const status = level <= maxLevel ? 'available' : level <= nextLimit ? 'observing' : 'locked';
            const statusLabel = status === 'available' ? '可整理' : status === 'observing' ? '积累中' : '锁定';
            return `<li class="is-${status}"><span>${level}</span><div><strong>${escapeHTML(label)}</strong><small>${escapeHTML(tier)}</small></div><i aria-hidden="true">${statusLabel}</i></li>`;
        }).join('');
        const weeks = overview.span_days ? Math.max(1, Math.ceil(Number(overview.span_days) / 7)) : 0;
        const countLabel = weeks ? `已积累 ${weeks} 周记录` : `已有 ${Number(overview.daily_events || 0)} 条记录`;
        const cards = state.insights.map(renderInsightCard).join('') || '<div class="review-empty review-insight-empty"><div><h2>还没有形成洞察</h2><p>先积累每日记录；重复出现后，再决定它是否属于你。</p></div></div>';
        elements.view.innerHTML = `<div class="review-insight-page"><div class="review-insights-workspace">
            <section class="review-insight-overview"><div><span>${escapeHTML(countLabel)}</span><h2>先看见重复，再决定它是否属于你</h2></div><div><p>目前适合整理${escapeHTML(suitable)}。进入${escapeHTML(next)}前，需要更多时间、来源与反例。</p><button class="review-text-button" type="button" data-ai="inner_insight">从记录寻找候选</button></div></section>
            ${showForm ? renderInsightForm() : ''}
            <div class="review-insight-layout"><section class="review-insight-list">${cards}</section><aside class="review-insight-depth"><header><span>观察深度</span><h2>八个层级</h2></header><ol>${depthRows}</ol></aside></div>
        </div></div>`;
    }

    function renderInsightForm() {
        const sources = state.insightSources.map((item) => `<label class="review-source-event"><input type="checkbox" name="source_id" value="${escapeAttr(item.id)}"><span><strong>${escapeHTML(item.review_date)} · ${escapeHTML(item.title || '未命名事件')}</strong><p>${escapeHTML(compactText(item.fact || item.quick_meaning, 90))}</p></span></label>`).join('');
        return `<section class="review-insight-form" id="review-insight-create"><header><h2>新增洞察</h2><p>先写可验证的陈述，再补充来源、反例和验证行动。</p></header><form id="review-insight-form"><div class="review-field-row"><label class="review-field"><span>层级</span><select name="tier"><option value="branch">枝叶</option><option value="trunk">树干</option><option value="root">根系</option></select></label><label class="review-field"><span>抽象级别 L1-L8</span><input name="level" type="number" value="1" min="1" max="8"></label></div><label class="review-field"><span>类别</span><select name="category"><option value="state">状态</option><option value="concern">在意的事</option><option value="person">重要人物</option><option value="interest">兴趣</option><option value="strength">优势</option><option value="thought_pattern">思维模式</option><option value="behavior_pattern">行为模式</option><option value="belief">信念</option><option value="fixed_idea">固有观念</option><option value="wish">真实想法与愿望</option></select></label><label class="review-field"><span>候选陈述</span><textarea name="statement" required placeholder="例如：在需要即兴表达的场合，我会通过过度准备来降低不确定性。"></textarea></label><fieldset class="review-source-picker"><legend>引用最近的原始记录</legend>${sources || '<p class="review-source-empty">还没有可引用的每日记录</p>'}</fieldset><label class="review-field"><span>补充支持证据（每行一条）</span><textarea name="evidence"></textarea></label><label class="review-field"><span>反例或另一种解释（每行一条）</span><textarea name="counter_evidence"></textarea></label><div class="review-field-row"><label class="review-field"><span>不确定性（0-1）</span><input name="uncertainty" type="number" value="0.5" min="0" max="1" step="0.1"></label><label class="review-field"><span>为什么仍不确定</span><input name="uncertainty_note" placeholder="例如：目前只有一周的记录"></label></div><label class="review-field"><span>用于验证的最小行动</span><textarea name="verification_experiment" placeholder="下一次如何在现实里观察它是否成立？"></textarea></label><button class="review-button review-button-primary" type="submit">保存为待确认洞察</button></form></section>`;
    }

    function renderInsightCard(item) {
        const strength = item.evidence_strength || {};
        const span = item.evidence_span || {};
        const evidence = (item.evidence || []).map((entry) => typeof entry === 'string' ? `<li>${escapeHTML(entry)}</li>` : `<li>${entry.source_id ? `<button class="review-chip is-source" type="button" data-action="source" data-source-type="${escapeAttr(entry.source_type || 'daily')}" data-source-id="${escapeAttr(entry.source_id)}">${escapeHTML(entry.record_date || shortId(entry.source_id))}</button>` : ''} ${escapeHTML(entry.observation || entry.text || entry.source_excerpt || '')}</li>`).join('');
        const counter = (item.counter_evidence || []).map((entry) => typeof entry === 'string' ? entry : entry?.text || entry?.observation || '').filter(Boolean).join('；');
        const sourceCount = strength.independent_sources || item.source_ids?.length || item.evidence?.length || 0;
        return `<article class="review-insight-card"><header><span>L${Number(item.level) || '—'} · ${escapeHTML(categoryLabel(item.category))}</span><b>${escapeHTML(statusLabel(item.status))}</b></header><h2>${escapeHTML(item.statement)}</h2><div class="review-insight-sources"><strong>${sourceCount} 条来源${span.days ? ` · 跨 ${span.days} 天` : ''}</strong>${evidence ? `<ul>${evidence}</ul>` : '<p>暂未引用具体来源</p>'}</div><details><summary>反例与下一次观察</summary><div><span>仍不能确定</span><p>${escapeHTML(counter || item.uncertainty_note || '需要更多现实记录')}</p><span>下一次观察</span><p>${escapeHTML(item.verification_experiment || '继续记录与这条判断不一致的情况。')}</p><span>我的状态</span><label class="review-insight-status"><select data-insight-status="${escapeAttr(item.id)}"><option value="pending"${['pending', 'candidate'].includes(item.status) ? ' selected' : ''}>待确认</option><option value="observing"${item.status === 'observing' ? ' selected' : ''}>继续观察</option><option value="accepted"${['accepted', 'recognized', 'verified'].includes(item.status) ? ' selected' : ''}>我认可</option><option value="rejected"${item.status === 'rejected' ? ' selected' : ''}>我不认可</option><option value="disproved"${item.status === 'disproved' ? ' selected' : ''}>已被证伪</option></select><button class="review-text-button" type="button" data-action="source" data-source-type="insight" data-source-id="${escapeAttr(item.id)}">查看来源</button></label></div></details></article>`;
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
        const figure = item.image ? `<figure class="review-help-figure"><img src="${escapeAttr(item.image)}" alt="${escapeAttr(item.image_alt || '')}"><figcaption>${escapeHTML(item.image_caption || '')}</figcaption></figure>` : '';
        elements.helpContent.innerHTML = `<div class="review-help-copy"><p>${escapeHTML(item.body)}</p>${figure}<div class="review-causality-note"><strong>例子：</strong><span>${escapeHTML(item.example)}</span></div></div>`;
        openDialog(elements.helpDialog);
    }

    function openExample() {
        const example = REVIEW_EXAMPLES[state.tab];
        if (!example) return;
        elements.exampleTitle.textContent = example.title;
        const sections = example.sections.map((section) => `<section class="review-example-section"><h4>${escapeHTML(section.title)}</h4><dl>${section.fields.map(([label, value]) => `<div><dt>${escapeHTML(label)}</dt><dd>${escapeHTML(value)}</dd></div>`).join('')}</dl></section>`).join('');
        elements.exampleContent.innerHTML = `<article class="review-example-case"><header><h3>${escapeHTML(example.subject)}</h3><p>${escapeHTML(example.context)}</p></header><div class="review-example-sections">${sections}</div><footer>依据《复盘自己：从记录到蜕变的行动指南》案例整理</footer></article>`;
        openDialog(elements.exampleDialog);
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
            if (data.applied_to?.type === 'annual') {
                const year = data.applied_to.year;
                const statement = String(data.candidate.confirmed_content.statement || '').trim();
                const draft = state.annualDrafts.get(year);
                if (draft && statement && !String(draft.summary || '').includes(statement)) {
                    state.annualDrafts.set(year, {
                        ...draft,
                        summary: `${String(draft.summary || '').trim()}\n- ${statement}`.trim(),
                    });
                    markDraftChanged('annual', year);
                }
                if (state.tab === 'annual' && state.year === year) await loadAnnual();
            }
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
        const query = new URLSearchParams({limit: '30'});
        Object.entries(values).forEach(([key, value]) => { if (value) query.append(key, value); });
        elements.searchResults.innerHTML = '<div class="review-loading">正在搜索…</div>';
        try {
            const data = await api(`/api/reviews/search?${query.toString()}`);
            elements.searchResults.innerHTML = data.items.length ? data.items.map((item) => `<button class="review-search-result" type="button" data-action="open-search-result" data-record-type="${escapeAttr(item.record_type)}" data-record-id="${escapeAttr(item.id)}" data-review-date="${escapeAttr(item.review_date || '')}" data-week-start="${escapeAttr(item.week_start || '')}" data-month-key="${escapeAttr(item.month_key || '')}" data-year-key="${escapeAttr(item.year_key || '')}"><header><strong>${escapeHTML(searchTitle(item))}</strong><span class="review-chip">${escapeHTML(recordTypeLabel(item.record_type))}</span></header><p>${escapeHTML(searchPreview(item))}</p></button>`).join('') : '<div class="review-empty review-search-empty"><div><p>没有找到符合条件的记录。</p></div></div>';
        } catch (error) { elements.searchResults.innerHTML = renderError(error.message); }
    }

    async function openSearchResult(button) {
        const type = button.dataset.recordType;
        const id = button.dataset.recordId;
        closeDialog(elements.searchDialog);
        if (type === 'daily' && button.dataset.reviewDate) {
            state.date = button.dataset.reviewDate;
            state.dailyEventId = id;
            return selectTab('daily');
        }
        if (type === 'weekly' && button.dataset.weekStart) {
            state.date = button.dataset.weekStart;
            return selectTab('weekly');
        }
        if (type === 'monthly' && button.dataset.monthKey) {
            if (state.tab === 'monthly') return selectMonthlyMonth(button.dataset.monthKey);
            state.month = button.dataset.monthKey;
            return selectTab('monthly');
        }
        if (type === 'annual' && button.dataset.yearKey) {
            if (state.tab === 'annual') return selectAnnualYear(button.dataset.yearKey);
            state.year = button.dataset.yearKey;
            return selectTab('annual');
        }
        return openSource(type, id);
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
        if (state.tab === 'weekly') syncWeeklyDraftFromView();
        if (state.tab === 'monthly') captureMonthlyDraft();
        if (state.tab === 'annual') captureAnnualDraft();
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
        if (action === 'shift-daily') return shiftDailyEvent(Number(button.dataset.shift || 0));
        if (action === 'open-search') return openSearch();
        if (action === 'open-guide') return openGuide();
        if (action === 'open-example') return openExample();
        if (action === 'source') return openSource(button.dataset.sourceType, button.dataset.sourceId);
        if (button.dataset.weeklyStep) return setWeeklyStep(button.dataset.weeklyStep);
        if (action === 'shift-weekly-step') return setWeeklyStep(state.weeklyStep + Number(button.dataset.shift || 0));
        if (action === 'select-month') return selectMonthlyMonth(button.dataset.month);
        if (action === 'open-annual-month') {
            state.month = button.dataset.month;
            return selectTab('monthly');
        }
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
        if (card && event.target.matches('[data-field], [data-list-field], [data-meaning-type]')) {
            updateDailyAssist(card);
            scheduleDailySave(card);
        }
        if (event.target.matches('[data-abstraction-level], #review-week-summary')) {
            syncWeeklyDraftFromView(true);
            setSaveState('dirty', '本周有未保存更改');
        }
        if (event.target.matches('[data-month-field], #review-month-cross, #review-month-affirmation')) {
            captureMonthlyDraft(true);
            setSaveState('dirty', '本月有未保存更改');
        }
        if (event.target.matches('#review-annual-summary, #review-annual-keywords')) {
            captureAnnualDraft(true);
            setSaveState('dirty', '本年有未保存更改');
        }
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
        if (dragged) {
            list.insertBefore(dragged, target);
            syncWeeklyDraftFromView(true);
            setSaveState('dirty', '本周有未保存更改');
        }
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
            if (state.tab === 'weekly') syncWeeklyDraftFromView();
            if (state.tab === 'monthly') captureMonthlyDraft();
            if (state.tab === 'annual') captureAnnualDraft();
            state.date = today; state.month = today.slice(0, 7); state.year = today.slice(0, 4);
            updateTabChrome(); loadCurrentView();
        });
        elements.periodInput.addEventListener('change', () => {
            if (state.tab === 'weekly') syncWeeklyDraftFromView();
            if (state.tab === 'monthly') captureMonthlyDraft();
            if (state.tab === 'annual') captureAnnualDraft();
            if (state.tab === 'daily' || state.tab === 'weekly') state.date = elements.periodInput.value;
            else if (state.tab === 'monthly') state.month = elements.periodInput.value;
            else if (state.tab === 'annual') state.year = elements.periodInput.value;
            loadCurrentView();
        });
        elements.newbie.addEventListener('change', savePreferences);
        elements.searchOpen.addEventListener('click', openSearch);
        elements.searchForm.addEventListener('submit', (event) => { event.preventDefault(); searchReviews(event.target); });
        elements.view.addEventListener('click', handleViewClick);
        elements.view.addEventListener('input', handleViewInput);
        elements.view.addEventListener('change', handleViewChange);
        elements.view.addEventListener('submit', handleViewSubmit);
        elements.view.addEventListener('keydown', handleViewKeydown);
        elements.view.addEventListener('dragstart', handleDragStart);
        elements.view.addEventListener('dragover', handleDragOver);
        document.addEventListener('click', (event) => {
            document.querySelectorAll('.review-more-menu[open]').forEach((menu) => {
                if (!menu.contains(event.target)) menu.removeAttribute('open');
            });
            const close = event.target.closest('[data-dialog-close]');
            if (close) closeDialog(close.closest('dialog'));
            const searchResult = event.target.closest('[data-action="open-search-result"]');
            if (searchResult) return openSearchResult(searchResult);
            const source = event.target.closest('[data-action="source"]');
            if (source && !elements.view.contains(source)) {
                if (elements.searchResults.contains(source)) closeDialog(elements.searchDialog);
                openSource(source.dataset.sourceType, source.dataset.sourceId);
            }
            const action = event.target.closest('[data-action]')?.dataset.action;
            if (action === 'run-ai') runAI();
            const candidate = event.target.closest('[data-candidate-id]');
            if (action === 'confirm-ai') confirmAI(candidate, false);
            if (action === 'confirm-ai-insight') confirmAI(candidate, true);
            if (action === 'dismiss-ai') dismissAI(candidate);
        });
        document.querySelectorAll('.review-dialog').forEach((dialog) => dialog.addEventListener('click', (event) => {
            if (event.target === dialog) closeDialog(dialog);
        }));
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
