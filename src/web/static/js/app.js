/**
 * 视频转录Web应用主要JavaScript文件
 * 负责URL提取、本地存储、API调用等核心功能
 */

// 应用配置
const APP_CONFIG = {
    STORAGE_KEYS: {
        BEARER_TOKEN: 'vta_bearer_token',
        WECHAT_WEBHOOK: 'vta_wechat_webhook',
        SPEAKER_RECOGNITION: 'vta_speaker_recognition',
        INCLUDE_COMMENTS: 'vta_include_comments',
        COMMENT_LIMIT: 'vta_comment_limit',
        TASK_HISTORY: 'vta_task_history',
        THEME_PREFERENCE: 'vta_theme_preference'
    },
    API_BASE_URL: '',
    MAX_HISTORY_ITEMS: 200,
    ENCRYPTION_KEY: 'vta_encrypt_key_2024' // 简单的加密密钥
};

// 全局变量
let currentTask = null;
let isAdvancedSettingsExpanded = false;
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

/**
 * 简单加密函数（Base64 + 简单混淆）
 */
function simpleEncrypt(text) {
    if (!text) return '';
    try {
        const encoded = btoa(unescape(encodeURIComponent(text + APP_CONFIG.ENCRYPTION_KEY)));
        return encoded.split('').reverse().join('');
    } catch (e) {
        console.error('加密失败:', e);
        return text;
    }
}

/**
 * 简单解密函数
 */
function simpleDecrypt(encoded) {
    if (!encoded) return '';
    try {
        const reversed = encoded.split('').reverse().join('');
        const decoded = decodeURIComponent(escape(atob(reversed)));
        return decoded.replace(APP_CONFIG.ENCRYPTION_KEY, '');
    } catch (e) {
        console.error('解密失败:', e);
        return encoded;
    }
}

/**
 * 本地存储管理类
 */
class StorageManager {
    static set(key, value) {
        try {
            if (key === APP_CONFIG.STORAGE_KEYS.BEARER_TOKEN) {
                // 敏感信息加密存储
                localStorage.setItem(key, simpleEncrypt(value));
            } else if (key === APP_CONFIG.STORAGE_KEYS.WECHAT_WEBHOOK) {
                // Webhook 地址直接存储（不是秘密）
                localStorage.setItem(key, value);
            } else {
                localStorage.setItem(key, JSON.stringify(value));
            }
        } catch (e) {
            console.error('存储失败:', e);
        }
    }

    static get(key) {
        try {
            const value = localStorage.getItem(key);
            if (!value) return null;

            if (key === APP_CONFIG.STORAGE_KEYS.BEARER_TOKEN) {
                // 敏感信息解密
                return simpleDecrypt(value);
            } else if (key === APP_CONFIG.STORAGE_KEYS.WECHAT_WEBHOOK) {
                // Webhook 地址直接读取
                return value;
            } else {
                return JSON.parse(value);
            }
        } catch (e) {
            console.error('读取存储失败:', e);
            return null;
        }
    }

