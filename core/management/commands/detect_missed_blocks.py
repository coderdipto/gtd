from django.core.management.base import BaseCommand
from django.db.models import F
from django.utils import timezone

from core.models import Task, TimeBlock


class Command(BaseCommand):
    help = (
        "Every 15 min: TimeBlocks past their end, still SCHEDULED, whose task is "
        "incomplete -> MISSED (solution-plan.md Step 8d)."
    )

    def handle(self, *args, **options):
        now = timezone.now()
        blocks = list(
            TimeBlock.objects.filter(
                end__lt=now, status=TimeBlock.Status.SCHEDULED, task__completed_at__isnull=True
            )
        )
        for block in blocks:
            block.status = TimeBlock.Status.MISSED
            block.save(update_fields=["status"])
            Task.objects.filter(pk=block.task_id).update(missed_block_count=F("missed_block_count") + 1)
            _notify_missed_block(block)
        self.stdout.write(f"detect_missed_blocks {now}: {len(blocks)} block(s) marked missed")


def _notify_missed_block(block):
    # Real ntfy dispatch is Epic 10's notify() helper - this is the wiring
    # point so that epic only has to fill in the body, not hunt for call sites.
    pass
