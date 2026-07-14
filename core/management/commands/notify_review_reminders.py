from datetime import datetime, time as dtime, timedelta

from dateutil.rrule import rrulestr
from django.core.management.base import BaseCommand
from django.urls import reverse
from django.utils import timezone

from core.models import ReviewConfig
from core.notifications import notify
from core.reviews import CADENCE_WEEKDAY_RRULE


class Command(BaseCommand):
    help = "T-15min reminder before each scheduled review, run frequently (solution-plan.md Step 10)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--now", type=str, default=None, help="Synthetic ISO datetime override, for testing."
        )

    def handle(self, *args, **options):
        now = datetime.fromisoformat(options["now"]) if options["now"] else timezone.localtime()
        if timezone.is_naive(now):
            now = timezone.make_aware(now)
        today = now.date()

        sent = 0
        for config in ReviewConfig.objects.all():
            if not self._scheduled_today(config, today):
                continue
            scheduled = datetime.combine(today, config.time)
            if timezone.is_naive(scheduled):
                scheduled = timezone.make_aware(scheduled)
            window_start = scheduled - timedelta(minutes=15)
            if not (window_start <= now < scheduled):
                continue
            was_sent = notify(
                "review_reminder",
                title=f"{config.get_cadence_display()} review in 15 minutes",
                message=f"Your {config.get_cadence_display().lower()} review is scheduled for {config.time.strftime('%H:%M')}.",
                url=reverse("review_dashboard"),
                ref_id=config.id,
            )
            if was_sent:
                sent += 1
        self.stdout.write(f"notify_review_reminders {now}: {sent} sent")

    def _scheduled_today(self, config, today):
        rrule_str = CADENCE_WEEKDAY_RRULE[config.cadence](config)
        rule = rrulestr(f"RRULE:{rrule_str}", dtstart=datetime.combine(today, dtime.min))
        occurrence = rule.after(datetime.combine(today, dtime.min), inc=True)
        return bool(occurrence and occurrence.date() == today)
