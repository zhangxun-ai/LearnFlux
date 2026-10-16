(function (root) {
    'use strict';

    const features = Object.freeze({
        collections: true,
        study_player: true,
        reading: true,
        focus_studio: true,
        history: true,
    });

    if (typeof module !== 'undefined' && module.exports) {
        module.exports = features;
    }

    if (root) {
        root.LEARNFLUX_UI_FEATURES = features;
    }
}(typeof window !== 'undefined' ? window : null));
