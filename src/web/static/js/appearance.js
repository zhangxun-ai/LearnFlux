(function () {
    'use strict';

    document.documentElement.setAttribute('data-theme', 'light');
    document.documentElement.style.colorScheme = 'light';
    try {
        localStorage.setItem('vta_theme_preference', JSON.stringify('light'));
    } catch (error) {
        // Appearance stays light when browser storage is unavailable.
    }
})();
