import markdown as _markdown
from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def markdownify(text):
    """Renders Note.body markdown to HTML (docs/task-breakdown.md Epic 6).
    Single-user, self-hosted system - no HTML sanitization pass, since the
    only author of this content is the same person viewing it."""
    return mark_safe(_markdown.markdown(text or "", extensions=["extra", "nl2br"]))

# Status/badge -> class-string map (docs/design.md §6/§8.1): kept here as a
# closed set of full literal Tailwind class strings, never assembled by
# concatenating request/model data into a class name. Because these literal
# tokens live in a .py file rather than a .html one, tailwind.config.js's
# `content` list includes this templatetags directory so its regex-based
# scanner still finds them (see the config's `content` array).
_PILL = "inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-mono"
_OUTLINE_PILL = "inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-mono border bg-transparent"

_BADGE_CLASSES = {
    "carried_over": f"{_PILL} bg-amber-bg text-amber",
    "missed": f"{_PILL} bg-red-bg text-red",
    "overdue": f"{_PILL} bg-red-bg text-red",
    "waiting": f"{_PILL} bg-line text-ink-soft",
    "waiting_due": f"{_PILL} bg-amber-bg text-amber",
    "q2": f"{_PILL} bg-violet-bg text-violet",
    "stalled": f"{_PILL} bg-amber-bg text-amber",
    "no_next": f"{_OUTLINE_PILL} border-amber text-amber",
    "progress": f"{_PILL} bg-line text-ink-soft",
    "big3": "text-star",
}


@register.inclusion_tag("components/badge.html")
def badge(kind, n=None, text=None, overdue=False):
    """Renders one of the closed badge vocabulary (docs/design.md §6).
    kind: carried_over|missed|overdue|waiting|q2|stalled|no_next|progress|big3
    """
    classes = _BADGE_CLASSES["waiting_due" if (kind == "waiting" and overdue) else kind]
    labels = {
        "carried_over": f"↩ ×{n}",
        "missed": f"⚠ ×{n}",
        "overdue": text or "overdue",
        "waiting": f"waiting {n}d",
        "q2": "Q2",
        "stalled": "stalled?",
        "no_next": "no next →",
        "progress": text,
        "big3": "★",
    }
    return {"classes": classes, "label": labels[kind]}


@register.filter
def get_item(mapping, key):
    """Dict lookup by variable key - Django's `.` lookup only works with
    literal keys in templates, so per-row meta/marker dicts need this."""
    return mapping.get(key) if mapping else None
