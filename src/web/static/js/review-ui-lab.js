(function () {
    'use strict';

    function deepFreeze(value) {
        if (!value || typeof value !== 'object' || Object.isFrozen(value)) return value;
        Object.values(value).forEach(deepFreeze);
        return Object.freeze(value);
    }

    const LAB_DATA = deepFreeze({
        daily: {
            date: '2026-08-25',
            events: [
                {
                    id: 'daily-1',
                    event: '评审开始十分钟后，我才打开准备好的提纲。',
                    thoughtFeeling: '我一直担心结论说得不够完整，所以不停补充背景。',
                    pastAction: '先解释来龙去脉，再慢慢靠近结论。',
                    pastResult: '讨论几次偏离核心问题，我也越来越紧张。',
                    reframe: '问题不在准备不足，而在开场时没有给大家一个清楚的判断。面对不确定性时，我会本能地增加信息来换取安全感。',
                    nextAction: '下一次评审前，先写下一句不超过 20 字的结论，并在开场先说出来。',
                    futureResult: '讨论能更快进入核心问题。',
                },
                {
                    id: 'daily-2',
                    event: '晚饭后散步二十分钟，回来删掉了课程中的三个支线章节。',
                    thoughtFeeling: '删除前有些舍不得，也担心内容显得不够丰富。',
                    pastAction: '先把所有想到的案例都塞进课程。',
                    pastResult: '主线越来越难复述，自己讲的时候也容易跑题。',
                    reframe: '留白没有削弱内容，反而让课程目标变得清楚。我常把“内容更多”误当成“准备更充分”。',
                    nextAction: '每节课只保留一个能被学员验证的目标。',
                    futureResult: '学员能用一句话复述下一步行动。',
                },
            ],
        },
        weekly: {
            period: '8 月 24 日 — 8 月 30 日',
            sources: [
                {id: 'w1', day: '周一', date: '08-24', title: '整理需求时保留了太多分支', selected: true},
                {id: 'w2', day: '周二', date: '08-25', title: '评审会上没有先说结论', selected: true},
                {id: 'w3', day: '周二', date: '08-25', title: '散步后重新整理课程结构', selected: true},
                {id: 'w4', day: '周三', date: '08-26', title: '与学员确认第一步', selected: false},
                {id: 'w5', day: '周四', date: '08-27', title: '没有记录', empty: true},
            ],
            connection: '三个场景里，我都先用增加信息来降低不确定性；真正推进事情的时刻，反而发生在我开始删减之后。',
            abstraction: '不确定时先增加内容，是我最近反复出现的行为模式。',
            action: '下一次需要表达判断时，先写一句结论，再决定哪些背景真的有必要。',
            when: '8 月 29 日的课程评审前',
            signal: '讨论在前 30 秒进入核心问题',
        },
        monthly: {
            year: '2026',
            months: [
                {month: '1月', inner: '想证明自己准备充分', action: '补充更多资料', result: '启动变慢', note: ''},
                {month: '2月', inner: '开始留意疲惫来源', action: '减少同时推进的项目', result: '注意力更稳定', note: ''},
                {month: '3月', inner: '仍害怕遗漏', action: '建立检查清单', result: '返工减少', note: '清单有用，但不能代替判断'},
                {month: '4月', inner: '更愿意承认不知道', action: '先提问再给方案', result: '沟通更直接', note: ''},
                {month: '5月', inner: '在意别人能否理解', action: '用一句话复述目标', result: '会议更短', note: ''},
                {month: '6月', inner: '对取舍仍有不安', action: '暂停两个支线', result: '主线开始清楚', note: ''},
                {month: '7月', inner: '准备焦虑反复出现', action: '记录触发时刻', result: '看见增加信息的习惯', note: '开始形成线索'},
                {month: '8月', inner: '接受内容少不等于价值低', action: '删掉三条支线；评审前写一句结论', result: '课程主线缩短；讨论更快进入核心', note: '本月真正做出了取舍'},
                {month: '9月', inner: '', action: '', result: '', note: ''},
                {month: '10月', inner: '', action: '', result: '', note: ''},
                {month: '11月', inner: '', action: '', result: '', note: ''},
                {month: '12月', inner: '', action: '', result: '', note: ''},
            ],
            connection: '7 月看见“增加信息”的习惯，8 月开始用主动删减回应它。',
        },
        annual: {
            year: '2026',
            months: Array.from({length: 12}, (_, index) => ({
                month: `${index + 1}月`,
                active: index < 8,
            })),
            headline: '我没有做得更多，但开始更清楚地选择什么值得做。',
            changes: [
                '从用信息量证明认真，转向先说清判断。',
                '从同时推进许多方向，转向保留一条能验证的主线。',
                '开始把疲惫当作需要观察的信号，而不是意志力不足。',
            ],
            actions: ['暂停两个支线项目', '建立每周复盘', '评审前先写一句结论'],
            keepWatching: '当任务重新变得不确定时，我是否又会通过增加内容来逃避判断。',
            keywords: ['取舍', '表达', '验证'],
        },
        insights: {
            weeks: 8,
            items: [
                {
                    id: 'i1',
                    level: 2,
                    tier: '枝叶',
                    category: '内心最在意的事',
                    status: '继续观察',
                    statement: '我近期很在意复杂内容能否被别人清楚理解和复述。',
                    evidence: ['8 月 25 日 · 评审会上没有先说结论', '8 月 25 日 · 散步后重新整理课程结构'],
                    counter: '目前主要来自工作和课程两个相近场景。',
                    next: '观察生活场景中是否也会主动收窄信息。',
                },
                {
                    id: 'i2',
                    level: 6,
                    tier: '树干',
                    category: '思维与行为模式',
                    status: '待确认',
                    statement: '面对不确定性时，我可能会通过增加信息来推迟做判断。',
                    evidence: ['7 月月度复盘', '8 月第 4 周周度复盘', '8 月 25 日 · 评审记录'],
                    counter: '有些任务确实需要更多背景，删减并不总是正确。',
                    next: '新增内容前，先写下“不增加会造成什么具体风险”。',
                },
            ],
            levels: [
                ['1', '自己的状态', '枝叶', 'available'],
                ['2', '内心最在意的事', '枝叶', 'available'],
                ['3', '重要人物', '枝叶', 'available'],
                ['4', '兴趣所在', '树干', 'observing'],
                ['5', '优势和特长', '树干', 'observing'],
                ['6', '思维与行为模式', '树干', 'observing'],
                ['7', '信念和固有观念', '根系', 'locked'],
                ['8', '想法和愿望', '根系', 'locked'],
            ],
        },
    });

    const VARIANTS = deepFreeze({
        a: {name: '引导'},
        b: {name: '对照'},
        c: {name: '专注'},
    });

    const VIEWS = deepFreeze({
        daily: {title: '今日复盘', kicker: '', period: '8 月 25 日', primary: ''},
        weekly: {title: '周度复盘', kicker: '本周', period: '8.24 — 8.30', primary: '完成本周复盘'},
        monthly: {title: '月度复盘', kicker: '全年视图', period: '2026 年', primary: '保存本月'},
        annual: {title: '年度复盘', kicker: '回看这一年', period: '2026 年', primary: '保存年度总结'},
        insights: {title: '内在洞察', kicker: '来自长期记录', period: '全部时间', primary: '整理一条洞察'},
    });

    const CONTENT_STATES = deepFreeze({
        ready: null,
        empty: {
            kicker: '还没有复盘记录',
            title: '从一件真正影响你的事开始',
            description: '先写清发生了什么，以及当时真实的想法。其他内容可以之后再补。',
            action: '使用示例开始',
        },
        loading: {
            kicker: '正在打开复盘',
            title: '正在整理记录与草稿',
            description: '载入完成后会回到你刚才查看的位置。',
            action: '立即显示',
        },
        error: {
            kicker: '暂时无法打开记录',
            title: '内容没有被覆盖',
            description: '请稍后重试。你当前输入的内容仍保留在这个页面中。',
            action: '重新尝试',
        },
    });

    function normalizeVariant(value) {
        const candidate = String(value || '').toLowerCase();
        return VARIANTS[candidate] ? candidate : 'a';
    }

    function normalizeView(value) {
        return VIEWS[value] ? value : 'daily';
    }

    function normalizePreview(value) {
        return ['auto', 'desktop', 'mobile'].includes(value) ? value : 'auto';
    }

    function normalizeContentState(value) {
        return Object.prototype.hasOwnProperty.call(CONTENT_STATES, value) ? value : 'ready';
    }

    function readInitialOptions(search) {
        const params = new URLSearchParams(search || '');
        return {
            variant: normalizeVariant(params.get('variant')),
            view: normalizeView(params.get('view')),
            preview: normalizePreview(params.get('preview')),
            contentState: normalizeContentState(params.get('state')),
            compare: params.get('compare') === '1',
            inspect: params.get('inspect') === '1' || params.get('compare') === '1',
        };
    }

    const publicAPI = Object.freeze({
        LAB_DATA,
        VARIANTS,
        VIEWS,
        CONTENT_STATES,
        normalizeVariant,
        normalizeView,
        normalizePreview,
        normalizeContentState,
        readInitialOptions,
    });
    globalThis.LearnFluxReviewUiLab = publicAPI;

    if (typeof document === 'undefined') return;

    const initial = readInitialOptions(window.location.search);
    const draftData = JSON.parse(JSON.stringify(LAB_DATA));
    const state = {
        variant: initial.variant,
        view: initial.view,
        preview: initial.preview,
        contentState: initial.contentState,
        compare: initial.compare,
        inspect: initial.inspect,
        dailyEventId: draftData.daily.events[0].id,
        weeklyStep: 1,
        selectedWeekly: new Set(draftData.weekly.sources.filter((item) => item.selected).map((item) => item.id)),
        monthlyIndex: 7,
        saveTimer: null,
        toastTimer: null,
    };

    const root = document.querySelector('.review-ui-lab');
    const workspace = document.getElementById('review-lab-workspace');
    const viewContent = document.getElementById('review-lab-view-content');
    const statePanel = document.querySelector('[data-state-panel]');
    const comparison = document.querySelector('[data-comparison]');
    const comparisonGrid = document.querySelector('[data-comparison-grid]');
    const canvas = document.querySelector('.review-lab-canvas');
    const toast = document.querySelector('[data-lab-toast]');
    const searchPanel = document.querySelector('[data-search-panel]');
    const searchOverlay = document.querySelector('[data-search-overlay]');

    function escapeHTML(value) {
        return String(value ?? '').replace(/[&<>'"]/g, (character) => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
        })[character]);
    }

    function escapeAttr(value) {
        return escapeHTML(value);
    }

    function field(label, value, name, options = {}) {
        const rows = options.rows || 3;
        const hint = options.hint ? `<small>${escapeHTML(options.hint)}</small>` : '';
        const placeholder = options.placeholder ? ` placeholder="${escapeAttr(options.placeholder)}"` : '';
        return `<label class="mock-field${options.className ? ` ${options.className}` : ''}">
            <span>${escapeHTML(label)}</span>
            ${hint}
            <textarea rows="${rows}" data-draft-field="${escapeAttr(name)}"${placeholder}>${escapeHTML(value)}</textarea>
        </label>`;
    }

    function showToast(message) {
        window.clearTimeout(state.toastTimer);
        toast.textContent = message;
        toast.hidden = false;
        state.toastTimer = window.setTimeout(() => {
            toast.hidden = true;
        }, 2200);
    }

    function scheduleSave() {
        window.clearTimeout(state.saveTimer);
        if (state.view === 'daily') {
            state.saveTimer = window.setTimeout(() => showToast('已保存'), 500);
            return;
        }
        const saveLabels = document.querySelectorAll('[data-save-label]');
        if (!saveLabels.length) return;
        saveLabels.forEach((label) => { label.textContent = '正在保存…'; });
        state.saveTimer = window.setTimeout(() => {
            saveLabels.forEach((label) => { label.textContent = '刚刚已保存'; });
        }, 500);
    }

    function currentDaily() {
        return draftData.daily.events.find((event) => event.id === state.dailyEventId)
            || draftData.daily.events[0];
    }

    function dailyRecordLabel(event) {
        const value = String(event.event || '').trim();
        if (!value) return '尚未记录事件';
        return value.length > 28 ? `${value.slice(0, 28)}…` : value;
    }

    function dailyField(label, hint, value, name, rows) {
        return `<label class="mock-method-field">
            <strong>${escapeHTML(label)}</strong>
            <small>${escapeHTML(hint)}</small>
            <textarea rows="${rows}" data-draft-field="${escapeAttr(name)}">${escapeHTML(value)}</textarea>
        </label>`;
    }

    function renderDaily() {
        const current = currentDaily();
        const records = draftData.daily.events.map((event) => `
            <button class="mock-record-choice${event.id === current.id ? ' is-active' : ''}" type="button" data-daily-event="${escapeAttr(event.id)}">
                <strong>${escapeHTML(dailyRecordLabel(event))}</strong>
            </button>`).join('');

        return `<div class="mock-daily-page">
            <aside class="mock-daily-records" aria-label="今日记录">
                <header><strong>${draftData.daily.events.length} 条记录</strong></header>
                <div class="mock-record-list">${records}</div>
                <button class="mock-add-link" type="button" data-mock-action="new-event">＋ 记录另一件事</button>
            </aside>

            <article class="mock-daily-method">
                <section class="mock-event-field">
                    <label>
                        <span>事件</span>
                        <strong>什么事件让你内心有所触动？</strong>
                        <small>只写客观发生的事，不加入感受或评价</small>
                        <textarea rows="3" data-draft-field="event">${escapeHTML(current.event)}</textarea>
                    </label>
                </section>

                <div class="mock-method-columns">
                    <section class="mock-method-lane" aria-labelledby="daily-step-one">
                        <header>
                            <span>第一步</span>
                            <h2 id="daily-step-one">如实记录</h2>
                        </header>
                        <div class="mock-method-flow">
                            ${dailyField('事件发生时，我在想什么、感受什么？', '不修饰，也不判断好坏', current.thoughtFeeling, 'thoughtFeeling', 4)}
                            ${dailyField('当时我采取了什么行动？', '如果没有，可以留空', current.pastAction, 'pastAction', 3)}
                            ${dailyField('这个行动带来了什么结果？', '如果还没有明显结果，可以留空', current.pastResult, 'pastResult', 3)}
                        </div>
                    </section>

                    <section class="mock-method-lane is-reframe" aria-labelledby="daily-step-two">
                        <header>
                            <span>第二步</span>
                            <h2 id="daily-step-two">意义重塑</h2>
                        </header>
                        <div class="mock-method-flow">
                            ${dailyField('回顾事件和左侧记录后，我重新注意到了什么？', '可以是对事件的新看法，也可以是对自己的新发现', current.reframe, 'reframe', 5)}
                            ${dailyField('从现在开始，我可以采取什么具体行动？', '只写从现在开始、仅靠自己可以做到的事', current.nextAction, 'nextAction', 4)}
                            ${dailyField('这些行动可能会带来怎样的结果？', '行动后可以回来补充实际结果；没有发生也算结果', current.futureResult, 'futureResult', 3)}
                        </div>
                    </section>
                </div>
            </article>
        </div>`;
    }

    function weeklyStepButton(step, label) {
        const active = state.weeklyStep === step;
        const done = state.weeklyStep > step;
        return `<button type="button" data-weekly-step="${step}" class="${active ? 'is-active' : ''}${done ? ' is-done' : ''}" aria-current="${active ? 'step' : 'false'}">
            <span>${done ? '✓' : step}</span><strong>${escapeHTML(label)}</strong>
        </button>`;
    }

    function renderWeeklySources() {
        return draftData.weekly.sources.map((source) => {
            const selected = state.selectedWeekly.has(source.id);
            return `<button class="mock-week-source${selected ? ' is-selected' : ''}${source.empty ? ' is-empty' : ''}" type="button" data-week-source="${escapeAttr(source.id)}"${source.empty ? ' disabled' : ''}>
                <span><b>${escapeHTML(source.day)}</b><small>${escapeHTML(source.date)}</small></span>
                <strong>${escapeHTML(source.title)}</strong>
                <i aria-hidden="true">${selected ? '✓' : ''}</i>
            </button>`;
        }).join('');
    }

    function renderWeekly() {
        const selected = draftData.weekly.sources.filter((source) => state.selectedWeekly.has(source.id));
        const selectedCards = selected.map((source) => `<article><span>${escapeHTML(source.date)}</span><strong>${escapeHTML(source.title)}</strong></article>`).join('');

        return `<div class="mock-weekly-workspace">
            <aside class="mock-week-source-rail">
                <header><div><span>每日记录</span><strong>选择最重要的事</strong></div><b>${state.selectedWeekly.size}/3</b></header>
                <div class="mock-week-source-list">${renderWeeklySources()}</div>
            </aside>

            <article class="mock-week-flow">
                <nav class="mock-week-stepper" aria-label="周度复盘步骤">
                    ${weeklyStepButton(1, '聚焦')}
                    ${weeklyStepButton(2, '找联系')}
                    ${weeklyStepButton(3, '看模式')}
                    ${weeklyStepButton(4, '具体化')}
                </nav>

                <section class="mock-week-panel${state.weeklyStep === 1 ? ' is-active' : ''}" data-week-panel="1">
                    <header><span>01 · 聚焦</span><h2>本周最影响我的三件事</h2><p>不是选“最正确”的事，只选现在仍让你有感受的事。</p></header>
                    <div class="mock-selected-events">${selectedCards || '<p>从左侧选择一条记录。</p>'}</div>
                </section>

                <section class="mock-week-panel${state.weeklyStep === 2 ? ' is-active' : ''}" data-week-panel="2">
                    <header><span>02 · 找联系</span><h2>这些事情之间，哪里很像？</h2><p>先描述你看见的重复，不急着解释原因。</p></header>
                    <div class="mock-connection-map">${selectedCards}<i aria-hidden="true"></i></div>
                    ${field('我看见的联系', draftData.weekly.connection, 'weekly.connection', {rows: 5})}
                </section>

                <section class="mock-week-panel${state.weeklyStep === 3 ? ' is-active' : ''}" data-week-panel="3">
                    <header><span>03 · 看模式</span><h2>这周让我更了解自己的什么？</h2><p>先从靠近事实的层级开始，深层判断需要更长时间。</p></header>
                    <div class="mock-level-choices">
                        <button type="button" class="is-selected"><span>1</span><strong>自己的状态</strong></button>
                        <button type="button" class="is-selected"><span>2</span><strong>在意的事</strong></button>
                        <button type="button"><span>3</span><strong>重要人物</strong></button>
                        <button type="button" disabled><span>4–6</span><strong>继续积累后再看</strong></button>
                    </div>
                    ${field('我目前看见的模式', draftData.weekly.abstraction, 'weekly.abstraction', {rows: 5})}
                </section>

                <section class="mock-week-panel${state.weeklyStep === 4 ? ' is-active' : ''}" data-week-panel="4">
                    <header><span>04 · 具体化</span><h2>下一次，我准备怎么做？</h2><p>行动要足够具体，也必须在自己的控制范围内。</p></header>
                    ${field('我要做的事', draftData.weekly.action, 'weekly.action', {rows: 4})}
                    <div class="mock-field-grid">
                        ${field('什么时候做？', draftData.weekly.when, 'weekly.when', {rows: 2})}
                        ${field('怎样知道做到了？', draftData.weekly.signal, 'weekly.signal', {rows: 2})}
                    </div>
                </section>

                <footer class="mock-sheet-footer">
                    <button type="button" data-weekly-shift="-1"${state.weeklyStep === 1 ? ' disabled' : ''}>← 上一步</button>
                    <span>第 ${state.weeklyStep} 步，共 4 步</span>
                    <button class="is-primary" type="button" data-weekly-shift="1"${state.weeklyStep === 4 ? ' disabled' : ''}>下一步 →</button>
                </footer>
            </article>

            <aside class="mock-week-result${state.weeklyStep === 4 ? ' is-visible' : ''}">
                <span>本周带走</span>
                <blockquote>“${escapeHTML(draftData.weekly.abstraction)}”</blockquote>
                <strong>下一步</strong>
                <p>${escapeHTML(draftData.weekly.action)}</p>
                <small>${escapeHTML(draftData.weekly.when)}</small>
            </aside>
        </div>`;
    }

    function compactCell(value) {
        if (!value) return '<span class="is-blank">—</span>';
        return escapeHTML(value.split('；')[0]);
    }

    function renderMonthly() {
        const current = draftData.monthly.months[state.monthlyIndex];
        const rows = draftData.monthly.months.map((month, index) => `
            <tr class="${index === state.monthlyIndex ? 'is-active' : ''}${index > 7 ? 'is-future' : ''}" data-month-row="${index}">
                <th scope="row"><button type="button" data-month-select="${index}">${escapeHTML(month.month)}</button></th>
                <td>${compactCell(month.inner)}</td>
                <td>${compactCell(month.action)}</td>
                <td>${compactCell(month.result)}</td>
                <td>${compactCell(month.note)}</td>
            </tr>`).join('');

        return `<div class="mock-monthly-workspace">
            <section class="mock-year-sheet">
                <header><div><span>${escapeHTML(draftData.monthly.year)}</span><h2>这一年发生了什么变化</h2></div><p>点击月份继续编辑</p></header>
                <div class="mock-year-table-wrap">
                    <table class="mock-year-table">
                        <thead><tr><th>月份</th><th>内心</th><th>行动</th><th>结果</th><th>备注</th></tr></thead>
                        <tbody>${rows}</tbody>
                    </table>
                </div>
                <div class="mock-month-connection">
                    <span>7 月</span><i aria-hidden="true">→</i><span>8 月</span>
                    <p>${escapeHTML(draftData.monthly.connection)}</p>
                </div>
            </section>

            <aside class="mock-month-editor">
                <header><span>${escapeHTML(draftData.monthly.year)} 年</span><h2>${escapeHTML(current.month)}</h2></header>
                ${field('内心', current.inner, 'monthly.inner', {hint: '这个月真正牵动我的事', rows: 4})}
                ${field('行动', current.action, 'monthly.action', {hint: '我实际做过什么', rows: 4})}
                ${field('结果', current.result, 'monthly.result', {hint: '现实发生了什么变化', rows: 4})}
                ${field('回看后想留下的话', current.note, 'monthly.note', {rows: 3})}
            </aside>
        </div>`;
    }

    function renderAnnual() {
        const months = draftData.monthly.months.map((month, index) => `
            <button type="button" data-annual-month="${index}" class="${index === 7 ? 'is-current' : ''}${index > 7 ? ' is-empty' : ''}">
                <span>${escapeHTML(month.month)}</span><i aria-hidden="true"></i>
            </button>`).join('');
        const changes = draftData.annual.changes.map((item) => `<li>${escapeHTML(item)}</li>`).join('');
        const actions = draftData.annual.actions.map((item) => `<li>${escapeHTML(item)}</li>`).join('');
        const keywords = draftData.annual.keywords.map((item) => `<span>${escapeHTML(item)}</span>`).join('');

        return `<div class="mock-annual-workspace">
            <article class="mock-annual-lead">
                <span>${escapeHTML(draftData.annual.year)} · 年度总结</span>
                <textarea aria-label="这一年的核心理解" data-draft-field="annual.headline" rows="3">${escapeHTML(draftData.annual.headline)}</textarea>
                <div class="mock-keywords">${keywords}</div>
            </article>

            <section class="mock-year-trace">
                <header><h2>十二个月</h2><span>有记录的月份会形成轨迹</span></header>
                <div>${months}</div>
            </section>

            <div class="mock-annual-columns">
                <section><span>发生的变化</span><ul>${changes}</ul></section>
                <section><span>我真正做过的事</span><ul>${actions}</ul></section>
                <section class="is-watch"><span>继续观察</span><p>${escapeHTML(draftData.annual.keepWatching)}</p></section>
            </div>
        </div>`;
    }

    function renderInsightCard(item) {
        const evidence = item.evidence.map((entry) => `<li>${escapeHTML(entry)}</li>`).join('');
        return `<article class="mock-insight-card">
            <header><span>L${item.level} · ${escapeHTML(item.category)}</span><b>${escapeHTML(item.status)}</b></header>
            <h2>${escapeHTML(item.statement)}</h2>
            <div class="mock-insight-sources"><strong>${item.evidence.length} 条来源</strong><ul>${evidence}</ul></div>
            <details>
                <summary>反例与下一次观察</summary>
                <div><span>仍不能确定</span><p>${escapeHTML(item.counter)}</p><span>下一次观察</span><p>${escapeHTML(item.next)}</p></div>
            </details>
        </article>`;
    }

    function renderInsights() {
        const levels = draftData.insights.levels.map(([number, label, tier, status]) => `
            <li class="is-${escapeAttr(status)}">
                <span>${escapeHTML(number)}</span>
                <div><strong>${escapeHTML(label)}</strong><small>${escapeHTML(tier)}</small></div>
                <i aria-hidden="true">${status === 'locked' ? '锁定' : status === 'observing' ? '积累中' : '可整理'}</i>
            </li>`).join('');
        const cards = draftData.insights.items.map(renderInsightCard).join('');

        return `<div class="mock-insights-workspace">
            <section class="mock-insight-overview">
                <div><span>已积累 ${draftData.insights.weeks} 周记录</span><h2>先看见重复，再决定它是否属于你</h2></div>
                <p>目前适合整理枝叶与部分树干。更深的判断需要更多时间和反例。</p>
            </section>
            <div class="mock-insight-layout">
                <section class="mock-insight-list">${cards}</section>
                <aside class="mock-level-map">
                    <header><span>观察深度</span><h2>八个层级</h2></header>
                    <ol>${levels}</ol>
                </aside>
            </div>
        </div>`;
    }

    function renderCurrentView() {
        if (state.view === 'daily') return renderDaily();
        if (state.view === 'weekly') return renderWeekly();
        if (state.view === 'monthly') return renderMonthly();
        if (state.view === 'annual') return renderAnnual();
        return renderInsights();
    }

    function updateHeader() {
        const view = VIEWS[state.view];
        document.querySelector('[data-view-title]').textContent = view.title;
        document.querySelector('[data-view-kicker]').textContent = view.kicker;
        document.querySelector('[data-view-period]').textContent = view.period;
        const primary = document.querySelector('[data-mock-action="primary"]');
        primary.textContent = view.primary;
        primary.hidden = !view.primary;
        document.querySelectorAll('[data-workspace-view]').forEach((button) => {
            const active = button.dataset.workspaceView === state.view;
            button.classList.toggle('is-active', active);
            if (active) button.setAttribute('aria-current', 'page');
            else button.removeAttribute('aria-current');
        });
    }

    function renderState() {
        const stateCopy = CONTENT_STATES[state.contentState];
        const ready = state.contentState === 'ready';
        statePanel.hidden = ready;
        viewContent.hidden = !ready;
        if (ready) {
            viewContent.innerHTML = renderCurrentView();
            return;
        }
        statePanel.dataset.kind = state.contentState;
        statePanel.querySelector('[data-state-kicker]').textContent = stateCopy.kicker;
        statePanel.querySelector('[data-state-title]').textContent = stateCopy.title;
        statePanel.querySelector('[data-state-description]').textContent = stateCopy.description;
        statePanel.querySelector('[data-state-recover]').textContent = stateCopy.action;
    }

    function syncUrl() {
        const params = new URLSearchParams();
        params.set('variant', state.variant);
        params.set('view', state.view);
        if (state.preview !== 'auto') params.set('preview', state.preview);
        if (state.contentState !== 'ready') params.set('state', state.contentState);
        if (state.compare) params.set('compare', '1');
        else if (state.inspect) params.set('inspect', '1');
        window.history.replaceState(null, '', `${window.location.pathname}?${params.toString()}`);
    }

    function syncControls() {
        root.dataset.variant = state.variant;
        root.dataset.preview = state.preview;
        root.dataset.state = state.contentState;
        root.dataset.inspect = String(state.inspect);
        workspace.dataset.variant = state.variant;
        workspace.dataset.view = state.view;

        document.querySelectorAll('[data-variant-choice]').forEach((button) => {
            button.setAttribute('aria-pressed', String(button.dataset.variantChoice === state.variant));
        });
        document.querySelectorAll('[data-preview-choice]').forEach((button) => {
            button.setAttribute('aria-pressed', String(button.dataset.previewChoice === state.preview));
        });
        document.querySelectorAll('[data-state-choice]').forEach((button) => {
            button.setAttribute('aria-pressed', String(button.dataset.stateChoice === state.contentState));
        });
        const select = document.querySelector('[data-view-choice]');
        if (select) select.value = state.view;
        const compareButton = document.querySelector('[data-compare-toggle]');
        compareButton.setAttribute('aria-pressed', String(state.compare));
        compareButton.textContent = state.compare ? '返回单页' : '并排查看';
    }

    function renderComparison() {
        comparison.hidden = !state.compare;
        canvas.hidden = state.compare;
        comparisonGrid.innerHTML = '';
        if (!state.compare) return;
        Object.keys(VARIANTS).forEach((variant) => {
            const wrapper = document.createElement('section');
            wrapper.className = 'review-lab-comparison-item';
            const heading = document.createElement('strong');
            heading.textContent = `${variant.toUpperCase()} · ${VARIANTS[variant].name}`;
            const clonedWorkspace = workspace.cloneNode(true);
            clonedWorkspace.removeAttribute('id');
            clonedWorkspace.dataset.variant = variant;
            clonedWorkspace.querySelectorAll('[id]').forEach((node) => node.removeAttribute('id'));
            clonedWorkspace.querySelectorAll('button, input, textarea, summary').forEach((node) => {
                node.setAttribute('tabindex', '-1');
            });
            wrapper.append(heading, clonedWorkspace);
            comparisonGrid.append(wrapper);
        });
    }

    function render() {
        updateHeader();
        renderState();
        syncControls();
        renderComparison();
        syncUrl();
    }

    function setView(view) {
        state.view = normalizeView(view);
        state.contentState = 'ready';
        closeMobileMenu();
        render();
        document.querySelector('.mock-review-main').scrollTop = 0;
    }

    function setWeeklyStep(step) {
        state.weeklyStep = Math.max(1, Math.min(4, Number(step)));
        render();
    }

    function handleDraftInput(target) {
        const fieldName = target.dataset.draftField;
        if (!fieldName) return;
        if (fieldName.startsWith('weekly.')) {
            draftData.weekly[fieldName.split('.')[1]] = target.value;
        } else if (fieldName.startsWith('monthly.')) {
            draftData.monthly.months[state.monthlyIndex][fieldName.split('.')[1]] = target.value;
        } else if (fieldName === 'annual.headline') {
            draftData.annual.headline = target.value;
        } else {
            currentDaily()[fieldName] = target.value;
        }
        scheduleSave();
    }

    function addDailyEvent() {
        const id = `daily-${Date.now()}`;
        draftData.daily.events.push({
            id,
            event: '',
            thoughtFeeling: '',
            pastAction: '',
            pastResult: '',
            reframe: '',
            nextAction: '',
            futureResult: '',
        });
        state.dailyEventId = id;
        render();
        window.setTimeout(() => document.querySelector('[data-draft-field="event"]')?.focus(), 0);
    }

    function openSearch() {
        searchPanel.hidden = false;
        searchOverlay.hidden = false;
        renderSearch(document.querySelector('[data-search-input]').value);
        window.setTimeout(() => document.querySelector('[data-search-input]')?.focus(), 0);
    }

    function closeSearch() {
        searchPanel.hidden = true;
        searchOverlay.hidden = true;
    }

    function renderSearch(query) {
        const normalized = String(query || '').trim().toLowerCase();
        const results = draftData.daily.events.filter((event) => {
            const haystack = Object.values(event).join(' ').toLowerCase();
            return !normalized || haystack.includes(normalized);
        });
        const container = document.querySelector('[data-search-results]');
        container.innerHTML = results.length ? results.map((event) => `
            <button type="button" data-search-event="${escapeAttr(event.id)}">
                <span>8 月 25 日</span><strong>${escapeHTML(dailyRecordLabel(event))}</strong><p>${escapeHTML(event.reframe || event.event)}</p>
            </button>`).join('') : '<p class="mock-search-empty">没有找到相关记录。</p>';
    }

    function openMobileMenu() {
        workspace.classList.add('is-nav-open');
        const backdrop = document.querySelector('[data-mobile-backdrop]');
        backdrop.hidden = false;
    }

    function closeMobileMenu() {
        workspace.classList.remove('is-nav-open');
        const backdrop = document.querySelector('[data-mobile-backdrop]');
        if (backdrop) backdrop.hidden = true;
    }

    document.addEventListener('click', (event) => {
        const target = event.target.closest('button, a');
        if (!target) return;

        if (target.matches('[data-variant-choice]')) {
            state.variant = normalizeVariant(target.dataset.variantChoice);
            render();
            return;
        }
        if (target.matches('[data-preview-choice]')) {
            state.preview = normalizePreview(target.dataset.previewChoice);
            render();
            return;
        }
        if (target.matches('[data-state-choice]')) {
            state.contentState = normalizeContentState(target.dataset.stateChoice);
            render();
            return;
        }
        if (target.matches('[data-workspace-view]')) {
            setView(target.dataset.workspaceView);
            return;
        }
        if (target.matches('[data-compare-toggle]')) {
            state.compare = !state.compare;
            if (state.compare) state.inspect = true;
            render();
            return;
        }
        if (target.matches('[data-state-recover]')) {
            state.contentState = 'ready';
            render();
            return;
        }
        if (target.matches('[data-daily-event]')) {
            state.dailyEventId = target.dataset.dailyEvent;
            render();
            return;
        }
        if (target.matches('[data-weekly-step]')) {
            setWeeklyStep(target.dataset.weeklyStep);
            return;
        }
        if (target.matches('[data-weekly-shift]')) {
            setWeeklyStep(state.weeklyStep + Number(target.dataset.weeklyShift));
            return;
        }
        if (target.matches('[data-week-source]')) {
            const id = target.dataset.weekSource;
            if (state.selectedWeekly.has(id)) state.selectedWeekly.delete(id);
            else if (state.selectedWeekly.size < 3) state.selectedWeekly.add(id);
            else {
                showToast('最多选择三件事');
                return;
            }
            render();
            return;
        }
        if (target.matches('[data-month-select]')) {
            state.monthlyIndex = Number(target.dataset.monthSelect);
            render();
            return;
        }
        if (target.closest('[data-month-row]')) {
            state.monthlyIndex = Number(target.closest('[data-month-row]').dataset.monthRow);
            render();
            return;
        }
        if (target.matches('[data-annual-month]')) {
            state.monthlyIndex = Number(target.dataset.annualMonth);
            setView('monthly');
            return;
        }
        if (target.matches('[data-mock-action="search"]')) {
            openSearch();
            return;
        }
        if (target.matches('[data-search-close]') || target.matches('[data-search-overlay]')) {
            closeSearch();
            return;
        }
        if (target.matches('[data-search-event]')) {
            state.dailyEventId = target.dataset.searchEvent;
            closeSearch();
            setView('daily');
            return;
        }
        if (target.matches('[data-mobile-menu]')) {
            openMobileMenu();
            return;
        }
        if (target.matches('[data-mobile-backdrop]')) {
            closeMobileMenu();
            return;
        }
        if (target.matches('[data-period-change]')) {
            showToast('已切换周期示例');
            return;
        }
        if (target.matches('[data-mock-action="new-event"]')) {
            addDailyEvent();
            return;
        }
        if (target.matches('[data-mock-action="primary"]')) {
            if (state.view === 'daily') addDailyEvent();
            else if (state.view === 'weekly') setWeeklyStep(4);
            else showToast('本次预览内容已保存');
            return;
        }
        if (target.matches('[data-mock-action="settings"]')) {
            showToast('设置页未在本次复盘预览中');
            return;
        }
        if (target.matches('[data-mock-action="unavailable"]')) {
            showToast('本轮只预览复盘模块');
        }
    });

    document.addEventListener('input', (event) => {
        const target = event.target;
        if (target.matches('[data-search-input]')) {
            renderSearch(target.value);
            return;
        }
        if (target.matches('[data-draft-field]')) handleDraftInput(target);
    });

    document.querySelector('[data-view-choice]')?.addEventListener('change', (event) => {
        setView(event.target.value);
    });

    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') {
            closeSearch();
            closeMobileMenu();
        }
    });

    render();
})();
