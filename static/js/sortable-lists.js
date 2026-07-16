// Wires SortableJS drag handles onto any `[data-sortable]` list container
// (docs/solution-plan.md Step 5, Decision #2). Rows are components/task_row.html
// rendered with sortable=True, so each carries data-task-id/data-reorder-url.
// Uses htmx.ajax() rather than a bare fetch() so the drop request picks up
// the same CSRF header configured globally via hx-headers on <body>.
//
// `<body hx-boost="true">` means normal navigation never re-fires
// DOMContentLoaded - htmx swaps content in place instead - so this listens
// for htmx:load, which htmx fires once for the initial page *and* again for
// every boosted/swapped-in fragment.
//
// The ~45KB SortableJS library itself is NOT shipped globally. It's only
// needed on the two pages with drag-reorder lists, so it's lazy-loaded the
// first time a [data-sortable] container actually appears - every other page
// never fetches it. The library URL comes from body[data-sortable-src], which
// base.html resolves through {% static %} so it stays correct under prod's
// hashed-manifest (WhiteNoise) storage. `_libPromise` memoizes the load so the
// script is injected at most once per session, and initialization waits on it
// (avoiding a race where htmx:load fires before the async library finishes).
let _libPromise = null;

function loadSortableLib() {
  if (typeof window.Sortable !== "undefined") return Promise.resolve();
  if (_libPromise) return _libPromise;
  const src = document.body.dataset.sortableSrc;
  if (!src) return Promise.reject(new Error("data-sortable-src missing on <body>"));
  _libPromise = new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = src;
    s.onload = () => resolve();
    s.onerror = () => reject(new Error("failed to load " + src));
    document.head.appendChild(s);
  });
  return _libPromise;
}

function activateSortable(el) {
  new Sortable(el, {
    handle: "[data-drag-handle]",
    animation: 150,
    onEnd(evt) {
      const item = evt.item;
      const url = item.dataset.reorderUrl;
      if (!url) return;
      const prev = item.previousElementSibling;
      const after = prev && prev.dataset.taskId ? prev.dataset.taskId : "";
      htmx.ajax("POST", url, { values: { after }, swap: "none" });
    },
  });
}

document.body.addEventListener("htmx:load", (evt) => {
  const root = evt.detail.elt;
  const containers = root.matches?.("[data-sortable]")
    ? [root]
    : root.querySelectorAll
      ? root.querySelectorAll("[data-sortable]")
      : [];
  if (!containers.length) return; // no drag lists here - library never requested
  loadSortableLib()
    .then(() => containers.forEach(activateSortable))
    .catch((err) => console.error("[sortable-lists]", err));
});
