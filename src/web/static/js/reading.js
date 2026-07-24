(function () {
    'use strict';

    const TOKEN_KEY = 'vta_bearer_token';
    const ENCRYPTION_KEY = 'vta_encrypt_key_2024';
    const PANEL_CLOSE_DELAY_MS = 300;
    const initialMatch = window.location.pathname.match(/^\/reading(?:\/([^/]+))?\/?$/);
    const state = {
        documentId: initialMatch && initialMatch[1] ? decodeURIComponent(initialMatch[1]) : null,
        detail: null,
        chapterIndex: 0,
        spreadIndex: 0,
        pageCount: 1,
        spreadCount: 1,
        paginationFrame: null,
        progressTimer: null,
        panel: null,
        panelCloseTimer: null,
        toolbarTimer: null,
        importTrigger: null,
        libraryItems: [],
        assetObjectUrls: [],
        ocrPollTimer: null,
        preferences: { theme: 'original', font_family: 'serif', font_size: 22, layout: 'double', sound_track: 'rain', sound_volume: 0.28 },
    };
    window.ReadingPageState = state;

    const elements = {
        library: document.getElementById('reading-library'),
        grid: document.getElementById('reading-grid'),
        empty: document.getElementById('reading-empty-state'),
        status: document.getElementById('reading-status'),
        search: document.getElementById('reading-search'),
        sort: document.getElementById('reading-sort'),
        continueCard: document.getElementById('reading-continue-card'),
        continueCover: document.getElementById('reading-continue-cover'),
        continueAuthor: document.getElementById('reading-continue-author'),
        continueCoverTitle: document.getElementById('reading-continue-cover-title'),
        continueFormat: document.getElementById('reading-continue-format'),
        continueTitle: document.getElementById('reading-continue-title'),
        continueChapter: document.getElementById('reading-continue-chapter'),
        continueProgress: document.getElementById('reading-continue-progress'),
        continueProgressLabel: document.getElementById('reading-continue-progress-label'),
        continueButton: document.getElementById('reading-continue-button'),
        importDialog: document.getElementById('reading-import'),
        importButton: document.getElementById('reading-import-button'),
        fileInput: document.getElementById('reading-file-input'),
        importStatus: document.getElementById('reading-import-status'),
        dropzone: document.getElementById('reading-dropzone'),
        reader: document.getElementById('reading-reader'),
        toolbar: document.getElementById('reading-toolbar'),
        readerTitle: document.getElementById('reading-reader-title'),
        content: document.getElementById('reading-reader-content'),
        pages: document.getElementById('reading-reader-pages'),
        flow: document.getElementById('reading-flow-content'),
        indicator: document.getElementById('reading-page-indicator'),
        tocList: document.getElementById('reading-toc-list'),
        documentSearch: document.getElementById('reading-document-search'),
        searchResult: document.getElementById('reading-search-result'),
        soundShortcut: document.getElementById('reading-sound-shortcut'),
        fontSize: document.getElementById('reading-font-size'),
        volume: document.getElementById('reading-volume'),
        audio: document.getElementById('reading-audio'),
        soundOptions: document.getElementById('reading-sound-options'),
    };

    function decryptToken(encoded) {
        if (!encoded) return '';
        try {
            const reversed = encoded.split('').reverse().join('');
            const decoded = decodeURIComponent(escape(atob(reversed)));
            return decoded.endsWith(ENCRYPTION_KEY)
                ? decoded.slice(0, -ENCRYPTION_KEY.length)
                : encoded;
        } catch (error) {
            return encoded;
        }
    }

    function token() {
        return decryptToken(localStorage.getItem(TOKEN_KEY)).trim();
    }

    async function api(path, options = {}) {
        const accessToken = token();
        if (!accessToken) throw new Error('请先在系统设置中保存 API 访问令牌');
        const headers = new Headers(options.headers || {});
        headers.set('Authorization', `Bearer ${accessToken}`);
        if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json');
        const response = await fetch(path, { ...options, headers });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload.detail || payload.message || '请求失败');
        return payload.data;
    }

    async function apiBlob(path) {
        const accessToken = token();
        if (!accessToken) throw new Error('请先在系统设置中保存 API 访问令牌');
        const response = await fetch(path, {
            headers: { Authorization: `Bearer ${accessToken}` },
        });
        if (!response.ok) throw new Error('图片加载失败');
        return response.blob();
    }

    function setStatus(message, isError = false) {
        elements.status.textContent = message || '';
        elements.status.classList.toggle('is-error', isError);
    }

    function openImport(event) {
        if (!elements.importDialog || elements.importDialog.open) return;
        state.importTrigger = event.currentTarget;
        elements.importStatus.textContent = '';
        elements.importDialog.showModal();
        const closeButton = elements.importDialog.querySelector('[data-reading-import-close]');
        if (closeButton) closeButton.focus({ preventScroll: true });
    }

    function closeImport() {
        if (elements.importDialog && elements.importDialog.open) elements.importDialog.close();
    }

    async function importFile(file) {
        if (!file) return;
        elements.importStatus.textContent = `正在导入「${file.name}」…`;
        elements.fileInput.disabled = true;
        try {
            const form = new FormData();
            form.append('file', file);
            const documentData = await api('/api/reading/documents', { method: 'POST', body: form });
            elements.importStatus.textContent = '导入完成，正在打开…';
            await loadLibrary();
            closeImport();
            await openDocument(documentData.id);
        } catch (error) {
            elements.importStatus.textContent = error.message;
        } finally {
            elements.fileInput.disabled = false;
            elements.fileInput.value = '';
        }
    }

    function formatLabel(value) {
        return ({ pdf: 'PDF', epub: 'EPUB', docx: 'DOCX', txt: 'TXT', markdown: 'MD' })[value] || value.toUpperCase();
    }

    function itemTimestamp(item, field) {
        const value = item[field] || item.updated_at || item.created_at || '';
        const timestamp = Date.parse(value);
        return Number.isNaN(timestamp) ? 0 : timestamp;
    }

    function filteredLibraryItems() {
        const query = (elements.search.value || '').trim().toLocaleLowerCase('zh-CN');
        const items = state.libraryItems.filter((item) => {
            if (!query) return true;
            return [item.title, item.author, item.format]
                .filter(Boolean)
                .some((value) => String(value).toLocaleLowerCase('zh-CN').includes(query));
        });
        if (elements.sort.value === 'title') {
            return items.sort((left, right) => left.title.localeCompare(right.title, 'zh-CN'));
        }
        const field = elements.sort.value === 'newest' ? 'created_at' : 'last_opened_at';
        return items.sort((left, right) => itemTimestamp(right, field) - itemTimestamp(left, field));
    }

    function progressPercent(item) {
        return Math.max(0, Math.min(100, Number(item._progress && item._progress.percent) || 0));
    }

    function renderContinueCard(items) {
        const item = items.find((candidate) => candidate.status === 'ready');
        elements.continueCard.hidden = !item;
        if (!item) return;
        const chapters = item._chapters || [];
        const locator = item._progress && item._progress.locator;
        const chapter = chapters.find((candidate) => locator && candidate.id === locator.chapter_id) || chapters[0];
        const percent = progressPercent(item);
        elements.continueCard.dataset.documentId = item.id;
        elements.continueAuthor.textContent = (item.author || formatLabel(item.format)).toUpperCase();
        elements.continueCoverTitle.textContent = item.title;
        elements.continueFormat.textContent = formatLabel(item.format);
        elements.continueTitle.textContent = item.title;
        elements.continueChapter.textContent = chapter ? chapter.title : '从上次停下的位置继续阅读';
        elements.continueProgress.style.width = `${percent}%`;
        elements.continueProgressLabel.textContent = percent > 0 ? `已读 ${Math.round(percent)}%` : '尚未开始';
    }

    function renderLibrary() {
        const items = filteredLibraryItems();
        elements.grid.replaceChildren();
        elements.empty.hidden = state.libraryItems.length > 0;
        renderContinueCard(state.libraryItems);
        items.forEach((item, index) => {
            const card = document.createElement('article');
            card.className = 'reading-book-card';
            card.dataset.documentId = item.id;
            const openButton = document.createElement('button');
            openButton.type = 'button';
            openButton.className = 'reading-book-open';
            const cover = document.createElement('span');
            cover.className = `reading-book-cover cover-${index % 6}`;
            const coverAuthor = document.createElement('span');
            coverAuthor.textContent = (item.author || 'LOCAL DOCUMENT').toUpperCase();
            const coverTitle = document.createElement('strong');
            coverTitle.textContent = item.title;
            const coverFormat = document.createElement('small');
            coverFormat.textContent = formatLabel(item.format);
            cover.append(coverAuthor, coverTitle, coverFormat);
            const meta = document.createElement('span');
            meta.className = 'reading-book-meta';
            const title = document.createElement('strong');
            title.textContent = item.title;
            const detail = document.createElement('small');
            const status = item.status === 'ready' ? formatLabel(item.format) : item.status === 'needs_ocr' ? '等待本地 OCR' : item.status === 'failed' ? '识别失败' : '正在本地 OCR';
            detail.textContent = `${item.author || '本地导入'} · ${status}`;
            const progress = document.createElement('span');
            progress.className = 'reading-book-progress';
            const progressValue = document.createElement('i');
            progressValue.style.width = `${progressPercent(item)}%`;
            progress.appendChild(progressValue);
            meta.append(title, detail, progress);
            openButton.append(cover, meta);
            openButton.addEventListener('click', () => openDocument(item.id));
            const removeButton = document.createElement('button');
            removeButton.type = 'button';
            removeButton.className = 'reading-book-remove';
            removeButton.setAttribute('aria-label', `移除《${item.title}》`);
            removeButton.textContent = '×';
            removeButton.addEventListener('click', async () => {
                if (!window.confirm(`移除《${item.title}》？`)) return;
                removeButton.disabled = true;
                try {
                    await api(`/api/reading/documents/${encodeURIComponent(item.id)}`, { method: 'DELETE' });
                    await loadLibrary();
                } catch (error) {
                    removeButton.disabled = false;
                    setStatus(error.message, true);
                }
            });
            card.append(openButton, removeButton);
            elements.grid.appendChild(card);
        });
    }

    async function enrichLibraryItems(items) {
        return Promise.all(items.map(async (item) => {
            if (item.status !== 'ready') return item;
            try {
                const detail = await api(`/api/reading/documents/${encodeURIComponent(item.id)}`);
                return { ...item, _progress: detail.progress, _chapters: detail.chapters || [] };
            } catch (_) {
                return item;
            }
        }));
    }

    async function loadLibrary() {
        setStatus('正在加载书架…');
        try {
            const data = await api('/api/reading/documents');
            state.libraryItems = await enrichLibraryItems(data.items || []);
            renderLibrary();
            setStatus('');
            clearTimeout(state.ocrPollTimer);
            if (state.libraryItems.some((item) => item.status === 'processing')) {
                state.ocrPollTimer = setTimeout(loadLibrary, 3000);
            }
        } catch (error) {
            state.libraryItems = [];
            renderLibrary();
            setStatus(error.message, true);
        }
    }

    async function openDocument(documentId, updateHistory = true) {
        setStatus('正在打开文档…');
        try {
            const detail = await api(`/api/reading/documents/${encodeURIComponent(documentId)}`);
            if (detail.document.status === 'processing') {
                setStatus('正在使用本地 OCR 识别扫描件，完成后可直接阅读。');
                return;
            }
            if (detail.document.status === 'needs_ocr') {
                const documentData = await api(`/api/reading/documents/${encodeURIComponent(documentId)}/ocr`, { method: 'POST' });
                if (documentData.status === 'processing') {
                    setStatus('正在使用本地 OCR 识别扫描件，完成后可直接阅读。');
                    await loadLibrary();
                    return;
                }
                throw new Error('本地 OCR 尚未就绪，请按服务端说明安装后重试。');
            }
            if (!detail.chapters || !detail.chapters.length) throw new Error('文档没有可阅读的文字内容');
            state.documentId = documentId;
            state.detail = detail;
            const savedChapter = detail.progress && detail.progress.locator ? detail.progress.locator.chapter_id : '';
            const savedIndex = detail.chapters.findIndex((chapter) => chapter.id === savedChapter);
            state.chapterIndex = savedIndex >= 0 ? savedIndex : 0;
            elements.reader.hidden = false;
            document.body.classList.add('reading-mode');
            renderToc();
            renderDocumentFlow();
            showToolbar();
            if (updateHistory && window.location.pathname !== `/reading/${documentId}`) {
                history.pushState({ documentId }, '', `/reading/${documentId}`);
            }
            setStatus('');
        } catch (error) {
            setStatus(error.message, true);
        }
    }

    function renderToc() {
        elements.tocList.replaceChildren();
        let entries = state.detail.chapters.map((chapter, index) => ({
            title: chapter.title,
            chapterIndex: index,
            level: 1,
        }));
        try {
            const outline = JSON.parse(state.detail.document.outline_json || '[]');
            const chapterIndexes = new Map(
                state.detail.chapters.map((chapter, index) => [chapter.id, index]),
            );
            const parsedEntries = outline
                .map((item) => ({
                    title: item.title,
                    chapterIndex: chapterIndexes.get(item.chapter_id || item.id),
                    level: Math.max(1, Number(item.level) || 1),
                }))
                .filter((item) => Number.isInteger(item.chapterIndex));
            if (parsedEntries.length) entries = parsedEntries;
        } catch (_) {}
        entries.forEach((entry) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.dataset.chapterIndex = String(entry.chapterIndex);
            button.dataset.level = String(entry.level);
            button.style.setProperty('--reading-toc-level', String(entry.level - 1));
            button.textContent = entry.title || `第 ${entry.chapterIndex + 1} 章`;
            button.classList.toggle('is-active', entry.chapterIndex === state.chapterIndex);
            button.addEventListener('click', () => navigateTo(entry.chapterIndex));
            elements.tocList.appendChild(button);
        });
    }

    function chapterNodes(chapter) {
        const template = document.createElement('template');
        template.innerHTML = chapter.sanitized_html;
        const nodes = Array.from(template.content.childNodes).filter((node) => (
            node.nodeType !== Node.TEXT_NODE || node.textContent.trim()
        ));
        const first = nodes[0];
        if (first && /^H[1-3]$/.test(first.tagName || '') && first.textContent.trim() === chapter.title.trim()) {
            nodes.shift();
        }
        return nodes;
    }

    function releaseAssetObjectUrls() {
        state.assetObjectUrls.forEach((value) => URL.revokeObjectURL(value));
        state.assetObjectUrls = [];
    }

    function hydrateReadingImages() {
        if (!state.documentId) return;
        const documentId = encodeURIComponent(state.documentId);
        elements.flow.querySelectorAll('img[data-reading-asset]').forEach(async (image) => {
            const assetName = encodeURIComponent(image.dataset.readingAsset || '');
            if (!assetName) return;
            try {
                const blob = await apiBlob(`/api/reading/documents/${documentId}/assets/${assetName}`);
                const objectUrl = URL.createObjectURL(blob);
                state.assetObjectUrls.push(objectUrl);
                image.src = objectUrl;
                image.addEventListener('load', () => paginateDocument({ focusContent: false }), { once: true });
            } catch (_) {
                image.replaceWith(Object.assign(document.createElement('span'), {
                    className: 'reading-image-placeholder',
                    textContent: '图片加载失败',
                }));
            }
        });
    }

    function appendChapterHeading(container, kicker, title) {
        const header = document.createElement('header');
        header.className = 'reading-flow-chapter-heading';
        const kickerElement = document.createElement('div');
        kickerElement.className = 'reading-chapter-kicker';
        kickerElement.textContent = kicker;
        const heading = document.createElement('h1');
        heading.textContent = title;
        header.append(kickerElement, heading);
        container.appendChild(header);
    }

    function columnsPerSpread() {
        if (state.preferences.layout === 'single') return 1;
        return window.matchMedia('(max-width: 900px)').matches ? 1 : 2;
    }

    function syncTocActive() {
        elements.tocList.querySelectorAll('[data-chapter-index]').forEach((button) => {
            button.classList.toggle(
                'is-active',
                Number(button.dataset.chapterIndex) === state.chapterIndex,
            );
        });
    }

    function chapterIndexAtOffset(offset) {
        let current = 0;
        elements.flow.querySelectorAll('[data-reading-chapter-marker]').forEach((marker) => {
            if (marker.offsetLeft <= offset + 2) current = Number(marker.dataset.readingChapterMarker);
        });
        return current;
    }

    function persistProgressSoon() {
        clearTimeout(state.progressTimer);
        state.progressTimer = setTimeout(() => {
            if (!state.detail || !state.documentId) return;
            const chapter = state.detail.chapters[state.chapterIndex];
            const percent = Math.round(((state.spreadIndex + 1) / state.spreadCount) * 100);
            api(`/api/reading/documents/${state.documentId}/progress`, {
                method: 'PUT',
                body: JSON.stringify({ chapter_id: chapter.id, percent }),
            }).catch(() => {});
        }, 180);
    }

    function updateSpreadControls() {
        const columns = columnsPerSpread();
        const firstPage = state.spreadIndex * columns + 1;
        const lastPage = Math.min(firstPage + columns - 1, state.pageCount);
        const visiblePages = firstPage === lastPage ? `${firstPage}` : `${firstPage}–${lastPage}`;
        elements.indicator.textContent = `${visiblePages} / ${state.pageCount}`;
        document.querySelector('[data-reading-prev]').disabled = state.spreadIndex === 0;
        document.querySelector('[data-reading-next]').disabled = state.spreadIndex >= state.spreadCount - 1;
    }

    function goToSpread(index, { behavior = 'smooth', saveProgress = true, focusContent = true } = {}) {
        if (!state.detail) return;
        const target = Math.max(0, Math.min(state.spreadCount - 1, index));
        state.spreadIndex = target;
        const targetLeft = target * elements.pages.clientWidth;
        if (behavior === 'auto') {
            elements.pages.scrollLeft = targetLeft;
        } else {
            elements.pages.scrollTo({ left: targetLeft, behavior });
        }
        state.chapterIndex = chapterIndexAtOffset(targetLeft + 4);
        syncTocActive();
        updateSpreadControls();
        if (focusContent) elements.content.focus({ preventScroll: true });
        if (saveProgress) persistProgressSoon();
    }

    function paginateDocument({ chapterIndex = null, saveProgress = false, focusContent = true } = {}) {
        if (!state.detail || elements.reader.hidden) return;
        const previousRatio = state.spreadCount > 1
            ? state.spreadIndex / (state.spreadCount - 1)
            : 0;
        cancelAnimationFrame(state.paginationFrame);
        state.paginationFrame = requestAnimationFrame(() => {
            const viewportWidth = elements.pages.clientWidth;
            if (!viewportWidth) return;
            const columns = columnsPerSpread();
            const pageWidth = viewportWidth / columns;
            const pageGutter = Number.parseFloat(getComputedStyle(elements.flow).marginLeft) || 0;
            const contentWidth = Math.max(240, pageWidth - (2 * pageGutter));
            elements.flow.style.setProperty('--reader-page-width', `${contentWidth}px`);
            elements.pages.scrollLeft = 0;
            void elements.flow.offsetWidth;
            const documentWidth = Math.max(elements.flow.scrollWidth, elements.pages.scrollWidth);
            state.pageCount = Math.max(1, Math.ceil((documentWidth - 1) / pageWidth));
            state.spreadCount = Math.max(1, Math.ceil(state.pageCount / columns));
            let target = Math.round(previousRatio * Math.max(0, state.spreadCount - 1));
            if (chapterIndex !== null) {
                const marker = elements.flow.querySelector(
                    `[data-reading-chapter-marker="${chapterIndex}"]`,
                );
                if (marker) target = Math.floor(marker.offsetLeft / viewportWidth);
            }
            goToSpread(target, { behavior: 'auto', saveProgress, focusContent });
        });
    }

    function renderDocumentFlow() {
        releaseAssetObjectUrls();
        elements.flow.replaceChildren();
        elements.readerTitle.textContent = state.detail.document.title;
        const isPdf = state.detail.document.format === 'pdf';
        state.detail.chapters.forEach((chapter, index) => {
            const marker = document.createElement('span');
            marker.className = 'reading-flow-marker';
            marker.dataset.readingChapterMarker = String(index);
            elements.flow.appendChild(marker);
            if (!isPdf) {
                appendChapterHeading(elements.flow, `第 ${index + 1} 章`, chapter.title);
            }
            chapterNodes(chapter).forEach((node) => elements.flow.appendChild(node.cloneNode(true)));
        });
        elements.reader.style.setProperty('--reader-font-size', `${state.preferences.font_size}px`);
        paginateDocument({ chapterIndex: state.chapterIndex, saveProgress: false });
        hydrateReadingImages();
    }

    function navigateTo(index) {
        if (!state.detail || index < 0 || index >= state.detail.chapters.length) return;
        const marker = elements.flow.querySelector(`[data-reading-chapter-marker="${index}"]`);
        if (!marker) return;
        const target = Math.floor(marker.offsetLeft / elements.pages.clientWidth);
        goToSpread(target);
        closePanels();
    }

    function exitReader(updateHistory = true) {
        cancelAnimationFrame(state.paginationFrame);
        clearTimeout(state.progressTimer);
        elements.reader.hidden = true;
        document.body.classList.remove('reading-mode');
        closePanels();
        pauseSound();
        releaseAssetObjectUrls();
        state.documentId = null;
        state.detail = null;
        if (updateHistory && window.location.pathname !== '/reading') history.pushState({}, '', '/reading');
    }

    function panelElement(name) {
        return document.getElementById(`reading-panel-${name}`);
    }

    function openPanel(name) {
        cancelPanelClose();
        if (state.panel === name && !panelElement(name).hidden) {
            closePanels();
            return;
        }
        document.querySelectorAll('.reading-panel').forEach((panel) => { panel.hidden = true; });
        const panel = panelElement(name);
        if (!panel) return;
        state.panel = name;
        panel.hidden = false;
        document.querySelectorAll('[data-reading-panel]').forEach((button) => {
            button.classList.toggle('is-active', button.dataset.readingPanel === name);
        });
        showToolbar();
        if (name === 'search') elements.documentSearch.focus({ preventScroll: true });
    }

    function closePanels() {
        cancelPanelClose();
        state.panel = null;
        document.querySelectorAll('.reading-panel').forEach((panel) => { panel.hidden = true; });
        document.querySelectorAll('[data-reading-panel]').forEach((button) => button.classList.remove('is-active'));
    }

    function showToolbar() {
        elements.reader.classList.add('toolbar-visible');
        clearTimeout(state.toolbarTimer);
        if (!state.panel) state.toolbarTimer = setTimeout(() => elements.reader.classList.remove('toolbar-visible'), 3000);
    }

    function cancelPanelClose() {
        clearTimeout(state.panelCloseTimer);
        state.panelCloseTimer = null;
    }

    function schedulePanelClose() {
        cancelPanelClose();
        state.panelCloseTimer = setTimeout(closePanels, PANEL_CLOSE_DELAY_MS);
    }

    function applyTheme(theme, persist = true) {
        state.preferences.theme = theme;
        elements.reader.dataset.readerTheme = theme;
        document.querySelectorAll('[data-reading-theme]').forEach((button) => {
            button.classList.toggle('is-active', button.dataset.readingTheme === theme);
        });
        if (persist) savePreferences();
    }

    function applyLayout(layout, persist = true) {
        state.preferences.layout = layout;
        elements.reader.dataset.readingLayout = layout;
        document.querySelectorAll('[data-reading-layout]').forEach((button) => {
            button.classList.toggle('is-active', button.dataset.readingLayout === layout);
        });
        if (state.detail) paginateDocument();
        if (persist) savePreferences();
    }

    function changeFontSize(direction) {
        const delta = direction === 'larger' ? 2 : -2;
        state.preferences.font_size = Math.max(16, Math.min(32, state.preferences.font_size + delta));
        elements.fontSize.value = state.preferences.font_size;
        elements.reader.style.setProperty('--reader-font-size', `${state.preferences.font_size}px`);
        if (state.detail) paginateDocument();
        savePreferences();
    }

    function highlightText(container, query) {
        if (!query) return 0;
        let matches = 0;
        const expression = new RegExp(query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi');
        const visit = (node) => {
            Array.from(node.childNodes).forEach((child) => {
                if (child.nodeType === Node.TEXT_NODE) {
                    const text = child.textContent || '';
                    if (!expression.test(text)) {
                        expression.lastIndex = 0;
                        return;
                    }
                    expression.lastIndex = 0;
                    const fragment = document.createDocumentFragment();
                    let cursor = 0;
                    text.replace(expression, (value, offset) => {
                        fragment.append(document.createTextNode(text.slice(cursor, offset)));
                        const mark = document.createElement('mark');
                        mark.textContent = value;
                        fragment.append(mark);
                        cursor = offset + value.length;
                        matches += 1;
                        return value;
                    });
                    fragment.append(document.createTextNode(text.slice(cursor)));
                    child.replaceWith(fragment);
                } else if (child.nodeType === Node.ELEMENT_NODE && child.tagName !== 'MARK') {
                    visit(child);
                }
            });
        };
        visit(container);
        return matches;
    }

    function clearHighlights() {
        elements.flow.querySelectorAll('mark').forEach((mark) => {
            mark.replaceWith(document.createTextNode(mark.textContent || ''));
        });
        elements.flow.normalize();
    }

    function searchDocument() {
        if (!state.detail) return;
        const query = elements.documentSearch.value.trim();
        clearHighlights();
        const matches = highlightText(elements.flow, query);
        elements.searchResult.textContent = query
            ? matches ? `整本文档找到 ${matches} 处匹配。` : '整本文档没有匹配内容。'
            : '输入关键词后定位文本。';
        paginateDocument({ focusContent: false });
        if (matches) {
            requestAnimationFrame(() => {
                const firstMatch = elements.flow.querySelector('mark');
                if (!firstMatch) return;
                const target = Math.floor(firstMatch.offsetLeft / elements.pages.clientWidth);
                goToSpread(target, { behavior: 'auto', saveProgress: false, focusContent: false });
            });
        }
    }

    function savePreferences() {
        api('/api/reading/preferences', {
            method: 'PUT', body: JSON.stringify(state.preferences),
        }).catch(() => {});
    }

    const soundSources = { rain: '/static/audio/rain.mp3', stream: '/static/audio/stream.mp3', snow: '/static/audio/snow.mp3' };

    function updateAudioUI() {
        const isPlaying = !elements.audio.paused;
        const container = document.querySelector('.reading-sound-options');
        if (container) container.classList.toggle('is-playing', isPlaying);
        elements.soundShortcut.setAttribute('aria-pressed', String(isPlaying));
    }

    function toggleSoundTrack(track) {
        if (state.preferences.sound_track === track && !elements.audio.paused) {
            elements.audio.pause();
        } else {
            if (state.preferences.sound_track !== track) {
                state.preferences.sound_track = track;
                elements.audio.src = soundSources[track];
                document.querySelectorAll('[data-reading-sound]').forEach((button) => {
                    button.classList.toggle('is-active', button.dataset.readingSound === track);
                });
                savePreferences();
            }
            elements.audio.play().catch(() => {});
        }
    }

    function bindEvents() {
        [elements.importButton, document.querySelector('[data-reading-import]')].forEach((button) => {
            if (button) button.addEventListener('click', openImport);
        });
        elements.search.addEventListener('input', renderLibrary);
        elements.sort.addEventListener('change', renderLibrary);
        elements.continueButton.addEventListener('click', () => {
            const documentId = elements.continueCard.dataset.documentId;
            if (documentId) openDocument(documentId);
        });
        elements.importDialog.querySelectorAll('[data-reading-import-close]').forEach((button) => button.addEventListener('click', closeImport));
        elements.importDialog.addEventListener('cancel', (event) => { event.preventDefault(); closeImport(); });
        elements.importDialog.addEventListener('close', () => {
            if (state.importTrigger && state.importTrigger.isConnected) state.importTrigger.focus({ preventScroll: true });
            state.importTrigger = null;
        });
        elements.fileInput.addEventListener('change', () => importFile(elements.fileInput.files[0]));
        ['dragenter', 'dragover'].forEach((type) => elements.dropzone.addEventListener(type, (event) => {
            event.preventDefault();
            elements.dropzone.classList.add('is-dragging');
        }));
        ['dragleave', 'drop'].forEach((type) => elements.dropzone.addEventListener(type, (event) => {
            event.preventDefault();
            elements.dropzone.classList.remove('is-dragging');
        }));
        elements.dropzone.addEventListener('drop', (event) => importFile(event.dataTransfer.files[0]));
        document.querySelector('[data-reading-exit]').addEventListener('click', () => exitReader());
        document.querySelector('[data-reading-prev]').addEventListener('click', () => goToSpread(state.spreadIndex - 1));
        document.querySelector('[data-reading-next]').addEventListener('click', () => goToSpread(state.spreadIndex + 1));
        document.querySelectorAll('[data-reading-panel]').forEach((button) => {
            button.addEventListener('click', (event) => {
                if (event.pointerType === 'mouse') return;
                openPanel(button.dataset.readingPanel);
            });
            button.addEventListener('pointerenter', (event) => {
                if (event.pointerType !== 'mouse') return;
                cancelPanelClose();
                if (state.panel !== button.dataset.readingPanel || panelElement(button.dataset.readingPanel).hidden) {
                    openPanel(button.dataset.readingPanel);
                }
            });
            button.addEventListener('pointerleave', (event) => {
                if (event.pointerType === 'mouse') schedulePanelClose();
            });
        });
        document.querySelectorAll('.reading-panel').forEach((panel) => {
            panel.addEventListener('pointerenter', (event) => {
                if (event.pointerType === 'mouse') cancelPanelClose();
            });
            panel.addEventListener('pointerleave', (event) => {
                if (event.pointerType === 'mouse') schedulePanelClose();
            });
        });
        document.querySelectorAll('[data-reading-panel-close]').forEach((button) => button.addEventListener('click', closePanels));
        document.querySelectorAll('[data-reading-theme]').forEach((button) => button.addEventListener('click', () => applyTheme(button.dataset.readingTheme)));
        document.querySelectorAll('[data-reading-layout]').forEach((button) => button.addEventListener('click', () => applyLayout(button.dataset.readingLayout)));
        document.querySelectorAll('[data-reading-size]').forEach((button) => button.addEventListener('click', () => changeFontSize(button.dataset.readingSize)));
        document.querySelectorAll('[data-reading-sound]').forEach((button) => button.addEventListener('click', () => toggleSoundTrack(button.dataset.readingSound)));
        elements.documentSearch.addEventListener('input', searchDocument);
        elements.audio.addEventListener('play', updateAudioUI);
        elements.audio.addEventListener('pause', updateAudioUI);
        elements.fontSize.addEventListener('input', () => {
            state.preferences.font_size = Number(elements.fontSize.value);
            elements.reader.style.setProperty('--reader-font-size', `${state.preferences.font_size}px`);
            if (state.detail) paginateDocument({ focusContent: false });
            savePreferences();
        });
        elements.volume.addEventListener('input', () => {
            state.preferences.sound_volume = Number(elements.volume.value);
            elements.audio.volume = state.preferences.sound_volume;
            savePreferences();
        });
        elements.reader.addEventListener('click', (event) => {
            if (event.clientY < 92 && !state.panel) showToolbar();
        });
        document.addEventListener('keydown', (event) => {
            if (elements.reader.hidden) return;
            if (event.key === 'ArrowLeft') goToSpread(state.spreadIndex - 1);
            if (event.key === 'ArrowRight') goToSpread(state.spreadIndex + 1);
            if (event.key === 'Escape') state.panel ? closePanels() : exitReader();
            if (event.key === 'Alt') showToolbar();
        });
        window.addEventListener('popstate', () => {
            const match = window.location.pathname.match(/^\/reading(?:\/([^/]+))?\/?$/);
            const id = match && match[1] ? decodeURIComponent(match[1]) : null;
            if (id) openDocument(id, false); else exitReader(false);
        });
        window.addEventListener('resize', () => {
            if (state.detail) paginateDocument();
        });
    }

    async function loadPreferences() {
        try {
            const saved = await api('/api/reading/preferences');
            if (saved) state.preferences = { ...state.preferences, ...saved };
        } catch (_) {}
        elements.fontSize.value = state.preferences.font_size;
        elements.volume.value = state.preferences.sound_volume;
        elements.audio.volume = state.preferences.sound_volume;
        applyTheme(state.preferences.theme, false);
        applyLayout(state.preferences.layout, false);

        if (state.preferences.sound_track) {
            elements.audio.src = soundSources[state.preferences.sound_track];
            document.querySelectorAll('[data-reading-sound]').forEach((button) => {
                button.classList.toggle('is-active', button.dataset.readingSound === state.preferences.sound_track);
            });
        }
        updateAudioUI();
    }

    async function start() {
        bindEvents();
        await loadPreferences();
        await loadLibrary();
        if (state.documentId) await openDocument(state.documentId, false);
        document.dispatchEvent(new CustomEvent('reading:route-ready', { detail: { documentId: state.documentId } }));
    }

    start();
})();
