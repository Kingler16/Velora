/* Velora Service Worker — PWA Foundation (Phase 0)
 *
 * Strategie:
 *  - PRECACHE: kritische Shell-Assets beim install
 *  - RUNTIME:  NetworkFirst für HTML/API, CacheFirst für /static/
 *  - OFFLINE:  fallback auf /offline für nicht gecachte HTML
 *
 * Push-Handler folgt in Phase 3.
 */

const VERSION = 'velora-0.6.0-redesign';
const STATIC_CACHE = `velora-static-${VERSION}`;
const RUNTIME_CACHE = `velora-runtime-${VERSION}`;
const API_CACHE = `velora-api-${VERSION}`;

const PRECACHE = [
  '/',
  '/offline',
  '/static/css/design-system.css',
  '/static/css/background.css',
  '/static/css/components.css',
  '/static/css/main.css',
  '/static/css/responsive.css',
  '/static/css/bottom-nav.css',
  '/static/css/mobile.css',
  '/static/vendor/htmx.min.js',
  '/static/vendor/apexcharts.min.js',
  '/static/js/chart-theme.js',
  '/static/js/haptics.js',
  '/static/js/pull-refresh.js',
  '/static/js/toast.js',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/apple-touch-icon.png',
];

// API-Endpoints, die stale-while-revalidate nutzen (schnelles Rendering aus Cache,
// im Hintergrund wird frischer Request gefetcht).
const SWR_PATHS = new Set([
  '/api/portfolio/summary',
  '/api/portfolio/history',
  '/api/market/indices',
  '/api/market/macro',
  '/api/briefings',
  '/api/recommendations',
  '/api/calendar',
]);

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(STATIC_CACHE)
      .then((cache) => cache.addAll(PRECACHE).catch(() => null))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((k) => !k.endsWith(VERSION))
            .map((k) => caches.delete(k)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  // SSE-Stream (Chat) niemals cachen
  if (url.pathname.startsWith('/api/chat/threads/') && url.pathname.endsWith('/message')) {
    return;
  }
  // Share-Target-POST wird durch method:GET filter schon rausgefiltert, aber defensiv:
  if (url.pathname === '/api/share/trade') return;
  // Cache-Status ist hoch-dynamisch
  if (url.pathname === '/api/cache/status') return;

  // Manifest + Service-Worker selbst nie cachen
  if (url.pathname === '/manifest.webmanifest' || url.pathname === '/sw.js') return;

  if (url.pathname.startsWith('/static/')) {
    event.respondWith(cacheFirst(req));
    return;
  }

  if (url.pathname.startsWith('/api/')) {
    if (SWR_PATHS.has(url.pathname)) {
      event.respondWith(staleWhileRevalidate(req));
    } else {
      event.respondWith(networkFirst(req, { fallbackToCache: true }));
    }
    return;
  }

  // HTML-Seiten: Network-First, Offline-Fallback
  if (req.mode === 'navigate' || req.headers.get('accept')?.includes('text/html')) {
    event.respondWith(networkFirst(req, { fallbackToCache: true, offlinePage: '/offline' }));
    return;
  }
});

async function cacheFirst(req) {
  const cached = await caches.match(req);
  if (cached) return cached;
  try {
    const res = await fetch(req);
    if (res.ok) {
      const cache = await caches.open(STATIC_CACHE);
      cache.put(req, res.clone());
    }
    return res;
  } catch (err) {
    if (cached) return cached;
    throw err;
  }
}

async function networkFirst(req, { fallbackToCache = false, offlinePage = null } = {}) {
  try {
    const res = await fetch(req);
    if (res.ok && req.method === 'GET') {
      const cache = await caches.open(RUNTIME_CACHE);
      cache.put(req, res.clone()).catch(() => null);
    }
    return res;
  } catch (err) {
    if (fallbackToCache) {
      const cached = await caches.match(req);
      if (cached) return cached;
    }
    if (offlinePage) {
      const offline = await caches.match(offlinePage);
      if (offline) return offline;
    }
    throw err;
  }
}

async function staleWhileRevalidate(req) {
  const cache = await caches.open(API_CACHE);
  const cached = await cache.match(req);
  const networkFetch = fetch(req)
    .then((res) => {
      if (res.ok) cache.put(req, res.clone()).catch(() => null);
      return res;
    })
    .catch(() => null);
  // Wenn Cache da: sofort zurück, Network läuft im Hintergrund weiter.
  // Wenn kein Cache: auf Network warten.
  return cached || networkFetch || new Response('offline', { status: 504 });
}

self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});

/* ─── Push Notifications (Phase 3) ──────────────────────── */

self.addEventListener('push', (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (_) {
    data = { title: 'Velora', body: event.data ? event.data.text() : '' };
  }

  const title = data.title || 'Velora';
  const options = {
    body: data.body || '',
    icon: '/static/icons/icon-192.png',
    badge: '/static/icons/icon-badge.png',
    tag: data.tag || data.category || 'velora',
    data: { url: data.url || '/', category: data.category, ...(data.data || {}) },
    renotify: Boolean(data.renotify),
    requireInteraction: false,
    silent: false,
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const targetUrl = (event.notification.data && event.notification.data.url) || '/';

  event.waitUntil((async () => {
    const allClients = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    // Fokussiere einen existierenden Tab wenn er bereits die Ziel-URL zeigt
    for (const client of allClients) {
      try {
        const url = new URL(client.url);
        if (url.pathname === targetUrl || client.url.endsWith(targetUrl)) {
          if ('focus' in client) return client.focus();
        }
      } catch (_) { /* ignore */ }
    }
    // Sonst: ersten offenen Tab fokussieren + navigieren, sonst neuen öffnen
    if (allClients.length > 0) {
      const client = allClients[0];
      if ('navigate' in client) {
        await client.navigate(targetUrl);
        return client.focus();
      }
    }
    return self.clients.openWindow(targetUrl);
  })());
});

self.addEventListener('pushsubscriptionchange', (event) => {
  /* Browser rotiert Endpoint — Client-JS re-subscribed beim nächsten Öffnen.
     Wir könnten hier proaktiv re-subscriben, aber dafür bräuchten wir den
     applicationServerKey, den wir hier nicht haben.  Stattdessen logs. */
  console.log('[SW] pushsubscriptionchange — client re-subscribe on next load');
});
