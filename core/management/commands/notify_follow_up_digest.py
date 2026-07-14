from django.core.management.base import BaseCommand
from django.urls import reverse
from django.utils import timezone

from core.models import Task
from core.notifications import notify


class Command(BaseCommand):
    help = "Daily 09:00 batched digest: N Waiting-For items need a nudge (solution-plan.md Step 10)."

    def handle(self, *args, **options):
        today = timezone.localtime().date()
        overdue = [
            t
            for t in Task.objects.filter(list=Task.List.WAITING, completed_at__isnull=True)
            if t.waiting_since and (today - t.waiting_since).days >= t.follow_up_after_days
        ]
        count = len(overdue)
        sent = False
        if count:
            sent = notify(
                "follow_up_due",
                title="Waiting For follow-ups",
                message=f"{count} Waiting-For item{'s' if count != 1 else ''} need a nudge.",
                url=reverse("waiting"),
            )
        self.stdout.write(f"notify_follow_up_digest {today}: {count} overdue, sent={bool(sent)}")
