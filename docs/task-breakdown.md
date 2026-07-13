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

- [ ] `focus_card.html` component per `design.md` §4 (max-w-xl, top progress bar, step counter, keyboard 1–4/Enter/Esc).
- [ ] "Process Inbox" entry point, oldest-first, one-at-a-time, no cherry-picking, auto-advance after each decision.
- [ ] Screen 1 "Is it actionable?": quoted inbox item in grey inset; No → Trash/Someday/Reference; Yes → screen 2.
- [ ] Trash path → unified trash view (Task-to-trash, not raw InboxItem discard).
- [ ] Someday path → Task form pre-filled, `list=SOMEDAY`.
- [ ] Reference path → Note form pre-filled (title/description → title/body).
- [ ] Screen 2 "Actionable path": 2-minute helper + "Did it — Done" button; else Single action / Project / Delegate.
- [ ] Single action → Task form (title, description, contexts/tags live parser, horizon default Anytime, optional due date, area).
- [ ] Project → same form + `is_project=True` + inline first-subtasks repeater; first subtask auto-flagged `is_next_action=True`.
- [ ] Delegate → Waiting For form (`waiting_on`, follow-up days default 5, `waiting_since=today`).
- [ ] `processed_at` set on completion; progress bar "N / M"; finish screen "Inbox zero 🎉" (the one place celebration is allowed, per `design.md` §7 — single subtle burst, not looping).
- [ ] Inline tag parser (shared util, reused in Step 5): `@([a-z0-9\-]+)` context tag, `#([a-z0-9\-]+)` plain tag, get-or-create + case-fold, tokens stay in text, M2M synced additively on save; Alpine typeahead after `@`/`#`.
- [ ] **Test:** each decision path produces the right entity; strict one-at-a-time ordering; parser create/reuse/case-fold/no-dupes.
- [ ] **Rollback:** wizard routes off; inbox remains a plain list.

## Epic 5 — Lists, projects, contexts, ordering, horizons (M1)

