(function (root, factory) {
    'use strict';
    const api = factory();
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
    root.ReadingFlow = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';

    const listItem = /^\s*(?:(\d+)[.)、]|([-•●▪]))\s*(.+?)\s*$/;
    const paragraphEnd = /[。！？!?；;：:]\s*$/;
    const headingEnd = /[，,、。！？!?；;：:]\s*$/;
    const isolatedMarker = /^(?:\d{1,3}|[-•●▪·])$/;

    function joinFragments(parts) {
        return parts.reduce((value, rawPart) => {
            const part = rawPart.trim();
            if (!part) return value;
            const needsSpace = /[A-Za-z0-9)]$/.test(value) && /^[A-Za-z0-9(]/.test(part);
            return value + (needsSpace ? ' ' : '') + part;
        }, '');
    }

    function pdfTextToBlocks(text, options = {}) {
        const blocks = [];
        let lines = String(text || '').split(/\r?\n/);
        if (options.promoteLeadingHeadings) {
            let cursor = 0;
            [['h1', 40], ['h2', 24]].some(([type, maxLength]) => {
                while (cursor < lines.length && !lines[cursor].trim()) cursor += 1;
                if (cursor >= lines.length) return true;
                const candidate = lines[cursor].trim();
                if (
                    candidate.length > maxLength
                    || headingEnd.test(candidate)
                    || isolatedMarker.test(candidate)
                    || listItem.test(candidate)
                ) return true;
                blocks.push({ type, text: candidate });
                cursor += 1;
                return false;
            });
            lines = lines.slice(cursor);
        }
        const paragraph = [];
        const items = [];
        const currentItem = [];
        let listKind = null;

        function flushParagraph() {
            if (!paragraph.length) return;
            blocks.push({ type: 'p', text: joinFragments(paragraph) });
            paragraph.length = 0;
        }

        function flushItem() {
            if (!currentItem.length) return;
            items.push(joinFragments(currentItem));
            currentItem.length = 0;
        }

        function flushList() {
            flushItem();
            if (listKind && items.length) blocks.push({ type: listKind, items: items.slice() });
            items.length = 0;
            listKind = null;
        }

        lines.forEach((rawLine) => {
            const line = rawLine.trim();
            if (!line) {
                flushParagraph();
                flushList();
                return;
            }
            if (isolatedMarker.test(line)) return;

            const match = listItem.exec(line);
            if (match) {
                const kind = match[1] ? 'ol' : 'ul';
                flushParagraph();
                if (listKind && listKind !== kind) flushList();
                if (!listKind) listKind = kind;
                flushItem();
                currentItem.push(match[3]);
                return;
            }

            if (listKind) {
                if (currentItem.length && paragraphEnd.test(currentItem[currentItem.length - 1])) {
                    flushList();
                } else {
                    currentItem.push(line);
                    return;
                }
            }

            paragraph.push(line);
            if (paragraphEnd.test(line)) flushParagraph();
        });

        flushParagraph();
        flushList();
        return blocks;
    }

    return { pdfTextToBlocks };
}));
