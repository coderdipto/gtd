// Minimal app-shell cache for fast PWA open. No offline queue (v2 backlog —
// see docs/task-breakdown.md "Explicitly out of scope").
const CACHE_NAME = "gtd-shell-v1";
const SHELL_URLS = ["/capture/", "/static/css/app.css", "/static/js/htmx.min.js", "/static/js/alpine.min.js"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_URLS)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  // Only intercept the app-shell URLs above - every other GET (Today,
  // Inbox, /admin/, HTMX partials, ...) must always hit the network
  // untouched. An unscoped handler here previously opportunistically
  // cached *any* page a tab happened to visit and served it stale-first
  // on the next visit - meaning dynamic, frequently-changing pages could
  // silently show last visit's snapshot instead of current data.
  const path = new URL(event.request.url).pathname;
  if (!SHELL_URLS.includes(path)) return;

  // Stale-while-revalidate for the shell itself: serve the cached copy
  // instantly (fast open, works offline), but always refetch in the
  // background and update the cache so the *next* load picks up new
  // CSS/JS. A plain cache-first match with a static CACHE_NAME would
  // otherwise freeze the shell at whatever it was on first install
  // forever, since nothing ever invalidates it.
  event.respondWith(
    caches.open(CACHE_NAME).then((cache) =>
      cache.match(event.request).then((cached) => {
        const network = fetch(event.request)
          .then((response) => {
            if (response.ok) cache.put(event.request, response.clone());
            return response;
          })
          .catch(() => cached);
        return cached || network;
      })
    )
  );
});
