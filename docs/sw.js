// Service worker for the TLDR Digest Archive PWA.
//
// Goal: the news stays readable on a poor or absent connection.
//
// Strategy:
//   - Digest data (data/index.json, data/*.json) — NETWORK-FIRST WITH A
//     TIMEOUT: try the network so a fresh run's news shows immediately, but if
//     it doesn't answer within NET_TIMEOUT_MS (a slow/flaky connection) serve
//     the cached copy instead of hanging. The network response, whenever it
//     lands, still updates the cache for next time.
//   - The cache is also WARMED proactively on activation: the most recent
//     WARM_RECENT_DAYS digests are fetched and stored up front, so recent news
//     is available offline even for days you never opened while online.
//   - Everything else (shell: HTML, icons, banner, data.js) — CACHE-FIRST with
//     a background refresh, so the app opens instantly and offline while still
//     picking up shell changes on the next visit.
//
// Bump CACHE_VERSION whenever the shell assets change to evict the old cache
// (also re-runs activate, which re-warms the digest cache).
const CACHE_VERSION = "tldr-digest-v2";

// How long to wait for the network before falling back to cached digest data.
const NET_TIMEOUT_MS = 3500;
// How many of the most recent days to pre-cache on activation.
const WARM_RECENT_DAYS = 7;

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
        Promise.all(SHELL_ASSETS.map((url) => cache.add(url).catch(() => undefined)))
      )
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(
        keys.filter((k) => k !== CACHE_VERSION).map((k) => caches.delete(k))
      );
      await self.clients.claim();
      // Fire-and-forget warm-up: never let a slow network block activation.
      await warmDigestCache().catch(() => undefined);
    })()
  );
});

// Pre-fetch the index and the most recent day files so recent news is
// readable offline without having visited each day first.
async function warmDigestCache() {
  const cache = await caches.open(CACHE_VERSION);
  const resp = await fetch("data/index.json", { cache: "no-cache" });
  if (!resp.ok) return;
  await cache.put("data/index.json", resp.clone());
  const dates = await resp.json();
  const recent = (Array.isArray(dates) ? dates : []).slice(0, WARM_RECENT_DAYS);
  await Promise.all(
    recent.map(async (date) => {
      try {
        const r = await fetch(`data/${date}.json`, { cache: "no-cache" });
        if (r.ok) await cache.put(`data/${date}.json`, r.clone());
      } catch {
        /* offline for this one — skip */
      }
    })
  );
}

function isDigestData(url) {
  return /\/data\/[^/]+\.json$/.test(url.pathname);
}

// Network-first, but fall back to cache once NET_TIMEOUT_MS elapses so a slow
// connection never blocks reading. The network result still refreshes the
// cache whenever it eventually arrives.
function networkFirstWithTimeout(request) {
  return new Promise((resolve) => {
    let settled = false;
    const done = (resp) => {
      if (settled) return;
      settled = true;
      resolve(resp);
    };

    const timer = setTimeout(async () => {
      const cached = await caches.match(request);
      if (cached) done(cached); // else keep waiting for the network
    }, NET_TIMEOUT_MS);

    fetch(request)
      .then((resp) => {
        clearTimeout(timer);
        // Refresh the cache even if the timeout already served a stale copy.
        const copy = resp.clone();
        caches.open(CACHE_VERSION).then((cache) => cache.put(request, copy));
        done(resp);
      })
      .catch(async () => {
        clearTimeout(timer);
        const cached = await caches.match(request);
        done(cached || Response.error());
      });
  });
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (isDigestData(url)) {
    event.respondWith(networkFirstWithTimeout(request));
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
