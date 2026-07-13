from django.core.management.base import BaseCommand

from core.google_calendar import get_credential, sync_calendar


class Command(BaseCommand):
    help = (
        "15-minute polling fallback for two-way GCal sync (solution-plan.md Step 8c) - "
        "runs regardless of whether webhooks are working, since they aren't guaranteed."
    )

    def handle(self, *args, **options):
        credential = get_credential()
        if not credential:
            self.stdout.write("sync_gcal: no Google credential connected, skipping")
            return
        count = sync_calendar(credential)
        self.stdout.write(f"sync_gcal: processed {count} event(s)")
