# GTD Capture — desktop client

A capture-only companion to the GTD web app for macOS and Windows. It lives in
the menu bar / system tray, opens on a global hotkey, takes a title and optional
notes, and POSTs them to `/api/capture` as an `InboxItem`. Nothing else: no
lists, no clarify, no offline copy of your data. Clarifying stays in the web app,
which is the point — capture should never turn into a place you browse.

## Why it exists

The PWA already covers this on a phone, but on a desktop "open browser → find
tab → click capture" is enough friction to lose a thought. `Cmd+Shift+Space` →
type → `Enter` is not.

## How it fits the server

It's a plain client of the same endpoint the iOS Shortcut uses — see
`core/api.py`. No Django changes are needed to run it beyond what's already
committed: it authenticates with a `CaptureToken` bearer token and sends
`{"title", "description", "source": "desktop"}`.

## Setup

1. Create a token: Django admin → **Capture tokens** → add one labelled `Mac`
   or `Windows`. Use a separate token per machine so one can be revoked without
   killing the others.
2. Launch the app. On first run (no server configured) it opens Settings.
3. Enter the server URL (e.g. `https://gtd.sudipto.dev`) and the token, then hit
   **Test connection** — it drops a real test item in your inbox.

Settings and the pending queue live in the OS app-data dir:

- macOS: `~/Library/Application Support/dev.sudipto.gtd.capture/`
- Windows: `%APPDATA%\dev.sudipto.gtd.capture\`

The token is stored in plaintext in `settings.json`, protected only by file
permissions — the same posture as the `.env` on the server. It's a capture-only
credential (it can create inbox items and nothing else), which is what makes
that acceptable here; don't reuse this pattern for a token with read or delete
scope.

## Offline behaviour

If the POST fails for a *retryable* reason (no network, 5xx, 429), the item goes
to `queue.json` and the box says "Saved locally". A background task retries every
30s, and the tray menu has **Send pending now**. A pending count shows in the
capture window's header.

Non-retryable failures (401 bad token, 400 bad payload) are *not* queued —
they'd fail identically forever. Those surface as a red error in the window so
you can fix the cause.

## Keys

| Key | Action |
| --- | --- |
| `Cmd/Ctrl+Shift+Space` | Toggle the capture box (configurable in Settings) |
| `Enter` | Capture (from the title field) |
| `Cmd/Ctrl+Enter` | Capture (from anywhere) |
| `Esc` | Dismiss |

Clicking outside the card dismisses it too — but only when it's empty, so a
half-typed thought is never thrown away by a stray click.

## Development

Requires the Rust toolchain (`rustup`) and Node (for the Tauri CLI only).

```bash
cd desktop
npm install
npm run dev      # hot-reloads the UI; Rust changes trigger a recompile
npm run build    # produces a .dmg/.app (macOS) or .msi/.exe (Windows)
npm run icons    # regenerate icons from static/icons/app/icon-512.png
```

The frontend in `ui/` is plain HTML/CSS/JS served directly by Tauri — **no
bundler and no build step**, matching the main repo's no-build-pipeline rule.
`npm` is only here to vendor the Tauri CLI. The palette in `ui/style.css` is
hand-copied from `docs/design.md` §2 rather than shared with Tailwind; if those
tokens are ever recolored again, this file needs the same edit by hand.

All logic that can fail (HTTP, disk, queueing) is in `src-tauri/src/main.rs`;
the webview is a dumb form that calls `capture` and renders the result.

### Building for the other platform

Tauri does not meaningfully cross-compile — a Windows `.msi` has to be built on
Windows and a macOS `.dmg` on macOS. Build each on its own machine, or add a
matrix GitHub Actions job if that ever gets tedious.

### Signing — why no Apple Developer ID is needed

Builds are **ad-hoc signed** (`bundle.macOS.signingIdentity: "-"`), not signed
with a paid Developer ID. For running it on the Mac that built it, that is
enough, and there is nothing extra to do:

```bash
npm run build
cp -R "src-tauri/target/release/bundle/macos/GTD Capture.app" /Applications/
open "/Applications/GTD Capture.app"     # launches, no prompt
```

Gatekeeper only blocks apps carrying a `com.apple.quarantine` xattr, which is
attached by whatever *downloads* them (browser, AirDrop, Slack). An app you
compiled locally never gets that flag, so Gatekeeper is never consulted —
`spctl -a` will still say "rejected", but that verdict only gets read for
quarantined apps, so it doesn't reflect what happens on launch. Verified: a
`open`-from-`/Applications` launch (identical path to a Finder double-click)
starts clean with no dialog.

The ad-hoc signature is worth having anyway, for a reason unrelated to
Gatekeeper: it gives the bundle a stable code identity (`dev.sudipto.gtd.capture`
rather than a per-build random `gtd_capture-<hash>`). macOS keys TCC permission
grants to code identity, so without it every rebuild can look like a brand-new
app and re-prompt.

Where a Developer ID *would* be needed: copying the `.dmg` to another machine
(it'd arrive quarantined). If that ever comes up, `xattr -cr "/Applications/GTD
Capture.app"` on the receiving Mac strips the flag and is still cheaper than
$99/yr for one user.
