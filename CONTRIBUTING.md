# Contributing

Thanks for your interest! GTD is a personal, single-user project, but fixes and
improvements are welcome.

## Development setup

The fastest path is Docker (see the README's Quick start). For a native setup:

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements/dev.txt
cp .env.example .env               # then edit: set DATABASE_URL, keep DEBUG=True
python manage.py migrate
python manage.py seed_demo         # optional: demo login + sample data
python manage.py runserver
```

PostgreSQL is required (the Notes full-text search uses Postgres features) — the
app does not run on SQLite.

## Running the tests

```bash
python manage.py test core
```

Please keep the suite green and add tests for behavior changes. CI runs the same
command against Postgres on every push and PR.

## Front-end / styling

Tailwind is compiled with the **standalone CLI** (no Node/bundler). The built
`static/css/app.css` is committed. If you change Tailwind classes in any
template or Python file, rebuild it:

```bash
.bin/tailwindcss -i static/css/input.css -o static/css/app.css --minify
```

Download the standalone binary from the Tailwind **v3.4.17** GitHub release
(the config is v3-style). HTMX drives all mutations (the server returns
partials); Alpine.js is for local UI state only — the server is the source of
truth. There are no dynamically-constructed Tailwind class names (they'd be
purged); status→class maps return full literal strings.

## Architecture

- `docs/solution-plan.md` — data models and build order (authoritative on behavior)
- `docs/design.md` — visual/UI design system (authoritative on look & feel)
- `CLAUDE.md` — a detailed map of conventions and gotchas established while building

## Conventions

- View modules are split by domain (`core/lists.py`, `core/projects.py`, …), not
  one big `views.py`.
- Background jobs are cron-triggered `manage.py` commands (no Celery/queue).
- Keep the single-user assumptions in mind (see `SECURITY.md`).
