# GTD App — Task Breakdown & Session Findings

Companion to `solution-plan.md` (behavior/data authority) and `design.md` (look/feel authority). This file is the epic/subtask breakdown for implementation and a log of decisions confirmed during planning. Update checkboxes as work lands; one PR per step per the solution plan's rollout rule.

## Findings from planning session (2026-07-13)

- Reviewed `solution-plan.md`, `design.md`, and the `design-files/` prototypes (`app-today.png`, `clarify-overlay.png`, `options.png`, `lower.png`). The prototypes confirm the "Paper — light" direction (`1b` in `options.png`) is what `design.md` documents; a dark "Nocturne" alternative was explored and rejected — matches CLAUDE.md's "dark mode out of scope for v1."
- All three "open decisions" in `solution-plan.md` were revisited and **confirmed as their stated defaults** — no changes to the plan:
  - `due_date` field stays on `Task` (nullable), independent of calendar time-blocks.
  - Calendar week view uses **FullCalendar 6 via CDN**, not a hand-rolled grid.
  - Two-way sync conflict rule stays **last-write-wins by timestamp, GCal wins ties**.
- Repo has no git history yet. Decision: **`git init` locally as part of Step 1**, no remote configured yet (user will add one later).
- No existing sibling repo (tracker.sudipto.dev / futsal app / tax app) will be used as a scaffold template — **build the Django scaffold clean from `solution-plan.md` Step 1**, not mirrored from another project.
- Per user request, work **pauses after this plan is saved** for review before any code is written — do not start Step 1 implementation without explicit go-ahead.

## How to read this breakdown

- Epics = the plan's Steps 1–12 (already sequenced and staged as one-PR-each in `solution-plan.md`), grouped under the same M1–M4 milestones.
- Subtasks are extracted from each step's bullets/tests in `solution-plan.md`, plus the relevant `design.md` screen instructions where UI is involved.
- "Tests" lines from the solution plan are kept as explicit subtasks, not folded in — they're the acceptance criteria per step.
- Nothing here redefines behavior; if a subtask seems to conflict with `solution-plan.md`, the plan wins.

---

## Epic 0 — Repo bootstrap (precursor to Step 1)

- [ ] `git init`, initial commit of existing `docs/`, `design-files/`, `CLAUDE.md`.
- [ ] Add `.gitignore` (Python/Django/Node-free, `static/css/app.css` is committed per plan — do NOT ignore it; ignore `.env`, `__pycache__`, `*.pyc`, media uploads).
- [ ] Confirm Python 3.12 available locally for scaffold.

## Epic 1 — Project scaffold, auth, PWA shell (M1)

- [x] Django 5.x project `gtd`, single app `core`, Python 3.12.
- [x] `django-environ` config, Postgres via `psycopg`; local `.env` + `.env.example`. (Dev Postgres: existing shared `postgres-container` Docker instance, database `gtd` created, user `sudipto`.)
- [x] Tailwind standalone CLI (v3.4.17, matches `tailwind.config.js`/safelist conventions in `design.md`) wired to output committed `static/css/app.css` (no bundler); tokens from `design.md` §2 in `tailwind.config.js` `theme.extend` (never raw hex in templates); safelist stub for future dynamic-ish classes.
- [~] Self-hosted fonts in `static/fonts/` — `@font-face` rules wired in `static/css/input.css` but **actual woff2 binaries not yet sourced** (Bricolage Grotesque 600/700, Inter 400/500/600, JetBrains Mono 400/500). Follow-up needed before fonts actually render; currently falls back to system sans-serif/monospace.
- [x] Vendor Alpine.js + HTMX into `static/js/` (no CDN); also vendored SortableJS early since Steps 5 & 9 need it.
- [x] Django auth, single superuser via `createsuperuser` (username `sudipto`).
- [x] `LoginRequiredMiddleware` (Django 5.1+) covering every view; webhook + capture API routes don't exist yet (Steps 3/8) so no exemption needed yet — add `@login_not_required` when those land.
- [x] Settings hygiene: `DEBUG` from env (default False), no `django-browser-reload` in requirements.
- [~] `manifest.json` (name "GTD", standalone display) — present at `static/manifest/manifest.json`, but **icons 192/512 PNGs not yet generated** (referenced paths currently 404).
- [x] Minimal service worker: cache app shell + `/capture`; served from root path (`/service-worker.js`) for full-scope registration; explicitly no offline queue (v2).
- [x] `base.html`: desktop sidebar (w-60) / mobile bottom tab bar (Inbox · Today · ＋ · Calendar · Review); global header trust strip stub (`inbox N · review Nd ago` — values hardcoded to defaults until Epic 2/5 wire real counts).
- [x] Vendor Lucide SVG icons into `templates/icons/` (no icon font, no CDN) — 12 icons pulled for nav; more to be added per-screen as needed.
- [x] **Test:** smoke test — anonymous redirected to login, authenticated request renders base template with expected content. `python manage.py test core` passes (2/2).
- [x] **Rollback:** n/a (greenfield).
- Note: all other nav routes (`/inbox`, `/tasks`, `/projects`, etc.) exist as named URLs pointing at a shared placeholder view/template so the shell nav doesn't 404 — real screens land in their own epics.

