# GTD Personal Task System — design.md

Instructions for Claude when building any UI for this project. Read together with `solution-plan.md`. Where the two conflict, `solution-plan.md` wins on behavior; this file wins on look and feel.

---

## 1. Design intent

The product is a **trusted system**. GTD's promise is "mind like water" — the UI must feel calm, legible, and boring in the best way. Every screen answers one question fast, then gets out of the way.

Guiding rules, in priority order:

1. **Calm over clever.** No decoration that doesn't encode information. No gradients, no glassmorphism, no shadows deeper than `shadow-sm`.
2. **One decision per screen.** The Clarify wizard, carry-over queue, and Eisenhower board show one item/one board at a time. Never present two competing decisions.
3. **Density on lists, air on decisions.** List views (Tasks, Waiting, Someday) are compact rows. Decision surfaces (Clarify, Review) are spacious single-column cards.
4. **Badges are a vocabulary, not confetti.** Only the badges defined in §6 exist. Never invent a new badge/color pairing ad hoc.
5. **Teach in the empty space.** Empty states and helper strips carry the GTD method (copy in §9). Helper text is quiet (small, muted), never modal, always dismissible where recurring.

Signature element (the one memorable thing): the **focus card** — Clarify, carry-over decisions, and review steps all use the same centered single card (max-w-xl) on a dimmed page, with a thin progress bar at its top edge. Everything else in the app stays quiet so this pattern lands.

## 2. Tokens

Define once in `tailwind.config.js` under `theme.extend`; never use raw hex in templates.

### Color

| Token | Hex | Tailwind name | Use |
|---|---|---|---|
| `paper` | `#FAFAF8` | `bg-paper` | App background |
| `surface` | `#FFFFFF` | `bg-surface` | Cards, rows, modals |
| `ink` | `#1F2937` | `text-ink` | Primary text |
| `ink-soft` | `#6B7280` | `text-ink-soft` | Secondary text, helper copy |
| `line` | `#E5E7EB` | `border-line` | All borders/dividers |
| `water` | `#0F766E` | accent | Primary actions, active states, links, Today curation |
| `water-soft` | `#CCFBF1` | | Accent backgrounds (chips, selected) |
| `amber` | `#B45309` / bg `#FEF3C7` | | Warnings: carried-over, stalled-?, follow-up due |
| `red` | `#B91C1C` / bg `#FEE2E2` | | Overdue, missed blocks, destructive |
| `violet` | `#6D28D9` / bg `#EDE9FE` | | Q2 chip only. Nothing else is violet |
| `star` | `#CA8A04` | | Big-3 star only |

Dark mode: **out of scope v1.** Do not add `dark:` variants.

Calendar colors (FullCalendar): GTD blocks `water` at 90% with white text; completed blocks `water` at 35% with ✓; missed blocks `red` bg-tint with red border; primary-calendar busy events `#9CA3AF` (grey), 60% opacity, not interactive.

### Typography

Self-hosted woff2 in `static/fonts/` (no Google Fonts CDN — single-server, offline-friendly).

| Role | Face | Use |
|---|---|---|
| Display | **Bricolage Grotesque** (600/700) | Page titles, review phase headings, big stat numbers, "Inbox zero" moment |
| Body | **Inter** (400/500/600) | Everything else |
| Mono | **JetBrains Mono** (400/500) | Dates, times, counters, streaks, `@context`/`#tag` tokens inside text |

Scale (rem): page title 1.5 / section 1.125 / body 0.9375 / meta & badges 0.75. Line-height 1.5 body, 1.2 display. Never bold whole sentences; weight 600 max for emphasis words.

### Spacing & shape

- Base unit 4px; standard paddings `p-3` rows, `p-4` cards, `p-6` focus cards.
- Radius: `rounded-md` (6px) everywhere — inputs, buttons, cards, chips use `rounded-full` only for tag/context chips and count pills.
- Borders over shadows: default card = `bg-surface border border-line`. `shadow-sm` only on floating things (modals, dropdowns, drag ghost).
- Max content width: lists `max-w-3xl`, focus card `max-w-xl`, calendar full-width.

## 3. Layout

**Desktop (≥1024px):** fixed left sidebar (w-60): logo/wordmark ("GTD" in display face), nav groups — *Capture* (Inbox), *Engage* (Today, This Week, This Month, Next Actions), *Organize* (Projects, Waiting For, Someday, Notes, Recurring, Tags), *Reflect* (Review, Stats), footer (Settings, Trash). Inbox item count as a mono pill; review-overdue turns the Review entry amber/red per §9.

**Mobile (<1024px):** bottom tab bar, 5 tabs: **Inbox · Today · ＋ · Calendar · Review**. The center ＋ is a raised circular `water` button opening quick capture. Everything else lives behind a "More" sheet from the Today header. Header is sticky, one line, back-arrow + title + single action.

