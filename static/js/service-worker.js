// App-shell cache for fast/offline PWA open, plus an offline capture queue
// (task #15). The queue logic is shared with the page via capture-queue.js,
// pulled in here with importScripts so both contexts use the same IndexedDB
// store; the 'sync' handler below replays it when the OS reports connectivity,
// even if no tab is open.
importScripts("/static/js/capture-queue.js");

const CACHE_NAME = "gtd-shell-v2";
const SHELL_URLS = [
  "/capture/",
  "/static/css/app.css",
  "/static/js/htmx.min.js",
  "/static/js/alpine.min.js",
  "/static/js/capture-queue.js",
  "/static/js/capture-offline.js",
];

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

// Background Sync: the browser fires this when connectivity returns (queued
// while offline via capture-offline.js). Drain the shared IndexedDB queue by
// replaying each capture POST. Works even with no page open.
self.addEventListener("sync", (event) => {
  if (event.tag === "gtd-capture-sync" && self.gtdCaptureQueue) {
    event.waitUntil(self.gtdCaptureQueue.drain());
  }
});

// A page can also nudge the worker to flush immediately (e.g. right after
// coming online) without waiting for the OS sync signal.
self.addEventListener("message", (event) => {
  if (event.data === "gtd-drain-captures" && self.gtdCaptureQueue) {
    event.waitUntil(self.gtdCaptureQueue.drain());
  }
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