## Epic 2 — Data model (M1)

- [x] Implement all models in `core/models.py` exactly as specified in `solution-plan.md` Step 2 (`Tag`, `Area`, `InboxItem`, `Task`, `Note`, `NoteAttachment`, `RecurringTemplate`, `TimeBlock`, `GoogleCredential`, `SyncChannel`, `ReviewConfig`, `ReviewSession`, `CaptureToken`, `NotificationLog`) — field lists are exhaustive, implement as written, do not redesign.
- [x] `CheckConstraint no_project_subtask` + `Meta.indexes` on `Task`. Also added `GinIndex` on `Note.search` (implied by the plan's "GIN index" comment on that field) and `django.contrib.postgres` to `INSTALLED_APPS` for `SearchVectorField`/`GinIndex` support.
- [x] Single initial migration (`core/migrations/0001_initial.py`).
- [x] Code-level semantics (not just schema):
  - [x] Project = `Task(is_project=True, parent=None)`; subtasks one level only (enforced by DB constraint, verified via test).
  - [x] `project.next_actions()` queryset helper implementing the three-state resolution (flagged → implicit first-incomplete → `NEEDS_ATTENTION`); returns `(state, [tasks])`.
  - [x] Trash = `list=TRASH` / `trashed_at`; `Task.objects.purgeable(as_of=, days=30)` queryset method (cron wiring itself is Step 12).
  - [x] Completing a project with incomplete subtasks: `Task.complete(force=False)` returns `False` (blocked) unless `force=True`, in which case subtasks are completed too. UI wiring for the confirm dialog is Step 5.
- [x] **Test:** model constraints (subtask-must-have-project-parent, both directions), `next_actions()` all three states + no-subtasks edge case, `complete()` blocked/forced paths, trash purge query (old vs. recent vs. non-trashed). 11/11 passing. Manually verified via Django admin (all 14 models registered and browsable) and confirmed the check constraint + GIN index exist in Postgres via `psql \d`.
- [x] **Rollback:** migration revert (greenfield tables) — not exercised, but standard `migrate core 0001` / squash path applies.

## Epic 3 — Capture (M1)

- [x] `/capture`: autofocused title input + collapsed "+ details" description disclosure (per `design.md` "Capture" screen spec — text-xl input, 400ms water-flash on submit, last-3-captured faded list below).
- [x] HTMX POST `/inbox/items/` → clears + refocuses for rapid-fire capture. (Alpine `x-init` refocuses `$refs.title` after each HTMX swap.)
- [x] Global "+" header button opens same form in a modal on every page (desktop header only — mobile already has a dedicated bottom-tab "+" that opens the full `/capture` page, which doubles as the PWA `start_url`). Modal fragment fetched fresh via `hx-get` each open so state never goes stale.
- [x] PWA `start_url: /capture` behavior when launched from home screen (set in Epic 1's `manifest.json`, confirmed still correct).
- [x] `POST /api/capture`: Bearer `CaptureToken` auth, `{"title": str, "description": str?}` → `201 {"id": …}`, 60/min rate limit (cache-based fixed window), CSRF-exempt, login-exempt (`@login_not_required`, Django 5.1).
- [x] Settings page: step-by-step iOS Shortcut setup instructions (Share Sheet → POST → Notification) + token create/revoke UI (HTMX partial swap, token value shown once on creation).
- [x] Inbox row **Done** button (2-minute rule): `done_directly=True, processed_at=now`, never becomes a Task.
- [x] Inbox screen per `design.md`: newest-first, stripped rows, "Process inbox →" primary button with count, empty state copy verbatim from §9 ("Inbox zero." / "Capture anything on your mind — filtering happens later.").
- [x] **Test:** API auth (valid/invalid/missing token, login-exemption, rate limit), done-directly path (never creates a Task, drops out of inbox list). 8 new tests, 19/19 total passing.
- [x] **Rollback:** remove routes.
- **Bug found and fixed during manual verification:** the HTMX `Done` button (a bare button, not inside a `<form>`) had no CSRF token and 403'd. Fixed by adding `hx-headers='{"X-CSRFToken": "{{ csrf_token }}"}'` to `<body>` in `templates/base.html` so every HTMX request carries it — a pattern the later epics (reorder, clarify wizard, etc.) will also depend on.
- Not yet implemented: the "Clarify" button on each inbox row and the "Process inbox →" button both currently point at a stub (`inbox_process`) — the real one-at-a-time wizard is Epic 4.

## Epic 4 — Clarify wizard (M1)

- [x] `focus_card.html` component per `design.md` §4 (max-w-xl, top progress bar, step counter, keyboard 1–4/Enter/Esc) — implemented as `templates/components/focus_card_base.html`; keyboard handling is a window-level Alpine `@keydown` that clicks `[data-wizard-key]` elements, Esc routes to Inbox.
- [x] "Process Inbox" entry point, oldest-first, one-at-a-time, no cherry-picking, auto-advance after each decision — `core/clarify.py::process_start`/`_next_item_or_none` (ordered `created_at, id`); per-row Inbox "Clarify" link deliberately routes through this same entry point rather than deep-linking a specific item, preserving no-cherry-picking.
- [x] Screen 1 "Is it actionable?": quoted inbox item in grey inset; No → Trash/Someday/Reference; Yes → screen 2.
- [x] Trash path → unified trash view (Task-to-trash, not raw InboxItem discard).
- [x] Someday path → Task form pre-filled, `list=SOMEDAY`.
- [x] Reference path → Note form pre-filled (title/description → title/body).
- [x] Screen 2 "Actionable path": 2-minute helper + "Did it — Done" button; else Single action / Project / Delegate.
- [x] Single action → Task form (title, description, contexts/tags live parser, horizon default Anytime, optional due date, area).
- [x] Project → same form + `is_project=True` + inline first-subtasks repeater; first subtask auto-flagged `is_next_action=True`; form refuses to save with zero subtasks (re-renders with an error, item stays unprocessed).
- [x] Delegate → Waiting For form (`waiting_on`, follow-up days default 5, `waiting_since=today`).
- [x] `processed_at` set on completion; progress bar "N / M" (progress is session-tracked processed-count + still-unprocessed count, recomputed each render so new captures mid-session extend the total instead of corrupting it); finish screen "Inbox zero 🎉" (the one place celebration is allowed, per `design.md` §7 — single subtle burst, not looping).
- [x] Inline tag parser (shared util, reused in Step 5): `@([a-z0-9\-]+)` context tag, `#([a-z0-9\-]+)` plain tag, get-or-create + case-fold, tokens stay in text, M2M synced additively on save — implemented in `core/tagging.py` (`extract_tags`/`sync_tags_from_text`); regex requires the `@`/`#` to be at start-of-text or preceded by whitespace (deliberate boundary fix over the plan's literal regex, so `john@example.com` / `...#comment` don't get misread as tags — see comment in `core/tagging.py`). Alpine typeahead after `@`/`#` implemented (`static/js/tag-typeahead.js` + `core/partials/field_tagged.html`, wired onto the description/body fields in someday/reference/single/project/delegate) — suggests from all existing `Tag` names client-side, server-side parsing in `tagging.py` remains the source of truth.
- [x] **Test:** each decision path produces the right entity; strict one-at-a-time ordering; parser create/reuse/case-fold/no-dupes. 20 new tests added to `core/tests.py` (`ClarifyWizardTests`, `TagParserTests`), 39/39 passing.
- [x] **Rollback:** wizard routes off; inbox remains a plain list (routes are independent entries in `core/urls.py`, no shared state to unwind).

## Epic 5 — Lists, projects, contexts, ordering, horizons (M1)

- [x] `/today`: curated section (horizon=today + today's TimeBlocks + due today/overdue + overdue recurring instances) with Big-3 pinned first, missed-block strip, block-time-then-manual ordering; collapsible "Anytime — pick from here" with context filter chips and "→ Today" quick action; Q2-chip violet left border. Missed-block strip's "Reschedule" link currently points at the `calendar_page` stub (real rescheduling is Epic 8).
- [x] `/week`, `/month`: same composition pattern (horizon match OR due within the remaining week/month window) — no Anytime sub-section on these two, matching `design.md`'s Key Screens section (only Today documents one).
- [x] `/tasks` (Next Actions): all `list=NEXT` non-project tasks, subtasks shown here AND under their project; filters (context, tag, horizon, area, "next actions only" — computed by grouping subtasks per project and calling `next_actions()` once per project, not per row).
- [x] `/projects`: cards with progress bar, next-action line, `stalled?`/`no next →` badges (`stalled?` = `NEEDS_ATTENTION` state, `no next →` = `implicit` state — see `core/projects.py::_project_state_badge`); project detail (description, drag-reorder subtask list, flag-as-next toggle via clickable marker dot, calendar allocation panel stub for Step 8, inline add-subtask); stalled banner per `design.md` copy §9. Plain task "Edit" and "Convert to note" (§4's ⋮ menu) are **not implemented** — deferred, no dedicated task-edit screen exists yet in any epic.
- [x] `/waiting`: sorted by `waiting_since`, overdue-follow-up tinted rows (`bg-amber-bg/40`), *Got it*/*Nudge sent* actions.
- [x] `/someday`: Activate → NEXT.
- [x] Trash view: restore / purge now, 30-day auto-purge note.
- [x] `task_row.html` component per `design.md` §4 (complete-circle HTMX PATCH + 150ms fade, next-action dot markers — clickable when `flag_url` passed, project folder+progress pill, ⋮ menu with Move-to-Someday/Waiting/Trash only — Edit/Block-time/Convert-to-note deferred, see above).
- [x] SortableJS drag handles on every list → HTMX PATCH `/tasks/<id>/reorder/` (via `htmx.ajax()` from `static/js/sortable-lists.js`, listening on `htmx:load` since `hx-boost` means `DOMContentLoaded` only fires once); server rewrites `sort_order` in steps of 100, renumber on collision. Known limitation: `/tasks` mixes top-level tasks and subtasks from different projects in one visual drag container — reordering is still scoped correctly server-side (siblings = same `parent`+`is_project`+`list`), but dropping next to a task from a *different* group falls back to "insert at front of my own group" rather than a precise position, since SortableJS doesn't know about the sub-grouping. Project detail's subtask list doesn't have this problem (one homogeneous group).
- [x] `rollover` cron logic (nightly): `this_week` carry-over Monday 00:05, `this_month` on the 1st, `today` daily; `carried_over_count += 1`; "↩ ×N" badge. `core/management/commands/rollover.py`, `--as-of YYYY-MM-DD` for synthetic-date testing. (Cron *registration* is Step 12; the command logic belongs here.)
- [x] `/tags` manager: usage counts, context toggle, slug-safe rename, merge (re-point M2M + delete source), delete with confirm; >7-context nag banner (`design.md` §9 copy).
- [x] `badge.html`, `chip.html`, `filter_bar.html`, `empty_state.html` components per `design.md` §4. Badge status→class strings live in `core/templatetags/gtd_extras.py` (Python, not a template) — `tailwind.config.js`'s `content` list had to add `./core/templatetags/**/*.py` so the compiler's scanner still sees those literal class tokens.
- [x] **Test:** Today view composition (all four inclusion rules), reorder persistence (incl. cross-parent isolation), carry-over cron on synthetic dates (today/week/month + completed-task exclusion), tag-merge correctness (incl. merge-into-self no-op), project badge states, screen-render smoke tests (empty + populated) for every new screen. 31 new tests, 70/70 passing.
- [x] **Rollback:** each view independent; disable route.

## Epic 6 — Notes (Reference) + search (M1)

- [x] `/notes`: Postgres `SearchVector` (title+body) updated via `post_save` signal (`core/signals.py`, registered in `CoreConfig.ready()`), GIN index already existed from Epic 2; tag filter (plain `#tag` chips only, not `@context` — Notes don't carry contexts); detail view with rendered markdown (`markdownify` filter in `core/templatetags/gtd_extras.py`, using the new `Markdown` dependency — added to `requirements/base.txt`, no HTML sanitization pass since it's a single-author single-user system); attachments (`MEDIA_ROOT`, 20MB cap enforced in `core/notes.py::note_attachment_upload`, nginx `X-Accel-Redirect` for private serving is Epic 12); inline edit (Alpine view/edit toggle on `note_detail.html`, editing is additive-tag-sync like everywhere else).
- [x] Inbox → Note conversion (Step 4's Reference path, `core/clarify.py::clarify_reference`) — re-verified against the real Notes module now that it exists and is searchable (`InboxReferenceConversionTests`).
- [x] Task → Note conversion ("this turned out to be reference"): `core/notes.py::task_convert_to_note` copies title/description and tags (direct M2M copy, not text re-parse), trashes the source task; wired into `task_row.html`'s ⋮ menu via `core/lists.py::_menu_moves`.
- [x] **Test:** FTS matches on body and title text, excludes trashed notes; conversion preserves tags (both directions); markdown rendering; soft-delete; oversized-attachment rejection. 20 new tests, 81/81 passing. Attachment-upload tests run under an isolated temp `MEDIA_ROOT` (`@override_settings`) so they don't leave files in the real `media/` — caught after an initial run polluted it.
- [x] **Rollback:** independent module.

**— M1 milestone checkpoint: full offline GTD system usable end-to-end (capture, clarify, all lists, contexts, notes, ordering, horizons) —**

## Epic 7 — Recurrence engine (M2)

- [x] `/recurring`: `RecurringTemplate` CRUD (`core/recurring.py`); rule builder (frequency/weekday/interval) → RRULE via a hand-rolled `build_rrule`/`parse_rrule` pair (round-trip tested) rather than constructing the string through `dateutil` directly — `dateutil.rrule` has no RRULE-string *serializer* (only `rrulestr` to parse one), so the string is built manually and `rrulestr` is what actually does the "via python-dateutil" occurrence generation in the materializer; optional standing block (start time + duration) fields save straight onto the existing `RecurringTemplate` fields.
- [x] `materialize_recurring` cron command (hourly, `core/management/commands/materialize_recurring.py`): generate occurrences `last_materialized_until` → `today + 14 days`; create `Task(list=NEXT, occurrence_date=…, horizon=TODAY if due today else ANYTIME)`; `--as-of YYYY-MM-DD` for synthetic-date testing, matching `rollover`'s convention.
- [x] Unique constraint `(recurring_template, occurrence_date)` for idempotence — added as `Task.Meta.constraints` (`unique_recurring_occurrence`, partial on `recurring_template__isnull=False`) in migration `0002_task_unique_recurring_occurrence`; this wasn't in Epic 2's original field list but is explicitly required by this step's spec, so it's an addition, not a redesign.
- [x] Today view inclusion rule: instances with `occurrence_date <= today` and incomplete — **already implemented in Epic 5**, re-confirmed here now that the materializer actually populates data (`MaterializeRecurringTests`).
- [x] Overdue pile-up: "overdue since {date}" badge (`Task.is_overdue_recurring`/`overdue_since_label` properties, rendered via `task_row.html`'s existing `overdue` badge kind), no replacement of prior instances; bulk actions "complete all overdue" / "trash all overdue" on recurring detail page.
- [x] Calendar linkage: implemented once Epic 8 landed — `core/recurring.py::_sync_gcal_event` creates one recurring GCal event mirroring the RRULE when a template has a standing block (start time + duration) and Google is connected; edits patch it, deactivating deletes it, reactivating re-creates it. No-op (gated on `get_credential()`) when Google isn't connected.
- [x] Completing an instance leaves the recurring GCal event untouched — the standing-block event lives on `RecurringTemplate`, not on the instance `Task`, so `retitle_task_blocks` (which only touches a completed *instance's* own `TimeBlock`s, and recurring instances never get per-instance TimeBlocks per this same step's spec) never looks anywhere near it.
- [x] **Test:** materializer run-twice idempotence, RRULE round-trip, pile-up query (badge presence, bulk actions, completing one instance doesn't affect siblings), unique-constraint enforcement, screen smoke tests. 25 new tests, 98/98 passing.
- [x] **Rollback:** deactivate templates; instances remain ordinary tasks.

## Epic 8 — Google Calendar integration (M2)

**Status: implemented and unit-tested with mocks, awaiting the user's manual Google Cloud Console setup before this epic can be verified end-to-end and committed — see the note at the end of this section.**

- [x] Dependencies: `google-auth`, `google-auth-oauthlib`, `google-api-python-client`, `cryptography` (Fernet) — added to `requirements/base.txt`; env vars `GOOGLE_CLIENT_ID/SECRET`, `GOOGLE_OAUTH_REDIRECT`, `FERNET_KEY` added to `gtd/settings.py` (`.env.example` already had placeholders from Epic 1 planning). `NTFY_TOPIC` deferred to Epic 10, which is where it's actually read.
- [x] **8a Connect flow:** `core/google_calendar.py` — OAuth2 web flow (`calendar` scope, `access_type=offline&prompt=consent`) via `google_auth_oauthlib.flow.Flow`; callback (`google_callback`) validates the session-stored `state`, stores the Fernet-encrypted refresh token in a singleton `GoogleCredential`, creates the secondary "GTD" calendar on first connect, registers a watch channel (`register_watch_channel`). **The one-time Google Cloud Console setup (project, OAuth consent screen, web client credentials, enable Calendar API) has NOT been done and cannot be done by the agent** — needs the user, see below.
- [x] **8b TimeBlocks app→GCal:** `core/timeblocks.py`. Scope note: the task-breakdown's "mini week view via FullCalendar" for the project detail "Calendar time" panel was simplified to a plain start/end form posting to the same `timeblock_create` endpoint — a second embedded FullCalendar instance felt like complexity without much payoff given this can't be visually verified in this environment anyway (no browser access here — see below). The full `/calendar` page **does** use real FullCalendar 6 (via CDN, the one confirmed exception to the no-CDN rule) with drag/resize wired to `timeblock_update` via `eventDrop`/`eventResize`; it does not support click-drag-*create* (new blocks always need a task to attach to, hence the form-based create path). Completing a task retitles every non-completed block's GCal event to `✓ <title>` and sets `status=COMPLETED` (`core/timeblocks.py::retitle_task_blocks`, called from `Task.complete()`).
- [x] `calendar.css` token overrides for FullCalendar per `design.md` §2/§5.
- [x] **8c GCal→app two-way:** `POST /gcal/webhook` (`core/google_calendar.py::gcal_webhook`, `@login_not_required`) validates `X-Goog-Channel-ID`/`X-Goog-Resource-ID` against `SyncChannel` (hardened to 404 rather than 500 on a malformed/non-UUID channel id); `sync_calendar()` does incremental sync via `events.list(syncToken=…)`, matches `gcal_event_id` to update a block or delete it on `status=cancelled` (unmatched events ignored), and falls back to a full resync on a 410. Conflict rule implemented literally as specified: GCal wins unless our `last_synced_at` is *strictly* newer. `renew_gcal_channels` (daily) and `sync_gcal` (15-min polling fallback) management commands.
- [x] **8d Missed-block engine:** `detect_missed_blocks` command (15-min): `end < now`, `status=SCHEDULED`, task incomplete → `status=MISSED`, `missed_block_count += 1` (atomic `F()` increment); the "Today Missed — reschedule strip" and "⚠ ×N" badge were **already wired in Epic 5** against this same query/field, so they light up automatically. The ntfy nag itself is a no-op stub (`_notify_missed_block` in the command) — real dispatch is Epic 10's `notify()` helper; this is only the wiring point.
- [x] Went back and finished Epic 7's `RecurringTemplate` calendar linkage (`core/recurring.py::_sync_gcal_event`), which that epic had explicitly deferred to here: a standing-block template gets one recurring GCal event (`recurrence: ["RRULE:..."]`) seeded from its next matching occurrence date; create/edit patches it, deactivate deletes it, reactivate re-creates it; no-op without a connected credential.
- [x] **Test:** 38 new tests, 136/136 passing — OAuth callback (mocked `Flow`/`GoogleCalendarClient.create_gtd_calendar`/`register_watch_channel`), state-mismatch rejection, disconnect wipes credential+channels, `GoogleCalendarClient`'s insert/patch/delete/list calls (mocked at the `_service()` boundary), webhook validation (unknown channel → 404, valid → 200 + sync triggered, login-exempt), sync-token 410 → full resync, conflict rule (tie → GCal wins, strictly-newer-local → local wins, `cancelled` → delete, unmatched → ignored), missed-block transition (+ completed-task and future-block non-transitions), retitle-on-complete (with and without a connected credential), TimeBlock create/update/delete views, calendar page/events.json/settings smoke tests, channel-renewal and polling-fallback commands, `RecurringTemplate` GCal linkage (create/patch/delete/no-op-without-standing-block). Two real bugs the tests caught before they could ever reach a real Google account: `_save_template` was assigning `block_start_time`/`block_duration_min` straight from `request.POST` as raw strings onto the in-memory `template` instance and then immediately calling `_sync_gcal_event(template)` on that *same* instance — Django's `TimeField`/`PositiveSmallIntegerField` only coerce strings on the way *out* of the DB, not on plain attribute assignment, so `datetime.combine()`/`timedelta(minutes=...)` would have thrown `TypeError` the first time anyone saved a recurring template with a standing block. Fixed by parsing both explicitly before assignment.
- [x] **Rollback:** "Disconnect Google" (`google_disconnect`) wipes `GoogleCredential` + all `SyncChannel` rows; every GCal-touching function checks `get_credential()`/`GoogleCredential.objects.exists()` first and no-ops or stays local-only when absent — verified by `RetitleOnCompleteTests.test_completing_task_marks_blocks_completed_without_credential` and `TimeblockViewTests.test_create_without_credential_is_local_only`.

**Why this epic is paused here:** per the user's explicit instruction for this run, Epic 8 (and 10, 12) implement + unit-test with mocks and then stop before the final commit, because they depend on a manual step outside the agent's control:
1. Google Cloud Console: create a project, configure the OAuth consent screen (internal/testing, the user's Gmail as test user), create web client credentials, enable the Calendar API, and put the resulting `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` in `.env`.
2. Generate a `FERNET_KEY` (`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`) and add it to `.env`.
3. Only then can the real OAuth connect flow, real event insert/patch/delete, and real webhook delivery be exercised end-to-end against an actual Google account — everything up to that point has been verified against mocks, not the live API.

**— M2 milestone checkpoint: recurrence + full two-way calendar —**

## Epic 9 — Reflect: reviews, Eisenhower board, Big-3 (M3)

- [ ] Onboarding banner until all four `ReviewConfig`s set; saving a config creates its recurring GCal event.
- [ ] Weekly Review wizard (`/review/weekly`, resumable via `phase_state`):
  - [ ] Get Clear: inbox-to-zero gate (or explicit skip) + mind-sweep capture box.
  - [ ] Get Current (a): projects checklist with 🟡/🔴 resolving actions inline.
  - [ ] Get Current (b): carried-over queue, one-by-one, Keep/Demote/Someday/Trash, hard gate (cannot proceed past unresolved items).
  - [ ] Get Current (c): Waiting For overdue pass (nudged/got it/drop).
  - [ ] Get Current (d): calendar pass (last 2 weeks capture box + next 2 weeks preview).
  - [ ] Get Current (e): Eisenhower board — 2×2 drag (SortableJS), active projects as cards, per-quadrant drop actions (Q1 checkmark/prompt, Q2 slot picker + `q2_week` set, Q3 delegate/someday, Q4 someday/trash); board state never persisted; review-only, per `design.md` layout spec (quadrant tints, axis labels, inline flip-to-action-UI on drop).
  - [ ] Get Creative: Someday Activate list, free capture box, Big-3 picker (auto-clear previous stars, max 3).
  - [ ] Finish: `completed_at`, streak toast, stats snapshot stored.
- [ ] Monthly wizard: Areas pass (per-Area health + capture box), Someday deep pass, `this_month` carry-over horizon check.
- [ ] Quarterly/Yearly: static guided checklists (1–2yr goals / vision & principles prompts) + capture boxes, tracked in `ReviewSession`.
- [ ] Enforcement: GCal recurring blocks (from config save), ntfy T-15min reminder + overdue daily nag, in-app persistent banner + Today header "Last review: N days ago" amber/red thresholds, rotating dismissible "GTD tip" strip (§8.1 pitfalls copy).
- [ ] **Test:** wizard resume, carried-over gate, Eisenhower drop actions (each quadrant → correct mutation), Big-3 auto-clear, streak computation.
- [ ] **Rollback:** reviews additive; disable routes; GCal review events removable from settings.

## Epic 10 — Notifications (ntfy) (M3)

- [ ] `notify(kind, title, message, url, priority)` helper → `POST https://ntfy.sh/<NTFY_TOPIC>` with deep link; document choosing a high-entropy topic name.
- [ ] `NotificationLog` dedupe (one per kind+ref+day).
- [ ] Kinds/timing: `missed_block` (immediate), `review_reminder` (T-15min), `review_overdue` (daily 09:00), `follow_up_due` (daily digest), `recurring_overdue` (daily 09:00 count-based).
- [ ] Settings page: per-kind toggles + test-fire button.
- [ ] **Test:** dedupe, digest batching, toggle respected.
- [ ] **Rollback:** `NTFY_TOPIC` unset → no-op.

**— M3 milestone checkpoint: guided reviews, Eisenhower, Big-3, nags —**

## Epic 11 — Stats (M4)

- [ ] `/stats` (Chart.js via CDN, single `water` accent, no multicolor): completions/day (30d) and /week (12wk), review streak + last-completed per cadence, inbox-zero event count, missed-block rate (4wk), median capture→clarify latency, 2-minute-rule count. All live aggregate queries, no denormalized tables.
- [ ] **Test:** each aggregate against fixture data.

## Epic 12 — Deployment & ops (M4)

- [ ] EC2 Ubuntu, gunicorn (systemd `gtd.service`), nginx vhost `gtd.sudipto.dev` + certbot TLS, local Postgres, `MEDIA_ROOT` via nginx `X-Accel-Redirect` (private attachments).
- [ ] Env vars: `SECRET_KEY, DATABASE_URL, ALLOWED_HOSTS, GOOGLE_*, FERNET_KEY, NTFY_TOPIC`.
- [ ] Cron table: `*/15 sync_gcal`, `hourly materialize_recurring`, `0:05 daily rollover`, `9:00 daily daily_digest`, `3:00 daily renew_gcal_channels`.
- [ ] Nightly `pg_dump` to S3, 14-day retention.
- [ ] Logging: Django file logs + gunicorn journal; sync errors logged with event ids.
- [ ] **Rollback:** systemd stop; each cron independent.

**— M4 milestone checkpoint: stats + hardened ops, v1 complete —**

---

## Explicitly out of scope (v2 backlog — do not implement)

Email-to-inbox capture; offline PWA queue; creating tasks from raw GCal events; multi-user; natural-language capture parsing; Areas on Notes; AI features.

## Blocking external actions (not automatable by the agent)

- Google Cloud Console: create project, configure OAuth consent screen (internal/testing, Sudipto's Gmail as test user), create web client credentials, enable Calendar API — needed before Epic 8 can be tested end-to-end, though Epic 8's code can be written and unit-tested (mocked client) beforehand.
- Choosing/registering the ntfy topic name — needed before Epic 10 can be tested end-to-end.
- EC2 provisioning, DNS for `gtd.sudipto.dev`, nginx/certbot setup — needed for Epic 12.

None of these block Epics 0–7 or 9–11's core logic; they only block the final integration test of the epics that touch them.