- [ ] `/today`: curated section (horizon=today + today's TimeBlocks + due today/overdue + overdue recurring instances) with Big-3 pinned first, missed-block strip, block-time-then-manual ordering; collapsible "Anytime — pick from here" with context filter chips and "→ Today" quick action; Q2-chip violet left border.
- [ ] `/week`, `/month`: same composition pattern against `this_week`/`this_month` + due window.
- [ ] `/tasks` (Next Actions): all `list=NEXT` non-project tasks, subtasks shown here AND under their project; filters (context, tag, horizon, area, "next actions only").
- [ ] `/projects`: cards with progress bar, next-action line, `stalled?`/`no next →` badges; project detail (description, drag-reorder subtask list, flag-as-next toggle, calendar allocation panel stub for Step 8, inline add-subtask); stalled banner per `design.md` copy §9.
- [ ] `/waiting`: sorted by `waiting_since`, overdue-follow-up tinted rows, *Got it*/*Nudge sent* actions.
- [ ] `/someday`: Activate → NEXT.
- [ ] Trash view: restore / purge now, 30-day auto-purge note.
- [ ] `task_row.html` component per `design.md` §4 (complete-circle HTMX PATCH + 150ms fade, next-action dot markers, project folder+progress pill, ⋮ menu).
- [ ] SortableJS drag handles on every list → HTMX PATCH `/tasks/<id>/reorder/`; server rewrites `sort_order` in steps of 100, renumber on collision.
- [ ] `rollover` cron logic (nightly): `this_week` carry-over Monday 00:05, `this_month` on the 1st, `today` daily; `carried_over_count += 1`; "↩ ×N" badge. (Cron *registration* is Step 12; the command logic belongs here.)
- [ ] `/tags` manager: usage counts, context toggle, slug-safe rename, merge (re-point M2M + delete source), delete with confirm; >7-context nag banner (`design.md` §9 copy).
- [ ] `badge.html`, `chip.html`, `filter_bar.html`, `empty_state.html` components per `design.md` §4.
- [ ] **Test:** Today view composition (all four inclusion rules), reorder persistence, carry-over cron on synthetic dates, tag-merge correctness.
- [ ] **Rollback:** each view independent; disable route.

## Epic 6 — Notes (Reference) + search (M1)

- [ ] `/notes`: Postgres `SearchVector` (title+body) updated via `post_save` signal, GIN index; tag filter; detail view with rendered markdown; attachments (`MEDIA_ROOT`, nginx-served later, 20MB cap); inline edit.
- [ ] Inbox → Note conversion (already wired in Step 4's Reference path — verify here).
- [ ] Task → Note conversion ("this turned out to be reference"): copy fields, trash the task.
- [ ] **Test:** FTS returns match on body text; conversion preserves tags.
- [ ] **Rollback:** independent module.

**— M1 milestone checkpoint: full offline GTD system usable end-to-end (capture, clarify, all lists, contexts, notes, ordering, horizons) —**

## Epic 7 — Recurrence engine (M2)

- [ ] `/recurring`: `RecurringTemplate` CRUD; rule builder (frequency/weekday/interval) → RRULE via `python-dateutil`; optional standing block (start time + duration).
- [ ] `materialize_recurring` cron command (hourly): generate occurrences `last_materialized_until` → `today + 14 days`; create `Task(list=NEXT, occurrence_date=…)`; unique constraint `(recurring_template, occurrence_date)` for idempotence; advance `last_materialized_until`.
- [ ] Today view inclusion rule: instances with `occurrence_date <= today` and incomplete.
- [ ] Overdue pile-up: "overdue since {date}" badge, no replacement of prior instances; bulk actions "complete all overdue" / "trash all overdue" on recurring detail page.
- [ ] Calendar linkage: standing block + GCal connected → one recurring GCal event on GTD calendar mirroring the RRULE, `gcal_event_id` stored; template edits patch the event; deactivation deletes it; per-instance TimeBlocks NOT created for recurring tasks.
- [ ] Completing an instance leaves the recurring GCal event untouched.
- [ ] **Test:** materializer run-twice idempotence, RRULE round-trip, pile-up query.
- [ ] **Rollback:** deactivate templates; instances remain ordinary tasks.

## Epic 8 — Google Calendar integration (M2)

- [ ] Dependencies: `google-auth`, `google-auth-oauthlib`, `google-api-python-client`, `cryptography` (Fernet); env vars `GOOGLE_CLIENT_ID/SECRET`, `GOOGLE_OAUTH_REDIRECT`, `FERNET_KEY`, `NTFY_TOPIC`.
- [ ] **8a Connect flow:** OAuth2 web flow (`calendar` scope, `access_type=offline&prompt=consent`); callback stores encrypted refresh token in singleton `GoogleCredential`; first-connect creates secondary "GTD" calendar; register watch channels. Document the one-time Google Cloud Console setup steps (OAuth consent screen, web client credentials, enable Calendar API) — **user must perform this manually; not automatable from the coding agent.**
- [ ] **8b TimeBlocks app→GCal:** task/project "Calendar time" panel (existing blocks list + "Add block" mini week view via FullCalendar showing GTD blocks + read-only primary busy events); click-drag → `TimeBlock` + `events.insert`; full `/calendar` page (week view, drag/resize → `events.patch`); completing a task retitles past+future events `✓ <title>`, block `status=COMPLETED`, block persists.
- [ ] `calendar.css` token overrides for FullCalendar per `design.md` §2/§5 (grid lines, today-column tint, block color states, drag-create duration tooltip).
- [ ] **8c GCal→app two-way:** `POST /gcal/webhook` (login-exempt, validates channel/resource id against `SyncChannel`) → incremental sync; `events.list(syncToken=…)` on GTD calendar; matched `gcal_event_id` → update block or delete on `status=cancelled`; unmatched events ignored (v1); sync-token 410 → full resync; conflict rule = last-write-wins, GCal wins ties (confirmed default); daily channel-renewal cron for <48h expiry; 15-min polling fallback regardless of webhooks; primary calendar fetched live for display only, never persisted.
- [ ] **8d Missed-block engine:** 15-min cron — `end < now`, `status=SCHEDULED`, task incomplete → `status=MISSED`, `missed_block_count += 1`, ntfy nag, Today "Missed — reschedule" strip, "⚠ ×N" badge everywhere.
- [ ] **Test:** OAuth callback (mocked), insert/patch/delete event calls (mocked client), webhook validation, sync-token 410 path, conflict rule, missed-block transition.
- [ ] **Rollback:** "Disconnect Google" wipes credential + channels, blocks stay local-only; every GCal call gated on `if credential exists`.

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
