/**
 * 视频转录Web应用主要JavaScript文件
 * 负责URL提取、本地存储、API调用等核心功能
 */

const AppTime = typeof module !== 'undefined' && module.exports
    ? require('./time.js') : globalThis.LearnFluxTime;

// 应用配置
const APP_CONFIG = {
    STORAGE_KEYS: {
        BEARER_TOKEN: 'vta_bearer_token',
        WECHAT_WEBHOOK: 'vta_wechat_webhook',
        SPEAKER_RECOGNITION: 'vta_speaker_recognition',
        INCLUDE_COMMENTS: 'vta_include_comments',
        COMMENT_LIMIT: 'vta_comment_limit',
        TASK_HISTORY: 'vta_task_history',
        TRANSCRIPTION_STRATEGY: 'vta_transcription_strategy',
        THEME_PREFERENCE: 'vta_theme_preference'
    },
    API_BASE_URL: '',
    MAX_HISTORY_ITEMS: 200,
    RECENT_HISTORY_ITEMS: 4
};

// 全局变量
let currentTask = null;
let webhookSaveTimer = null;

/**
 * 通用URL提取正则表达式
 */
const URL_PATTERNS = [
    // 标准HTTP/HTTPS URL
    /https?:\/\/[^\s\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]+/gi,
    // 支持无协议的URL（如 www.example.com）
    /(?:www\.)[a-zA-Z0-9][-a-zA-Z0-9]*[a-zA-Z0-9]*\.[a-zA-Z]{2,}[^\s\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]*/gi,
    // 支持短链（如 t.co, bit.ly 等）
    /[a-zA-Z0-9][-a-zA-Z0-9]*[a-zA-Z0-9]*\.[a-zA-Z]{2,}\/[^\s\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]+/gi
];

const VIDEO_URL_DOMAINS = Object.freeze([
    'youtube.com', 'youtu.be', 'bilibili.com', 'b23.tv',
    'xiaohongshu.com', 'xhslink.com', 'xhslink.cn', 'douyin.com',
    'xiaoyuzhoufm.com', 'tiktok.com'
]);
const SHORT_LINK_DOMAINS = Object.freeze([
    't.co', 'bit.ly', 'tinyurl.com', 'short.link',
    'suo.im', 'dwz.cn', 'urlc.cn'
]);
const WWW_EQUIVALENT_DOMAINS = new Set([
    'youtube.com', 'bilibili.com', 'xiaohongshu.com',
    'douyin.com', 'xiaoyuzhoufm.com', 'tiktok.com'
]);

/**
 * 本地存储管理类。管理口令只交换为 HttpOnly 会话，不写入 Web Storage。
 */
class StorageManager {
    static set(key, value) {
        try {
            if (key === APP_CONFIG.STORAGE_KEYS.BEARER_TOKEN) {
                if (value && window.LearnFluxAuth) {
                    return window.LearnFluxAuth.login(value);
                }
                return null;
            } else if (key === APP_CONFIG.STORAGE_KEYS.WECHAT_WEBHOOK) {
                // Webhook 地址直接存储（不是秘密）
                localStorage.setItem(key, value);
            } else {
                localStorage.setItem(key, JSON.stringify(value));
            }
        } catch (e) {
            console.error('Storage failed:', e);
        }
        return null;
    }

    static get(key) {
        try {
            if (key === APP_CONFIG.STORAGE_KEYS.BEARER_TOKEN) {
                return window.LearnFluxAuth
                    ? window.LearnFluxAuth.getTokenPlaceholder()
                    : null;
            }
            const value = localStorage.getItem(key);
            if (!value) return null;

            if (key === APP_CONFIG.STORAGE_KEYS.WECHAT_WEBHOOK) {
                // Webhook 地址直接读取
                return value;
            }
            return JSON.parse(value);
        } catch (e) {
            console.error('Storage read failed:', e);
            return null;
        }
    }

    static remove(key) {
        try {
            if (key === APP_CONFIG.STORAGE_KEYS.BEARER_TOKEN) {
                return window.LearnFluxAuth ? window.LearnFluxAuth.logout() : null;
            }
            localStorage.removeItem(key);
        } catch (e) {
            console.error('Storage removal failed:', e);
        }
        return null;
    }

    static clear() {
        try {
            Object.values(APP_CONFIG.STORAGE_KEYS).forEach(key => {
                localStorage.removeItem(key);
            });
        } catch (e) {
            console.error('清空存储失败:', e);
        }
    }
}

function initializeTranscriptionStrategy() {
    const saved = StorageManager.get(APP_CONFIG.STORAGE_KEYS.TRANSCRIPTION_STRATEGY);
    const strategy = saved === 'cloud' ? 'cloud' : 'local';
    const inputs = Array.from(document.querySelectorAll(
        'input[name="transcription-strategy"], input[name="file-transcription-strategy"]'
    ));
    const select = (value) => {
        inputs.forEach(input => { input.checked = input.value === value; });
        const cloudNote = document.getElementById('link-cloud-note');
        if (cloudNote) cloudNote.hidden = value !== 'cloud';
    };
    select(strategy);
    inputs.forEach(input => input.addEventListener('change', () => {
        if (!input.checked || !['local', 'cloud'].includes(input.value)) return;
        select(input.value);
        StorageManager.set(APP_CONFIG.STORAGE_KEYS.TRANSCRIPTION_STRATEGY, input.value);
    }));
}

async function requireManagementSession(reason) {
    if (!window.LearnFluxAuth || !window.LearnFluxAuth.requireSession) {
        throw new Error('认证组件加载失败，请刷新页面后重试。');
    }
    return window.LearnFluxAuth.requireSession({
        title: '连接后继续学习',
        reason: reason || '输入管理口令建立安全会话，继续当前操作。'
    });
}

/**
 * URL提取和处理工具类
 */
class URLExtractor {
    /**
     * 从文本中提取所有URL，并按平台等价域名去重。
     */
    static extractURLs(text) {
        const urls = [];
        const seenKeys = new Set();
        const source = typeof text === 'string' ? text : '';

        URL_PATTERNS.forEach((pattern) => {
            pattern.lastIndex = 0;
            const matches = source.match(pattern) || [];
            matches.forEach((rawUrl) => {
                const cleanUrl = this.cleanURL(rawUrl);
                const canonicalKey = cleanUrl ? this.canonicalKey(cleanUrl) : null;
                if (cleanUrl && canonicalKey && !seenKeys.has(canonicalKey)) {
                    seenKeys.add(canonicalKey);
                    urls.push(cleanUrl);
                }
            });
        });

        return urls;
    }

    /**
     * 只接受 HTTP/HTTPS，并返回 URL API 规范化、编码后的安全字符串。
     */
    static cleanURL(rawUrl) {
        if (!rawUrl) return null;

        let candidate = String(rawUrl).trim();
        if (!candidate || candidate.length > 4096) return null;
        if (/[\u0000-\u001F\u007F]/.test(candidate)) return null;

        candidate = candidate.replace(/[.,;:!?)\]}>'"。，；：！？）】》'"]+$/, '');
        if (/^[a-zA-Z][a-zA-Z\d+.-]*:/.test(candidate)
            && !/^https?:\/\//i.test(candidate)) {
            return null;
        }
        if (candidate.startsWith('//')) candidate = 'https:' + candidate;
        if (!/^https?:\/\//i.test(candidate)) candidate = 'https://' + candidate;

        try {
            const parsed = new URL(candidate);
            if (!['http:', 'https:'].includes(parsed.protocol)) return null;
            if (!parsed.hostname || parsed.username || parsed.password) return null;
            return parsed.href;
        } catch (error) {
            return null;
        }
    }

    /**
     * 生成候选去重键。仅对已知内容平台视 www 子域为等价地址。
     */
    static canonicalKey(url) {
        try {
            const parsed = new URL(url);
            const hostname = parsed.hostname.toLowerCase();
            if (hostname.startsWith('www.')) {
                const rootHostname = hostname.slice(4);
                if (WWW_EQUIVALENT_DOMAINS.has(rootHostname)) {
                    parsed.hostname = rootHostname;
                }
            }
            return parsed.href;
        } catch (error) {
            return null;
        }
    }

    static hostnameMatches(hostname, domain) {
        return hostname === domain || hostname.endsWith('.' + domain);
    }

    /**
     * 内部排序分数只用于确定推荐候选，不暴露给用户。
     */
    static scoreURL(url) {
        let score = 0;
        let parsed;
        try {
            parsed = new URL(url);
        } catch (error) {
            return score;
        }

        const hostname = parsed.hostname.toLowerCase();
        if (VIDEO_URL_DOMAINS.some((domain) => this.hostnameMatches(hostname, domain))) {
            score += 10;
        }
        if (SHORT_LINK_DOMAINS.some((domain) => this.hostnameMatches(hostname, domain))) {
            score += 5;
        }

        const searchable = (parsed.pathname + parsed.search).toLowerCase();
        const videoKeywords = ['video', 'watch', 'play', 'episode'];
        if (videoKeywords.some((keyword) => searchable.includes(keyword))) score += 3;

        const pathDepth = parsed.pathname.split('/').filter(Boolean).length;
        if (pathDepth > 1) score += pathDepth - 1;
        return score;
    }

    /**
     * 智能URL提取和排序。推荐状态是用户可见的唯一排序信息。
     */
    static extractAndRankURLs(text) {
        const ranked = this.extractURLs(text)
            .map((url, inputOrder) => ({
                url,
                inputOrder,
                internalScore: this.scoreURL(url),
                display: url.length > 120 ? url.substring(0, 117) + '...' : url
            }))
            .sort((first, second) => (
                second.internalScore - first.internalScore
                || first.inputOrder - second.inputOrder
            ));

        return ranked.map((result, index) => ({
            url: result.url,
            display: result.display,
            recommended: index === 0
        }));
    }
}

/**
 * API调用管理类
 */
