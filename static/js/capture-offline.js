// Offline-capture page glue (task #15). Depends on capture-queue.js (loaded
// first). Registers document-level listeners once from base.html's persistent
// shell, so nothing stacks across boosted navigation (same reasoning as
// sortable-lists.js). Two jobs:
//
//   1. When an htmx capture POST fails to reach the network (htmx:sendError),
//      enqueue it in IndexedDB, show a "saved offline" note, and reset the
//      field — so capture feels successful and is never lost.
//   2. Drain the queue whenever we regain connectivity (the 'online' event and
//      once on load), and ask the service worker to register a Background Sync
//      so a still-closed tab also flushes when the OS reports connectivity.
//
// The capture form is identified by its hx-post target: the request path equals
// the endpoint the form posts to. We read that from the triggering element.

(function () {
  var CAPTURE_PATH = "/inbox/items/"; // matches url 'inbox_item_create'

  function isCapture(evt) {
    var xhr = evt.detail && evt.detail.xhr;
    var path = evt.detail && evt.detail.pathInfo && evt.detail.pathInfo.requestPath;
    // pathInfo.requestPath is set by htmx for the request; fall back to the
    // form's action if absent.
    if (path) return path.indexOf(CAPTURE_PATH) !== -1;
    var elt = evt.detail && evt.detail.elt;
    var form = elt && (elt.matches && elt.matches("form") ? elt : elt.closest && elt.closest("form"));
    var action = form && (form.getAttribute("hx-post") || form.getAttribute("action") || "");
    return action.indexOf(CAPTURE_PATH) !== -1;
    void xhr;
  }

  function formToBody(form) {
    return new URLSearchParams(new FormData(form)).toString();
  }

  function flashOffline(form) {
    var wrap = form.closest("[id^='capture-form-wrap']") || form.parentElement;
    var note = wrap.querySelector("[data-offline-note]");
    if (!note) {
      note = document.createElement("p");
      note.setAttribute("data-offline-note", "");
      note.className = "text-xs text-amber mt-1";
      form.appendChild(note);
    }
    note.textContent = "Saved offline — will sync when you reconnect.";
    var title = form.querySelector("[name='title']");
    if (title) { title.value = ""; title.focus(); }
    var desc = form.querySelector("[name='description']");
    if (desc) desc.value = "";
  }

  function requestBackgroundSync() {
    if (!("serviceWorker" in navigator)) return;
    navigator.serviceWorker.ready.then(function (reg) {
      if (reg.sync) {
        reg.sync.register("gtd-capture-sync").catch(function () {});
      }
    }).catch(function () {});
  }

  document.body.addEventListener("htmx:sendError", function (evt) {
    if (!isCapture(evt)) return;
    var elt = evt.detail.elt;
    var form = elt.matches && elt.matches("form") ? elt : elt.closest("form");
    if (!form || !self.gtdCaptureQueue) return;
    self.gtdCaptureQueue
      .add({ url: CAPTURE_PATH, body: formToBody(form), headers: {} })
      .then(function () {
        flashOffline(form);
        requestBackgroundSync();
      });
  });

  function drain() {
    if (self.gtdCaptureQueue) self.gtdCaptureQueue.drain();
    // Also nudge the worker so a flush happens in its context (and via
    // Background Sync it survives the page being closed mid-drain).
    if (navigator.serviceWorker && navigator.serviceWorker.controller) {
      navigator.serviceWorker.controller.postMessage("gtd-drain-captures");
    }
  }

  window.addEventListener("online", drain);
  // Drain once shortly after load in case we came back while the tab was shut.
  if (navigator.onLine) setTimeout(drain, 1500);
})();
