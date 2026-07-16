// Shared offline-capture queue (task #15). Loaded in BOTH contexts — the page
// (<script src>) and the service worker (importScripts) — so it must only touch
// `self`/`indexedDB`, which exist in both. It owns a tiny IndexedDB store of
// pending captures; capture-offline.js (page) enqueues on a failed send, and
// both the page ('online' event) and the SW ('sync'/'message') drain it by
// replaying each POST to the capture endpoint. The whole point is the GTD trust
// guarantee: a capture typed while offline is never lost.
(function (global) {
  var DB_NAME = "gtd-offline";
  var STORE = "captures";
  var VERSION = 1;

  function openDb() {
    return new Promise(function (resolve, reject) {
      var req = indexedDB.open(DB_NAME, VERSION);
      req.onupgradeneeded = function () {
        var db = req.result;
        if (!db.objectStoreNames.contains(STORE)) {
          db.createObjectStore(STORE, { keyPath: "id", autoIncrement: true });
        }
      };
      req.onsuccess = function () { resolve(req.result); };
      req.onerror = function () { reject(req.error); };
    });
  }

  function tx(mode, fn) {
    return openDb().then(function (db) {
      return new Promise(function (resolve, reject) {
        var t = db.transaction(STORE, mode);
        var store = t.objectStore(STORE);
        var out = fn(store);
        t.oncomplete = function () { resolve(out && out.result !== undefined ? out.result : out); };
        t.onerror = function () { reject(t.error); };
        t.onabort = function () { reject(t.error); };
      });
    });
  }

  // rec = { url, body (urlencoded string), headers: {..} }
  function add(rec) {
    return tx("readwrite", function (store) { return store.add(rec); });
  }

  function all() {
    return tx("readonly", function (store) { return store.getAll(); });
  }

  function remove(id) {
    return tx("readwrite", function (store) { store.delete(id); });
  }

  function count() {
    return tx("readonly", function (store) { return store.count(); });
  }

  // Replay every queued capture in insertion order. Stops on the first network
  // failure (still offline) so records are never dropped; a record the server
  // rejects with a 4xx is removed (it would never succeed on replay). Returns
  // the number successfully flushed.
  function drain() {
    return all().then(function (records) {
      var flushed = 0;
      var chain = Promise.resolve();
      records.forEach(function (rec) {
        chain = chain.then(function () {
          return fetch(rec.url, {
            method: "POST",
            credentials: "include",
            headers: Object.assign(
              { "Content-Type": "application/x-www-form-urlencoded", "X-Requested-With": "XMLHttpRequest" },
              rec.headers || {}
            ),
            body: rec.body,
          }).then(function (resp) {
            if (resp.ok || (resp.status >= 400 && resp.status < 500)) {
              flushed += 1;
              return remove(rec.id);
            }
            throw new Error("server " + resp.status); // 5xx: keep for later
          });
        });
      });
      return chain.then(function () { return flushed; }).catch(function () { return flushed; });
    });
  }

  global.gtdCaptureQueue = { add: add, all: all, remove: remove, count: count, drain: drain };
})(self);
