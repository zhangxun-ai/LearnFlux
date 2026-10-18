(() => {
    const icons = {
        douyin: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 3v11.2a4 4 0 1 1-3.1-3.9" fill="none" stroke="#25F4EE" stroke-width="4" stroke-linecap="round"/><path d="M14 3v11.2a4 4 0 1 1-3.1-3.9" fill="none" stroke="#FE2C55" stroke-width="2.4" stroke-linecap="round" transform="translate(1 0)"/><path d="M14 3v11.2a4 4 0 1 1-3.1-3.9" fill="none" stroke="#171717" stroke-width="2.4" stroke-linecap="round"/><path d="M14 3c.4 2.5 2.1 4.1 4.5 4.6" fill="none" stroke="#171717" stroke-width="2.4" stroke-linecap="round"/></svg>',
        xiaohongshu: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="1" y="1" width="22" height="22" rx="5" fill="#F04452"/><text x="12" y="10.5" text-anchor="middle" fill="#fff" font-size="5.4" font-weight="700" font-family="Arial,sans-serif">小红</text><text x="12" y="17" text-anchor="middle" fill="#fff" font-size="5.4" font-weight="700" font-family="Arial,sans-serif">书</text></svg>',
        bilibili: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m8 4 2.2 2M16 4l-2.2 2" fill="none" stroke="#00A1D6" stroke-width="1.8" stroke-linecap="round"/><rect x="3" y="7" width="18" height="14" rx="3" fill="#00A1D6"/><path d="M8 12v3m8-3v3" stroke="#fff" stroke-width="2" stroke-linecap="round"/></svg>',
        youtube: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="2" y="5" width="20" height="14" rx="4" fill="#F00"/><path d="m10 9 6 3-6 3z" fill="#fff"/></svg>',
        x: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 4h4.2l9.8 16h-4.2zM19 4l-6.1 7.2M5 20l6.1-7.2" fill="none" stroke="#111" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
        wechat: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4c-4.4 0-8 2.8-8 6.2 0 1.8 1.1 3.4 2.8 4.5l-.7 2.6 3.2-1.4c.8.2 1.7.4 2.7.4 4.4 0 8-2.8 8-6.2S16.4 4 12 4Z" fill="#36B26D"/><circle cx="9" cy="10" r=".9" fill="#fff"/><circle cx="15" cy="10" r=".9" fill="#fff"/><path d="M5.8 7.2C6.8 5.3 9.1 4 12 4c.5 0 1 0 1.5.1C12.2 2.8 10.2 2 8 2 4.7 2 2 3.8 2 6.1c0 1 .5 2 1.4 2.7l-.3 1.7 1.7-.9" fill="#62C887"/></svg>',
        xiaoyuzhou: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="11" fill="#F1A35B"/><path d="M6 13c1.3-3.3 2.4-3.3 3.7 0s2.4 3.3 3.7 0 2.4-3.3 3.7 0" fill="none" stroke="#fff" stroke-width="1.7" stroke-linecap="round"/></svg>',
        local: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 3.5h9l5 5V20a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1zM14 3.5V9h5" fill="none" stroke="#5B7565" stroke-width="1.7" stroke-linejoin="round"/><path d="M8 13h8M8 17h8" stroke="#5B7565" stroke-width="1.5" stroke-linecap="round"/></svg>',
        other: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 13a5 5 0 0 0 7.1 0l3-3A5 5 0 0 0 13 2.9l-1.7 1.7M14 11a5 5 0 0 0-7.1 0l-3 3a5 5 0 0 0 7.1 7.1l1.7-1.7" fill="none" stroke="#60766A" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>'
    };

    const byId = {
        douyin: ['douyin', '抖音'],
        tiktok: ['douyin', 'TikTok'],
        xiaohongshu: ['xiaohongshu', '小红书'],
        bilibili: ['bilibili', '哔哩哔哩'],
        youtube: ['youtube', 'YouTube'],
        twitter: ['x', 'X'],
        x: ['x', 'X'],
        weixin: ['wechat', '公众号'],
        wechat: ['wechat', '公众号'],
        wechat_channels: ['wechat', '视频号'],
        xiaoyuzhou: ['xiaoyuzhou', '小宇宙'],
        local: ['local', '本地文件'],
        file: ['local', '本地文件']
    };

    function platformFor(card) {
        const raw = (card.querySelector('.hist-platform')?.textContent || '').trim().toLowerCase();
        const sourceHref = card.querySelector('.hist-source a[href]')?.href || '';
        let host = '';
        try { host = new URL(sourceHref, window.location.href).hostname.toLowerCase().replace(/^www\./, ''); } catch (_) {}

        if (host.includes('xiaohongshu.com') || host.startsWith('xhslink.')) return ['xiaohongshu', '小红书'];
        if (host.includes('douyin.com') || host.includes('iesdouyin.com')) return ['douyin', '抖音'];
        if (host.includes('bilibili.com') || host === 'b23.tv') return ['bilibili', '哔哩哔哩'];
        if (host.includes('youtube.com') || host === 'youtu.be') return ['youtube', 'YouTube'];
        if (host === 'x.com' || host.endsWith('.x.com') || host.includes('twitter.com')) return ['x', 'X'];
        if (raw.includes('wechat_channels') || raw.includes('视频号')) return ['wechat', '视频号'];
        if (host.includes('weixin.qq.com')) return ['wechat', '公众号'];
        if (host.includes('xiaoyuzhoufm.com')) return ['xiaoyuzhou', '小宇宙'];
        if (byId[raw]) return byId[raw];
        if (raw.includes('本地文件') || raw === 'local') return ['local', '本地文件'];
        if (raw && !raw.includes('_')) return ['other', raw];
        return ['other', '其他来源'];
    }

    function decorateCard(card) {
        const platformEl = card.querySelector('.hist-platform');
        const meta = card.querySelector('.hist-meta');
        const status = card.querySelector('.status-badge');
        if (meta && status && !meta.contains(status)) meta.append(status);
        if (!platformEl || platformEl.querySelector('.home-platform-badge')) return;
        const [key, label] = platformFor(card);
        const badge = document.createElement('span');
        badge.className = 'home-platform-badge';
        badge.setAttribute('aria-label', `来源平台：${label}`);

        const mark = document.createElement('span');
        mark.className = `home-platform-mark home-platform-mark-${key}`;
        mark.setAttribute('aria-hidden', 'true');
        mark.innerHTML = icons[key] || icons.other;

        const name = document.createElement('span');
        name.className = 'home-platform-name';
        name.textContent = label;
        badge.append(mark, name);
        platformEl.replaceChildren(badge);
    }

    function decorateAll() {
        document.querySelectorAll('#history-list .hist-card').forEach(decorateCard);
    }

    const historyList = document.getElementById('history-list');
    if (!historyList) return;
    decorateAll();
    new MutationObserver(decorateAll).observe(historyList, { childList: true, subtree: true });
})();
