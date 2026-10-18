(function (global) {
    'use strict';

    if (!global || global.LearnFluxAuth) return;

    var SESSION_ENDPOINT = '/api/auth/session';
    var SESSION_PLACEHOLDER = '__learnflux_browser_session__';
    var LEGACY_ENCRYPTION_KEY = 'vta_encrypt_key_2024';
    var LEGACY_KEYS = [
        'vta_bearer_token',
        'vta_settings_token',
        'vta_api_key_persist',
        'vta_api_key',
        'api_key'
    ];
    var SAFE_METHODS = { GET: true, HEAD: true, OPTIONS: true };
    var nativeFetch = typeof global.fetch === 'function' ? global.fetch.bind(global) : null;
    var NativeXHR = global.XMLHttpRequest;
    var state = {
        status: 'checking',
        authenticated: false,
        csrfToken: '',
        expiresAt: '',
        user: null
    };
    var authScriptSearch = '';
    if (global.document && global.document.currentScript) {
        try {
            authScriptSearch = new global.URL(
                global.document.currentScript.src,
                global.location && global.location.href
            ).search;
        } catch (error) {
            authScriptSearch = '';
        }
    }

    function ensureAuthGateStyles() {
        if (!global.document || !global.document.head) return;
        if (global.document.getElementById('learnflux-auth-gate-styles')) return;
        var link = global.document.createElement('link');
        link.id = 'learnflux-auth-gate-styles';
        link.rel = 'stylesheet';
        link.href = '/static/css/auth-gate.css' + authScriptSearch;
        global.document.head.appendChild(link);
    }

    ensureAuthGateStyles();

    function snapshot() {
        return {
            status: state.status,
            authenticated: state.authenticated,
            expires_at: state.expiresAt,
            user: state.user
        };
    }

    function emitChange() {
        if (typeof global.dispatchEvent !== 'function' || typeof global.CustomEvent !== 'function') return;
        global.dispatchEvent(new global.CustomEvent('learnflux:authchange', {
            detail: snapshot()
        }));
    }

    function applyAuthenticated(payload) {
        state.status = 'authenticated';
        state.authenticated = true;
        state.csrfToken = String(payload && payload.csrf_token || '');
        state.expiresAt = String(payload && payload.expires_at || '');
        state.user = payload && payload.user ? payload.user : null;
        emitChange();
        return snapshot();
    }

    function applyUnauthenticated() {
        state.status = 'unauthenticated';
        state.authenticated = false;
        state.csrfToken = '';
        state.expiresAt = '';
        state.user = null;
        emitChange();
        return snapshot();
    }

    function storageValue(storage, key) {
        try {
            return storage && storage.getItem ? storage.getItem(key) : null;
        } catch (error) {
            return null;
        }
    }

    function removeStorageValue(storage, key) {
        try {
            if (storage && storage.removeItem) storage.removeItem(key);
        } catch (error) {
            // Storage can be unavailable in private or sandboxed contexts.
        }
    }

    function clearLegacyCredentials() {
        LEGACY_KEYS.forEach(function (key) {
            removeStorageValue(global.localStorage, key);
            removeStorageValue(global.sessionStorage, key);
        });
    }

    function decodeLegacyValue(rawValue) {
        var raw = String(rawValue || '').trim();
        if (!raw) return '';
        try {
            var reversed = raw.split('').reverse().join('');
            var decoded = decodeURIComponent(escape(global.atob(reversed)));
            if (decoded.indexOf(LEGACY_ENCRYPTION_KEY) >= 0) {
                return decoded.replace(LEGACY_ENCRYPTION_KEY, '').trim();
            }
        } catch (error) {
            // Legacy settings/history keys were stored as plain text.
        }
        return raw;
    }

    function takeLegacyCredential() {
        var storages = [global.localStorage, global.sessionStorage];
        for (var keyIndex = 0; keyIndex < LEGACY_KEYS.length; keyIndex += 1) {
            for (var storageIndex = 0; storageIndex < storages.length; storageIndex += 1) {
                var raw = storageValue(storages[storageIndex], LEGACY_KEYS[keyIndex]);
                var decoded = decodeLegacyValue(raw);
                if (decoded) return decoded;
            }
        }
        return '';
    }

    async function parsePayload(response) {
        try {
            return await response.json();
        } catch (error) {
            return {};
        }
    }

    function errorMessage(payload, fallback) {
        var detail = payload && payload.detail;
        if (typeof detail === 'string') return detail;
        if (detail && typeof detail.message === 'string') return detail.message;
        return payload && payload.message || fallback;
    }

    async function exchangeManagementToken(managementToken) {
        if (!nativeFetch) throw new Error('Browser fetch API is unavailable');
        var response = await nativeFetch(SESSION_ENDPOINT, {
            method: 'POST',
            credentials: 'same-origin',
            cache: 'no-store',
            headers: {
                'Accept': 'application/json',
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ management_token: managementToken })
        });
        var payload = await parsePayload(response);
        if (!response.ok || !payload.authenticated) {
            var error = new Error(errorMessage(payload, '管理口令无效'));
            error.status = response.status;
            throw error;
        }
        clearLegacyCredentials();
        return applyAuthenticated(payload);
    }

    async function initialize() {
        if (!nativeFetch) return applyUnauthenticated();
        try {
            var response = await nativeFetch(SESSION_ENDPOINT, {
                method: 'GET',
                credentials: 'same-origin',
                cache: 'no-store',
                headers: { 'Accept': 'application/json' }
            });
            if (response.ok) {
                var existing = await parsePayload(response);
                clearLegacyCredentials();
                return applyAuthenticated(existing);
            }
        } catch (error) {
            // A legacy credential can still be exchanged after a transient GET failure.
        }

        var legacyCredential = takeLegacyCredential();
        // Remove both valid and stale reversible credentials after this one-time read.
        clearLegacyCredentials();
        if (!legacyCredential) return applyUnauthenticated();
        try {
            return await exchangeManagementToken(legacyCredential);
        } catch (error) {
            return applyUnauthenticated();
        }
    }

    var ready = initialize();
    var reconnectPromise = null;

    function isLocalPage() {
        var host = global.location && global.location.hostname;
        return host === 'localhost' || host === '127.0.0.1' || host === '[::1]';
    }

    function reconnectLocalSession() {
        if (!isLocalPage() || !nativeFetch) return Promise.resolve(false);
        if (reconnectPromise) return reconnectPromise;
        reconnectPromise = (async function () {
            var response = await nativeFetch(SESSION_ENDPOINT, {
                method: 'GET', credentials: 'same-origin', cache: 'no-store',
                headers: { 'Accept': 'application/json' }
            });
            var payload = await parsePayload(response);
            if (response.ok && payload.authenticated) {
                applyAuthenticated(payload);
                return true;
            }
            if (response.status === 401) {
                applyUnauthenticated();
                return false;
            }
            var error = new Error(errorMessage(payload, '无法连接 LearnFlux'));
            error.status = response.status;
            throw error;
        })().finally(function () { reconnectPromise = null; });
        return reconnectPromise;
    }

    async function login(managementToken) {
        var token = String(managementToken || '').trim();
        if (!token) throw new Error('请输入管理口令');
        state.status = 'authenticating';
        try {
            return await exchangeManagementToken(token);
        } catch (error) {
            applyUnauthenticated();
            throw error;
        }
    }

    async function logout() {
        await ready;
        if (!nativeFetch || !state.authenticated) {
            clearLegacyCredentials();
            return applyUnauthenticated();
        }
        var response = await nativeFetch(SESSION_ENDPOINT, {
            method: 'DELETE',
            credentials: 'same-origin',
            cache: 'no-store',
            headers: {
                'Accept': 'application/json',
                'X-CSRF-Token': state.csrfToken
            }
        });
        if (!response.ok && response.status !== 401) {
            var payload = await parsePayload(response);
            var error = new Error(errorMessage(payload, '退出登录失败'));
            error.status = response.status;
            throw error;
        }
        clearLegacyCredentials();
        return applyUnauthenticated();
    }

    var gateRuntime = {
        dialog: null,
        elements: null,
        promise: null,
        resolve: null,
        reject: null,
        opener: null,
        submitting: false
    };

    function authGateCancellation() {
        var error = new Error('认证已取消');
        error.name = 'AuthGateCancelledError';
        error.code = 'AUTH_GATE_CANCELLED';
        return error;
    }

    function authErrorMessage(error) {
        var status = Number(error && error.status || 0);
        var message = String(error && error.message || '');
        if (status === 401) {
            if (/会话.*(?:过期|无效)|未提供授权令牌/.test(message)) {
                return '浏览器会话已过期，请重新连接。';
            }
            if (/管理口令|授权令牌无效|认证失败/.test(message)) {
                return '管理口令不正确，请重新输入。';
            }
            return '当前请求尚未认证，请连接后重试。';
        }
        if (status === 403) return '当前页面的安全校验已失效，请刷新后重试。';
        if (!status) return '无法连接 LearnFlux，请检查网络后重试。';
        return message || '认证失败，请稍后重试。';
    }

    function currentReturnURL() {
        if (!global.location) return '/';
        return String(global.location.pathname || '/')
            + String(global.location.search || '')
            + String(global.location.hash || '');
    }

    function waitForDocumentBody() {
        if (global.document && global.document.body) return Promise.resolve();
        return new Promise(function (resolve) {
            if (!global.document) return resolve();
            global.document.addEventListener('DOMContentLoaded', resolve, { once: true });
        });
    }

    function createGateElement(tagName, className, text) {
        var element = global.document.createElement(tagName);
        if (className) element.className = className;
        if (text !== undefined) element.textContent = text;
        return element;
    }

    function settleGate(error, authState) {
        var resolve = gateRuntime.resolve;
        var reject = gateRuntime.reject;
        var dialog = gateRuntime.dialog;
        var opener = gateRuntime.opener;
        gateRuntime.promise = null;
        gateRuntime.resolve = null;
        gateRuntime.reject = null;
        gateRuntime.opener = null;
        gateRuntime.submitting = false;
        if (dialog && dialog.open) dialog.close();
        if (opener && typeof opener.focus === 'function') {
            global.setTimeout(function () { opener.focus(); }, 0);
        }
        if (error) {
            if (reject) reject(error);
        } else if (resolve) {
            resolve(authState || snapshot());
        }
    }

    function cancelGate() {
        if (!gateRuntime.promise || gateRuntime.submitting) return;
        settleGate(authGateCancellation());
    }

    function ensureAuthGateDialog() {
        if (gateRuntime.dialog && gateRuntime.dialog.isConnected) return gateRuntime.dialog;
        if (!global.document || !global.document.body) return null;

        var dialog = createGateElement('dialog', 'lf-auth-gate');
        dialog.setAttribute('aria-labelledby', 'lf-auth-gate-title');
        dialog.setAttribute('aria-describedby', 'lf-auth-gate-description');

        var form = createGateElement('form', 'lf-auth-gate-card lf-auth-gate-form');
        form.method = 'dialog';
        var closeButton = createGateElement('button', 'lf-auth-gate-close', '×');
        closeButton.type = 'button';
        closeButton.setAttribute('aria-label', '关闭管理口令窗口');

        var header = createGateElement('header', 'lf-auth-gate-header');
        var kicker = createGateElement('p', 'lf-auth-gate-kicker', '安全会话');
        var title = createGateElement('h2', 'lf-auth-gate-title', '连接 LearnFlux');
        title.id = 'lf-auth-gate-title';
        var description = createGateElement(
            'p',
            'lf-auth-gate-description',
            '输入部署时设置的管理口令，继续当前操作。'
        );
        description.id = 'lf-auth-gate-description';
        header.append(kicker, title, description);

        var field = createGateElement('div', 'lf-auth-gate-field');
        var label = createGateElement('label', 'lf-auth-gate-label', '管理口令');
        label.htmlFor = 'lf-auth-gate-input';
        var input = createGateElement('input', 'lf-auth-gate-input');
        input.id = 'lf-auth-gate-input';
        input.name = 'management-token';
        input.type = 'password';
        input.required = true;
        input.autocomplete = 'current-password';
        input.placeholder = '输入管理口令';
        var hint = createGateElement(
            'p',
            'lf-auth-gate-hint',
            '口令只用于建立短期 HttpOnly 会话，不会保存在浏览器存储中。'
        );
        field.append(label, input, hint);

        var status = createGateElement('p', 'lf-auth-gate-status');
        status.setAttribute('aria-live', 'polite');
        var settingsLink = createGateElement('a', 'lf-auth-gate-settings-link', '管理口令在哪里设置？');
        settingsLink.href = '/settings?return_to=' + encodeURIComponent(currentReturnURL());

        var actions = createGateElement('div', 'lf-auth-gate-actions');
        var cancelButton = createGateElement('button', 'lf-auth-gate-secondary', '取消');
        cancelButton.type = 'button';
        var submitButton = createGateElement('button', 'lf-auth-gate-primary', '连接并继续');
        submitButton.type = 'submit';
        actions.append(cancelButton, submitButton);

        form.append(closeButton, header, field, status, settingsLink, actions);
        dialog.appendChild(form);
        global.document.body.appendChild(dialog);

        closeButton.addEventListener('click', cancelGate);
        cancelButton.addEventListener('click', cancelGate);
        dialog.addEventListener('cancel', function (event) {
            event.preventDefault();
            cancelGate();
        });
        dialog.addEventListener('close', function () {
            if (gateRuntime.promise && !gateRuntime.submitting) cancelGate();
        });
        input.addEventListener('input', function () { status.textContent = ''; });
        form.addEventListener('submit', async function (event) {
            event.preventDefault();
            var managementToken = input.value.trim();
            if (!managementToken || gateRuntime.submitting) return;
            gateRuntime.submitting = true;
            submitButton.disabled = true;
            submitButton.textContent = '正在连接…';
            status.textContent = '';
            try {
                var authState = await login(managementToken);
                input.value = '';
                settleGate(null, authState);
            } catch (error) {
                gateRuntime.submitting = false;
                status.textContent = authErrorMessage(error);
                input.select();
            } finally {
                submitButton.disabled = false;
                submitButton.textContent = '连接并继续';
            }
        });

        gateRuntime.dialog = dialog;
        gateRuntime.elements = {
            title: title,
            description: description,
            input: input,
            status: status,
            submit: submitButton
        };
        return dialog;
    }

    async function requireSession(options) {
        await ready;
        // An open page may still hold a CSRF token from before a service restart.
        // Check locally before opening the login dialog or sending an upload.
        if (isLocalPage()) await reconnectLocalSession();
        if (state.authenticated) return snapshot();
        if (gateRuntime.promise) return gateRuntime.promise;
        if (!global.document) {
            var unavailable = new Error('Browser authentication UI is unavailable');
            unavailable.code = 'AUTH_GATE_UNAVAILABLE';
            throw unavailable;
        }
        await waitForDocumentBody();
        ensureAuthGateStyles();
        var dialog = ensureAuthGateDialog();
        if (!dialog) throw new Error('Browser authentication UI is unavailable');

        var config = options || {};
        gateRuntime.elements.title.textContent = config.title || '连接 LearnFlux';
        gateRuntime.elements.description.textContent = config.reason
            || '输入部署时设置的管理口令，继续当前操作。';
        gateRuntime.elements.status.textContent = '';
        gateRuntime.elements.submit.textContent = config.submitLabel || '连接并继续';
        gateRuntime.opener = global.document.activeElement;
        gateRuntime.promise = new Promise(function (resolve, reject) {
            gateRuntime.resolve = resolve;
            gateRuntime.reject = reject;
        });
        if (typeof dialog.showModal === 'function') dialog.showModal();
        else dialog.setAttribute('open', '');
        global.setTimeout(function () { gateRuntime.elements.input.focus(); }, 0);
        return gateRuntime.promise;
    }

    function renderAuthGate(container, options) {
        if (!container || !global.document) return function () {};
        var config = options || {};
        var completed = false;
        var card = createGateElement('section', 'lf-auth-required');
        card.setAttribute('aria-labelledby', config.labelId || 'lf-auth-required-title');
        var icon = createGateElement('span', 'lf-auth-required-icon', '⌁');
        icon.setAttribute('aria-hidden', 'true');
        var title = createGateElement('h2', '', config.title || '连接后继续');
        title.id = config.labelId || 'lf-auth-required-title';
        var description = createGateElement(
            'p',
            '',
            config.reason || '输入管理口令建立安全会话，即可使用此功能。'
        );
        var button = createGateElement('button', 'lf-auth-required-action', config.actionLabel || '连接管理会话');
        button.type = 'button';
        card.append(icon, title, description, button);
        container.replaceChildren(card);

        async function complete() {
            if (completed) return;
            completed = true;
            card.remove();
            if (typeof config.onAuthenticated === 'function') {
                await config.onAuthenticated(snapshot());
            }
        }
        async function openGate() {
            try {
                await requireSession({ title: config.dialogTitle, reason: config.reason });
                await complete();
            } catch (error) {
                if (error && error.code !== 'AUTH_GATE_CANCELLED') {
                    description.textContent = authErrorMessage(error);
                }
            }
        }
        function onAuthChange(event) {
            if (event && event.detail && event.detail.authenticated) complete();
        }
        button.addEventListener('click', openGate);
        global.addEventListener('learnflux:authchange', onAuthChange);
        if (state.authenticated) complete();
        return function () {
            completed = true;
            global.removeEventListener('learnflux:authchange', onAuthChange);
            if (card.isConnected) card.remove();
        };
    }

    async function guard(action, options) {
        await requireSession(options);
        return action();
    }

    function getTokenPlaceholder() {
        return state.authenticated ? SESSION_PLACEHOLDER : '';
    }

    function isSameOrigin(input) {
        try {
            var rawUrl = typeof global.Request === 'function' && input instanceof global.Request
                ? input.url
                : String(input);
            return new global.URL(rawUrl, global.location.href).origin === global.location.origin;
        } catch (error) {
            return false;
        }
    }

    function isSessionAuthorization(value) {
        return String(value || '').trim() === 'Bearer ' + SESSION_PLACEHOLDER;
    }

    if (nativeFetch && typeof global.Headers === 'function') {
        global.fetch = async function authAwareFetch(input, init) {
            var options = init ? Object.assign({}, init) : {};
            if (!isSameOrigin(input)) return nativeFetch(input, options);

            var requestUrl = typeof global.Request === 'function' && input instanceof global.Request
                ? input.url
                : String(input);
            var parsedUrl = new global.URL(requestUrl, global.location.href);
            if (parsedUrl.pathname === SESSION_ENDPOINT) {
                return nativeFetch(input, options);
            }

            await ready;
            var requestHeaders = typeof global.Request === 'function' && input instanceof global.Request
                ? input.headers
                : undefined;
            var headers = new global.Headers(options.headers || requestHeaders || {});
            var authorization = headers.get('Authorization');
            if (isSessionAuthorization(authorization)) {
                headers.delete('Authorization');
                authorization = '';
            }
            var method = String(
                options.method
                || (typeof global.Request === 'function' && input instanceof global.Request ? input.method : 'GET')
                || 'GET'
            ).toUpperCase();
            if (state.authenticated && !authorization && !SAFE_METHODS[method]) {
                headers.set('X-CSRF-Token', state.csrfToken);
            }
            options.headers = headers;
            options.credentials = 'same-origin';
            var retryInput = input;
            var replayable = !(typeof global.ReadableStream === 'function'
                && options.body instanceof global.ReadableStream);
            if (isLocalPage() && !authorization && typeof global.Request === 'function'
                && input instanceof global.Request) {
                try { retryInput = input.clone(); }
                catch (error) { replayable = false; }
            }
            var response = await nativeFetch(input, options);
            if (response.status === 401 && !authorization) {
                if (isLocalPage()) {
                    var recovered = await reconnectLocalSession();
                    // A 401 is rejected by authentication before the handler runs.
                    // Replay at most once, with the new CSRF token and same body.
                    if (recovered && replayable) {
                        if (!SAFE_METHODS[method]) headers.set('X-CSRF-Token', state.csrfToken);
                        response = await nativeFetch(retryInput, options);
                    }
                }
                if (response.status === 401) {
                    // A streaming upload cannot be replayed, but its session is
                    // now restored and the next attempt need not ask for a token.
                    if (isLocalPage() && state.authenticated && !replayable) return response;
                    applyUnauthenticated();
                }
            }
            return response;
        };
    }

    if (typeof NativeXHR === 'function' && NativeXHR.prototype) {
        var nativeOpen = NativeXHR.prototype.open;
        var nativeSetRequestHeader = NativeXHR.prototype.setRequestHeader;
        var nativeSend = NativeXHR.prototype.send;
        var nativeAbort = NativeXHR.prototype.abort;

        NativeXHR.prototype.open = function authAwareOpen(method, url) {
            this.__learnfluxAuth = {
                method: String(method || 'GET').toUpperCase(),
                sameOrigin: isSameOrigin(url),
                bearer: false,
                aborted: false
            };
            return nativeOpen.apply(this, arguments);
        };

        NativeXHR.prototype.setRequestHeader = function authAwareSetHeader(name, value) {
            var metadata = this.__learnfluxAuth;
            if (metadata && String(name).toLowerCase() === 'authorization') {
                if (isSessionAuthorization(value)) return;
                metadata.bearer = Boolean(String(value || '').trim());
            }
            return nativeSetRequestHeader.apply(this, arguments);
        };

        NativeXHR.prototype.send = function authAwareSend(body) {
            var xhr = this;
            var metadata = xhr.__learnfluxAuth;
            if (!metadata || !metadata.sameOrigin) return nativeSend.call(xhr, body);
            ready.then(function () {
                if (metadata.aborted) return;
                xhr.withCredentials = true;
                if (state.authenticated && !metadata.bearer && !SAFE_METHODS[metadata.method]) {
                    nativeSetRequestHeader.call(xhr, 'X-CSRF-Token', state.csrfToken);
                }
                nativeSend.call(xhr, body);
            }).catch(function () {
                if (!metadata.aborted) nativeSend.call(xhr, body);
            });
        };

        NativeXHR.prototype.abort = function authAwareAbort() {
            if (this.__learnfluxAuth) this.__learnfluxAuth.aborted = true;
            return nativeAbort.apply(this, arguments);
        };
    }

    global.LearnFluxAuth = Object.freeze({
        ready: ready,
        login: login,
        logout: logout,
        requireSession: requireSession,
        renderAuthGate: renderAuthGate,
        guard: guard,
        authErrorMessage: authErrorMessage,
        isCancellation: function (error) { return Boolean(error && error.code === 'AUTH_GATE_CANCELLED'); },
        isAuthenticated: function () { return state.authenticated; },
        getTokenPlaceholder: getTokenPlaceholder,
        getState: snapshot
    });
})(typeof window !== 'undefined' ? window : globalThis);