    static remove(key) {
        try {
            localStorage.removeItem(key);
        } catch (e) {
            console.error('删除存储失败:', e);
        }
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

/**
 * URL提取和处理工具类
 */
class URLExtractor {
    /**
     * 从文本中提取所有URL
     */
    static extractURLs(text) {
        const urls = [];
        const seenUrls = new Set();

        URL_PATTERNS.forEach(pattern => {
            const matches = text.match(pattern);
            if (matches) {
                matches.forEach(url => {
                    const cleanUrl = this.cleanURL(url);
                    if (cleanUrl && !seenUrls.has(cleanUrl)) {
                        seenUrls.add(cleanUrl);
                        urls.push(cleanUrl);
                    }
                });
            }
        });

        return urls;
    }

    /**
     * 清理URL（移除末尾标点符号，确保协议前缀等）
     */
    static cleanURL(url) {
        if (!url) return null;

        // 移除末尾的标点符号和特殊字符
        url = url.replace(/[.,;:!?)\]}>'"。，；：！？）】》'"]+$/, '');

        // 确保有协议前缀
        if (!url.match(/^https?:\/\//)) {
            url = 'https://' + url;
        }

        // 基本URL格式验证
        try {
            new URL(url);
            return url;
        } catch (e) {
            return null;
        }
    }

    /**
     * URL评分系统，优先显示最可能的视频链接
     */
    static scoreURL(url) {
        let score = 0;

        // 已知视频平台域名加分
        const videoDomains = [
            'youtube.com', 'youtu.be', 'bilibili.com', 'b23.tv',
            'xiaohongshu.com', 'xhslink.com', 'douyin.com', 'v.douyin.com',
            'xiaoyuzhoufm.com', 'tiktok.com', 'vm.tiktok.com'
        ];

        if (videoDomains.some(domain => url.includes(domain))) {
            score += 10;
        }

        // 短链服务域名加分
        const shortLinkDomains = [
            't.co', 'bit.ly', 'tinyurl.com', 'short.link',
            'suo.im', 'dwz.cn', 'urlc.cn'
        ];

        if (shortLinkDomains.some(domain => url.includes(domain))) {
            score += 5;
        }

        // URL包含视频相关关键词加分
        const videoKeywords = ['video', 'watch', 'v', 'play', 'episode'];
        if (videoKeywords.some(keyword => url.toLowerCase().includes(keyword))) {
            score += 3;
        }

        // 更长的路径通常是内容页面
        const pathLength = url.split('/').length;
        if (pathLength > 3) {
            score += pathLength - 3;
        }

        return score;
    }

    /**
     * 智能URL提取和排序
     */
    static extractAndRankURLs(text) {
        const urls = this.extractURLs(text);

        return urls.map(url => ({
            url: url,
            score: this.scoreURL(url),
            display: url.length > 50 ? url.substring(0, 47) + '...' : url
        })).sort((a, b) => b.score - a.score);
    }
}

/**
 * API调用管理类
 */
class APIManager {
    /**
     * 提交转录任务
     */
    static async submitTranscription(url, useSpeakerRecognition, wechatWebhook = null, includeComments = false, commentLimit = 100, preserveSourceFile = false) {
        const token = StorageManager.get(APP_CONFIG.STORAGE_KEYS.BEARER_TOKEN);

        if (!token) {
            throw new Error('请先设置API访问令牌');
        }

        const requestBody = {
            url: url,
            use_speaker_recognition: useSpeakerRecognition,
            include_comments: Boolean(includeComments),
            comment_limit: Number.parseInt(commentLimit, 10) || 100,
            preserve_source_file: Boolean(preserveSourceFile)
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
            throw new Error('请先设置API访问令牌');
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
}

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
                timestamp: Date.now(),
                useSpeakerRecognition: taskData.use_speaker_recognition || false,
                includeComments: taskData.include_comments || false,
                status: 'submitted'
            };

            // 基于URL去重：相同URL只保留最新的记录
            const existingUrlIndex = history.findIndex(task => task.url === newTask.url);
            let isDuplicate = false;
            let oldTask = null;

            if (existingUrlIndex !== -1) {
                // 如果已存在相同URL的任务，移除旧的记录
                oldTask = history[existingUrlIndex];
                history.splice(existingUrlIndex, 1);
                isDuplicate = true;
                console.log(`检测到重复URL，已移除旧记录: ${newTask.url}`);
            }

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

    /**
     * 删除指定任务
     */
    static deleteTask(taskId) {
        try {
            if (!confirm('确定要删除这个任务记录吗？')) {
                return;
            }

            const history = this.getHistory();
            const updatedHistory = history.filter(task => task.id !== taskId);

            StorageManager.set(APP_CONFIG.STORAGE_KEYS.TASK_HISTORY, updatedHistory);
            this.renderHistory();

            UIManager.showStatus('success', '任务记录已删除');
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
            } else if (hostname.includes('xiaohongshu.com')) {
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
        const filtered = allHistory
            .filter((task) => {
                const t = histTypeOf(task);
                const typeOk = typeFilter === 'all' || t === typeFilter;
                const sc = statusInfo(task.status, t).cls;
                const statusOk = statusFilter === 'all'
                    || (statusFilter === 'done' && sc === 'done')
                    || (statusFilter === 'failed' && sc === 'failed')
                    || (statusFilter === 'running' && (sc === 'running' || sc === 'queued'));
                return typeOk && statusOk && inDateRange(task.timestamp, dateFilter);
            })
            .sort((a, b) => (b.timestamp || 0) - (a.timestamp || 0));

        // 分页
        const totalPages = Math.max(1, Math.ceil(filtered.length / HISTORY_PAGE_SIZE));
        let page = Math.min(Math.max(window.__histPage || 1, 1), totalPages);
        window.__histPage = page;
        const pageItems = filtered.slice((page - 1) * HISTORY_PAGE_SIZE, page * HISTORY_PAGE_SIZE);

        list.innerHTML = '';
        if (pageItems.length === 0) {
            const empty = document.createElement('div');
            empty.className = 'hist-empty';
            empty.innerHTML = '<span class="empty-icon">🗂️</span>该筛选条件下暂无记录';
            list.appendChild(empty);
        } else {
            pageItems.forEach((task) => list.appendChild(buildHistoryCard(task)));
        }

        renderHistoryPagination(filtered.length, page, totalPages);
        refreshHistoryStatuses();
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
                themeToggle.textContent = '☀️';
                themeToggle.title = '切换到浅色模式';
            }
        } else {
            if (themeToggle) {
                themeToggle.textContent = '🌙';
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
    static showStatus(type, message, details = '') {
        const container = document.getElementById('status-container');
        const content = document.getElementById('status-content');

        container.className = `status-container status-${type} fade-in`;
        container.style.display = 'block';

        let icon = '';
        switch (type) {
            case 'success':
                icon = '✅';
                break;
            case 'error':
                icon = '❌';
                break;
            case 'loading':
                icon = '<span class="loading-spinner"></span>';
                break;
            default:
                icon = 'ℹ️';
        }

        content.innerHTML = `
            <div style="font-size: 1.1rem; font-weight: 600; margin-bottom: 0.5rem;">
                ${icon} ${message}
            </div>
            ${details ? `<div style="font-size: 0.95rem; opacity: 0.8;">${details}</div>` : ''}
        `;

        // 滚动到状态区域
        container.scrollIntoView({ behavior: 'smooth' });
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

        const selectedURL = getSelectedURL();
        const token = StorageManager.get(APP_CONFIG.STORAGE_KEYS.BEARER_TOKEN);

        const canSubmit = selectedURL && token && !currentTask;

        btn.disabled = !canSubmit;

        if (currentTask) {
            btnIcon.textContent = '⏳';
            btnText.textContent = '处理中...';
        } else if (!selectedURL) {
            btnIcon.textContent = '📝';
            btnText.textContent = '请输入包含视频链接的内容';
        } else if (!token) {
            btnIcon.textContent = '🔐';
            btnText.textContent = '请在高级设置中填写 API 令牌';
        } else {
            btnIcon.textContent = '🚀';
            btnText.textContent = submitLabelForUrl(selectedURL);
        }
    }

    /**
     * 切换高级设置显示状态
     */
    static toggleAdvancedSettings() {
        const settings = document.getElementById('advanced-settings');
        const icon = document.querySelector('.toggle-icon');

        isAdvancedSettingsExpanded = !isAdvancedSettingsExpanded;

        if (isAdvancedSettingsExpanded) {
            settings.classList.add('expanded');
            icon.classList.add('rotated');
        } else {
            settings.classList.remove('expanded');
            icon.classList.remove('rotated');
        }
    }

    /**
     * 切换令牌可见性
     */
    static toggleTokenVisibility() {
        const input = document.getElementById('bearer-token');
        const btn = document.getElementById('toggle-token-visibility');

        if (input.classList.contains('secret-masked')) {
            input.classList.remove('secret-masked');
            btn.textContent = '🙈';
            btn.setAttribute('aria-label', '隐藏 API 令牌');
        } else {
            input.classList.add('secret-masked');
            btn.textContent = '👁️';
            btn.setAttribute('aria-label', '显示 API 令牌');
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
function handleTextInput(textarea) {
    const text = textarea.value;
    const urlResults = URLExtractor.extractAndRankURLs(text);

    const previewContainer = document.getElementById('url-preview');

    if (urlResults.length === 0) {
        previewContainer.innerHTML = '<div class="no-urls">未检测到URL</div>';
        UIManager.updateSubmitButton();
        return;
    }

    // 显示提取的URL，最高分的作为默认选择
    let html = '<div class="detected-urls">';
    urlResults.forEach((result, index) => {
        const isDefault = index === 0;
        html += `
            <div class="url-option ${isDefault ? 'selected' : ''}" data-url="${result.url}">
                <input type="radio" name="selected-url" value="${result.url}" ${isDefault ? 'checked' : ''}>
                <label>
                    <span class="url-display">${result.display}</span>
                    <span class="url-score">评分: ${result.score}</span>
                </label>
            </div>
        `;
    });
    html += '</div>';

    previewContainer.innerHTML = html;

    // 绑定选择事件
    bindURLSelection();
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
 * 内容识别：从链接判断内容形态（视频深度学习 / 帖子洞察 / 未识别）。
 * 业务入口由当前页面决定，这里不把普通解析流路由到 IP 对标模块。
 */
function classifyContent(url) {
    let host = '';
    let path = '';
    try {
        const u = new URL(url);
        host = u.hostname.replace(/^www\./, '').toLowerCase();
        path = u.pathname;
    } catch (e) {
        return { type: 'unknown', platform: 'unknown', label: '未识别', action: '尝试按视频处理', soon: false };
    }

    // X / Twitter 帖子（已支持）
    if ((host === 'x.com' || host === 'twitter.com' || host === 'mobile.twitter.com')
        && /\/status\/\d+/.test(path)) {
        return { type: 'post', platform: 'twitter', label: '𝕏 帖子', action: '帖子精华提炼 + 可信度判断', soon: false };
    }
    // 微信公众号文章 → 帖子洞察（正文 + 留言）
    if (host === 'mp.weixin.qq.com') {
        return { type: 'post', platform: 'weixin', label: '微信公众号', action: '帖子精华提炼', soon: false };
    }
    // 小红书内容：留在深度学习流，不跳到 IP 对标工作台。
    if (host === 'xiaohongshu.com' || host === 'xhslink.com') {
        return { type: 'video', platform: 'xiaohongshu', label: '小红书内容', action: '视频转录 / 图文深度学习', soon: false };
    }
    // 视频平台（已支持，走转录）
    const videoHosts = ['youtube.com', 'youtu.be', 'bilibili.com', 'b23.tv',
        'douyin.com', 'v.douyin.com', 'iesdouyin.com', 'xiaoyuzhoufm.com',
        'tiktok.com', 'vm.tiktok.com'];
    if (videoHosts.some((h) => host === h || host.endsWith('.' + h))) {
        return { type: 'video', platform: host, label: '视频', action: '语音转录', soon: false };
    }
    // 其它/短链：未知，尝试按视频处理
    return { type: 'unknown', platform: host || 'unknown', label: '未识别', action: '尝试按视频处理', soon: false };
}

/** 提交按钮文案（按识别类型） */
function submitLabelForUrl(url) {
    if (!url) return '开始解析';
    const c = classifyContent(url);
    if (c.soon) return '该平台暂未支持';
    if (c.type === 'post') return '提炼精华';
    if (c.type === 'video') return '开始深度学习';
    return '开始解析';
}

/** 历史状态徽章信息 */
function statusInfo(status, type) {
    const s = (status || '').toString().toLowerCase();
    if (type === 'post') return { cls: 'done', text: '已完成' };
    if (['done', 'completed', 'success', 'finished'].includes(s)) return { cls: 'done', text: '已完成' };
    if (['failed', 'error', 'fail'].includes(s)) return { cls: 'failed', text: '失败' };
    if (['processing', 'running', 'transcribing', 'in_progress'].includes(s)) return { cls: 'running', text: '处理中' };
    if (['queued', 'pending', 'submitted'].includes(s)) return { cls: 'running', text: '处理中' };
    return { cls: 'queued', text: '已提交' };
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
    try { return new Date(ts).toLocaleDateString('zh-CN'); } catch (e) { return ''; }
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

/** 每页历史条数 */
const HISTORY_PAGE_SIZE = 8;

/** 日期范围判断（today / 7d / 30d / 90d / all） */
function inDateRange(ts, rangeKey) {
    if (!rangeKey || rangeKey === 'all' || !ts) return true;
    const now = Date.now();
    const DAY = 86400000;
    if (rangeKey === 'today') {
        const d = new Date();
        d.setHours(0, 0, 0, 0);
        return ts >= d.getTime();
    }
    if (rangeKey === '7d') return ts >= now - 7 * DAY;
    if (rangeKey === '30d') return ts >= now - 30 * DAY;
    if (rangeKey === '90d') return ts >= now - 90 * DAY;
    return true;
}

/** 构建单条历史卡片 DOM */
// 历史条目类型：优先存储的 type；其次有 view_token 视作视频转录（有 /view 结果）；否则按 URL。
function histTypeOf(task) {
    if (task.type) return task.type;
    if (task.view_token) return 'video';
    const cls = classifyContent(task.url).type;
    if (cls === 'post') return 'post';
    return 'video';
}

function buildHistoryCard(task) {
    const cls = classifyContent(task.url);
    const histType = histTypeOf(task);
    // 图标按来源平台映射（展示来源，避免帖子一律显示 𝕏）
    const PLATFORM_ICONS = {
        twitter: '𝕏', xiaohongshu: '📕', weixin: '📰',
        bilibili: '📺', douyin: '🎵', youtube: '▶️', xiaoyuzhou: '🎙️',
    };
    const icon = histType === 'file'
        ? '📁'
        : (PLATFORM_ICONS[cls.platform] || (histType === 'post' ? '📝' : '🎬'));
    const typeLabel = histType === 'post' ? '帖子' : (histType === 'file' ? '文件' : '视频');
    const st = statusInfo(task.status, histType);
    const timeStr = formatRelativeTime(task.timestamp);

    let host = '链接';
    try { host = new URL(task.url).hostname.replace(/^www\./, ''); } catch (e) { /* keep fallback */ }

    // 动作按状态：失败→重试（不查看失败页）；处理中→禁用；成功→查看真正的结果
    let viewBtn;
    if (st.cls === 'failed') {
        const retryHref = (cls.type === 'post')
            ? ('/post?url=' + encodeURIComponent(task.url))
            : '/add_task_by_web';
        viewBtn = `<a class="hist-btn" href="${retryHref}">🔁 重试</a>`;
    } else if (st.cls === 'running' || st.cls === 'queued') {
        viewBtn = `<a class="hist-btn" aria-disabled="true">⏳ 处理中</a>`;
    } else if (task.result_id) {
        // 帖子洞察结果（已持久化到本地）→ 查看存储结果
        viewBtn = `<a class="hist-btn" href="/post?view=${encodeURIComponent(task.result_id)}">👁️ 查看</a>`;
    } else if (task.view_token) {
        viewBtn = `<a class="hist-btn" href="/view/${task.view_token}" target="_blank">👁️ 查看</a>`;
    } else if (cls.type === 'post') {
        viewBtn = `<a class="hist-btn" href="/post?url=${encodeURIComponent(task.url)}">🔁 重新分析</a>`;
    } else {
        viewBtn = `<a class="hist-btn" href="/add_task_by_web">🔁 重新提交</a>`;
    }

    const tags = [];
    if (task.useSpeakerRecognition) tags.push('<span class="hist-feature-tag">说话人识别</span>');
    if (task.includeComments) tags.push('<span class="hist-feature-tag">评论洞察</span>');

    const card = document.createElement('div');
    card.className = 'hist-card fade-in';
    card.setAttribute('data-type', histType);
    if (task.id) card.setAttribute('data-task-id', task.id);
    card.innerHTML = `
                <div class="hist-icon">${icon}</div>
                <div class="hist-body">
                    <div class="hist-top-row">
                        <span class="type-badge t-${histType}">${typeLabel}</span>
                        <span class="status-badge s-${st.cls}">${st.text}</span>
                        <span class="hist-title" title="${escapeAttr(task.title || '')}">${escapeHtml(task.title || '未命名')}</span>
                    </div>
                    <div class="hist-meta">
                        <span class="hist-source">🔗 <a href="${escapeAttr(task.url)}" target="_blank" rel="noopener">${escapeHtml(host)}</a></span>
                        <span class="hist-time">${timeStr}</span>
                        ${tags.join('')}
                    </div>
                </div>
                <div class="hist-actions">
                    ${viewBtn}
                    <button class="hist-btn" onclick="copyToClipboard('${jsAttr(task.url)}')">📋 复制</button>
                    <button class="hist-btn danger" onclick="TaskHistoryManager.deleteTask('${jsAttr(task.id)}')">🗑️ 删除</button>
                </div>
            `;
    return card;
}

/** 渲染分页控件（只有超过一页时显示） */
function renderHistoryPagination(total, page, totalPages) {
    const el = document.getElementById('history-pagination');
    if (!el) return;
    if (total <= HISTORY_PAGE_SIZE) { el.innerHTML = ''; return; }
    el.innerHTML = `
        <button type="button" class="page-btn" data-page-action="prev" ${page <= 1 ? 'disabled' : ''}>‹ 上一页</button>
        <span class="page-info">第 ${page} / ${totalPages} 页 · 共 ${total} 条</span>
        <button type="button" class="page-btn" data-page-action="next" ${page >= totalPages ? 'disabled' : ''}>下一页 ›</button>
    `;
}

/** 历史视频任务的状态最佳努力刷新（复用既有 getTaskStatus，容错字段名） */
function refreshHistoryStatuses() {
    let token = null;
    try { token = StorageManager.get(APP_CONFIG.STORAGE_KEYS.BEARER_TOKEN); } catch (e) { return; }
    if (!token) return;
    const history = TaskHistoryManager.getHistory();
    document.querySelectorAll('.hist-card[data-task-id][data-type="video"]').forEach((card) => {
        const taskId = card.getAttribute('data-task-id');
        if (!taskId) return;
        APIManager.getTaskStatus(taskId).then((resp) => {
            const raw = (resp && (resp.data || resp)) || {};
            const s = raw.status || raw.task_status || raw.state;
            if (!s) return;
            const norm = String(s).toLowerCase();
            const entry = history.find((t) => t && t.id === taskId);
            if (!entry) return;
            // 回写真实状态（下次渲染直接正确，不再从 submitted 起跳）
            if (entry.status !== norm) {
                entry.status = norm;
                StorageManager.set(APP_CONFIG.STORAGE_KEYS.TASK_HISTORY, history);
            }
            // 用最新状态重建整张卡片：徽章与动作按钮（查看/重试/处理中）保持一致
            if (card.parentNode) {
                card.replaceWith(buildHistoryCard(entry));
            }
        }).catch(() => { /* best-effort, ignore */ });
    });
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
    if (videoOpts) videoOpts.hidden = !(c.type === 'video' || c.type === 'unknown');
    if (typeof UIManager !== 'undefined') UIManager.updateSubmitButton();
}

/** 工作台新增交互的初始化 */
function initWorkbenchUI() {
    // 输入 Tab 切换
    document.querySelectorAll('.input-tab').forEach((tab) => {
        tab.addEventListener('click', () => {
            document.querySelectorAll('.input-tab').forEach((t) => {
                t.classList.remove('active');
                t.setAttribute('aria-selected', 'false');
            });
            document.querySelectorAll('.input-panel').forEach((p) => {
                p.classList.remove('active');
                p.hidden = true;
            });
            tab.classList.add('active');
            tab.setAttribute('aria-selected', 'true');
            const panel = document.getElementById(tab.getAttribute('data-panel'));
            if (panel) { panel.classList.add('active'); panel.hidden = false; }
        });
    });
    if (window.location.hash === '#local-video-study') {
        const fileTab = document.getElementById('tab-file');
        if (fileTab) fileTab.click();
    }

    // 本地文件：上传 → 转录 → 跳结果页
    const dz = document.getElementById('file-dropzone');
    const fileInput = document.getElementById('file-input');
    if (dz && fileInput) {
        const hint = document.getElementById('dropzone-hint');
        const mediaExtensions = new Set(['mp3', 'm4a', 'wav', 'aac', 'flac', 'mp4', 'mov', 'mkv', 'webm', 'avi', 'm4v']);

        const isMediaFile = (fileObj) => {
            const type = (fileObj.type || '').toLowerCase();
            if (type.startsWith('audio/') || type.startsWith('video/')) return true;
            const ext = (fileObj.name || '').split('.').pop().toLowerCase();
            return mediaExtensions.has(ext);
        };

        const readUploadResponse = async (response) => {
            const contentType = (response.headers.get('content-type') || '').toLowerCase();
            if (contentType.includes('application/json')) {
                return {
                    status: response.status,
                    ok: response.ok,
                    d: await response.json().catch(() => ({})),
                    text: '',
                };
            }
            return {
                status: response.status,
                ok: response.ok,
                d: {},
                text: (await response.text().catch(() => '')).trim(),
            };
        };

        const uploadLocalFile = (fileObj) => {
            if (!fileObj) return;
            const token = StorageManager.get(APP_CONFIG.STORAGE_KEYS.BEARER_TOKEN);
            if (!token) {
                UIManager.showStatus('error', '请先设置 API 令牌', '请在高级设置中填写你的 API 访问令牌（Bearer Token）');
                if (!isAdvancedSettingsExpanded) UIManager.toggleAdvancedSettings();
                setTimeout(() => { const t = document.getElementById('bearer-token'); if (t) t.focus(); }, 100);
                setTimeout(UIManager.hideStatus, 5000);
                return;
            }
            const mediaFile = isMediaFile(fileObj);
            if (hint) hint.textContent = mediaFile ? '上传中… 将进入本地学习模式' : '上传中… ' + fileObj.name;
            dz.classList.add('uploading');
            const fd = new FormData();
            fd.append('file', fileObj);
            fd.append('use_speaker_recognition', 'false');
            fetch(mediaFile ? '/api/study/upload' : '/api/upload-transcribe', {
                method: 'POST',
                headers: { 'Authorization': 'Bearer ' + token },
                body: fd,
            }).then(readUploadResponse)
              .then(({ status, ok, d, text }) => {
                  dz.classList.remove('uploading');
                  if (status === 401 || status === 403) {
                      if (hint) hint.textContent = '令牌无效，请在高级设置重新填写';
                      return;
                  }
                  if (!ok) {
                      if (hint) {
                          hint.textContent = (d && (d.detail || d.message)) || text || ('上传失败（HTTP ' + status + '）');
                      }
                      return;
                  }
                  if (d && d.code === 202 && d.data && d.data.view_token) {
                      if (hint) hint.textContent = mediaFile ? '上传成功，正在打开学习模式…' : '上传成功，正在转录…';
                      window.location.href = (mediaFile ? '/study/' : '/view/') + d.data.view_token;
                  } else if (hint) {
                      hint.textContent = (d && (d.detail || d.message)) || '上传失败，请重试';
                  }
              }).catch((error) => {
                  dz.classList.remove('uploading');
                  if (hint) hint.textContent = (error && error.message) || '网络错误，请重试';
              });
        };

        dz.addEventListener('click', () => fileInput.click());
        dz.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fileInput.click(); }
        });
        fileInput.addEventListener('change', () => {
            if (fileInput.files && fileInput.files[0]) uploadLocalFile(fileInput.files[0]);
        });
        ['dragover', 'dragenter'].forEach((ev) => dz.addEventListener(ev, (e) => {
            e.preventDefault(); dz.classList.add('dragover');
        }));
        dz.addEventListener('dragleave', (e) => { e.preventDefault(); dz.classList.remove('dragover'); });
        dz.addEventListener('drop', (e) => {
            e.preventDefault();
            dz.classList.remove('dragover');
            const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
            if (f) uploadLocalFile(f);
        });
    }

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

    // 历史：分页（事件委托，按钮会随渲染重建）
    const pager = document.getElementById('history-pagination');
    if (pager) {
        pager.addEventListener('click', (e) => {
            const btn = e.target.closest('[data-page-action]');
            if (!btn || btn.disabled) return;
            const cur = window.__histPage || 1;
            window.__histPage = btn.getAttribute('data-page-action') === 'next' ? cur + 1 : cur - 1;
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

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initWorkbenchUI);
} else {
    initWorkbenchUI();
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
    const useSpeakerRecognition = document.getElementById('speaker-recognition').checked;
    const preserveSourceFile = document.getElementById('preserve-source-file').checked;
    const includeComments = document.getElementById('include-comments').checked;
    const commentLimit = Number.parseInt(document.getElementById('comment-limit').value, 10) || 100;
    const wechatWebhook = document.getElementById('wechat-webhook').value.trim();
    const originalText = document.getElementById('share-content').value.trim();

    if (!selectedURL) {
        UIManager.showStatus('error', '请先选择一个内容链接', '请在上方文本框中输入包含内容链接的文本，系统会自动提取并显示可选链接');
        setTimeout(UIManager.hideStatus, 5000);
        return;
    }

    // 按当前深度学习入口路由：已支持的帖子（X / 公众号）进入帖子洞察；
    // 视频和未识别链接留在转录 / 深度学习流程。
    const detected = classifyContent(selectedURL);
    if (detected.type === 'post' && !detected.soon) {
        window.location.href = '/post?url=' + encodeURIComponent(selectedURL);
        return;
    }
    if (detected.soon) {
        UIManager.showStatus('error', detected.label + ' 暂未支持',
            '该平台的解析功能即将上线，敬请期待');
        setTimeout(UIManager.hideStatus, 4000);
        return;
    }

    const token = StorageManager.get(APP_CONFIG.STORAGE_KEYS.BEARER_TOKEN);
    if (!token) {
        UIManager.showStatus('error', '请先设置 API 令牌', '请在高级设置中填写你的 API 访问令牌（Bearer Token）');
        // 自动展开高级设置
        if (!isAdvancedSettingsExpanded) {
            UIManager.toggleAdvancedSettings();
        }
        // 聚焦到 token 输入框
        setTimeout(() => {
            const tokenInput = document.getElementById('bearer-token');
            if (tokenInput) {
                tokenInput.focus();
            }
        }, 100);
        setTimeout(UIManager.hideStatus, 5000);
        return;
    }

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
            preserveSourceFile
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

            // 根据是否重复显示不同的提示
            let statusMessage = '任务提交成功！';
            let statusDetails = `任务ID: ${response.data.task_id}<br>转录将在后台进行，完成后会通过配置的企业微信通知您<br>`;

            if (historyResult.isDuplicate) {
                statusMessage = '任务提交成功！(检测到重复URL)';
                statusDetails += `<span style="color: #f59e0b;">⚠️ 相同链接的旧任务记录已被更新</span><br>`;
            }

            statusDetails += `<a href="/view/${response.data.view_token}" target="_blank" style="color: #667eea; text-decoration: underline;">点击查看任务进度</a>`;

            UIManager.showStatus('success', statusMessage, statusDetails);

            // 清空表单
            document.getElementById('share-content').value = '';
            document.getElementById('url-preview').innerHTML = '<div class="no-urls">请输入包含视频链接的内容</div>';

            // 3秒后跳转到查看页面
            setTimeout(() => {
                window.open(`/view/${response.data.view_token}`, '_blank');
            }, 3000);

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
function initializePage() {
    console.log('初始化视频转录Web应用...');

    // 加载保存的设置
    const savedToken = StorageManager.get(APP_CONFIG.STORAGE_KEYS.BEARER_TOKEN);
    const savedWebhook = StorageManager.get(APP_CONFIG.STORAGE_KEYS.WECHAT_WEBHOOK);
    const savedSpeakerRecognition = StorageManager.get(APP_CONFIG.STORAGE_KEYS.SPEAKER_RECOGNITION);
    const savedIncludeComments = StorageManager.get(APP_CONFIG.STORAGE_KEYS.INCLUDE_COMMENTS);
    const savedCommentLimit = StorageManager.get(APP_CONFIG.STORAGE_KEYS.COMMENT_LIMIT);

    if (savedToken) {
        document.getElementById('bearer-token').value = savedToken;
    }

    // 加载 webhook 地址
    if (savedWebhook) {
        document.getElementById('wechat-webhook').value = savedWebhook;
    }

    if (savedSpeakerRecognition !== null) {
        document.getElementById('speaker-recognition').checked = savedSpeakerRecognition;
    }

    if (savedIncludeComments !== null) {
        document.getElementById('include-comments').checked = savedIncludeComments;
    }

    if (savedCommentLimit !== null) {
        document.getElementById('comment-limit').value = String(savedCommentLimit);
    }
    updateCommentLimitControl();

    // 绑定事件监听器
    const textarea = document.getElementById('share-content');
    textarea.value = ''; // 确保初始为空
    textarea.addEventListener('input', () => handleTextInput(textarea));

    // 确保URL预览区域初始状态正确
    const previewContainer = document.getElementById('url-preview');
    previewContainer.innerHTML = '<div class="no-urls">请输入包含视频链接的内容</div>';

    // 如果没有保存的 token，自动展开高级设置
    if (!savedToken) {
        UIManager.toggleAdvancedSettings();
    }

    const form = document.getElementById('transcribe-form');
    form.addEventListener('submit', submitTranscription);

    const advancedToggle = document.getElementById('advanced-toggle');
    advancedToggle.addEventListener('click', UIManager.toggleAdvancedSettings);

    const tokenToggle = document.getElementById('toggle-token-visibility');
    tokenToggle.addEventListener('click', UIManager.toggleTokenVisibility);

    const clearWebhookBtn = document.getElementById('clear-webhook');
    clearWebhookBtn.addEventListener('click', UIManager.clearWebhook);

    // 监听设置变化
    document.getElementById('bearer-token').addEventListener('input', (e) => {
        StorageManager.set(APP_CONFIG.STORAGE_KEYS.BEARER_TOKEN, e.target.value);
        UIManager.updateSubmitButton();
    });

    document.getElementById('wechat-webhook').addEventListener('input', (e) => {
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

    document.getElementById('speaker-recognition').addEventListener('change', (e) => {
        StorageManager.set(APP_CONFIG.STORAGE_KEYS.SPEAKER_RECOGNITION, e.target.checked);
    });

    document.getElementById('include-comments').addEventListener('change', (e) => {
        StorageManager.set(APP_CONFIG.STORAGE_KEYS.INCLUDE_COMMENTS, e.target.checked);
        updateCommentLimitControl();
    });

    document.getElementById('comment-limit').addEventListener('change', (e) => {
        StorageManager.set(
            APP_CONFIG.STORAGE_KEYS.COMMENT_LIMIT,
            Number.parseInt(e.target.value, 10) || 100
        );
    });

    // 渲染任务历史
    TaskHistoryManager.renderHistory();

    // 初始化主题系统
    ThemeManager.initialize();

    // 初始状态更新
    UIManager.updateSubmitButton();

    console.log('视频转录Web应用初始化完成');
}

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', initializePage);

// 导出全局函数供HTML使用
window.copyToClipboard = copyToClipboard;
