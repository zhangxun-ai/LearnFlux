(function () {
    'use strict';

    var INBOX_KEY = 'vta_focus_studio_inbox';
    var FOCUS_URL = '/static/focus-studio.html?inbox=1';

    var TYPE_LABELS = {
        calibrated: '校对文本',
        summary: '内容总结',
        comment_insight: '高赞评论洞察',
        transcript: '原始转录'
    };

    function setButtonState(button, state, text) {
        var action = button.querySelector('.focus-handoff-action');
        if (!action) return;
        button.classList.toggle('is-loading', state === 'loading');
        button.classList.toggle('is-done', state === 'done');
        button.classList.toggle('is-error', state === 'error');
        action.textContent = text;
    }

    function stripFrontMatter(text) {
        if (!text || text.slice(0, 4) !== '---\n') return text || '';
        var end = text.indexOf('\n---\n', 4);
        if (end === -1) return text;
        return text.slice(end + 5).replace(/^\s+/, '');
    }

    function composeText(title, label, content) {
        var parts = [];
        var cleanTitle = (title || '').trim();
        var cleanLabel = (label || '').trim();
        var cleanContent = stripFrontMatter(content).trim();

        if (cleanTitle) parts.push('# ' + cleanTitle);
        if (cleanLabel) parts.push('> 来源：' + cleanLabel);
        if (cleanContent) parts.push(cleanContent);

        return parts.join('\n\n') + '\n';
    }

    function openPlaceholder() {
        var target = window.open('', '_blank');
        if (!target) return null;
        try {
            target.document.write(
                '<!doctype html><meta charset="utf-8"><title>Focus Studio</title>' +
                '<body style="margin:0;background:#070b0b;color:#cfd6d2;font:16px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;display:grid;place-items:center;height:100vh">' +
                '<p>正在进入心流写作...</p></body>'
            );
            target.document.close();
        } catch (error) {
            // Ignore cross-window write errors. The tab can still be redirected.
        }
        return target;
    }

    function redirectToFocus(target) {
        if (target && !target.closed) {
            target.location.href = FOCUS_URL;
            try { target.opener = null; } catch (error) {}
        } else {
            window.open(FOCUS_URL, '_blank', 'noopener');
        }
    }

    function readPageSection(type) {
        var safeType = String(type || '').replace(/"/g, '');
        var section = document.querySelector('[data-focus-section="' + safeType + '"]');
        return section ? section.innerText : '';
    }

    async function sendToFocus(button) {
        var viewToken = button.getAttribute('data-view-token');
        var type = button.getAttribute('data-focus-type');
        var title = button.getAttribute('data-focus-title') || document.title;
        var label = button.getAttribute('data-focus-label') || TYPE_LABELS[type] || type;
        var target = openPlaceholder();

        if (!viewToken || !type) {
            setButtonState(button, 'error', '失败');
            redirectToFocus(target);
            return;
        }

        setButtonState(button, 'loading', '准备中');

        try {
            var rawUrl = '/view/' + encodeURIComponent(viewToken) + '?raw=' + encodeURIComponent(type);
            var response = await fetch(rawUrl, { credentials: 'same-origin' });
            var text = response.ok ? await response.text() : readPageSection(type);
            if (!text.trim()) throw new Error('Focus handoff content unavailable: ' + response.status);

            var payload = {
                text: composeText(title, label, text),
                sourceType: type,
                sourceLabel: label,
                sourceTitle: title,
                createdAt: new Date().toISOString()
            };
            localStorage.setItem(INBOX_KEY, JSON.stringify(payload));

            setButtonState(button, 'done', '已发送');
            redirectToFocus(target);
            setTimeout(function () {
                setButtonState(button, '', '送入');
            }, 1600);
        } catch (error) {
            console.error('Focus handoff failed:', error);
            setButtonState(button, 'error', '失败');
            if (target && !target.closed) target.close();
            setTimeout(function () {
                setButtonState(button, '', '送入');
            }, 1800);
        }
    }

    document.addEventListener('DOMContentLoaded', function () {
        document.querySelectorAll('[data-focus-handoff]').forEach(function (button) {
            button.addEventListener('click', function () {
                sendToFocus(button);
            });
        });
    });
})();
