from datetime import datetime, time, timedelta

from dateutil.rrule import rrulestr
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.dateparse import parse_date

from core.models import RecurringTemplate, Task

MATERIALIZE_HORIZON_DAYS = 14


class Command(BaseCommand):
    help = (
        "Materialize recurring Task instances (docs/solution-plan.md Step 7): for each "
        "active RecurringTemplate, generate occurrences from last_materialized_until "
        "through today + 14 days. Registered as an hourly cron job in Epic 12."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--as-of", type=str, default=None, help="Synthetic date (YYYY-MM-DD), for testing."
        )

    def handle(self, *args, **options):
        as_of = parse_date(options["as_of"]) if options["as_of"] else timezone.localtime().date()
        window_end = as_of + timedelta(days=MATERIALIZE_HORIZON_DAYS)

        total = 0
        for template in RecurringTemplate.objects.filter(active=True):
            total += self._materialize_one(template, as_of, window_end)
        self.stdout.write(f"materialize_recurring {as_of}: {total} instance(s) created")

    def _materialize_one(self, template, as_of, window_end):
        # First-ever run for a template has no last_materialized_until yet -
        # anchor the window (and the RRULE's dtstart) at "yesterday" so today
        # itself is included.
        anchor = template.last_materialized_until or (as_of - timedelta(days=1))
        window_start = anchor + timedelta(days=1)
        if window_start > window_end:
            return 0

        rule = rrulestr(f"RRULE:{template.rrule}", dtstart=datetime.combine(anchor, time.min))
        occurrences = rule.between(
            datetime.combine(window_start, time.min),
            datetime.combine(window_end, time.min),
            inc=True,
        )

        created = 0
        for occ in occurrences:
            occurrence_date = occ.date()
            _, was_created = Task.objects.get_or_create(
                recurring_template=template,
                occurrence_date=occurrence_date,
                defaults={
                    "title": template.title,
                    "description": template.description,
                    "list": Task.List.NEXT,
                    "horizon": Task.Horizon.TODAY if occurrence_date <= as_of else Task.Horizon.ANYTIME,
                    "area": template.area,
                },
            )
            if was_created:
                created += 1

        template.last_materialized_until = window_end
        template.save(update_fields=["last_materialized_until"])
        return created
