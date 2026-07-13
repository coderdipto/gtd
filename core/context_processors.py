from django.utils import timezone

from .models import InboxItem, ReviewSession


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

    return {"inbox_count": inbox_count, "review_age_days": review_age_days}
