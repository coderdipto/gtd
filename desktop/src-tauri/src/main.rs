#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

//! GTD Capture — a capture-only desktop client.
//!
//! Deliberately knows nothing about the GTD domain beyond "a title and an
//! optional description become an InboxItem". All clarify/organize/reflect
//! work stays in the web app; this exists purely to shorten the path between
//! having a thought and it being safely in the inbox.
//!
//! Everything that can fail (HTTP, disk) lives here in Rust rather than in the
//! webview, so the frontend stays a dumb form: it calls `capture` and is told
//! whether the item went to the server or to the local queue.

use std::fs;
use std::path::PathBuf;
use std::time::Duration;

use serde::{Deserialize, Serialize};
use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    AppHandle, Emitter, Manager,
};
use tauri_plugin_global_shortcut::GlobalShortcutExt;
use tokio::sync::Mutex;

const DEFAULT_HOTKEY: &str = "CmdOrCtrl+Shift+Space";
const FLUSH_INTERVAL: Duration = Duration::from_secs(30);
const HTTP_TIMEOUT: Duration = Duration::from_secs(10);

// ---------------------------------------------------------------- data types

#[derive(Serialize, Deserialize, Clone, Debug)]
#[serde(default)]
struct Settings {
    server_url: String,
    token: String,
    hotkey: String,
}

impl Default for Settings {
    fn default() -> Self {
        Self {
            server_url: String::new(),
            token: String::new(),
            hotkey: DEFAULT_HOTKEY.to_string(),
        }
    }
}

impl Settings {
    fn configured(&self) -> bool {
        !self.server_url.trim().is_empty() && !self.token.trim().is_empty()
    }

    fn capture_url(&self) -> String {
        format!("{}/api/capture", self.server_url.trim().trim_end_matches('/'))
    }
}

#[derive(Serialize, Deserialize, Clone, Debug)]
struct QueuedItem {
    title: String,
    #[serde(default)]
    description: String,
    captured_at: String,
}

#[derive(Serialize, Clone, Debug)]
struct CaptureResult {
    queued: bool,
    queue_len: usize,
}

/// Whether a failed POST is worth retrying later. A 4xx that isn't 408/429 is
/// the server saying the *request* is wrong (bad token, empty title) — retrying
/// an unchanged payload against it just burns the queue in a loop, so those
/// surface to the user immediately instead of being swallowed into the queue.
struct PostError {
    message: String,
    retryable: bool,
}

/// Serializes read-modify-write cycles on queue.json. The flush loop and a
/// user-triggered capture genuinely can run at the same moment (the hotkey
/// works while a flush is in flight), and without this the two read-then-write
/// pairs can interleave and drop an item.
struct QueueLock(Mutex<()>);

// ------------------------------------------------------------- disk helpers

fn data_dir(app: &AppHandle) -> PathBuf {
    let dir = app
        .path()
        .app_data_dir()
        .expect("platform always provides an app data dir");
    let _ = fs::create_dir_all(&dir);
    dir
}

fn settings_path(app: &AppHandle) -> PathBuf {
    data_dir(app).join("settings.json")
}

fn queue_path(app: &AppHandle) -> PathBuf {
    data_dir(app).join("queue.json")
}

fn read_settings(app: &AppHandle) -> Settings {
    fs::read_to_string(settings_path(app))
        .ok()
        .and_then(|raw| serde_json::from_str(&raw).ok())
        .unwrap_or_default()
}

fn write_settings(app: &AppHandle, settings: &Settings) -> Result<(), String> {
    let json = serde_json::to_string_pretty(settings).map_err(|e| e.to_string())?;
    fs::write(settings_path(app), json).map_err(|e| e.to_string())
}

fn read_queue(app: &AppHandle) -> Vec<QueuedItem> {
    fs::read_to_string(queue_path(app))
        .ok()
        .and_then(|raw| serde_json::from_str(&raw).ok())
        .unwrap_or_default()
}

fn write_queue(app: &AppHandle, items: &[QueuedItem]) -> Result<(), String> {
    let json = serde_json::to_string_pretty(items).map_err(|e| e.to_string())?;
    fs::write(queue_path(app), json).map_err(|e| e.to_string())
}

/// Tell the UI the pending-count changed so the queue badge stays honest
/// without the frontend having to poll for it.
fn emit_queue_changed(app: &AppHandle, len: usize) {
    let _ = app.emit("queue-changed", len);
}

