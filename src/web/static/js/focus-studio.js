(function () {
    'use strict';

    const STORAGE = {
        text: 'vta_focus_studio_text',
        inbox: 'vta_focus_studio_inbox',
        savedAt: 'vta_focus_studio_saved_at',
        mode: 'vta_focus_studio_mode',
        font: 'vta_focus_studio_font',
        size: 'vta_focus_studio_size',
        intensity: 'vta_focus_studio_intensity',
        volume: 'vta_focus_studio_volume',
        sound: 'vta_focus_studio_sound'
    };

    const state = {
        mode: localStorage.getItem(STORAGE.mode) || 'rainy',
        font: localStorage.getItem(STORAGE.font) || 'handwriting',
        size: localStorage.getItem(STORAGE.size) || 'small',
        intensity: Number(localStorage.getItem(STORAGE.intensity) || 80) / 100,
        volume: Number(localStorage.getItem(STORAGE.volume) || 40) / 100,
        sound: localStorage.getItem(STORAGE.sound) || 'rain',
        mouseX: 0.5,
        mouseY: 0.5,
        running: true
    };

    const body = document.body;
    const canvas = document.getElementById('focus-canvas');
    const editor = document.getElementById('focus-editor');
    const weatherSlider = document.getElementById('weather-slider');
    const volumeSlider = document.getElementById('volume-slider');
    const weatherValue = document.getElementById('weather-value');
    const volumeValue = document.getElementById('volume-value');
    const weatherName = document.getElementById('weather-name');
    const mixerPanel = document.querySelector('.mixer-panel');
    const soundGroup = document.querySelector('.sound-group');
    const soundCurrent = document.getElementById('sound-current');
    const soundName = document.getElementById('sound-name');
    const soundMenu = document.getElementById('sound-menu');
    const soundStart = document.getElementById('sound-start');
    const brandMode = document.getElementById('brand-mode');
    const exportButton = document.getElementById('focus-export');
    const exportMenu = document.getElementById('export-menu');
    const exportFormatButtons = document.querySelectorAll('[data-export-format]');
    const clearButton = document.getElementById('focus-clear');
    const saveStatus = document.getElementById('save-status');
    const audioImport = document.getElementById('audio-import');
    const audioFile = document.getElementById('audio-file');
    let soundCloseTimer = null;
    let exportCloseTimer = null;

    function clamp(value, min, max) {
        return Math.max(min, Math.min(max, value));
    }

    function setDataset() {
        body.dataset.mode = state.mode;
        body.dataset.font = state.font;
        body.dataset.size = state.size;
    }

    function updateMode(mode) {
        state.mode = mode;
        localStorage.setItem(STORAGE.mode, mode);
        setDataset();
        document.querySelectorAll('[data-mode]').forEach((button) => {
            const active = button.dataset.mode === mode;
            button.classList.toggle('active', active);
            button.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
        weatherName.textContent = mode === 'snowy' ? 'Snow' : 'Rain';
        brandMode.textContent = mode === 'snowy' ? 'Snowy Mode' : 'Rainy Mode';
        renderer.setMode(mode);
        if (audioEngine.currentSound === 'rain' || audioEngine.currentSound === 'snow') {
            updateSound(mode === 'snowy' ? 'snow' : 'rain');
        }
    }

    function updateFont(font) {
        state.font = font;
        localStorage.setItem(STORAGE.font, font);
        setDataset();
        document.querySelectorAll('[data-font]').forEach((button) => {
            button.classList.toggle('active', button.dataset.font === font);
        });
    }

    function updateSize(size) {
        state.size = size;
        localStorage.setItem(STORAGE.size, size);
        setDataset();
        document.querySelectorAll('[data-size]').forEach((button) => {
            button.classList.toggle('active', button.dataset.size === size);
        });
    }

    function updateIntensity(value) {
        state.intensity = clamp(value, 0, 1);
        localStorage.setItem(STORAGE.intensity, String(Math.round(state.intensity * 100)));
        weatherSlider.value = String(Math.round(state.intensity * 100));
        weatherValue.textContent = weatherSlider.value + '%';
        renderer.setIntensity(state.intensity);
        audioEngine.setIntensity(state.intensity);
    }

    function updateVolume(value) {
        state.volume = clamp(value, 0, 1);
        localStorage.setItem(STORAGE.volume, String(Math.round(state.volume * 100)));
        volumeSlider.value = String(Math.round(state.volume * 100));
        volumeValue.textContent = volumeSlider.value + '%';
        audioEngine.setVolume(state.volume);
    }

    function soundLabel(sound) {
        return {
            rain: '雨声',
            snow: '雪夜',
            ocean: '海洋',
            stream: '溪流',
            night: '夜晚',
            noise: '平衡噪声'
        }[sound] || sound;
    }

    function updateSound(sound) {
        state.sound = sound;
        localStorage.setItem(STORAGE.sound, sound);
        soundName.textContent = 'Volume';
        soundCurrent.title = '当前背景音：' + soundLabel(sound);
        document.querySelectorAll('[data-sound]').forEach((button) => {
            button.classList.toggle('active', button.dataset.sound === sound);
        });
        audioEngine.setSound(sound);
        setSoundMenuOpen(false);
    }

    function setSoundMenuOpen(open) {
        if (soundCloseTimer) {
            clearTimeout(soundCloseTimer);
            soundCloseTimer = null;
        }
        soundGroup.classList.toggle('is-open', open);
        soundMenu.classList.toggle('is-open', open);
        mixerPanel.classList.toggle('is-locked', open);
        soundCurrent.setAttribute('aria-expanded', open ? 'true' : 'false');
    }

    function scheduleSoundMenuClose() {
        if (soundCloseTimer) clearTimeout(soundCloseTimer);
        soundCloseTimer = setTimeout(() => setSoundMenuOpen(false), 260);
    }

    const renderer = (function createRenderer() {
        let gl = null;
        let program = null;
        let buffer = null;
        let uniforms = {};
        let lastRender = 0;
        let start = performance.now();
        let dpr = 1;
        let fallbackTimer = null;

        const vertexSource = `
            attribute vec2 a_position;
            void main() {
                gl_Position = vec4(a_position, 0.0, 1.0);
            }
        `;

        const fragmentSource = `
            precision highp float;
            uniform vec2 u_resolution;
            uniform vec2 u_mouse;
            uniform float u_time;
            uniform float u_mode;
            uniform float u_intensity;

            float hash(vec2 p) {
                return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123);
            }

            float softCircle(vec2 p, float radius, float feather) {
                return 1.0 - smoothstep(radius, radius + feather, length(p));
            }

            float rainCell(vec2 uv, vec2 scale, float speed, float seed) {
                vec2 g = uv * scale;
                vec2 id = floor(g);
                vec2 f = fract(g);
                float rnd = hash(id + seed);
                float fall = fract(f.y + u_time * speed + rnd);
                float x = 0.5 + (rnd - 0.5) * 0.72 + sin(u_time * 0.7 + rnd * 6.28) * 0.04;
                vec2 dropPos = vec2(x, fall);
                vec2 p = f - dropPos;
                p.x *= 1.9;
                float body = softCircle(p, 0.052 + rnd * 0.025, 0.025);
                float trail = (1.0 - smoothstep(0.0, 0.025, abs(f.x - x))) * smoothstep(0.04, 0.34, f.y - fall) * (1.0 - smoothstep(0.34, 0.72, f.y - fall));
                float shine = softCircle(p - vec2(-0.018, 0.02), 0.018, 0.018);
                return (body + trail * 0.32 + shine * 0.60) * smoothstep(0.14, 1.0, rnd);
            }

            float rain(vec2 uv) {
                float r = 0.0;
                r += rainCell(uv + vec2(0.03, 0.0), vec2(16.0, 9.0), 0.22, 1.0);
                r += rainCell(uv + vec2(-0.08, 0.12), vec2(28.0, 15.0), 0.34, 8.0) * 0.58;
                r += rainCell(uv + vec2(0.11, -0.04), vec2(46.0, 24.0), 0.48, 19.0) * 0.34;
                float streak = smoothstep(0.985, 1.0, hash(floor(vec2((uv.x - uv.y * 0.23) * 90.0, uv.y * 12.0 + u_time * 18.0))));
                return r + streak * 0.13;
            }

            float snowLayer(vec2 uv, float scale, float speed, float seed) {
                vec2 mouse = (u_mouse - 0.5) * 0.40;
                vec2 p = uv;
                p.x += sin(uv.y * 6.0 + u_time * 0.25 + seed) * 0.045;
                p += mouse * (0.035 + seed * 0.004);
                p.y += u_time * speed;
                p *= scale;
                vec2 id = floor(p);
                vec2 f = fract(p) - 0.5;
                float rnd = hash(id + seed);
                vec2 offset = vec2(rnd - 0.5, hash(id + seed + 2.8) - 0.5) * 0.58;
                return softCircle(f - offset, 0.030 + rnd * 0.022, 0.030) * smoothstep(0.08, 1.0, rnd);
            }

            float snow(vec2 uv) {
                float s = 0.0;
                s += snowLayer(uv, 11.0, 0.035, 2.0) * 0.90;
                s += snowLayer(uv + vec2(0.17, 0.0), 19.0, 0.060, 7.0) * 0.60;
                s += snowLayer(uv + vec2(-0.09, 0.21), 31.0, 0.095, 13.0) * 0.42;
                return s;
            }

            vec3 rainBackground(vec2 uv) {
                vec2 p = uv - 0.5;
                vec3 col = vec3(0.018, 0.021, 0.020);
                col += vec3(0.36, 0.31, 0.22) * exp(-length((p - vec2(0.23, 0.18)) * vec2(1.2, 1.8)) * 3.6);
                col += vec3(0.34, 0.42, 0.38) * exp(-length((p - vec2(-0.18, -0.22)) * vec2(1.5, 1.1)) * 4.0);
                col += vec3(0.20, 0.23, 0.21) * exp(-length((p - vec2(0.02, -0.02)) * vec2(0.8, 0.8)) * 2.7);
                return col;
            }

            vec3 snowBackground(vec2 uv) {
                vec2 p = uv - 0.5;
                vec3 sky = mix(vec3(0.018, 0.032, 0.046), vec3(0.18, 0.25, 0.34), uv.y);
                float valley = exp(-length((p - vec2(0.00, -0.24)) * vec2(1.1, 0.8)) * 3.4);
                float ridge = smoothstep(0.15, 0.74, uv.y + abs(p.x) * 0.48);
                vec3 col = mix(vec3(0.015, 0.026, 0.032), sky, ridge);
                col += vec3(0.18, 0.28, 0.36) * valley;
                col += vec3(0.04, 0.08, 0.10) * (1.0 - smoothstep(0.10, 0.54, uv.y));
                return col;
            }

            void main() {
                vec2 uv = gl_FragCoord.xy / max(u_resolution.xy, vec2(1.0));
                vec2 p = uv - 0.5;
                float aspect = u_resolution.x / max(u_resolution.y, 1.0);
                float vignette = 1.0 - smoothstep(0.28, 0.92, length(p * vec2(aspect, 1.0)));
                vec3 col = mix(rainBackground(uv), snowBackground(uv), u_mode);
                float weather = mix(rain(uv), snow(uv), u_mode) * (0.35 + u_intensity * 1.35);
                vec3 weatherColor = mix(vec3(0.80, 0.92, 0.96), vec3(0.90, 0.96, 1.00), u_mode);
                col += weatherColor * weather * mix(0.38, 0.82, u_mode);
                col *= 0.48 + vignette * 0.72;
                col += pow(weather, 2.0) * vec3(0.22, 0.25, 0.27);
                gl_FragColor = vec4(col, 1.0);
            }
        `;

        function compile(type, source) {
            const shader = gl.createShader(type);
            gl.shaderSource(shader, source);
            gl.compileShader(shader);
            if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
                throw new Error(gl.getShaderInfoLog(shader));
            }
            return shader;
        }

        function init() {
            try {
                gl = canvas.getContext('webgl', {
                    antialias: false,
                    alpha: false,
                    powerPreference: 'low-power',
                    preserveDrawingBuffer: true
                });
                if (!gl) throw new Error('WebGL unavailable');
                const vertex = compile(gl.VERTEX_SHADER, vertexSource);
                const fragment = compile(gl.FRAGMENT_SHADER, fragmentSource);
                program = gl.createProgram();
                gl.attachShader(program, vertex);
                gl.attachShader(program, fragment);
                gl.linkProgram(program);
                if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
                    throw new Error(gl.getProgramInfoLog(program));
                }
                gl.useProgram(program);
                buffer = gl.createBuffer();
                gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
                gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]), gl.STATIC_DRAW);
                const position = gl.getAttribLocation(program, 'a_position');
                gl.enableVertexAttribArray(position);
                gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);
                uniforms = {
                    resolution: gl.getUniformLocation(program, 'u_resolution'),
                    mouse: gl.getUniformLocation(program, 'u_mouse'),
                    time: gl.getUniformLocation(program, 'u_time'),
                    mode: gl.getUniformLocation(program, 'u_mode'),
                    intensity: gl.getUniformLocation(program, 'u_intensity')
                };
                resize();
                requestAnimationFrame(render);
            } catch (error) {
                console.error('Focus Studio WebGL failed:', error);
                fallback();
            }
        }

        function fallback() {
            let tick = 0;
            const ctx = canvas.getContext('2d');
            function paint() {
                const width = canvas.width = window.innerWidth;
                const height = canvas.height = window.innerHeight;
                const gradient = ctx.createRadialGradient(width * 0.55, height * 0.45, 40, width * 0.5, height * 0.5, Math.max(width, height));
                if (state.mode === 'snowy') {
                    gradient.addColorStop(0, '#33485f');
                    gradient.addColorStop(0.52, '#12202b');
                    gradient.addColorStop(1, '#000');
                } else {
                    gradient.addColorStop(0, '#6c7065');
                    gradient.addColorStop(0.45, '#201915');
                    gradient.addColorStop(1, '#000');
                }
                ctx.fillStyle = gradient;
                ctx.fillRect(0, 0, width, height);
                ctx.fillStyle = state.mode === 'snowy' ? 'rgba(255,255,255,.35)' : 'rgba(220,235,240,.24)';
                const count = Math.round(90 * state.intensity);
                for (let i = 0; i < count; i++) {
                    const x = (i * 73 + tick * (state.mode === 'snowy' ? 0.24 : -0.18)) % width;
                    const y = (i * 131 + tick * (state.mode === 'snowy' ? 0.42 : 1.4)) % height;
                    if (state.mode === 'snowy') {
                        ctx.beginPath();
                        ctx.arc(x, y, 1.2, 0, Math.PI * 2);
                        ctx.fill();
                    } else {
                        ctx.fillRect(x, y, 1, 10);
                    }
                }
                tick += 1;
            }
            fallbackTimer = setInterval(paint, 66);
            paint();
        }

        function resize() {
            if (!gl) return;
            const width = window.innerWidth;
            const height = window.innerHeight;
            const maxPixels = 1500000;
            dpr = Math.min(window.devicePixelRatio || 1, 1.5, Math.sqrt(maxPixels / (width * height)));
            canvas.width = Math.max(1, Math.floor(width * dpr));
            canvas.height = Math.max(1, Math.floor(height * dpr));
            canvas.style.width = width + 'px';
            canvas.style.height = height + 'px';
            gl.viewport(0, 0, canvas.width, canvas.height);
        }

        function render(now) {
            if (!gl) return;
            if (!document.hidden && state.running && now - lastRender > 33) {
                lastRender = now;
                gl.useProgram(program);
                gl.uniform2f(uniforms.resolution, canvas.width, canvas.height);
                gl.uniform2f(uniforms.mouse, state.mouseX, state.mouseY);
                gl.uniform1f(uniforms.time, (now - start) / 1000);
                gl.uniform1f(uniforms.mode, state.mode === 'snowy' ? 1 : 0);
                gl.uniform1f(uniforms.intensity, state.intensity);
                gl.drawArrays(gl.TRIANGLES, 0, 6);
            }
            requestAnimationFrame(render);
        }

        window.addEventListener('resize', resize);
        document.addEventListener('visibilitychange', () => {
            state.running = !document.hidden;
        });

        return {
            init,
            setMode: () => {},
            setIntensity: () => {},
            destroy: () => {
                if (fallbackTimer) clearInterval(fallbackTimer);
            }
        };
    })();

    const audioEngine = (function createAudioEngine() {
        let context = null;
        let master = null;
        let source = null;
        let filter = null;
        let customAudio = null;
        let customUrl = null;
        let playing = false;

        function ensureContext() {
            if (context) return context;
            const AudioContext = window.AudioContext || window.webkitAudioContext;
            if (!AudioContext) return null;
            context = new AudioContext();
            master = context.createGain();
            master.gain.value = state.volume;
            master.connect(context.destination);
            return context;
        }

        function createNoiseBuffer(duration) {
            const ctx = ensureContext();
            if (!ctx) return null;
            const length = Math.floor(ctx.sampleRate * duration);
            const buffer = ctx.createBuffer(2, length, ctx.sampleRate);
            for (let channel = 0; channel < 2; channel++) {
                const data = buffer.getChannelData(channel);
                let last = 0;
                for (let i = 0; i < length; i++) {
                    const white = Math.random() * 2 - 1;
                    last = last * 0.82 + white * 0.18;
                    data[i] = last * 0.78 + white * 0.22;
                }
            }
            return buffer;
        }

        function stopGenerated() {
            if (source) {
                try { source.stop(); } catch (e) {}
                source.disconnect();
                source = null;
            }
            if (filter) {
                filter.disconnect();
                filter = null;
            }
        }

        function stopCustom() {
            if (customAudio) {
                customAudio.pause();
                customAudio.src = '';
                customAudio = null;
            }
            if (customUrl) {
                URL.revokeObjectURL(customUrl);
                customUrl = null;
            }
        }

        function configureFilter(sound) {
            const ctx = ensureContext();
            if (!ctx) return null;
            const biquad = ctx.createBiquadFilter();
            const settings = {
                rain: ['bandpass', 820, 0.55],
                snow: ['lowpass', 620, 0.38],
                ocean: ['lowpass', 520, 0.62],
                stream: ['bandpass', 1320, 0.72],
                night: ['lowpass', 360, 0.28],
                noise: ['lowpass', 920, 0.40]
            }[sound] || ['lowpass', 700, 0.5];
            biquad.type = settings[0];
            biquad.frequency.value = settings[1];
            biquad.Q.value = settings[2];
            return biquad;
        }

        function startGenerated(sound) {
            const ctx = ensureContext();
            if (!ctx) return;
            stopGenerated();
            const buffer = createNoiseBuffer(sound === 'stream' ? 1.2 : 2.4);
            source = ctx.createBufferSource();
            source.buffer = buffer;
            source.loop = true;
            filter = configureFilter(sound);
            source.connect(filter);
            filter.connect(master);
            source.start();
        }

        function setVolume(value) {
            if (master) master.gain.setTargetAtTime(value, context.currentTime, 0.08);
            if (customAudio) customAudio.volume = value;
        }

        function setIntensity(value) {
            if (filter && context) {
                const target = state.sound === 'rain' ? 620 + value * 620 : 420 + value * 360;
                filter.frequency.setTargetAtTime(target, context.currentTime, 0.12);
            }
        }

        function setSound(sound) {
            state.sound = sound;
            audioEngine.currentSound = sound;
            if (!playing) return;
            stopCustom();
            startGenerated(sound);
            setVolume(state.volume);
            setIntensity(state.intensity);
        }

        async function play() {
            const ctx = ensureContext();
            if (!ctx) return;
            if (ctx.state === 'suspended') await ctx.resume();
            playing = true;
            soundStart.classList.add('is-playing');
            soundStart.textContent = 'Sound On';
            setSound(state.sound);
        }

        function playCustom(file) {
            if (!file) return;
            stopGenerated();
            stopCustom();
            customUrl = URL.createObjectURL(file);
            customAudio = new Audio(customUrl);
            customAudio.loop = true;
            customAudio.volume = state.volume;
            customAudio.play().then(() => {
                playing = true;
                audioEngine.currentSound = 'custom';
                soundStart.classList.add('is-playing');
                soundStart.textContent = 'Sound On';
                soundName.textContent = file.name.replace(/\.[^/.]+$/, '').slice(0, 14) || 'Custom';
            }).catch((error) => {
                console.warn('Custom audio playback blocked:', error);
            });
        }

        return {
            currentSound: state.sound,
            play,
            playCustom,
            setSound,
            setVolume,
            setIntensity
        };
    })();

    function formatClock(value) {
        if (!value) return '';
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return '';
        return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false });
    }

    function updateSaveStatus(label) {
        const savedAt = localStorage.getItem(STORAGE.savedAt);
        const clock = formatClock(savedAt);
        saveStatus.textContent = label || (clock ? 'Saved ' + clock : 'Saved');
        saveStatus.classList.add('is-fresh');
        window.setTimeout(() => saveStatus.classList.remove('is-fresh'), 900);
    }

    function persistDraft() {
        localStorage.setItem(STORAGE.text, editor.value);
        localStorage.setItem(STORAGE.savedAt, new Date().toISOString());
        updateSaveStatus();
    }

    function safeFileStamp() {
        const date = new Date();
        const pad = (value) => String(value).padStart(2, '0');
        return [
            date.getFullYear(),
            pad(date.getMonth() + 1),
            pad(date.getDate())
        ].join('-') + '-' + pad(date.getHours()) + pad(date.getMinutes());
    }

    function exportText(format) {
        const type = format === 'md' ? 'md' : 'txt';
        const content = editor.value;
        if (!content.trim()) {
            updateSaveStatus('Empty');
            return;
        }
        const mime = type === 'md' ? 'text/markdown;charset=utf-8' : 'text/plain;charset=utf-8';
        const blob = new Blob([content], { type: mime });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'focus-studio-' + safeFileStamp() + '.' + type;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
        setExportMenuOpen(false);
    }

    function clearText() {
        if (!editor.value.trim()) return;
        editor.value = '';
        localStorage.removeItem(STORAGE.text);
        localStorage.removeItem(STORAGE.savedAt);
        updateSaveStatus('Released');
        editor.focus();
    }

    function setExportMenuOpen(open) {
        if (exportCloseTimer) {
            clearTimeout(exportCloseTimer);
            exportCloseTimer = null;
        }
        exportMenu.classList.toggle('is-open', open);
        exportButton.setAttribute('aria-expanded', open ? 'true' : 'false');
    }

    function scheduleExportMenuClose() {
        if (exportCloseTimer) clearTimeout(exportCloseTimer);
        exportCloseTimer = setTimeout(() => setExportMenuOpen(false), 220);
    }

    function loadInitialText() {
        const savedText = localStorage.getItem(STORAGE.text) || '';
        const rawInbox = localStorage.getItem(STORAGE.inbox);
        if (!rawInbox) return savedText;

        localStorage.removeItem(STORAGE.inbox);
        try {
            const payload = JSON.parse(rawInbox);
            const incomingText = typeof payload.text === 'string' ? payload.text : '';
            if (!incomingText.trim()) return savedText;
            localStorage.setItem(STORAGE.text, incomingText);
            localStorage.setItem(STORAGE.savedAt, new Date().toISOString());
            return incomingText;
        } catch (error) {
            console.error('Focus Studio inbox failed:', error);
            return savedText;
        }
    }

    function bindEvents() {
        document.querySelectorAll('[data-mode]').forEach((button) => {
            button.addEventListener('click', () => updateMode(button.dataset.mode));
        });
        document.querySelectorAll('[data-font]').forEach((button) => {
            button.addEventListener('click', () => updateFont(button.dataset.font));
        });
        document.querySelectorAll('[data-size]').forEach((button) => {
            button.addEventListener('click', () => updateSize(button.dataset.size));
        });
        document.querySelectorAll('[data-sound]').forEach((button) => {
            button.addEventListener('click', () => updateSound(button.dataset.sound));
        });
        soundGroup.addEventListener('pointerenter', () => setSoundMenuOpen(true));
        soundGroup.addEventListener('pointerleave', scheduleSoundMenuClose);
        soundMenu.addEventListener('pointerenter', () => setSoundMenuOpen(true));
        soundMenu.addEventListener('pointerleave', scheduleSoundMenuClose);
        soundCurrent.addEventListener('click', (event) => {
            event.stopPropagation();
            setSoundMenuOpen(!soundMenu.classList.contains('is-open'));
        });
        document.addEventListener('click', (event) => {
            if (!event.target.closest('.sound-group')) {
                setSoundMenuOpen(false);
            }
            if (!event.target.closest('.export-group')) {
                setExportMenuOpen(false);
            }
        });
        document.addEventListener('keydown', (event) => {
            if (event.key === 'Escape') {
                setSoundMenuOpen(false);
                setExportMenuOpen(false);
            }
        });
        weatherSlider.addEventListener('input', () => updateIntensity(Number(weatherSlider.value) / 100));
        volumeSlider.addEventListener('input', () => updateVolume(Number(volumeSlider.value) / 100));
        soundStart.addEventListener('click', () => audioEngine.play());
        exportButton.addEventListener('click', (event) => {
            event.stopPropagation();
            setExportMenuOpen(!exportMenu.classList.contains('is-open'));
        });
        exportButton.parentElement.addEventListener('pointerenter', () => setExportMenuOpen(true));
        exportButton.parentElement.addEventListener('pointerleave', scheduleExportMenuClose);
        exportMenu.addEventListener('pointerenter', () => setExportMenuOpen(true));
        exportMenu.addEventListener('pointerleave', scheduleExportMenuClose);
        exportFormatButtons.forEach((button) => {
            button.addEventListener('click', () => exportText(button.dataset.exportFormat));
        });
        clearButton.addEventListener('click', clearText);
        audioImport.addEventListener('click', () => {
            setSoundMenuOpen(false);
            audioFile.click();
        });
        audioFile.addEventListener('change', () => {
            const file = audioFile.files && audioFile.files[0];
            audioEngine.playCustom(file);
        });
        editor.addEventListener('input', () => {
            persistDraft();
        });
        window.addEventListener('beforeunload', persistDraft);
        window.addEventListener('pointermove', (event) => {
            state.mouseX = event.clientX / Math.max(1, window.innerWidth);
            state.mouseY = 1 - event.clientY / Math.max(1, window.innerHeight);
        }, { passive: true });
    }

    function init() {
        setDataset();
        editor.value = loadInitialText();
        bindEvents();
        updateMode(state.mode);
        updateFont(state.font);
        updateSize(state.size);
        updateIntensity(state.intensity);
        updateVolume(state.volume);
        updateSound(state.sound);
        updateSaveStatus(editor.value.trim() ? undefined : 'Ready');
        renderer.init();
        setTimeout(() => editor.focus(), 120);
    }

    document.addEventListener('DOMContentLoaded', init);
})();
