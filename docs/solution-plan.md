# GTD Personal Task System — Solution Plan

## Intro

Personal project for Sudipto. A single-user, self-hosted web app implementing the Getting Things Done (GTD) framework end to end: capture → clarify → organize → reflect → engage. Core surfaces: Inbox, Tasks/Projects with contexts, Notes (reference), Waiting For, Someday, recurring tasks, two-way Google Calendar time-blocking, guided review wizards (weekly/monthly/quarterly/yearly) with an embedded Eisenhower triage board, ntfy push notifications, and a light stats page.

Stack: Django 5.x + HTMX + Alpine.js + Tailwind CSS (pre-built via CLI, no bundler) + PostgreSQL. Deployed like `tracker.sudipto.dev`: Ubuntu EC2, gunicorn behind nginx, systemd service, at `gtd.sudipto.dev`.

## Business need / Purpose

**Stakeholder:** Sudipto (sole user).

**Problem today:** No trusted external system. Commitments live across Slack, Jira, email, and memory; the GTD study doc identified the cost (open loops, mental rehearsal, unreliable recall). Generic task apps don't enforce GTD behavior — capture without clarify, no review discipline, no next-action rule.

**What changes:** One system holds everything. The app doesn't just store lists — it *teaches and enforces* the method: frictionless capture, a clarify wizard that forces a decision per item, stalled-project indicators, forced carry-over decisions, guided reviews with nags, and Eisenhower as a weekly judgment lens (never stored metadata).

**Priority bucket:** Personal project, discretionary. No deadline.

## Other information

- Source methodology: `gtd-detailed-study.md` (uploaded study doc). Design decisions below follow its §9 (Eisenhower), §8.1 (pitfalls), §8.3 (GTD + time-blocking hybrid).
- Related personal projects sharing the stack pattern: futsal app, tax app, meeting tracker.

### Decision log (agreed during interview)

| # | Decision |
|---|---|
| 1 | Horizon default = **Anytime**. Today view = curated Today section + collapsible "Anytime — pick from here" section (context-filterable). |
| 2 | No stored priority field. Priority = manual sort order within views + Weekly **Big-3** stars (auto-clear at next review) + transient **Q2 chip** (expires Sunday). |
| 3 | Eisenhower exists only as a drag-board step inside the Weekly Review and as the Q2 tie-breaker chip. No quadrant field on tasks, no standalone matrix menu. |
| 4 | Capture requires **title only**; one open text box, description optional. |
| 5 | Reference items are a separate `Note` model (not tasks): body, links, attachments, contexts/tags, full-text search. |
| 6 | "Tags" are the user's word for GTD contexts + plain tags: one `Tag` model with `is_context` flag. Inline `@word` = context, `#word` = plain tag, parsed live. Soft nag above ~7 contexts. |
| 7 | Next action = explicitly flagged subtask, multiple allowed (one per parallel track). Zero flagged → first incomplete subtask by sort order shown as *implicit* next action (hollow marker). No incomplete subtasks → "stalled or done?" indicator. |
| 8 | Recurring tasks: one recurring GCal event; app materializes one instance per occurrence; missed instances **pile up** as overdue. |
| 9 | GCal: dedicated secondary calendar "GTD" (write target), primary calendar read-only busy overlay. Two-way sync. Personal Gmail, single-user OAuth. Completing a task **keeps** its calendar block (retitled with ✓). |
| 10 | Missed block: auto-flag, ntfy nag, reschedule prompt, task shows "missed deadline before" badge (`missed_block_count`). |
| 11 | 2-minute rule: "Done" button directly on inbox items + helper prompt in the clarify wizard. |
| 12 | Notifications via **ntfy.sh** (existing pattern from claude-watch). |
| 13 | Reviews: fully guided wizards for Weekly + Monthly; lighter checklists for Quarterly + Yearly. All four: recurring GCal blocks + overdue nags. `Area` entity ships in v1. |
| 14 | iPhone capture: installable PWA `/capture` screen + iOS Shortcut → `POST /api/capture` (token auth). Share sheet + Siri via Shortcuts. Email-to-inbox = v2. |
| 15 | Carry-over: incomplete `today`/`this_week`/`this_month` tasks keep horizon at rollover, gain "carried over ×N" badge; Weekly Review forces a decision per carried-over task. |
| 16 | Waiting For: `waiting_on` free text, auto `waiting_since`, follow-up nag after N days (default 5, per-item override). |
| 17 | Stats v1 (read-only page): completions per day/week, review streak, inbox-zero events, missed-block rate, capture→clarify latency. |

