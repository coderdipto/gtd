"""Natural-language date parsing for capture text (docs task #14).

A deliberately *small*, dependency-free parser — same spirit as the hand-rolled
RRULE assembly in core/recurring.py (we already avoid a heavyweight builder
there). It recognizes a documented, conservative vocabulary of relative-date
phrases so that a well-formed capture like "Call plumber tomorrow 3pm" can
pre-fill the due date on the clarify Single-action screen, with the temporal
phrase stripped from the title. It is intentionally NOT a general parser: it
only matches explicit relative words and weekday names as whole tokens, so it
won't misread arbitrary numbers or nouns as dates. Anything it pre-fills is
shown in an editable form field, so an over-eager match is a correctable
inconvenience, never a silent data change.

Deliberate v1 limitations (documented rather than silently swallowed):
- A parsed clock time ("3pm") is used only to strip the token from the title;
  the Task's due_date is date-only, so the time itself is discarded. Actual
  time-blocking stays the separate calendar step.
- Matching is anchored to the END of the text (where a trailing "… tomorrow"
  naturally lands), which also keeps it from eating date-like words that are
  really part of the subject ("Monday.com renewal").
"""

import re
from dataclasses import dataclass
from datetime import date, time, timedelta

WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}

# A clock time: "3pm", "3:30pm", "11am", "at 9 pm". Captured optionally so a
# phrase like "tomorrow 3pm" strips as a unit.
_TIME = r"(?:\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm))?"

# Each date phrase is anchored to end-of-string (with the optional trailing
# time) so it only fires on a genuine trailing temporal clause.
_PATTERNS = [
    ("today", re.compile(r"\btoday" + _TIME + r"\s*$", re.I)),
    ("tonight", re.compile(r"\btonight" + _TIME + r"\s*$", re.I)),
    ("tomorrow", re.compile(r"\b(?:tomorrow|tmrw)" + _TIME + r"\s*$", re.I)),
    ("in_days", re.compile(r"\bin\s+(\d{1,2})\s+days?" + _TIME + r"\s*$", re.I)),
    ("next_week", re.compile(r"\bnext\s+week" + _TIME + r"\s*$", re.I)),
    ("weekday", re.compile(
        r"\b(next\s+)?(" + "|".join(WEEKDAYS) + r")" + _TIME + r"\s*$", re.I)),
]


@dataclass
class ParsedCapture:
    cleaned_title: str      # title with the temporal phrase removed
    due_date: date | None   # None when nothing matched
    parsed_time: time | None
    matched_text: str | None


def _time_from(groups):
    """Build a datetime.time from an (hour, minute, ampm) regex tail, or None."""
    hour, minute, ampm = groups
    if not hour or not ampm:
        return None
    h = int(hour) % 12
    if ampm.lower() == "pm":
        h += 12
    return time(h, int(minute or 0))


def _weekday_date(today, target_wd, is_next):
    ahead = (target_wd - today.weekday()) % 7
    if ahead == 0:
        ahead = 7  # a bare weekday name means the next such day, not today
    if is_next:
        ahead += 7
    return today + timedelta(days=ahead)


def parse_capture(text, today=None):
    """Parse a trailing relative-date phrase out of `text`.

    Returns a ParsedCapture. When nothing matches, due_date is None and
    cleaned_title is the original text unchanged.
    """
    today = today or date.today()
    for kind, pattern in _PATTERNS:
        m = pattern.search(text)
        if not m:
            continue

        if kind == "today":
            due = today
            t = _time_from(m.groups())
        elif kind == "tonight":
            due = today
            t = _time_from(m.groups()) or time(20, 0)
        elif kind == "tomorrow":
            due = today + timedelta(days=1)
            t = _time_from(m.groups())
        elif kind == "in_days":
            due = today + timedelta(days=int(m.group(1)))
            t = _time_from(m.groups()[1:])
        elif kind == "next_week":
            due = today + timedelta(days=7)
            t = _time_from(m.groups())
        else:  # weekday
            is_next = bool(m.group(1))
            due = _weekday_date(today, WEEKDAYS[m.group(2).lower()], is_next)
            t = _time_from(m.groups()[2:])

        cleaned = text[: m.start()].rstrip(" ,-—")
        return ParsedCapture(
            cleaned_title=cleaned or text.strip(),
            due_date=due,
            parsed_time=t,
            matched_text=m.group(0).strip(),
        )

    return ParsedCapture(cleaned_title=text.strip(), due_date=None, parsed_time=None, matched_text=None)


def horizon_for_date(due, today=None):
    """Map a due date onto a Task.Horizon value ("today"/"this_week"/…).

    Returned as the raw string so callers (clarify) don't need to import the
    model here. "this week" runs through the coming Sunday; "this month" is the
    remainder of the current calendar month; anything further is "anytime".
    """
    today = today or date.today()
    if due <= today:
        return "today"
    end_of_week = today + timedelta(days=(6 - today.weekday()))
    if due <= end_of_week:
        return "this_week"
    if due.year == today.year and due.month == today.month:
        return "this_month"
    return "anytime"
