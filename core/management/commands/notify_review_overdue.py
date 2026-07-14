from django.core.management.base import BaseCommand
from django.urls import reverse
from django.utils import timezone

from core.models import ReviewConfig, ReviewSession
from core.notifications import notify

# Deadlines per cadence day-count (solution-plan.md Step 10: "weekly: end of
# the scheduled day" - approximated here as N days since the last completed
# session, consistent with the trust-strip's own review_age_days logic).
CADENCE_OVERDUE_DAYS = {"weekly": 7, "monthly": 31, "quarterly": 93, "yearly": 365}


class Command(BaseCommand):
    help = "Daily 09:00: nag once per day if a configured cadence's review is overdue (solution-plan.md Step 10)."

    def handle(self, *args, **options):
        today = timezone.localtime().date()
        sent = 0
        for cadence, threshold_days in CADENCE_OVERDUE_DAYS.items():
            if not ReviewConfig.objects.filter(cadence=cadence).exists():
                continue  # not configured - nothing to enforce for this cadence
            last = (
                ReviewSession.objects.filter(cadence=cadence, completed_at__isnull=False)
                .order_by("-completed_at")
                .first()
            )
            age_days = (today - last.completed_at.date()).days if last else None
            if age_days is not None and age_days <= threshold_days:
                continue
            label = f"{age_days} days" if age_days is not None else "never done"
            was_sent = notify(
                f"review_overdue_{cadence}",
                title=f"{cadence.capitalize()} review overdue",
                message=f"{cadence.capitalize()} review overdue ({label}).",
                url=reverse("review_dashboard"),
                priority="high",
            )
            if was_sent:
                sent += 1
        self.stdout.write(f"notify_review_overdue {today}: {sent} sent")
