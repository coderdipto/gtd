from django.core.management.base import BaseCommand
from django.db.models import F
from django.utils import timezone
from django.utils.dateparse import parse_date

from core.models import Task


class Command(BaseCommand):
    help = (
        "Nightly horizon carry-over (docs/solution-plan.md Step 5, Decision #15): "
        "increments carried_over_count on incomplete tasks whose horizon window "
        "just rolled over. Registered as a cron job in Epic 12; this is just the logic."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--as-of",
            type=str,
            default=None,
            help="Synthetic date (YYYY-MM-DD) to run as-of, for testing.",
        )

    def handle(self, *args, **options):
        as_of = parse_date(options["as_of"]) if options["as_of"] else timezone.localtime().date()

        today_n = self._carry_over(Task.Horizon.TODAY)
        week_n = self._carry_over(Task.Horizon.WEEK) if as_of.weekday() == 0 else 0
        month_n = self._carry_over(Task.Horizon.MONTH) if as_of.day == 1 else 0

        self.stdout.write(
            f"rollover {as_of}: today +{today_n}, this_week +{week_n}, this_month +{month_n}"
        )

    def _carry_over(self, horizon):
        return Task.objects.filter(horizon=horizon, completed_at__isnull=True).update(
            carried_over_count=F("carried_over_count") + 1
        )