// ------------------------------------------------------------------ network

/// A 5xx is the server being briefly unwell; 429/408 are it asking us to come
/// back later. Everything else in the 4xx range is a verdict on the payload
/// itself, which won't change by being sent again.
fn status_is_retryable(status: reqwest::StatusCode) -> bool {
    status.is_server_error()
        || status == reqwest::StatusCode::TOO_MANY_REQUESTS
        || status == reqwest::StatusCode::REQUEST_TIMEOUT
}

async fn post_item(settings: &Settings, item: &QueuedItem) -> Result<(), PostError> {
    let client = reqwest::Client::builder()
        .timeout(HTTP_TIMEOUT)
        .build()
        .map_err(|e| PostError {
            message: e.to_string(),
            retryable: false,
        })?;

    let response = client
        .post(settings.capture_url())
        .bearer_auth(settings.token.trim())
        .json(&serde_json::json!({
            "title": item.title,
            "description": item.description,
            "source": "desktop",
        }))
        .send()
        .await
        // A transport-level failure is exactly the offline case: always retry.
        .map_err(|e| PostError {
            message: e.to_string(),
            retryable: true,
        })?;

    let status = response.status();
    if status.is_success() {
        return Ok(());
    }

    let retryable = status_is_retryable(status);

    let detail = response
        .json::<serde_json::Value>()
        .await
        .ok()
        .and_then(|body| body.get("detail").and_then(|d| d.as_str().map(String::from)))
        .unwrap_or_else(|| format!("HTTP {}", status.as_u16()));

    Err(PostError {
        message: match status.as_u16() {
            401 => format!("{detail} — check the token in Settings"),
            _ => detail,
        },
        retryable,
    })
}

/// Drain as much of the queue as the server will take, oldest first.
///
/// Stops at the first failure of any kind rather than skipping past it: the
/// queue is chronological, and a 401 or an offline server will fail every
/// remaining item identically, so continuing would just replay the same error
/// N times. Items are only dropped on confirmed success.
async fn flush_queue(app: &AppHandle) -> usize {
    let lock = app.state::<QueueLock>();
    let _guard = lock.0.lock().await;

    let settings = read_settings(app);
    let mut items = read_queue(app);
    if !settings.configured() || items.is_empty() {
        return items.len();
    }

    let mut sent = 0usize;
    for item in items.clone() {
        match post_item(&settings, &item).await {
            Ok(()) => sent += 1,
            Err(_) => break,
        }
    }

    if sent > 0 {
        items.drain(0..sent);
        let _ = write_queue(app, &items);
        emit_queue_changed(app, items.len());
    }
    items.len()
}

// ----------------------------------------------------------------- commands

#[tauri::command]
fn get_settings(app: AppHandle) -> Settings {
    read_settings(&app)
}

#[tauri::command]
fn save_settings(app: AppHandle, mut settings: Settings) -> Result<Settings, String> {
    settings.server_url = settings.server_url.trim().to_string();
    settings.token = settings.token.trim().to_string();
    settings.hotkey = match settings.hotkey.trim() {
        "" => DEFAULT_HOTKEY.to_string(),
        h => h.to_string(),
    };

    // Re-register before persisting: an unparseable accelerator must not be
    // written to disk, or every subsequent launch fails to bind the hotkey
    // and the app is only reachable from the tray.
    let previous = read_settings(&app);
    if previous.hotkey != settings.hotkey {
        let shortcuts = app.global_shortcut();
        let _ = shortcuts.unregister(previous.hotkey.as_str());
        shortcuts
            .register(settings.hotkey.as_str())
            .map_err(|e| format!("Couldn't register {}: {e}", settings.hotkey))?;
    }

    write_settings(&app, &settings)?;
    Ok(settings)
}

#[tauri::command]
async fn capture(
    app: AppHandle,
    title: String,
    description: Option<String>,
) -> Result<CaptureResult, String> {
    let title = title.trim().to_string();
    if title.is_empty() {
        return Err("Nothing to capture".into());
    }

    let settings = read_settings(&app);
    if !settings.configured() {
        return Err("Set your server URL and token in Settings first".into());
    }

    let item = QueuedItem {
        title,
        description: description.unwrap_or_default().trim().to_string(),
        captured_at: chrono::Utc::now().to_rfc3339(),
    };

    match post_item(&settings, &item).await {
        Ok(()) => Ok(CaptureResult {
            queued: false,
            queue_len: read_queue(&app).len(),
        }),
        // Offline/server-down: the whole point of the queue. Keep the thought,
        // tell the user it's held locally, and let the flush loop deal with it.
        Err(e) if e.retryable => {
            let lock = app.state::<QueueLock>();
            let _guard = lock.0.lock().await;

            let mut items = read_queue(&app);
            items.push(item);
            write_queue(&app, &items)?;
            emit_queue_changed(&app, items.len());
            Ok(CaptureResult {
                queued: true,
                queue_len: items.len(),
            })
        }
        Err(e) => Err(e.message),
    }
}

