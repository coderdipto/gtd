import json
from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .google_calendar import GoogleCalendarClient, get_credential
from .models import Task, TimeBlock

BLOCK_COLORS = {"scheduled": "#BE5133", "completed": "#BE5133", "missed": "#B91C1C"}  # water/red (tailwind.config.js)


def blocks_json(blocks, title):
    # Feeds the mini FullCalendar in components/calendar_time_panel.html
    # (shared by project_detail.html and task_detail.html) via that
    # template's data-events="{{ blocks_json }}" attribute (deliberately NOT
    # |safe - same reasoning as field_tagged.html's tagTypeahead JSON:
    # Django's default auto-escaping must run so this string's own `"`
    # characters become &quot; and get decoded back by the HTML parser
    # before JS reads them, or the attribute value truncates at the first
    # one). json.dumps already handles proper string escaping of `title`,
    # which is free text.
    data = [
        {
            "title": title,
            "start": b.start.isoformat(),
            "end": b.end.isoformat(),
            "color": BLOCK_COLORS[b.status],
            "editable": False,
        }
        for b in blocks
    ]
    return json.dumps(data)


def _parse_local_datetime(value):
    """Parses an ISO string from a <input type=datetime-local> (naive, in
    the app's local Asia/Dhaka time per settings.TIME_ZONE) into an
    aware datetime, or a full ISO string with an offset/'Z' from FullCalendar's
    JS Date - fromisoformat handles both once 'Z' is normalized."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed)
    return parsed


def retitle_task_blocks(task):
    """'Completing a task retitles past+future events ✓ <title>, block
    status=COMPLETED, block persists' (solution-plan.md Step 7/8). No-op
    when Google Calendar isn't connected - blocks just aren't linked yet."""
    credential = get_credential()
    blocks = task.blocks.exclude(status=TimeBlock.Status.COMPLETED)
    if not blocks.exists():
        return
    client = GoogleCalendarClient(credential) if credential else None
    for block in blocks:
        if client and block.gcal_event_id:
            client.patch_event(credential.gtd_calendar_id, block.gcal_event_id, {"summary": f"✓ {task.title}"})
        block.status = TimeBlock.Status.COMPLETED
        block.save(update_fields=["status"])


@login_required
def calendar_page(request):
    return render(request, "core/calendar.html", {"credential": get_credential()})


@login_required
def calendar_events_json(request):
    """FullCalendar's `events` source for the week view: our TimeBlocks (as
    real events) plus the primary calendar's busy events fetched live for
    display only - solution-plan.md Step 8 is explicit these are never
    persisted, so they're not stored anywhere, only returned in this response."""
    events = []
    for block in TimeBlock.objects.select_related("task"):
        color = BLOCK_COLORS[block.status]
        detail_url_name = "project_detail" if block.task.is_project else "task_detail"
        events.append(
            {
                "id": f"block-{block.id}",
                "title": block.task.title,
                "start": block.start.isoformat(),
                "end": block.end.isoformat(),
                "backgroundColor": color,
                "editable": block.status == TimeBlock.Status.SCHEDULED,
                "extendedProps": {"detailUrl": reverse(detail_url_name, args=[block.task_id])},
            }
        )

    credential = get_credential()
    if credential:
        client = GoogleCalendarClient(credential)
        try:
            result = client.list_events(credential.primary_calendar_id)
            for item in result.get("items", []):
                start = item.get("start", {}).get("dateTime")
                end = item.get("end", {}).get("dateTime")
                if not start or not end:
                    continue
                events.append(
                    {
                        "title": item.get("summary", "Busy"),
                        "start": start,
                        "end": end,
                        "backgroundColor": "#9CA3AF",
                        "editable": False,
                    }
                )
        except Exception:
            pass  # primary calendar is a display-only nicety, never block the page on it

    return JsonResponse(events, safe=False)


@login_required
@require_POST
def timeblock_create(request, task_pk):
    task = get_object_or_404(Task, pk=task_pk)
    try:
        start = _parse_local_datetime(request.POST["start"])
        end = _parse_local_datetime(request.POST["end"])
    except (KeyError, ValueError):
        return HttpResponseBadRequest("start/end must be ISO datetimes")

    block = TimeBlock.objects.create(task=task, start=start, end=end)

    credential = get_credential()
    if credential:
        client = GoogleCalendarClient(credential)
        body = {
            "summary": task.title,
            "start": {"dateTime": start.isoformat()},
            "end": {"dateTime": end.isoformat()},
        }
        result = client.insert_event(credential.gtd_calendar_id, body)
        block.gcal_event_id = result.get("id", "")
        block.gcal_etag = result.get("etag", "")
        block.save(update_fields=["gcal_event_id", "gcal_etag"])

    # The Today "Plan on calendar" drag (task #17) calls this via htmx.ajax and
    # stays on the page — it just refetches the calendar afterward, so it wants
    # an empty body, not a navigation. Detect that by the HX-Request header and
    # return 204. Everything else here is a plain <form method=post>
    # (project_detail.html's "Add block"), which <body hx-boost="true">
    # AJAX-intercepts and expects a redirect (or real HTML) back — a raw
    # JsonResponse would otherwise get swapped in as literal `{"id": 1}` text
    # with that URL pushed into the address bar.
    if request.headers.get("HX-Request") == "true":
        return HttpResponse(status=204)
    if task.is_project:
        return redirect("project_detail", pk=task.id)
    return redirect("task_detail", pk=task.id)


@login_required
@require_POST
def timeblock_update(request, pk):
    """Drag/resize on the calendar page - patches start/end."""
    block = get_object_or_404(TimeBlock, pk=pk)
    try:
        block.start = _parse_local_datetime(request.POST["start"])
        block.end = _parse_local_datetime(request.POST["end"])
    except (KeyError, ValueError):
        return HttpResponseBadRequest("start/end must be ISO datetimes")
    block.save(update_fields=["start", "end"])

    credential = get_credential()
    if credential and block.gcal_event_id:
        client = GoogleCalendarClient(credential)
        client.patch_event(
            credential.gtd_calendar_id,
            block.gcal_event_id,
            {"start": {"dateTime": block.start.isoformat()}, "end": {"dateTime": block.end.isoformat()}},
        )
    return HttpResponse("")


@login_required
@require_POST
def timeblock_delete(request, pk):
    block = get_object_or_404(TimeBlock, pk=pk)
    task = block.task
    credential = get_credential()
    if credential and block.gcal_event_id:
        client = GoogleCalendarClient(credential)
        client.delete_event(credential.gtd_calendar_id, block.gcal_event_id)
    block.delete()
    # Same boosted-plain-form issue as timeblock_create above: an empty
    # HttpResponse("") swapped in by hx-boost leaves the page blank at this
    # URL instead of returning to the project/task it came from.
    if task.is_project:
        return redirect("project_detail", pk=task.id)
    return redirect("task_detail", pk=task.id)
