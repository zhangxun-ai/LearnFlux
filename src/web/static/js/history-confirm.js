(function (root) {
    'use strict';
    let active = false;

    function open(items) {
        if (active || !items?.length) return Promise.resolve(false);
        active = true;
        const doc = root.document;
        const opener = doc.activeElement;
        const dialog = doc.createElement('dialog');
        dialog.className = 'history-confirm';
        dialog.setAttribute('aria-labelledby', 'history-confirm-title');
        dialog.setAttribute('aria-describedby', 'history-confirm-description history-confirm-note');
        // Only static UI markup is inserted as HTML. Record titles stay plain text.
        dialog.innerHTML = `
            <button type="button" class="history-confirm-close" aria-label="关闭删除提示"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18"/></svg></button>
            <span class="history-confirm-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M4 7h16M9 7V4h6v3M6 7l1 14h10l1-14M10 11v6M14 11v6"/></svg></span>
            <h2 id="history-confirm-title"></h2>
            <p id="history-confirm-description">这些记录将从近期任务和历史记录中移除。</p>
            <ul class="history-confirm-records" aria-label="将要移除的记录"></ul>
            <p id="history-confirm-note"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 4 4L19 6"/></svg><span>解析结果和原始文件仍保留。</span></p>
            <div class="history-confirm-actions"><button type="button" class="history-confirm-cancel" autofocus>取消</button><button type="button" class="history-confirm-submit"></button></div>`;
        dialog.querySelector('h2').textContent = items.length === 1
            ? '删除这条历史记录？' : `删除所选的 ${items.length} 条记录？`;
        dialog.querySelector('#history-confirm-description').textContent = items.length === 1
            ? '这条记录将从近期任务和历史记录中移除。'
            : '这些记录将从近期任务和历史记录中移除。';
        const list = dialog.querySelector('ul');
        items.slice(0, 3).forEach(item => {
            const row = doc.createElement('li');
            row.textContent = item.title || '未命名记录';
            list.appendChild(row);
        });
        if (items.length > 3) {
            const rest = doc.createElement('li');
            rest.className = 'history-confirm-more';
            rest.textContent = `以及另外 ${items.length - 3} 条记录`;
            list.appendChild(rest);
        }
        dialog.querySelector('.history-confirm-submit').textContent = items.length === 1 ? '确认删除' : `删除 ${items.length} 条记录`;
        const cancel = dialog.querySelector('.history-confirm-cancel');
        const previousOverflow = doc.documentElement.style.overflow;
        return new Promise(resolve => {
            const finish = () => {
                const confirmed = dialog.returnValue === 'remove';
                dialog.remove();
                doc.documentElement.style.overflow = previousOverflow;
                active = false;
                if (opener?.isConnected) opener.focus({ preventScroll: true });
                resolve(confirmed);
            };
            dialog.addEventListener('close', finish, { once: true });
            cancel.addEventListener('click', () => dialog.close('cancel'));
            dialog.querySelector('.history-confirm-close').addEventListener('click', () => dialog.close('cancel'));
            dialog.querySelector('.history-confirm-submit').addEventListener('click', () => dialog.close('remove'));
            dialog.addEventListener('keydown', event => {
                if (event.key !== 'Tab') return;
                const buttons = [...dialog.querySelectorAll('button')];
                const first = buttons[0];
                const last = buttons[buttons.length - 1];
                if (event.shiftKey && doc.activeElement === first) {
                    event.preventDefault();
                    last.focus();
                } else if (!event.shiftKey && doc.activeElement === last) {
                    event.preventDefault();
                    first.focus();
                }
            });
            dialog.addEventListener('click', event => {
                if (event.target !== dialog) return;
                const box = dialog.getBoundingClientRect();
                if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) dialog.close('cancel');
            });
            doc.body.appendChild(dialog);
            try {
                dialog.showModal();
                doc.documentElement.style.overflow = 'hidden';
                cancel.focus({ preventScroll: true });
            } catch (error) {
                finish();
            }
        });
    }
    root.LearnFluxHistoryConfirm = { open };
}(window));