### Open decisions (flagged, defaults chosen)

| Item | Default in this plan | Alternative |
|---|---|---|
| Optional `due_date` on tasks | **Included** (nullable). Deadline ≠ time block; drives urgency display. | Omit; rely on blocks only. |
| Calendar UI library | **FullCalendar 6 via CDN** (no build step needed). | Hand-rolled week grid (≈3× the work). |
| Two-way sync conflict | **Last-write-wins by timestamp; GCal wins ties.** | App always wins. |

## Solution overview

One Django project, one app-server, five subsystems:

1. **Core GTD engine** — models, lists, clarify wizard, contexts/tags, horizons, ordering.
2. **Recurrence engine** — templates → materialized instances, overdue pile-up.
3. **Calendar subsystem** — Google OAuth, dedicated GTD calendar, TimeBlocks, two-way sync (webhook + polling fallback), missed-block detection, week-view UI.
4. **Reflect subsystem** — review configs, guided wizards, Eisenhower board, Big-3, carry-over enforcement.
5. **Notification subsystem** — ntfy dispatch with digest rules.

Background work runs on **cron via Django management commands** (no Celery/queue — single user, low volume; keeps ops identical to the tracker deployment). All cron entries listed in Step 12.

### Alternatives considered

| Option | Verdict |
|---|---|
| Off-the-shelf (Todoist/Things + plugins) | Rejected: no enforcement of clarify/review discipline, no custom Eisenhower-in-review flow, no self-hosting. |
| Celery + Redis for background jobs | Rejected for v1: cron covers every job (sync poll, materializer, nags) at single-user scale. Revisit if sync latency ever matters. |
| SQLite | Rejected: Postgres FTS needed for Notes search; Postgres is already the personal-stack default. |

### Rollout

Staged, one PR per step below. Steps 1–6 give a fully usable offline GTD system; 7–12 add recurrence, calendar, reviews, notifications, stats. Each step is deployable alone.

### Complexity

**High complexity.** The core CRUD is easy, but three pieces carry real risk: (1) two-way Google Calendar sync — webhook channels that expire, sync tokens, conflict resolution; (2) the recurrence engine with per-instance materialization and calendar linkage; (3) the guided review wizard with a drag-and-drop Eisenhower board. Everything else is low-risk Django/HTMX.

### Challenges

- Google push channels expire (max ~1 month TTL) and can silently die → polling fallback is mandatory, not optional.
- Recurring GCal event ↔ per-instance app records is an impedance mismatch; the mapping rules in Step 7 must be followed exactly.
- iOS PWA has no share-target and limited service-worker scope → the Shortcut endpoint is the primary mobile capture path; don't over-invest in the service worker.

---

## Step 1: Project scaffold, auth, PWA shell

**Setup**
- Django 5.x project `gtd`, single app `core`. Python 3.12.
- `django-environ` for config. Postgres via `psycopg`.
- Tailwind standalone CLI → `static/css/app.css` committed pre-built. Alpine.js + HTMX vendored to `static/js/`.
- Auth: Django auth, single superuser via `createsuperuser`. `LoginRequiredMiddleware` (Django 5.1+) — every view requires login except the webhook + capture API.
- Settings hygiene from day one: `DEBUG=False` in prod, no `django-browser-reload` in prod requirements (lesson from tracker).

**PWA shell**
- `manifest.json` (name "GTD", standalone display, icons 192/512).
- Minimal service worker: cache app shell + `/capture` for fast open; **no offline queue in v1** (flagged v2).
- `base.html`: bottom tab bar on mobile (Inbox, Today, Calendar, Review, More), sidebar on desktop. All list interactions via HTMX partials.

**Tests:** smoke test (login, base renders). **Rollback:** n/a (greenfield).

## Step 2: Data model

All models in `core/models.py`, one initial migration. Field lists are exhaustive — implement as written.

