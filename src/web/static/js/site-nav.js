/* ============================================================
   site-nav.js — 全站唯一导航（单一来源）
   用法：在页面放 <div id="site-nav"></div> 并引入本脚本。
   改这里的品牌或链接，所有页面同步生效。
   ============================================================ */
(function () {
    var LINKS = [
        { href: '/', label: '首页' },
        { href: '/add_task_by_web', label: '单篇深度学习' },
        { href: '/collections', label: '系列深度学习' },
        { href: '/static/focus-studio.html', label: '心流写作' },
        { href: '/post', label: '帖子洞察' },
        { href: '/flywheel', label: 'IP 对标' },
        { href: '/static/history.html', label: '历史' },
        { href: '/settings', label: '设置' }
    ];

    function isActive(href) {
        var path = location.pathname;
        if (href === '/') return path === '/';
        return path.indexOf(href) === 0;
    }

    function navHTML() {
        var links = LINKS.map(function (l) {
            return '<a href="' + l.href + '"' + (isActive(l.href) ? ' class="active"' : '') + '>' + l.label + '</a>';
        }).join('');
        return '<nav class="site-nav">' +
            '<a class="nav-brand" href="/"><img class="nav-logo" src="/static/icon/logo.svg" alt=""> 内容解析工作台</a>' +
            '<div class="nav-links">' + links + '</div>' +
            '</nav>';
    }

    function render() {
        var el = document.getElementById('site-nav');
        if (el) el.outerHTML = navHTML();
    }

    if (document.getElementById('site-nav')) render();
    else document.addEventListener('DOMContentLoaded', render);
})();