class APIManager {
    static async submitStudyText(title, content) {
        await requireManagementSession('输入管理口令后，即可创建这份文字学习内容；当前输入会保留。');
        const token = StorageManager.get(APP_CONFIG.STORAGE_KEYS.BEARER_TOKEN);

        const response = await fetch('/api/study/text', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            },
            body: JSON.stringify({ title, content })
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(data.detail || data.message || `提交失败（HTTP ${response.status}）`);
        }
        return data;
    }

    /**
     * 提交转录任务
     */
    static async submitTranscription(url, useSpeakerRecognition, wechatWebhook = null, includeComments = false, commentLimit = 100, preserveSourceFile = false, transcriptionStrategy = 'local') {
        await requireManagementSession('输入管理口令后，即可提交当前链接；已经填写的内容不会丢失。');
        const token = StorageManager.get(APP_CONFIG.STORAGE_KEYS.BEARER_TOKEN);

        const requestBody = {
            url: url,
            use_speaker_recognition: useSpeakerRecognition,
            include_comments: Boolean(includeComments),
            comment_limit: Number.parseInt(commentLimit, 10) || 100,
            preserve_source_file: Boolean(preserveSourceFile)
            ,transcription_strategy: transcriptionStrategy
        };

        // 只有当 webhook 不为空时才添加到请求体中
        if (wechatWebhook && wechatWebhook.trim() !== '') {
            requestBody.wechat_webhook = wechatWebhook.trim();
        }

        const response = await fetch('/api/transcribe', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            },
            body: JSON.stringify(requestBody)
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ message: '请求失败' }));
            throw new Error(errorData.message || `HTTP ${response.status}`);
        }

        return await response.json();
    }

    /**
     * 查询任务状态
     */
    static async getTaskStatus(taskId) {
        const token = StorageManager.get(APP_CONFIG.STORAGE_KEYS.BEARER_TOKEN);

        if (!token) {
            throw new Error('浏览器会话不可用，请重新输入管理口令。');
        }

        const response = await fetch(`/api/task/${taskId}`, {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ message: '查询失败' }));
            throw new Error(errorData.message || `HTTP ${response.status}`);
        }

        return await response.json();
    }

    /**
     * 获取 PostgreSQL/服务端保存的最近任务。
     */
    static async getTaskHistory(limit = APP_CONFIG.RECENT_HISTORY_ITEMS, offset = 0) {
        const token = StorageManager.get(APP_CONFIG.STORAGE_KEYS.BEARER_TOKEN);

        if (!token) {
            throw new Error('浏览器会话不可用，请重新输入管理口令。');
        }

        const query = new URLSearchParams({
            limit: String(limit),
            offset: String(offset)
        });
        const response = await fetch(`/api/tasks?${query.toString()}`, {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ message: '查询失败' }));
            throw new Error(errorData.message || errorData.detail || `HTTP ${response.status}`);
        }

        return await response.json();
    }

    static async confirmCloudQuote(taskId, quoteToken, maxCost) {
        await requireManagementSession('输入管理口令后继续确认当前报价。');
        const token = StorageManager.get(APP_CONFIG.STORAGE_KEYS.BEARER_TOKEN);
        const response = await fetch(`/api/task/${encodeURIComponent(taskId)}/cloud-confirm`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            },
            body: JSON.stringify({
                quote_token: quoteToken,
                accepted_max_cost_cny: String(maxCost)
            })
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.detail || '云端确认失败');
        return data;
    }

    static async retryASR(taskId, strategy) {
        await requireManagementSession('继续处理当前音频，已经下载的内容会保留。');
        const token = StorageManager.get(APP_CONFIG.STORAGE_KEYS.BEARER_TOKEN);
        const response = await fetch(`/api/task/${encodeURIComponent(taskId)}/asr-retry`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            },
            body: JSON.stringify({ transcription_strategy: strategy })
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.detail || data.message || '继续转录失败');
        return data;
    }

    static async useLocalForCloudQuote(taskId) {
        await requireManagementSession('输入管理口令后继续切换转录方式。');
        const token = StorageManager.get(APP_CONFIG.STORAGE_KEYS.BEARER_TOKEN);
        const response = await fetch(`/api/task/${encodeURIComponent(taskId)}/cloud-use-local`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${token}` }
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.detail || '切换本地转录失败');
        return data;
    }

    static async refreshCloudQuote(taskId) {
        await requireManagementSession('输入管理口令后刷新当前报价。');
        const token = StorageManager.get(APP_CONFIG.STORAGE_KEYS.BEARER_TOKEN);
        const response = await fetch(`/api/task/${encodeURIComponent(taskId)}/cloud-refresh`, {
            method: 'POST', headers: { 'Authorization': `Bearer ${token}` }
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.detail || '刷新报价失败');
        return data;
    }

    static async getTaskSummary(viewToken) {
        const token = StorageManager.get(APP_CONFIG.STORAGE_KEYS.BEARER_TOKEN);

        if (!token) {
            throw new Error('浏览器会话不可用，请重新输入管理口令。');
        }

        const response = await fetch(`/api/audit/summary?view_token=${encodeURIComponent(viewToken)}`, {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ message: '摘要查询失败' }));
            throw new Error(errorData.message || `HTTP ${response.status}`);
        }

        return await response.json();
    }

    static async getContentMark(viewToken) {
        const token = StorageManager.get(APP_CONFIG.STORAGE_KEYS.BEARER_TOKEN);

        if (!token) {
            throw new Error('浏览器会话不可用，请重新输入管理口令。');
        }

        const response = await fetch(`/api/marks/transcripts/${encodeURIComponent(viewToken)}`, {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ message: '标记状态查询失败' }));
            throw new Error(errorData.message || errorData.detail || `HTTP ${response.status}`);
        }

        return await response.json();
    }

    static async getAuditHistory(params = {}) {
        const token = StorageManager.get(APP_CONFIG.STORAGE_KEYS.BEARER_TOKEN);

        if (!token) {
            throw new Error('浏览器会话不可用，请重新输入管理口令。');
        }

        const query = new URLSearchParams(params);
        const url = `/api/audit/history${query.toString() ? `?${query.toString()}` : ''}`;
        const response = await fetch(url, {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ message: '历史记录查询失败' }));
            throw new Error(errorData.message || errorData.detail || `HTTP ${response.status}`);
        }

        return await response.json();
    }

    static async deleteTask(taskId) {
        await requireManagementSession('输入管理口令后继续删除这条任务记录。');
        const token = StorageManager.get(APP_CONFIG.STORAGE_KEYS.BEARER_TOKEN);

        const response = await fetch(`/api/task/${encodeURIComponent(taskId)}`, {
            method: 'DELETE',
            headers: { 'Authorization': `Bearer ${token}` },
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(data.message || data.detail || `HTTP ${response.status}`);
        }
        return data;
    }
}

let taskHistoryServerSyncPromise = null;

/**
 * 任务历史管理类
 */
class TaskHistoryManager {
    /**
     * 添加任务到历史记录
     * @param {Object} taskData 任务数据
     * @returns {Object} 包含是否为重复任务的信息
     */
    static addTask(taskData) {
        try {
            const history = this.getHistory();
            const newTask = {
                id: taskData.task_id,
                view_token: taskData.view_token,
                url: taskData.url,
                original_text: taskData.original_text || '',
                title: taskData.title || this.extractTitleFromURL(taskData.url),
                author: taskData.author || '',
                platform: taskData.platform || '',
                description: taskData.description || '',
                summaryPreview: taskData.summaryPreview || '',
                summaryPreviewLoaded: Boolean(taskData.summaryPreview),
                type: taskData.type || '',
                timestamp: Date.now(),
                useSpeakerRecognition: taskData.use_speaker_recognition || false,
                includeComments: taskData.include_comments || false,
                status: taskData.status || 'submitted'
            };

            // 每次提交都是独立任务。相同链接只提示重复，不再删除旧任务入口。
            const oldTask = history.find(task => task.url === newTask.url) || null;
            const isDuplicate = Boolean(oldTask);

            // 将新任务添加到最前面
            history.unshift(newTask);

            // 保持历史记录数量限制
            if (history.length > APP_CONFIG.MAX_HISTORY_ITEMS) {
                history.splice(APP_CONFIG.MAX_HISTORY_ITEMS);
            }

            StorageManager.set(APP_CONFIG.STORAGE_KEYS.TASK_HISTORY, history);
            window.__histPage = 1;  // 新任务回到第 1 页（最新在最前）
            this.renderHistory();

            return {
                isDuplicate: isDuplicate,
                oldTask: oldTask,
                newTask: newTask
            };
        } catch (e) {
            console.error('添加任务历史失败:', e);
            return { isDuplicate: false, error: e.message };
        }
    }

    /**
     * 获取任务历史记录
     */
    static getHistory() {
        return StorageManager.get(APP_CONFIG.STORAGE_KEYS.TASK_HISTORY) || [];
    }

    static timestampFromServer(value) {
        if (!value) return Date.now();
        const parsed = AppTime.parse(value);
        return Number.isNaN(parsed) ? Date.now() : parsed;
    }

    static serverTaskToHistoryEntry(task, cached) {
        const source = cached || {};
        const url = task.url || source.url || '';
        const type = (
            url.startsWith('local://') && !isLocalMediaHistoryItem({ url, title: task.title })
                ? 'file'
                : 'video'
        );
        return Object.assign({}, source, {
            id: task.task_id,
            view_token: task.view_token,
            url: url,
            title: task.title || source.title || this.extractTitleFromURL(url),
            author: task.author || source.author || '',
            platform: task.platform || source.platform || '',
            type: type,
            timestamp: this.timestampFromServer(task.created_at),
            status: task.status || source.status || 'queued',
            progress: normalizeHistoryProgress(task.progress),
            error_message: task.error_message || '',
            completed_at: task.completed_at || null,
            updated_at: task.updated_at || null,
            useSpeakerRecognition: Boolean(task.use_speaker_recognition),
            serverBacked: true
        });
    }

    /**
     * 用服务端任务表恢复最近解析；localStorage 仅保留为快速首屏缓存。
     */
    static async syncFromServer(options = {}) {
        let token = null;
        try { token = StorageManager.get(APP_CONFIG.STORAGE_KEYS.BEARER_TOKEN); } catch (e) { return false; }
        if (!token) return false;
        if (taskHistoryServerSyncPromise) return taskHistoryServerSyncPromise;

        taskHistoryServerSyncPromise = APIManager.getTaskHistory().then((response) => {
            const raw = (response && (response.data || response)) || {};
            const tasks = Array.isArray(raw.items) ? raw.items : [];
            const cachedHistory = this.getHistory();
            const serverEntries = tasks.map((task) => {
                const cached = cachedHistory.find((entry) => entry && entry.id === task.task_id)
                    || cachedHistory.find((entry) => entry && entry.view_token === task.view_token);
                return this.serverTaskToHistoryEntry(task, cached);
            });

            // 帖子洞察等非转录产物暂时仍由各自模块管理；转录任务完全以服务端为准。
            const clientOnlyEntries = cachedHistory.filter((entry) => (
                entry && entry.result_id && !entry.view_token
            ));
            const merged = serverEntries.concat(clientOnlyEntries)
                .sort((a, b) => (b.timestamp || 0) - (a.timestamp || 0))
                .slice(0, APP_CONFIG.MAX_HISTORY_ITEMS);

            StorageManager.set(APP_CONFIG.STORAGE_KEYS.TASK_HISTORY, merged);
            if (options.render !== false) this.renderHistory();
            return true;
        }).catch((error) => {
            console.warn('服务端任务历史同步失败，暂时使用浏览器缓存:', error.message);
            return false;
        }).finally(() => {
            taskHistoryServerSyncPromise = null;
        });

        return taskHistoryServerSyncPromise;
    }

    /**
     * 删除指定任务
     */
    static async deleteTask(taskId) {
        try {
            if (!confirm('确定要删除这个任务记录及服务器缓存吗？删除后同一视频会重新转写。')) {
                return;
            }

            await APIManager.deleteTask(taskId);
            const history = this.getHistory();
            const updatedHistory = history.filter(task => task.id !== taskId);

            StorageManager.set(APP_CONFIG.STORAGE_KEYS.TASK_HISTORY, updatedHistory);
            this.renderHistory();

            UIManager.showStatus('success', '任务记录及服务器缓存已删除');
            setTimeout(UIManager.hideStatus, 2000);
        } catch (e) {
            console.error('删除任务记录失败:', e);
            UIManager.showStatus('error', '删除失败', '请稍后重试');
            setTimeout(UIManager.hideStatus, 3000);
        }
    }

    /**
     * 从URL提取简单标题
     */
    static extractTitleFromURL(url) {
        try {
            const urlObj = new URL(url);
            const hostname = urlObj.hostname.replace('www.', '');

            if (hostname.includes('youtube.com') || hostname.includes('youtu.be')) {
                return 'YouTube视频';
            } else if (hostname.includes('bilibili.com')) {
                return 'Bilibili视频';
            } else if (hostname.includes('xiaohongshu.com') || hostname.includes('xhslink.')) {
                return '小红书内容';
            } else if (hostname.includes('douyin.com')) {
                return '抖音视频';
            } else if (hostname.includes('xiaoyuzhoufm.com')) {
                return '小宇宙播客';
            } else {
                return '视频内容';
            }
        } catch (e) {
            return '视频内容';
        }
    }

    /**
     * 渲染历史记录
     */
    static renderHistory() {
        const allHistory = this.getHistory();
        const container = document.getElementById('history-container');
        const list = document.getElementById('history-list');
        if (!container || !list) return;

        if (allHistory.length === 0) {
            container.style.display = 'none';
            return;
        }
        container.style.display = 'block';

        // 过滤（类型 + 状态 + 日期）→ 按时间倒序（最近靠前）
        const typeFilter = window.__histFilter || 'all';
        const statusFilter = window.__histStatus || 'all';
        const dateFilter = window.__histDate || 'all';
        if (typeFilter === 'marked') {
            syncMarkedHistoryFromServer();
        }
        const filtered = allHistory
            .filter((task) => {
                const t = histTypeOf(task);
                const typeOk = typeFilter === 'all'
                    || (typeFilter === 'marked' && task.is_marked)
                    || (typeFilter !== 'marked' && t === typeFilter);
                const sc = statusInfo(task.status, t).cls;
                const statusOk = statusFilter === 'all'
                    || (statusFilter === 'done' && sc === 'done')
                    || (statusFilter === 'failed' && sc === 'failed')
                    || (statusFilter === 'running' && (sc === 'running' || sc === 'queued' || sc === 'action'));
                return typeOk && statusOk && inDateRange(task.timestamp, dateFilter);
            })
            .sort((a, b) => (b.timestamp || 0) - (a.timestamp || 0));

        // The import surface only shows recent tasks; full browsing lives in history.
        window.__histPage = 1;
        const pageItems = filtered.slice(0, APP_CONFIG.RECENT_HISTORY_ITEMS);

        list.innerHTML = '';
        if (pageItems.length === 0) {
            const empty = document.createElement('div');
            empty.className = 'hist-empty';
            empty.innerHTML = '<span class="empty-icon">—</span>该筛选条件下暂无记录';
            list.appendChild(empty);
        } else {
            pageItems.forEach((task) => list.appendChild(buildHistoryCard(task)));
        }

        refreshHistoryMarks();
        refreshHistoryStatuses();
        refreshHistoryPreviews();
        ensureHistoryStatusPolling();
    }
}

/**
 * 主题管理类
 */
class ThemeManager {
    /**
     * 初始化主题系统
     */
    static initialize() {
        // 获取保存的主题偏好
        const savedTheme = StorageManager.get(APP_CONFIG.STORAGE_KEYS.THEME_PREFERENCE);

        // 如果没有保存的主题，则检测系统偏好
        let theme = savedTheme;
        if (!theme) {
            theme = this.detectSystemTheme();
        }

        // 应用主题
        this.applyTheme(theme);

        // 绑定主题切换按钮事件
        const themeToggle = document.getElementById('theme-toggle');
        if (themeToggle) {
            themeToggle.addEventListener('click', () => this.toggleTheme());
        }

        // 监听系统主题变化（如果用户没有手动设置过主题）
        if (!savedTheme && window.matchMedia) {
            const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
            mediaQuery.addEventListener('change', (e) => {
                // 只在用户未手动设置主题时才自动切换
                const currentSavedTheme = StorageManager.get(APP_CONFIG.STORAGE_KEYS.THEME_PREFERENCE);
                if (!currentSavedTheme) {
                    this.applyTheme(e.matches ? 'dark' : 'light');
                }
            });
        }
    }

    /**
     * 检测系统主题偏好
     */
    static detectSystemTheme() {
        if (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) {
            return 'light';
        }
        return 'dark';
    }

    /**
     * 应用主题
     */
    static applyTheme(theme) {
        const root = document.documentElement;
        const themeToggle = document.getElementById('theme-toggle');

        // 始终通过 data-theme 属性设置主题
        root.setAttribute('data-theme', theme);

        if (theme === 'dark') {
            if (themeToggle) {
                themeToggle.textContent = '浅色';
                themeToggle.title = '切换到浅色模式';
            }
        } else {
            if (themeToggle) {
                themeToggle.textContent = '深色';
                themeToggle.title = '切换到深色模式';
            }
        }
    }

    /**
     * 切换主题
     */
    static toggleTheme() {
        const currentTheme = this.getCurrentTheme();
        const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
        const themeToggle = document.getElementById('theme-toggle');

        // 添加按钮旋转动画
        if (themeToggle) {
            themeToggle.classList.add('switching');
            setTimeout(() => {
                themeToggle.classList.remove('switching');
            }, 600);
        }

        // 保存用户偏好
        StorageManager.set(APP_CONFIG.STORAGE_KEYS.THEME_PREFERENCE, newTheme);

        // 添加页面过渡动画
        const body = document.body;
        body.style.transition = 'all 0.3s cubic-bezier(0.4, 0, 0.2, 1)';

        // 应用新主题
        setTimeout(() => {
            this.applyTheme(newTheme);
        }, 50);

        // 清除过渡样式
        setTimeout(() => {
            body.style.transition = '';
        }, 350);
    }

    /**
     * 获取当前主题
     */
    static getCurrentTheme() {
        return document.documentElement.getAttribute('data-theme') || 'dark';
    }
}

/**
 * UI管理类
 */
class UIManager {
    /**
     * 显示状态信息
     */
    static showStatus(type, message, details = '', options = {}) {
        const container = document.getElementById('status-container');
        const content = document.getElementById('status-content');

        const detailsOpen = Boolean(content.querySelector('.task-status-meta[open]'));
        const focusedId = content.contains(document.activeElement) ? document.activeElement.id : '';
        container.className = `status-container status-${type}${options.scroll === false ? '' : ' fade-in'}`;
        container.setAttribute('role', 'region');
        container.setAttribute('aria-label', '任务状态');
        container.style.display = 'block';

        const statusTitle = document.createElement('div');
        statusTitle.className = 'task-status-title';
        statusTitle.setAttribute('role', 'status');
        statusTitle.textContent = String(message || '');
        if (type === 'loading') {
            const spinner = document.createElement('span');
            spinner.className = 'loading-spinner';
            spinner.setAttribute('aria-hidden', 'true');
            statusTitle.prepend(spinner, document.createTextNode(' '));
        }
        content.replaceChildren(statusTitle);

        if (details) {
            const detailsElement = document.createElement('div');
            detailsElement.style.fontSize = '0.95rem';
            detailsElement.style.opacity = '0.8';
            detailsElement.textContent = String(details);
            content.appendChild(detailsElement);
        }

        if (options.detailsNode) {
            content.appendChild(options.detailsNode);
            const meta = content.querySelector('.task-status-meta');
            if (meta) meta.open = detailsOpen;
            const focusTarget = focusedId && document.getElementById(focusedId);
            if (focusTarget) focusTarget.focus({ preventScroll: true });
        }

        // 滚动到状态区域
        if (options.scroll !== false) {
            container.scrollIntoView({ behavior: 'smooth' });
        }
    }

    /**
     * 隐藏状态信息
     */
    static hideStatus() {
        const container = document.getElementById('status-container');
        container.style.display = 'none';
    }

    /**
     * 更新提交按钮状态
     */
    static updateSubmitButton() {
        const btn = document.getElementById('submit-btn');
        const btnIcon = btn.querySelector('.btn-icon');
        const btnText = btn.querySelector('.btn-text');
        const hint = document.getElementById('submit-hint');

        const selectedURL = getSelectedURL();

        const canSubmit = selectedURL && !currentTask;

        btn.disabled = !canSubmit;

        if (currentTask) {
            btnIcon.textContent = '…';
            btnText.textContent = '处理中...';
            if (hint) hint.textContent = '当前任务处理中，请稍候。';
        } else if (!selectedURL) {
            if (document.body.classList.contains('page-home')) {
                btnText.textContent = '开始学习';
                if (hint) hint.textContent = '粘贴链接后即可开始学习。';
            } else {
                btnIcon.textContent = '↗';
                btnText.textContent = '开始解析';
                if (hint) hint.textContent = '粘贴或选择一个链接后即可开始解析。';
            }
        } else {
            btnIcon.textContent = '↗';
            btnText.textContent = submitLabelForUrl(selectedURL);
            if (hint) hint.textContent = '';
        }
    }

    /**
     * 清除 Webhook 地址
     */
    static clearWebhook() {
        const input = document.getElementById('wechat-webhook');
        input.value = '';
        StorageManager.remove(APP_CONFIG.STORAGE_KEYS.WECHAT_WEBHOOK);

        // 显示提示
        UIManager.showStatus('success', 'Webhook 地址已清除', '已删除浏览器本地保存的 Webhook 地址');
        setTimeout(UIManager.hideStatus, 2000);
    }

    /**
     * 显示 Webhook 保存成功提示
     */
    static showWebhookSaved() {
        UIManager.showStatus('success', '✓ Webhook 地址已保存', '已自动保存到浏览器本地');
        setTimeout(UIManager.hideStatus, 1500);
    }
}

/**
 * 处理文本输入，实时URL提取和预览
 */
function renderURLPreview(previewContainer, urlResults) {
    if (!previewContainer) return;

    previewContainer.replaceChildren();
    if (!Array.isArray(urlResults) || urlResults.length === 0) {
        previewContainer.hidden = true;
        return;
    }

    const ownerDocument = previewContainer.ownerDocument || document;
    const list = ownerDocument.createElement('div');
    list.className = 'detected-urls';

    urlResults.forEach((result, index) => {
        const isDefault = index === 0;
        const option = ownerDocument.createElement('div');
        option.className = 'url-option' + (isDefault ? ' selected' : '');
        option.dataset.url = result.url;

        const input = ownerDocument.createElement('input');
        input.type = 'radio';
        input.id = 'detected-url-' + index;
        input.name = 'selected-url';
        input.value = result.url;
        input.checked = isDefault;

        const label = ownerDocument.createElement('label');
        label.htmlFor = input.id;

        const display = ownerDocument.createElement('span');
        display.className = 'url-display';
        display.textContent = result.display;
        label.append(display);

        if (result.recommended) {
            const recommendation = ownerDocument.createElement('span');
            recommendation.className = 'url-recommendation';
            recommendation.textContent = '推荐';
            label.append(recommendation);
        }

        option.append(input, label);
        list.append(option);
    });

    previewContainer.replaceChildren(list);
    previewContainer.dataset.single = String(urlResults.length === 1);
    previewContainer.hidden = false;
}

function handleTextInput(textarea) {
    const text = textarea.value;
    const urlResults = URLExtractor.extractAndRankURLs(text);
    const previewContainer = document.getElementById('url-preview');

    renderURLPreview(previewContainer, urlResults);
    if (urlResults.length > 0) bindURLSelection();
    UIManager.updateSubmitButton();
}

/**
 * 绑定URL选择事件
 */
function bindURLSelection() {
    const options = document.querySelectorAll('.url-option');

    options.forEach(option => {
        option.addEventListener('click', () => {
            // 移除所有选中状态
            options.forEach(opt => opt.classList.remove('selected'));

            // 添加选中状态
            option.classList.add('selected');

            // 选中对应的单选按钮
            const radio = option.querySelector('input[type="radio"]');
            radio.checked = true;

            UIManager.updateSubmitButton();
        });
    });
}

/**
 * 获取用户选择的URL
 */
function getSelectedURL() {
    const selected = document.querySelector('input[name="selected-url"]:checked');
    return selected ? selected.value : null;
}

/* ============================================================
   工作台：内容识别 / 路由 / 历史筛选 / Tab / 上下文选项
   （函数声明会被提升，供上方 submitTranscription、renderHistory、
    updateSubmitButton 在运行时调用）
   ============================================================ */

/**
 * 内容识别：仅用于工作台展示识别标签，不决定业务跳转。
 * 「单篇深度学习」与「帖子洞察」是独立入口；深度学习提交始终走转录/学习链路。
 */
function classifyContent(url) {
    let host = '';
    let path = '';
    try {
        const u = new URL(url);
        host = u.hostname.replace(/^www\./, '').toLowerCase();
        path = u.pathname;
    } catch (e) {
        return { type: 'unknown', platform: 'unknown', label: '未识别', action: '深度学习解析', soon: false };
    }

    // X / Twitter 帖子：在深度学习入口仍按深度学习处理，不跳转帖子洞察。
    if ((host === 'x.com' || host === 'twitter.com' || host === 'mobile.twitter.com')
        && /\/status\/\d+/.test(path)) {
        return { type: 'video', platform: 'twitter', label: '𝕏 帖子', action: '深度学习解析', soon: false };
    }
    // 微信公众号文章：同上，入口决定产品能力。
    if (host === 'mp.weixin.qq.com') {
        return { type: 'video', platform: 'weixin', label: '微信公众号', action: '深度学习解析', soon: false };
    }
    // 小红书内容
    if (host === 'xiaohongshu.com' || host === 'xhslink.com' || host === 'xhslink.cn') {
        return { type: 'video', platform: 'xiaohongshu', label: '小红书内容', action: '深度学习解析', soon: false };
    }
    // 视频平台
    const videoHosts = ['youtube.com', 'youtu.be', 'bilibili.com', 'b23.tv',
        'douyin.com', 'v.douyin.com', 'iesdouyin.com', 'xiaoyuzhoufm.com',
        'tiktok.com', 'vm.tiktok.com'];
    if (videoHosts.some((h) => host === h || host.endsWith('.' + h))) {
        return { type: 'video', platform: host, label: '视频', action: '深度学习解析', soon: false };
    }
    // 其它/短链：未知，仍尝试深度学习
    return { type: 'unknown', platform: host || 'unknown', label: '未识别', action: '深度学习解析', soon: false };
}

/** 单篇深度学习工作台提交按钮文案：与内容形态解耦，始终深度学习。 */
function submitLabelForUrl(url) {
    return '开始学习';
}

/** 历史状态徽章信息 */
function statusInfo(status, type) {
    const s = (status || '').toString().toLowerCase();
    if (type === 'post') return { cls: 'done', text: '解析完成' };
    if (['done', 'completed', 'success', 'finished'].includes(s)) return { cls: 'done', text: '解析完成' };
    if (s === 'no_transcript') return { cls: 'failed', text: '无可转录内容' };
    if (s === 'canceled') return { cls: 'failed', text: '已取消' };
    if (['failed', 'error', 'fail'].includes(s)) return { cls: 'failed', text: '失败' };
    if (s === 'awaiting_cloud_confirmation') return { cls: 'action', text: '待确认费用' };
    if (['processing', 'running', 'transcribing', 'in_progress', 'calibrating'].includes(s)) return { cls: 'running', text: '处理中' };
    if (['queued', 'pending', 'submitted'].includes(s)) return { cls: 'queued', text: '排队中' };
    return { cls: 'queued', text: '已提交' };
}

function normalizeHistoryProgress(rawProgress) {
    if (!rawProgress || typeof rawProgress !== 'object' || Array.isArray(rawProgress)) return null;
    const progress = {};
    ['stage', 'stage_label', 'percent', 'basis', 'confidence', 'eta_seconds', 'message'].forEach((key) => {
        if (rawProgress[key] !== undefined && rawProgress[key] !== null) progress[key] = rawProgress[key];
    });
    const evidence = rawProgress.evidence;
    if (evidence && typeof evidence === 'object' && !Array.isArray(evidence)) {
        const quote = evidence.cloud_quote;
        if (quote && typeof quote === 'object' && !Array.isArray(quote)) {
            progress.evidence = {
                cloud_quote: {
                    duration_seconds: quote.duration_seconds,
                    billable_seconds: quote.billable_seconds,
                    unit_price_cny_per_second: quote.unit_price_cny_per_second,
                    max_cost_cny: quote.max_cost_cny
                }
            };
        }
    }
    return progress;
}

function formatHistoryCost(value) {
    const amount = Number(value);
    if (!Number.isFinite(amount) || amount < 0) return '';
    return amount.toFixed(2);
}

/** 相对时间 */
function formatRelativeTime(ts) {
    if (!ts) return '';
    const diff = Date.now() - ts;
    const m = Math.floor(diff / 60000);
    if (m < 1) return '刚刚';
    if (m < 60) return m + ' 分钟前';
    const h = Math.floor(m / 60);
    if (h < 24) return h + ' 小时前';
    const d = Math.floor(h / 24);
    if (d < 30) return d + ' 天前';
    return AppTime.format(ts);
}

function escapeHtml(s) {
    return (s == null ? '' : String(s)).replace(/[&<>"']/g, (c) => (
        { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
    ));
}
function escapeAttr(s) { return escapeHtml(s); }
/** 用于内联 onclick 的 JS 字符串实参转义 */
function jsAttr(s) {
    return String(s == null ? '' : s)
        .replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/"/g, '&quot;');
}

function compactText(s, maxLen) {
    const text = String(s == null ? '' : s).replace(/\s+/g, ' ').trim();
    if (!text) return '';
    return text.length > maxLen ? text.slice(0, maxLen - 1) + '…' : text;
}

/** 每页历史条数 */
const HISTORY_PREVIEW_LOADING = new Set();
const HISTORY_MARK_LOADING = new Set();
const HISTORY_MARK_REFRESH_MS = 5000;
const HISTORY_MARKED_SYNC_MS = 5000;
const HISTORY_STATUS_POLL_MS = 5000;
let historyStatusPollTimer = null;
let submittedTaskPollTimer = null;
let markedHistorySyncPromise = null;
let markedHistoryLastSyncAt = 0;

/** 日期范围判断（today / 7d / 30d / 90d / all） */
function inDateRange(ts, rangeKey) {
    if (!rangeKey || rangeKey === 'all' || !ts) return true;
    const now = Date.now();
    const DAY = 86400000;
    if (rangeKey === 'today') {
        return ts >= AppTime.startOfDay(now) && ts <= now;
    }
    if (rangeKey === '7d') return ts >= now - 7 * DAY;
    if (rangeKey === '30d') return ts >= now - 30 * DAY;
    if (rangeKey === '90d') return ts >= now - 90 * DAY;
    return true;
}

/** 构建单条历史卡片 DOM */
const LOCAL_MEDIA_HISTORY_EXTENSIONS = new Set([
    'mp3', 'm4a', 'wav', 'aac', 'flac',
    'mp4', 'ts', 'mov', 'mkv', 'webm', 'avi', 'm4v'
]);

function isLocalMediaHistoryItem(task) {
    const url = String(task && (task.url || task.video_url) || '');
    if (!url.startsWith('local://')) return false;
    const sourceName = String(task && task.title || url).split(/[?#]/, 1)[0];
    const extension = sourceName.includes('.') ? sourceName.split('.').pop().toLowerCase() : '';
    return LOCAL_MEDIA_HISTORY_EXTENSIONS.has(extension);
}

// 历史条目类型：本地音视频按真实扩展名纠正旧数据，再使用已存类型或 URL 推断。
function histTypeOf(task) {
    if (task.type === 'file' && isLocalMediaHistoryItem(task)) return 'video';
    if (task.type) return task.type;
    if (task.view_token) return 'video';
    const cls = classifyContent(task.url).type;
    if (cls === 'post') return 'post';
    return 'video';
}

function buildHistoryCard(task) {
    const cls = classifyContent(task.url);
    const displayTitle = compactText(task.title || '未命名', 100);
    const histType = histTypeOf(task);
    const icon = histType === 'file' ? '文' : (histType === 'post' ? '帖' : '视');
    const typeLabel = histType === 'post' ? '帖子' : (histType === 'file' ? '文件' : '视频');
    const st = statusInfo(task.status, histType);
    const timeStr = formatRelativeTime(task.timestamp);
    const author = compactText(task.author || '', 36);
    const description = compactText(task.description || '', 140);
    const summaryPreview = compactText(task.summaryPreview || '', 180);
    const originalPreview = compactText(task.original_text || '', 140);
    const progress = normalizeHistoryProgress(task.progress);
    const progressValue = progress ? Number(progress.percent) : NaN;
    const hasProgressValue = Number.isFinite(progressValue);
    const progressPercent = hasProgressValue ? Math.max(0, Math.min(100, Math.round(progressValue))) : null;
    const progressLabel = progress && (progress.stage_label || progress.message) || '';
    const quote = progress && progress.evidence && progress.evidence.cloud_quote || {};
    const quoteCost = formatHistoryCost(quote.max_cost_cny);

    const isLocalSource = String(task.url || '').startsWith('local://');
    let host = isLocalSource ? (task.title || '本地文件') : '链接';
    try {
        if (!isLocalSource) host = new URL(task.url).hostname.replace(/^www\./, '');
    } catch (e) { /* keep fallback */ }
    const platformId = String(task.platform || cls.platform || '').toLowerCase();
    const platformLabels = {
        youtube: 'YouTube', bilibili: '哔哩哔哩', douyin: '抖音',
        xiaohongshu: '小红书', xiaoyuzhou: '小宇宙', twitter: '𝕏',
        x: '𝕏', weixin: '公众号', tiktok: 'TikTok', local: '本地文件'
    };
    const platformLabel = platformLabels[platformId] || (isLocalSource ? '本地文件' : platformId || host);

    // 每个转录任务从创建起都使用同一个稳定页面；完成后该页面直接显示结果。
    const taskHref = task.view_token ? `/view/${encodeURIComponent(task.view_token)}` : '';
    let viewBtn;
    if (taskHref) {
        const label = st.cls === 'done'
            ? '查看结果'
            : (st.cls === 'action'
                ? '查看并确认'
                : (st.cls === 'failed' ? '查看详情' : '查看进度'));
        viewBtn = `<a class="hist-btn${st.cls === 'action' ? ' primary' : ''}" href="${escapeAttr(taskHref)}">${label}</a>`;
    } else if (task.result_id) {
        viewBtn = '';
    } else if (st.cls === 'failed') {
        viewBtn = `<a class="hist-btn" href="/add_task_by_web">重试</a>`;
    } else {
        viewBtn = `<a class="hist-btn" href="/add_task_by_web">重新提交</a>`;
    }
    const studyPreviewButton = task.study_available && task.study_url
        ? `<a class="hist-btn" href="${escapeHtml(task.study_url)}">边播边学</a>`
        : '';

    const tags = [];
    if (task.is_marked) tags.push('<span class="hist-feature-tag">精华</span>');
    if (task.useSpeakerRecognition) tags.push('<span class="hist-feature-tag">说话人识别</span>');
    if (task.includeComments) tags.push('<span class="hist-feature-tag">评论洞察</span>');

    let previewText = '';
    if (st.cls === 'action') {
        previewText = quoteCost
            ? `云端音频已准备好，预计费用 ¥${quoteCost}，确认后才会开始转录。`
            : '云端音频已准备好，请确认费用后继续转录。';
    } else if (st.cls === 'running' || st.cls === 'queued') {
        previewText = progressLabel || '任务已保存，正在等待后台处理。';
    } else {
        previewText = summaryPreview || description || originalPreview;
    }
    if (!previewText && histType === 'video' && task.view_token && st.cls === 'done' && !task.summaryPreviewLoaded) {
        previewText = '正在加载摘要预览...';
    } else if (!previewText) {
        previewText = cls.action || '暂无内容预览';
    }
    const progressHtml = (st.cls === 'running' || st.cls === 'queued') && progressPercent !== null
        ? `<div class="hist-progress" aria-label="任务进度 ${progressPercent}%">
                <div class="hist-progress-track"><span style="width: ${progressPercent}%"></span></div>
                <span class="hist-progress-value">${progressPercent}%</span>
           </div>`
        : '';

    const card = document.createElement('div');
    card.className = 'hist-card fade-in';
    card.setAttribute('data-type', histType);
    if (task.id) card.setAttribute('data-task-id', task.id);
    if (task.view_token) card.setAttribute('data-view-token', task.view_token);
    card.innerHTML = `
                <div class="hist-icon">${icon}</div>
                <div class="hist-body">
                    <div class="hist-top-row">
                        <span class="type-badge t-${histType}">${typeLabel}</span>
                        <span class="status-badge s-${st.cls}">${st.text}</span>
                        <span class="hist-title" title="${escapeAttr(task.title || '')}">${escapeHtml(displayTitle)}</span>
                    </div>
                    ${author ? `<div class="hist-author">作者：${escapeHtml(author)}</div>` : ''}
                    <div class="hist-preview">${escapeHtml(previewText)}</div>
                    ${progressHtml}
                    <div class="hist-meta">
                        <span class="hist-platform">${escapeHtml(platformLabel)}</span>
                        <span class="hist-source">${isLocalSource ? escapeHtml(host) : `<a href="${escapeAttr(task.url)}" target="_blank" rel="noopener">${escapeHtml(host)}</a>`}</span>
                        <span class="hist-time">${timeStr}</span>
                        ${tags.join('')}
                    </div>
                </div>
                <div class="hist-actions">
                    ${studyPreviewButton}
                    ${viewBtn}
                    <button class="hist-btn" onclick="copyToClipboard('${jsAttr(task.url)}')">复制</button>
                    <button class="hist-btn danger" onclick="TaskHistoryManager.deleteTask('${jsAttr(task.id)}')">删除</button>
                </div>
            `;
    if (taskHref) {
        card.classList.add('is-clickable');
        card.setAttribute('role', 'link');
        card.setAttribute('tabindex', '0');
        card.setAttribute('aria-label', `${st.cls === 'done' ? '查看结果' : '查看任务进度'}：${displayTitle}`);
        const openTask = () => window.location.assign(taskHref);
        card.addEventListener('click', (event) => {
            if (event.target.closest('a, button, input, select, textarea')) return;
            openTask();
        });
        card.addEventListener('keydown', (event) => {
            if (event.target !== card || !['Enter', ' '].includes(event.key)) return;
            event.preventDefault();
            openTask();
        });
    }
    return card;
}

function hydrateHistoryPreview(entry, card) {
    if (!entry || !entry.view_token) return;
    const st = statusInfo(entry.status, histTypeOf(entry));
    if (st.cls !== 'done' || entry.summaryPreview || entry.summaryPreviewLoaded) return;
    const key = entry.view_token;
    if (HISTORY_PREVIEW_LOADING.has(key)) return;
    HISTORY_PREVIEW_LOADING.add(key);

    APIManager.getTaskSummary(key).then((resp) => {
        const raw = (resp && (resp.data || resp)) || {};
        if (resp && resp.code === 202) return;

        const history = TaskHistoryManager.getHistory();
        const latest = history.find((t) => t && t.view_token === key);
        if (!latest) return;

        latest.summaryPreview = compactText(raw.summary || '', 300);
        latest.summaryPreviewLoaded = true;
        StorageManager.set(APP_CONFIG.STORAGE_KEYS.TASK_HISTORY, history);

        const target = card && card.isConnected
            ? card
            : Array.from(document.querySelectorAll('.hist-card[data-view-token]'))
                .find((node) => node.getAttribute('data-view-token') === key);
        if (target && target.parentNode) {
            target.replaceWith(buildHistoryCard(latest));
        }
    }).catch(() => {
        /* best-effort, ignore */
    }).finally(() => {
        HISTORY_PREVIEW_LOADING.delete(key);
    });
}

function isTerminalHistoryStatus(status, type) {
    const cls = statusInfo(status, type).cls;
    return cls === 'done' || cls === 'failed';
}

function applyTaskStatusToEntry(entry, raw) {
    if (!entry || !raw) return false;
    let changed = false;
    const status = raw.status || raw.task_status || raw.state;
    if (status) {
        const norm = String(status).toLowerCase();
        if (entry.status !== norm) {
            entry.status = norm;
            changed = true;
        }
    }
    ['title', 'author', 'platform', 'view_token', 'completed_at', 'updated_at'].forEach((key) => {
        if (raw[key] && entry[key] !== raw[key]) {
            entry[key] = raw[key];
            changed = true;
        }
    });
    const errorMessage = raw.error_message || raw.error;
    if (errorMessage && entry.error_message !== errorMessage) {
        entry.error_message = errorMessage;
        changed = true;
    }
    const nextProgress = normalizeHistoryProgress(raw.progress || raw.progress_json);
    if (nextProgress && JSON.stringify(entry.progress || null) !== JSON.stringify(nextProgress)) {
        entry.progress = nextProgress;
        changed = true;
    }
    return changed;
}

function findVisibleHistoryCard(entry) {
    if (!entry) return null;
    const taskId = entry.id ? String(entry.id) : '';
    if (taskId) {
        const byTask = Array.from(document.querySelectorAll('.hist-card[data-task-id]'))
            .find((node) => node.getAttribute('data-task-id') === taskId);
        if (byTask) return byTask;
    }
    const viewToken = entry.view_token ? String(entry.view_token) : '';
    if (!viewToken) return null;
    return Array.from(document.querySelectorAll('.hist-card[data-view-token]'))
        .find((node) => node.getAttribute('data-view-token') === viewToken) || null;
}

function replaceVisibleHistoryCard(entry, card) {
    const target = card && card.isConnected ? card : findVisibleHistoryCard(entry);
    if (!target || !target.parentNode) return;
    const nextCard = buildHistoryCard(entry);
    target.replaceWith(nextCard);
    hydrateHistoryPreview(entry, nextCard);
}

function updateHistoryEntryFromStatus(taskId, raw, card) {
    const history = TaskHistoryManager.getHistory();
    const entry = history.find((t) => t && t.id === taskId);
    if (!entry) return null;
    const changed = applyTaskStatusToEntry(entry, raw);
    if (changed) {
        StorageManager.set(APP_CONFIG.STORAGE_KEYS.TASK_HISTORY, history);
    }
    replaceVisibleHistoryCard(entry, card);
    return entry;
}

async function refreshHistoryEntryStatus(taskId, card) {
    let token = null;
    try { token = StorageManager.get(APP_CONFIG.STORAGE_KEYS.BEARER_TOKEN); } catch (e) { return; }
    if (!token) return;
    if (!taskId) return;
    const resp = await APIManager.getTaskStatus(taskId);
    const raw = (resp && (resp.data || resp)) || {};
    updateHistoryEntryFromStatus(taskId, raw, card);
}

/** 深度学习历史任务的状态最佳努力刷新（文档与音视频共用同一真相源） */
function refreshHistoryStatuses() {
    document.querySelectorAll('.hist-card[data-task-id]').forEach((card) => {
        if (card.getAttribute('data-type') === 'post') return;
        const taskId = card.getAttribute('data-task-id');
        refreshHistoryEntryStatus(taskId, card).catch(() => { /* best-effort, ignore */ });
    });
}

async function refreshRunningHistoryStatuses() {
    const history = TaskHistoryManager.getHistory();
    const tasks = history.filter((task) => {
        const type = histTypeOf(task);
        return type !== 'post' && task.id && !isTerminalHistoryStatus(task.status, type);
    });
    await Promise.all(tasks.map((task) => (
        refreshHistoryEntryStatus(task.id).catch(() => { /* best-effort, ignore */ })
    )));
}

function ensureHistoryStatusPolling() {
    if (historyStatusPollTimer) {
        clearTimeout(historyStatusPollTimer);
        historyStatusPollTimer = null;
    }
    let token = null;
    try { token = StorageManager.get(APP_CONFIG.STORAGE_KEYS.BEARER_TOKEN); } catch (e) { return; }
    if (!token) return;
    const hasRunningTask = TaskHistoryManager.getHistory().some((task) => {
        const type = histTypeOf(task);
        return type !== 'post' && task.id && !isTerminalHistoryStatus(task.status, type);
    });
    if (!hasRunningTask) return;
    historyStatusPollTimer = setTimeout(async () => {
        historyStatusPollTimer = null;
        await refreshRunningHistoryStatuses();
        ensureHistoryStatusPolling();
    }, HISTORY_STATUS_POLL_MS);
}

function renderSubmittedTaskStatus(taskId, viewToken, raw, entry, isDuplicate, options = {}) {
    const status = raw && (raw.status || raw.task_status || raw.state) || (entry && entry.status) || 'processing';
    const token = raw && raw.view_token || viewToken || (entry && entry.view_token) || '';
    const type = histTypeOf(entry || { view_token: token });
    const state = statusInfo(status, type);
    const progress = raw && (raw.progress || raw.progress_json) || (entry && entry.progress) || {};
    const detailsNode = document.createElement('div');
    detailsNode.className = 'task-status-body';
    const addText = (text, className = 'task-status-note') => {
        const node = document.createElement('p');
        node.className = className;
        node.textContent = String(text || '');
        detailsNode.appendChild(node);
        return node;
    };
    const title = raw && raw.title || (entry && entry.title) || '';
    if (title) addText(title, 'task-status-subject').title = String(title);
    const actions = document.createElement('div');
    actions.className = 'task-status-actions';
    const addAction = (label, id) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'hist-btn';
        button.id = id;
        button.textContent = label;
        actions.appendChild(button);
        return button;
    };
    if (token) {
        const link = document.createElement('a');
        link.href = `/view/${encodeURIComponent(token)}`;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        link.className = 'hist-btn task-status-link';
        link.id = 'submitted-task-link';
        link.textContent = state.cls === 'done' ? '查看结果' : state.cls === 'failed' ? '查看详情' : '查看进度';
        actions.appendChild(link);
    }
    const show = (kind, message) => {
        if (isDuplicate) addText('已更新相同链接的任务记录');
        detailsNode.appendChild(actions);
        const meta = document.createElement('details');
        meta.className = 'task-status-meta';
        const summary = document.createElement('summary');
        summary.textContent = '任务详情';
        const id = document.createElement('p');
        id.textContent = `任务 ID：${taskId}`;
        meta.append(summary, id);
        detailsNode.appendChild(meta);
        UIManager.showStatus(kind, message, '', { ...options, detailsNode });
    };
    if (status === 'awaiting_cloud_confirmation') {
        const progress = raw && raw.progress || {};
        const evidence = progress.evidence || {};
        const quote = evidence.cloud_quote || progress.cloud_quote || {};
        if (quote.quote_token && quote.max_cost_cny) {
            addText(`音频时长 ${quote.duration_seconds} 秒 · 计费 ${quote.billable_seconds} 秒`);
            addText(`预计费用 ¥${quote.max_cost_cny}，确认后才会开始云端转录。`);
            if (options.cloudQuoteNote) addText(options.cloudQuoteNote);
            addAction('确认云端转录', 'confirm-cloud-quote');
            addAction('改用本地免费', 'use-local-quote');
            show('pending', '等待费用确认');
            const button = document.getElementById('confirm-cloud-quote');
            if (button) button.onclick = async () => {
                button.disabled = true;
                try {
                    await APIManager.confirmCloudQuote(taskId, quote.quote_token, quote.max_cost_cny);
                    UIManager.showStatus('loading', '云端转录已确认', '正在提交转录任务…');
                } catch (error) {
                    if (/quote_expired|quote_token_mismatch|quote_not_confirmable/.test(String(error.message || ''))) {
                        try {
                            const response = await APIManager.getTaskStatus(taskId);
                            const latest = response && (response.data || response) || {};
                            renderSubmittedTaskStatus(taskId, token, latest, entry, false, {
                                ...options, cloudQuoteNote: '报价已更新，请确认预计费用。'
                            });
                        } catch (refreshError) {
                            renderSubmittedTaskStatus(taskId, token, raw, entry, false, {
                                ...options, cloudQuoteNote: '报价暂时无法更新，请稍后重试。'
                            });
                        }
                        return;
                    }
                    button.disabled = false;
                    UIManager.showStatus('error', '确认失败', error.message);
                }
            };
            const localButton = document.getElementById('use-local-quote');
            if (localButton) localButton.onclick = async () => {
                localButton.disabled = true;
                try {
                    await APIManager.useLocalForCloudQuote(taskId);
                    UIManager.showStatus('loading', '已改用本地免费', '正在使用已取得的音频转录，无需重新下载…');
                } catch (error) {
                    localButton.disabled = false;
                    UIManager.showStatus('error', '切换失败', error.message);
                }
            };
            return;
        }
    }
    if (state.cls === 'done') {
        show('success', '解析完成');
        return;
    }
    if (state.cls === 'failed') {
        addText(raw && raw.error_message || '请打开任务详情查看原因');
        if (String(status).toLowerCase() === 'failed' && progress.evidence?.retry_available === true) {
            addText('已保留音频，可继续转录，无需重新下载。');
            const local = addAction('重试本地', 'retry-local-asr');
            const cloud = addAction('改用云端并看费用', 'retry-cloud-asr');
            let retrying = false;
            const retry = async (strategy) => {
                if (retrying) return;
                retrying = true;
                local.disabled = cloud.disabled = true;
                try {
                    await APIManager.retryASR(taskId, strategy);
                    watchSubmittedTask(taskId, token, options);
                } catch (error) {
                    renderSubmittedTaskStatus(taskId, token, {
                        ...raw, error_message: error.message
                    }, entry, false, options);
                }
            };
            local.onclick = () => retry('local');
            cloud.onclick = () => retry('cloud');
        }
        show('error', state.text === '已取消' ? '任务已取消' : '解析失败');
        return;
    }
    if (state.cls === 'action') {
        addText('打开任务页面确认费用，或切换为本地免费转录。');
        show('pending', '等待费用确认');
        return;
    }
    const stageLabel = progress.stage_label || progress.message;
    const percent = progress.percent;
    const hasPercent = percent !== null && percent !== undefined && percent !== ''
        && Number.isFinite(Number(percent));
    if (hasPercent) {
        const value = Math.max(0, Math.min(100, Math.round(Number(percent))));
        const row = document.createElement('div');
        row.className = 'task-status-progress-row';
        const label = document.createElement('span');
        label.textContent = progress.confidence === 'high' ? '处理进度' : '预估进度';
        const number = document.createElement('span');
        number.textContent = `${value}%`;
        row.append(label, number);
        const bar = document.createElement('progress');
        bar.max = 100;
        bar.value = value;
        bar.setAttribute('aria-label', label.textContent);
        detailsNode.append(row, bar);
    }
    addText(state.cls === 'queued' ? '任务已进入队列，开始处理后会自动更新。' : '状态自动更新，可继续提交其他内容。');
    show('loading', stageLabel || (state.cls === 'queued' ? '等待处理' : '正在解析'));

}

function watchSubmittedTask(taskId, viewToken, options = {}) {
    if (submittedTaskPollTimer) {
        clearTimeout(submittedTaskPollTimer);
        submittedTaskPollTimer = null;
    }

    let showDuplicateNote = Boolean(options.isDuplicate);
    const poll = async () => {
        try {
            const resp = await APIManager.getTaskStatus(taskId);
            const raw = (resp && (resp.data || resp)) || {};
            const entry = updateHistoryEntryFromStatus(taskId, raw);
            renderSubmittedTaskStatus(taskId, viewToken, raw, entry, showDuplicateNote, { scroll: false });
            showDuplicateNote = false;
            const type = histTypeOf(entry || { view_token: viewToken });
            const status = raw.status || raw.task_status || raw.state || (entry && entry.status);
            if (!isTerminalHistoryStatus(status, type)) {
                submittedTaskPollTimer = setTimeout(poll, HISTORY_STATUS_POLL_MS);
            } else {
                submittedTaskPollTimer = null;
                ensureHistoryStatusPolling();
            }
        } catch (error) {
            submittedTaskPollTimer = setTimeout(poll, HISTORY_STATUS_POLL_MS);
        }
    };

    renderSubmittedTaskStatus(taskId, viewToken, { status: 'processing', view_token: viewToken }, null, showDuplicateNote);
    submittedTaskPollTimer = setTimeout(poll, 2500);
}

function refreshHistoryPreviews() {
    let token = null;
    try { token = StorageManager.get(APP_CONFIG.STORAGE_KEYS.BEARER_TOKEN); } catch (e) { return; }
    if (!token) return;
    const history = TaskHistoryManager.getHistory();
    document.querySelectorAll('.hist-card[data-view-token]').forEach((card) => {
        const viewToken = card.getAttribute('data-view-token');
        const entry = history.find((t) => t && t.view_token === viewToken);
        hydrateHistoryPreview(entry, card);
    });
}

function refreshHistoryMarks() {
    let token = null;
    try { token = StorageManager.get(APP_CONFIG.STORAGE_KEYS.BEARER_TOKEN); } catch (e) { return; }
    if (!token) return;

    const now = Date.now();
    const history = TaskHistoryManager.getHistory();
    history.forEach((entry) => {
        if (!entry || !entry.view_token) return;
        const checkedAt = Number(entry.markStatusCheckedAt || 0);
        if (checkedAt && now - checkedAt < HISTORY_MARK_REFRESH_MS) return;

        const key = entry.view_token;
        if (HISTORY_MARK_LOADING.has(key)) return;
        HISTORY_MARK_LOADING.add(key);

        APIManager.getContentMark(key).then((resp) => {
            const raw = (resp && (resp.data || resp)) || {};
            const marked = Boolean(raw.marked);
            const latestHistory = TaskHistoryManager.getHistory();
            const latest = latestHistory.find((task) => task && task.view_token === key);
            if (!latest) return;

            const changed = latest.is_marked !== marked || latest.markStatusLoaded !== true;
            latest.is_marked = marked;
            latest.markStatusLoaded = true;
            latest.markStatusCheckedAt = Date.now();
            StorageManager.set(APP_CONFIG.STORAGE_KEYS.TASK_HISTORY, latestHistory);

            if (!changed) return;
            if ((window.__histFilter || 'all') === 'marked') {
                TaskHistoryManager.renderHistory();
                return;
            }
            replaceVisibleHistoryCard(latest);
        }).catch(() => {
            /* best-effort, ignore */
        }).finally(() => {
            HISTORY_MARK_LOADING.delete(key);
        });
    });
}

function historyTimestampFromAuditItem(item) {
    const raw = String(item && item.request_time || '').trim();
    if (!raw) return Date.now();
    const parsed = AppTime.parse(raw);
    return Number.isNaN(parsed) ? Date.now() : parsed;
}

function historyTypeFromAuditItem(item) {
    const url = String(item && item.video_url || '');
    if (url.startsWith('local://')) return isLocalMediaHistoryItem(item) ? 'video' : 'file';
    const platform = String(item && item.platform || '').toLowerCase();
    if (['twitter', 'x', 'xiaohongshu', 'weixin', 'wechat'].includes(platform)) return 'post';
    return 'video';
}

function mergeMarkedHistoryItems(items) {
    if (!Array.isArray(items) || items.length === 0) return false;
    const history = TaskHistoryManager.getHistory();
    let changed = false;
    const checkedAt = Date.now();

    items.forEach((item) => {
        if (!item || !item.view_token) return;
        const next = {
            id: item.task_id || item.view_token,
            view_token: item.view_token,
            url: item.video_url || '',
            title: item.title || item.video_url || '未命名',
            author: item.author || '',
            platform: item.platform || '',
            type: historyTypeFromAuditItem(item),
            timestamp: historyTimestampFromAuditItem(item),
            status: item.status || 'success',
            is_marked: Boolean(item.is_marked),
            markStatusLoaded: true,
            markStatusCheckedAt: checkedAt
        };
        const existingIndex = history.findIndex((task) => (
            task && (
                task.view_token === next.view_token
                || (next.id && task.id === next.id)
            )
        ));
        if (existingIndex === -1) {
            history.unshift(next);
            changed = true;
            return;
        }
        const current = history[existingIndex];
        const merged = Object.assign({}, current, next, {
            summaryPreview: current.summaryPreview || '',
            summaryPreviewLoaded: Boolean(current.summaryPreviewLoaded)
        });
        history[existingIndex] = merged;
        changed = true;
    });

    if (changed) {
        if (history.length > APP_CONFIG.MAX_HISTORY_ITEMS) {
            history.splice(APP_CONFIG.MAX_HISTORY_ITEMS);
        }
        StorageManager.set(APP_CONFIG.STORAGE_KEYS.TASK_HISTORY, history);
    }
    return changed;
}

function syncMarkedHistoryFromServer(force = false) {
    if ((window.__histFilter || 'all') !== 'marked') return Promise.resolve(false);

    let token = null;
    try { token = StorageManager.get(APP_CONFIG.STORAGE_KEYS.BEARER_TOKEN); } catch (e) { return Promise.resolve(false); }
    if (!token) return Promise.resolve(false);

    const now = Date.now();
    if (!force && markedHistoryLastSyncAt && now - markedHistoryLastSyncAt < HISTORY_MARKED_SYNC_MS) {
        return Promise.resolve(false);
    }
    if (markedHistorySyncPromise) return markedHistorySyncPromise;

    markedHistorySyncPromise = APIManager.getAuditHistory({
        marked: 'true',
        status: 'all',
        limit: '100'
    }).then((resp) => {
        markedHistoryLastSyncAt = Date.now();
        const raw = (resp && (resp.data || resp)) || {};
        const changed = mergeMarkedHistoryItems(raw.items || []);
        if (changed) {
            TaskHistoryManager.renderHistory();
        }
        return changed;
    }).catch(() => false).finally(() => {
        markedHistorySyncPromise = null;
    });

    return markedHistorySyncPromise;
}

/** 更新识别横幅 + 视频专属选项可见性 + 按钮文案 */
function updateDetection() {
    const banner = document.getElementById('detect-banner');
    const videoOpts = document.getElementById('video-options');
    const url = getSelectedURL();

    if (!url) {
        if (banner) banner.hidden = true;
        if (videoOpts) videoOpts.hidden = true;
        if (typeof UIManager !== 'undefined') UIManager.updateSubmitButton();
        return;
    }

    const c = classifyContent(url);
    if (banner) {
        const variant = c.type === 'video' ? 'is-video'
            : (c.type === 'post' ? (c.soon ? 'is-soon' : 'is-post') : 'is-unknown');
        banner.className = 'detect-banner ' + variant;
        banner.hidden = false;
        banner.innerHTML = '<span class="db-chip">' + escapeHtml(c.label) + '</span>'
            + '<span class="db-text">将执行：<strong>' + escapeHtml(c.action) + '</strong></span>';
    }
    // 深度学习工作台始终展示解析选项，不因识别为帖子而隐藏。
    if (videoOpts) videoOpts.hidden = false;
    if (typeof UIManager !== 'undefined') UIManager.updateSubmitButton();
}

/** Keep draft recovery and errors independent from button availability. */
function initializeTextImport() {
    const form = document.getElementById('study-text-form');
    const title = document.getElementById('study-text-title');
    const content = document.getElementById('study-text-content');
    const submit = document.getElementById('study-text-submit');
    const status = document.getElementById('study-text-status');
    const count = document.getElementById('study-text-count');
    const note = document.getElementById('study-draft-note');
    const clear = document.getElementById('study-draft-clear');
    if (!form || !title || !content || !submit || !status) return;
    const draftPrefix = 'learnflux_study_text_draft_v2:';
    let draftKey = null;
    let draftOwnerId = null;
    let authResolved = false;
    let submitting = false;
    let authGeneration = 0;
    const getAuth = () => window.LearnFluxAuth?.getState?.() || { status: 'checking' };
    const ownerKey = auth => auth.authenticated && auth.user?.user_id && auth.expires_at
        ? draftPrefix + encodeURIComponent(`${auth.user.user_id}:${auth.expires_at}`)
        : null;
    const updateTextSubmit = () => {
        const hasContent = Boolean(content.value.trim());
        submit.disabled = submitting || !hasContent;
        title.disabled = submitting;
        content.disabled = submitting;
        if (count) count.textContent = `${content.value.length.toLocaleString()} / 200,000 字`;
        if (clear) clear.hidden = !content.value && !title.value;
    };
    const saveDraft = () => {
        updateTextSubmit();
        if (!draftKey) {
            if (note) note.textContent = '连接后可保存当前标签页的草稿';
            return;
        }
        try {
            if (!content.value && !title.value) {
                sessionStorage.removeItem(draftKey);
                if (note) note.textContent = '';
                return;
            }
            sessionStorage.setItem(draftKey, JSON.stringify({ title: title.value, content: content.value }));
            if (note) note.textContent = '草稿已保存在当前标签页';
        } catch (error) {
            if (note) note.textContent = '浏览器未能保存草稿，请保留原文';
        }
    };
    const syncDraftOwner = () => {
        const auth = getAuth();
        if (auth.status === 'checking') return;
        const nextKey = ownerKey(auth);
        const nextOwnerId = auth.authenticated && auth.user?.user_id ? String(auth.user.user_id) : null;
        if (authResolved && nextKey === draftKey) return;
        if (draftKey && nextKey && draftOwnerId === nextOwnerId) {
            // An authenticated session refresh keeps the same owner's active
            // draft and request generation; only its storage scope changes.
            try {
                if (title.value || content.value) {
                    sessionStorage.setItem(nextKey, JSON.stringify({ title: title.value, content: content.value }));
                }
                sessionStorage.removeItem(draftKey);
            } catch (error) {
                if (note) note.textContent = '浏览器未能更新草稿，请保留原文';
            }
            draftKey = nextKey;
            updateTextSubmit();
            return;
        }
        // Preserve text typed during the initial connection, while every logout
        // or change from an identified session clears the previous owner's UI.
        if (authResolved && (draftKey !== null || nextKey === null)) {
            if (draftKey) {
                try { sessionStorage.removeItem(draftKey); } catch (error) { /* Scoped data stays inaccessible to another owner. */ }
            }
            authGeneration += 1;
            submitting = false;
            title.value = '';
            content.value = '';
            status.textContent = '';
            status.dataset.state = '';
            if (note) note.textContent = '';
            if (clear) clear.disabled = false;
        }
        draftKey = nextKey;
        draftOwnerId = nextOwnerId;
        authResolved = true;
        if (draftKey) {
            try {
                // Never read or migrate the previous unscoped/anonymous key.
                const draft = JSON.parse(sessionStorage.getItem(draftKey) || 'null');
                if (!title.value && !content.value && draft && typeof draft.content === 'string') {
                    title.value = typeof draft.title === 'string' ? draft.title.slice(0, 160) : '';
                    content.value = draft.content.slice(0, 200000);
                    if (note) note.textContent = '已恢复当前标签页的草稿';
                }
            } catch (error) { /* A missing draft must never prevent importing text. */ }
        }
        updateTextSubmit();
    };
    syncDraftOwner();
    window.addEventListener?.('learnflux:authchange', syncDraftOwner);
    if (window.LearnFluxAuth?.ready) {
        Promise.resolve(window.LearnFluxAuth.ready).then(syncDraftOwner).catch(() => {});
    }
    title.addEventListener('input', saveDraft);
    content.addEventListener('input', saveDraft);
    if (clear) clear.addEventListener('click', () => {
        if (submitting) return;
        title.value = '';
        content.value = '';
        status.textContent = '草稿已清空，粘贴正文后即可开始学习。';
        status.dataset.state = '';
        saveDraft();
        content.focus();
    });
    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const body = content.value.trim();
        if (submitting || !body) return;
        const submissionGeneration = authGeneration;
        const submissionDraftKey = draftKey;
        submitting = true;
        updateTextSubmit();
        if (clear) clear.disabled = true;
        status.dataset.state = '';
        status.textContent = '正在创建学习内容…';
        try {
            const data = await APIManager.submitStudyText(title.value.trim(), body);
            if (submissionGeneration !== authGeneration) return;
            if (!data.data || !data.data.view_token) throw new Error(data.message || '未返回学习内容标识');
            if (submissionDraftKey) {
                try {
                    sessionStorage.removeItem(submissionDraftKey);
                    if (draftKey && draftKey !== submissionDraftKey) sessionStorage.removeItem(draftKey);
                } catch (error) { /* Navigation can proceed without storage. */ }
            }
            status.textContent = '正在打开学习工作区…';
            window.location.href = '/study/' + data.data.view_token;
        } catch (error) {
            if (submissionGeneration !== authGeneration) return;
            status.dataset.state = 'error';
            status.textContent = error && error.message ? error.message : '提交失败，请重试';
        } finally {
            if (submissionGeneration === authGeneration) {
                submitting = false;
                if (clear) clear.disabled = false;
                updateTextSubmit();
            }
        }
    });
    updateTextSubmit();
}

/** Stage files before starting upload, keeping selection available after failure. */
function initializeFileImport() {
    const dz = document.getElementById('file-dropzone');
    const fileInput = document.getElementById('file-input');
    const selection = document.getElementById('file-selection');
    const name = document.getElementById('selected-file-name');
    const details = document.getElementById('selected-file-details');
    const options = document.getElementById('file-transcription-options');
    const cloudNote = document.getElementById('file-cloud-note');
    const actions = document.getElementById('file-actions');
    const submit = document.getElementById('file-submit');
    const remove = document.getElementById('file-remove');
    const cancel = document.getElementById('file-cancel');
    const status = document.getElementById('file-upload-status');
    if (!dz || !fileInput || !selection || !submit || !status) return;
    const mediaExtensions = new Set(['mp3', 'm4a', 'wav', 'aac', 'flac', 'mp4', 'ts', 'mov', 'mkv', 'webm', 'avi', 'm4v']);
    const documentExtensions = new Set(['txt', 'md', 'markdown', 'csv', 'log', 'html', 'htm', 'pdf', 'docx']);
    let selectedFile = null;
    let activeUpload = null;
    const isMediaFile = fileObj => /^(audio|video)\//.test(fileObj.type || '')
        || mediaExtensions.has(fileObj.name.split('.').pop().toLowerCase());
    const strategy = () => document.querySelector('input[name="file-transcription-strategy"]:checked')?.value || 'local';
    const setStatus = (message, isError = false) => {
        status.textContent = message;
        status.dataset.state = isError ? 'error' : '';
    };
    const renderSelection = () => {
        const busy = Boolean(activeUpload);
        const mediaFile = selectedFile && isMediaFile(selectedFile);
        selection.hidden = !selectedFile;
        if (actions) actions.hidden = !selectedFile;
        if (options) options.hidden = !mediaFile;
        if (cloudNote) cloudNote.hidden = !mediaFile || strategy() !== 'cloud';
        submit.disabled = busy || !selectedFile;
        submit.textContent = busy ? '上传中…' : '开始学习';
        dz.disabled = busy;
        fileInput.disabled = busy;
        if (remove) remove.disabled = busy;
        if (cancel) cancel.hidden = !busy;
        document.querySelectorAll('input[name="file-transcription-strategy"]').forEach(input => { input.disabled = busy; });
        if (selectedFile) {
            if (name) name.textContent = selectedFile.name;
            const bytes = selectedFile.size;
            const size = bytes < 1024 * 1024 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
            const audioFile = (selectedFile.type || '').startsWith('audio/') || ['mp3', 'm4a', 'wav', 'aac', 'flac'].includes(selectedFile.name.split('.').pop().toLowerCase());
            const type = mediaFile ? (audioFile ? '音频' : '视频') : '文档';
            if (details) details.textContent = `${type} · ${size} · ${mediaFile ? (strategy() === 'cloud' ? '先估算云端转录费用' : '本地转录后解析') : '提取正文后解析，无需音视频转录'}`;
        }
    };
    const selectFile = fileObj => {
        if (!fileObj || activeUpload) return;
        const ext = fileObj.name.split('.').pop().toLowerCase();
        if (!isMediaFile(fileObj) && !documentExtensions.has(ext)) {
            setStatus('暂不支持此文件格式，请选择音视频、PDF、DOCX 或文本文件。', true);
            return;
        }
        if (!fileObj.size) {
            setStatus('文件为空，请重新选择。', true);
            return;
        }
        selectedFile = fileObj;
        setStatus('文件已就绪，点击「开始学习」后上传。');
        renderSelection();
    };
    const readUploadResponse = async response => {
        const contentType = (response.headers.get('content-type') || '').toLowerCase();
        return {
            status: response.status,
            ok: response.ok,
            d: contentType.includes('application/json') ? await response.json().catch(() => ({})) : {},
            text: contentType.includes('application/json') ? '' : (await response.text().catch(() => '')).trim(),
        };
    };
    const uploadLocalFile = async () => {
        if (!selectedFile || activeUpload) return;
        const fileObj = selectedFile;
        const attempt = new AbortController();
        activeUpload = attempt;
        renderSelection();
        setStatus('正在连接并准备上传…');
        try {
            await requireManagementSession('输入管理口令后继续上传；已经选择的文件会保留。');
            if (attempt.signal.aborted) return;
            const token = StorageManager.get(APP_CONFIG.STORAGE_KEYS.BEARER_TOKEN);
            const mediaFile = isMediaFile(fileObj);
            const fileStrategyEl = mediaFile ? document.querySelector('input[name="file-transcription-strategy"]:checked') : null;
            const fileStrategy = fileStrategyEl ? fileStrategyEl.value : 'local';
            const fd = new FormData();
            fd.append('file', fileObj);
            fd.append('use_speaker_recognition', 'false');
            fd.append('transcription_strategy', fileStrategy);
            const uploadEndpoint = mediaFile && fileStrategy === 'local' ? '/api/study/upload' : '/api/upload-transcribe';
            setStatus(`正在上传「${fileObj.name}」…`);
            const response = await fetch(uploadEndpoint, {
                method: 'POST',
                headers: { 'Authorization': 'Bearer ' + token },
                body: fd,
                signal: attempt.signal,
            });
            const { status: code, ok, d, text } = await readUploadResponse(response);
            if (attempt.signal.aborted || activeUpload !== attempt) return;
            if (code === 401) throw new Error('浏览器会话已过期，请重新连接后重试。');
            if (code === 403) throw new Error('当前页面的安全校验已失效，请刷新后重试。');
            if (!ok) {
                const message = typeof d.detail === 'string' ? d.detail : d.message;
                throw new Error(message || text || `上传失败（HTTP ${code}）`);
            }
            if (!d || d.code !== 202 || !d.data || !d.data.view_token) throw new Error(d.message || '上传未完成，请重试');
            setStatus('上传成功，正在打开学习内容…');
            TaskHistoryManager.addTask({
                task_id: d.data.task_id,
                view_token: d.data.view_token,
                url: 'local://' + fileObj.name,
                title: fileObj.name,
                type: mediaFile ? 'video' : 'file',
                status: 'submitted',
            });
            window.location.href = '/view/' + d.data.view_token;
        } catch (error) {
            if (activeUpload !== attempt) return;
            if (error.name === 'AbortError') setStatus('上传已取消；已提交的任务仍可在历史记录查看。');
            else if (window.LearnFluxAuth && window.LearnFluxAuth.isCancellation(error)) setStatus('尚未上传，文件选择已保留。');
            else setStatus(error.message || '网络错误，文件选择已保留，请重试。', true);
        } finally {
            if (activeUpload === attempt) {
                activeUpload = null;
                renderSelection();
            }
        }
    };
    dz.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', () => selectFile(fileInput.files?.[0]));
    submit.addEventListener('click', uploadLocalFile);
    if (remove) remove.addEventListener('click', () => {
        if (activeUpload) return;
        selectedFile = null;
        fileInput.value = '';
        setStatus('');
        renderSelection();
    });
    if (cancel) cancel.addEventListener('click', () => {
        if (!activeUpload) return;
        activeUpload.abort();
        activeUpload = null;
        setStatus('上传已取消；已提交的任务仍可在历史记录查看。');
        renderSelection();
    });
    ['dragover', 'dragenter'].forEach(ev => dz.addEventListener(ev, event => {
        event.preventDefault();
        if (!activeUpload) dz.classList.add('dragover');
    }));
    dz.addEventListener('dragleave', event => { event.preventDefault(); dz.classList.remove('dragover'); });
    dz.addEventListener('drop', event => {
        event.preventDefault();
        dz.classList.remove('dragover');
        const files = event.dataTransfer?.files;
        if (files && files.length > 1) {
            setStatus('单篇学习每次选择一个文件，请重新选择。', true);
            return;
        }
        selectFile(files?.[0]);
    });
    document.querySelectorAll('input[name="file-transcription-strategy"], input[name="transcription-strategy"]').forEach(input => {
        input.addEventListener('change', () => queueMicrotask(renderSelection));
    });
    renderSelection();
}

/** 工作台新增交互的初始化 */
function initWorkbenchUI() {
    // 输入 Tab 切换
    const inputTabs = Array.from(document.querySelectorAll('.input-tab'));
    const activateInputTab = (tab, shouldFocus = false) => {
        if (!tab) return;
        inputTabs.forEach((item) => {
            item.classList.remove('active');
            item.setAttribute('aria-selected', 'false');
            item.tabIndex = -1;
        });
        document.querySelectorAll('.input-panel').forEach((panel) => {
            panel.classList.remove('active');
            panel.hidden = true;
        });
        tab.classList.add('active');
        tab.setAttribute('aria-selected', 'true');
        tab.tabIndex = 0;
        const panel = document.getElementById(tab.getAttribute('data-panel'));
        if (panel) {
            panel.classList.add('active');
            panel.hidden = false;
        }
        if (shouldFocus) tab.focus();
    };

    inputTabs.forEach((tab) => {
        tab.addEventListener('click', () => {
            activateInputTab(tab);
        });
        tab.addEventListener('keydown', (event) => {
            const index = inputTabs.indexOf(tab);
            let nextIndex = null;
            if (event.key === 'ArrowRight') nextIndex = (index + 1) % inputTabs.length;
            if (event.key === 'ArrowLeft') nextIndex = (index - 1 + inputTabs.length) % inputTabs.length;
            if (event.key === 'Home') nextIndex = 0;
            if (event.key === 'End') nextIndex = inputTabs.length - 1;
            if (nextIndex === null) return;
            event.preventDefault();
            activateInputTab(inputTabs[nextIndex], true);
        });
    });
    if (window.location.hash === '#local-video-study') {
        const fileTab = document.getElementById('tab-file');
        if (fileTab) fileTab.click();
    }
    if (window.location.hash === '#pasted-text-study') {
        const textTab = document.getElementById('tab-text');
        if (textTab) textTab.click();
    }

    initializeTextImport();
    initializeFileImport();
    const linkCloudNote = document.getElementById('link-cloud-note');
    const updateLinkCloudNote = () => {
        if (linkCloudNote) linkCloudNote.hidden = !document.querySelector('input[name="transcription-strategy"][value="cloud"]:checked');
    };
    document.querySelectorAll('input[name="transcription-strategy"]').forEach(input => {
        input.addEventListener('change', updateLinkCloudNote);
    });
    updateLinkCloudNote();

    // 历史：类型筛选
    document.querySelectorAll('#history-filter .filter-chip').forEach((chip) => {
        chip.addEventListener('click', () => {
            document.querySelectorAll('#history-filter .filter-chip').forEach((c) => c.classList.remove('active'));
            chip.classList.add('active');
            window.__histFilter = chip.getAttribute('data-filter');
            window.__histPage = 1;
            TaskHistoryManager.renderHistory();
        });
    });

    // 历史：日期筛选
    const dateSel = document.getElementById('history-date');
    if (dateSel) {
        dateSel.addEventListener('change', () => {
            window.__histDate = dateSel.value;
            window.__histPage = 1;
            TaskHistoryManager.renderHistory();
        });
    }

    // 历史：状态筛选（成功 / 失败 / 处理中）
    const statusSel = document.getElementById('history-status');
    if (statusSel) {
        statusSel.addEventListener('change', () => {
            window.__histStatus = statusSel.value;
            window.__histPage = 1;
            TaskHistoryManager.renderHistory();
        });
    }

    // 识别横幅：输入或选择变化后更新（setTimeout 让既有 handleTextInput/选择逻辑先跑）
    const share = document.getElementById('share-content');
    const preview = document.getElementById('url-preview');
    if (share) share.addEventListener('input', () => setTimeout(updateDetection, 0));
    if (preview) preview.addEventListener('click', () => setTimeout(updateDetection, 0));
    updateDetection();
}

if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initWorkbenchUI);
    } else {
        initWorkbenchUI();
    }
}

function updateCommentLimitControl() {
    const includeComments = document.getElementById('include-comments');
    const commentLimit = document.getElementById('comment-limit');
    const control = document.getElementById('comment-limit-control');

    if (!includeComments || !commentLimit || !control) {
        return;
    }

    const enabled = includeComments.checked;
    commentLimit.disabled = !enabled;
    control.classList.toggle('disabled', !enabled);
}

/**
 * 复制文本到剪贴板
 */
async function copyToClipboard(text) {
    try {
        await navigator.clipboard.writeText(text);
        UIManager.showStatus('success', '已复制到剪贴板', text);
        setTimeout(UIManager.hideStatus, 2000);
    } catch (e) {
        console.error('复制失败:', e);
        UIManager.showStatus('error', '复制失败', '请手动复制链接');
        setTimeout(UIManager.hideStatus, 3000);
    }
}

/**
 * 提交转录任务
 */
async function submitTranscription(event) {
    event.preventDefault();

    if (currentTask) {
        return;
    }

    const selectedURL = getSelectedURL();

    const speakerRecEl = document.getElementById('speaker-recognition');
    const useSpeakerRecognition = speakerRecEl ? speakerRecEl.checked : false;
    const strategyEl = document.querySelector('input[name="transcription-strategy"]:checked');
    const transcriptionStrategy = strategyEl ? strategyEl.value : 'local';

    const preserveEl = document.getElementById('preserve-source-file');
    const preserveSourceFile = preserveEl ? preserveEl.checked : false;

    const includeCommentsEl = document.getElementById('include-comments');
    const includeComments = includeCommentsEl ? includeCommentsEl.checked : false;

    const commentLimitEl = document.getElementById('comment-limit');
    const commentLimit = commentLimitEl ? (Number.parseInt(commentLimitEl.value, 10) || 100) : 100;

    const wechatWebhookEl = document.getElementById('wechat-webhook');
    const wechatWebhook = wechatWebhookEl ? wechatWebhookEl.value.trim() : '';
    const originalText = document.getElementById('share-content').value.trim();

    if (!selectedURL) {
        UIManager.showStatus('error', '请先选择一个内容链接', '请在上方文本框中输入包含内容链接的文本，系统会自动提取并显示可选链接');
        setTimeout(UIManager.hideStatus, 5000);
        return;
    }

    // 单篇深度学习入口始终提交转录/学习任务，不因链接形态跳转到帖子洞察。

    const token = StorageManager.get(APP_CONFIG.STORAGE_KEYS.BEARER_TOKEN);
    // Removed strict token validation to allow global fallback configurations to handle missing tokens

    try {
        currentTask = { url: selectedURL };
        UIManager.updateSubmitButton();
        UIManager.showStatus('loading', '正在提交转录任务...', '请稍候，正在处理您的请求');

        // 保存设置到本地存储
        StorageManager.set(APP_CONFIG.STORAGE_KEYS.SPEAKER_RECOGNITION, useSpeakerRecognition);
        StorageManager.set(APP_CONFIG.STORAGE_KEYS.INCLUDE_COMMENTS, includeComments);
        StorageManager.set(APP_CONFIG.STORAGE_KEYS.COMMENT_LIMIT, commentLimit);

        const response = await APIManager.submitTranscription(
            selectedURL,
            useSpeakerRecognition,
            wechatWebhook,
            includeComments,
            commentLimit,
            preserveSourceFile,
            transcriptionStrategy
        );

        if (response.code === 202 && response.data && response.data.task_id) {
            const taskData = {
                task_id: response.data.task_id,
                view_token: response.data.view_token,
                url: selectedURL,
                original_text: originalText,
                use_speaker_recognition: useSpeakerRecognition,
                preserve_source_file: preserveSourceFile,
                include_comments: includeComments
            };

            // 添加到历史记录
            const historyResult = TaskHistoryManager.addTask(taskData);
            watchSubmittedTask(response.data.task_id, response.data.view_token, {
                isDuplicate: Boolean(historyResult.isDuplicate)
            });

            // 清空表单
            document.getElementById('share-content').value = '';
            const previewContainer = document.getElementById('url-preview');
            previewContainer.hidden = true;
            previewContainer.replaceChildren();

        } else {
            throw new Error(response.message || '提交失败');
        }

    } catch (error) {
        console.error('提交任务失败:', error);
        UIManager.showStatus('error', '提交任务失败', error.message);
    } finally {
        currentTask = null;
        UIManager.updateSubmitButton();
    }
}

/**
 * 页面初始化
 */
async function initializePage() {
    initializeTranscriptionStrategy();
    // 加载不敏感的浏览器偏好；管理口令只存在于共享会话组件中。
    const savedWebhook = StorageManager.get(APP_CONFIG.STORAGE_KEYS.WECHAT_WEBHOOK);
    const savedSpeakerRecognition = StorageManager.get(APP_CONFIG.STORAGE_KEYS.SPEAKER_RECOGNITION);
    const savedIncludeComments = StorageManager.get(APP_CONFIG.STORAGE_KEYS.INCLUDE_COMMENTS);
    const savedCommentLimit = StorageManager.get(APP_CONFIG.STORAGE_KEYS.COMMENT_LIMIT);

    // HttpOnly 会话不能、也不应回填到口令输入框。

    // 加载 webhook 地址
    if (savedWebhook) {
        const webhookEl = document.getElementById('wechat-webhook');
        if (webhookEl) webhookEl.value = savedWebhook;
    }

    const speakerRecEl = document.getElementById('speaker-recognition');
    if (savedSpeakerRecognition !== null && speakerRecEl) {
        speakerRecEl.checked = savedSpeakerRecognition;
    }

    const includeCommentsEl = document.getElementById('include-comments');
    if (savedIncludeComments !== null && includeCommentsEl) {
        includeCommentsEl.checked = savedIncludeComments;
    }

    const commentLimitEl = document.getElementById('comment-limit');
    if (savedCommentLimit !== null && commentLimitEl) {
        commentLimitEl.value = String(savedCommentLimit);
    }
    updateCommentLimitControl();

    // 绑定事件监听器
    const textarea = document.getElementById('share-content');
    textarea.addEventListener('input', () => handleTextInput(textarea));

    // 确保URL预览区域初始状态正确
    const previewContainer = document.getElementById('url-preview');
    previewContainer.hidden = true;
    previewContainer.replaceChildren();

    const form = document.getElementById('transcribe-form');
    form.addEventListener('submit', submitTranscription);

    const clearWebhookBtn = document.getElementById('clear-webhook');
    if (clearWebhookBtn) {
        clearWebhookBtn.addEventListener('click', UIManager.clearWebhook);
    }

    const webhookEl = document.getElementById('wechat-webhook');
    if (webhookEl) {
        webhookEl.addEventListener('input', (e) => {
            const webhookValue = e.target.value;

            // 立即保存到 localStorage
            StorageManager.set(APP_CONFIG.STORAGE_KEYS.WECHAT_WEBHOOK, webhookValue);

            // 清除之前的定时器
            if (webhookSaveTimer) {
                clearTimeout(webhookSaveTimer);
            }

            // 设置新的定时器：用户停止输入 1 秒后显示保存成功提示
            if (webhookValue.trim() !== '') {
                webhookSaveTimer = setTimeout(() => {
                    UIManager.showWebhookSaved();
                }, 1000);
            }
        });
    }

    if (speakerRecEl) {
        speakerRecEl.addEventListener('change', (e) => {
            StorageManager.set(APP_CONFIG.STORAGE_KEYS.SPEAKER_RECOGNITION, e.target.checked);
        });
    }

    if (includeCommentsEl) {
        includeCommentsEl.addEventListener('change', (e) => {
            StorageManager.set(APP_CONFIG.STORAGE_KEYS.INCLUDE_COMMENTS, e.target.checked);
            updateCommentLimitControl();
        });
    }

    if (commentLimitEl) {
        commentLimitEl.addEventListener('change', (e) => {
            StorageManager.set(
                APP_CONFIG.STORAGE_KEYS.COMMENT_LIMIT,
                Number.parseInt(e.target.value, 10) || 100
            );
        });
    }

    // 先渲染本地记录；只有已有会话时才读取受保护的服务端历史。
    TaskHistoryManager.renderHistory();
    const authState = window.LearnFluxAuth ? await window.LearnFluxAuth.ready : { authenticated: false };
    if (authState.authenticated) TaskHistoryManager.syncFromServer();

    // 从其他页面返回或重新激活标签页时，再从 PostgreSQL 恢复最新状态。
    window.addEventListener('pageshow', () => {
        if (window.LearnFluxAuth && window.LearnFluxAuth.isAuthenticated()) {
            TaskHistoryManager.syncFromServer();
        }
    });
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible'
            && window.LearnFluxAuth
            && window.LearnFluxAuth.isAuthenticated()) {
            TaskHistoryManager.syncFromServer();
        }
    });
    window.addEventListener('learnflux:authchange', (event) => {
        if (event.detail && event.detail.authenticated) TaskHistoryManager.syncFromServer();
    });

    // 初始化主题系统
    ThemeManager.initialize();

    // 初始状态更新
    UIManager.updateSubmitButton();

}

// 页面加载完成后初始化
if (typeof document !== 'undefined') {
    document.addEventListener('DOMContentLoaded', initializePage);
}

// 导出全局函数供HTML使用
if (typeof window !== 'undefined') {
    window.copyToClipboard = copyToClipboard;
}

// 纯 URL 工具同时供 Node 回归测试复用，浏览器行为保持不变。
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {formatRelativeTime, inDateRange, URLExtractor, renderURLPreview, UIManager, renderSubmittedTaskStatus, APIManager, TaskHistoryManager, initializeTranscriptionStrategy, initializeTextImport, initializeFileImport};
}