#[tauri::command]
fn queue_count(app: AppHandle) -> usize {
    read_queue(&app).len()
}

#[tauri::command]
async fn flush_now(app: AppHandle) -> usize {
    flush_queue(&app).await
}

#[tauri::command]
async fn test_connection(app: AppHandle) -> Result<String, String> {
    let settings = read_settings(&app);
    if !settings.configured() {
        return Err("Enter a server URL and token first".into());
    }
    let probe = QueuedItem {
        title: "GTD Capture — connection test".into(),
        description: "Sent from the desktop app's Settings screen.".into(),
        captured_at: chrono::Utc::now().to_rfc3339(),
    };
    match post_item(&settings, &probe).await {
        Ok(()) => Ok("Connected — a test item is in your inbox".into()),
        Err(e) => Err(e.message),
    }
}

#[tauri::command]
fn hide_window(app: AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.hide();
    }
}

// ------------------------------------------------------------------ windows

fn show_view(app: &AppHandle, view: &str) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.emit("show-view", view);
        let _ = window.show();
        let _ = window.set_focus();
    }
}

fn toggle_capture(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        // is_visible() alone isn't enough: on macOS the window can be visible
        // but behind another app, where the hotkey should raise it rather than
        // hide it. Only a focused window means "the user is looking at it".
        let focused = window.is_focused().unwrap_or(false);
        let visible = window.is_visible().unwrap_or(false);
        if visible && focused {
            let _ = window.hide();
        } else {
            show_view(app, "capture");
        }
    }
}

fn build_tray(app: &AppHandle) -> tauri::Result<()> {
    let capture_item = MenuItem::with_id(app, "capture", "Capture…", true, None::<&str>)?;
    let settings_item = MenuItem::with_id(app, "settings", "Settings…", true, None::<&str>)?;
    let flush_item = MenuItem::with_id(app, "flush", "Send pending now", true, None::<&str>)?;
    let quit_item = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
    let menu = Menu::with_items(
        app,
        &[&capture_item, &settings_item, &flush_item, &quit_item],
    )?;

    TrayIconBuilder::new()
        // A dedicated template icon, NOT the app icon. macOS template images are
        // drawn from the alpha channel alone — every opaque pixel is repainted in
        // the menu-bar foreground colour — so the glyph has to be the opaque part
        // and the backdrop transparent. The app icon is the exact inverse (an
        // opaque filled square with the mark painted on top), so using it here
        // rendered a solid block in the menu bar. Regenerate with
        // scripts/make_tray_icon.swift if the mark ever changes.
        .icon(tauri::include_image!("icons/tray-icon.png"))
        .icon_as_template(true)
        .tooltip("GTD Capture")
        .menu(&menu)
        .show_menu_on_left_click(true)
        .on_menu_event(|app, event| match event.id().as_ref() {
            "capture" => show_view(app, "capture"),
            "settings" => show_view(app, "settings"),
            "flush" => {
                let app = app.clone();
                tauri::async_runtime::spawn(async move {
                    flush_queue(&app).await;
                });
            }
            "quit" => app.exit(0),
            _ => {}
        })
        .build(app)?;
    Ok(())
}

// --------------------------------------------------------------------- main

