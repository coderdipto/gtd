from django.utils import timezone

from .models import InboxItem, ReviewSession, Task


def trust_strip(request):
    """Global header trust strip (docs/design.md §3) - always-visible system
    health readout. A context processor so every template gets it without
    every view needing to pass it explicitly."""
    if not request.user.is_authenticated:
        return {}
    inbox_count = InboxItem.objects.filter(processed_at__isnull=True).count()

    last_weekly = (
        ReviewSession.objects.filter(cadence="weekly", completed_at__isnull=False)
        .order_by("-completed_at")
        .first()
    )
    review_age_days = (timezone.localtime().date() - last_weekly.completed_at.date()).days if last_weekly else None

    # Active projects feed the command palette's per-project jump entries
    # (task-follow-up). Kept small (id/title only) since it runs on every page.
    palette_projects = list(
        Task.objects.filter(is_project=True, completed_at__isnull=True)
        .exclude(list=Task.List.TRASH)
        .order_by("title")
        .values("id", "title")
    )

    return {
        "inbox_count": inbox_count,
        "review_age_days": review_age_days,
        "palette_projects": palette_projects,
    }
