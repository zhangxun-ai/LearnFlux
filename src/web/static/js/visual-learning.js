(function () {
    'use strict';

    const THEMES = new Set(['study-notes', 'clean-lecture', 'chalkboard', 'technical-blueprint']);

    function normalizeMarkdownForReader(markdown) {
        let text = String(markdown || '').replace(/^\uFEFF/, '');
        const fenced = text.match(/^\s*```(?:markdown|md)?[ \t]*\r?\n([\s\S]*?)\r?\n```[ \t]*\s*$/i);
        if (fenced) text = fenced[1];
        const lines = text.split(/\r?\n/);
        if (lines[0] && lines[0].trim() === '---') {
            const closing = lines.findIndex((line, index) => index > 0 && line.trim() === '---');
            if (closing > 0) text = lines.slice(closing + 1).join('\n').replace(/^\n+/, '');
        }
        return text;
    }

    function createReaderState(ownerId, initialMode) {
        let currentOwner = String(ownerId || '');
        let mode = initialMode === 'visual' ? 'visual' : 'text';
        let sectionId = '';
        let generation = 1;
        return {
            snapshot: () => ({ ownerId: currentOwner, mode: mode, sectionId: sectionId }),
            setMode: (nextMode) => {
                mode = nextMode === 'visual' ? 'visual' : 'text';
                return mode;
            },
            setSection: (nextSectionId) => {
                sectionId = String(nextSectionId || '');
                return sectionId;
            },
            resetOwner: (nextOwnerId) => {
                currentOwner = String(nextOwnerId || '');
                sectionId = '';
                generation += 1;
                return generation;
            },
            invalidate: () => {
                generation += 1;
                return generation;
            },
            generation: () => generation,
            accepts: (candidateOwner, candidateGeneration) => (
                String(candidateOwner || '') === currentOwner
                && Number(candidateGeneration) === generation
            ),
        };
    }

    function node(tag, className, text) {
        const element = document.createElement(tag);
        if (className) element.className = className;
        if (text !== undefined && text !== null) element.textContent = String(text);
        return element;
    }

    function appendTextList(parent, values, className) {
        const list = node('ul', className || 'vl-text-list');
        (values || []).forEach((value) => list.appendChild(node('li', '', value)));
        parent.appendChild(list);
    }

    function renderLabeledItems(block, field, className, ordered) {
        const list = node(ordered ? 'ol' : 'div', className);
        (block[field] || []).forEach((item, index) => {
            const row = node(ordered ? 'li' : 'article', 'vl-labeled-item');
            if (!ordered) row.appendChild(node('span', 'vl-item-index', index + 1));
            const body = node('div', 'vl-item-body');
            body.appendChild(node('strong', '', item.label));
            body.appendChild(node('p', '', item.description));
            row.appendChild(body);
            list.appendChild(row);
        });
        return list;
    }

    function renderHero(block) {
        const body = node('div', 'vl-hero-summary');
        body.appendChild(node('h3', '', block.headline));
        body.appendChild(node('p', 'vl-hero-copy', block.summary));
        appendTextList(body, block.points, 'vl-key-points');
        return body;
    }

    function renderConceptChain(block) {
        return renderLabeledItems(block, 'items', 'vl-concept-chain', false);
    }

    function renderProcessFlow(block) {
        return renderLabeledItems(block, 'steps', 'vl-process-flow', true);
    }

    function renderComparison(block) {
        const grid = node('div', 'vl-comparison');
        (block.columns || []).forEach((column) => {
            const section = node('section', 'vl-comparison-column');
            section.appendChild(node('h4', '', column.title));
            (column.items || []).forEach((item) => {
                const row = node('div', 'vl-comparison-item');
                row.appendChild(node('strong', '', item.label));
                row.appendChild(node('p', '', item.description));
                section.appendChild(row);
            });
            grid.appendChild(section);
        });
        return grid;
    }

    function renderHierarchy(block) {
        const tree = node('div', 'vl-hierarchy');
        const nodesByParent = new Map();
        (block.nodes || []).forEach((item) => {
            const parent = item.parent_id || '';
            if (!nodesByParent.has(parent)) nodesByParent.set(parent, []);
            nodesByParent.get(parent).push(item);
        });
        const appendLevel = (parent, target, depth, visited) => {
            (nodesByParent.get(parent) || []).forEach((item) => {
                if (visited.has(item.id)) return;
                const nextVisited = new Set(visited);
                nextVisited.add(item.id);
                const row = node('article', 'vl-hierarchy-node');
                row.style.setProperty('--vl-depth', String(depth));
                row.appendChild(node('strong', '', item.label));
                row.appendChild(node('p', '', item.description));
                target.appendChild(row);
                appendLevel(item.id, target, depth + 1, nextVisited);
            });
        };
        appendLevel('', tree, 0, new Set());
        return tree;
    }

    function renderTimeline(block) {
        const timeline = node('ol', 'vl-timeline');
        (block.events || []).forEach((event) => {
            const item = node('li', 'vl-timeline-event');
            item.appendChild(node('time', '', event.time_label));
            item.appendChild(node('strong', '', event.label));
            item.appendChild(node('p', '', event.description));
            timeline.appendChild(item);
        });
        return timeline;
    }

    function renderConceptGrid(block) {
        const grid = node('div', 'vl-concept-grid');
        (block.items || []).forEach((item) => {
            const card = node('article', 'vl-concept-item');
            card.appendChild(node('strong', '', item.label));
            card.appendChild(node('p', '', item.description));
            grid.appendChild(card);
        });
        return grid;
    }

    function renderMindMap(block) {
        const map = node('div', 'vl-mind-map');
        map.appendChild(node('div', 'vl-mind-center', block.center_label));
        const branches = node('div', 'vl-mind-branches');
        (block.branches || []).forEach((branch) => {
            const section = node('section', 'vl-mind-branch');
            section.appendChild(node('h4', '', branch.label));
            appendTextList(section, branch.children, 'vl-mind-children');
            branches.appendChild(section);
        });
        map.appendChild(branches);
        return map;
    }

    function renderCallout(block) {
        const callout = node('aside', `vl-callout vl-callout-${block.tone || 'key'}`);
        callout.appendChild(node('p', '', block.text));
        return callout;
    }

    function renderReviewQuestions(block) {
        const list = node('div', 'vl-review-questions');
        (block.questions || []).forEach((item, index) => {
            const details = node('details', 'vl-review-question');
            details.appendChild(node('summary', '', `${index + 1}. ${item.question}`));
            details.appendChild(node('p', '', item.answer));
            list.appendChild(details);
        });
        return list;
    }

    const blockRenderers = {
        hero_summary: renderHero,
        concept_chain: renderConceptChain,
        process_flow: renderProcessFlow,
        comparison: renderComparison,
        hierarchy: renderHierarchy,
        timeline: renderTimeline,
        concept_grid: renderConceptGrid,
        mind_map: renderMindMap,
        callout: renderCallout,
        review_questions: renderReviewQuestions,
    };

    function renderReferences(block, sourceMap, options) {
        const refs = node('div', 'vl-source-refs');
        (block.source_ref_ids || []).forEach((refId) => {
            const sourceRef = sourceMap.get(refId);
            if (!sourceRef) return;
            const button = node('button', 'vl-source-ref', '查看原文');
            button.type = 'button';
            button.setAttribute('data-source-ref', refId);
            button.title = sourceRef.excerpt || '查看对应原文';
            button.addEventListener('click', () => {
                if (typeof options.onSourceRef === 'function') {
                    options.onSourceRef(refId, sourceRef);
                }
            });
            refs.appendChild(button);
        });
        return refs;
    }

    function renderBlock(block, sourceMap, options, continuous) {
        const className = `vl-block vl-block-${block.type || 'unknown'}`;
        const wrapper = continuous ? node('figure', className) : node('article', className);
        wrapper.dataset.blockId = block.id || '';
        if (block.title) {
            wrapper.appendChild(node(continuous ? 'figcaption' : 'h3', 'vl-block-title', block.title));
        }
        const renderer = blockRenderers[block.type];
        if (renderer) {
            wrapper.appendChild(renderer(block));
        } else {
            wrapper.appendChild(node('p', 'vl-unsupported', '该知识块暂不支持展示。'));
        }
        if (!continuous) {
            const references = renderReferences(block, sourceMap, options);
            if (references.childElementCount) wrapper.appendChild(references);
        }
        return wrapper;
    }

    function collectPageReferences(page, sourceMap) {
        const seen = new Set();
        const references = [];
        (page.blocks || []).forEach((block) => {
            (block.source_ref_ids || []).forEach((refId) => {
                if (seen.has(refId)) return;
                const sourceRef = sourceMap.get(refId);
                if (!sourceRef) return;
                seen.add(refId);
                references.push({
                    refId: refId,
                    sourceRef: sourceRef,
                    blockTitle: block.title || page.title,
                    summaryOnly: refId.includes(':summary:section:'),
                });
            });
        });
        return references;
    }

    function stableSectionId(page, pageIndex) {
        const suffix = String(page.id || `page-${pageIndex + 1}`)
            .toLowerCase()
            .replace(/[^a-z0-9_-]+/g, '-')
            .replace(/^-+|-+$/g, '') || `page-${pageIndex + 1}`;
        return `vl-section-${String(pageIndex + 1).padStart(2, '0')}-${suffix}`;
    }

    function renderSectionEvidence(page, sourceMap, options) {
        const references = collectPageReferences(page, sourceMap);
        if (!references.length) return null;
        const originalCount = references.filter((reference) => !reference.summaryOnly).length;
        const summaryCount = references.length - originalCount;
        const labels = [];
        if (originalCount) labels.push(`原文依据 ${originalCount}`);
        if (summaryCount) labels.push(`解读摘要 ${summaryCount}`);
        const button = node('button', 'vl-section-evidence', `查看依据（${labels.join(' · ')}）`);
        button.type = 'button';
        button.dataset.originalRefCount = String(originalCount);
        button.dataset.summaryRefCount = String(summaryCount);
        button.addEventListener('click', () => {
            if (typeof options.onSectionEvidence === 'function') {
                options.onSectionEvidence({
                    page: page,
                    references: references,
                    originalReferences: references.filter((reference) => !reference.summaryOnly),
                    summaryReferences: references.filter((reference) => reference.summaryOnly),
                }, button);
            }
        });
        return button;
    }

    function render(container, visualDocument, options) {
        if (!container) throw new Error('VisualLearning.render requires a container');
        const doc = visualDocument || {};
        const renderOptions = options || {};
        const continuous = renderOptions.readerMode === 'continuous';
        const sourceMap = new Map((doc.source_refs || []).map((ref) => [ref.id, ref]));
        const root = node(continuous ? 'article' : 'div', continuous ? 'vl-document vl-continuous-article' : 'vl-document');
        root.setAttribute('data-vl-theme', THEMES.has(doc.recommended_style) ? doc.recommended_style : 'study-notes');

        const header = node('header', 'vl-document-head');
        header.appendChild(node(continuous ? 'h1' : 'h2', '', doc.title || '视觉学习笔记'));
        if (doc.subtitle) header.appendChild(node('p', '', doc.subtitle));
        root.appendChild(header);

        (doc.pages || []).forEach((page, pageIndex) => {
            const section = node('section', 'vl-page');
            section.dataset.pageId = page.id || `page-${pageIndex + 1}`;
            section.dataset.sectionTitle = page.title || `第 ${pageIndex + 1} 节`;
            section.id = stableSectionId(page, pageIndex);
            const pageHead = node('header', 'vl-page-head');
            pageHead.appendChild(node('span', 'vl-page-number', String(pageIndex + 1).padStart(2, '0')));
            const titleWrap = node('div', 'vl-page-title');
            titleWrap.appendChild(node('h2', '', page.title));
            titleWrap.appendChild(node('p', '', page.learning_goal));
            pageHead.appendChild(titleWrap);
            section.appendChild(pageHead);
            const blocks = node('div', 'vl-block-grid');
            (page.blocks || []).forEach((block) => {
                blocks.appendChild(renderBlock(block, sourceMap, renderOptions, continuous));
            });
            section.appendChild(blocks);
            if (continuous) {
                const evidence = renderSectionEvidence(page, sourceMap, renderOptions);
                if (evidence) section.appendChild(evidence);
                const nextPage = (doc.pages || [])[pageIndex + 1];
                const transition = page.transition || (nextPage ? `接下来：${nextPage.learning_goal}` : '');
                if (transition) section.appendChild(node('p', 'vl-page-transition', transition));
            }
            root.appendChild(section);
        });

        container.replaceChildren(root);
        return root;
    }

    function summarySectionId(refId) {
        const marker = ':summary:section:';
        const index = String(refId || '').indexOf(marker);
        return index < 0 ? '' : String(refId).slice(index + marker.length);
    }

    function focusDiagram(root, sectionId) {
        const targetId = sectionId || '';
        root.dataset.focusSection = targetId || 'macro';
        root.querySelectorAll('.vl-diagram').forEach((diagram) => {
            const active = targetId
                ? diagram.dataset.diagramSection === targetId
                : diagram.dataset.diagramRole === 'macro';
            diagram.classList.toggle('is-focused', active);
            diagram.setAttribute('data-focus-state', active ? 'active' : 'inactive');
        });
        root.querySelectorAll('.vl-two-layer-section').forEach((article) => {
            const focused = Boolean(targetId) && article.dataset.sectionId === targetId;
            article.classList.toggle('is-focused', focused);
            article.setAttribute('data-focus-state', focused ? 'active' : 'inactive');
        });
    }

    function activateSection(root, sectionId, shouldScroll) {
        focusDiagram(root, sectionId);
        const target = Array.from(root.querySelectorAll('.vl-two-layer-section'))
            .find((article) => article.dataset.sectionId === sectionId);
        if (target && shouldScroll) {
            target.scrollIntoView({ block: 'start', behavior: 'smooth' });
        }
    }

    function appendInlineMarkdown(parent, value) {
        const text = String(value || '');
        const pattern = /(\*\*[^*]+\*\*|`[^`]+`)/g;
        let offset = 0;
        let match = pattern.exec(text);
        while (match) {
            if (match.index > offset) {
                parent.appendChild(document.createTextNode(text.slice(offset, match.index)));
            }
            const token = match[0];
            const inline = token.startsWith('**')
                ? node('strong', '', token.slice(2, -2))
                : node('code', '', token.slice(1, -1));
            parent.appendChild(inline);
            offset = match.index + token.length;
            match = pattern.exec(text);
        }
        if (offset < text.length) {
            parent.appendChild(document.createTextNode(text.slice(offset)));
        }
    }

    function renderSafeMarkdown(markdown) {
        const root = node('div', 'vl-original-markdown');
        let activeList = null;
        let activeListType = '';
        normalizeMarkdownForReader(markdown).split(/\r?\n/).forEach((line) => {
            if (!line.trim()) {
                activeList = null;
                activeListType = '';
                return;
            }
            const heading = line.match(/^(#{1,6})\s+(.+)$/);
            const unordered = line.match(/^\s*[-*+]\s+(.+)$/);
            const ordered = line.match(/^\s*\d+[.)]\s+(.+)$/);
            const quote = line.match(/^\s*>\s?(.*)$/);
            if (heading) {
                const element = node(`h${heading[1].length}`, '');
                appendInlineMarkdown(element, heading[2]);
                root.appendChild(element);
                activeList = null;
                activeListType = '';
            } else if (quote) {
                const element = node('blockquote', '');
                appendInlineMarkdown(element, quote[1]);
                root.appendChild(element);
                activeList = null;
                activeListType = '';
            } else if (unordered || ordered) {
                const listType = unordered ? 'ul' : 'ol';
                if (!activeList || activeListType !== listType) {
                    activeList = unordered ? node('ul', '') : node('ol', '');
                    activeListType = listType;
                    root.appendChild(activeList);
                }
                const item = node('li', '');
                appendInlineMarkdown(item, (unordered || ordered)[1]);
                activeList.appendChild(item);
            } else {
                const paragraph = node('p', '');
                appendInlineMarkdown(paragraph, line.trim());
                root.appendChild(paragraph);
                activeList = null;
                activeListType = '';
            }
        });
        return root;
    }

    function reviewBlocks(fullNote) {
        return ((fullNote && fullNote.pages) || []).flatMap((page) => (
            (page.blocks || []).filter((block) => block.type === 'review_questions')
        ));
    }

    function reviewBlocksForReader(data) {
        if (data && data.fullNoteStale) return [];
        return reviewBlocks(data && data.fullNote);
    }

    function readerAction(label, className, callback) {
        const button = node('button', className || 'vl-reader-action', label);
        button.type = 'button';
        button.addEventListener('click', callback);
        return button;
    }

    function renderReaderVisual(panel, data, sectionId, options) {
        const overview = data.overview || null;
        const fullNote = data.fullNote || null;
        if (sectionId === 'review') {
            if (data.fullNoteStale) {
                panel.appendChild(node('div', 'vl-reader-empty', '逐段图解正在更新，当前文字仍可阅读。'));
                return;
            }
            const blocks = reviewBlocksForReader(data);
            const sourceMap = new Map(((fullNote && fullNote.source_refs) || []).map((ref) => [ref.id, ref]));
            const review = node('section', 'vl-reader-review');
            review.appendChild(node('h2', '', '复习与自测'));
            blocks.forEach((block) => review.appendChild(renderBlock(block, sourceMap, options, false)));
            panel.appendChild(review);
            return;
        }
        if (!sectionId) {
            if (overview) {
                render(panel, overview, options).classList.add('vl-diagram');
            } else {
                const empty = node('div', 'vl-reader-empty');
                empty.appendChild(node('strong', '', data.overviewStatus || '全局图解尚未生成'));
                if (typeof options.onGenerateOverview === 'function') {
                    empty.appendChild(readerAction('一键生成图解', 'vl-reader-primary', options.onGenerateOverview));
                }
                panel.appendChild(empty);
            }
            return;
        }
        if (data.fullNoteStale) {
            panel.appendChild(node('div', 'vl-reader-empty', '逐段图解正在更新，当前文字仍可阅读。'));
            return;
        }
        const page = ((fullNote && fullNote.pages) || []).find((item) => item.id === sectionId);
        if (!page) {
            const empty = node('div', 'vl-reader-empty');
            empty.appendChild(node('strong', '', data.fullNoteStatus || '逐段图解尚未生成'));
            if (typeof options.onGenerateFullNote === 'function') {
                empty.appendChild(readerAction('生成逐段图解', 'vl-reader-primary', options.onGenerateFullNote));
            }
            panel.appendChild(empty);
            return;
        }
        const pageDocument = {
            ...fullNote,
            pages: [{
                ...page,
                blocks: (page.blocks || []).filter((block) => block.type !== 'review_questions'),
            }],
        };
        render(panel, pageDocument, options).classList.add('vl-diagram');
    }

    function renderImmersiveReader(container, model, options) {
        if (!container) throw new Error('VisualLearning.renderImmersiveReader requires a container');
        const data = model || {};
        const renderOptions = options || {};
        const mode = data.mode === 'visual' ? 'visual' : 'text';
        const sectionId = String(data.sectionId || '');
        const sections = data.sections || [];
        const reviews = reviewBlocksForReader(data);
        const root = node('section', 'vl-immersive-reader');
        root.dataset.readerMode = mode;
        root.dataset.readerSection = sectionId || 'global';
        root.setAttribute('data-vl-theme', THEMES.has(data.theme) ? data.theme : 'study-notes');

        const toolbar = node('header', 'vl-reader-toolbar');
        toolbar.appendChild(readerAction('返回', 'vl-reader-close', () => {
            if (typeof renderOptions.onClose === 'function') renderOptions.onClose();
        }));
        const heading = node('div', 'vl-reader-heading');
        heading.appendChild(node('span', '', data.contextLabel || '沉浸阅读'));
        heading.appendChild(node('h1', '', data.title || '学习内容'));
        toolbar.appendChild(heading);
        const tabs = node('div', 'vl-reader-mode-tabs');
        tabs.setAttribute('role', 'tablist');
        [['text', '文字解读'], ['visual', '图解']].forEach(([value, label]) => {
            const button = readerAction(label, mode === value ? 'is-active' : '', () => {
                if (typeof renderOptions.onModeChange === 'function') renderOptions.onModeChange(value);
            });
            button.setAttribute('role', 'tab');
            button.setAttribute('aria-selected', mode === value ? 'true' : 'false');
            tabs.appendChild(button);
        });
        toolbar.appendChild(tabs);
        const actions = node('div', 'vl-reader-actions');
        if (mode === 'visual' && typeof renderOptions.onExport === 'function') {
            actions.appendChild(readerAction('导出 SVG', '', renderOptions.onExport));
        }
        toolbar.appendChild(actions);
        root.appendChild(toolbar);

        const sectionNav = node('nav', 'vl-reader-sections');
        sectionNav.setAttribute('aria-label', '阅读章节');
        const navItems = [{ id: '', title: '全局' }, ...sections];
        if (mode === 'visual' && reviews.length) navItems.push({ id: 'review', title: '复习' });
        navItems.forEach((section) => {
            const button = readerAction(section.title, sectionId === section.id ? 'is-active' : '', () => {
                if (typeof renderOptions.onSectionChange === 'function') {
                    renderOptions.onSectionChange(section.id);
                }
            });
            button.dataset.readerSectionTarget = section.id || 'global';
            sectionNav.appendChild(button);
        });
        root.appendChild(sectionNav);

        const body = node('main', 'vl-reader-body');
        const panel = node('article', `vl-reader-panel vl-reader-panel-${mode}`);
        if (mode === 'text') {
            const section = sections.find((item) => item.id === sectionId);
            const markdown = section ? section.markdown : data.globalMarkdown;
            panel.appendChild(renderSafeMarkdown(markdown || '当前文字解读不可用。'));
        } else {
            renderReaderVisual(panel, data, sectionId, renderOptions);
        }
        body.appendChild(panel);
        root.appendChild(body);
        container.replaceChildren(root);
        return root;
    }

    function renderTopicEntries(root, overview, sections) {
        const sectionMap = new Map((sections || []).map((section) => [section.id, section]));
        const blocksById = new Map();
        root.querySelectorAll('[data-block-id]').forEach((element) => {
            blocksById.set(element.dataset.blockId, element);
        });
        (overview.pages || []).forEach((page) => {
            (page.blocks || []).forEach((block) => {
                const sectionIds = (block.source_ref_ids || [])
                    .map(summarySectionId)
                    .filter((sectionId) => sectionMap.has(sectionId));
                if (!sectionIds.length) return;
                const blockElement = blocksById.get(block.id || '');
                if (!blockElement) return;
                const entries = node('ol', 'vl-topic-entries');
                sectionIds.forEach((sectionId) => {
                    const item = node('li', 'vl-topic-entry-item');
                    const button = node('button', 'vl-topic-entry', sectionMap.get(sectionId).title);
                    button.type = 'button';
                    button.dataset.sectionTarget = sectionId;
                    button.addEventListener('click', () => {
                        activateSection(root, sectionId, true);
                    });
                    item.appendChild(button);
                    entries.appendChild(item);
                });
                blockElement.appendChild(entries);
            });
        });
    }

    function renderTwoLayer(container, layers, options) {
        if (!container) throw new Error('VisualLearning.renderTwoLayer requires a container');
        const data = layers || {};
        const renderOptions = options || {};
        const overview = data.overview || null;
        const fullNote = data.fullNote || null;
        const sections = data.sections || [];
        const recommendedTheme = (overview || fullNote || {}).recommended_style;
        const root = node('div', 'vl-two-layer');
        root.setAttribute('data-vl-theme', THEMES.has(recommendedTheme) ? recommendedTheme : 'study-notes');

        if (overview) {
            const macro = node('section', 'vl-two-layer-overview');
            macro.dataset.diagramRole = 'macro';
            render(macro, overview, renderOptions).classList.add('vl-diagram');
            macro.querySelector('.vl-document').dataset.diagramRole = 'macro';
            root.appendChild(macro);
            renderTopicEntries(root, overview, sections);
        }

        const paired = node('div', 'vl-two-layer-sections');
        const pageMap = new Map(((fullNote && fullNote.pages) || []).map((page) => [page.id, page]));
        const sourceRefs = (fullNote && fullNote.source_refs) || [];
        const sourceMap = new Map(sourceRefs.map((ref) => [ref.id, ref]));
        const reviewBlocks = [];

        const pairedSections = data.interpretationAvailable === false && fullNote
            ? (fullNote.pages || []).map((page) => ({
                id: page.id,
                title: page.title,
                markdown: '',
            }))
            : sections;
        if (data.interpretationAvailable === false && !pairedSections.length) {
            paired.appendChild(node('p', 'vl-interpretation-unavailable', '原解读已不可用'));
        } else {
            pairedSections.forEach((section) => {
                const page = pageMap.get(section.id);
                if (!page) return;
                const article = node('article', 'vl-two-layer-section');
                article.setAttribute('data-section-id', section.id);
                article.setAttribute('data-interpretation-section', section.id);
                const original = node('section', 'vl-two-layer-original');
                original.setAttribute('data-interpretation-section', section.id);
                original.tabIndex = 0;
                original.setAttribute('role', 'button');
                original.setAttribute('aria-label', `聚焦图解：${section.title}`);
                original.addEventListener('click', () => activateSection(root, section.id, false));
                original.addEventListener('keydown', (event) => {
                    if (event.key !== 'Enter' && event.key !== ' ') return;
                    event.preventDefault();
                    activateSection(root, section.id, false);
                });
                original.appendChild(node('h2', '', section.title));
                original.appendChild(data.interpretationAvailable === false
                    ? node('p', 'vl-interpretation-unavailable', '原解读已不可用')
                    : renderSafeMarkdown(section.markdown));
                article.appendChild(original);

                const visual = node('section', 'vl-two-layer-visual');
                visual.setAttribute('data-interpretation-section', section.id);
                visual.dataset.diagramSection = section.id;
                const visualPage = {
                    ...page,
                    blocks: (page.blocks || []).filter((block) => block.type !== 'review_questions'),
                };
                (page.blocks || []).filter((block) => block.type === 'review_questions')
                    .forEach((block) => reviewBlocks.push(block));
                const pageDocument = {
                    ...fullNote,
                    pages: [visualPage],
                    source_refs: sourceRefs,
                };
                const diagram = render(visual, pageDocument, renderOptions);
                diagram.classList.add('vl-diagram');
                diagram.dataset.diagramSection = section.id;
                visual.addEventListener('click', () => activateSection(root, section.id, false));
                article.appendChild(visual);
                const evidence = renderSectionEvidence(page, sourceMap, renderOptions);
                if (evidence) article.appendChild(evidence);
                paired.appendChild(article);
            });
        }
        root.appendChild(paired);

        if (reviewBlocks.length) {
            const review = node('section', 'vl-two-layer-review');
            review.appendChild(node('h2', '', '复习与自测'));
            reviewBlocks.forEach((block) => {
                review.appendChild(renderBlock(block, sourceMap, renderOptions, false));
            });
            root.appendChild(review);
        }

        container.replaceChildren(root);
        focusDiagram(root, '');
        return root;
    }

    function activeDiagram(container) {
        if (!container) return null;
        if (container.matches && container.matches('.vl-diagram')) return container;
        if (!container.querySelector) return null;
        return container.querySelector('.vl-diagram[data-focus-state="active"]')
            || container.querySelector('.vl-diagram[data-diagram-role="macro"]')
            || container.querySelector('.vl-diagram');
    }

    function setTheme(container, theme) {
        const root = container && container.matches && container.matches('.vl-document, .vl-two-layer, .vl-immersive-reader')
            ? container
            : container && container.querySelector ? container.querySelector('.vl-immersive-reader, .vl-two-layer, .vl-document') : null;
        if (!root || !THEMES.has(theme)) return false;
        root.setAttribute('data-vl-theme', theme);
        root.querySelectorAll('.vl-document').forEach((documentRoot) => {
            documentRoot.setAttribute('data-vl-theme', theme);
        });
        return true;
    }

    function inlineComputedStyles(sourceRoot, cloneRoot) {
        const sourceNodes = [sourceRoot, ...sourceRoot.querySelectorAll('*')];
        const cloneNodes = [cloneRoot, ...cloneRoot.querySelectorAll('*')];
        sourceNodes.forEach((source, index) => {
            const target = cloneNodes[index];
            if (!target) return;
            const computed = window.getComputedStyle(source);
            Array.from(computed).forEach((property) => {
                target.style.setProperty(
                    property,
                    computed.getPropertyValue(property),
                    computed.getPropertyPriority(property)
                );
            });
        });
    }

    function exportSvg(container, filename) {
        const root = container && container.matches && container.matches('.vl-document')
            ? container
            : container && container.querySelector ? container.querySelector('.vl-document') : null;
        if (!root) throw new Error('No visual document to export');
        const width = Math.max(720, Math.min(1440, root.scrollWidth || 1200));
        const height = Math.max(480, root.scrollHeight || 800);
        const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
        svg.setAttribute('width', String(width));
        svg.setAttribute('height', String(height));
        svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
        const foreignObject = document.createElementNS('http://www.w3.org/2000/svg', 'foreignObject');
        foreignObject.setAttribute('width', '100%');
        foreignObject.setAttribute('height', '100%');
        const wrapper = node('div', 'vl-export-frame');
        wrapper.setAttribute('xmlns', 'http://www.w3.org/1999/xhtml');
        const clone = root.cloneNode(true);
        inlineComputedStyles(root, clone);
        clone.style.width = `${width}px`;
        clone.style.maxWidth = 'none';
        wrapper.appendChild(clone);
        foreignObject.appendChild(wrapper);
        svg.appendChild(foreignObject);

        const xml = new XMLSerializer().serializeToString(svg);
        const blob = new Blob([xml], { type: 'image/svg+xml;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const anchor = node('a');
        anchor.href = url;
        anchor.download = filename || 'visual-learning.svg';
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        window.setTimeout(() => URL.revokeObjectURL(url), 0);
        return blob;
    }

    window.VisualLearning = {
        render: render,
        renderTwoLayer: renderTwoLayer,
        renderImmersiveReader: renderImmersiveReader,
        createReaderState: createReaderState,
        normalizeMarkdownForReader: normalizeMarkdownForReader,
        reviewBlocksForReader: reviewBlocksForReader,
        activeDiagram: activeDiagram,
        setTheme: setTheme,
        exportSvg: exportSvg,
    };
})();
