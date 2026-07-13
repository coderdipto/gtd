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
document.body.addEventListener("htmx:load", (evt) => {
  const root = evt.detail.elt;
  const containers = root.matches?.("[data-sortable]")
    ? [root]
    : root.querySelectorAll
      ? root.querySelectorAll("[data-sortable]")
      : [];
  containers.forEach((el) => {
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
  });
});
