(function () {
  if (!('serviceWorker' in navigator)) return;

  var isSecureContext = window.isSecureContext || window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
  if (!isSecureContext) return;

  window.addEventListener('load', function () {
    navigator.serviceWorker.register('/service-worker.js', { scope: '/' }).catch(function (error) {
      console.warn('PWA service worker registration failed:', error);
    });
  });
})();