fn main() {
    tauri::Builder::default()
        .manage(QueueLock(Mutex::new(())))
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_handler(|app, _shortcut, event| {
                    // Fires on both press and release; without this guard a
                    // single keypress toggles twice and nets out to nothing.
                    if event.state == tauri_plugin_global_shortcut::ShortcutState::Pressed {
                        toggle_capture(app);
                    }
                })
                .build(),
        )
        .invoke_handler(tauri::generate_handler![
            get_settings,
            save_settings,
            capture,
            queue_count,
            flush_now,
            test_connection,
            hide_window,
        ])
        .setup(|app| {
            let handle = app.handle().clone();

            // Menu-bar app, not a dock app: capture should never steal a dock
            // slot or an app-switcher position for a window that's hidden
            // ~100% of the time.
            #[cfg(target_os = "macos")]
            app.set_activation_policy(tauri::ActivationPolicy::Accessory);

            build_tray(&handle)?;

            let settings = read_settings(&handle);
            if let Err(e) = handle.global_shortcut().register(settings.hotkey.as_str()) {
                eprintln!("could not register hotkey {}: {e}", settings.hotkey);
            }

            // First run has no server configured, so surface the window rather
            // than starting silently in the tray. Which *view* it lands on is
            // the frontend's call (see ui/app.js `init`), deliberately not an
            // emit from here: at this point the webview may still be loading
            // and would miss the event, leaving first-run users on a capture
            // box they can't configure.
            if !settings.configured() {
                if let Some(window) = handle.get_webview_window("main") {
                    let _ = window.show();
                    let _ = window.set_focus();
                }
            }

            let flusher = handle.clone();
            tauri::async_runtime::spawn(async move {
                loop {
                    tokio::time::sleep(FLUSH_INTERVAL).await;
                    flush_queue(&flusher).await;
                }
            });

            Ok(())
        })
        .on_window_event(|window, event| {
            // Closing/blurring hides rather than exits — the app is its tray
            // icon, and a capture box that quit the process on Esc would mean
            // the hotkey silently stopped working.
            match event {
                tauri::WindowEvent::CloseRequested { api, .. } => {
                    api.prevent_close();
                    let _ = window.hide();
                }
                tauri::WindowEvent::Focused(false) => {
                    let _ = window.emit("window-blurred", ());
                }
                _ => {}
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running GTD Capture");
}

// -------------------------------------------------------------------- tests
//
// Only the pure decision logic is covered here — the parts that decide whether
// a capture is sendable and whether a failure is worth keeping. The queue's
// actual read/flush cycle needs a live AppHandle, so it's verified by running
// the app against a real server instead (see docs/task-breakdown.md).

#[cfg(test)]
mod tests {
    use super::*;
    use reqwest::StatusCode;

    fn settings(server_url: &str, token: &str) -> Settings {
        Settings {
            server_url: server_url.into(),
            token: token.into(),
            hotkey: DEFAULT_HOTKEY.into(),
        }
    }

    #[test]
    fn server_errors_are_retryable() {
        for code in [500, 502, 503, 504] {
            let status = StatusCode::from_u16(code).unwrap();
            assert!(status_is_retryable(status), "HTTP {code} should retry");
        }
    }

    #[test]
    fn backpressure_codes_are_retryable() {
        assert!(status_is_retryable(StatusCode::TOO_MANY_REQUESTS)); // 429
        assert!(status_is_retryable(StatusCode::REQUEST_TIMEOUT)); // 408
    }

    #[test]
    fn payload_rejections_are_not_retryable() {
        // The whole point of the queue distinction: an unchanged payload will
        // fail these forever, so they must surface instead of being swallowed.
        assert!(!status_is_retryable(StatusCode::UNAUTHORIZED)); // 401, bad token
        assert!(!status_is_retryable(StatusCode::BAD_REQUEST)); // 400, no title
        assert!(!status_is_retryable(StatusCode::NOT_FOUND)); // 404, wrong URL
        assert!(!status_is_retryable(StatusCode::FORBIDDEN)); // 403
    }

    #[test]
    fn capture_url_tolerates_trailing_slash_and_whitespace() {
        assert_eq!(
            settings("http://127.0.0.1:8000", "t").capture_url(),
            "http://127.0.0.1:8000/api/capture"
        );
        assert_eq!(
            settings("http://127.0.0.1:8000/", "t").capture_url(),
            "http://127.0.0.1:8000/api/capture"
        );
        assert_eq!(
            settings("  https://gtd.sudipto.dev///  ", "t").capture_url(),
            "https://gtd.sudipto.dev/api/capture"
        );
    }

    #[test]
    fn configured_requires_both_url_and_token() {
        assert!(settings("http://127.0.0.1:8000", "tok").configured());
        assert!(!settings("", "tok").configured());
        assert!(!settings("http://127.0.0.1:8000", "").configured());
        assert!(!Settings::default().configured());
        // Whitespace isn't configuration.
        assert!(!settings("   ", "tok").configured());
        assert!(!settings("http://127.0.0.1:8000", "   ").configured());
    }
}
