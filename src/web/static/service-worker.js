const CACHE_NAME = 'vta-pwa-20260720-product-linear-1';

const PRECACHE_URLS = [
  '/',
  '/add_task_by_web',
  '/collections',
  '/post',
  '/trend-radar',
  '/flywheel',
  '/settings',
  '/visual-learning',
  '/static/history.html',
  '/static/focus-studio.html',
  '/manifest.webmanifest',
  '/static/css/app-shell.css',
  '/static/css/editorial.css',
  '/static/css/styles.css',
  '/static/css/workbench.css',
  '/static/css/collections.css',
  '/static/css/focus-studio.css',
  '/static/css/floating-toc.css',
  '/static/css/study.css',
  '/static/css/trend-radar.css',
  '/static/css/visual-learning.css',
  '/static/css/product-linear.css',
  '/static/css/product-linear-core.css',
  '/static/css/product-linear-insights.css',
  '/static/css/product-linear-system.css',
  '/static/js/app.js',
  '/static/js/app-shell.js',
  '/static/js/collections.js',
  '/static/js/floating-toc.js',
  '/static/js/focus-studio.js',
  '/static/js/focus-journal.js',
  '/static/js/pwa-register.js',
  '/static/js/study.js',
  '/static/js/trend-radar.js',
  '/static/js/visual-learning.js',
  '/static/js/visual-learning-workbench.js',
  '/static/audio/rain.mp3',
  '/static/audio/snow.mp3',
  '/static/audio/stream.mp3',
  '/static/icon/logo.svg',
  '/static/icon/favicon-32.png',
  '/static/icon/favicon.png',
  '/static/icon/apple-touch-icon.png',
  '/static/img/focus/rain-bg.jpg',
  '/static/img/focus/snow-bg.jpg'
];

const CACHEABLE_PATHS = [
  '/',
  '/add_task_by_web',
  '/collections',
  '/post',
  '/flywheel',
  '/settings',
  '/static/'
];

function shouldHandle(request) {
  if (request.method !== 'GET') return false;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return false;
  if (url.pathname.startsWith('/api/')) return false;
  if (url.pathname.startsWith('/view/')) return false;
  if (url.pathname.startsWith('/export/')) return false;

  if (url.pathname.startsWith('/static/')) return true;
  if (url.search) return false;

  return CACHEABLE_PATHS.some((path) => (
    path === '/' ? url.pathname === '/' : url.pathname.startsWith(path)
  ));
}

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(PRECACHE_URLS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys
          .filter((key) => key !== CACHE_NAME)
          .map((key) => caches.delete(key))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  if (!shouldHandle(event.request)) return;

  event.respondWith(
    fetch(event.request)
      .then((response) => {
        if (response && response.ok) {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
        }
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});
