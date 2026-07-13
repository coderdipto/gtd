from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.google_calendar import get_credential, register_watch_channel
from core.models import SyncChannel


class Command(BaseCommand):
    help = "Daily: renew GCal watch channels expiring within 48h (solution-plan.md Step 8c)."

    def handle(self, *args, **options):
        credential = get_credential()
        if not credential:
            self.stdout.write("renew_gcal_channels: no Google credential connected, skipping")
            return

        threshold = timezone.now() + timedelta(hours=48)
        expiring = list(SyncChannel.objects.filter(calendar_id=credential.gtd_calendar_id, expiration__lt=threshold))
        for channel in expiring:
            register_watch_channel(credential, channel.calendar_id)
            channel.delete()
        self.stdout.write(f"renew_gcal_channels: renewed {len(expiring)} channel(s)")
