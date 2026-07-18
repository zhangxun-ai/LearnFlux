(function () {
    'use strict';

    const STORAGE_KEY = 'vta_app_shell_sidebar';
    const MOBILE_QUERY = '(max-width: 900px)';

    const body = document.body;
    if (!body || !body.classList.contains('app-shell')) return;

    const sidebar = document.querySelector('.sidebar');
    const topbarTitle = document.querySelector('.topbar-title');
    const brand = document.querySelector('.sidebar-brand');
    if (!sidebar || !topbarTitle || !brand) return;

    const media = window.matchMedia(MOBILE_QUERY);
    let lastFocus = null;

    if (!sidebar.querySelector('a[href="/visual-learning"]')) {
        const collectionsLink = sidebar.querySelector('a[href="/collections"]');
        if (collectionsLink) {
            const link = document.createElement('a');
            const icon = document.createElement('span');
            const label = document.createElement('span');
            link.className = 'nav-item';
            link.href = '/visual-learning';
            icon.className = 'nav-icon';
            icon.setAttribute('aria-hidden', 'true');
            icon.textContent = '▦';
            label.textContent = '图解生成';
            link.append(icon, label);
            if (window.location.pathname.startsWith('/visual-learning')) {
                link.classList.add('is-active');
            }
            collectionsLink.insertAdjacentElement('afterend', link);
        }
    }

    const studyPlayerHref = '/study';
    if (!sidebar.querySelector('a[href="/study"]')) {
        const insertAfter = sidebar.querySelector('a[href="/visual-learning"]')
            || sidebar.querySelector('a[href="/collections"]');
        if (insertAfter) {
            const link = document.createElement('a');
            const icon = document.createElement('span');
            const label = document.createElement('span');
            link.className = 'nav-item';
            link.href = studyPlayerHref;
            icon.className = 'nav-icon';
            icon.setAttribute('aria-hidden', 'true');
            icon.textContent = '▶';
            label.textContent = '边播边学';
            link.append(icon, label);
            if (window.location.pathname === '/study' || window.location.pathname.startsWith('/study/')) {
                link.classList.add('is-active');
            }
            insertAfter.insertAdjacentElement('afterend', link);
        }
    }

    if (!sidebar.id) {
        sidebar.id = 'app-sidebar';
    }

    function icon(paths) {
        return `<svg viewBox="0 0 24 24" aria-hidden="true">${paths}</svg>`;
    }

    function createButton(className, label, paths) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = `shell-icon-button ${className}`;
        button.setAttribute('aria-label', label);
        button.setAttribute('aria-controls', sidebar.id);
        button.innerHTML = icon(paths);
        return button;
    }

    const collapseButton = createButton(
        'shell-collapse-toggle',
        '收起侧边栏',
        '<path d="M15 18 9 12l6-6"/><path d="M20 12H9"/><path d="M4 5v14"/>'
    );
    const mobileButton = createButton(
        'shell-mobile-toggle',
        '打开导航',
        '<path d="M4 6h16"/><path d="M4 12h16"/><path d="M4 18h16"/>'
    );
    const overlay = document.createElement('button');
    overlay.type = 'button';
    overlay.className = 'shell-overlay';
    overlay.setAttribute('aria-label', '关闭导航');

    const themeButton = createButton(
        'shell-theme-toggle',
        '切换外观',
        ''
    );
    function updateThemeIcon() {
        const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
        themeButton.innerHTML = icon(isDark 
            ? '<circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/>'
            : '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>');
    }
    updateThemeIcon();
    themeButton.addEventListener('click', () => {
        const newTheme = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', newTheme);
        localStorage.setItem('vta_theme_preference', JSON.stringify(newTheme));
        updateThemeIcon();
    });

    brand.appendChild(themeButton);
    brand.appendChild(collapseButton);
    topbarTitle.insertBefore(mobileButton, topbarTitle.firstChild);
    body.appendChild(overlay);

    function navLabel(link) {
        const clone = link.cloneNode(true);
        clone.querySelectorAll('.nav-icon').forEach((node) => node.remove());
        return clone.textContent.trim();
    }

    document.querySelectorAll('.sidebar .nav-item').forEach((link) => {
        const label = navLabel(link);
        if (!label) return;
        link.dataset.label = label;
        if (!link.getAttribute('aria-label')) {
            link.setAttribute('aria-label', label);
        }
        link.title = label;
    });

    function preferredDesktopState() {
        const stored = localStorage.getItem(STORAGE_KEY);
        if (stored === 'expanded' || stored === 'collapsed') return stored;
        return body.classList.contains('focus-body') ? 'collapsed' : 'expanded';
    }

    function closeDrawer() {
        body.classList.remove('sidebar-drawer-open');
        mobileButton.setAttribute('aria-expanded', 'false');
        if (lastFocus && typeof lastFocus.focus === 'function') {
            lastFocus.focus({ preventScroll: true });
        }
    }

    function openDrawer() {
        lastFocus = document.activeElement;
        body.classList.add('sidebar-drawer-open');
        mobileButton.setAttribute('aria-expanded', 'true');
        const active = sidebar.querySelector('.nav-item.is-active') || sidebar.querySelector('a, button');
        if (active && typeof active.focus === 'function') {
            active.focus({ preventScroll: true });
        }
    }

    function applyDesktopState(state) {
        body.classList.toggle('sidebar-collapsed', state === 'collapsed');
        collapseButton.setAttribute('aria-expanded', state !== 'collapsed' ? 'true' : 'false');
        collapseButton.setAttribute('aria-label', state === 'collapsed' ? '展开侧边栏' : '收起侧边栏');
    }

    function syncMode() {
        if (media.matches) {
            body.classList.remove('sidebar-collapsed');
            closeDrawer();
            mobileButton.setAttribute('aria-expanded', 'false');
            return;
        }
        closeDrawer();
        applyDesktopState(preferredDesktopState());
    }

    collapseButton.addEventListener('click', () => {
        const collapsed = !body.classList.contains('sidebar-collapsed');
        const state = collapsed ? 'collapsed' : 'expanded';
        localStorage.setItem(STORAGE_KEY, state);
        applyDesktopState(state);
    });

    mobileButton.addEventListener('click', () => {
        if (body.classList.contains('sidebar-drawer-open')) {
            closeDrawer();
        } else {
            openDrawer();
        }
    });

    overlay.addEventListener('click', closeDrawer);

    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && body.classList.contains('sidebar-drawer-open')) {
            closeDrawer();
        }
    });

    sidebar.addEventListener('click', (event) => {
        if (media.matches && event.target.closest('a')) {
            closeDrawer();
        }
    });

    if (typeof media.addEventListener === 'function') {
        media.addEventListener('change', syncMode);
    } else {
        media.addListener(syncMode);
    }

    syncMode();
})();
