# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository state

This repo currently contains **planning and design artifacts only** — there is no Django project, no source code, and no build/lint/test tooling yet. Before assuming any command works, check whether the app scaffold in `docs/solution-plan.md` Step 1 has actually been created; do not invent `manage.py`/`npm`/tooling commands that don't exist on disk.

- `docs/solution-plan.md` — the authoritative spec: data models (exact field lists in Step 2), build order (Steps 1–12), decision log, and rollout milestones. Treat model/field definitions here as literal — implement as written rather than redesigning.
- `docs/design.md` — the UI/visual design spec (tokens, components, screens, copy). Read together with the solution plan. **Where they conflict: `solution-plan.md` wins on behavior, `design.md` wins on look and feel.**
- `design-files/*.dc.html` — visual mockups/prototypes exported from a design tool (custom `<x-dc>`, `sc-if`, `sc-for`, `{{ }}` template syntax driven by `support.js`). These are references for layout/visual intent only — do not copy their templating syntax into Django templates; translate the visuals into HTMX/Django partials per `design.md` §4.
- `design-files/uploads/` contains duplicate copies of `design.md`/`solution-plan.md` plus reference screenshots — the `docs/` copies are the ones to edit.

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
