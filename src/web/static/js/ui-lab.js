(function () {
    'use strict';

    const LAB_DATA = Object.freeze({
        title: '从功能堆叠到学习闭环：怎样设计一套真正会被持续使用的 AI 产品',
        summary: '这节课用一个具体产品案例，拆解触发、行动、反馈与再次使用之间的关系。',
        currentTime: '14:32',
        duration: '38:24',
        progress: '62%',
        question: '这段里“闭环”的判断标准是什么？',
        answerIntro: '不是看功能数量，而是看用户能否顺畅完成一个重要任务。可以检查三个信号：',
        answerPoints: Object.freeze([
            '用户知道下一步该做什么。',
            '每一步都有清楚、及时的反馈。',
            '完成后自然产生下一次使用的理由。',
        ]),
        note: [
            '闭环不是功能清单，而是一条连续的用户任务路径。',
            '',
            '判断标准：',
            '1. 下一步是否清楚；',
            '2. 反馈是否及时；',
            '3. 是否形成再次使用的理由。',
            '',
            '待验证：把 LearnFlux 的“解析完成”接到第一次主动复习。',
        ].join('\n'),
        transcript: Object.freeze([
            Object.freeze({ time: '13:48', text: '我们先回到用户真正要完成的事情，而不是马上列功能清单。' }),
            Object.freeze({ time: '14:02', text: '功能越多，不代表产品价值越大，反而可能让主要路径变得模糊。' }),
            Object.freeze({ time: '14:18', text: '一个看似完整的产品，可能只是很多彼此无关的按钮被放在了一起。' }),
            Object.freeze({ time: '14:32', text: '好的产品不是把功能堆在一起，而是围绕一个任务形成闭环。' }),
            Object.freeze({ time: '14:47', text: '这个闭环至少包含触发、行动、反馈，以及下一次使用的理由。' }),
            Object.freeze({ time: '15:06', text: '当其中任何一环断掉，用户就会重新回到原来的工具或习惯。' }),
            Object.freeze({ time: '15:24', text: '判断功能是否需要存在，先看它是否让闭环更短、更顺畅。' }),
            Object.freeze({ time: '15:51', text: '接下来我们用一个具体案例拆解这四个步骤。' }),
        ]),
    });

    const VARIANTS = Object.freeze({
        a: Object.freeze({
            code: '方案 A',
            name: '专注长桌',
            summary: '把当前内容放在最中心，其他工具在需要时出现。',
            plain: Object.freeze({
                '第一眼': '先看到课程标题和当前视频，学习目标很直接。',
                '松紧感': '更宽松，内容之间留有明显呼吸空间。',
                '容易发现': '视频、进度和逐字稿最容易发现，AI 与笔记集中在右侧。',
                '适合用户': '容易被复杂界面打断，想一次专注一件事的学习者。',
                '长期感受': '安静、压力小，但高频切换 AI 与笔记时会多一次面板操作。',
            }),
            parameters: Object.freeze({
                '信息密度': '低至中',
                '页面最大宽度': '1370px',
                '主辅比例': '1.58 : 0.58',
                '层级强度': '内容 > 工具 > 导航',
                '间距': '22–30px',
                '分组方式': '媒体与逐字稿主线 + 单一研究侧栏',
                '卡片程度': '中等，柔和分区',
                '响应式': '移动端：视频 → 逐字稿 → 研究台',
            }),
        }),
        b: Object.freeze({
            code: '方案 B',
            name: '专业控制台',
            summary: '媒体、逐字稿和研究工具同时在场，减少切换成本。',
            plain: Object.freeze({
                '第一眼': '立即看到三个清楚面板，像一张完整的学习控制台。',
                '松紧感': '更紧凑，同一屏容纳更多可操作信息。',
                '容易发现': '逐字稿、AI、笔记入口和播放控制都很容易被找到。',
                '适合用户': '熟悉产品、经常边看边查边记的高频用户。',
                '长期感受': '效率高、可预期，但新用户可能需要先理解三个面板。',
            }),
            parameters: Object.freeze({
                '信息密度': '高',
                '页面最大宽度': '无额外限制',
                '主辅比例': '1.16 : 0.88 : 0.72',
                '层级强度': '三个工作区并列',
                '间距': '11–16px',
                '分组方式': '媒体 / 逐字稿 / 研究台固定三栏',
                '卡片程度': '高，面板边界清楚',
                '响应式': '1024 变两栏；移动端回到任务顺序',
            }),
        }),
        c: Object.freeze({
            code: '方案 C',
            name: '研究阅读室',
            summary: '把逐字稿当作主文档，视频是证据来源，AI 与笔记是研究工具。',
            plain: Object.freeze({
                '第一眼': '先进入课程主题和长文阅读，像在研究一份有时间线的材料。',
                '松紧感': '正文宽松，外围工具更克制。',
                '容易发现': '逐字稿和研究台最突出；播放画面存在，但不是视觉中心。',
                '适合用户': '重视理解、引用、反复阅读和形成观点的深度学习者。',
                '长期感受': '适合长时间阅读与研究，但以看视频为主的人可能觉得画面偏小。',
            }),
            parameters: Object.freeze({
                '信息密度': '中',
                '页面最大宽度': '1360px',
                '主辅比例': '0.64 : 1.35 : 0.76',
                '层级强度': '逐字稿 > 研究工具 > 媒体',
                '间距': '18–34px',
                '分组方式': '中心阅读流 + 两侧上下文',
                '卡片程度': '低，接近文档与边栏',
                '响应式': '移动端：逐字稿 → 研究台 → 媒体',
            }),
        }),
    });

    const CONTENT_STATES = Object.freeze({
        success: Object.freeze({
            kicker: '学习内容已就绪',
            title: '学习工作台',
            description: '媒体、逐字稿和学习记录已载入。',
            action: '保持成功状态',
        }),
        loading: Object.freeze({
            kicker: '加载学习内容',
            title: '正在准备你的学习工作台',
            description: '正在载入媒体、逐字稿和学习记录。',
            action: '切换到成功状态',
        }),
        empty: Object.freeze({
            kicker: '暂无可学习内容',
            title: '这份内容还没有逐字稿',
            description: '解析完成后，视频、逐字稿、AI 问答和笔记会出现在这里。',
            action: '查看成功示例',
        }),
        error: Object.freeze({
            kicker: '内容载入失败',
            title: '暂时无法打开这份学习内容',
            description: '原始内容仍然安全保留，可以稍后重新载入。',
            action: '模拟重新载入',
        }),
    });

    function normalizeVariant(value) {
        const candidate = String(value || '').toLowerCase();
        return VARIANTS[candidate] ? candidate : 'a';
    }

    function normalizePreview(value) {
        return ['auto', 'desktop', 'mobile'].includes(value) ? value : 'auto';
    }

    function normalizeContentState(value) {
        return CONTENT_STATES[value] ? value : 'success';
    }

    function readInitialOptions(search) {
        const params = new URLSearchParams(search || '');
        return {
            variant: normalizeVariant(params.get('variant')),
            preview: normalizePreview(params.get('preview')),
            contentState: normalizeContentState(params.get('state')),
            embed: params.get('embed') === '1',
        };
    }

    function appendDefinitionList(list, values) {
        list.replaceChildren();
        Object.entries(values).forEach(([label, value]) => {
            const group = document.createElement('div');
            const term = document.createElement('dt');
            const description = document.createElement('dd');
            term.textContent = label;
            description.textContent = value;
            group.append(term, description);
            list.append(group);
        });
    }

    function setTextFields(root) {
        root.querySelectorAll('[data-lab-field]').forEach((element) => {
            const value = LAB_DATA[element.dataset.labField];
            if (typeof value === 'string') element.textContent = value;
        });
        const points = root.querySelector('#answer-points');
        LAB_DATA.answerPoints.forEach((point) => {
            const item = document.createElement('li');
            item.textContent = point;
            points.append(item);
        });
        root.querySelector('#notes-input').value = LAB_DATA.note;
    }

    function createTranscriptLine(item, index) {
        const line = document.createElement('button');
        const time = document.createElement('time');
        const text = document.createElement('span');
        line.className = `transcript-line${index === 3 ? ' is-current' : ''}`;
        line.type = 'button';
        line.dataset.transcriptIndex = String(index);
        if (index === 3) line.setAttribute('aria-current', 'true');
        time.textContent = item.time;
        text.textContent = item.text;
        line.append(time, text);
        return line;
    }

    function renderTranscript(root) {
        const list = root.querySelector('#transcript-list');
        LAB_DATA.transcript.forEach((item, index) => {
            list.append(createTranscriptLine(item, index));
        });
        const empty = document.createElement('p');
        empty.className = 'transcript-empty';
        empty.hidden = true;
        empty.textContent = '没有匹配的逐字稿内容。';
        list.append(empty);
    }

    function stripCloneIdentifiers(clone) {
        clone.removeAttribute('id');
        clone.querySelectorAll('[id]').forEach((element) => element.removeAttribute('id'));
        clone.querySelectorAll('[for], [aria-controls], [aria-labelledby]').forEach((element) => {
            element.removeAttribute('for');
            element.removeAttribute('aria-controls');
            element.removeAttribute('aria-labelledby');
        });
        clone.querySelectorAll('button, input, textarea').forEach((element) => {
            element.setAttribute('tabindex', '-1');
            element.setAttribute('disabled', '');
        });
        clone.setAttribute('aria-hidden', 'true');
        clone.inert = true;
        return clone;
    }

    function initLab() {
        const page = document.getElementById('ui-lab');
        const surface = document.getElementById('lab-variant-surface');
        const workspace = document.getElementById('lab-workspace');
        const singlePreview = document.getElementById('single-preview');
        const comparisonPreview = document.getElementById('comparison-preview');
        const comparisonGrid = document.getElementById('comparison-grid');
        const initial = readInitialOptions(window.location.search);
        let currentVariant = initial.variant;
        let currentPreview = initial.preview;
        let currentContentState = initial.contentState;
        let comparisonOpen = false;
        let playing = false;

        setTextFields(workspace);
        renderTranscript(workspace);
        if (initial.embed) document.body.classList.add('is-embed');

        function updateUrl() {
            const params = new URLSearchParams();
            params.set('variant', currentVariant);
            if (currentPreview !== 'auto') params.set('preview', currentPreview);
            if (currentContentState !== 'success') params.set('state', currentContentState);
            if (initial.embed) params.set('embed', '1');
            window.history.replaceState(null, '', `${window.location.pathname}?${params.toString()}`);
        }

        function updateComparison() {
            if (!comparisonOpen) return;
            comparisonGrid.replaceChildren();
            Object.entries(VARIANTS).forEach(([key, variant]) => {
                const card = document.createElement('article');
                const header = document.createElement('header');
                const title = document.createElement('strong');
                const detail = document.createElement('span');
                const viewport = document.createElement('div');
                const scaler = document.createElement('div');
                const cloneSurface = document.createElement('div');
                const clone = stripCloneIdentifiers(workspace.cloneNode(true));

                card.className = 'comparison-card';
                title.textContent = `${variant.code} · ${variant.name}`;
                detail.textContent = variant.parameters['信息密度'];
                header.append(title, detail);
                viewport.className = 'comparison-viewport';
                scaler.className = 'comparison-scaler';
                cloneSurface.className = 'lab-variant-surface';
                cloneSurface.dataset.variant = key;
                cloneSurface.append(clone);
                scaler.append(cloneSurface);
                viewport.append(scaler);
                card.append(header, viewport);
                comparisonGrid.append(card);
            });
        }

        function renderVariant() {
            const variant = VARIANTS[currentVariant];
            page.dataset.variant = currentVariant;
            surface.dataset.variant = currentVariant;
            document.getElementById('direction-code').textContent = variant.code;
            document.getElementById('direction-name').textContent = variant.name;
            document.getElementById('direction-summary').textContent = variant.summary;
            appendDefinitionList(document.getElementById('plain-language-list'), variant.plain);
            appendDefinitionList(document.getElementById('design-parameters-list'), variant.parameters);
            document.querySelectorAll('[data-variant-choice]').forEach((button) => {
                button.setAttribute('aria-pressed', String(button.dataset.variantChoice === currentVariant));
            });
            updateComparison();
            updateUrl();
        }

        function renderPreview() {
            page.dataset.preview = currentPreview;
            const labels = { auto: '自适应画布', desktop: '1280px 桌面画布', mobile: '390px 手机画布' };
            document.getElementById('current-canvas-label').textContent = labels[currentPreview];
            document.querySelectorAll('[data-preview-choice]').forEach((button) => {
                button.setAttribute('aria-pressed', String(button.dataset.previewChoice === currentPreview));
            });
            updateUrl();
        }

        function renderContentState() {
            const state = CONTENT_STATES[currentContentState];
            page.dataset.contentState = currentContentState;
            document.getElementById('state-kicker').textContent = state.kicker;
            document.getElementById('state-title').textContent = state.title;
            document.getElementById('state-description').textContent = state.description;
            document.getElementById('state-action').textContent = state.action;
            document.querySelectorAll('[data-state-choice]').forEach((button) => {
                button.setAttribute('aria-pressed', String(button.dataset.stateChoice === currentContentState));
            });
            updateComparison();
            updateUrl();
        }

        function setResearchTab(name) {
            const selected = name === 'notes' ? 'notes' : 'ai';
            document.querySelectorAll('[data-research-tab]').forEach((button) => {
                button.setAttribute('aria-selected', String(button.dataset.researchTab === selected));
            });
            document.getElementById('ai-panel').hidden = selected !== 'ai';
            document.getElementById('notes-panel').hidden = selected !== 'notes';
        }

        document.querySelectorAll('[data-variant-choice]').forEach((button) => {
            button.addEventListener('click', () => {
                currentVariant = normalizeVariant(button.dataset.variantChoice);
                renderVariant();
            });
        });

        document.querySelectorAll('[data-preview-choice]').forEach((button) => {
            button.addEventListener('click', () => {
                currentPreview = normalizePreview(button.dataset.previewChoice);
                renderPreview();
            });
        });

        document.querySelectorAll('[data-state-choice]').forEach((button) => {
            button.addEventListener('click', () => {
                currentContentState = normalizeContentState(button.dataset.stateChoice);
                renderContentState();
            });
        });

        document.querySelectorAll('[data-research-tab]').forEach((button) => {
            button.addEventListener('click', () => setResearchTab(button.dataset.researchTab));
        });

        document.getElementById('compare-toggle').addEventListener('click', (event) => {
            comparisonOpen = !comparisonOpen;
            event.currentTarget.setAttribute('aria-pressed', String(comparisonOpen));
            event.currentTarget.textContent = comparisonOpen ? '返回单案' : '三案同屏';
            singlePreview.hidden = comparisonOpen;
            comparisonPreview.hidden = !comparisonOpen;
            updateComparison();
        });

        document.getElementById('state-action').addEventListener('click', () => {
            currentContentState = 'success';
            renderContentState();
        });

        function togglePlayback() {
            playing = !playing;
            document.getElementById('media-control-play').textContent = playing ? '暂停' : '播放';
            document.getElementById('media-play').querySelector('span').textContent = playing ? 'Ⅱ' : '▶';
        }

        document.getElementById('media-play').addEventListener('click', togglePlayback);
        document.getElementById('media-control-play').addEventListener('click', togglePlayback);
        document.getElementById('media-timeline').addEventListener('click', () => {
            document.getElementById('media-current-time').textContent = '15:24';
            document.getElementById('media-caption').textContent = LAB_DATA.transcript[6].text;
            document.querySelectorAll('.transcript-line').forEach((line) => {
                const selected = line.dataset.transcriptIndex === '6';
                line.classList.toggle('is-current', selected);
                if (selected) line.setAttribute('aria-current', 'true');
                else line.removeAttribute('aria-current');
            });
        });

        document.getElementById('transcript-list').addEventListener('click', (event) => {
            const line = event.target.closest('[data-transcript-index]');
            if (!line) return;
            const item = LAB_DATA.transcript[Number(line.dataset.transcriptIndex)];
            document.querySelectorAll('.transcript-line').forEach((candidate) => {
                candidate.classList.toggle('is-current', candidate === line);
                if (candidate === line) candidate.setAttribute('aria-current', 'true');
                else candidate.removeAttribute('aria-current');
            });
            document.getElementById('media-current-time').textContent = item.time;
            document.getElementById('media-caption').textContent = item.text;
        });

        document.getElementById('transcript-search').addEventListener('input', (event) => {
            const query = event.currentTarget.value.trim().toLowerCase();
            let visible = 0;
            document.querySelectorAll('[data-transcript-index]').forEach((line) => {
                const item = LAB_DATA.transcript[Number(line.dataset.transcriptIndex)];
                const matches = !query || `${item.time} ${item.text}`.toLowerCase().includes(query);
                line.hidden = !matches;
                if (matches) visible += 1;
            });
            document.querySelector('.transcript-empty').hidden = visible !== 0;
        });

        const noteInput = document.getElementById('notes-input');
        const noteSave = document.getElementById('note-save');
        noteInput.addEventListener('input', () => {
            noteSave.disabled = false;
            document.getElementById('note-status').textContent = '仅本页有未模拟保存的修改';
        });
        noteSave.addEventListener('click', () => {
            noteSave.disabled = true;
            document.getElementById('note-status').textContent = '已模拟保存到页面内存';
        });

        document.getElementById('ai-send').addEventListener('click', () => {
            const input = document.getElementById('ai-input');
            const status = document.getElementById('ai-status');
            if (!input.value.trim()) {
                status.textContent = '请先输入一个模拟问题';
                return;
            }
            input.value = '';
            status.textContent = '已在本页内模拟回应，没有网络请求';
        });

        document.addEventListener('keydown', (event) => {
            if (event.metaKey || event.ctrlKey || event.altKey) return;
            if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) return;
            const candidate = event.key.toLowerCase();
            if (!VARIANTS[candidate]) return;
            currentVariant = candidate;
            renderVariant();
        });

        renderVariant();
        renderPreview();
        renderContentState();
        setResearchTab('ai');
    }

    globalThis.LearnFluxUiLab = Object.freeze({
        LAB_DATA,
        VARIANTS,
        CONTENT_STATES,
        normalizeVariant,
        normalizePreview,
        normalizeContentState,
        readInitialOptions,
    });

    if (typeof document !== 'undefined') {
        document.addEventListener('DOMContentLoaded', initLab);
    }
}());
