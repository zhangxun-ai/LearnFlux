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

    // 背景音清单：kind=file 用真实录音（自托管或导入），kind=noise 用合成有色噪声。
    // 想新增一个背景音：把 mp3 放到 /static/audio/，在此加一行 { id, label, kind:'file', src }，
    // 菜单与播放会自动对应（选项即对应你上传的文件）。噪声类对标系统背景音（明亮/平衡/低沉）。
    const SOUNDS = [
        { id: 'rain',     label: '雨声',   kind: 'file',  src: '/static/audio/rain.mp3' },
        { id: 'snow',     label: '雪夜',   kind: 'file',  src: '/static/audio/snow.mp3' },
        { id: 'stream',   label: '溪流',   kind: 'file',  src: '/static/audio/stream.mp3' },
        { id: 'bright',   label: '明亮噪声', kind: 'noise', color: 'white' },
        { id: 'balanced', label: '平衡噪声', kind: 'noise', color: 'pink' },
        { id: 'dark',     label: '低沉噪声', kind: 'noise', color: 'brown' }
    ];
    const SOUND_BY_ID = Object.fromEntries(SOUNDS.map((item) => [item.id, item]));

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
    const timerToggle = document.getElementById('timer-toggle');   // 复用氛围 orb 作为番茄钟控制
    const timerTime = document.getElementById('timer-time');
    const timerPhase = document.getElementById('timer-phase');
    const timerRing = document.getElementById('timer-ring-progress');
    const timerZone = document.getElementById('mixer-zone');
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
        document.querySelectorAll('button[data-mode]').forEach((button) => {
            const active = button.dataset.mode === mode;
            button.classList.toggle('active', active);
            button.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
        weatherName.textContent = mode === 'snowy' ? 'Snow' : 'Rain';
        renderer.setMode(mode);
        if (audioEngine.currentSound === 'rain' || audioEngine.currentSound === 'snow') {
            updateSound(mode === 'snowy' ? 'snow' : 'rain');
        }
    }

    function updateFont(font) {
        state.font = font;
        localStorage.setItem(STORAGE.font, font);
        setDataset();
        document.querySelectorAll('button[data-font]').forEach((button) => {
            button.classList.toggle('active', button.dataset.font === font);
        });
    }

    function updateSize(size) {
        state.size = size;
        localStorage.setItem(STORAGE.size, size);
        setDataset();
        document.querySelectorAll('button[data-size]').forEach((button) => {
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
        return (SOUND_BY_ID[sound] && SOUND_BY_ID[sound].label) || sound;
    }

    function updateSound(sound) {
        if (!SOUND_BY_ID[sound]) sound = 'rain';
        state.sound = sound;
        localStorage.setItem(STORAGE.sound, sound);
        soundName.textContent = 'Volume';
        soundCurrent.title = '当前背景音：' + soundLabel(sound);
        document.querySelectorAll('button[data-sound]').forEach((button) => {
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
        let buffer = null;
        let scenes = null;          // { rainy, snowy } 每个含 program / uniforms / texture
        let lastRender = 0;
        let start = performance.now();
        let dpr = 1;
        let fallbackTimer = null;

        // 自托管底图：雨=车内模糊 bokeh，雪=阿尔卑斯雪湖（与目标站点同源素材）
        const TEXTURES = {
            rainy: '/static/img/focus/rain-bg.jpg',
            snowy: '/static/img/focus/snow-bg.jpg'
        };

        // 共享顶点着色器：全屏四边形，并把裁剪坐标映射成 [0,1] 的 vUv 供片元采样底图
        const VERTEX_SHADER = `
            attribute vec2 a_position;
            varying vec2 vUv;
            void main() {
                vUv = a_position * 0.5 + 0.5;
                gl_Position = vec4(a_position, 0.0, 1.0);
            }
        `;

        // 雨模式：玻璃雨痕折射（"Heartfelt" by Martijn Steinrucken / BigWIngs, Shadertoy）
        // 折射水珠对底图做位移采样 + 日间冷色分级 + 高光 + 胶片颗粒 + 暗角
        const RAIN_FRAGMENT = `
            precision highp float;
            uniform float uTime;
            uniform vec2 uResolution;
            uniform float uIntensity;
            uniform float uBlur;
            uniform sampler2D uTexture;
            varying vec2 vUv;

            #define S(a, b, t) smoothstep(a, b, t)

            vec3 N13(float p) {
                vec3 p3 = fract(vec3(p) * vec3(.1031, .11369, .13787));
                p3 += dot(p3, p3.yzx + 19.19);
                return fract(vec3((p3.x + p3.y) * p3.z, (p3.x + p3.z) * p3.y, (p3.y + p3.z) * p3.x));
            }

            float N(float t) {
                return fract(sin(t * 12345.564) * 7658.76);
            }

            float Saw(float b, float t) {
                return S(0., b, t) * S(1., b, t);
            }

            float StaticDrops(vec2 uv, float t) {
                uv *= 40.;
                vec2 id = floor(uv);
                uv = fract(uv) - .5;
                vec3 n = N13(id.x * 107.45 + id.y * 3543.654);
                vec2 p = (n.xy - .5) * .7;
                float d = length(uv - p);
                float fade = Saw(.025, fract(t + n.z));
                float c = S(.3, 0., d) * fract(n.z * 10.) * fade;
                return c;
            }

            vec2 DropLayer(vec2 uv, float t) {
                vec2 UV = uv;
                uv.y += t * 0.75;
                vec2 a = vec2(6., 1.);
                vec2 grid = a * 2.;
                vec2 id = floor(uv * grid);

                float colShift = N(id.x);
                uv.y += colShift;

                id = floor(uv * grid);
                vec3 n = N13(id.x * 35.2 + id.y * 2376.1);
                vec2 st = fract(uv * grid) - vec2(.5, 0);

                float x = n.x - .5;
                float y = UV.y * 20.;
                float wiggle = sin(y + sin(y));
                x += wiggle * (.5 - abs(x)) * (n.z - .5);
                x *= .7;
                float ti = fract(t + n.z);
                y = (Saw(.85, ti) - .5) * .9 + .5;
                vec2 p = vec2(x, y);

                float d = length((st - p) * a.yx);
                float mainDrop = S(.4, .0, d);

                float r = sqrt(S(1., y, st.y));
                float cd = abs(st.x - x);
                float trail = S(.23 * r, .15 * r * r, cd);
                float trailFront = S(-.02, .02, st.y - y);
                trail *= trailFront * r * r;

                y = UV.y;
                float trail2 = S(.2 * r, .0, cd);
                float droplets = max(0., (sin(y * (1. - y) * 120.) - st.y)) * trail2 * trailFront * n.z;
                y = fract(y * 10.) + (st.y - .5);
                float dd = length(st - vec2(x, y));
                droplets = S(.3, 0., dd);
                float m = mainDrop + droplets * r * trailFront;

                return vec2(m, trail);
            }

            vec2 Drops(vec2 uv, float t, float l0, float l1, float l2) {
                float s = StaticDrops(uv, t) * l0;
                vec2 m1 = DropLayer(uv, t) * l1;
                vec2 m2 = DropLayer(uv * 1.85, t) * l2;

                float c = s + m1.x + m2.x;
                c = S(.3, 1., c);

                return vec2(c, max(m1.y * l0, m2.y * l1));
            }

            void main() {
                vec2 uv = vUv;
                vec2 centeredUv = (uv - 0.5) * 2.0;
                float aspect = uResolution.y > 0.0 ? uResolution.x / uResolution.y : 1.0;
                centeredUv.x *= aspect;

                float t = uTime * 0.2;
                vec2 rainUv = uv * vec2(aspect, 1.0);

                float staticDrops = S(-.5, 1., uIntensity) * 2.;
                float layer1 = S(.25, .75, uIntensity);
                float layer2 = S(.0, .5, uIntensity);

                vec2 c = Drops(rainUv, t, staticDrops, layer1, layer2);

                vec2 e = vec2(.001, 0.);
                float cx = Drops(rainUv + e, t, staticDrops, layer1, layer2).x;
                float cy = Drops(rainUv + e.yx, t, staticDrops, layer1, layer2).x;
                vec2 n = vec2(cx - c.x, cy - c.x);

                vec3 col = texture2D(uTexture, uv + n).rgb;

                vec3 daytimeTint = vec3(0.75, 0.82, 0.9);
                col = mix(col, col * daytimeTint, 0.8);
                col = mix(vec3(dot(col, vec3(0.299, 0.587, 0.114))), col, 0.8);

                vec3 lightDir = normalize(vec3(-1.0, 1.0, 0.5));
                float spec = max(0.0, dot(normalize(vec3(n, 0.05)), lightDir));
                col += pow(spec, 30.0) * 0.5 * S(0.1, 0.5, c.x);

                float grain = fract(sin(dot(uv + t * 0.01, vec2(12.9898, 78.233))) * 43758.5453);
                col += (grain - 0.5) * 0.03;

                float vignette = 1.0 - length(centeredUv * 0.5);
                col *= S(0.0, 1.0, vignette);

                gl_FragColor = vec4(col, 1.0);
            }
        `;

        // 雪模式："Just snow" by Andrew Baldwin (thndl.com)
        // License: CC BY-NC-SA 3.0 (http://creativecommons.org/licenses/by-nc-sa/3.0/deed.en_US)
        // 50 层视差雪花 + 景深(DoF) + 鼠标视差，叠加在雪景底图上并做冬季冷色分级
        const SNOW_FRAGMENT = `
            precision highp float;
            uniform float uTime;
            uniform vec2 uResolution;
            uniform vec2 uMouse;
            uniform sampler2D uTexture;
            uniform float uIntensity;
            varying vec2 vUv;

            #define S(a, b, t) smoothstep(a, b, t)

            #define LAYERS 50
            #define DEPTH .5
            #define WIDTH .3
            #define SPEED .6

            void main() {
                const mat3 p = mat3(13.323122, 23.5112, 21.71123, 21.1212, 28.7312, 11.9312, 21.8112, 14.7212, 61.3934);

                vec2 uv = vUv;
                vec2 centeredUv = (uv - 0.5) * 2.0;
                float aspect = uResolution.y > 0.0 ? uResolution.x / uResolution.y : 1.0;
                centeredUv.x *= aspect;

                // 鼠标视差
                vec2 snowUv = uMouse.xy / uResolution.xy + vec2(1., uResolution.y / uResolution.x) * vUv;

                vec3 acc = vec3(0.0);
                float dof = 5. * sin(uTime * .1);

                for (int i = 0; i < LAYERS; i++) {
                    // 用强度控制实际可见的雪花层数
                    if (float(i) > float(LAYERS) * uIntensity) break;

                    float fi = float(i);
                    vec2 q = snowUv * (1. + fi * DEPTH);
                    q += vec2(q.y * (WIDTH * mod(fi * 7.238917, 1.) - WIDTH * .5), SPEED * uTime / (1. + fi * DEPTH * .03));
                    vec3 n = vec3(floor(q), 31.189 + fi);
                    vec3 m = floor(n) * .00001 + fract(n);
                    vec3 mp = (31415.9 + m) / fract(p * m);
                    vec3 r = fract(mp);
                    vec2 s = abs(mod(q, 1.) - .5 + .9 * r.xy - .45);
                    s += .01 * abs(2. * fract(10. * q.yx) - 1.);
                    float d = .6 * max(s.x - s.y, s.x + s.y) + max(s.x, s.y) - .01;
                    float edge = .005 + .05 * min(.5 * abs(fi - 5. - dof), 1.);
                    acc += vec3(smoothstep(edge, -edge, d) * (r.x / (1. + .02 * fi * DEPTH)));
                }

                // 采样雪景底图
                vec3 col = texture2D(uTexture, uv).rgb;

                // 冬季冷色分级
                vec3 winterTint = vec3(0.85, 0.9, 1.0);
                col = mix(col, col * winterTint, 0.5);

                // 叠加雪花
                col += acc * 0.8;

                // 暗角
                float vignette = 1.0 - length(centeredUv * 0.4);
                col *= S(0.0, 1.0, vignette);

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

        // 创建底图纹理：先用 1x1 占位色，图片异步加载完成后再上传（NPOT 用 CLAMP_TO_EDGE + LINEAR）
        function createTexture(url) {
            const texture = gl.createTexture();
            gl.bindTexture(gl.TEXTURE_2D, texture);
            gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array([10, 12, 16, 255]));
            gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
            gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
            gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
            gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
            const image = new Image();
            image.crossOrigin = 'anonymous';
            image.onload = () => {
                gl.bindTexture(gl.TEXTURE_2D, texture);
                gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
                gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, image);
            };
            image.onerror = () => console.warn('Focus Studio texture failed:', url);
            image.src = url;
            return texture;
        }

        // 用共享顶点着色器 + 指定片元着色器构建一套独立场景（program + uniforms + texture）
        function buildScene(fragmentSource, textureUrl) {
            const vertex = compile(gl.VERTEX_SHADER, VERTEX_SHADER);
            const fragment = compile(gl.FRAGMENT_SHADER, fragmentSource);
            const program = gl.createProgram();
            gl.attachShader(program, vertex);
            gl.attachShader(program, fragment);
            gl.linkProgram(program);
            if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
                throw new Error(gl.getProgramInfoLog(program));
            }
            return {
                program,
                position: gl.getAttribLocation(program, 'a_position'),
                uniforms: {
                    time: gl.getUniformLocation(program, 'uTime'),
                    resolution: gl.getUniformLocation(program, 'uResolution'),
                    mouse: gl.getUniformLocation(program, 'uMouse'),
                    intensity: gl.getUniformLocation(program, 'uIntensity'),
                    blur: gl.getUniformLocation(program, 'uBlur'),
                    texture: gl.getUniformLocation(program, 'uTexture')
                },
                texture: createTexture(textureUrl)
            };
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
                buffer = gl.createBuffer();
                gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
                gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]), gl.STATIC_DRAW);
                scenes = {
                    rainy: buildScene(RAIN_FRAGMENT, TEXTURES.rainy),
                    snowy: buildScene(SNOW_FRAGMENT, TEXTURES.snowy)
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
            if (!gl || !scenes) return;
            if (!document.hidden && state.running && now - lastRender > 33) {
                lastRender = now;
                const scene = state.mode === 'snowy' ? scenes.snowy : scenes.rainy;
                const u = scene.uniforms;
                gl.useProgram(scene.program);
                gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
                gl.enableVertexAttribArray(scene.position);
                gl.vertexAttribPointer(scene.position, 2, gl.FLOAT, false, 0, 0);
                if (u.time) gl.uniform1f(u.time, (now - start) / 1000);
                if (u.resolution) gl.uniform2f(u.resolution, canvas.width, canvas.height);
                if (u.mouse) gl.uniform2f(u.mouse, state.mouseX * canvas.width, state.mouseY * canvas.height);
                if (u.intensity) gl.uniform1f(u.intensity, state.intensity);
                if (u.blur) gl.uniform1f(u.blur, 0.4);
                if (u.texture) {
                    gl.activeTexture(gl.TEXTURE0);
                    gl.bindTexture(gl.TEXTURE_2D, scene.texture);
                    gl.uniform1i(u.texture, 0);
                }
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
        let source = null;        // 合成噪声源
        let customAudio = null;   // 真实录音 / 导入文件（HTMLAudioElement）
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

        // 生成 4 秒可循环的有色噪声：white=明亮、pink=平衡、brown=低沉（纯 DSP，听感对标系统背景音）
        function createNoiseBuffer(color) {
            const ctx = ensureContext();
            if (!ctx) return null;
            const length = Math.floor(ctx.sampleRate * 4);
            const buffer = ctx.createBuffer(2, length, ctx.sampleRate);
            for (let channel = 0; channel < 2; channel++) {
                const data = buffer.getChannelData(channel);
                if (color === 'pink') {
                    // Paul Kellet 粉噪声近似：能量随频率 1/f 下降，听感最"平衡"
                    let b0 = 0, b1 = 0, b2 = 0, b3 = 0, b4 = 0, b5 = 0, b6 = 0;
                    for (let i = 0; i < length; i++) {
                        const white = Math.random() * 2 - 1;
                        b0 = 0.99886 * b0 + white * 0.0555179;
                        b1 = 0.99332 * b1 + white * 0.0750759;
                        b2 = 0.96900 * b2 + white * 0.1538520;
                        b3 = 0.86650 * b3 + white * 0.3104856;
                        b4 = 0.55000 * b4 + white * 0.5329522;
                        b5 = -0.7616 * b5 - white * 0.0168980;
                        data[i] = (b0 + b1 + b2 + b3 + b4 + b5 + b6 + white * 0.5362) * 0.11;
                        b6 = white * 0.115926;
                    }
                } else if (color === 'brown') {
                    // 棕（红）噪声：白噪声积分，低频厚实、听感最"低沉"
                    let last = 0;
                    for (let i = 0; i < length; i++) {
                        const white = Math.random() * 2 - 1;
                        last = (last + 0.02 * white) / 1.02;
                        data[i] = last * 3.5;
                    }
                } else {
                    // 白噪声：全频均匀，听感最"明亮"
                    for (let i = 0; i < length; i++) {
                        data[i] = (Math.random() * 2 - 1) * 0.5;
                    }
                }
            }
            return buffer;
        }

        function stopNoise() {
            if (source) {
                try { source.stop(); } catch (e) {}
                source.disconnect();
                source = null;
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

        function startNoise(color) {
            const ctx = ensureContext();
            if (!ctx) return;
            stopNoise();
            source = ctx.createBufferSource();
            source.buffer = createNoiseBuffer(color);
            source.loop = true;
            source.connect(master);
            source.start();
        }

        // 播放真实录音（自托管或导入文件），停掉合成噪声
        function startFile(url, isObjectUrl) {
            stopNoise();
            stopCustom();
            if (isObjectUrl) customUrl = url;
            customAudio = new Audio(url);
            customAudio.loop = true;
            customAudio.volume = state.volume;
            customAudio.play().catch((error) => {
                console.warn('Focus Studio audio playback blocked:', error);
            });
        }

        function setVolume(value) {
            if (master && context) master.gain.setTargetAtTime(value, context.currentTime, 0.08);
            if (customAudio) customAudio.volume = value;
        }

        function setSound(id) {
            const sound = SOUND_BY_ID[id];
            // 已在播放同一音源则不重启，避免任何重复选择打断正在播放的背景音
            const alreadyPlaying = playing && id === audioEngine.currentSound && Boolean(customAudio || source);
            state.sound = id;
            audioEngine.currentSound = id;
            if (!playing || !sound || alreadyPlaying) return;
            if (sound.kind === 'file') {
                startFile(sound.src, false);
            } else {
                stopCustom();
                startNoise(sound.color);
            }
            setVolume(state.volume);
        }

        async function play() {
            const ctx = ensureContext();
            if (!ctx) return;
            if (ctx.state === 'suspended') await ctx.resume();
            playing = true;
            setSound(state.sound);
        }

        function pause() {
            playing = false;
            stopNoise();
            stopCustom();
        }

        function playCustom(file) {
            if (!file) return;
            playing = true;
            startFile(URL.createObjectURL(file), true);
            audioEngine.currentSound = 'custom';
            soundName.textContent = file.name.replace(/\.[^/.]+$/, '').slice(0, 14) || 'Custom';
        }

        return {
            currentSound: state.sound,
            play,
            pause,
            playCustom,
            setSound,
            setVolume,
            setIntensity: () => {},
            getContext: () => context
        };
    })();

    // 番茄钟：25 分钟专注 ↔ 5 分钟休息循环；开始即联动播放背景音，暂停/重置联动停止
    const pomodoro = (function createPomodoro() {
        const FOCUS = 25 * 60;
        const BREAK = 5 * 60;
        const RING = 2 * Math.PI * 24;   // 与 SVG 进度圆 r=24 对应的周长
        let phase = 'focus';
        let total = FOCUS;
        let remaining = FOCUS;
        let running = false;
        let interval = null;
        let sessions = 0;
        let pressTimer = null;
        let longPressed = false;

        function format(sec) {
            const m = Math.floor(sec / 60);
            const s = sec % 60;
            return String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0');
        }

        function paint() {
            timerTime.textContent = format(remaining);
            const elapsed = total > 0 ? (total - remaining) / total : 0;
            // 环随时间顺时针"填满"（与 flow-space 一致）：dashoffset 从周长降到 0，起始仅顶部圆点
            timerRing.style.strokeDashoffset = (RING * (1 - elapsed)).toFixed(2);
            timerPhase.textContent = phase === 'focus' ? '专注' : '休息';
            timerZone.classList.toggle('is-running', running);
            timerZone.classList.toggle('is-break', phase === 'break');
            timerToggle.setAttribute('aria-pressed', running ? 'true' : 'false');
        }

        // 阶段结束的柔和提示音（Web Audio 合成，无需音频素材）
        function chime(bright) {
            const ctx = audioEngine.getContext();
            if (!ctx) return;
            const notes = bright ? [880, 1320] : [660, 880];
            notes.forEach((freq, i) => {
                const osc = ctx.createOscillator();
                const gain = ctx.createGain();
                const t0 = ctx.currentTime + i * 0.18;
                osc.type = 'sine';
                osc.frequency.value = freq;
                gain.gain.setValueAtTime(0, t0);
                gain.gain.linearRampToValueAtTime(0.22, t0 + 0.03);
                gain.gain.exponentialRampToValueAtTime(0.0008, t0 + 0.6);
                osc.connect(gain);
                gain.connect(ctx.destination);
                osc.start(t0);
                osc.stop(t0 + 0.62);
            });
        }

        function complete() {
            chime(phase === 'focus');
            if (phase === 'focus') {
                sessions += 1;
                phase = 'break';
                total = BREAK;
            } else {
                phase = 'focus';
                total = FOCUS;
            }
            remaining = total;
            paint();   // 自动进入下一阶段，保持运行与背景音
        }

        function tick() {
            remaining -= 1;
            if (remaining <= 0) {
                complete();
            } else {
                paint();
            }
        }

        function start() {
            if (running) return;
            running = true;
            audioEngine.play();          // 开始番茄钟即播放当前背景音
            interval = window.setInterval(tick, 1000);
            paint();
        }

        function pause() {
            if (!running) return;
            running = false;
            window.clearInterval(interval);
            interval = null;
            audioEngine.pause();         // 暂停联动停止背景音
            paint();
        }

        function toggle() {
            if (longPressed) { longPressed = false; return; }   // 长按已触发重置，忽略本次点击
            if (running) {
                pause();
            } else {
                start();
            }
        }

        // 长按 orb 重置（参考 flow-space 的交互）
        function pressStart() {
            longPressed = false;
            pressTimer = window.setTimeout(() => {
                longPressed = true;
                reset();
            }, 600);
        }

        function pressEnd() {
            if (pressTimer) {
                window.clearTimeout(pressTimer);
                pressTimer = null;
            }
        }

        function reset() {
            running = false;
            window.clearInterval(interval);
            interval = null;
            phase = 'focus';
            total = FOCUS;
            remaining = FOCUS;
            audioEngine.pause();
            paint();
        }

        return { toggle, reset, paint, pressStart, pressEnd };
    })();

    // 依据 SOUNDS 生成背景音菜单（插在"导入录音"之前）；新增背景音只需改 SOUNDS 配置
    function renderSoundMenu() {
        const fragment = document.createDocumentFragment();
        SOUNDS.forEach((item) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.dataset.sound = item.id;
            button.textContent = item.label;
            if (item.id === state.sound) button.classList.add('active');
            fragment.appendChild(button);
        });
        soundMenu.insertBefore(fragment, audioImport);
    }

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
        document.querySelectorAll('button[data-mode]').forEach((button) => {
            button.addEventListener('click', () => updateMode(button.dataset.mode));
        });
        document.querySelectorAll('button[data-font]').forEach((button) => {
            button.addEventListener('click', () => updateFont(button.dataset.font));
        });
        document.querySelectorAll('button[data-size]').forEach((button) => {
            button.addEventListener('click', () => updateSize(button.dataset.size));
        });
        document.querySelectorAll('button[data-sound]').forEach((button) => {
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
        timerToggle.addEventListener('click', () => pomodoro.toggle());
        timerToggle.addEventListener('mousedown', () => pomodoro.pressStart());
        timerToggle.addEventListener('touchstart', () => pomodoro.pressStart(), { passive: true });
        ['mouseup', 'mouseleave', 'touchend'].forEach((evt) => {
            timerToggle.addEventListener(evt, () => pomodoro.pressEnd());
        });
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
        if (!SOUND_BY_ID[state.sound]) state.sound = 'rain';
        renderSoundMenu();
        editor.value = loadInitialText();
        bindEvents();
        updateMode(state.mode);
        updateFont(state.font);
        updateSize(state.size);
        updateIntensity(state.intensity);
        updateVolume(state.volume);
        updateSound(state.sound);
        updateSaveStatus(editor.value.trim() ? undefined : 'Ready');
        pomodoro.paint();
        renderer.init();
        setTimeout(() => editor.focus(), 120);
    }

    document.addEventListener('DOMContentLoaded', init);
})();
