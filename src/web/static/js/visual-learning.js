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

    function appendTeachingFields(parent, item) {
        const fields = [
            ['为什么', item.why_needed],
            ['怎么运作', item.mechanism],
            ['例子', item.example],
            ['别误解', item.misconception],
        ].filter((entry) => entry[1]);
        if (!fields.length) return;
        const list = node('dl', 'vl-teaching-fields');
        fields.forEach(([label, value]) => {
            list.appendChild(node('dt', 'vl-teaching-label', label));
            list.appendChild(node('dd', '', value));
        });
        parent.appendChild(list);
    }

    function renderLabeledItems(block, field, className, ordered) {
        const list = node(ordered ? 'ol' : 'div', className);
        (block[field] || []).forEach((item, index) => {
            const row = node(ordered ? 'li' : 'article', 'vl-labeled-item');
            if (!ordered) row.appendChild(node('span', 'vl-item-index', index + 1));
            const body = node('div', 'vl-item-body');
            body.appendChild(node('strong', '', item.label));
            body.appendChild(node('p', 'vl-item-description', item.description));
            appendTeachingFields(body, item);
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

    function comparisonKey(label) {
        return String(label || '').trim().toLowerCase();
    }

    function comparisonRows(columns) {
        const rows = [];
        const seen = new Set();
        columns.forEach((column) => {
            (column.items || []).forEach((item) => {
                const key = comparisonKey(item.label);
                if (!key || seen.has(key)) return;
                seen.add(key);
                rows.push({ key: key, label: item.label });
            });
        });
        return rows;
    }

    function renderComparisonMatrix(columns, rows) {
        const table = node('table', 'vl-comparison-matrix');
        const thead = node('thead');
        const headRow = node('tr');
        headRow.appendChild(node('th', 'vl-comparison-axis', '维度'));
        columns.forEach((column) => {
            const th = node('th', '', column.title);
            th.scope = 'col';
            headRow.appendChild(th);
        });
        thead.appendChild(headRow);
        table.appendChild(thead);

        const tbody = node('tbody');
        rows.forEach((row) => {
            const tr = node('tr');
            const rowHead = node('th', 'vl-comparison-rowhead', row.label);
            rowHead.scope = 'row';
            tr.appendChild(rowHead);
            columns.forEach((column) => {
                const match = (column.items || []).find((item) => comparisonKey(item.label) === row.key);
                const td = node('td');
                td.appendChild(node('p', '', match ? match.description : ''));
                tr.appendChild(td);
            });
            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        return table;
    }

    function renderComparison(block) {
        const columns = block.columns || [];
        const rows = comparisonRows(columns);
        if (columns.length >= 2 && rows.length >= 2) {
            return renderComparisonMatrix(columns, rows);
        }
        const grid = node('div', 'vl-comparison');
        columns.forEach((column) => {
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

    function renderPairedContrast(block) {
        const list = node('div', 'vl-paired-contrast');
        (block.pairs || []).forEach((pair) => {
            const row = node('article', 'vl-contrast-pair');
            const bad = node('section', 'vl-contrast-side vl-contrast-bad');
            bad.appendChild(node('strong', '', pair.bad_label));
            bad.appendChild(node('p', '', pair.bad_signal));
            const bridge = node('div', 'vl-contrast-bridge');
            if (pair.risk_label) bridge.title = pair.risk_label;
            bridge.appendChild(node('span', '', pair.risk_label));
            const better = node('section', 'vl-contrast-side vl-contrast-better');
            better.appendChild(node('strong', '', pair.better_label));
            if (pair.better_signal) better.appendChild(node('p', '', pair.better_signal));
            row.appendChild(bad);
            row.appendChild(bridge);
            row.appendChild(better);
            list.appendChild(row);
        });
        return list;
    }

    function renderSignalFlow(block) {
        const wrap = node('div', 'vl-signal-flow');
        const steps = node('ol', 'vl-signal-steps');
        (block.steps || []).forEach((step, index) => {
            const item = node('li', 'vl-signal-step');
            item.appendChild(node('span', 'vl-signal-index', index + 1));
            const body = node('div', 'vl-signal-body');
            body.appendChild(node('strong', '', step.label));
            body.appendChild(node('p', '', step.description));
            item.appendChild(body);
            steps.appendChild(item);
        });
        wrap.appendChild(steps);
        if (block.outcome_label) {
            wrap.appendChild(node('p', 'vl-signal-outcome', block.outcome_label));
        }
        return wrap;
    }

    function renderDecisionAxis(block) {
        const axis = node('div', 'vl-decision-axis');
        const xAxis = block.x_axis || {};
        const yAxis = block.y_axis || {};
        const head = node('div', 'vl-axis-head');
        head.appendChild(node('span', '', yAxis.high || '高'));
        head.appendChild(node('strong', '', block.title || '决策坐标'));
        axis.appendChild(head);
        const grid = node('div', 'vl-axis-grid');
        (block.quadrants || []).forEach((quadrant) => {
            const cell = node('article', `vl-axis-quadrant vl-axis-${quadrant.tone || 'neutral'}`);
            cell.dataset.axisX = quadrant.x || '';
            cell.dataset.axisY = quadrant.y || '';
            cell.appendChild(node('strong', '', quadrant.label));
            if (quadrant.description) cell.appendChild(node('p', '', quadrant.description));
            grid.appendChild(cell);
        });
        axis.appendChild(grid);
        const foot = node('div', 'vl-axis-foot');
        foot.appendChild(node('span', '', xAxis.low || '低'));
        foot.appendChild(node('span', '', yAxis.low || '低'));
        foot.appendChild(node('span', '', xAxis.high || '高'));
        axis.appendChild(foot);
        return axis;
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
                const branch = node('li', 'vl-hierarchy-branch');
                const card = node('article', 'vl-hierarchy-node');
                card.style.setProperty('--vl-depth', String(depth));
                card.appendChild(node('strong', '', item.label));
                card.appendChild(node('p', 'vl-item-description', item.description));
                appendTeachingFields(card, item);
                branch.appendChild(card);
                const children = nodesByParent.get(item.id) || [];
                if (children.length) {
                    const childList = node('ol', 'vl-hierarchy-children');
                    appendLevel(item.id, childList, depth + 1, nextVisited);
                    branch.appendChild(childList);
                }
                target.appendChild(branch);
            });
        };
        const rootList = node('ol', 'vl-hierarchy-tree');
        appendLevel('', rootList, 0, new Set());
        tree.appendChild(rootList);
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
            card.appendChild(node('p', 'vl-item-description', item.description));
            appendTeachingFields(card, item);
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
        paired_contrast: renderPairedContrast,
        signal_flow: renderSignalFlow,
        decision_axis: renderDecisionAxis,
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
        if (!continuous && options.showInlineSourceRefs === true) {
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
                if (evidence && renderOptions.showSectionEvidence === true) section.appendChild(evidence);
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

    function captureReaderScroll(container, mode, sectionId) {
        const current = container && container.querySelector
            ? container.querySelector('.vl-immersive-reader')
            : null;
        const readerSection = sectionId || 'global';
        if (
            !current
            || current.dataset.readerMode !== mode
            || current.dataset.readerSection !== readerSection
        ) {
            return null;
        }
        const body = current.querySelector('.vl-reader-body');
        const sections = current.querySelector('.vl-reader-sections');
        return {
            bodyTop: body ? body.scrollTop : 0,
            sectionsLeft: sections ? sections.scrollLeft : 0,
        };
    }

    function restoreReaderScroll(root, scrollState) {
        if (!scrollState) return;
        const body = root.querySelector('.vl-reader-body');
        if (body) body.scrollTop = scrollState.bodyTop;
        const sections = root.querySelector('.vl-reader-sections');
        if (sections) sections.scrollLeft = scrollState.sectionsLeft;
    }

    function isGeneratingStatus(status) {
        const value = String(status || '');
        return value.includes('生成中')
            || value.includes('正在请求')
            || value.includes('正在生成')
            || value.includes('正在建立')
            || value.includes('正在回查')
            || value.includes('正在校验')
            || value.includes('正在压缩')
            || value.includes('等待生成');
    }

    function readerAction(label, className, callback, options) {
        const button = node('button', className || 'vl-reader-action', label);
        button.type = 'button';
        const disabled = Boolean(options && options.disabled);
        button.disabled = disabled;
        button.setAttribute('aria-busy', disabled ? 'true' : 'false');
        if (disabled) {
            button.title = (options && options.title) || '正在生成，请稍候';
        } else if (typeof callback === 'function') {
            button.addEventListener('click', callback);
        }
        return button;
    }

    function mergedSourceRefs(documents) {
        const refs = [];
        const seen = new Set();
        documents.forEach((doc) => {
            ((doc && doc.source_refs) || []).forEach((ref) => {
                const refId = String(ref.id || '');
                if (!refId || seen.has(refId)) return;
                seen.add(refId);
                refs.push(ref);
            });
        });
        return refs;
    }

    function visualAtlasPages(document, label, idPrefix) {
        return ((document && document.pages) || []).map((page, index) => {
            const rawId = String(page.id || `${idPrefix}-${index + 1}`);
            return {
                ...page,
                id: idPrefix ? `${idPrefix}-${rawId}` : rawId,
                title: label ? `${label} · ${page.title || `第 ${index + 1} 节`}` : page.title,
            };
        });
    }

    function composeVisualAtlasDocument(data) {
        const globalOnly = data.visualScope === 'global';
        const overview = data.overview || null;
        const fullNote = globalOnly || data.fullNoteStale ? null : (data.fullNote || null);
        const pages = [
            ...visualAtlasPages(overview, '总览', 'global'),
            ...visualAtlasPages(fullNote, '逐段', ''),
        ];
        if (!pages.length) return null;
        const base = overview || fullNote || {};
        return {
            ...base,
            title: data.title || base.title || '图解学习页',
            subtitle: data.visualSubtitle || (globalOnly
                ? '这是当前合集的全局图解，用来建立宏观结构；子内容图解请进入对应内容独立查看。'
                : (fullNote
                ? '全局总览与逐段图解已合并在同一个页面中，顺着读即可完成吸收。'
                : '全局图解已生成；逐段图解可在后台继续补齐。')),
            recommended_style: base.recommended_style || 'study-notes',
            source_refs: mergedSourceRefs([overview, fullNote]),
            pages: pages,
        };
    }

    function annotateVisualAtlas(root, atlasDocument) {
        const header = root.querySelector('.vl-document-head');
        if (header) header.dataset.readerAnchor = 'global';
        const pages = atlasDocument.pages || [];
        root.querySelectorAll('.vl-page').forEach((pageNode, index) => {
            const page = pages[index] || {};
            pageNode.dataset.readerAnchor = visualPageAnchorId(page);
        });
    }

    function visualPageAnchorId(page) {
        const pageId = String((page && page.id) || '');
        if (pageId.startsWith('global-')) return 'global';
        const hasReview = ((page && page.blocks) || []).some((block) => block.type === 'review_questions');
        if (hasReview) return 'review';
        return pageId || 'global';
    }

    function visualReaderNavItems(data, atlasDocument, reviews) {
        if (!atlasDocument || data.visualScope === 'global') return [];
        const items = [{ id: 'global', title: '图解总览' }];
        const seen = new Set(['global']);
        (atlasDocument.pages || []).forEach((page, index) => {
            const targetId = visualPageAnchorId(page);
            if (!targetId || seen.has(targetId)) return;
            seen.add(targetId);
            items.push({
                id: targetId,
                title: page.title || `图解 ${index + 1}`,
            });
        });
        if ((reviews || []).length && !seen.has('review')) {
            items.push({ id: 'review', title: '复习' });
        }
        return items.length > 1 ? items : [];
    }

    function renderVisualStatusBlock(status, actionLabel, callback) {
        const empty = node('section', 'vl-reader-detail-prompt');
        const statusStr = status || '图解尚未生成';
        if (isGeneratingStatus(statusStr)) {
            empty.classList.add('is-generating');
            empty.appendChild(node('div', 'vl-spinner'));
            empty.appendChild(node('strong', '', statusStr));
            empty.appendChild(node('p', '', '生成完成后会自动补到当前页面，不需要来回切换。'));
        } else {
            empty.appendChild(node('strong', '', statusStr));
            empty.appendChild(node('p', '', '先阅读已有总览，需要更细颗粒度时再补齐逐段图解。'));
            if (typeof callback === 'function') {
                empty.appendChild(readerAction(actionLabel, 'vl-reader-primary', callback));
            }
        }
        return empty;
    }

    function renderReaderVisual(panel, data, _sectionId, options, visualAtlasDocument) {
        const atlasDocument = visualAtlasDocument || composeVisualAtlasDocument(data);
        if (atlasDocument) {
            const diagram = render(panel, atlasDocument, {
                ...options,
                readerMode: 'continuous',
            });
            diagram.classList.add('vl-diagram', 'vl-reader-visual-atlas');
            diagram.dataset.diagramRole = 'macro';
            diagram.setAttribute('data-focus-state', 'active');
            annotateVisualAtlas(diagram, atlasDocument);
            if (data.visualScope === 'global') {
                return;
            }
            if (data.fullNoteStale) {
                panel.appendChild(renderVisualStatusBlock(
                    '逐段图解正在更新，当前总览仍可阅读。',
                    '重新生成逐段图解',
                    options.onGenerateFullNote
                ));
            } else if (!data.fullNote) {
                panel.appendChild(renderVisualStatusBlock(
                    data.fullNoteStatus || '逐段图解尚未生成',
                    '生成逐段图解',
                    options.onGenerateFullNote
                ));
            }
            return;
        }

        const empty = node('div', 'vl-reader-empty');
        const statusStr = data.overviewStatus || '全局图解尚未生成';
        if (isGeneratingStatus(statusStr) || options.overviewGenerating) {
            empty.classList.add('is-generating');
            empty.appendChild(node('div', 'vl-spinner'));
            empty.appendChild(node('strong', '', statusStr));
            const skeleton = node('div', 'vl-skeleton');
            skeleton.appendChild(node('div', 'vl-skeleton-title'));
            skeleton.appendChild(node('div', 'vl-skeleton-box'));
            skeleton.appendChild(node('div', 'vl-skeleton-box'));
            empty.appendChild(skeleton);
            // Never offer a second generate click while the job is still running.
        } else {
            empty.appendChild(node('strong', '', statusStr));
            if (typeof options.onGenerateOverview === 'function') {
                empty.appendChild(readerAction('一键生成图解', 'vl-reader-primary', options.onGenerateOverview));
            }
        }
        panel.appendChild(empty);
    }

    function setReaderNavActive(root, targetId) {
        root.querySelectorAll('.vl-reader-sections button').forEach((button) => {
            const active = button.dataset.readerSectionTarget === targetId;
            button.classList.toggle('is-active', active);
            button.setAttribute('aria-current', active ? 'location' : 'false');
        });
    }

    function scrollReaderToAnchor(root, targetId) {
        const anchorId = targetId || 'global';
        root.dataset.readerSection = anchorId;
        const body = root.querySelector('.vl-reader-body');
        const target = Array.from(root.querySelectorAll('[data-reader-anchor]'))
            .find((element) => element.dataset.readerAnchor === anchorId);
        if (!body || !target) return;
        body.scrollTo({
            top: Math.max(0, target.offsetTop - 18),
            behavior: 'smooth',
        });
        setReaderNavActive(root, anchorId);
    }

    function renderImmersiveReader(container, model, options) {
        if (!container) throw new Error('VisualLearning.renderImmersiveReader requires a container');
        const data = model || {};
        const renderOptions = options || {};
        const mode = data.mode === 'visual' ? 'visual' : 'text';
        const sectionId = String(data.sectionId || '');
        const sections = data.sections || [];
        const reviews = reviewBlocksForReader(data);
        const scrollState = captureReaderScroll(container, mode, sectionId);
        const visualAtlasDocument = mode === 'visual' ? composeVisualAtlasDocument(data) : null;
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
        if (mode === 'text' && typeof renderOptions.onExportText === 'function') {
            actions.appendChild(readerAction('一键导出', '', renderOptions.onExportText));
        }
        if (mode === 'visual' && typeof renderOptions.onExport === 'function') {
            actions.appendChild(readerAction('导出 SVG', '', renderOptions.onExport));
        }
        toolbar.appendChild(actions);
        root.appendChild(toolbar);

        const navItems = mode === 'visual'
            ? visualReaderNavItems(data, visualAtlasDocument, reviews)
            : [{ id: '', title: '全局' }, ...sections];
        if (navItems.length) {
            const sectionNav = node('nav', 'vl-reader-sections');
            sectionNav.setAttribute('aria-label', mode === 'visual' ? '图解页导航' : '阅读章节');
            navItems.forEach((section) => {
                const targetId = section.id || 'global';
                const active = (sectionId || 'global') === targetId;
                const button = readerAction(section.title, active ? 'is-active' : '', () => {
                    if (mode === 'visual') scrollReaderToAnchor(root, targetId);
                    if (typeof renderOptions.onSectionChange === 'function') {
                        renderOptions.onSectionChange(section.id);
                    }
                });
                button.dataset.readerSectionTarget = section.id || 'global';
                button.setAttribute('aria-current', active ? 'location' : 'false');
                sectionNav.appendChild(button);
            });
            root.appendChild(sectionNav);
        } else {
            root.classList.add('vl-reader-no-sections');
        }

        const body = node('main', 'vl-reader-body');
        const panel = node('article', `vl-reader-panel vl-reader-panel-${mode}`);
        if (mode === 'text') {
            const section = sections.find((item) => item.id === sectionId);
            const markdown = section ? section.markdown : data.globalMarkdown;
            panel.appendChild(renderSafeMarkdown(markdown || '当前文字解读不可用。'));
        } else {
            renderReaderVisual(panel, data, sectionId, renderOptions, visualAtlasDocument);
        }
        body.appendChild(panel);
        root.appendChild(body);
        container.replaceChildren(root);
        restoreReaderScroll(root, scrollState);
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
                if (evidence && renderOptions.showSectionEvidence === true) article.appendChild(evidence);
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
