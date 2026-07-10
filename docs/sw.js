// Service worker for the TLDR Digest Archive PWA.
//
// Strategy:
//   - Digest data (data/index.json, data/*.json) — NETWORK-FIRST: always try
//     the network so a fresh run's news shows immediately, falling back to the
//     cache only when offline. The archive changes daily, so stale data here
//     would defeat the point.
//   - Everything else (shell: HTML, icons, banner, data.js) — CACHE-FIRST with
//     a background refresh (stale-while-revalidate), so the app opens instantly
//     and offline while still picking up shell changes on the next visit.
//
// Bump CACHE_VERSION whenever the shell assets change to evict the old cache.
const CACHE_VERSION = "tldr-digest-v2";

const SHELL_ASSETS = [
  "./",
  "index.html",
  "favicon.png",
  "apple-touch-icon.png",
  "logo.png",
  "icon-maskable-192.png",
  "icon-maskable-512.png",
  "banner.jpg",
  "manifest.webmanifest",
  "data/data.js",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE_VERSION)
      // addAll is atomic — if any asset 404s the whole install fails, so add
      // them individually and ignore misses (e.g. data.js before the first run).
      .then((cache) =>
        Promise.all(
          SHELL_ASSETS.map((url) =>
            cache.add(url).catch(() => undefined)
          )
        )
      )
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys.filter((k) => k !== CACHE_VERSION).map((k) => caches.delete(k))
        )
      )
      .then(() => self.clients.claim())
  );
});

function isDigestData(url) {
  return /\/data\/[^/]+\.json$/.test(url.pathname);
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (isDigestData(url)) {
    // Network-first: fresh news wins, cache is the offline fallback.
    event.respondWith(
      fetch(request)
        .then((resp) => {
          const copy = resp.clone();
          caches.open(CACHE_VERSION).then((cache) => cache.put(request, copy));
          return resp;
        })
        .catch(() => caches.match(request))
    );
    return;
  }

  // Shell: cache-first, refresh in the background.
  event.respondWith(
    caches.match(request).then((cached) => {
      const network = fetch(request)
        .then((resp) => {
          const copy = resp.clone();
          caches.open(CACHE_VERSION).then((cache) => cache.put(request, copy));
          return resp;
        })
        .catch(() => cached);
      return cached || network;
    })
  );
});
