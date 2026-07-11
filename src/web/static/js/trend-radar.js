(function () {
    const CURRENT_REPORT_VERSION = "decision-brief-v4";
    const TOKEN_KEY = "vta_bearer_token";
    const ENC = "vta_encrypt_key_2024";

    const stageMeta = {
        "too-early": { label: "太早期", className: "stage-too-early", verdict: "观察，不急" },
        opportunity: { label: "机会期", className: "stage-opportunity", verdict: "现在验证" },
        mature: { label: "成熟期", className: "stage-mature", verdict: "最后窗口" },
        overheated: { label: "过热", className: "stage-overheated", verdict: "谨慎进入" },
        noise: { label: "噪音", className: "stage-noise", verdict: "暂不入场" }
    };

    const stackMeta = {
        energy: { id: "energy", label: "能源", summary: "电力、散热、数据中心选址和能源成本决定 AI 供给上限。" },
        compute: { id: "compute", label: "芯片 / 计算", summary: "GPU、推理芯片、边缘计算和国产替代决定能力成本曲线。" },
        infrastructure: { id: "infrastructure", label: "基础设施 / AI 工厂", summary: "云、数据管线、权限、安全、部署和监控把模型变成可用生产力。" },
        models: { id: "models", label: "模型", summary: "多模态、推理、记忆、Agent 和世界模型决定新应用边界。" },
        applications: { id: "applications", label: "应用", summary: "AI 在行业和生活场景里解决具体问题并接受市场检验。" }
    };

    const needMeta = {
        physiological: { id: "physiological", label: "生理需求", summary: "健康、饮食、睡眠、照护和基础生活质量。" },
        safety: { id: "safety", label: "安全需求", summary: "隐私、合规、就业、财务安全和组织稳定。" },
        belonging: { id: "belonging", label: "归属与爱", summary: "陪伴、社群、家庭连接和亲密关系。" },
        esteem: { id: "esteem", label: "尊重需求", summary: "身份、能力证明、职业竞争力和影响力。" },
        cognitive: { id: "cognitive", label: "认知需求", summary: "学习、理解世界、决策、研究和知识管理。" },
        aesthetic: { id: "aesthetic", label: "审美需求", summary: "创作、设计、娱乐、表达和体验。" },
        self_actualization: { id: "self_actualization", label: "自我实现", summary: "创业、创造、长期目标、个人系统和人生管理。" }
    };

    let trendRadarData = [
        {
            id: "agentic-procurement",
            title: "AI 采购与供应商流程代理",
            domain: "work",
            stackLayer: stackMeta.infrastructure,
            needLayer: needMeta.safety,
            opportunityType: "需求爆发",
            stage: "opportunity",
            score: 91,
            confidence: 82,
            cognitiveGap: 88,
            velocity: 64,
            gapMonths: 10,
            verdict: "适合现在做窄场景验证",
            marketWindow: "高质量英文区认真讨论，中文区还停留在通用 AI 助手叙事。",
            summary: "企业开始把 AI agent 从写作助手迁移到采购、询价、供应商比价等真实流程。",
            socialNeed: "社会实际需求：降低供应链不确定性，让采购、法务和财务流程更可审计。",
            supplyShift: "供给侧变化：Agent 权限、RAG、工作流编排和审计能力让业务流程自动化开始可落地。",
            counterEvidence: ["如果企业无法提供真实历史询价单，说明切入点还不够痛。"],
            userValue: "适合优先做内容占位、用户访谈或服务化验证。",
            whyNow: "业务流程型 agent 正从 demo 进入可衡量 ROI 的试点期。",
            validationAction: "3 天内访谈 5 个外贸/制造采购负责人，交付一个自动询价和报价对比样例。",
            exitSignal: "如果 10 个目标客户中少于 2 个愿意提供真实历史询价单，先降级观察。",
            bestFor: "懂 B2B 流程、能做交付型 SaaS 或咨询转产品的团队。",
            notFor: "只想做通用 AI 工具、没有企业流程交付经验的人。",
            decision: "现在验证",
            sourceQuality: "强",
            evidenceGrade: "A",
            brief: {
                verdict: "现在验证",
                value: "认知差仍可能存在，先用小样本验证真实需求。",
                whyNow: "英文 X 出现前沿讨论，中文平台需求表达仍零散。",
                nextAction: "访谈采购负责人，验证自动询价和条款初筛是否可付费。",
                killCriteria: "如果没有真实数据或预算，降级观察。",
                limitations: "样本只代表本次采样，需要人工复核原文。"
            },
            signals: {
                x: { label: "英文 X", accept: 52, oppose: 21, unknown: 27, signal: "研究者、SaaS 创业者和运营负责人开始争论落地边界。", sample: 180 },
                xiaohongshu: { label: "小红书", accept: 12, oppose: 16, unknown: 72, signal: "少量职场账号提到采购自动化，评论在问能否替代 Excel 流程。", sample: 46 },
                douyin: { label: "抖音", accept: 5, oppose: 18, unknown: 77, signal: "大众侧仍把 AI 理解成聊天工具。", sample: 38 }
            },
            evidence: [
                { platform: "英文 X", type: "英文高质量依据", time: "近 72 小时", displayTitle: "Agent 进入采购流程", displaySummary: "B2B 创业者讨论采购、法务、财务流程中的 Agent 落地边界。", keyFacts: ["英文 X", "创业者讨论", "权限与审计"], url: "https://x.com/" },
                { platform: "小红书", type: "中文需求苗头", time: "近 7 天", displayTitle: "采购人询问自动比价", displaySummary: "职场用户询问能否自动整理供应商报价和询价邮件。", keyFacts: ["小红书", "真实流程问题"], url: "https://www.xiaohongshu.com/" }
            ]
        },
        {
            id: "personal-ai-memory",
            title: "个人 AI 记忆层与生活操作系统",
            domain: "ai",
            stackLayer: stackMeta.applications,
            needLayer: needMeta.cognitive,
            opportunityType: "需求爆发",
            stage: "mature",
            score: 73,
            confidence: 70,
            cognitiveGap: 52,
            velocity: 58,
            gapMonths: 6,
            verdict: "最后入场窗口，必须垂直化",
            marketWindow: "英文区已接近共识，中文区开始出现工作流和第二大脑讨论。",
            summary: "用户开始需要长期记忆而不是一次性问答，但通用入口可能被大模型平台吸收。",
            socialNeed: "社会实际需求：降低个人信息过载，让学习、项目和生活决策可以被持续管理。",
            supplyShift: "供给侧变化：长上下文、工具调用和本地知识库让长期记忆从笔记变成行动系统。",
            counterEvidence: ["如果用户只把它当笔记工具而不愿持续交互，价值可能不足。"],
            userValue: "只适合找垂直场景，不适合做泛用第二大脑。",
            whyNow: "模型长上下文、跨端记录和本地知识库逐渐成熟。",
            validationAction: "选求职、健身或慢病场景，做 20 人手动代运营记忆服务。",
            decision: "只做垂直细分",
            sourceQuality: "中",
            evidenceGrade: "B",
            brief: {
                verdict: "只做垂直细分",
                value: "泛记忆层容易被平台吸收，垂直闭环仍有空间。",
                whyNow: "模型和本地知识库能力成熟，中文用户开始理解第二大脑。",
                nextAction: "做一个具体人群的记忆管家服务。",
                killCriteria: "如果没有复购和持续交互，停止。",
                limitations: "隐私信任成本高。"
            },
            signals: {
                x: { label: "英文 X", accept: 71, oppose: 14, unknown: 15, signal: "AI builder 认同 memory layer 是下一阶段入口。", sample: 260 },
                xiaohongshu: { label: "小红书", accept: 42, oppose: 22, unknown: 36, signal: "用户开始用它管理学习、情绪和职业资料。", sample: 170 },
                douyin: { label: "抖音", accept: 18, oppose: 20, unknown: 62, signal: "大众侧仍以 AI 聊天和提示词玩法为主。", sample: 120 }
            },
            evidence: [
                { platform: "英文 X", type: "共识上升", time: "近 14 天", displayTitle: "Memory layer 讨论增加", displaySummary: "独立开发者围绕个人 OS 和 Agent context 讨论明显增加。", keyFacts: ["英文 X", "开发者讨论"], url: "https://x.com/" }
            ]
        },
        {
            id: "data-center-power",
            title: "AI 数据中心电力与散热瓶颈",
            domain: "infrastructure",
            stackLayer: stackMeta.energy,
            needLayer: needMeta.safety,
            opportunityType: "底层约束",
            stage: "opportunity",
            score: 79,
            confidence: 76,
            cognitiveGap: 68,
            velocity: 62,
            gapMonths: 8,
            verdict: "适合长期跟踪",
            marketWindow: "算力需求上升后，能源和数据中心约束开始决定应用成本。",
            summary: "AI 不只受模型能力限制，也受电力、散热、机房建设和区域政策限制。",
            socialNeed: "社会实际需求：保障数字基础设施稳定，避免 AI 扩张挤压能源和公共资源。",
            supplyShift: "供给侧变化：推理规模扩大，数据中心从云成本问题变成能源和城市规划问题。",
            counterEvidence: ["如果只停留在宏观叙事，没有具体项目或成本变化，不宜短期下注。"],
            userValue: "适合观察能源、IDC、边缘推理和企业成本优化机会。",
            whyNow: "推理负载持续上升，电力成本开始影响 AI 产品毛利。",
            validationAction: "跟踪 3 个数据中心区域的电力价格、审批和云厂商扩容动作。",
            decision: "现在验证",
            sourceQuality: "中",
            evidenceGrade: "B",
            brief: {
                verdict: "现在验证",
                value: "底层约束会反向塑造 AI 应用成本和区域机会。",
                whyNow: "推理需求扩张使能源成为显性变量。",
                nextAction: "建立能源与推理成本监控表。",
                killCriteria: "如果没有可量化成本变化，只保留观察。",
                limitations: "需要产业数据补充。"
            },
            signals: {
                x: { label: "英文 X", accept: 48, oppose: 12, unknown: 40, signal: "投资人和基础设施从业者开始讨论能源约束。", sample: 90 },
                xiaohongshu: { label: "小红书", accept: 2, oppose: 6, unknown: 92, signal: "中文消费侧几乎无感。", sample: 8 },
                douyin: { label: "抖音", accept: 1, oppose: 8, unknown: 91, signal: "大众侧尚未形成概念。", sample: 12 }
            },
            evidence: [
                { platform: "英文 X", type: "基础设施信号", time: "近 7 天", displayTitle: "AI 电力约束被讨论", displaySummary: "基础设施从业者讨论数据中心扩张和能源成本。", keyFacts: ["英文 X", "能源约束"], url: "https://x.com/" }
            ]
        }
    ];

    const state = {
        stage: "all",
        stack: "all",
        need: "all",
        query: "",
        selectedId: trendRadarData[0].id,
        report: null,
        history: [],
        usingFallback: true
    };

    const els = {
        stackGallery: document.getElementById("stack-gallery"),
        needGallery: document.getElementById("need-gallery"),
        curation: document.getElementById("curation-list"),
        matrix: document.getElementById("matrix-list"),
        priority: document.getElementById("priority-list"),
        watch: document.getElementById("watch-list"),
        list: document.getElementById("trend-list"),
        detail: document.getElementById("trend-detail"),
        count: document.getElementById("list-count"),
        search: document.getElementById("trend-search"),
        stack: document.getElementById("stack-filter"),
        need: document.getElementById("need-filter"),
        updated: document.getElementById("last-updated"),
        refresh: document.getElementById("refresh-signals"),
        budget: document.getElementById("run-budget"),
        budgetHint: document.getElementById("budget-hint"),
        status: document.getElementById("run-status"),
        history: document.getElementById("report-history-list"),
        historyCount: document.getElementById("history-count"),
        metrics: {
            newWindow: document.getElementById("metric-new-window"),
            mature: document.getElementById("metric-mature"),
            hot: document.getElementById("metric-hot"),
            confidence: document.getElementById("metric-confidence")
        }
    };

    function escapeHtml(value) {
        return String(value || "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    function truncateText(value, limit) {
        const text = String(value || "").replace(/\s+/g, " ").trim();
        if (text.length <= limit) return text;
        return text.slice(0, Math.max(0, limit - 1)).trim() + "…";
    }

    function sleep(ms) {
        return new Promise((resolve) => window.setTimeout(resolve, ms));
    }

    function getToken() {
        try {
            const raw = localStorage.getItem(TOKEN_KEY);
            if (!raw) return "";
            const decoded = decodeURIComponent(escape(atob(raw.split("").reverse().join(""))));
            return decoded.replace(ENC, "");
        } catch (error) {
            return "";
        }
    }

    function setStatus(message, tone) {
        if (!els.status) return;
        els.status.textContent = message || "";
        els.status.dataset.tone = tone || "neutral";
    }

    function clampBudget() {
        return Math.min(Math.max(Number(els.budget?.value || 2), 1), 5);
    }

    function updateBudgetHint() {
        if (!els.budgetHint) return;
        const budget = clampBudget();
        els.budgetHint.textContent = budget <= 2
            ? "建议 $2，可调高到 $5。"
            : "当前 $" + budget.toFixed(1).replace(/\.0$/, "") + "，适合更深采样。";
    }

    async function apiFetch(url, options) {
        const token = getToken();
        if (!token) {
            throw new Error("还没有设置 API Token。请先在首页或 IP 对标页保存服务访问口令。");
        }
        const headers = Object.assign(
            { "Content-Type": "application/json", "Authorization": "Bearer " + token },
            (options && options.headers) || {}
        );
        let response;
        try {
            response = await fetch(url, Object.assign({}, options || {}, { headers }));
        } catch (error) {
            throw new Error(networkErrorMessage(url, error));
        }
        const text = await response.text();
        let data = {};
        try {
            data = text ? JSON.parse(text) : {};
        } catch (error) {
            data = { error: text || "响应解析失败" };
        }
        if (!response.ok) {
            throw new Error(data.detail || data.error || ("HTTP " + response.status));
        }
        return data;
    }

    function networkErrorMessage(url, error) {
        const detail = error && error.message ? "（" + error.message + "）" : "";
        if (String(url || "").startsWith("/api/")) {
            return "无法连接 8000 后端服务。请确认服务仍在运行后重试" + detail;
        }
        return "网络请求失败" + detail;
    }

    function coerceLayer(value, catalog, fallbackId) {
        if (value && typeof value === "object" && catalog[value.id]) {
            return Object.assign({}, catalog[value.id], value);
        }
        if (typeof value === "string" && catalog[value]) {
            return catalog[value];
        }
        return catalog[fallbackId];
    }

    function inferStack(item) {
        const id = String(item.id || "");
        const text = (item.title || item.summary || "").toLowerCase();
        if (id.includes("glp") || text.includes("glp")) return stackMeta.applications;
        if (text.includes("energy") || text.includes("电力") || text.includes("数据中心")) return stackMeta.energy;
        if (text.includes("gpu") || text.includes("芯片") || text.includes("算力")) return stackMeta.compute;
        if (text.includes("模型") || text.includes("memory layer")) return stackMeta.models;
        if (id.includes("agentic") || text.includes("agent") || text.includes("智能体") || text.includes("流程")) return stackMeta.infrastructure;
        return stackMeta.applications;
    }

    function inferNeed(item) {
        const id = String(item.id || "");
        const text = (item.title || item.summary || "").toLowerCase();
        if (id.includes("glp") || text.includes("健康") || text.includes("减重")) return needMeta.physiological;
        if (text.includes("安全") || text.includes("权限") || text.includes("审计") || text.includes("采购")) return needMeta.safety;
        if (text.includes("陪伴") || text.includes("情绪")) return needMeta.belonging;
        if (text.includes("职业") || text.includes("影响力")) return needMeta.esteem;
        if (text.includes("创作") || text.includes("设计")) return needMeta.aesthetic;
        if (text.includes("创业") || text.includes("人生")) return needMeta.self_actualization;
        return needMeta.cognitive;
    }

    function normalizeTrend(item) {
        const stackLayer = coerceLayer(item.stackLayer || item.stack_layer || inferStack(item), stackMeta, "applications");
        const needLayer = coerceLayer(item.needLayer || item.need_layer || inferNeed(item), needMeta, "cognitive");
        return Object.assign({}, item, {
            id: String(item.id || item.title || "trend").replace(/\s+/g, "-"),
            stackLayer,
            needLayer,
            opportunityType: item.opportunityType || item.opportunity_type || "前沿线索",
            socialNeed: item.socialNeed || item.social_need || ("社会实际需求：" + needLayer.summary),
            supplyShift: item.supplyShift || item.supply_shift || ("供给侧变化：" + stackLayer.summary),
            counterEvidence: Array.isArray(item.counterEvidence || item.counter_evidence)
                ? (item.counterEvidence || item.counter_evidence)
                : [],
            evidence: Array.isArray(item.evidence) ? item.evidence : [],
            brief: item.brief || {},
            signals: item.signals || {},
            stage: item.stage || "noise",
            score: Number(item.score || 0),
            confidence: Number(item.confidence || 0)
        });
    }

    function normalizeReport(report) {
        const items = Array.isArray(report && report.items) ? report.items.map(normalizeTrend) : trendRadarData.map(normalizeTrend);
        return Object.assign({}, report || {}, { items });
    }

    function hasRequiredChineseEvidencePreviews(report) {
        const items = Array.isArray(report && report.items) ? report.items : [];
        const englishRows = items.flatMap((item) => item.evidence || []).filter((row) => row.platform === "英文 X");
        if (!englishRows.length) return true;
        return englishRows.every((row) => row.displayTitle || row.displaySummary || /[\u4e00-\u9fff]/.test(row.title || row.summary || ""));
    }

    function reportNeedsRegeneration(report) {
        if (!report || !Array.isArray(report.items)) return "";
        if (report.analysis_version && report.analysis_version !== CURRENT_REPORT_VERSION) {
            return "legacy_report_version";
        }
        if (!hasRequiredChineseEvidencePreviews(report)) {
            return "missing_chinese_preview";
        }
        return "";
    }

    function filteredItems() {
        const query = state.query.trim().toLowerCase();
        return trendRadarData.filter((item) => {
            if (state.stage !== "all" && item.stage !== state.stage) return false;
            if (state.stack !== "all" && item.stackLayer.id !== state.stack) return false;
            if (state.need !== "all" && item.needLayer.id !== state.need) return false;
            if (!query) return true;
            const haystack = [
                item.title,
                item.summary,
                item.socialNeed,
                item.supplyShift,
                item.stackLayer.label,
                item.needLayer.label,
                item.opportunityType
            ].join(" ").toLowerCase();
            return haystack.includes(query);
        });
    }

    function countBy(items, getter) {
        return items.reduce((acc, item) => {
            const key = getter(item);
            acc[key] = (acc[key] || 0) + 1;
            return acc;
        }, {});
    }

    function renderMetrics(report) {
        const metrics = report.metrics || {};
        els.metrics.newWindow.textContent = String(metrics.new_window ?? trendRadarData.filter((item) => item.stage === "opportunity").length);
        els.metrics.mature.textContent = String(metrics.mature ?? trendRadarData.filter((item) => item.stage === "mature").length);
        els.metrics.hot.textContent = String(metrics.hot ?? trendRadarData.filter((item) => item.stage === "overheated").length);
        els.metrics.confidence.textContent = String(metrics.confidence ?? averageConfidence(trendRadarData)) + "%";
        if (els.updated) {
            const generated = report.generated_at ? new Date(report.generated_at) : null;
            els.updated.textContent = generated && !Number.isNaN(generated.valueOf())
                ? generated.toLocaleString("zh-CN", { hour12: false })
                : "样例报告";
            if (generated) els.updated.dateTime = generated.toISOString();
        }
    }

    function averageConfidence(items) {
        if (!items.length) return 0;
        return Math.round(items.reduce((sum, item) => sum + Number(item.confidence || 0), 0) / items.length);
    }

    function renderStackGallery(items) {
        const counts = countBy(items, (item) => item.stackLayer.id);
        els.stackGallery.innerHTML = Object.values(stackMeta).map((layer) => `
            <article class="stack-tile ${counts[layer.id] ? "is-active" : ""}" data-layer="${escapeHtml(layer.id)}">
                <h3>${escapeHtml(layer.label)}</h3>
                <p>${escapeHtml(layer.summary)}</p>
                <span class="tile-count">${counts[layer.id] || 0}</span>
            </article>
        `).join("");
    }

    function renderNeedGallery(items) {
        const counts = countBy(items, (item) => item.needLayer.id);
        els.needGallery.innerHTML = Object.values(needMeta).map((layer) => `
            <article class="need-tile ${counts[layer.id] ? "is-active" : ""}">
                <h3>${escapeHtml(layer.label)}</h3>
                <p>${escapeHtml(layer.summary)}</p>
                <span class="tile-count">${counts[layer.id] || 0}</span>
            </article>
        `).join("");
    }

    function renderCurationList(items) {
        const top = items.slice().sort((a, b) => b.score - a.score).slice(0, 3);
        if (!top.length) {
            els.curation.innerHTML = '<div class="empty-state">暂无可策展趋势。</div>';
            return;
        }
        els.curation.innerHTML = top.map((item) => `
            <article class="curation-item">
                <div class="badge-row">
                    <span class="stack-badge">${escapeHtml(item.stackLayer.label)}</span>
                    <span class="need-badge">${escapeHtml(item.needLayer.label)}</span>
                </div>
                <h3>${escapeHtml(item.title)}</h3>
                <p>${escapeHtml(truncateText(item.socialNeed || item.summary, 120))}</p>
            </article>
        `).join("");
    }

    function renderMatrixPanel(items) {
        if (!items.length) {
            els.matrix.innerHTML = '<div class="empty-state">暂无二维映射。</div>';
            return;
        }
        const stackLayers = Object.values(stackMeta);
        const needLayers = Object.values(needMeta).slice().reverse();
        const bucket = items.reduce((acc, item) => {
            const key = item.needLayer.id + "::" + item.stackLayer.id;
            if (!acc[key]) acc[key] = [];
            acc[key].push(item);
            acc[key].sort((a, b) => b.score - a.score);
            return acc;
        }, {});

        const header = [
            '<div class="matrix-corner" aria-hidden="true"></div>',
            ...stackLayers.map((layer) => `<div class="matrix-col-head">${escapeHtml(layer.label)}</div>`)
        ].join("");
        const rows = needLayers.map((need) => {
            const cells = stackLayers.map((stack) => {
                const cellItems = (bucket[need.id + "::" + stack.id] || []).slice(0, 3);
                const dots = cellItems.map((item) => `
                    <button type="button" class="matrix-dot-button" data-select-trend="${escapeHtml(item.id)}" title="${escapeHtml(item.title)}">
                        <span class="matrix-signal-dot ${matrixSignalTone(item)} size-${matrixSignalSize(item)}"></span>
                        <span class="sr-only">${escapeHtml(item.title)}</span>
                    </button>
                `).join("");
                return `<div class="matrix-cell ${cellItems.length ? "has-signal" : ""}">${dots}</div>`;
            }).join("");
            return `<div class="matrix-row-head">${escapeHtml(need.label)}</div>${cells}`;
        }).join("");

        els.matrix.innerHTML = header + rows;
    }

    function matrixSignalTone(item) {
        if (item.stage === "overheated") return "hot";
        if (item.stage === "opportunity" || item.stage === "mature") return "warm";
        return "cold";
    }

    function matrixSignalSize(item) {
        if (Number(item.score || 0) >= 85) return 3;
        if (Number(item.score || 0) >= 70) return 2;
        return 1;
    }

    function renderPriorityBoard(items) {
        const priority = items.filter((item) => ["opportunity", "mature"].includes(item.stage)).slice(0, 4);
        const watch = items.filter((item) => !["opportunity", "mature"].includes(item.stage)).slice(0, 4);
        els.priority.innerHTML = priority.length ? priority.map(renderQueueItem).join("") : '<div class="empty-state compact">今天没有需要立即验证的趋势。</div>';
        els.watch.innerHTML = watch.length ? watch.map(renderQueueItem).join("") : '<div class="empty-state compact">暂无观察项。</div>';
    }

    function renderQueueItem(item) {
        return `
            <button type="button" class="queue-item" data-select-trend="${escapeHtml(item.id)}">
                <div class="badge-row">
                    <span class="decision-badge">${escapeHtml(item.decision || item.verdict || stageMeta[item.stage]?.verdict || "继续观察")}</span>
                    <span class="need-badge">${escapeHtml(item.needLayer.label)}</span>
                </div>
                <h3>${escapeHtml(item.title)}</h3>
                <p>${escapeHtml(truncateText(item.validationAction || item.summary, 110))}</p>
            </button>
        `;
    }

    function renderTrendList(items) {
        if (!els.list) return;
        if (els.count) els.count.textContent = items.length ? items.length + " 个候选" : "没有匹配项";
        if (!items.length) {
            els.list.innerHTML = '<div class="empty-state">没有匹配当前筛选的趋势。</div>';
            return;
        }
        els.list.innerHTML = items.map((item) => `
            <div role="listitem">
                <button type="button" class="trend-card ${item.id === state.selectedId ? "is-active" : ""}" data-select-trend="${escapeHtml(item.id)}">
                    <h3>${escapeHtml(item.title)}</h3>
                    <p>${escapeHtml(truncateText(item.summary || item.socialNeed, 110))}</p>
                    <div class="trend-card-meta">
                        <span class="stage-badge ${stageMeta[item.stage]?.className || "stage-noise"}">${escapeHtml(stageMeta[item.stage]?.label || item.stage)}</span>
                        <span class="stack-badge">${escapeHtml(item.stackLayer.label)}</span>
                        <span class="need-badge">${escapeHtml(item.needLayer.label)}</span>
                    </div>
                </button>
            </div>
        `).join("");
    }

    function renderTrendDetail() {
        const item = trendRadarData.find((entry) => entry.id === state.selectedId) || trendRadarData[0];
        if (!item || !els.detail) {
            els.detail.innerHTML = '<div class="empty-state">请选择一个趋势。</div>';
            return;
        }
        const stage = stageMeta[item.stage] || stageMeta.noise;
        els.detail.innerHTML = `
            <div class="detail-hero">
                <div class="detail-meta">
                    <span class="stage-badge ${stage.className}">${escapeHtml(stage.label)}</span>
                    <span class="stack-badge">${escapeHtml(item.stackLayer.label)}</span>
                    <span class="need-badge">${escapeHtml(item.needLayer.label)}</span>
                    <span class="type-badge">${escapeHtml(item.opportunityType)}</span>
                </div>
                <h2>${escapeHtml(item.title)}</h2>
                <p>${escapeHtml(item.summary || "")}</p>
            </div>
            <div class="detail-grid">
                <section class="brief-panel" aria-label="决策简报">
                    <h3>决策简报</h3>
                    <ul class="brief-list">
                        ${briefRow("价值判断", item.brief.value || item.userValue || item.verdict)}
                        ${briefRow("社会需求", item.socialNeed)}
                        ${briefRow("供给变化", item.supplyShift)}
                        ${briefRow("下一步", item.brief.nextAction || item.validationAction)}
                        ${briefRow("反证", (item.counterEvidence || []).join("；") || item.brief.killCriteria || item.exitSignal)}
                    </ul>
                </section>
                <section class="data-quality-panel">
                    <h3>数据质量</h3>
                    <p>证据等级：${escapeHtml(item.evidenceGrade || "C")}；来源质量：${escapeHtml(item.sourceQuality || "待核查")}。</p>
                    <p>${escapeHtml(item.evidenceSummary || item.brief.limitations || "报告不替代人工阅读原文和访谈验证。")}</p>
                </section>
            </div>
            <section class="evidence-section">
                <h3>优先核查来源</h3>
                ${renderEvidence(item.evidence)}
            </section>
        `;
    }

    function briefRow(label, value) {
        if (!value) return "";
        return `<li><strong>${escapeHtml(label)}</strong><span>${escapeHtml(value)}</span></li>`;
    }

    function renderEvidence(rows) {
        if (!rows || !rows.length) {
            return '<div class="empty-state">暂无可打开原始来源。</div>';
        }
        return rows.map((row) => {
            const title = row.displayTitle || row.title || row.author || "原始依据";
            const summary = row.displaySummary || row.summary || row.text || "原文信息不足，只能看到来源标题。";
            const facts = Array.isArray(row.keyFacts) ? row.keyFacts : [row.platform, row.author, row.time].filter(Boolean);
            const link = row.url ? `<a href="${escapeHtml(row.url)}" target="_blank" rel="noreferrer">打开原文</a>` : "无链接";
            return `
                <article class="evidence-card">
                    <div class="evidence-head">
                        <span class="quality-badge">${escapeHtml(row.platform || "来源")}</span>
                        <span>${escapeHtml(row.type || row.quality || "可复核依据")}</span>
                    </div>
                    <h4>${escapeHtml(truncateText(title, 96))}</h4>
                    <p>${escapeHtml(truncateText(summary, 180))}</p>
                    ${row.title && row.title !== title ? `<p class="raw-title">原始标题：${escapeHtml(truncateText(row.title, 120))}</p>` : ""}
                    ${facts.length ? `<ul class="key-fact-list">${facts.slice(0, 4).map((fact) => `<li>${escapeHtml(fact)}</li>`).join("")}</ul>` : ""}
                    <div class="raw-source">${link}</div>
                </article>
            `;
        }).join("");
    }

    function renderNoOpportunityState(reason, message) {
        const diagnostics = state.report && state.report.diagnostics;
        const reasonText = reason === "missing_chinese_preview"
            ? "英文来源尚未生成中文解读，请重新生成报告。"
            : reason === "legacy_report_version"
                ? "旧版报告结构需要重新生成。"
                : message || "本次没有足够可信的机会信号。";
        const detail = diagnostics && diagnostics.discarded_reasons
            ? "过滤原因包括：" + Object.keys(diagnostics.discarded_reasons).join("、") + "，其中 topic_mismatch 表示样本不符合主题相关性。"
            : "";
        const html = `<div class="empty-state"><strong>${escapeHtml(reasonText)}</strong><p>${escapeHtml(detail)}</p></div>`;
        els.curation.innerHTML = html;
        els.list.innerHTML = html;
        els.detail.innerHTML = html;
    }

    function renderAll() {
        const items = filteredItems();
        if (!items.find((item) => item.id === state.selectedId)) {
            state.selectedId = items[0]?.id || trendRadarData[0]?.id || "";
        }
        renderStackGallery(trendRadarData);
        renderNeedGallery(trendRadarData);
        renderCurationList(trendRadarData);
        renderMatrixPanel(trendRadarData);
        renderPriorityBoard(trendRadarData);
        renderTrendList(items);
        renderTrendDetail();
    }

    function renderReport(report) {
        const normalized = normalizeReport(report);
        const reason = reportNeedsRegeneration(normalized);
        state.report = normalized;
        trendRadarData = normalized.items;
        state.selectedId = trendRadarData[0]?.id || "";
        renderMetrics(normalized);
        if (reason) {
            renderNoOpportunityState(reason);
            return;
        }
        if (!trendRadarData.length) {
            renderNoOpportunityState("", "本次没有足够可信的机会信号。");
            return;
        }
        renderAll();
    }

    async function loadLatestReport() {
        try {
            const report = await apiFetch("/api/trend-radar/reports/latest");
            state.usingFallback = false;
            renderReport(report);
            setStatus("");
        } catch (error) {
            state.usingFallback = true;
            renderReport({ analysis_version: CURRENT_REPORT_VERSION, items: trendRadarData });
            setStatus(error.message, "warn");
        }
    }

    async function loadReportHistory() {
        if (!els.history) return;
        try {
            const data = await apiFetch("/api/trend-radar/reports?limit=8");
            state.history = data.items || [];
            els.historyCount.textContent = state.history.length + " 条";
            els.history.innerHTML = state.history.length ? state.history.map((item) => `
                <button type="button" class="history-item" data-report-id="${escapeHtml(item.report_id)}">
                    <h3>${escapeHtml(item.summary?.title || item.report_id)}</h3>
                    <p>${escapeHtml((item.top_titles || []).slice(0, 2).join(" / ") || item.generated_at || "")}</p>
                </button>
            `).join("") : '<div class="empty-state compact">暂无历史记录。</div>';
        } catch (error) {
            els.historyCount.textContent = "读取失败";
            els.history.innerHTML = `<div class="err">${escapeHtml(error.message)}</div>`;
        }
    }

    async function loadHistoryReport(reportId) {
        try {
            const report = await apiFetch("/api/trend-radar/reports/" + encodeURIComponent(reportId));
            renderReport(report);
            setStatus("已载入历史报告。");
        } catch (error) {
            setStatus(error.message, "warn");
        }
    }

    async function waitForReportJob(jobId) {
        for (let attempt = 0; attempt < 120; attempt += 1) {
            await sleep(2500);
            const job = await apiFetch("/api/trend-radar/jobs/" + encodeURIComponent(jobId), { method: "GET" });
            if (job.status === "completed") return job.report;
            if (job.status === "failed") throw new Error(job.error || "趋势雷达生成失败");
            setStatus("后台生成中，已检查 " + (attempt + 1) + " 次。");
        }
        throw new Error("后台生成中，但等待超时。请稍后刷新最近报告。");
    }

    async function runReport() {
        const budget = clampBudget();
        setStatus("正在提交趋势雷达任务。");
        try {
            const job = await apiFetch("/api/trend-radar/reports/run", {
                method: "POST",
                body: JSON.stringify({ budget_usd: budget, mode: "standard" })
            });
            setStatus("后台生成中，任务 " + job.job_id + "。");
            const report = await waitForReportJob(job.job_id);
            renderReport(report);
            await loadReportHistory();
            setStatus("报告已生成。");
        } catch (error) {
            setStatus(error.message, "warn");
        }
    }

    function bindEvents() {
        els.search?.addEventListener("input", () => {
            state.query = els.search.value || "";
            renderAll();
        });
        els.stack?.addEventListener("change", () => {
            state.stack = els.stack.value || "all";
            renderAll();
        });
        els.need?.addEventListener("change", () => {
            state.need = els.need.value || "all";
            renderAll();
        });
        document.querySelectorAll("[data-stage-filter]").forEach((button) => {
            button.addEventListener("click", () => {
                document.querySelectorAll("[data-stage-filter]").forEach((node) => node.classList.remove("is-active"));
                button.classList.add("is-active");
                state.stage = button.dataset.stageFilter || "all";
                renderAll();
            });
        });
        document.addEventListener("click", (event) => {
            const trendButton = event.target.closest("[data-select-trend]");
            if (trendButton) {
                state.selectedId = trendButton.dataset.selectTrend;
                renderAll();
                return;
            }
            const historyButton = event.target.closest("[data-report-id]");
            if (historyButton) {
                loadHistoryReport(historyButton.dataset.reportId);
            }
        });
        els.refresh?.addEventListener("click", runReport);
        els.budget?.addEventListener("input", updateBudgetHint);
    }

    function init() {
        trendRadarData = trendRadarData.map(normalizeTrend);
        bindEvents();
        updateBudgetHint();
        renderReport({ analysis_version: CURRENT_REPORT_VERSION, items: trendRadarData });
        loadLatestReport();
        loadReportHistory();
    }

    init();
}());