**Global header (both):** persistent **trust strip** — right-aligned, mono, small: `inbox 4 · review 3d ago`. Colors follow §9 thresholds. This is the always-visible system-health readout; never remove it.

Touch targets ≥44px on mobile. Row actions that are hover-revealed on desktop become a swipe/long-press sheet on mobile — never hover-only.

## 4. Core components

Build each as a Django partial in `templates/components/`; reuse everywhere. Names below are the file names.

**`task_row.html`** — one line on desktop, two on mobile:
`[complete-circle] Title …badges… [context chips] [meta: due/block time, mono] [⋮]`
- Complete circle: 20px ring; hover fills `water`; click → HTMX PATCH, row fades out (150ms) then removes.
- Next-action markers (subtasks): filled `water` dot = flagged; hollow dot = implicit first-incomplete. Tooltip explains.
- Project rows: folder glyph + progress pill `3/7` (mono).
- ⋮ menu: Edit, Block time, Flag as next, Move to (Someday/Waiting/Trash), Convert to note.

**`badge.html`** — see vocabulary §6. Pill, 0.75rem, icon + short label.

**`chip.html`** — tag/context chips: `@context` in `water-soft`/`water` text, `#tag` in grey. Clickable = filter toggle; active state = solid fill.

**`focus_card.html`** — the signature: centered `max-w-xl` card, 2px progress bar top edge (`water`), step counter top-right (mono, `4/17`), large question in display face, 2–4 big option buttons (full-width, `h-12`, icon + label), muted helper line beneath. Keyboard: 1–4 select options, Enter confirms, Esc exits wizard (state saved).

**`empty_state.html`** — icon (line-style), one display-face line, one body line of GTD teaching (§9 copy), one primary action button. Never an empty white void.

**`filter_bar.html`** — horizontal scrollable chip row: contexts first (`@`), then tags, then horizon dropdown, area dropdown. Active filters solid; "clear" appears when any active.

**Buttons:** primary = solid `water` white text; secondary = `border-line` surface; destructive = red text ghost, solid red only inside confirm dialogs. Verbs as labels ("Add block", "Move to Someday"), never "OK/Submit".

**Toasts:** bottom-center, 3s, surface + border, icon-colored by kind. Every HTMX mutation gets one ("Moved to Someday", "Block created — Tue 14:00"). Include Undo where the action is reversible (complete, trash, move).

## 5. Key screens — specific instructions

**Inbox:** newest first, stripped rows (title + relative time, mono). Row actions: **Done** (2-min rule, checkmark button with tooltip "Under 2 minutes? Do it now") and **Clarify**. Top: "Process inbox →" primary button with count. Empty state: "Inbox zero." in display face + "Capture anything on your mind — filtering happens later."

**Capture (`/capture` & modal):** one autofocused input, huge (text-xl), placeholder "What's on your mind?". Description behind a "+ details" disclosure. Submit clears + refocuses with a 400ms `water` flash on the border — rapid-fire feel. Show last 3 captured below, faded.

**Clarify wizard:** focus card sequence per the decision tree (plan Step 4). The "Is it actionable?" screen shows the inbox item text quoted at top in a grey inset. Forms appear inside the same card. On finish: full-card "Inbox zero 🎉" moment — the one place celebration is allowed.

**Today:** two sections. *Today* (curated): Big-3 starred rows pinned first, then missed-block strip (red-tinted, "Reschedule" inline), then the rest ordered by block time then manual order. *Anytime — pick from here*: collapsed by default (chevron + count), context filter chips inside, rows show a "→ Today" quick action. Q2-chipped rows get a violet left border (2px).

**Project detail:** header (title, area, badges, complete button) → description → subtask list (drag handles, next-action dot toggles) → **Calendar time** panel: list of blocks (mono times, status-colored) + "Add block" opening the mini week view (§2 calendar colors) → activity footer (created, completed count). Stalled/`NEEDS_ATTENTION` states render as an amber banner *inside* the header with the two resolving actions inline ("Add next task" / "Mark project done").

**Calendar page:** FullCalendar week view, styled to tokens via CSS variable overrides in one `calendar.css` — kill FC's default theme borders; grid lines `line`, today column `water` at 4% tint. Drag-create shows a live-duration tooltip (mono).

**Eisenhower board (in review):** full-width step, 2×2 grid, axes labeled in small caps mono (URGENT →, IMPORTANT ↑). Quadrants: Q1 red-tinted 6%, Q2 violet 6%, Q3 amber 6%, Q4 grey 6%, each with its action subtitle ("Q2 — schedule it now"). Project cards: title + next-action line, drag with SortableJS; on drop, the card flips to its action UI (slot picker / delegate form / someday confirm) inline in the quadrant. Board is never shown outside the review wizard.

