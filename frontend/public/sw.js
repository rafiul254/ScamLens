/* ScamLens service worker: cache-first for the app shell, network-only for /api.
   API responses are never cached because a verdict must always be fresh. */
const SHELL = 'scamlens-shell-v1'
const ASSETS = ['./', './index.html', './manifest.webmanifest', './icon.svg']

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(SHELL).then((c) => c.addAll(ASSETS)).then(() => self.skipWaiting()))
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== SHELL).map((k) => caches.delete(k)))),
  )
})

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url)
  if (event.request.method !== 'GET' || url.pathname.startsWith('/api')) return
  event.respondWith(
    caches.match(event.request).then(
      (cached) =>
        cached ||
        fetch(event.request)
          .then((res) => {
            const copy = res.clone()
            caches.open(SHELL).then((c) => c.put(event.request, copy)).catch(() => {})
            return res
          })
          .catch(() => caches.match('./index.html')),
    ),
  )
})
