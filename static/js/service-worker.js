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
  event.respondWith(
    caches.match(event.request).then((cached) => cached || fetch(event.request))
  );
});
