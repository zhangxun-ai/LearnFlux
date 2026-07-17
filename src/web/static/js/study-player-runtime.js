(function (root, factory) {
    const runtime = factory();
    if (typeof module === 'object' && module.exports) module.exports = runtime;
    if (root) root.StudyPlayerRuntime = runtime;
}(typeof window !== 'undefined' ? window : globalThis, function () {
    async function togglePlayback(media) {
        if (media.paused) {
            await media.play();
        } else {
            media.pause();
        }
    }

    function progressSeconds(progressValue, duration) {
        const safeDuration = Number(duration || 0);
        if (!Number.isFinite(safeDuration) || safeDuration <= 0) return 0;
        const numericProgress = Number(progressValue || 0);
        const safeProgress = Number.isFinite(numericProgress)
            ? Math.max(0, Math.min(100, numericProgress))
            : 0;
        return safeDuration * (safeProgress / 100);
    }

    async function seekFromProgress(media, progressValue) {
        const seconds = progressSeconds(progressValue, media.duration);
        if (!Number.isFinite(Number(media.duration)) || Number(media.duration) <= 0) return 0;
        media.currentTime = seconds;
        await media.play();
        return seconds;
    }

    function setPlaybackRate(media, value) {
        const numericRate = Number(value);
        const rate = Number.isFinite(numericRate)
            ? Math.max(0.5, Math.min(2, numericRate))
            : 1;
        media.defaultPlaybackRate = rate;
        media.playbackRate = rate;
        return rate;
    }

    function estimateTimeline(lines, duration) {
        const safeDuration = Number(duration || 0);
        if (!Array.isArray(lines) || !lines.length || !Number.isFinite(safeDuration) || safeDuration <= 0) {
            return Array.isArray(lines) ? lines : [];
        }

        const weights = lines.map((line) => Math.max(4, String(line.text || '').replace(/\s/g, '').length));
        const totalWeight = weights.reduce((total, weight) => total + weight, 0);
        let elapsed = 0;
        return lines.map((line, index) => {
            const start = elapsed;
            elapsed += safeDuration * (weights[index] / totalWeight);
            const end = index === lines.length - 1 ? safeDuration : elapsed;
            return {
                ...line,
                start_seconds: Number(start.toFixed(3)),
                end_seconds: Number(end.toFixed(3)),
                seekable: true,
                estimated: true,
            };
        });
    }

    function activeLineAt(lines, currentSeconds) {
        const current = Number(currentSeconds || 0);
        let active = null;
        for (const line of lines || []) {
            if (!line.seekable || !Number.isFinite(Number(line.start_seconds))) continue;
            if (Number(line.start_seconds) <= current) active = line;
            else break;
        }
        return active;
    }

    return {
        togglePlayback,
        progressSeconds,
        seekFromProgress,
        setPlaybackRate,
        estimateTimeline,
        activeLineAt,
    };
}));
