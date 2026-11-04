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
        if (value === 'collapsed' || value === 'rail') return {mode: 'floating', groups: {}};
        if (!value || typeof value !== 'object' || Array.isArray(value)) {
            return {mode: DEFAULT_STATE.mode, groups: {}};
        }

        const mode = ['floating', 'rail', 'collapsed'].includes(value.mode)
            ? 'floating' : DEFAULT_STATE.mode;
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
        if (item.exact === true) {
            const normalizedPath = pathname.length > 1 ? pathname.replace(/\/$/, '') : pathname;
            return matches.some((match) => {
                const normalizedMatch = match.length > 1 ? match.replace(/\/$/, '') : match;
                return normalizedPath === normalizedMatch;
            });
        }
        return matches.some((match) => (
            pathname === match || (match !== '/' && pathname.startsWith(`${match}/`))
        ));
    }

    function reconcileNavigation(sidebar, pathname) {
        if (!sidebar || typeof sidebar.querySelectorAll !== 'function') return;
        sidebar.querySelectorAll('.nav-item, .nav-subitem').forEach((link) => {
            const aliases = (link.dataset.aliases || '')
                .split(',')
                .map((value) => value.trim())
                .filter(Boolean);
            const active = isNavItemActive(pathname, {
                href: link.getAttribute('href'),
                aliases,
                exact: link.dataset.navMatch === 'exact',
            });
            link.classList.toggle('is-active', active);
            if (active && link.dataset.navParent !== 'true') {
                link.setAttribute('aria-current', 'page');
            }
            else link.removeAttribute('aria-current');
        });
    }

    function syncProductPageTitle(sidebar, documentRoot) {
        if (!sidebar || !documentRoot || typeof sidebar.querySelector !== 'function') {
            return '';
        }
        const activeLink = sidebar.querySelector('.nav-subitem.is-active, .nav-item.is-active');
        const label = activeLink ? navLabel(activeLink) : '';
        if (!label) return documentRoot.title || '';
        const title = `${label} · LearnFlux`;
        documentRoot.title = title;
        return title;
    }

    function setNavigationBranchExpanded(branch, expanded) {
        if (!branch || typeof branch.querySelector !== 'function') return false;
        const toggle = branch.querySelector('.nav-branch-toggle');
        const subitems = branch.querySelector('.nav-subitems');
        if (!toggle || !subitems) return false;

        const nextExpanded = Boolean(expanded);
        branch.classList.toggle('is-expanded', nextExpanded);
        toggle.setAttribute('aria-expanded', String(nextExpanded));
        subitems.hidden = !nextExpanded;

        const label = branch
            .querySelector('[data-nav-parent="true"] .nav-label')
            ?.textContent?.trim() || '导航';
        toggle.setAttribute(
            'aria-label',
            `${nextExpanded ? '收起' : '展开'}${label}二级导航`
        );
        return nextExpanded;
    }

    const exported = {
        applyFeatureVisibility,
        isFeatureEnabled,
        isNavItemActive,
        normalizeShellState,
        reconcileNavigation,
        setNavigationBranchExpanded,
        syncProductPageTitle,
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
    syncProductPageTitle(sidebar, document);

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

    sidebar.querySelectorAll('.nav-item, .nav-subitem').forEach((link) => {
        const label = navLabel(link);
        if (!label) return;
        link.dataset.label = label;
        if (!link.getAttribute('aria-label')) link.setAttribute('aria-label', label);
    });

    sidebar.querySelectorAll('.nav-branch-toggle').forEach((control) => {
        const branch = control.closest('.nav-branch');
        if (!branch) return;
        const activeBranch = Boolean(
            branch.querySelector('.nav-item[data-nav-parent="true"].is-active')
        );
        setNavigationBranchExpanded(
            branch,
            activeBranch || control.getAttribute('aria-expanded') === 'true'
        );
        control.addEventListener('click', () => {
            setNavigationBranchExpanded(
                branch,
                control.getAttribute('aria-expanded') !== 'true'
            );
        });
    });

    const groupControls = [...sidebar.querySelectorAll('.nav-group-toggle')];
    function groupIdFor(control) {
        return control.dataset.group || control.closest('.nav-group')?.dataset.group || '';
    }

    function applyGroupStates() {
        groupControls.forEach((control) => {
            const groupId = groupIdFor(control);
            const contentId = control.getAttribute('aria-controls');
            const content = contentId ? document.getElementById(contentId) : null;
            if (!content) return;
            const expanded = shellState.groups[groupId] !== false;
            content.hidden = !expanded;
            control.setAttribute('aria-expanded', String(expanded));
        });
    }

    function applyDesktopMode() {
        const floating = !media.matches && shellState.mode === 'floating';
        body.classList.remove('sidebar-rail', 'sidebar-collapsed', 'drawer-hover-open');
        body.classList.toggle('sidebar-floating', floating);
        sidebar.inert = media.matches || floating;
        collapseButton.setAttribute('aria-pressed', String(!floating));
        collapseButton.setAttribute('aria-label', floating ? '固定侧边栏' : '自动隐藏侧边栏');
        collapseButton.innerHTML = icon(floating
            ? '<path d="M12 17v5M9 10.5V9a3 3 0 0 1 6 0v1.5a4 4 0 0 0 1.25 2.91 1.48 1.48 0 0 1-.48 2.59H8.23a1.48 1.48 0 0 1-.48-2.59A4 4 0 0 0 9 10.5Z"/>'
            : '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 3v18"/>');
        applyGroupStates();
    }

    groupControls.forEach((control) => {
        const group = control.closest('.nav-group');
        if (group?.querySelector('.nav-item.is-active, .nav-subitem.is-active')) {
            group.classList.add('has-active-item');
        }
        control.addEventListener('click', () => {
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
        )].filter((node) => !node.closest('[hidden]') && node.getClientRects().length > 0);
    }

    function closeDrawer(options) {
        body.classList.remove('sidebar-drawer-open');
        sidebar.inert = media.matches || shellState.mode === 'floating';
        mobileButton.setAttribute('aria-expanded', 'false');
        if (options?.restoreFocus !== false && lastFocus && typeof lastFocus.focus === 'function') {
            lastFocus.focus({preventScroll: true});
        }
    }

    function openDrawer() {
        lastFocus = document.activeElement;
        sidebar.inert = false;
        body.classList.add('sidebar-drawer-open');
        mobileButton.setAttribute('aria-expanded', 'true');
        const active = sidebar.querySelector('.nav-subitem.is-active:not([hidden])')
            || sidebar.querySelector('.nav-item.is-active:not([hidden])')
            || sidebar.querySelector('a:not([hidden]), button:not([hidden])');
        active?.focus({preventScroll: true});
    }

    function syncMode() {
        closeDrawer({restoreFocus: false});
        applyDesktopMode();
    }

    collapseButton.addEventListener('click', () => {
        shellState.mode = shellState.mode === 'floating' ? 'expanded' : 'floating';
        saveState();
        applyDesktopMode();
        if (shellState.mode === 'floating') floatingToggleBtn.focus({preventScroll: true});
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
        if (event.key === 'Escape' && body.classList.contains('drawer-hover-open')) {
            closeFloating();
            floatingToggleBtn.focus({preventScroll: true});
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

    // Width and visibility are owned by this shell, across every product page.
    const resizer = document.createElement('div');
    resizer.className = 'sidebar-resizer';
    resizer.setAttribute('role', 'separator');
    resizer.setAttribute('aria-label', '调整侧边栏宽度');
    resizer.setAttribute('aria-orientation', 'vertical');
    resizer.setAttribute('aria-valuemin', '240');
    resizer.setAttribute('aria-valuemax', '600');
    resizer.tabIndex = 0;
    sidebar.appendChild(resizer);

    let isResizing = false;
    let savedWidth = 280;
    try {
        savedWidth = Number(localStorage.getItem('vta_sidebar_width')) || 280;
    } catch (error) {
        // Navigation remains usable when browser storage is unavailable.
    }

    function setSidebarWidth(width, persist = false) {
        const nextWidth = Math.round(Math.max(240, Math.min(600, width)));
        body.style.setProperty('--shell-sidebar', `${nextWidth}px`);
        resizer.setAttribute('aria-valuenow', String(nextWidth));
        if (persist) {
            try {
                localStorage.setItem('vta_sidebar_width', String(nextWidth));
            } catch (error) {
                // Width persistence is optional.
            }
        }
    }
    setSidebarWidth(savedWidth);

    resizer.addEventListener('mousedown', (event) => {
        if (media.matches || event.button !== 0) return;
        event.preventDefault();
        isResizing = true;
        body.classList.add('is-resizing');
    });
    document.addEventListener('mousemove', (event) => {
        if (isResizing) setSidebarWidth(event.clientX);
    });
    document.addEventListener('mouseup', () => {
        if (!isResizing) return;
        isResizing = false;
        body.classList.remove('is-resizing');
        setSidebarWidth(Number(resizer.getAttribute('aria-valuenow')), true);
    });
    resizer.addEventListener('keydown', (event) => {
        const current = Number(resizer.getAttribute('aria-valuenow'));
        const widths = {ArrowLeft: current - 10, ArrowRight: current + 10, Home: 240, End: 600};
        if (!(event.key in widths)) return;
        event.preventDefault();
        setSidebarWidth(widths[event.key], true);
    });

    const hoverTrigger = document.createElement('div');
    hoverTrigger.className = 'sidebar-hover-trigger';
    hoverTrigger.setAttribute('aria-hidden', 'true');
    body.appendChild(hoverTrigger);
    const floatingToggleBtn = createButton('floating-toggle-btn', '打开侧边栏',
        '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 3v18"/>');
    body.appendChild(floatingToggleBtn);

    // Reveal near the actual button without putting a hit area over page content.
    function updateFloatingToggleVisibility(event) {
        if (event.pointerType === 'touch' || media.matches || shellState.mode !== 'floating') return;
        const rect = floatingToggleBtn.getBoundingClientRect();
        const near = event.clientX >= rect.left - 16 && event.clientX <= rect.right + 16
            && event.clientY >= rect.top - 16 && event.clientY <= rect.bottom + 16;
        floatingToggleBtn.classList.toggle('is-revealed', near);
    }
    function hideFloatingToggle() {
        floatingToggleBtn.classList.remove('is-revealed');
    }
    document.addEventListener('pointermove', updateFloatingToggleVisibility, {passive: true});
    document.addEventListener('pointerleave', hideFloatingToggle);
    document.addEventListener('input', hideFloatingToggle);
    window.addEventListener('blur', hideFloatingToggle);

    let hoverTimeout;
    function openFloating() {
        if (media.matches || shellState.mode !== 'floating') return;
        clearTimeout(hoverTimeout);
        sidebar.inert = false;
        body.classList.add('drawer-hover-open');
    }
    function closeFloating() {
        if (isResizing) return;
        clearTimeout(hoverTimeout);
        body.classList.remove('drawer-hover-open');
        sidebar.inert = !media.matches && shellState.mode === 'floating';
    }
    hoverTrigger.addEventListener('mouseenter', openFloating);
    sidebar.addEventListener('mouseenter', () => clearTimeout(hoverTimeout));
    sidebar.addEventListener('mouseleave', () => {
        if (media.matches || shellState.mode !== 'floating' || isResizing) return;
        hoverTimeout = setTimeout(() => {
            if (!sidebar.contains(document.activeElement)) closeFloating();
        }, 300);
    });
    sidebar.addEventListener('focusout', (event) => {
        if (!sidebar.contains(event.relatedTarget)) closeFloating();
    });
    floatingToggleBtn.addEventListener('click', () => {
        openFloating();
        const active = sidebar.querySelector('.nav-item.is-active, a:not([hidden])');
        active?.focus({preventScroll: true});
    });
}());