```python
class Tag(models.Model):
    name = models.SlugField(max_length=40, unique=True)  # stored lowercase
    is_context = models.BooleanField(default=False)      # @word vs #word
    created_at = models.DateTimeField(auto_now_add=True)

class Area(models.Model):                                # Horizon 2: roles
    name = models.CharField(max_length=80, unique=True)
    description = models.TextField(blank=True)
    sort_order = models.PositiveIntegerField(default=0)

class InboxItem(models.Model):
    title = models.CharField(max_length=300)
    description = models.TextField(blank=True)
    source = models.CharField(max_length=20, default="web")  # web|shortcut|review
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    done_directly = models.BooleanField(default=False)    # 2-minute rule
    processed_at = models.DateTimeField(null=True)        # set on clarify

class Task(models.Model):
    class List(models.TextChoices):
        NEXT = "next"; WAITING = "waiting"; SOMEDAY = "someday"; TRASH = "trash"
    class Horizon(models.TextChoices):
        TODAY = "today"; WEEK = "this_week"; MONTH = "this_month"; ANYTIME = "anytime"

    title = models.CharField(max_length=300)
    description = models.TextField(blank=True)            # markdown
    list = models.CharField(max_length=10, choices=List.choices, default=List.NEXT)
    is_project = models.BooleanField(default=False)
    parent = models.ForeignKey("self", null=True, blank=True,
                               on_delete=models.CASCADE, related_name="subtasks")
    is_next_action = models.BooleanField(default=False)    # explicit flag, subtasks only
    horizon = models.CharField(max_length=12, choices=Horizon.choices,
                               default=Horizon.ANYTIME)    # Decision #1
    sort_order = models.PositiveIntegerField(default=0)    # manual priority
    big3 = models.BooleanField(default=False)              # weekly star
    q2_week = models.DateField(null=True, blank=True)      # Monday of chip validity week
    area = models.ForeignKey(Area, null=True, blank=True, on_delete=models.SET_NULL)
    tags = models.ManyToManyField(Tag, blank=True)
    due_date = models.DateField(null=True, blank=True)     # open decision: included
    # Waiting For (only when list == WAITING)
    waiting_on = models.CharField(max_length=120, blank=True)
    waiting_since = models.DateField(null=True, blank=True)
    follow_up_after_days = models.PositiveSmallIntegerField(default=5)
    last_follow_up_nag = models.DateField(null=True, blank=True)
    # lifecycle / counters
    carried_over_count = models.PositiveSmallIntegerField(default=0)
    missed_block_count = models.PositiveSmallIntegerField(default=0)
    recurring_template = models.ForeignKey("RecurringTemplate", null=True, blank=True,
                                           on_delete=models.SET_NULL, related_name="instances")
    occurrence_date = models.DateField(null=True, blank=True)  # set on instances
    completed_at = models.DateTimeField(null=True, blank=True)
    trashed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            # subtasks are single-level: parent must be a project
            models.CheckConstraint(name="no_project_subtask",
                check=~Q(is_project=True) | Q(parent__isnull=True)),
        ]
        indexes = [models.Index(fields=["list", "horizon"]),
                   models.Index(fields=["completed_at"])]

class Note(models.Model):                                  # Reference (Decision #5)
    title = models.CharField(max_length=300)
    body = models.TextField(blank=True)                    # markdown; links live here
    tags = models.ManyToManyField(Tag, blank=True)
    trashed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    search = SearchVectorField(null=True)                  # Postgres FTS, GIN index

class NoteAttachment(models.Model):
    note = models.ForeignKey(Note, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to="attachments/%Y/%m/")
    original_name = models.CharField(max_length=255)

class RecurringTemplate(models.Model):
    title = models.CharField(max_length=300)
    description = models.TextField(blank=True)
    rrule = models.CharField(max_length=200)               # RFC 5545, e.g. FREQ=WEEKLY;BYDAY=TH
    tags = models.ManyToManyField(Tag, blank=True)
    area = models.ForeignKey(Area, null=True, blank=True, on_delete=models.SET_NULL)
    # optional standing time block
    block_start_time = models.TimeField(null=True, blank=True)
    block_duration_min = models.PositiveSmallIntegerField(null=True, blank=True)
    gcal_event_id = models.CharField(max_length=120, blank=True)  # recurring event
    active = models.BooleanField(default=True)
    last_materialized_until = models.DateField(null=True, blank=True)

class TimeBlock(models.Model):
    class Status(models.TextChoices):
        SCHEDULED = "scheduled"; MISSED = "missed"; COMPLETED = "completed"
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="blocks")
    start = models.DateTimeField(); end = models.DateTimeField()
    status = models.CharField(max_length=10, choices=Status.choices,
                              default=Status.SCHEDULED)
    gcal_event_id = models.CharField(max_length=120, blank=True)
    gcal_etag = models.CharField(max_length=120, blank=True)
    last_synced_at = models.DateTimeField(null=True)

class GoogleCredential(models.Model):                      # singleton row
    refresh_token = models.BinaryField()                   # Fernet-encrypted
    gtd_calendar_id = models.CharField(max_length=120, blank=True)
    primary_calendar_id = models.CharField(max_length=120, default="primary")
    connected_at = models.DateTimeField(auto_now_add=True)

class SyncChannel(models.Model):
    calendar_id = models.CharField(max_length=120)
    channel_id = models.UUIDField(); resource_id = models.CharField(max_length=120)
    expiration = models.DateTimeField()
    sync_token = models.CharField(max_length=255, blank=True)

class ReviewConfig(models.Model):
    class Cadence(models.TextChoices):
        WEEKLY = "weekly"; MONTHLY = "monthly"; QUARTERLY = "quarterly"; YEARLY = "yearly"
    cadence = models.CharField(max_length=10, choices=Cadence.choices, unique=True)
    weekday = models.PositiveSmallIntegerField(default=4)  # Fri
    time = models.TimeField(default=time(16, 0))
    duration_min = models.PositiveSmallIntegerField(default=60)
    gcal_event_id = models.CharField(max_length=120, blank=True)

class ReviewSession(models.Model):
    cadence = models.CharField(max_length=10, choices=ReviewConfig.Cadence.choices)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True)
    phase_state = models.JSONField(default=dict)           # wizard progress, resumable
    stats_snapshot = models.JSONField(default=dict)

class CaptureToken(models.Model):                          # iOS Shortcut auth
    token = models.CharField(max_length=64, unique=True)   # secrets.token_urlsafe(32)
    label = models.CharField(max_length=60, default="iPhone")
    last_used_at = models.DateTimeField(null=True)

class NotificationLog(models.Model):
    kind = models.CharField(max_length=30)                 # missed_block|follow_up|review_due|...
    ref_id = models.PositiveIntegerField(null=True)
    sent_at = models.DateTimeField(auto_now_add=True)      # dedupe key: kind+ref_id+date
```

