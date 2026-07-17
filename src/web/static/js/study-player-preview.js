(function () {
    'use strict';

    const previewStates = {
        'standalone-video': { collection: false, media: 'video' },
        'standalone-audio': { collection: false, media: 'audio' },
        'collection-video': { collection: true, media: 'video' },
        'collection-audio': { collection: true, media: 'audio' },
    };

    function computePreviewView(stateName) {
        const selectedState = previewStates[stateName] ? stateName : 'standalone-video';
        const state = previewStates[selectedState];
        return {
            selectedState,
            showCollection: state.collection,
            showVideo: state.media === 'video',
            showAudio: state.media === 'audio',
            contextLabel: state.collection
                ? `${state.media === 'video' ? '合集视频' : '合集音频'} · 第 3/12 集`
                : `${state.media === 'video' ? '单个视频' : '单个音频'} · 非合集内容`,
            mediaTitle: state.media === 'video' ? '原始视频' : '原始音频',
            mediaMeta: state.media === 'video' ? 'MP4 · 1080p · 38:24' : 'MP3 · 38:24',
        };
    }

    function resolveRequestedState(search) {
        const params = new URLSearchParams(search || '');
        const requestedState = params.get('state');
        return previewStates[requestedState] ? requestedState : 'standalone-video';
    }

    function renderPreviewState(stateName) {
        const view = computePreviewView(stateName);
        const collectionContext = document.getElementById('preview-collection-context');
        const videoStage = document.getElementById('preview-video-stage');
        const audioStage = document.getElementById('preview-audio-stage');

        document.body.dataset.previewState = view.selectedState;
        collectionContext.hidden = !view.showCollection;
        videoStage.hidden = !view.showVideo;
        audioStage.hidden = !view.showAudio;
        document.getElementById('preview-context-label').textContent = view.contextLabel;
        document.getElementById('preview-media-title').textContent = view.mediaTitle;
        document.getElementById('preview-media-meta').textContent = view.mediaMeta;

        document.querySelectorAll('[data-preview-state]').forEach((button) => {
            const active = button.dataset.previewState === view.selectedState;
            button.classList.toggle('is-active', active);
            button.setAttribute('aria-pressed', String(active));
        });
    }

    function initPreview() {
        document.querySelectorAll('[data-preview-state]').forEach((button) => {
            button.addEventListener('click', () => renderPreviewState(button.dataset.previewState));
        });
        renderPreviewState(resolveRequestedState(window.location.search));
    }

    globalThis.StudyPlayerPreview = {
        previewStates,
        computePreviewView,
        resolveRequestedState,
    };

    if (typeof document !== 'undefined') {
        document.addEventListener('DOMContentLoaded', initPreview);
    }
}());
