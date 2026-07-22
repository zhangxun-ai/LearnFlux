(function () {
    'use strict';

    const STORAGE_KEY = 'vta_app_shell_sidebar';
    const MOBILE_QUERY = '(max-width: 900px)';
    const DEFAULT_STATE = Object.freeze({mode: 'expanded', groups: {}});

    function isFeatureEnabled(features, featureId) {
        return Boolean(featureId) && Boolean(features) && features[featureId] === true;
    }

    function applyFeatureVisibility(root, features) {
        if (!root) return;
        const entries = [];
        if (typeof root.matches === 'function' && root.matches('[data-feature]')) {
            entries.push(root);
        }
        if (typeof root.querySelectorAll === 'function') {
            entries.push(...root.querySelectorAll('[data-feature]'));
        }
        entries.forEach((entry) => {
            entry.hidden = !isFeatureEnabled(features, entry.dataset.feature);
        });
    }

    function normalizeShellState(value) {
        if (value === 'expanded') return {mode: 'expanded', groups: {}};
        if (value === 'collapsed') return {mode: 'rail', groups: {}};
        if (!value || typeof value !== 'object' || Array.isArray(value)) {
            return {mode: DEFAULT_STATE.mode, groups: {}};
        }

        const mode = value.mode === 'rail' || value.mode === 'expanded'
            ? value.mode
            : DEFAULT_STATE.mode;
        const groups = {};
        if (value.groups && typeof value.groups === 'object' && !Array.isArray(value.groups)) {
            Object.entries(value.groups).forEach(([groupId, expanded]) => {
                if (typeof expanded === 'boolean') groups[groupId] = expanded;
            });
        }
        return {mode, groups};
    }

    function isNavItemActive(pathname, item) {
        const matches = [item.href, ...(item.aliases || [])].filter(Boolean);
        return matches.some((match) => (
            pathname === match || (match !== '/' && pathname.startsWith(`${match}/`))
        ));
    }

    function reconcileNavigation(sidebar, pathname) {
        if (!sidebar || typeof sidebar.querySelectorAll !== 'function') return;
        sidebar.querySelectorAll('.nav-item').forEach((link) => {
            const aliases = (link.dataset.aliases || '')
                .split(',')
                .map((value) => value.trim())
                .filter(Boolean);
            const active = isNavItemActive(pathname, {
                href: link.getAttribute('href'),
                aliases,
            });
            link.classList.toggle('is-active', active);
            if (active) link.setAttribute('aria-current', 'page');
            else link.removeAttribute('aria-current');
        });
    }

    const exported = {
        applyFeatureVisibility,
        isFeatureEnabled,
        isNavItemActive,
        normalizeShellState,
        reconcileNavigation,
    };

    if (typeof module !== 'undefined' && module.exports) {
        module.exports = exported;
    }

    const body = typeof document !== 'undefined' ? document.body : null;
    if (!body || !body.classList.contains('app-shell')) return;

    const features = window.LEARNFLUX_UI_FEATURES || Object.freeze({});
    const sidebar = document.querySelector('.sidebar');
    const brand = sidebar?.querySelector('.sidebar-brand');
    const topbarTitle = document.querySelector('.topbar-title');
    if (!sidebar || !brand || !topbarTitle) return;

    document.documentElement.classList.add('shell-enhanced');
    if (!sidebar.id) sidebar.id = 'app-sidebar';
    applyFeatureVisibility(document, features);
    reconcileNavigation(sidebar, window.location.pathname);

    const observerRoot = document.querySelector('.main-area') || body;
    if (typeof MutationObserver === 'function') {
        const featureObserver = new MutationObserver((records) => {
            records.forEach((record) => {
                record.addedNodes.forEach((node) => {
                    if (node.nodeType === 1) applyFeatureVisibility(node, features);
                });
            });
        });
        featureObserver.observe(observerRoot, {childList: true, subtree: true});
    }

    function readState() {
        try {
            const raw = localStorage.getItem(STORAGE_KEY);
            if (!raw) return normalizeShellState(null);
            if (raw === 'expanded' || raw === 'collapsed') return normalizeShellState(raw);
            return normalizeShellState(JSON.parse(raw));
        } catch (error) {
            return normalizeShellState(null);
        }
    }

    let shellState = readState();

    function saveState() {
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(shellState));
        } catch (error) {
            // Storage is an enhancement; navigation must remain usable without it.
        }
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

    const collapseButton = brand.querySelector('.shell-collapse-toggle') || createButton(
        'shell-collapse-toggle',
        '收起侧边栏',
        '<path d="M15 18 9 12l6-6"/><path d="M20 12H9"/><path d="M4 5v14"/>'
    );
    if (!collapseButton.isConnected) brand.appendChild(collapseButton);

    let mobileButton = document.querySelector('.shell-mobile-toggle, .mobile-menu-btn');
    if (!mobileButton) {
        mobileButton = createButton(
            'shell-mobile-toggle',
            '打开导航',
            '<path d="M4 6h16"/><path d="M4 12h16"/><path d="M4 18h16"/>'
        );
        topbarTitle.insertBefore(mobileButton, topbarTitle.firstChild);
    } else {
        mobileButton.classList.add('shell-mobile-toggle');
        mobileButton.setAttribute('aria-controls', sidebar.id);
    }

    let overlay = document.querySelector('.shell-overlay, .sidebar-overlay');
    if (!overlay) {
        overlay = document.createElement('button');
        overlay.type = 'button';
        overlay.className = 'shell-overlay';
        overlay.setAttribute('aria-label', '关闭导航');
        body.appendChild(overlay);
    } else {
        overlay.classList.add('shell-overlay');
        if (overlay.tagName === 'BUTTON') overlay.type = 'button';
        overlay.setAttribute('aria-label', '关闭导航');
    }

    let themeButton = brand.querySelector('.shell-theme-toggle');
    if (!themeButton) {
        themeButton = createButton('shell-theme-toggle', '切换外观', '');
        brand.appendChild(themeButton);
    }

    function updateThemeIcon() {
        const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
        themeButton.innerHTML = icon(isDark
            ? '<circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/>'
            : '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>');
    }
    updateThemeIcon();
    themeButton.addEventListener('click', () => {
        const current = document.documentElement.getAttribute('data-theme');
        const next = current === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', next);
        try {
            localStorage.setItem('vta_theme_preference', JSON.stringify(next));
        } catch (error) {
            // Theme persistence is optional.
        }
        updateThemeIcon();
    });

    function navLabel(link) {
        const explicit = link.querySelector('.nav-label')?.textContent;
        if (explicit) return explicit.trim();
        const clone = link.cloneNode(true);
        clone.querySelectorAll('.nav-icon').forEach((node) => node.remove());
        return clone.textContent.trim();
    }

    sidebar.querySelectorAll('.nav-item').forEach((link) => {
        const label = navLabel(link);
        if (!label) return;
        link.dataset.label = label;
        if (!link.getAttribute('aria-label')) link.setAttribute('aria-label', label);
    });

    const groupControls = [...sidebar.querySelectorAll('.nav-group-toggle')];
    function groupIdFor(control) {
        return control.dataset.group || control.closest('.nav-group')?.dataset.group || '';
    }

    function applyGroupStates() {
        const rail = shellState.mode === 'rail' && !window.matchMedia(MOBILE_QUERY).matches;
        groupControls.forEach((control) => {
            const groupId = groupIdFor(control);
            const contentId = control.getAttribute('aria-controls');
            const content = contentId ? document.getElementById(contentId) : null;
            if (!content) return;
            const expanded = rail || shellState.groups[groupId] !== false;
            content.hidden = !expanded;
            control.setAttribute('aria-expanded', String(expanded));
        });
    }

    function applyDesktopMode() {
        const rail = shellState.mode === 'rail';
        body.classList.toggle('sidebar-rail', rail);
        body.classList.toggle('sidebar-collapsed', rail);
        collapseButton.setAttribute('aria-expanded', String(!rail));
        collapseButton.setAttribute('aria-label', rail ? '展开侧边栏' : '收起为图标栏');
        applyGroupStates();
    }

    groupControls.forEach((control) => {
        const group = control.closest('.nav-group');
        if (group?.querySelector('.nav-item.is-active')) group.classList.add('has-active-item');
        control.addEventListener('click', () => {
            if (shellState.mode === 'rail' && !media.matches) return;
            const groupId = groupIdFor(control);
            shellState.groups[groupId] = control.getAttribute('aria-expanded') !== 'true';
            saveState();
            applyGroupStates();
        });
    });

    const media = window.matchMedia(MOBILE_QUERY);
    let lastFocus = null;

    function focusableDrawerItems() {
        return [...sidebar.querySelectorAll(
            'a[href]:not([hidden]), button:not([disabled]):not([hidden]), '
            + 'input:not([disabled]):not([hidden]), select:not([disabled]):not([hidden]), '
            + 'textarea:not([disabled]):not([hidden]), [tabindex]:not([tabindex="-1"]):not([hidden])'
        )].filter((node) => !node.closest('[hidden]'));
    }

    function closeDrawer(options) {
        body.classList.remove('sidebar-drawer-open');
        mobileButton.setAttribute('aria-expanded', 'false');
        if (options?.restoreFocus !== false && lastFocus && typeof lastFocus.focus === 'function') {
            lastFocus.focus({preventScroll: true});
        }
    }

    function openDrawer() {
        lastFocus = document.activeElement;
        body.classList.add('sidebar-drawer-open');
        mobileButton.setAttribute('aria-expanded', 'true');
        const active = sidebar.querySelector('.nav-item.is-active:not([hidden])')
            || sidebar.querySelector('a:not([hidden]), button:not([hidden])');
        active?.focus({preventScroll: true});
    }

    function syncMode() {
        if (media.matches) {
            body.classList.remove('sidebar-rail', 'sidebar-collapsed');
            closeDrawer({restoreFocus: false});
            applyGroupStates();
            return;
        }
        closeDrawer({restoreFocus: false});
        applyDesktopMode();
    }

    collapseButton.addEventListener('click', () => {
        shellState.mode = shellState.mode === 'rail' ? 'expanded' : 'rail';
        saveState();
        applyDesktopMode();
    });
    mobileButton.addEventListener('click', () => {
        if (body.classList.contains('sidebar-drawer-open')) closeDrawer();
        else openDrawer();
    });
    overlay.addEventListener('click', () => closeDrawer());
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && body.classList.contains('sidebar-drawer-open')) {
            closeDrawer();
            return;
        }
        if (event.key === 'Tab' && media.matches
            && body.classList.contains('sidebar-drawer-open')) {
            const items = focusableDrawerItems();
            if (!items.length) return;
            const first = items[0];
            const last = items[items.length - 1];
            if (event.shiftKey && document.activeElement === first) {
                event.preventDefault();
                last.focus();
            } else if (!event.shiftKey && document.activeElement === last) {
                event.preventDefault();
                first.focus();
            }
        }
    });
    sidebar.addEventListener('click', (event) => {
        if (media.matches && event.target.closest('a')) closeDrawer({restoreFocus: false});
    });

    if (typeof media.addEventListener === 'function') media.addEventListener('change', syncMode);
    else media.addListener(syncMode);

    syncMode();
}());
