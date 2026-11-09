const CACHE_NAME = 'learnflux-pwa-20261104-light-shell';

const PRECACHE_URLS = [
  '/',
  '/add_task_by_web',
  '/collections',
  '/settings',
  '/visual-learning',
  '/static/history.html',
  '/static/focus-studio.html',
  '/manifest.webmanifest',
  '/static/css/app-shell.css',
  '/static/css/auth-gate.css',
  '/static/css/editorial.css',
  '/static/css/styles.css',
  '/static/css/workbench.css',
  '/static/css/collections.css',
  '/static/css/focus-studio.css',
  '/static/css/floating-toc.css',
  '/static/css/study.css',
  '/static/css/visual-learning.css',
  '/static/css/image-diagrams.css',
  '/static/css/product-linear.css',
  '/static/css/product-linear-core.css',
  '/static/css/product-linear-system.css',
  '/static/css/workbench-wildwood.css',
  '/static/js/app.js',
  '/static/js/time.js',
  '/static/js/auth-session.js',
  '/static/js/app-shell.js',
  '/static/js/appearance.js',
  '/static/js/ui-features.js',
  '/static/js/collections.js',
  '/static/js/floating-toc.js',
  '/static/js/focus-studio.js',
  '/static/js/focus-journal.js',
  '/static/js/pwa-register.js',
  '/static/js/study.js',
  '/static/js/visual-learning.js',
  '/static/js/image-diagrams.js',
  '/static/js/visual-learning-workbench.js',
  '/static/audio/rain.mp3',
  '/static/audio/snow.mp3',
  '/static/audio/stream.mp3',
  '/static/icon/learnflux-leaf.svg',
  '/static/icon/learnflux-leaf-32.png',
  '/static/icon/learnflux-leaf-180.png',
  '/static/icon/learnflux-leaf-192.png',
  '/static/icon/learnflux-leaf-256.png',
  '/static/icon/learnflux-leaf-512.png',
  '/static/icon/learnflux-og.png',
  '/static/img/focus/rain-bg.jpg',
  '/static/img/focus/snow-bg.jpg',
  '/static/images/landing/learnflux-meadow-hero-v2.png',
  '/static/images/landing/learnflux-reading-nook-cover.webp'
];

const CACHEABLE_PATHS = [
  '/',
  '/add_task_by_web',
  '/collections',
  '/settings',
  '/visual-learning',
  '/reading',
  '/study',
  '/review',
  '/manifest.webmanifest'
];

const STATIC_SHELL_PATHS = new Set([
  '/static/index.html',
  '/static/collections.html',
  '/static/settings.html',
  '/static/visual-learning.html',
  '/static/reading.html',
  '/static/study.html',
  '/static/review.html',
  '/static/history.html',
  '/static/focus-studio.html'
]);

function shouldHandle(request) {
  if (request.method !== 'GET') return false;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return false;
  if (url.pathname.startsWith('/api/')) return false;
  if (url.pathname.startsWith('/view/')) return false;
  if (url.pathname.startsWith('/export/')) return false;

  if (url.pathname.startsWith('/static/')) {
    return STATIC_SHELL_PATHS.has(url.pathname)
      || /\.(?:css|js|mjs|png|jpe?g|webp|svg|ico|woff2?|mp3)$/i.test(url.pathname);
  }
  if (url.search) return false;
  return CACHEABLE_PATHS.includes(url.pathname);
}

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(
        PRECACHE_URLS.map((url) => new Request(url, { cache: 'no-store' }))
      ))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', (event) => {
  if (!shouldHandle(event.request)) return;

  event.respondWith(
    // A network-first strategy must also bypass the browser's HTTP cache.
    // Otherwise a successful fetch can still return an obsolete HTML/CSS file.
    fetch(event.request, { cache: 'no-store' })
      .then((response) => {
        const cacheControl = response.headers.get('Cache-Control') || '';
        if (response.ok && !/\b(?:no-store|private)\b/i.test(cacheControl)) {
          const copy = response.clone();
          event.waitUntil(
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy))
          );
        }
        return response;
      })
      .catch(async () => {
        const cache = await caches.open(CACHE_NAME);
        return await cache.match(event.request) || await caches.match(event.request)
          || Response.error();
      })
  );
});