**Review wizard:** same focus-card chrome, but `max-w-2xl` for list-bearing steps. Phase header: "Get Clear · 1 of 3" in display face. A left dot-rail shows phases; completed dots fill `water`. Resumable state = returning shows "Resume review (started Fri 16:04)".

**Stats:** Chart.js, single accent color (`water`) — no multicolor charts. Streak shown as a display-face number with a mono label. No decoration.

**Settings:** plain stacked sections (Google, ntfy, Reviews, Capture tokens, Tags nag threshold). Connection states as labeled pills: `Connected · sudipto@…` (water) / `Not connected` (grey).

## 6. Badge vocabulary (closed set)

| Badge | Style | Meaning | Where |
|---|---|---|---|
| `↩ ×N` | amber pill | Carried over N times | Task rows, review queue |
| `⚠ ×N` | red pill | Missed N time blocks | Task rows, project cards |
| `overdue` | red pill, mono date | Recurring instance past occurrence / past due date | Today, Recurring |
| `waiting Nd` | grey pill, turns amber past follow-up threshold | Days waiting | Waiting For |
| `★` | star color, no pill | Big-3 this week | Everywhere the task renders |
| `Q2` | violet pill | Time-blocked as important-not-urgent, expires Sunday | Today/week lists |
| `stalled?` | amber pill | Project with no incomplete subtasks | Project cards |
| `no next →` | amber outline pill | Project has subtasks but none flagged next | Project cards |
| `3/7` | mono grey pill | Subtask progress | Project rows |

Do not add badges beyond this table without updating this file first.

## 7. Motion

Minimal and consistent: 150ms ease-out for row add/remove/fade, 200ms for card transitions in wizards (slide-up 8px + fade), no page-level animation, no spinners on HTMX swaps < 300ms (use `htmx-indicator` opacity pulse beyond that). Confetti/celebration only on inbox-zero and review-complete, and it's a single subtle burst, not looping. Respect `prefers-reduced-motion`: all transitions drop to opacity-only.

## 8. HTMX / Alpine / Tailwind conventions (hard rules)

1. **No build pipeline.** Tailwind standalone CLI, output committed. Because of purge: **never construct class names dynamically** (`bg-{{ color }}` is forbidden). Status→class maps live in a template tag returning full literal class strings; add any dynamic-ish classes to `safelist` in the config.
2. HTMX for all mutations; server returns partials. Full-page reloads only on navigation. `hx-boost` on nav links.
3. Alpine only for local UI state (disclosures, chip toggles, typeahead, keyboard shortcuts). No Alpine stores as data sources — server is truth.
4. One `components/` partial per §4 component; screens compose partials. If you're copy-pasting row markup between templates, stop and extract.
5. Icons: Lucide static SVGs vendored into `templates/icons/` and included via `{% include %}` — no icon font, no CDN.
6. Every interactive element keyboard-reachable with visible focus (`focus-visible:ring-2 ring-water`). Wizard keyboard map per §4.
7. Forms: labels above inputs, errors inline below the field in red text (never toast-only), submit buttons disabled while `htmx-request` in flight.
8. All dates/times displayed in Asia/Dhaka, mono face, formats: `Tue 14:00`, `12 Jul`, `12 Jul 2026` — pick the shortest unambiguous form.

## 9. Voice & GTD teaching copy

Register: plain, second person, sentence case, no exclamation marks except inbox-zero. The app sounds like a calm coach, not a cheerleader.

Fixed copy (use verbatim; source: the GTD study doc):

- Inbox empty: "Inbox zero." / "Capture anything on your mind — filtering happens later."
- Clarify helper: "What's the very next physical action? Something you could watch someone do."
- 2-min helper: "Under 2 minutes? Do it now — tracking it costs more than doing it."
- Someday empty: "Nothing parked. Someday/Maybe lets you *not* do things without losing them."
- Waiting empty: "Waiting on no one. Delegate something and track it here."
- Projects stalled banner: "No next action. A project without a next action is stalled by definition."
- Carried-over gate: "Decide, don't defer again: keep, demote, park, or drop."
- Review nag banner: "Your system is only trusted if it's current. Last review: {N} days ago."
- Contexts nag (>7): "Too many contexts turns the system into a hobby. Merge some?"

Trust-strip thresholds: review age ≤7d muted, 8–10d amber, >10d red; inbox count >20 amber.

Rotating "GTD tip" strip (dismissible, one per day, footer of Today): cycle the §8.1 pitfalls from the study doc as one-liners.

## 10. Quality floor (check before calling any screen done)

- Renders correctly at 375px and 1440px; no horizontal scroll at 375px.
- Loading, empty, and error states exist for every list and every HTMX action.
- Keyboard: tab order sane, focus visible, wizard shortcuts work.
- All literal Tailwind classes (grep for `{{` inside `class=`), safelist updated.
- Badges only from §6; colors only from §2.
- Toast + Undo present on complete/trash/move.
- Copy matches §9 where fixed; everything else follows the voice rules.
