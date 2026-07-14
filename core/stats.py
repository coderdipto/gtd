import json
import statistics
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone

from .models import InboxItem, ReviewConfig, ReviewSession, Task, TimeBlock

COMPLETIONS_DAYS = 30
COMPLETIONS_WEEKS = 12
MISSED_BLOCK_WEEKS = 4


def _completions_per_day(today):
    start = today - timedelta(days=COMPLETIONS_DAYS - 1)
    completions = list(
        Task.objects.filter(completed_at__date__gte=start, completed_at__date__lte=today).values_list(
            "completed_at", flat=True
        )
    )
    counts = {}
    for dt in completions:
        d = timezone.localtime(dt).date()
        counts[d] = counts.get(d, 0) + 1
    days = [start + timedelta(days=i) for i in range(COMPLETIONS_DAYS)]
    return [{"label": d.strftime("%d %b"), "count": counts.get(d, 0)} for d in days]


def _completions_per_week(today):
    current_monday = today - timedelta(days=today.weekday())
    start_monday = current_monday - timedelta(weeks=COMPLETIONS_WEEKS - 1)
    completions = list(
        Task.objects.filter(completed_at__date__gte=start_monday).values_list("completed_at", flat=True)
    )
    counts = {}
    for dt in completions:
        d = timezone.localtime(dt).date()
        monday = d - timedelta(days=d.weekday())
        counts[monday] = counts.get(monday, 0) + 1
    weeks = [start_monday + timedelta(weeks=i) for i in range(COMPLETIONS_WEEKS)]
    return [{"label": w.strftime("%d %b"), "count": counts.get(w, 0)} for w in weeks]


def _review_stats():
    rows = []
    for cadence, label in ReviewConfig.Cadence.choices:
        sessions = list(
            ReviewSession.objects.filter(cadence=cadence, completed_at__isnull=False).order_by("-completed_at")
        )
        rows.append(
            {
                "cadence": label,
                "streak": len(sessions),
                "last_completed": sessions[0].completed_at if sessions else None,
            }
        )
    return rows


def _inbox_zero_event_count():
    """Every time the running unprocessed-inbox count transitions from >0 to
    0, reconstructed from created_at/processed_at timestamps - no separate
    event log/denormalized table needed."""
    events = []
    for created_at, processed_at in InboxItem.objects.values_list("created_at", "processed_at"):
        events.append((created_at, 1))
        if processed_at:
            events.append((processed_at, -1))
    events.sort(key=lambda e: e[0])

    running = 0
    zero_events = 0
    for _when, delta in events:
        previous = running
        running += delta
        if previous > 0 and running == 0:
            zero_events += 1
    return zero_events


def _missed_block_rate(today):
    window_start = today - timedelta(weeks=MISSED_BLOCK_WEEKS)
    blocks = TimeBlock.objects.filter(start__date__gte=window_start).exclude(status=TimeBlock.Status.SCHEDULED)
    # SCHEDULED blocks are still pending (neither completed nor missed yet),
    # so they're excluded from both the numerator and denominator here.
    total = TimeBlock.objects.filter(start__date__gte=window_start).exclude(status=TimeBlock.Status.SCHEDULED).count()
    missed = blocks.filter(status=TimeBlock.Status.MISSED).count()
    return round(100 * missed / total) if total else None


def _median_capture_to_clarify_latency():
    deltas = []
    for created_at, processed_at in InboxItem.objects.filter(processed_at__isnull=False).values_list(
        "created_at", "processed_at"
    ):
        deltas.append((processed_at - created_at).total_seconds())
    if not deltas:
        return None
    return statistics.median(deltas)


def _format_seconds(total_seconds):
    if total_seconds is None:
        return "—"
    minutes = round(total_seconds / 60)
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    remaining_minutes = minutes % 60
    if hours < 24:
        return f"{hours}h {remaining_minutes}m" if remaining_minutes else f"{hours}h"
    days = hours // 24
    return f"{days}d"


@login_required
def stats_view(request):
    today = timezone.localtime().date()
    completions_per_day = _completions_per_day(today)
    completions_per_week = _completions_per_week(today)

    context = {
        "completions_per_day_json": json.dumps(completions_per_day),
        "completions_per_week_json": json.dumps(completions_per_week),
        "review_rows": _review_stats(),
        "inbox_zero_count": _inbox_zero_event_count(),
        "missed_block_rate": _missed_block_rate(today),
        "median_latency_label": _format_seconds(_median_capture_to_clarify_latency()),
        "two_minute_count": InboxItem.objects.filter(done_directly=True).count(),
    }
    return render(request, "core/stats.html", context)
