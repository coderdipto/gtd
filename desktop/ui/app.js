// Frontend is deliberately thin: it collects text and renders whatever Rust
// says happened. No HTTP, no retry logic, no knowledge of the queue beyond a
// count — see src-tauri/src/main.rs for all of that.

const { invoke } = window.__TAURI__.core;
const { listen } = window.__TAURI__.event;

const $ = (id) => document.getElementById(id);

const views = { capture: $("view-capture"), settings: $("view-settings") };
const titleEl = $("title");
const descEl = $("description");
const captureBtn = $("capture-btn");
const captureMsg = $("capture-msg");
const settingsMsg = $("settings-msg");
const queueBadge = $("queue-badge");
const isMac = navigator.platform.toLowerCase().includes("mac");

// --------------------------------------------------------------- messaging

let msgTimer = null;

function showMsg(el, text, kind) {
  el.textContent = text;
  el.className = `msg ${kind}`;
  el.hidden = false;
  clearTimeout(msgTimer);
  if (kind !== "err") {
    msgTimer = setTimeout(() => (el.hidden = true), 4000);
  }
}

function clearMsg(el) {
  clearTimeout(msgTimer);
  el.hidden = true;
}

function renderQueue(count) {
  queueBadge.hidden = count === 0;
  queueBadge.textContent = count === 1 ? "1 pending" : `${count} pending`;
}

// ------------------------------------------------------------------- views

function showView(name) {
  for (const [key, el] of Object.entries(views)) el.hidden = key !== name;
  clearMsg(captureMsg);
  clearMsg(settingsMsg);

  if (name === "capture") {
    titleEl.value = "";
    descEl.value = "";
    // The window is shown by Rust before this event lands, so the focus call
    // has a real window to land in.
    setTimeout(() => titleEl.focus(), 20);
    invoke("queue_count").then(renderQueue);
  } else {
    loadSettings();
  }
}

function dismiss() {
  invoke("hide_window");
}

// ----------------------------------------------------------------- capture

async function submitCapture(event) {
  event.preventDefault();
  const title = titleEl.value.trim();
  if (!title) return;

  captureBtn.disabled = true;
  try {
    const result = await invoke("capture", {
      title,
      description: descEl.value.trim(),
    });
    renderQueue(result.queue_len);

    if (result.queued) {
      // Offline is a success from the user's point of view — the thought is
      // safe. Say so plainly and keep the window open long enough to read it.
      showMsg(captureMsg, "Saved locally — will send when you're back online", "warn");
      titleEl.value = "";
      descEl.value = "";
      titleEl.focus();
    } else {
      showMsg(captureMsg, "Captured", "ok");
      setTimeout(dismiss, 350);
    }
  } catch (err) {
    showMsg(captureMsg, String(err), "err");
  } finally {
    captureBtn.disabled = false;
  }
}

// ---------------------------------------------------------------- settings

async function loadSettings() {
  const settings = await invoke("get_settings");
  $("server-url").value = settings.server_url;
  $("token").value = settings.token;
  $("hotkey").value = settings.hotkey;
}

async function submitSettings(event) {
  event.preventDefault();
  const saveBtn = $("save-btn");
  saveBtn.disabled = true;
  try {
    await invoke("save_settings", {
      settings: {
        server_url: $("server-url").value,
        token: $("token").value,
        hotkey: $("hotkey").value,
      },
    });
    showMsg(settingsMsg, "Saved", "ok");
    invoke("flush_now").then(renderQueue);
  } catch (err) {
    showMsg(settingsMsg, String(err), "err");
  } finally {
    saveBtn.disabled = false;
  }
}

async function testConnection() {
  const testBtn = $("test-btn");
  testBtn.disabled = true;
  showMsg(settingsMsg, "Testing…", "ok");
  try {
    // Test against what's on screen, not what's on disk — otherwise the button
    // silently tests stale values whenever a field has been edited but not saved.
    await invoke("save_settings", {
      settings: {
        server_url: $("server-url").value,
        token: $("token").value,
        hotkey: $("hotkey").value,
      },
    });
    showMsg(settingsMsg, await invoke("test_connection"), "ok");
  } catch (err) {
    showMsg(settingsMsg, String(err), "err");
  } finally {
    testBtn.disabled = false;
  }
}

// ----------------------------------------------------------------- wiring

$("capture-form").addEventListener("submit", submitCapture);
$("settings-form").addEventListener("submit", submitSettings);
$("test-btn").addEventListener("click", testConnection);

// In-window navigation between the two views, so Settings is reachable even
// when the tray icon is hidden (notch / menu-bar overflow) and the hotkey only
// opens the capture card.
$("open-settings").addEventListener("click", () => showView("settings"));
$("close-settings").addEventListener("click", () => showView("capture"));

for (const el of document.querySelectorAll("[data-dismiss]")) {
  el.addEventListener("click", dismiss);
}

// Cmd/Ctrl+Enter submits from either field, so a note doesn't force a reach
// for the mouse. Plain Enter in the title submits; in the notes it newlines.
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    dismiss();
    return;
  }
  if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
    const form = views.capture.hidden ? $("settings-form") : $("capture-form");
    form.requestSubmit();
  }
});

titleEl.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    $("capture-form").requestSubmit();
  }
});

listen("show-view", (event) => showView(event.payload));
listen("queue-changed", (event) => renderQueue(event.payload));
// Blur-to-dismiss only applies to capture: settings has fields worth half
// filling out while you go and look up a token elsewhere.
listen("window-blurred", () => {
  if (!views.capture.hidden && !titleEl.value.trim() && !descEl.value.trim()) {
    dismiss();
  }
});

$("submit-hint").textContent = isMac ? "⌘↵" : "Ctrl+↵";

// The starting view is decided here rather than pushed from Rust's setup():
// this code runs once the webview definitely exists, whereas an emit during
// setup can land before this file has registered its listener and be dropped.
async function init() {
  const settings = await invoke("get_settings");
  const configured = settings.server_url.trim() && settings.token.trim();
  showView(configured ? "capture" : "settings");
  renderQueue(await invoke("queue_count"));
}

init();
