# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository state

**The Django scaffold exists** (Epic 0 + Epic 1 of `docs/task-breakdown.md`, committed). Project `gtd`, single app `core`, `manage.py` at repo root. Build order continues per `docs/solution-plan.md` Steps 2–12 / `docs/task-breakdown.md` Epics 2–12 — check that file's checkboxes (`[x]` done, `[~]` partial, `[ ]` not started) before assuming a screen or model exists.

- `docs/solution-plan.md` — the authoritative spec: data models (exact field lists in Step 2), build order (Steps 1–12), decision log, and rollout milestones. Treat model/field definitions here as literal — implement as written rather than redesigning.
- `docs/design.md` — the UI/visual design spec (tokens, components, screens, copy). Read together with the solution plan. **Where they conflict: `solution-plan.md` wins on behavior, `design.md` wins on look and feel.**
- `docs/task-breakdown.md` — the epic/subtask checklist tracking implementation against the plan above, plus a running log of decisions confirmed during planning (open-decision defaults, git setup, scaffold-from-scratch choice). Update its checkboxes as work lands; don't let it drift from what's actually on disk.
- `design-files/*.dc.html` — visual mockups/prototypes exported from a design tool (custom `<x-dc>`, `sc-if`, `sc-for`, `{{ }}` template syntax driven by `support.js`). These are references for layout/visual intent only — do not copy their templating syntax into Django templates; translate the visuals into HTMX/Django partials per `design.md` §4.
- `design-files/uploads/` contains duplicate copies of `design.md`/`solution-plan.md` plus reference screenshots — the `docs/` copies are the ones to edit.

### Local dev environment

- Virtualenv at `.venv/` (not committed). Activate or call directly: `.venv/Scripts/python.exe manage.py <command>`.
- Requirements split: `requirements/base.txt`, `dev.txt`, `prod.txt` (installed manually so far; no lockfile yet).
- Postgres: dev DB is `gtd` on the existing shared `postgres-container` Docker container (user `sudipto`), **not** a project-dedicated container — reuses infra also used by other personal projects (e.g. `jimmy` db in the same instance). Connection string lives in `.env` (gitignored; see `.env.example` for the shape). Postgres is required from day one (Notes FTS) — don't fall back to SQLite.
- Tailwind: standalone CLI binary at `.bin/tailwindcss.exe` (gitignored, ~40MB — re-download from the v3.4.17 GitHub release if missing, not v4: the config uses v3-style `tailwind.config.js` + `safelist`). Rebuild with `.bin/tailwindcss.exe -i static/css/input.css -o static/css/app.css --minify`. `static/css/app.css` is the committed, pre-built output — `input.css` is the source.
- Tests: `.venv/Scripts/python.exe manage.py test core`.
- Known gaps (tracked in `docs/task-breakdown.md` Epic 1, marked `[~]`): font woff2 binaries not sourced (falls back to system fonts), PWA icon PNGs (192/512) not generated.
- Git identity is set repo-local only (`git config user.name/email` without `--global`) — do not touch global git config.

## Product summary

A single-user, self-hosted Getting Things Done (GTD) task system for Sudipto: capture → clarify → organize → reflect → engage, with two-way Google Calendar time-blocking, guided review wizards with an Eisenhower triage board, ntfy push notifications, and a stats page.

**Planned stack** (per `solution-plan.md`): Django 5.x + HTMX + Alpine.js + Tailwind CSS (standalone CLI, no bundler, output committed) + PostgreSQL. Single app `core`. No Celery/queue — background work runs via cron-triggered `manage.py` commands (see the cron table in Step 12). Deployed like the existing `tracker.sudipto.dev` pattern: EC2 Ubuntu, gunicorn + nginx + systemd.

## Architecture (once implemented)

Five subsystems inside one Django project/app-server:
1. **Core GTD engine** — models (`Task`, `InboxItem`, `Note`, `Tag`, `Area`), clarify wizard, contexts/tags, horizons (`today`/`this_week`/`this_month`/`anytime`), manual sort ordering.
2. **Recurrence engine** — `RecurringTemplate` → materialized `Task` instances (one per occurrence), overdue instances pile up rather than replacing each other.
3. **Calendar subsystem** — Google OAuth, dedicated secondary "GTD" calendar (write target) + primary calendar read-only busy overlay, two-way sync via webhook + 15-min polling fallback, missed-block detection.
4. **Reflect subsystem** — `ReviewConfig`/`ReviewSession`, guided weekly/monthly wizards, lighter quarterly/yearly checklists, the Eisenhower board (drag-only, in-review, never persisted as task metadata), Big-3 stars, carry-over decision gate.
5. **Notification subsystem** — ntfy.sh dispatch with per-kind dedupe (`NotificationLog`) and digest batching.

Key domain rules to preserve when implementing (see `solution-plan.md` Step 2 "Semantics to enforce in code"):
- A project is `Task(is_project=True, parent=None)`; subtasks are one level deep only (enforced by a `CheckConstraint`).
- Next-action resolution is a single queryset helper: explicit flagged subtask(s) → else first incomplete subtask by `sort_order` (marked `implicit=True`) → else project state `NEEDS_ATTENTION`.
- There is no stored priority/quadrant field anywhere — priority is manual `sort_order` + weekly `big3` stars (auto-cleared each review) + a transient `q2_week` chip (expires the following Monday). The Eisenhower board is a review-time-only UI, not a data model.
- Trash is a soft-delete (`list=TRASH` / `trashed_at`), purged by cron after 30 days.

## Design system rules (from `docs/design.md`)

- No dynamically-constructed Tailwind class names (`bg-{{ color }}` is forbidden because of purge) — status→class mappings must return full literal strings, added to the Tailwind safelist.
- Badges are a closed vocabulary (§6 of `design.md`) — don't invent new badge/color pairings without updating that file first.
- Dark mode is out of scope for v1; don't add `dark:` variants.
- All dates/times render in Asia/Dhaka, mono typeface.
- HTMX handles all mutations (server returns partials); Alpine is for local UI state only, never a data source — the server is truth.
