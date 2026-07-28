/*
 * Reader files and progress are account-scoped in IndexedDB; this cache only
 * contains the unsigned application shell. API responses, session data and
 * cover URLs must never be added here.
 */
const CACHE = 'bookflow-shell-v4';
const OFFLINE = new URL('offline.html', self.registration.scope).toString();
const APP_SHELL = new URL('./', self.registration.scope).toString();
const BUILD_ASSETS = __BOOKFLOW_PRECACHE__;
const SHELL = [
  new URL('./', self.registration.scope).toString(),
  OFFLINE,
  new URL('manifest.webmanifest', self.registration.scope).toString(),
  new URL('theme-init.js', self.registration.scope).toString(),
  new URL('icon-192.png', self.registration.scope).toString(),
  new URL('icon-512.png', self.registration.scope).toString(),
  new URL('icon-maskable-512.png', self.registration.scope).toString(),
  ...BUILD_ASSETS.map((asset) => new URL(asset, self.registration.scope).toString()),
];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', (event) => event.waitUntil(
  caches.keys()
    .then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))))
    .then(() => self.clients.claim()),
));
self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET' || request.url.includes('/api/') || request.url.includes('/socket.io/') || request.destination === 'image') return;
  if (request.mode === 'navigate') {
    // A cached app shell lets the SPA resolve an offline reader route. The
    // reader itself obtains its selected book from account-scoped IndexedDB.
    event.respondWith(fetch(request).then((response) => response).catch(() => caches.match(APP_SHELL).then((cached) => cached || caches.match(OFFLINE))));
    return;
  }
  if (request.destination === 'script' || request.destination === 'style' || request.destination === 'font') {
    event.respondWith(caches.match(request).then((cached) => cached || fetch(request).then((response) => { const copy = response.clone(); void caches.open(CACHE).then((cache) => cache.put(request, copy)); return response; })));
  }
});
self.addEventListener('push', (event) => {
  let data = {}; try { data = event.data ? event.data.json() : {}; } catch { data = { title: 'BookFlow', body: event.data?.text() }; }
  const payload = data && typeof data === 'object' ? data : {};
  const scope = new URL(self.registration.scope);
  let destination = scope.toString();
  try {
    const candidate = new URL(String(payload.url || './').replace(/^\/+/, ''), scope);
    if (candidate.origin === scope.origin && candidate.href.startsWith(scope.href)) {
      destination = candidate.toString();
    }
  } catch {
    // Invalid and cross-origin destinations safely fall back to the app root.
  }
  event.waitUntil(self.registration.showNotification(payload.title || 'BookFlow', { body: payload.body || 'There is an update in BookFlow.', data: { url: destination }, icon: new URL('icon-192.png', self.registration.scope).toString() }));
});
self.addEventListener('notificationclick', (event) => { event.notification.close(); event.waitUntil(clients.openWindow(event.notification.data?.url || self.registration.scope)); });
