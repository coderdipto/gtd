from django.core.management.base import BaseCommand
from django.urls import reverse
from django.utils import timezone

from core.models import Task
from core.notifications import notify


class Command(BaseCommand):
    help = "Daily 09:00, count-based nag for overdue recurring instances (solution-plan.md Step 10)."

    def handle(self, *args, **options):
        today = timezone.localtime().date()
        count = Task.objects.filter(
            recurring_template__isnull=False, occurrence_date__lt=today, completed_at__isnull=True
        ).count()
        sent = False
        if count:
            sent = notify(
                "recurring_overdue",
                title="Recurring tasks overdue",
                message=f"{count} recurring task{'s' if count != 1 else ''} overdue.",
                url=reverse("recurring"),
            )
        self.stdout.write(f"notify_recurring_overdue {today}: {count} overdue, sent={bool(sent)}")