**Semantics to enforce in code, not just schema:**
- A **project** = `Task(is_project=True, parent=None)`. Subtasks: `parent=project, is_project=False`. One level only.
- **Next action resolution** (Decision #7), single queryset helper `project.next_actions()`: flagged incomplete subtasks; if none, first incomplete subtask by `sort_order` returned with `implicit=True`; if no incomplete subtasks → project state `NEEDS_ATTENTION` ("stalled or done?").
- **Trash** = `list=TRASH` + `trashed_at` (tasks) / `trashed_at` (notes). Cron purges after 30 days.
- Completing a project prompts if it still has incomplete subtasks ("Complete anyway? Subtasks will be completed too.").

**Tests:** model constraints, `next_actions()` all three states, trash purge query.
**Rollback:** migration revert (greenfield tables).

## Step 3: Capture

**Web quick capture**
- `/capture`: single autofocused title input + collapsed optional description. Submit → HTMX POST `/inbox/items/` → clears and refocuses (rapid-fire capture). Global "+" in the header opens the same form in a modal on every page.
- Mobile PWA opens straight to `/capture` when launched from home screen if the inbox modal param is set (`start_url: /capture`).

**API capture (iOS Shortcut)**
- `POST /api/capture` — auth via `Authorization: Bearer <CaptureToken>`. Body `{"title": str, "description": str?}`. Returns `201 {"id": …}`. Rate-limited 60/min. CSRF-exempt, login-exempt.
- Settings page renders step-by-step Shortcut setup (Get Text from Share Sheet → Get Contents of URL POST → Show Notification), so share-sheet + Siri capture work. Token create/revoke UI.

**2-minute rule (Decision #11)**
- Each inbox row has **Done** (marks `done_directly=True, processed_at=now` — logged for stats, never becomes a Task) and **Clarify**.

**Tests:** API auth (valid/invalid/missing token), rapid double-submit idempotence not required (duplicates are fine in an inbox), done-directly path.
**Rollback:** remove routes.

## Step 4: Clarify wizard

The GTD decision tree as a per-item HTMX wizard. Primary entry: "Process Inbox" button → takes items **oldest first, one at a time** (the GTD default; next item auto-loads after each decision). A per-row **Clarify** button is the deliberate exception — it opens the wizard directly on that item (cherry-picking), then falls through to the remaining items oldest-first once decided. (Originally spec'd as strictly no-cherry-picking; relaxed after the per-row button made jumping to a specific item the expected behavior.)

Screens per item:
1. **Is it actionable?** Helper text quotes the doc's Q2. Buttons: *No* → (Trash | Someday | Reference) · *Yes* → next screen.
   - Trash → `Task(list=TRASH)` shell or direct `InboxItem` discard (implement as Task-to-trash for unified trash view).
   - Someday → Task form pre-filled, `list=SOMEDAY`.
   - Reference → **Note form** pre-filled (title/description → title/body).
2. **Actionable path.** Helper: "Under 2 minutes? Do it now." with a *Did it — Done* button. Otherwise: *Single action* | *Project* | *Delegate (Waiting For)*.
   - Single action → Task form: title, description, contexts/tags (inline parser live), horizon (default Anytime), optional due date, area.
   - Project → same form with `is_project=True` + inline "add first subtasks" repeater; first subtask auto-flagged `is_next_action=True` (helper: "Every project needs a next action").
   - Delegate → Waiting For form: `waiting_on`, follow-up days (default 5); `waiting_since=today`.
3. Item marked `processed_at`, wizard advances. Progress bar "4 / 17". Finish screen: "Inbox zero 🎉" (logged for stats).

**Inline tag parser** (used in all title/description inputs, and in Step 5's manager):
- Regex on save: `@([a-z0-9\-]+)` → get-or-create `Tag(is_context=True)`; `#([a-z0-9\-]+)` → `Tag(is_context=False)`. Tokens stay in the text; M2M is synced additively on every save (removal of a tag = explicit chip removal in the form, not text editing). Alpine-powered typeahead suggests existing tags after `@`/`#`.

**Tests:** each decision path produces the right entity; one-at-a-time ordering; parser (create, reuse, case-fold, no dupes).
**Rollback:** wizard routes off; inbox remains a plain list.

## Step 5: Lists, projects, contexts, ordering, horizons

**Views (all HTMX-partial driven):**
- **Today** (`/today`): section 1 = curated (`horizon=today`, plus tasks with a TimeBlock today, plus due today/overdue, plus overdue recurring instances). Section 2 = collapsible **Anytime** picker, filter chips by context. Big-3 stars pinned on top; Q2 chips highlighted where `q2_week == current week's Monday`.
- **This Week / This Month**: same pattern with matching horizon + due window.
- **Next Actions** (`/tasks`): all `list=NEXT` non-project tasks (standalone + subtasks — Decision: subtasks appear here *and* under their project, requirement #5). Filters: context chips, tag chips, horizon, area, "next actions only" toggle.
- **Projects** (`/projects`): cards with subtask progress bar, next-action line, and badges: 🟡 `NEEDS_ATTENTION` (no incomplete subtasks → "Mark done or add next task"), 🔴 stalled variant when no *flagged* next action exists but subtasks remain (hollow-marker implicit shown). Project detail: description, subtask list (drag-reorder, flag-as-next toggle), calendar allocation panel (Step 8), add-subtask inline.
- **Waiting For** (`/waiting`): sorted by `waiting_since`; overdue-follow-up rows tinted; row actions: *Got it* (→ back to NEXT or done), *Nudge sent* (resets nag date).
- **Someday** (`/someday`): reviewed via Weekly Review; row action *Activate* → NEXT.
- **Trash**: restore / purge now; auto-purge note ("cleared after 30 days").

**Ordering (Decision #2):** SortableJS (CDN) drag handles on every list; drop → HTMX PATCH `/tasks/<id>/reorder/` with new index; server rewrites `sort_order` gap-based (steps of 100, renumber on collision).

**Horizon carry-over (Decision #15):** nightly cron `rollover`: on Monday 00:05 local, incomplete `this_week` tasks get `carried_over_count += 1`; on the 1st, same for `this_month`; daily for `today`. Badge "↩ ×N" shown; the Weekly Review forces a decision on every task with `carried_over_count > 0` (Step 10).

**Tag manager** (`/tags`): list with usage counts, context toggle, rename (slug-safe), merge (re-point M2M, delete source), delete (confirm). Soft nag banner when `is_context=True` count > 7: "GTD warning: too many contexts becomes a hobby."

**Tests:** Today view composition (all four inclusion rules), reorder persistence, carry-over cron on synthetic dates, merge correctness.
**Rollback:** each view independent; disable route.

## Step 6: Notes (Reference) + search

- `/notes`: searchable list (Postgres `SearchVector` on title+body, updated via `post_save` signal), tag filter, note detail with rendered markdown, attachments (upload to `MEDIA_ROOT`, nginx-served, 20 MB cap), edit inline.
- Convertible both ways: inbox → note (Step 4); task → note ("this turned out to be reference") copies fields, trashes the task.

**Tests:** FTS returns match on body text; conversion keeps tags.
**Rollback:** independent module.

## Step 7: Recurrence engine

- `/recurring`: CRUD for `RecurringTemplate`. Rule builder UI: frequency (daily/weekly/monthly/yearly), weekday picker, interval — serialized to RRULE via `dateutil.rrule` (dependency: `python-dateutil`). Optional standing block: start time + duration.
- **Materializer** (cron, hourly): for each active template, generate occurrences from `last_materialized_until` through `today + 14 days`; create `Task(list=NEXT, horizon=TODAY on its occurrence_date — set when date arrives, ANYTIME before)`. Simpler rule, implement this: instance is created with `occurrence_date`; Today view includes instances with `occurrence_date <= today` and not completed. Advance `last_materialized_until`.
- **Overdue pile-up (Decision #8):** an instance past its `occurrence_date` and incomplete renders with an "overdue since {date}" badge; instances accumulate. Bulk actions on the recurring detail page: "complete all overdue", "trash all overdue".
- **Calendar linkage:** if the template has a standing block and GCal is connected, create **one recurring GCal event** on the GTD calendar (RRULE mirrored); store `gcal_event_id`. Per-instance TimeBlocks are *not* created for recurring tasks — the recurring event itself is the block. Editing template time/rule patches the GCal event; deactivating deletes it.
- Completing an instance does not touch the recurring event (Decision #9 analog: history stays).

**Tests:** materializer idempotence (run twice, no dupes — unique constraint on `(recurring_template, occurrence_date)`), RRULE round-trip, pile-up query.
**Rollback:** deactivate templates; instances are ordinary tasks.

## Step 8: Google Calendar integration

**Dependencies:** `google-auth`, `google-auth-oauthlib`, `google-api-python-client`, `cryptography` (Fernet). Env vars: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_OAUTH_REDIRECT=https://gtd.sudipto.dev/google/callback`, `FERNET_KEY`, `NTFY_TOPIC`.

**8a. Connect flow**
- Settings → "Connect Google": OAuth2 web flow, scope `https://www.googleapis.com/auth/calendar`, `access_type=offline&prompt=consent`. Callback stores encrypted refresh token (singleton `GoogleCredential`).
- On first connect: create secondary calendar **"GTD"** via `calendars.insert`, store id. Register watch channels (below).
- Plan documents the one-time Google Cloud setup: project → OAuth consent (internal/testing, your Gmail as test user) → Web client credentials → enable Calendar API.

**8b. TimeBlocks (app → GCal)**
- Task/project detail → "Calendar time" panel: existing blocks list + "Add block" → mini week view (FullCalendar, CDN) showing GTD blocks *and* busy events from primary calendar (`events.list`, read-only) — requirement #4's "see my current allocation". Click-drag a slot → `TimeBlock` created → `events.insert` on GTD calendar (summary = task title, description = deep link `https://gtd.sudipto.dev/tasks/<id>`), store `gcal_event_id`/`etag`.
- Full calendar page (`/calendar`): week view, GTD blocks (colored, draggable — drag/resize → PATCH block → `events.patch`) overlaid with primary busy events (grey, immutable).
- Completing a task: blocks keep their events; future+past events retitled `✓ <title>`, block `status=COMPLETED` (Decision #9).

**8c. GCal → app (two-way)**
- **Webhook:** `POST /gcal/webhook` (login-exempt; validate `X-Goog-Channel-Id` + `X-Goog-Resource-Id` against `SyncChannel`). On notify → run incremental sync for that calendar.
- **Incremental sync:** `events.list(syncToken=…)` on the GTD calendar; for each changed event with a matching `gcal_event_id`: update block start/end (moved/resized in Google), or on `status=cancelled` → delete block (task stays, becomes unblocked). Events on the GTD calendar with no matching block are ignored in v1 (creating tasks from GCal = v2). Token expiry (HTTP 410) → full resync.
- **Conflict rule:** compare event `updated` vs block `last_synced_at`; last write wins, GCal wins ties (open-decision default).
- **Channel renewal:** daily cron re-registers channels expiring < 48h. **Polling fallback:** cron every 15 min runs incremental sync regardless of webhooks — this is the reliability floor; webhooks only reduce latency.
- Primary calendar is **not** watched or synced into the DB; its events are fetched live for display only (single user; avoids mirroring your work life into the app DB).

**8d. Missed-block engine (Decision #10)**
- Cron every 15 min: blocks with `end < now`, `status=SCHEDULED`, task incomplete → `status=MISSED`, task `missed_block_count += 1`, ntfy nag ("Missed block: <task>. Reschedule?" with deep link), Today view shows the task in a "Missed — reschedule" strip with one-tap "pick new slot". Badge "⚠ missed ×N" on the task everywhere.

**Tests:** OAuth callback (mocked), insert/patch/delete event calls (mocked client), webhook validation, sync-token 410 path, conflict rule, missed-block transition.
**Rollback:** "Disconnect Google" wipes credential + channels; blocks remain local-only; every GCal call is behind `if credential exists`.

## Step 9: Reflect — reviews, Eisenhower board, Big-3

**Setup:** onboarding banner until all four `ReviewConfig`s are set (weekly default Fri 16:00/60min, monthly 1st Fri, quarterly, yearly). Saving a config creates the recurring GCal event on the GTD calendar ("🔁 GTD Weekly Review" etc.).

**Weekly Review wizard** (`/review/weekly`, resumable via `phase_state`):
1. **Get Clear** — inbox count with inline process-inbox embed (must reach zero or explicitly "skip, I know"); mini mind-sweep capture box (multi-line, one item per line → inbox → immediately clarified or left).
2. **Get Current** —
   a. Projects checklist: each project row shows its next-action state; 🟡/🔴 projects demand an action (add subtask / flag next / mark done / move to Someday).
   b. **Carried-over queue:** every task with `carried_over_count > 0` presented one by one: Keep (resets counter) / Demote to Anytime / Someday / Trash. Cannot proceed past unresolved items.
   c. Waiting For pass: overdue follow-ups → "nudged / got it / drop".
   d. Calendar pass: last 2 weeks (capture box: "anything to capture from these?") + next 2 weeks preview.
   e. **Eisenhower board (Decision #3):** 2×2 drag board, active projects as cards. Drop actions: **Q2** → inline slot picker → creates TimeBlock next week *and* sets `q2_week = next Monday` on the project's next action(s); **Q3** → convert next action to Waiting For dialog, or project → Someday; **Q4** → Someday/Trash; **Q1** → checkmark if it has a block/due date this week, else prompts to add one. Nothing else persists; board state is discarded.
3. **Get Creative** — Someday list with *Activate* buttons; free capture box; **Big-3 picker:** previous stars auto-cleared, pick up to 3 tasks/projects → `big3=True`.
4. Finish → `ReviewSession.completed_at`, streak++ toast, stats snapshot stored.

**Monthly wizard:** Areas pass (each `Area`: "healthy? anything to capture/start/stop?" + capture box per area), Someday deep pass, horizon check for `this_month` carried-overs.
**Quarterly / Yearly checklists:** static guided checklist (1–2yr goals / vision & principles prompts from the doc's Horizons table) + capture boxes; completion tracked in `ReviewSession`.

**Enforcement layer (requirement #9 + your "make the system remind me" ask):**
- GCal recurring blocks (above).
- ntfy: T-15min reminder on review day; if no completed session by cadence deadline (weekly: end of the scheduled day) → daily "Weekly review overdue (N days)" nag until done.
- In-app: persistent banner when overdue; Today view header shows "Last review: N days ago" turning amber > 7, red > 10.
- Helper texts throughout the app are first-class: every list's empty state teaches its GTD rule (copy sourced from the study doc); a dismissible "GTD tip" strip rotates the pitfalls of §8.1.

**Tests:** wizard resume, carried-over gate, Eisenhower drop actions (each quadrant → correct mutation), Big-3 auto-clear, streak computation.
**Rollback:** reviews are additive; disable routes, GCal review events removable from settings.

## Step 10: Notifications (ntfy)

- Helper `notify(kind, title, message, url, priority)` → `POST https://ntfy.sh/<NTFY_TOPIC>` with click-action deep link. Topic in env; document choosing a high-entropy topic name (same practice as claude-watch).
- Dedupe via `NotificationLog` (one per kind+ref+day).
- Kinds & timing: `missed_block` (immediate), `review_reminder` (T-15min), `review_overdue` (daily 09:00), `follow_up_due` (batched daily 09:00 digest: "3 Waiting-For items need a nudge"), `recurring_overdue` (daily 09:00, count-based).
- Settings page: per-kind on/off toggles, test-fire button.

**Tests:** dedupe, digest batching, toggle respected.
**Rollback:** `NTFY_TOPIC` unset → no-op.

## Step 11: Stats

`/stats` (read-only, Chart.js via CDN): completions per day (last 30) and per week (last 12); review streak + last-completed per cadence; inbox-zero events count; missed-block rate (missed / total blocks, last 4 weeks); median capture→clarify latency; 2-minute-rule count (`done_directly`). All computed live with aggregate queries — no denormalized tables at this scale.

**Tests:** each aggregate against fixture data.

## Step 12: Deployment & ops

- EC2 Ubuntu, gunicorn (systemd `gtd.service`), nginx vhost `gtd.sudipto.dev` + certbot TLS (webhook requires valid HTTPS), Postgres local, `MEDIA_ROOT` served by nginx with auth via `X-Accel-Redirect` (attachments are private).
- Env: `SECRET_KEY, DATABASE_URL, ALLOWED_HOSTS, GOOGLE_*, FERNET_KEY, NTFY_TOPIC`.
- **Cron table** (system crontab → `manage.py` commands):

| Schedule | Command | Purpose |
|---|---|---|
| `*/15 * * * *` | `sync_gcal` | polling fallback + missed-block engine |
| `0 * * * *` | `materialize_recurring` | recurrence instances |
| `5 0 * * *` | `rollover` | horizon carry-over, Q2 chip expiry (Mondays), trash purge |
| `0 9 * * *` | `daily_digest` | follow-up + recurring-overdue + review-overdue nags |
| `0 3 * * *` | `renew_gcal_channels` | webhook channel renewal |

- Backups: nightly `pg_dump` to S3 (reuse existing pattern), 14-day retention.
- Logging: Django file logs + gunicorn journal; sync errors logged with event ids (debugging two-way sync without logs is misery).

**Rollback:** systemd stop; each cron independent.

---

## Build order & milestones

| Milestone | Steps | You get |
|---|---|---|
| M1 — Trusted lists | 1–6 | Full offline GTD: capture (web+iPhone), clarify, all lists, contexts, notes, ordering, horizons |
| M2 — Time | 7–8 | Recurrence + full two-way calendar |
| M3 — Discipline | 9–10 | Guided reviews, Eisenhower, Big-3, nags |
| M4 — Polish | 11–12 | Stats, hardened ops |

## Explicitly out of scope (v2 backlog)

Email-to-inbox capture; offline PWA queue; creating tasks from raw GCal events; multi-user; natural-language capture parsing ("call plumber friday 3pm"); Areas on Notes; AI features.
