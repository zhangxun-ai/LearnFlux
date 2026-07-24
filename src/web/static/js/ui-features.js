(function (root) {
    'use strict';

    const features = Object.freeze({
        collections: true,
        visual_learning: true,
        study_player: true,
        reading: true,
        focus_studio: true,
        post_insight: true,
        trend_radar: false,
        flywheel: true,
        history: true,
    });

    if (typeof module !== 'undefined' && module.exports) {
        module.exports = features;
    }

    if (root) {
        root.LEARNFLUX_UI_FEATURES = features;
    }
}(typeof window !== 'undefined' ? window : null));
